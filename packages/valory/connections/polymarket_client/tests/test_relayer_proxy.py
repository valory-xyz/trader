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

"""Tests for the wildcard relayer proxy client."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from eth_account import Account
from eth_account.messages import encode_defunct

from packages.valory.connections.polymarket_client.relayer_proxy import (
    CHALLENGE_PREFIX,
    DW_FACTORY,
    RELAYER_PATH_PREFIX,
    RelayerProxyClient,
    RelayerProxyError,
    _as_0x,
    _to_bytes,
)

# Deterministic test key (never used on-chain).
TEST_KEY = "0x0123456789012345678901234567890123456789012345678901234567890123"
BASE_URL = "https://mpp.example.org"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"


def _make_client() -> RelayerProxyClient:
    """Build a client with a deterministic signer."""
    return RelayerProxyClient(
        base_url=BASE_URL + "/",  # trailing slash is stripped
        private_key=TEST_KEY,
        chain_id=137,
        logger=MagicMock(),
    )


def _resp(json_body, raise_exc=None):  # type: ignore[no-untyped-def]
    """Build a fake requests.Response."""
    r = MagicMock()
    if raise_exc is not None:
        r.raise_for_status.side_effect = raise_exc
    r.json.return_value = json_body
    return r


class TestInitAndHelpers:
    """Construction, URL building and challenge auth."""

    def test_base_url_trailing_slash_stripped(self) -> None:
        """The trailing slash on the base URL is removed."""
        assert _make_client().base_url == BASE_URL

    def test_address_is_checksummed(self) -> None:
        """The address property exposes the signer's checksummed address."""
        client = _make_client()
        assert client.address.startswith("0x")
        assert len(client.address) == 42

    def test_path_and_url(self) -> None:
        """_path / _url build the relayer path and full URL."""
        client = _make_client()
        assert client._path("deploy_dw") == f"{RELAYER_PATH_PREFIX}/deploy_dw"
        assert client._url("deploy_dw") == (
            f"{BASE_URL}{RELAYER_PATH_PREFIX}/deploy_dw"
        )

    def test_auth_headers_sign_full_path_ms_challenge(self) -> None:
        """Headers carry an EIP-191 sig over the full-path, ms-timestamp challenge."""
        client = _make_client()
        path = client._path("exec_wallet_batch")
        with (
            patch(
                "packages.valory.connections.polymarket_client.relayer_proxy.time.time",
                return_value=1700.0,
            ),
            patch(
                "packages.valory.connections.polymarket_client.relayer_proxy."
                "secrets.token_hex",
                return_value="abcd",
            ),
        ):
            headers = client._auth_headers(path)
        # millisecond timestamp
        assert headers["X-Wallet-Timestamp"] == "1700000"
        assert headers["X-Wallet-Nonce"] == "abcd"
        assert headers["X-Wallet-Signature"].startswith("0x")
        assert "X-Wallet-From" not in headers
        # the signature recovers to the signer over the documented challenge
        challenge = f"{CHALLENGE_PREFIX}:{client.address}:{path}:1700000:abcd"
        recovered = Account.recover_message(
            encode_defunct(text=challenge),
            signature=headers["X-Wallet-Signature"],
        )
        assert recovered == client.address


class TestRequest:
    """The low-level _request wrapper."""

    def test_request_success(self) -> None:
        """A 2xx JSON response is returned parsed."""
        client = _make_client()
        with patch.object(requests, "request", return_value=_resp({"ok": True})):
            assert client._request("GET", "transaction") == {"ok": True}

    def test_request_post_sets_content_type(self) -> None:
        """A POST with a JSON body sets the Content-Type header."""
        client = _make_client()
        with patch.object(requests, "request", return_value=_resp({"ok": True})) as rq:
            client._request("POST", "deploy_dw", json_body={"a": 1})
        assert rq.call_args.kwargs["headers"]["Content-Type"] == "application/json"
        assert rq.call_args.kwargs["json"] == {"a": 1}

    def test_request_transport_error(self) -> None:
        """A transport error is wrapped."""
        client = _make_client()
        with patch.object(
            requests,
            "request",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            with pytest.raises(RelayerProxyError, match="failed"):
                client._request("GET", "transaction")

    def test_request_http_error(self) -> None:
        """A non-2xx status is wrapped."""
        client = _make_client()
        err = requests.exceptions.HTTPError("500")
        with patch.object(requests, "request", return_value=_resp({}, raise_exc=err)):
            with pytest.raises(RelayerProxyError):
                client._request("GET", "transaction")

    def test_request_non_json(self) -> None:
        """A non-JSON body is wrapped."""
        client = _make_client()
        r = MagicMock()
        r.json.side_effect = ValueError("not json")
        with patch.object(requests, "request", return_value=r):
            with pytest.raises(RelayerProxyError, match="non-JSON"):
                client._request("GET", "transaction")


class TestDeployedAndDeploy:
    """deployed / deploy_dw endpoints."""

    def test_deployed_true(self) -> None:
        """Deployed returns True when the registry has indexed the DW."""
        client = _make_client()
        with patch.object(client, "_request", return_value={"deployed": True}) as rq:
            assert client.deployed(DW) is True
        assert rq.call_args.kwargs["params"]["type"] == "WALLET"

    def test_deployed_false(self) -> None:
        """Deployed returns False when not yet indexed."""
        client = _make_client()
        with patch.object(client, "_request", return_value={"deployed": False}):
            assert client.deployed(DW) is False

    def test_deploy_dw_body_and_id(self) -> None:
        """deploy_dw posts the WALLET-CREATE body and returns the tx id."""
        client = _make_client()
        with patch.object(
            client, "_request", return_value={"transactionID": "tx1"}
        ) as rq:
            assert client.deploy_dw() == "tx1"
        body = rq.call_args.kwargs["json_body"]
        assert body["type"] == "WALLET-CREATE"
        assert body["from"] == client.address
        assert body["to"] == DW_FACTORY

    def test_deploy_dw_no_id_raises(self) -> None:
        """deploy_dw raises when no transaction id is returned."""
        client = _make_client()
        with patch.object(client, "_request", return_value={}):
            with pytest.raises(RelayerProxyError, match="no transaction id"):
                client.deploy_dw()


class TestExecWalletBatch:
    """exec_wallet_batch — EIP-712 batch signing + body shape."""

    def test_body_shape_and_signature(self) -> None:
        """The batch body targets the factory and carries a signed envelope."""
        client = _make_client()
        calls = [{"target": PUSD, "data": "0xabcd"}]
        with patch.object(
            client, "_request", return_value={"transactionID": "tx2"}
        ) as rq:
            tx = client.exec_wallet_batch(DW, nonce=3, calls=calls, deadline=999)
        assert tx == "tx2"
        body = rq.call_args.kwargs["json_body"]
        assert body["to"] == DW_FACTORY
        assert body["from"] == client.address
        assert body["nonce"] == "3"
        assert body["signature"].startswith("0x")
        assert len(body["signature"]) == 2 + 130  # 65-byte ECDSA
        params = body["depositWalletParams"]
        assert params["deadline"] == "999"
        assert params["calls"][0]["target"].lower() == PUSD.lower()
        assert params["calls"][0]["value"] == "0"
        assert params["calls"][0]["data"] == "0xabcd"

    def test_default_deadline(self) -> None:
        """When no deadline is given, one is derived from now."""
        client = _make_client()
        with (
            patch(
                "packages.valory.connections.polymarket_client.relayer_proxy.time.time",
                return_value=1000.0,
            ),
            patch.object(client, "_request", return_value={"transactionID": "t"}) as rq,
        ):
            client.exec_wallet_batch(
                DW, nonce=0, calls=[{"target": PUSD, "data": "0x"}]
            )
        deadline = rq.call_args.kwargs["json_body"]["depositWalletParams"]["deadline"]
        assert deadline == str(1000 + 3600)

    def test_no_id_raises(self) -> None:
        """exec_wallet_batch raises when no transaction id is returned."""
        client = _make_client()
        with patch.object(client, "_request", return_value={}):
            with pytest.raises(RelayerProxyError, match="no transaction id"):
                client.exec_wallet_batch(
                    DW, nonce=0, calls=[{"target": PUSD, "data": "0x"}]
                )

    def test_signature_is_deterministic_for_same_batch(self) -> None:
        """The same batch inputs produce the same owner signature."""
        client = _make_client()
        calls = [{"target": PUSD, "data": "0x1234"}]
        with patch.object(
            client, "_request", return_value={"transactionID": "a"}
        ) as r1:
            client.exec_wallet_batch(DW, nonce=1, calls=calls, deadline=5)
        with patch.object(
            client, "_request", return_value={"transactionID": "b"}
        ) as r2:
            client.exec_wallet_batch(DW, nonce=1, calls=calls, deadline=5)
        sig1 = r1.call_args.kwargs["json_body"]["signature"]
        sig2 = r2.call_args.kwargs["json_body"]["signature"]
        assert sig1 == sig2


class TestTransaction:
    """transaction state polling."""

    def test_mined_with_hash(self) -> None:
        """A mined tx returns its state and hash."""
        client = _make_client()
        with patch.object(
            client,
            "_request",
            return_value={"state": "STATE_MINED", "transactionHash": "0xabc"},
        ):
            assert client.transaction("t") == ("STATE_MINED", "0xabc")

    def test_failed_hash_fallback(self) -> None:
        """Transaction falls back to the ``hash`` field name."""
        client = _make_client()
        with patch.object(
            client,
            "_request",
            return_value={"state": "STATE_FAILED", "hash": "0xd"},
        ):
            assert client.transaction("t") == ("STATE_FAILED", "0xd")

    def test_list_selects_matching_id(self) -> None:
        """The proxy returns a list; the record matching the id is selected."""
        client = _make_client()
        body = [
            {"transactionID": "other", "state": "STATE_NEW"},
            {
                "transactionID": "t",
                "state": "STATE_CONFIRMED",
                "transactionHash": "0xok",
            },
        ]
        with patch.object(client, "_request", return_value=body):
            assert client.transaction("t") == ("STATE_CONFIRMED", "0xok")

    def test_list_absent_id_returns_empty(self) -> None:
        """With no id match, no record is used (avoids binding a wrong tx)."""
        client = _make_client()
        body = [{"transactionID": "other", "state": "STATE_EXECUTED", "hash": "0xa"}]
        with patch.object(client, "_request", return_value=body):
            assert client.transaction("t") == ("", None)

    def test_list_id_match_selected(self) -> None:
        """The record whose transactionID equals tx_id is selected."""
        client = _make_client()
        body = [
            {"transactionID": "other", "state": "STATE_FAILED"},
            {"transactionID": "t", "state": "STATE_EXECUTED", "transactionHash": "0xb"},
        ]
        with patch.object(client, "_request", return_value=body):
            assert client.transaction("t") == ("STATE_EXECUTED", "0xb")

    def test_empty_list(self) -> None:
        """An empty list yields an empty state and no hash."""
        client = _make_client()
        with patch.object(client, "_request", return_value=[]):
            assert client.transaction("t") == ("", None)


class TestEncodingHelpers:
    """The calldata coercion helpers."""

    def test_to_bytes(self) -> None:
        """_to_bytes accepts 0x-hex and raw bytes."""
        assert _to_bytes("0x0102") == b"\x01\x02"
        assert _to_bytes("0102") == b"\x01\x02"
        assert _to_bytes(b"\x03") == b"\x03"

    def test_as_0x(self) -> None:
        """_as_0x produces a 0x-prefixed hex string."""
        assert _as_0x(b"\x01\x02") == "0x0102"
        assert _as_0x("0xdead") == "0xdead"
        assert _as_0x("dead") == "0xdead"
