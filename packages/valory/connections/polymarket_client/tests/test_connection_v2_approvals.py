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

"""Tests for the Protocol V2 plumbing of the Polymarket connection.

Covers the Safe's PositionManager ``setApprovalForAll(Router, true)`` on the
relayer path and in the approval check, the relayer error body in the logged
error, and that a V1 market order still signs against the CTF Exchange with
EIP-712 domain version ``"2"``.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import requests
import yaml
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address
from py_builder_relayer_client.models import OperationType
from py_clob_client_v2 import ClobClient, OrderType
from py_clob_client_v2 import client as clob_client_module

from packages.valory.connections.polymarket_client import (
    connection as connection_module,
)
from packages.valory.connections.polymarket_client.connection import (
    PolymarketClientConnection,
    SIGNATURE_TYPE_POLY_1271,
)
from packages.valory.connections.polymarket_client.relayer_proxy import (
    RelayerProxyClient,
)

# Polygon addresses from https://docs.polymarket.com/resources/contracts
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF_COLLATERAL_ADAPTER = "0xAdA100Db00Ca00073811820692005400218FcE1f"
NEG_RISK_CTF_COLLATERAL_ADAPTER = "0xadA2005600Dec949baf300f4C6120000bDB6eAab"
EXCHANGE_V3 = "0xe3333700cA9d93003F00f0F71f8515005F6c00Aa"
POSITION_MANAGER = "0x006F54F7f9A22e0000CC2AB60031000000ae9fEF"
ROUTER = "0x12121212006e4CD160D18e3f00711DA5c3372600"
AUTO_REDEEMER = "0xa1200000d0002264C9a1698e001292D00E1b00af"

SAFE = "0x1111111111111111111111111111111111111111"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
# Deterministic test key (never used on-chain).
TEST_KEY = "0x0123456789012345678901234567890123456789012345678901234567890123"
PROXY_URL = "https://mpp.example.org"
MAX_UINT256 = 2**256 - 1
APPROVE = "095ea7b3"  # approve(address,uint256)
SET_APPROVAL_FOR_ALL = "a22cb465"  # setApprovalForAll(address,bool)

# Connection address attributes set to the documented addresses.
DOCS_ADDRESSES = {
    "collateral_address": PUSD,
    "ctf_address": CTF,
    "ctf_exchange": CTF_EXCHANGE,
    "neg_risk_ctf_exchange": NEG_RISK_CTF_EXCHANGE,
    "neg_risk_adapter": NEG_RISK_ADAPTER,
    "ctf_collateral_adapter": CTF_COLLATERAL_ADAPTER,
    "neg_risk_ctf_collateral_adapter": NEG_RISK_CTF_COLLATERAL_ADAPTER,
    "position_manager": POSITION_MANAGER,
    "router": ROUTER,
}

# The same attributes set to fixed addresses unlike the documented ones.
DISTINCT_ADDRESSES = {
    name: to_checksum_address("0x" + f"{0x10 + 0x11 * index:02x}" * 20)
    for index, name in enumerate(DOCS_ADDRESSES)
}

# The Safe approvals that predate Protocol V2, in their relayer order, as
# (target attribute, selector, argument attribute, uint argument).
SAFE_EXISTING_APPROVALS = (
    ("collateral_address", APPROVE, "ctf_exchange", MAX_UINT256),
    ("ctf_address", SET_APPROVAL_FOR_ALL, "ctf_exchange", 1),
    ("collateral_address", APPROVE, "neg_risk_ctf_exchange", MAX_UINT256),
    ("ctf_address", SET_APPROVAL_FOR_ALL, "neg_risk_ctf_exchange", 1),
    ("collateral_address", APPROVE, "neg_risk_adapter", MAX_UINT256),
    ("ctf_address", SET_APPROVAL_FOR_ALL, "neg_risk_adapter", 1),
    ("ctf_address", SET_APPROVAL_FOR_ALL, "ctf_collateral_adapter", 1),
    ("ctf_address", SET_APPROVAL_FOR_ALL, "neg_risk_ctf_collateral_adapter", 1),
)

# The Safe's PositionManager ``setApprovalForAll(Router, true)``.
SAFE_ROUTER_APPROVAL = ("position_manager", SET_APPROVAL_FOR_ALL, "router", 1)

_TESTS_DIR = Path(__file__).resolve().parent
_CONNECTION_YAML = _TESTS_DIR.parent / "connection.yaml"


class _Conn(PolymarketClientConnection):
    """Shadow the read-only configuration properties for direct assignment."""

    configuration = None  # type: ignore[assignment]
    crypto_store = None  # type: ignore[assignment]


def _make_conn() -> _Conn:
    """Build a connection bypassing ``__init__`` with V2 addresses set.

    :return: the connection.
    """
    conn = object.__new__(_Conn)
    conn.logger = MagicMock()
    conn.client = MagicMock()
    conn.relayer_client = MagicMock()
    conn.relayer_proxy = MagicMock()
    conn.dw_address = None
    conn._client_funder = SAFE
    conn._host = "https://clob.example"
    conn._chain_id = 137
    conn.builder_config = None
    conn.connection_private_key = TEST_KEY
    conn.w3 = MagicMock()
    conn.collateral_address = PUSD
    conn.ctf_address = CTF
    conn.ctf_exchange = CTF_EXCHANGE
    conn.neg_risk_ctf_exchange = NEG_RISK_CTF_EXCHANGE
    conn.neg_risk_adapter = NEG_RISK_ADAPTER
    conn.ctf_collateral_adapter = CTF_COLLATERAL_ADAPTER
    conn.neg_risk_ctf_collateral_adapter = NEG_RISK_CTF_COLLATERAL_ADAPTER
    conn.position_manager = POSITION_MANAGER
    conn.router = ROUTER
    conn.clob_version = "v2"
    configuration = MagicMock()
    configuration.config.get.side_effect = lambda key, *a, **k: (
        {"polygon": SAFE} if key == "safe_contract_addresses" else (a[0] if a else None)
    )
    conn.configuration = configuration
    return conn


def _decode(target: str, data: str) -> Tuple[str, str, str, int]:
    """Decode an approve / setApprovalForAll call from its ABI words.

    :param target: the call target.
    :param data: the 0x-hex calldata.
    :return: ``(target, selector, address argument, uint argument)``.
    """
    raw = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    assert len(raw) == 4 + 32 + 32, f"unexpected calldata length {len(raw)}"
    assert raw[4:16] == bytes(12), "address word is not left-padded"
    return (
        to_checksum_address(target),
        raw[:4].hex(),
        to_checksum_address("0x" + raw[16:36].hex()),
        int.from_bytes(raw[36:68], "big"),
    )


def _safe_calls_for(a: Dict[str, str]) -> List[Tuple[str, str, str, int]]:
    """Return the eight existing Safe approvals for the addresses ``a``.

    :param a: the connection address attributes.
    :return: the decoded calls, in relayer order.
    """
    return [
        (a[target], selector, a[argument], amount)
        for target, selector, argument, amount in SAFE_EXISTING_APPROVALS
    ]


def _check_on(conn: _Conn, a: Dict[str, str], router_approved: bool) -> Dict[str, Any]:
    """Run ``_check_approval`` against the Safe approvals for addresses ``a``.

    Only the approvals the Safe actually grants read as set: pUSD allowances
    to the three spenders, CTF operator rights for the five CTF operators and,
    if ``router_approved``, the Router as operator on the PositionManager.

    :param conn: the connection.
    :param a: the connection address attributes.
    :param router_approved: whether the Router approval is on chain.
    :return: the approval status.
    """
    granted = {
        (token, operator)
        for token, _, operator, _ in _safe_calls_for(a)
        if token == a["ctf_address"]
    }
    if router_approved:
        granted.add((a["position_manager"], a["router"]))
    allowances = {
        spender
        for token, selector, spender, _ in _safe_calls_for(a)
        if selector == APPROVE
    }

    def _allowance(token: str, owner: str, spender: str) -> int:
        approved = (
            to_checksum_address(token) == a["collateral_address"]
            and owner == SAFE
            and to_checksum_address(spender) in allowances
        )
        return MAX_UINT256 if approved else 0

    def _is_approved_for_all(token: str, owner: str, operator: str) -> bool:
        pair = (to_checksum_address(token), to_checksum_address(operator))
        return owner == SAFE and pair in granted

    conn._check_erc20_allowance = _allowance  # type: ignore[method-assign]
    conn._check_erc1155_approval = _is_approved_for_all  # type: ignore[method-assign]
    status, error = conn._check_approval()
    assert error is None
    return status


class _Chain:
    """On-chain approval state of the Safe, read by ``_check_approval``."""

    def __init__(self, router_approved: bool) -> None:
        """Start with every existing approval set.

        :param router_approved: whether the Router operates the Safe's
            PositionManager positions.
        """
        self.router_approved = router_approved
        self.erc1155_reads: List[Tuple[str, str, str]] = []

    def allowance(self, token: str, owner: str, spender: str) -> int:
        """Every existing pUSD allowance is set.

        :param token: the ERC-20 token.
        :param owner: the owner.
        :param spender: the spender.
        :return: the allowance.
        """
        assert owner == SAFE
        return MAX_UINT256

    def is_approved_for_all(self, token: str, owner: str, operator: str) -> bool:
        """Every existing operator approval is set; the Router one may not be.

        :param token: the ERC-1155 token.
        :param owner: the owner.
        :param operator: the operator.
        :return: whether ``operator`` is approved.
        """
        self.erc1155_reads.append(
            (to_checksum_address(token), owner, to_checksum_address(operator))
        )
        if to_checksum_address(token) == POSITION_MANAGER:
            return self.router_approved and to_checksum_address(operator) == ROUTER
        return True


def _check_with(chain: _Chain) -> Dict[str, Any]:
    """Run ``_check_approval`` against ``chain``.

    :param chain: the on-chain approval state.
    :return: the approval status.
    """
    conn = _make_conn()
    conn._check_erc20_allowance = chain.allowance  # type: ignore[method-assign]
    conn._check_erc1155_approval = chain.is_approved_for_all  # type: ignore[method-assign]
    status, error = conn._check_approval()
    assert error is None
    return status


# ---------------------------------------------------------------------------
# Safe Router approval
# ---------------------------------------------------------------------------


class TestSafeRouterApproval:
    """The Safe approves the Router on the PositionManager to claim V2 winnings."""

    def test_safe_approves_router_for_v2_positions(self) -> None:
        """The relayer path adds the Router approval; the check requires it.

        The relayer batch keeps the eight existing Safe approvals in order and
        appends PositionManager ``setApprovalForAll(Router, true)`` as a plain
        call with no value. ``_check_approval`` reports ``all_approvals_set:
        false`` until that approval is on chain, and reports the approval
        itself under ``position_manager_approvals.router``. Checked for the
        documented addresses and for a distinct set.
        """
        for a in (DOCS_ADDRESSES, DISTINCT_ADDRESSES):
            conn = _make_conn()
            for name, address in a.items():
                setattr(conn, name, address)
            result = MagicMock()
            result.get_transaction.return_value = {"transactionID": "safe-tx"}
            conn.relayer_client.execute.return_value = result

            tx, error = conn._set_approval()

            assert error is None, a
            assert tx == {"transactionID": "safe-tx"}, a
            txs = conn.relayer_client.execute.call_args.kwargs["transactions"]
            for t in txs:
                assert t.operation == OperationType.Call, a
                assert t.value == "0", a
            calls = [_decode(t.to, t.data) for t in txs]
            target, selector, argument, amount = SAFE_ROUTER_APPROVAL
            assert calls == _safe_calls_for(a) + [
                (a[target], selector, a[argument], amount)
            ], a
            addresses = [c[0] for c in calls] + [c[2] for c in calls]
            assert EXCHANGE_V3 not in addresses
            assert AUTO_REDEEMER not in addresses

            for router_approved in (False, True):
                status = _check_on(conn, a, router_approved)
                assert status["all_approvals_set"] is router_approved, a
                assert status["position_manager_approvals"] == {
                    "router": router_approved
                }, a

        pending = _Chain(router_approved=False)
        pending_status = _check_with(pending)
        assert pending_status["all_approvals_set"] is False
        assert pending_status["position_manager_approvals"] == {"router": False}
        assert (POSITION_MANAGER, SAFE, ROUTER) in pending.erc1155_reads

        mined = _Chain(router_approved=True)
        mined_status = _check_with(mined)
        assert mined_status["all_approvals_set"] is True
        assert mined_status["position_manager_approvals"] == {"router": True}
        assert (POSITION_MANAGER, SAFE, ROUTER) in mined.erc1155_reads

    def test_check_router_approval_on_position_manager_only(self) -> None:
        """The Router check reads the PositionManager, never the CTF.

        An operator approval for the Router on the CTF does not let the
        Router claim V2 winnings, so it must not satisfy the check.
        """
        chain = _Chain(router_approved=False)
        status = _check_with(chain)

        assert status["all_approvals_set"] is False
        router_reads = [r for r in chain.erc1155_reads if r[2] == ROUTER]
        assert router_reads == [(POSITION_MANAGER, SAFE, ROUTER)]
        assert all(r[2] != AUTO_REDEEMER for r in chain.erc1155_reads)
        assert all(r[2] != EXCHANGE_V3 for r in chain.erc1155_reads)

    def test_connection_loads_v2_router_approval_addresses(self) -> None:
        """``__init__`` reads the PositionManager and Router from the config.

        The defaults in ``connection.yaml`` are the documented addresses.
        """
        config = yaml.safe_load(_CONNECTION_YAML.read_text(encoding="utf-8"))["config"]
        assert config.get("position_manager_address") == POSITION_MANAGER
        assert config.get("router_address") == ROUTER

        config = dict(config)
        config["safe_contract_addresses"] = {"polygon": SAFE}
        config["is_running_on_polymarket"] = True
        conn = object.__new__(_Conn)
        conn.logger = MagicMock()
        conn.configuration = MagicMock(config=config)
        conn.crypto_store = MagicMock(private_keys={"ethereum": TEST_KEY})
        with (
            patch.object(
                connection_module.BaseSyncConnection, "__init__", return_value=None
            ),
            patch.object(connection_module, "RelayClient"),
            patch.object(connection_module, "RelayerProxyClient"),
            patch.object(connection_module, "Web3"),
            patch.object(_Conn, "_build_clob_client"),
        ):
            PolymarketClientConnection.__init__(conn)

        assert getattr(conn, "position_manager", None) == POSITION_MANAGER
        assert getattr(conn, "router", None) == ROUTER

        # Configured values win over the documented defaults.
        position_manager = DISTINCT_ADDRESSES["position_manager"]
        router = DISTINCT_ADDRESSES["router"]
        config["position_manager_address"] = position_manager
        config["router_address"] = router
        conn = object.__new__(_Conn)
        conn.logger = MagicMock()
        conn.configuration = MagicMock(config=config)
        conn.crypto_store = MagicMock(private_keys={"ethereum": TEST_KEY})
        with (
            patch.object(
                connection_module.BaseSyncConnection, "__init__", return_value=None
            ),
            patch.object(connection_module, "RelayClient"),
            patch.object(connection_module, "RelayerProxyClient"),
            patch.object(connection_module, "Web3"),
            patch.object(_Conn, "_build_clob_client"),
        ):
            PolymarketClientConnection.__init__(conn)

        assert to_checksum_address(conn.position_manager) == position_manager
        assert to_checksum_address(conn.router) == router


# ---------------------------------------------------------------------------
# Relayer error body
# ---------------------------------------------------------------------------

POLICY_REASON = (
    "call blocked: call[0] blocked: approve to exchange "
    "0xe3333700cA9d93003F00f0F71f8515005F6c00Aa must be MaxUint256"
)


def _http_response(status: int, body: str) -> requests.Response:
    """Build a real ``requests.Response`` with ``status`` and ``body``.

    :param status: the HTTP status code.
    :param body: the raw response body.
    :return: the response.
    """
    response = requests.Response()
    response.status_code = status
    response.reason = "Bad Request"
    response.url = f"{PROXY_URL}/polymarket/relayer/exec_wallet_batch"
    response._content = body.encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    return response


class TestRelayerErrorBody:
    """The relayer's 4xx body carries the policy reason; it must be logged."""

    def test_relayer_error_body_is_logged(self) -> None:
        """A 400 from the relayer proxy puts its body in the logged error."""
        conn = _make_conn()
        conn.relayer_proxy = RelayerProxyClient(
            base_url=PROXY_URL, private_key=TEST_KEY, chain_id=137, logger=MagicMock()
        )
        conn._dw_nonce = MagicMock(return_value=0)  # type: ignore[method-assign]
        body = '{"error":"' + POLICY_REASON + '"}'
        approve = "0x" + APPROVE + "00" * 12 + EXCHANGE_V3[2:].lower() + "ff" * 32
        with patch.object(
            requests, "request", return_value=_http_response(400, body)
        ) as request:
            response, error = conn._exec_wallet_batch(
                [{"to": PUSD, "data": approve, "value": "0"}], dw_address=DW
            )

        request.assert_called_once()
        assert response == {"error": error}
        assert POLICY_REASON in error
        logged = " ".join(str(c) for c in conn.logger.error.call_args_list)
        assert POLICY_REASON in logged
        assert "400" in logged


# ---------------------------------------------------------------------------
# SDK 1.2.1 and V1 orders
# ---------------------------------------------------------------------------


def _ctf_exchange_domain_separator(version: str) -> bytes:
    """Compute the CTF Exchange EIP-712 domain separator on Polygon.

    :param version: the domain version.
    :return: the domain separator.
    """
    return keccak(
        abi_encode(
            ["bytes32", "bytes32", "bytes32", "uint256", "address"],
            [
                keccak(
                    text=(
                        "EIP712Domain(string name,string version,uint256 chainId,"
                        "address verifyingContract)"
                    )
                ),
                keccak(text="Polymarket CTF Exchange"),
                keccak(text=version),
                137,
                CTF_EXCHANGE,
            ],
        )
    )


def _recover_poly_1271_signer(signed: Any, domain_separator: bytes) -> str:
    """Recover the EOA behind a POLY_1271 (DepositWallet) order signature.

    :param signed: the signed order.
    :param domain_separator: the exchange domain separator to verify against.
    :return: the recovered signer address.
    """
    order_type = (
        "Order(uint256 salt,address maker,address signer,uint256 tokenId,"
        "uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,"
        "uint256 timestamp,bytes32 metadata,bytes32 builder)"
    )
    contents_hash = keccak(
        abi_encode(
            [
                "bytes32",
                "uint256",
                "address",
                "address",
                "uint256",
                "uint256",
                "uint256",
                "uint8",
                "uint8",
                "uint256",
                "bytes32",
                "bytes32",
            ],
            [
                keccak(text=order_type),
                int(signed.salt),
                signed.maker,
                signed.signer,
                int(signed.tokenId),
                int(signed.makerAmount),
                int(signed.takerAmount),
                int(signed.side),
                int(signed.signatureType),
                int(signed.timestamp),
                bytes.fromhex(signed.metadata[2:].zfill(64)),
                bytes.fromhex(signed.builder[2:].zfill(64)),
            ],
        )
    )
    typed_data_sign = keccak(
        abi_encode(
            [
                "bytes32",
                "bytes32",
                "bytes32",
                "bytes32",
                "uint256",
                "address",
                "bytes32",
            ],
            [
                keccak(
                    text=(
                        "TypedDataSign(Order contents,string name,string version,"
                        "uint256 chainId,address verifyingContract,bytes32 salt)"
                        + order_type
                    )
                ),
                contents_hash,
                keccak(text="DepositWallet"),
                keccak(text="1"),
                137,
                signed.signer,
                bytes(32),
            ],
        )
    )
    digest = keccak(b"\x19\x01" + domain_separator + typed_data_sign)
    signature = bytes.fromhex(signed.signature[2:])
    return Account._recover_hash(digest, signature=signature[:65])


V1_TOKEN_ID = "71321045679252212594626385532706912750332728571942532289631379312455583992563"  # nosec B105
V1_CONDITION_ID = "0x" + "c1" * 32


def _clob_get(
    endpoint: str,
    headers: Optional[dict] = None,
    data: Any = None,
    params: Optional[dict] = None,
) -> Any:
    """Answer the CLOB API reads a V1 market order makes.

    The market behind ``V1_TOKEN_ID`` is a V1 (non-neg-risk) market with a
    0.01 tick and no fees, and the CLOB reports order version 2.

    :param endpoint: the requested URL.
    :param headers: the request headers.
    :param data: the request body.
    :param params: the query parameters.
    :return: the decoded JSON reply.
    """
    path = urlparse(endpoint).path
    if path == f"/markets-by-token/{V1_TOKEN_ID}":
        return {"condition_id": V1_CONDITION_ID}
    if path == f"/clob-markets/{V1_CONDITION_ID}":
        return {
            "t": [{"t": V1_TOKEN_ID}],
            "mts": 0.01,
            "nr": False,
            "fd": {"r": 0, "e": 0},
        }
    if path == "/version":
        return {"version": 2}
    raise AssertionError(f"unexpected CLOB read {path} {params}")


class TestV1Orders:
    """SDK 1.2.1 keeps V1 market orders on token ids and domain version "2"."""

    def test_v1_order_unchanged(self) -> None:
        """A V1 market order sets ``token_id`` and signs with domain version "2".

        The connection funds the order from the DepositWallet (POLY_1271), so
        the signature embeds the CTF Exchange domain separator, which must be
        the version "2" one, and recovers to the agent EOA under it. The SDK
        runs through its public calls; only the CLOB API replies are faked.
        """
        conn = _make_conn()
        conn._read_dw_collateral_balance = MagicMock(return_value=100.0)  # type: ignore[method-assign]
        posted = {"orderID": "0xorder", "status": "matched"}
        with (
            patch.object(clob_client_module, "get", side_effect=_clob_get),
            patch.object(ClobClient, "create_or_derive_api_key", return_value=None),
            patch.object(ClobClient, "calculate_market_price", return_value=0.5),
            patch.object(
                ClobClient,
                "create_market_order",
                autospec=True,
                side_effect=ClobClient.create_market_order,
            ) as create_market_order,
            patch.object(ClobClient, "post_order", return_value=posted) as post_order,
        ):
            response, error = conn._place_bet(
                token_id=V1_TOKEN_ID, amount=5.0, funder=DW
            )

        assert error is None
        assert response["orderID"] == "0xorder"
        assert conn._client_funder == to_checksum_address(DW)
        order_args = create_market_order.call_args.args[1]
        assert order_args.token_id == V1_TOKEN_ID
        assert getattr(order_args, "position_id", "absent") is None

        signed, order_type = post_order.call_args.args
        assert order_type == OrderType.FOK
        assert signed.tokenId == V1_TOKEN_ID
        assert int(signed.signatureType) == SIGNATURE_TYPE_POLY_1271
        assert signed.maker == to_checksum_address(DW)
        separator = _ctf_exchange_domain_separator("2")
        assert signed.signature[2 + 130 : 2 + 130 + 64] == separator.hex()
        agent = Account.from_key(TEST_KEY).address
        assert _recover_poly_1271_signer(signed, separator) == agent
        v3_separator = _ctf_exchange_domain_separator("3")
        assert _recover_poly_1271_signer(signed, v3_separator) != agent
