#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Client for the wildcard predict-api relayer proxy (CLOB v2).

Under CLOB v2 the legacy Safe-funder relayer
(``relayer-v2.polymarket.com``) is replaced by a sibling **DepositWallet
(DW)** that funds the CLOB. The DW is owned by the agent EOA and is
provisioned / driven through wildcard's predict-api proxy, which holds the
Verified-tier Builder key. A direct-to-Polymarket path is not viable: that
credential cannot ship in a desktop client.

The wire format below is the contract empirically verified against the live
proxy (``mpp.valory.xyz``) during the CLOB v2 migration validation
(grandfathered-Polystrat e2e, probes 21-24).

Endpoints (all under ``{base_url}/polymarket/relayer/``)::

    POST /deploy_dw          {type: "WALLET-CREATE", from, to: <DW factory>}
                             -> {"transactionID": <id>, "state": "STATE_NEW"}
    POST /exec_wallet_batch  {from, to: <DW factory>, nonce, signature,
                              depositWalletParams: {depositWallet, deadline,
                              calls: [{target, value, data}]}}
                             -> {"transactionID": <id>, ...}
    GET  /deployed?address=<addr>&type=WALLET  -> {"deployed": <bool>}
    GET  /transaction?id=<id>
                 -> {"state": "STATE_MINED", "transactionHash": "0x..."}

``exec_wallet_batch`` relays a DepositWallet ``execute(Batch, sig)`` call;
the DW's ``execute`` is ``onlyFactory``, so the relayer (not the owner)
submits it. The batch is an EIP-712 ``Batch`` envelope over the
``DepositWallet`` / ``1`` / chainId domain, signed by the agent EOA as a
plain 65-byte owner ECDSA. The owner's DW ``nonce()`` must be read on-chain
and passed in for replay protection.

Every call is authenticated with the wildcard challenge

    wildcard-relayer:v2:{from}:{full_path}:{ts_ms}:{nonce}

signed by the agent EOA (EIP-191 ``personal_sign``), presented in the
``X-Wallet-Signature`` / ``X-Wallet-Timestamp`` / ``X-Wallet-Nonce`` headers.
"""

import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_checksum_address

CHALLENGE_PREFIX = "wildcard-relayer:v2"
PROXY_REQUEST_TIMEOUT = 30
RELAYER_PATH_PREFIX = "/polymarket/relayer"

# Polymarket DepositWallet factory on Polygon. All relayer mutations target
# the factory (which dispatches to the per-owner DW), never the DW directly.
DW_FACTORY = to_checksum_address("0x00000000000Fb5C9ADea0298D729A0CB3823Cc07")

# Relayer transaction states (GET /transaction). MINED/CONFIRMED are terminal
# success; FAILED/INVALID are terminal failure; anything else is in-flight.
TX_STATE_MINED = "STATE_MINED"
TX_STATE_CONFIRMED = "STATE_CONFIRMED"
TX_STATE_FAILED = "STATE_FAILED"
TX_STATE_INVALID = "STATE_INVALID"
TX_TERMINAL_OK = (TX_STATE_MINED, TX_STATE_CONFIRMED)
TX_TERMINAL_FAIL = (TX_STATE_FAILED, TX_STATE_INVALID)
TX_TERMINAL_STATES = TX_TERMINAL_OK + TX_TERMINAL_FAIL

# EIP-712 typehashes for the DepositWallet ``Batch`` envelope.
_EIP712_DOMAIN_TYPEHASH = keccak(
    text=(
        "EIP712Domain(string name,string version,uint256 chainId,"
        "address verifyingContract)"
    )
)
_CALL_TYPEHASH = keccak(text="Call(address target,uint256 value,bytes data)")
_BATCH_TYPEHASH = keccak(
    text=(
        "Batch(address wallet,uint256 nonce,uint256 deadline,Call[] calls)"
        "Call(address target,uint256 value,bytes data)"
    )
)
_DW_DOMAIN_NAME_HASH = keccak(text="DepositWallet")
_DW_DOMAIN_VERSION_HASH = keccak(text="1")
# Calls are always value-0 (token transfers / approvals carry no native value).
_CALL_VALUE = 0
# Batch validity window from build time.
_BATCH_DEADLINE_SECONDS = 3600


class RelayerProxyError(Exception):
    """Raised when the relayer proxy returns an error or an unusable response."""


class RelayerProxyClient:
    """HTTP client for the wildcard predict-api relayer proxy.

    Beyond the signer the client is stateless; each method issues one
    challenge-authenticated HTTP request. Polling of relayer-submitted
    transactions is driven by the caller so the connection worker thread is
    never blocked for the full settlement window.
    """

    def __init__(
        self,
        base_url: str,
        private_key: str,
        chain_id: int,
        logger: Any,
    ) -> None:
        """Initialize the proxy client.

        :param base_url: predict-api proxy base URL (no trailing slash needed).
        :param private_key: agent EOA private key (hex, with or without 0x).
        :param chain_id: EVM chain id (137 for Polygon).
        :param logger: logger to emit diagnostics through.
        """
        self.base_url = base_url.rstrip("/")
        self.chain_id = chain_id
        self.logger = logger
        self._account = Account.from_key(private_key)

    @property
    def address(self) -> str:
        """Return the checksummed agent EOA used as the relayer ``from``."""
        return self._account.address

    def _path(self, endpoint: str) -> str:
        """Return the relayer path component (challenge + URL share this)."""
        return f"{RELAYER_PATH_PREFIX}/{endpoint}"

    def _url(self, endpoint: str) -> str:
        """Build the full proxy URL for a relayer endpoint."""
        return f"{self.base_url}{self._path(endpoint)}"

    def _auth_headers(self, path: str) -> Dict[str, str]:
        """Build challenge-auth headers for a relayer request.

        The signed challenge binds the caller, the full request path, a
        millisecond timestamp and a single-use nonce, so a captured header
        cannot be replayed against a different endpoint or after expiry.

        :param path: the full relayer path being authenticated
            (e.g. ``/polymarket/relayer/exec_wallet_batch``).
        :return: the X-Wallet-* auth headers.
        """
        ts = str(int(time.time() * 1000))
        nonce = secrets.token_hex(16)
        challenge = f"{CHALLENGE_PREFIX}:{self.address}:{path}:{ts}:{nonce}"
        signature = self._account.sign_message(
            encode_defunct(text=challenge)
        ).signature.hex()
        signature = signature if signature.startswith("0x") else f"0x{signature}"
        return {
            "X-Wallet-Signature": signature,
            "X-Wallet-Timestamp": ts,
            "X-Wallet-Nonce": nonce,
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Issue one challenge-authenticated request and return parsed JSON.

        The parsed body is a dict for most endpoints but a *list* for
        ``GET /transaction`` (per the live proxy), so the return type is broad.

        :param method: ``"GET"`` or ``"POST"``.
        :param endpoint: relayer endpoint name (the path component).
        :param params: optional query parameters.
        :param json_body: optional JSON body for POST requests.
        :return: the parsed JSON response body.
        :raises RelayerProxyError: on transport error, non-2xx status, or
            non-JSON body.
        """
        path = self._path(endpoint)
        headers = self._auth_headers(path)
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = requests.request(
                method,
                self.base_url + path,
                params=params,
                json=json_body,
                headers=headers,
                timeout=PROXY_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise RelayerProxyError(
                f"Relayer proxy {method} {endpoint} failed: {e}"
            ) from e
        except ValueError as e:
            raise RelayerProxyError(
                f"Relayer proxy {method} {endpoint} returned non-JSON: {e}"
            ) from e

    def deployed(self, address: str, wallet_type: str = "WALLET") -> bool:
        """Return whether a DepositWallet is registered for ``address``.

        :param address: the DW address to check.
        :param wallet_type: relayer wallet type discriminator.
        :return: ``True`` once the relayer's registry has indexed the DW.
        """
        data = self._request(
            "GET",
            "deployed",
            params={"address": to_checksum_address(address), "type": wallet_type},
        )
        return bool(data.get("deployed"))

    def deploy_dw(self) -> str:
        """Deploy a DepositWallet owned by the agent EOA.

        :return: the relayer transaction id to poll via :meth:`transaction`.
        """
        body = {
            "type": "WALLET-CREATE",
            "from": self.address,
            "to": DW_FACTORY,
        }
        data = self._request("POST", "deploy_dw", json_body=body)
        tx_id = data.get("transactionID")
        if not tx_id:
            raise RelayerProxyError(f"deploy_dw returned no transaction id: {data}")
        return str(tx_id)

    def exec_wallet_batch(
        self,
        dw_address: str,
        nonce: int,
        calls: List[Dict[str, Any]],
        deadline: Optional[int] = None,
    ) -> str:
        """Relay a DepositWallet ``execute(Batch, sig)`` of ``calls``.

        Builds and owner-signs the EIP-712 ``Batch`` envelope, then POSTs it
        for the relayer to submit (the DW ``execute`` is ``onlyFactory``).

        :param dw_address: the DepositWallet to execute from.
        :param nonce: the DW's current ``nonce()`` (read on-chain by caller).
        :param calls: list of ``{"target": <addr>, "data": <0x hex>}`` calls
            (each implicitly value 0).
        :param deadline: unix-seconds batch validity bound; defaults to
            ``now + 3600``.
        :return: the relayer transaction id to poll via :meth:`transaction`.
        """
        dw_address = to_checksum_address(dw_address)
        if deadline is None:
            deadline = int(time.time()) + _BATCH_DEADLINE_SECONDS
        signature = self._sign_batch(dw_address, nonce, deadline, calls)
        body = {
            "from": self.address,
            "to": DW_FACTORY,
            "nonce": str(nonce),
            "signature": signature,
            "depositWalletParams": {
                "depositWallet": dw_address,
                "deadline": str(deadline),
                "calls": [
                    {
                        "target": to_checksum_address(c["target"]),
                        "value": "0",
                        "data": _as_0x(c["data"]),
                    }
                    for c in calls
                ],
            },
        }
        data = self._request("POST", "exec_wallet_batch", json_body=body)
        tx_id = data.get("transactionID")
        if not tx_id:
            raise RelayerProxyError(
                f"exec_wallet_batch returned no transaction id: {data}"
            )
        return str(tx_id)

    def _sign_batch(
        self,
        dw_address: str,
        nonce: int,
        deadline: int,
        calls: List[Dict[str, Any]],
    ) -> str:
        """Build and owner-sign the EIP-712 DepositWallet ``Batch`` digest.

        :param dw_address: the DW (EIP-712 ``verifyingContract`` and wallet).
        :param nonce: the DW's current nonce.
        :param deadline: unix-seconds validity bound.
        :param calls: the ``{"target", "data"}`` calls.
        :return: the 0x-prefixed 65-byte owner ECDSA signature.
        """
        domain_separator = keccak(
            abi_encode(
                ["bytes32", "bytes32", "bytes32", "uint256", "address"],
                [
                    _EIP712_DOMAIN_TYPEHASH,
                    _DW_DOMAIN_NAME_HASH,
                    _DW_DOMAIN_VERSION_HASH,
                    self.chain_id,
                    dw_address,
                ],
            )
        )
        call_hashes = b"".join(
            keccak(
                abi_encode(
                    ["bytes32", "address", "uint256", "bytes32"],
                    [
                        _CALL_TYPEHASH,
                        to_checksum_address(c["target"]),
                        _CALL_VALUE,
                        keccak(_to_bytes(c["data"])),
                    ],
                )
            )
            for c in calls
        )
        struct_hash = keccak(
            abi_encode(
                ["bytes32", "address", "uint256", "uint256", "bytes32"],
                [_BATCH_TYPEHASH, dw_address, nonce, deadline, keccak(call_hashes)],
            )
        )
        digest = keccak(b"\x19\x01" + domain_separator + struct_hash)
        signature = Account._sign_hash(  # noqa: SLF001
            digest, self._account.key
        ).signature.hex()
        return _as_0x(signature)

    def transaction(self, tx_id: str) -> Tuple[str, Optional[str]]:
        """Fetch the state of a relayer-submitted transaction.

        The proxy's ``GET /transaction`` returns a *list* of matching records
        (verified against the live API); only the entry whose ``transactionID``
        equals ``tx_id`` is selected, or a bare dict is accepted defensively.

        :param tx_id: the relayer transaction id returned by a POST call.
        :return: ``(state, tx_hash)`` where ``state`` is one of the relayer
            states (terminal: ``STATE_MINED`` / ``STATE_CONFIRMED`` ok,
            ``STATE_FAILED`` / ``STATE_INVALID`` fail) and ``tx_hash`` is the
            mined hash when available. An absent ``tx_id`` yields ``("", None)``
            (non-terminal) so the caller keeps polling rather than binding an
            unrelated transaction's state.
        """
        data = self._request("GET", "transaction", params={"id": tx_id})
        if isinstance(data, list):
            # Never fall back to an arbitrary record: a wrong match could bind
            # the wrong DW address / tx hash. Absent id → empty (non-terminal).
            record = next(
                (r for r in data if r.get("transactionID") == tx_id),
                {},
            )
        else:
            record = data
        state = str(record.get("state") or "")
        tx_hash = record.get("transactionHash") or record.get("hash")
        return state, tx_hash


def _to_bytes(data: Any) -> bytes:
    """Coerce 0x-hex / bytes calldata to bytes."""
    if isinstance(data, bytes):
        return data
    text = data[2:] if str(data).startswith("0x") else str(data)
    return bytes.fromhex(text)


def _as_0x(data: Any) -> str:
    """Coerce 0x-hex / bytes to a 0x-prefixed hex string."""
    if isinstance(data, bytes):
        return "0x" + data.hex()
    return data if str(data).startswith("0x") else "0x" + str(data)
