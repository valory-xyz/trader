# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""Tests for the polymarket_client connection."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from packages.valory.connections.polymarket_client.connection import (
    DATA_API_BASE_URL,
    GAMMA_API_BASE_URL,
    MAX_UINT256,
    PARENT_COLLECTION_ID,
    POLYMARKET_CATEGORY_TAGS,
    PolymarketClientConnection,
    SrrDialogues,
    _validate_builder_code,
)
from packages.valory.connections.polymarket_client.request_types import RequestType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAFE_ADDRESS = "0x0000000000000000000000000000000000000001"
COLLATERAL_ADDRESS = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"  # pUSD (v2)
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # legacy wrap source
COLLATERAL_ONRAMP_ADDRESS = "0x93070a847efEf7F70739046A929D47a521F5B8ee"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"  # v2
NEG_RISK_CTF_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"  # v2
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF_COLLATERAL_ADAPTER = "0xAdA100Db00Ca00073811820692005400218FcE1f"
NEG_RISK_CTF_COLLATERAL_ADAPTER = "0xadA2005600Dec949baf300f4C6120000bDB6eAab"


class _TestableConnection(PolymarketClientConnection):
    """Shadows the read-only AEA configuration property with a plain instance attribute."""

    configuration = None  # type: ignore[assignment]


def _make_connection() -> _TestableConnection:
    """Create a _TestableConnection instance bypassing __init__ (pragma: no cover).

    We bypass __init__ (which is marked pragma: no cover) and directly set instance
    attributes needed for testing. Shadowing the read-only AEA 'configuration'
    property at class level allows direct assignment on the instance.
    """
    conn = object.__new__(_TestableConnection)
    conn.logger = MagicMock()
    conn.client = MagicMock()
    conn.relayer_client = MagicMock()
    conn.w3 = MagicMock()
    conn.collateral_address = COLLATERAL_ADDRESS
    conn.usdc_e_address = USDC_E_ADDRESS
    conn.collateral_onramp_address = COLLATERAL_ONRAMP_ADDRESS
    conn.ctf_address = CTF_ADDRESS
    conn.ctf_exchange = CTF_EXCHANGE
    conn.neg_risk_ctf_exchange = NEG_RISK_CTF_EXCHANGE
    conn.neg_risk_adapter = NEG_RISK_ADAPTER
    conn.ctf_collateral_adapter = CTF_COLLATERAL_ADAPTER
    conn.neg_risk_ctf_collateral_adapter = NEG_RISK_CTF_COLLATERAL_ADAPTER
    conn.clob_version = "v2"
    conn.dialogues = MagicMock()
    configuration_mock = MagicMock()
    safe_contract_addresses = {"polygon": SAFE_ADDRESS}
    configuration_mock.config.get.side_effect = lambda key, *args, **kwargs: (
        safe_contract_addresses
        if key == "safe_contract_addresses"
        else args[0] if args else None
    )
    conn.configuration = configuration_mock
    return conn


# ---------------------------------------------------------------------------
# SrrDialogues
# ---------------------------------------------------------------------------


class TestSrrDialogues:
    """Tests for SrrDialogues."""

    def test_role_from_first_message(self) -> None:
        """The role is always CONNECTION; verified by invoking the dialogue creation path."""
        from packages.valory.protocols.srr.dialogues import SrrDialogue
        from packages.valory.protocols.srr.message import SrrMessage

        conn_id = "valory/polymarket_client:0.1.0"
        dialogues = SrrDialogues(connection_id=conn_id)

        # Creating a dialogue invokes the inner role_from_first_message callback (line 103)
        # create() returns (message, dialogue)
        msg, dialogue = dialogues.create(
            counterparty="some_skill",
            performative=SrrMessage.Performative.REQUEST,
            payload="{}",
        )
        assert dialogue is not None
        # The connection should be the role
        assert dialogue.role == SrrDialogue.Role.CONNECTION

    def test_connection_id_passed_to_parent(self) -> None:
        """Test that connection_id is consumed and not forwarded as a kwarg."""
        mock_id = MagicMock()
        mock_id.__str__ = lambda s: "valory/polymarket_client:0.1.0"
        dialogues = SrrDialogues(connection_id=mock_id)
        assert dialogues is not None


# ---------------------------------------------------------------------------
# safe_address property
# ---------------------------------------------------------------------------


class TestSafeAddressProperty:
    """Tests for the safe_address property."""

    def test_safe_address_returns_polygon(self) -> None:
        """Test safe_address reads from configuration."""
        conn = _make_connection()
        # The property reads config.get("safe_contract_addresses").get("polygon")
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        assert conn.safe_address == SAFE_ADDRESS


# ---------------------------------------------------------------------------
# main / on_connect / on_disconnect
# ---------------------------------------------------------------------------


class TestLifecycleMethods:
    """Tests for main, on_connect, on_disconnect."""

    def test_main_does_not_raise(self) -> None:
        """main() is a no-op; verify it returns None without error."""
        conn = _make_connection()
        result = conn.main()
        assert result is None

    def test_on_connect_does_not_raise(self) -> None:
        """on_connect() is a no-op; verify it returns None without error."""
        conn = _make_connection()
        result = conn.on_connect()
        assert result is None

    def test_on_disconnect_does_not_raise(self) -> None:
        """on_disconnect() is a no-op; verify it returns None without error."""
        conn = _make_connection()
        result = conn.on_disconnect()
        assert result is None


# ---------------------------------------------------------------------------
# on_send
# ---------------------------------------------------------------------------


class TestOnSend:
    """Tests for on_send."""

    def _make_envelope(self, payload: dict) -> Any:
        """Create a mock envelope with the given payload."""
        from packages.valory.protocols.srr.message import SrrMessage

        envelope = MagicMock()
        message = MagicMock(spec=SrrMessage)
        message.performative = SrrMessage.Performative.REQUEST
        message.payload = json.dumps(payload)
        envelope.message = message
        return envelope

    def test_on_send_routes_request(self) -> None:
        """on_send calls _route_request and puts a response envelope back.

        Critically, the response envelope must swap to/sender so the reply
        is addressed back to the original caller.
        """
        conn = _make_connection()
        from packages.valory.protocols.srr.message import SrrMessage

        # Set up dialogue mock
        dialogue_mock = MagicMock()
        response_msg = MagicMock(spec=SrrMessage)
        # Envelope consistency checks require message.to == envelope.sender
        response_msg.to = "sender_address"
        response_msg.sender = "receiver_address"
        dialogue_mock.reply.return_value = response_msg
        conn.dialogues.update.return_value = dialogue_mock

        # Mock _route_request
        conn._route_request = MagicMock(return_value=({"result": "ok"}, ""))
        conn.put_envelope = MagicMock()

        envelope = self._make_envelope({"request_type": "fetch_markets", "params": {}})
        # Envelope requires string addresses
        envelope.sender = "sender_address"
        envelope.to = "receiver_address"
        envelope.context = None
        conn.on_send(envelope)

        conn._route_request.assert_called_once()
        conn.put_envelope.assert_called_once()

        # Verify the response envelope addresses are correctly swapped:
        # the reply must go back to the original sender
        sent_envelope = conn.put_envelope.call_args[0][0]
        assert sent_envelope.to == "sender_address"  # reply goes to original sender
        assert sent_envelope.sender == "receiver_address"  # from the connection

    def test_on_send_wrong_performative_logs_error(self) -> None:
        """on_send logs error and returns early when performative is not REQUEST."""
        conn = _make_connection()
        from packages.valory.protocols.srr.message import SrrMessage

        envelope = MagicMock()
        message = MagicMock(spec=SrrMessage)
        message.performative = SrrMessage.Performative.RESPONSE  # wrong performative
        message.payload = json.dumps({})
        envelope.message = message

        conn.dialogues.update.return_value = MagicMock()
        conn.put_envelope = MagicMock()

        conn.on_send(envelope)
        conn.logger.error.assert_called_once()
        conn.put_envelope.assert_not_called()


# ---------------------------------------------------------------------------
# _route_request
# ---------------------------------------------------------------------------


class TestRouteRequest:
    """Tests for _route_request."""

    def test_missing_request_type_returns_error(self) -> None:
        """Missing request_type key returns an error tuple."""
        conn = _make_connection()
        response, error = conn._route_request({})
        assert response is None
        assert "Missing 'request_type'" in error

    def test_invalid_request_type_returns_error(self) -> None:
        """An unrecognised request type returns an error tuple."""
        conn = _make_connection()
        response, error = conn._route_request({"request_type": "nonexistent_type"})
        assert response is None
        assert "not supported" in error

    def test_valid_request_type_is_dispatched(self) -> None:
        """A valid request_type calls the correct handler."""
        conn = _make_connection()
        conn._fetch_markets = MagicMock(return_value=({"cat": []}, None))
        response, error = conn._route_request(
            {"request_type": RequestType.FETCH_MARKETS.value, "params": {}}
        )
        conn._fetch_markets.assert_called_once_with()
        assert error == ""

    def test_handler_error_wrapped_in_dict(self) -> None:
        """When handler returns an error string, the response is wrapped."""
        conn = _make_connection()
        conn._fetch_markets = MagicMock(return_value=(None, "some error from API"))
        response, error = conn._route_request(
            {"request_type": RequestType.FETCH_MARKETS.value, "params": {}}
        )
        assert response == {"error": "some error from API"}
        assert error == "some error from API"

    def test_handler_error_preserves_response_dict_keys(self) -> None:
        """A handler-returned response dict is not clobbered by the error wrap.

        ``_place_bet`` returns ``signed_order_json`` in its error response so the
        caller can cache the signed order and retry without re-signing. The
        router must preserve those extra keys rather than overwriting the dict.
        """
        conn = _make_connection()
        handler_response = {
            "error": "duplicate order",
            "signed_order_json": '{"cached": "order"}',
        }
        conn._place_bet = MagicMock(return_value=(handler_response, "duplicate order"))
        response, error = conn._route_request(
            {
                "request_type": RequestType.PLACE_BET.value,
                "params": {"token_id": "t", "amount": 1.0},  # nosec B105
            }
        )
        assert error == "duplicate order"
        assert response["error"] == "duplicate order"
        assert response["signed_order_json"] == '{"cached": "order"}'

    def test_type_error_in_handler_returns_error(self) -> None:
        """Test that TypeError from handler (bad params) is caught and returned."""
        conn = _make_connection()
        conn._place_bet = MagicMock(side_effect=TypeError("bad args"))
        response, error = conn._route_request(
            {"request_type": RequestType.PLACE_BET.value, "params": {}}
        )
        assert response is None
        assert "Invalid parameters" in error

    def test_generic_exception_in_handler_returns_error(self) -> None:
        """A generic exception from the handler is caught."""
        conn = _make_connection()
        conn._check_approval = MagicMock(side_effect=RuntimeError("oops"))
        response, error = conn._route_request(
            {
                "request_type": RequestType.CHECK_APPROVAL.value,
                "params": {},
            }
        )
        assert response is None
        assert "Error executing" in error

    @pytest.mark.parametrize("request_type", list(RequestType))
    def test_all_request_types_have_handler(self, request_type: RequestType) -> None:
        """Every RequestType member maps to a handler method."""
        conn = _make_connection()
        # Mock every real handler to avoid side-effects
        for method in [
            "_place_bet",
            "_fetch_markets",
            "_fetch_market_by_slug",
            "_get_positions",
            "_fetch_all_positions",
            "_get_trades",
            "_fetch_all_trades",
            "_redeem_positions",
            "_set_approval",
            "_check_approval",
            "_fetch_order_book",
        ]:
            setattr(conn, method, MagicMock(return_value=({"ok": True}, None)))

        response, error = conn._route_request(
            {"request_type": request_type.value, "params": {}}
        )
        assert error == ""


# ---------------------------------------------------------------------------
# _test_connection
# ---------------------------------------------------------------------------


class TestTestConnection:
    """Tests for _test_connection."""

    def test_returns_true_on_success(self) -> None:
        """Returns True when client.get_ok() succeeds."""
        conn = _make_connection()
        conn.client.get_ok.return_value = True
        assert conn._test_connection() is True

    def test_returns_false_on_exception(self) -> None:
        """Returns False when client.get_ok() raises."""
        conn = _make_connection()
        conn.client.get_ok.side_effect = Exception("network error")
        assert conn._test_connection() is False


# ---------------------------------------------------------------------------
# _place_bet
# ---------------------------------------------------------------------------


class TestPlaceBet:
    """Tests for _place_bet."""

    @staticmethod
    def _make_signed_order_v2() -> "object":
        """Build a real SignedOrderV2 instance for serialization round-trips."""
        from py_clob_client_v2.order_utils import Side
        from py_clob_client_v2.order_utils.model.order_data_v2 import SignedOrderV2
        from py_clob_client_v2.order_utils.model.signature_type_v2 import (
            SignatureTypeV2,
        )

        return SignedOrderV2(
            salt="1",
            maker="0x0000000000000000000000000000000000000001",
            signer="0x0000000000000000000000000000000000000002",
            tokenId="tok",
            makerAmount="10",
            takerAmount="5",
            side=Side.BUY,
            signatureType=SignatureTypeV2.POLY_GNOSIS_SAFE,
            timestamp="1700000000000",
            metadata="0x" + "00" * 32,
            builder="0x" + "00" * 32,
            expiration="0",
            signature="0xdeadbeef",
        )

    def test_place_bet_success_no_cache(self) -> None:
        """Places bet from scratch (no cached order) and returns response.

        The response must include 'signed_order_json' with the v2 cache marker
        so the caller can retry with the same order if the submission fails.
        """
        conn = _make_connection()
        signed = self._make_signed_order_v2()
        conn.client.create_market_order.return_value = signed
        conn.client.post_order.return_value = {"status": "matched"}

        response, error = conn._place_bet(token_id="tok123", amount=10.0)  # nosec B106
        assert error is None
        conn.client.create_market_order.assert_called_once()
        conn.client.post_order.assert_called_once()
        # Signed-order JSON must be embedded and marked as v2 for the
        # cache-invalidation guard in _place_bet.
        assert "signed_order_json" in response
        cached_dict = json.loads(response["signed_order_json"])
        assert cached_dict["clob_version"] == "v2"
        assert cached_dict["timestamp"] == "1700000000000"

    def test_place_bet_with_cached_v2_order(self) -> None:
        """Uses cached v2 signed order instead of creating a new one."""
        conn = _make_connection()
        from packages.valory.connections.polymarket_client.connection import (
            _serialize_signed_order_v2,
        )

        cached = _serialize_signed_order_v2(self._make_signed_order_v2())
        cached_json = json.dumps(cached)
        conn.client.post_order.return_value = {"status": "matched"}

        response, error = conn._place_bet(
            token_id="tok123",
            amount=10.0,
            cached_signed_order_json=cached_json,  # nosec B106
        )
        # Must reuse the cached order — no resign.
        conn.client.create_market_order.assert_not_called()
        assert error is None
        assert response is not None
        assert response["signed_order_json"] == cached_json

    def test_place_bet_drops_v1_cache_and_resigns(self) -> None:
        """v1-shaped cache (no ``clob_version`` marker) is dropped; order resigned."""
        conn = _make_connection()
        v1_cached = {
            "salt": "1",
            "maker": "0x0",
            "tokenId": "tok",
            "makerAmount": "10",
            "takerAmount": "5",
            "side": 0,
            "signatureType": 2,
            "nonce": "0",
            "expiration": "0",
            "taker": "0x0",
            "feeRateBps": "0",
            "signature": "0xdeadbeef",
        }
        conn.client.create_market_order.return_value = self._make_signed_order_v2()
        conn.client.post_order.return_value = {"status": "matched"}

        response, error = conn._place_bet(
            token_id="tok123",
            amount=10.0,
            cached_signed_order_json=json.dumps(v1_cached),  # nosec B106
        )
        # The v1 entry must be discarded and a fresh v2 order signed.
        conn.client.create_market_order.assert_called_once()
        assert error is None
        assert json.loads(response["signed_order_json"])["clob_version"] == "v2"

    def test_place_bet_unparseable_cache_resigns(self) -> None:
        """Garbage cache JSON: warn and fall through to fresh signing."""
        conn = _make_connection()
        conn.client.create_market_order.return_value = self._make_signed_order_v2()
        conn.client.post_order.return_value = {"status": "matched"}

        response, error = conn._place_bet(
            token_id="tok123",
            amount=10.0,
            cached_signed_order_json="not-json{{",  # nosec B106
        )
        conn.client.create_market_order.assert_called_once()
        assert error is None
        assert json.loads(response["signed_order_json"])["clob_version"] == "v2"

    def test_place_bet_poly_api_exception_with_dict_error(self) -> None:
        """Check that a PolyApiException with dict error_msg returns error in response.

        The response must also contain 'signed_order_json' so the caller can
        retry the submission with the same order (even though order creation
        failed before posting).
        """
        from py_clob_client_v2.exceptions import PolyApiException

        conn = _make_connection()
        exc = PolyApiException(error_msg={"error": "duplicate order"})
        conn.client.create_market_order.side_effect = exc

        response, error = conn._place_bet(token_id="tok123", amount=5.0)  # nosec B106
        assert error == "duplicate order"
        assert "error" in response
        # signed_order_json must be present so the caller can cache and retry
        assert "signed_order_json" in response

    def test_place_bet_poly_api_exception_non_dict_error(self) -> None:
        """Check that a PolyApiException with non-dict error_msg falls to the generic branch."""
        from py_clob_client_v2.exceptions import PolyApiException

        conn = _make_connection()
        exc = PolyApiException(error_msg="plain string error")
        conn.client.create_market_order.side_effect = exc

        response, error = conn._place_bet(token_id="tok123", amount=5.0)  # nosec B106
        assert error is not None
        assert error.startswith("Error placing bet:")
        assert "error" in response

    def test_place_bet_post_order_none_response(self) -> None:
        """When post_order returns None, response is None but no crash."""
        conn = _make_connection()
        conn.client.create_market_order.return_value = self._make_signed_order_v2()
        conn.client.post_order.return_value = None

        response, error = conn._place_bet(token_id="tok123", amount=5.0)  # nosec B106
        assert error is None
        assert response is None


# ---------------------------------------------------------------------------
# _request_with_retries
# ---------------------------------------------------------------------------


class TestRequestWithRetries:
    """Tests for _request_with_retries."""

    def test_success_on_first_attempt(self) -> None:
        """Returns data on the first successful request."""
        conn = _make_connection()
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "1"}

        with patch("requests.get", return_value=mock_response) as mock_get:
            result, error = conn._request_with_retries("https://example.com/api")

        assert result == {"id": "1"}
        assert error is None
        assert mock_get.call_count == 1

    def test_retries_on_request_exception_then_succeeds(self) -> None:
        """Retries after RequestException and returns data on success."""
        conn = _make_connection()
        success_response = MagicMock()
        success_response.json.return_value = {"data": "ok"}

        with patch("requests.get") as mock_get, patch("time.sleep"):
            mock_get.side_effect = [
                requests.exceptions.RequestException("timeout"),
                success_response,
            ]
            result, error = conn._request_with_retries(
                "https://example.com/api", max_retries=3
            )

        assert result == {"data": "ok"}
        assert error is None

    def test_exhausts_retries_returns_error(self) -> None:
        """After max_retries all fail, returns None and last error."""
        conn = _make_connection()
        with patch("requests.get") as mock_get, patch("time.sleep"):
            mock_get.side_effect = requests.exceptions.RequestException("fail")
            result, error = conn._request_with_retries(
                "https://example.com/api", max_retries=2
            )

        assert result is None
        assert "fail" in error
        assert mock_get.call_count == 2

    def test_passes_params_to_request(self) -> None:
        """Query params are forwarded to requests.get."""
        conn = _make_connection()
        mock_response = MagicMock()
        mock_response.json.return_value = []

        params = {"tag_id": "42", "limit": 300}
        with patch("requests.get", return_value=mock_response) as mock_get:
            conn._request_with_retries("https://example.com/markets", params=params)

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"] == params


# ---------------------------------------------------------------------------
# _filter_tradeable_markets
# ---------------------------------------------------------------------------


class TestFilterTradeableMarkets:
    """Tests for _filter_tradeable_markets.

    /events returns some nested markets that are tagged Yes/No but are not
    actually tradeable (missing outcomePrices / clobTokenIds, or active=False).
    The old /markets endpoint filtered these server-side. This filter matches
    that behaviour client-side so the downstream behaviour doesn't warn on them.
    """

    def test_drops_market_missing_outcome_prices(self) -> None:
        """Market with empty outcomePrices is dropped."""
        conn = _make_connection()
        markets = [
            {
                "id": "m1",
                "outcomePrices": "[]",
                "clobTokenIds": '["t1","t2"]',
                "active": True,
            },
            {
                "id": "m2",
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": True,
            },
        ]
        result = conn._filter_tradeable_markets(markets)
        assert [m["id"] for m in result] == ["m2"]

    def test_drops_market_missing_clob_token_ids(self) -> None:
        """Market with empty clobTokenIds is dropped."""
        conn = _make_connection()
        markets = [
            {
                "id": "m1",
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": "[]",
                "active": True,
            },
            {
                "id": "m2",
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": True,
            },
        ]
        result = conn._filter_tradeable_markets(markets)
        assert [m["id"] for m in result] == ["m2"]

    def test_drops_market_with_active_false(self) -> None:
        """Market with active=False is dropped even if other fields are populated."""
        conn = _make_connection()
        markets = [
            {
                "id": "m1",
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": False,
            },
            {
                "id": "m2",
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": True,
            },
        ]
        result = conn._filter_tradeable_markets(markets)
        assert [m["id"] for m in result] == ["m2"]

    def test_drops_market_missing_active_field(self) -> None:
        """Market without an `active` key is treated as not-tradeable and dropped."""
        conn = _make_connection()
        markets = [
            {
                "id": "m1",
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
            },
        ]
        result = conn._filter_tradeable_markets(markets)
        assert result == []

    def test_drops_market_with_missing_fields(self) -> None:
        """Market with no outcomePrices / clobTokenIds keys at all is dropped."""
        conn = _make_connection()
        markets = [{"id": "m1", "active": True}]
        result = conn._filter_tradeable_markets(markets)
        assert result == []

    def test_drops_market_with_malformed_json_fields(self) -> None:
        """Market whose outcomePrices / clobTokenIds is not valid JSON is dropped."""
        conn = _make_connection()
        markets = [
            {
                "id": "m1",
                "outcomePrices": "not json",
                "clobTokenIds": '["t1","t2"]',
                "active": True,
            },
        ]
        result = conn._filter_tradeable_markets(markets)
        assert result == []

    def test_keeps_fully_populated_active_market(self) -> None:
        """A market with populated fields and active=True is kept."""
        conn = _make_connection()
        markets = [
            {
                "id": "m1",
                "outcomePrices": '["0.4","0.6"]',
                "clobTokenIds": '["tok1","tok2"]',
                "active": True,
            },
        ]
        result = conn._filter_tradeable_markets(markets)
        assert [m["id"] for m in result] == ["m1"]

    def test_empty_input_returns_empty(self) -> None:
        """No markets → empty list."""
        conn = _make_connection()
        assert conn._filter_tradeable_markets([]) == []


# ---------------------------------------------------------------------------
# _fetch_markets applies tradeable filter
# ---------------------------------------------------------------------------


class TestFetchMarketsAppliesTradeableFilter:
    """Ensure _fetch_markets runs the new tradeable filter alongside the others."""

    def test_fetch_markets_drops_inactive_or_unpriced_markets(self) -> None:
        """Markets that pass yes/no but fail the tradeable filter are excluded."""
        conn = _make_connection()
        # Mix of yes/no markets: one tradeable, one missing prices, one inactive
        markets = [
            {
                "id": "keep",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.4","0.6"]',
                "clobTokenIds": '["tok1","tok2"]',
                "active": True,
                "_poly_tags": ["politics"],
            },
            {
                "id": "drop_prices",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["Yes","No"]',
                "outcomePrices": "[]",
                "clobTokenIds": '["tok1","tok2"]',
                "active": True,
                "_poly_tags": ["politics"],
            },
            {
                "id": "drop_inactive",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.4","0.6"]',
                "clobTokenIds": '["tok1","tok2"]',
                "active": False,
                "_poly_tags": ["politics"],
            },
        ]
        conn._fetch_markets_by_tag_slug = MagicMock(return_value=(markets, None))

        result, error = conn._fetch_markets()
        assert error is None
        for cat_markets in result.values():
            ids = [m["id"] for m in cat_markets]
            assert ids == ["keep"]


# ---------------------------------------------------------------------------
# _filter_markets_by_created_at
# ---------------------------------------------------------------------------


class TestFilterMarketsByCreatedAt:
    """Tests for _filter_markets_by_created_at."""

    def test_filters_older_markets(self) -> None:
        """Removes markets created before MARKETS_MIN_CREATED_AT."""
        conn = _make_connection()
        markets = [
            {"id": "old", "createdAt": "2025-12-01T00:00:00Z"},
            {"id": "new", "createdAt": "2026-01-01T00:00:00Z"},
        ]
        result = conn._filter_markets_by_created_at(markets)
        assert len(result) == 1
        assert result[0]["id"] == "new"

    def test_missing_created_at_treated_as_empty_string(self) -> None:
        """Markets without createdAt are filtered out (empty string < MIN)."""
        conn = _make_connection()
        markets = [{"id": "no_date"}]
        result = conn._filter_markets_by_created_at(markets)
        assert result == []

    def test_all_pass(self) -> None:
        """Returns all markets when all are recent."""
        conn = _make_connection()
        markets = [
            {"id": "a", "createdAt": "2026-02-01T00:00:00Z"},
            {"id": "b", "createdAt": "2026-03-01T00:00:00Z"},
        ]
        result = conn._filter_markets_by_created_at(markets)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _filter_yes_no_markets
# ---------------------------------------------------------------------------


class TestFilterYesNoMarkets:
    """Tests for _filter_yes_no_markets."""

    def test_yes_no_market_passes(self) -> None:
        """Markets with Yes/No outcomes pass the filter."""
        conn = _make_connection()
        markets = [{"id": "yn", "outcomes": '["Yes", "No"]'}]
        result = conn._filter_yes_no_markets(markets)
        assert len(result) == 1

    def test_non_binary_market_filtered(self) -> None:
        """Markets with more than 2 outcomes are filtered out."""
        conn = _make_connection()
        markets = [{"id": "multi", "outcomes": '["A", "B", "C"]'}]
        result = conn._filter_yes_no_markets(markets)
        assert result == []

    def test_different_outcomes_filtered(self) -> None:
        """Markets without Yes/No pair are filtered out."""
        conn = _make_connection()
        markets = [{"id": "other", "outcomes": '["Option A", "Option B"]'}]
        result = conn._filter_yes_no_markets(markets)
        assert result == []

    def test_missing_outcomes_field_filtered(self) -> None:
        """Markets without 'outcomes' key are filtered out."""
        conn = _make_connection()
        markets = [{"id": "nofield"}]
        result = conn._filter_yes_no_markets(markets)
        assert result == []

    def test_invalid_json_in_outcomes_filtered(self) -> None:
        """Markets with invalid JSON in outcomes are filtered out."""
        conn = _make_connection()
        markets = [{"id": "bad", "outcomes": "not json {{"}]
        result = conn._filter_yes_no_markets(markets)
        assert result == []

    def test_case_insensitive_matching(self) -> None:
        """Matching is case-insensitive (yes/YES/Yes all accepted)."""
        conn = _make_connection()
        markets = [{"id": "ci", "outcomes": '["YES", "no"]'}]
        result = conn._filter_yes_no_markets(markets)
        assert len(result) == 1

    def test_empty_list(self) -> None:
        """Returns empty list when input is empty."""
        conn = _make_connection()
        result = conn._filter_yes_no_markets([])
        assert result == []


# ---------------------------------------------------------------------------
# _remove_duplicate_markets
# ---------------------------------------------------------------------------


class TestRemoveDuplicateMarkets:
    """Tests for _remove_duplicate_markets."""

    def test_removes_duplicates(self) -> None:
        """Only the first occurrence of each market ID is kept."""
        conn = _make_connection()
        markets = [
            {"id": "1", "slug": "first"},
            {"id": "2", "slug": "second"},
            {"id": "1", "slug": "duplicate"},
        ]
        result = conn._remove_duplicate_markets(markets)
        assert len(result) == 2
        assert result[0]["slug"] == "first"

    def test_no_id_market_skipped(self) -> None:
        """Markets without 'id' field are silently skipped."""
        conn = _make_connection()
        markets = [{"slug": "no_id"}]
        result = conn._remove_duplicate_markets(markets)
        assert result == []

    def test_empty_list(self) -> None:
        """Returns empty list when input is empty."""
        conn = _make_connection()
        result = conn._remove_duplicate_markets([])
        assert result == []

    def test_all_unique(self) -> None:
        """Returns all markets when there are no duplicates."""
        conn = _make_connection()
        markets = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = conn._remove_duplicate_markets(markets)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# _fetch_markets
# ---------------------------------------------------------------------------


class TestFetchMarkets:
    """Tests for _fetch_markets."""

    def test_successful_fetch_returns_markets_by_category(self) -> None:
        """Returns dict of category->markets with Yes/No + tradeable filtering applied.

        Markets that do NOT have Yes/No outcomes, that are too old, or that
        are untradeable must be excluded even if returned by the API.
        """
        conn = _make_connection()
        # Mix: one valid tradeable market and two that should be filtered out
        markets = [
            # passes all filters
            {
                "id": "m1",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": True,
                "_poly_tags": ["politics"],
            },
            # fails yes/no filter (multi-outcome)
            {
                "id": "m2",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["A","B","C"]',
                "outcomePrices": '["0.3","0.3","0.4"]',
                "clobTokenIds": '["t1","t2","t3"]',
                "active": True,
                "_poly_tags": ["politics"],
            },
            # fails createdAt filter (too old - empty string < MIN_CREATED_AT)
            {
                "id": "m3",
                "createdAt": "",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": True,
                "_poly_tags": ["politics"],
            },
        ]
        conn._fetch_markets_by_tag_slug = MagicMock(return_value=(markets, None))

        result, error = conn._fetch_markets()
        assert error is None
        assert isinstance(result, dict)
        # All categories attempted
        for cat in POLYMARKET_CATEGORY_TAGS:
            assert cat in result
        # Each category's list must contain only the one valid market
        for cat_markets in result.values():
            assert len(cat_markets) == 1
            assert cat_markets[0]["id"] == "m1"

    def test_markets_fetch_error_continues_other_categories(self) -> None:
        """Continues to next category when market fetch fails for one."""
        conn = _make_connection()
        # First category fails, rest succeed with empty list
        conn._fetch_markets_by_tag_slug = MagicMock(
            side_effect=[(None, "api error")]
            + [([], None)] * (len(POLYMARKET_CATEGORY_TAGS) - 1)
        )

        result, error = conn._fetch_markets()
        assert error is None
        # All categories with successful fetch (empty) should be present
        assert len(result) == len(POLYMARKET_CATEGORY_TAGS) - 1

    def test_unexpected_exception_returns_error(self) -> None:
        """Catches unexpected exceptions and returns error message."""
        conn = _make_connection()
        conn._fetch_markets_by_tag_slug = MagicMock(
            side_effect=RuntimeError("disk full")
        )

        result, error = conn._fetch_markets()
        assert result is None
        assert "Unexpected error" in error

    def test_fetch_markets_warns_on_full_tradeable_drop(self) -> None:
        """WARN when the tradeable filter drops 100% of a non-empty input.

        Guards against silent collapse if Polymarket ever changes how
        outcomePrices / clobTokenIds are encoded, or introduces a new
        lifecycle state that makes `active` falsy for every market.
        """
        conn = _make_connection()
        # Five yes/no markets, all inactive → tradeable filter drops all five.
        markets = [
            {
                "id": f"m{i}",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.5","0.5"]',
                "clobTokenIds": '["t1","t2"]',
                "active": False,
                "_poly_tags": ["politics"],
            }
            for i in range(5)
        ]
        conn._fetch_markets_by_tag_slug = MagicMock(return_value=(markets, None))

        result, error = conn._fetch_markets()
        assert error is None
        # Every category should have logged the 100% drop warning once.
        warning_calls = [
            c for c in conn.logger.warning.call_args_list if "dropped 100%" in str(c)
        ]
        assert len(warning_calls) == len(POLYMARKET_CATEGORY_TAGS)


# ---------------------------------------------------------------------------
# _fetch_markets_by_tag_slug (new /events-based fetcher)
# ---------------------------------------------------------------------------


class TestFetchMarketsByTagSlug:
    """Tests for _fetch_markets_by_tag_slug (the /events?tag_slug=X fetcher)."""

    def test_flattens_events_and_attaches_poly_tags(self) -> None:
        """Each event's tag slugs are attached to every child market as _poly_tags."""
        conn = _make_connection()
        events = [
            {
                "id": "e1",
                "tags": [{"slug": "politics"}, {"slug": "elections"}],
                "markets": [{"id": "m1"}, {"id": "m2"}],
            },
            {
                "id": "e2",
                "tags": [{"slug": "world"}],
                "markets": [{"id": "m3"}],
            },
        ]
        conn._request_with_retries = MagicMock(return_value=({"events": events}, None))

        result, error = conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )

        assert error is None
        assert len(result) == 3
        ids = [m["id"] for m in result]
        assert ids == ["m1", "m2", "m3"]
        assert result[0]["_poly_tags"] == ["politics", "elections"]
        assert result[1]["_poly_tags"] == ["politics", "elections"]
        assert result[2]["_poly_tags"] == ["world"]

    def test_paginates_until_next_cursor_absent(self) -> None:
        """Paginates /events/keyset until a response omits next_cursor."""
        from packages.valory.connections.polymarket_client.connection import (
            EVENTS_LIMIT,
        )

        page1 = [
            {"id": f"e{i}", "tags": [], "markets": [{"id": f"m{i}"}]}
            for i in range(EVENTS_LIMIT)
        ]
        page2 = [
            {"id": f"e{i}x", "tags": [], "markets": [{"id": f"m{i}x"}]}
            for i in range(3)
        ]
        conn = _make_connection()
        conn._request_with_retries = MagicMock(
            side_effect=[
                ({"events": page1, "next_cursor": "cursor-1"}, None),
                ({"events": page2}, None),
            ]
        )

        result, error = conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert error is None
        assert len(result) == EVENTS_LIMIT + 3
        # Second call must forward the cursor from page 1.
        second_call_params = conn._request_with_retries.call_args_list[1][1]["params"]
        assert second_call_params["after_cursor"] == "cursor-1"

    def test_empty_response_stops_pagination(self) -> None:
        """Empty events list stops pagination."""
        conn = _make_connection()
        conn._request_with_retries = MagicMock(return_value=({"events": []}, None))
        result, error = conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert result == []
        assert error is None

    def test_api_error_propagates(self) -> None:
        """Returns (None, error) on API error."""
        conn = _make_connection()
        conn._request_with_retries = MagicMock(return_value=(None, "boom"))
        result, error = conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert result is None
        assert error == "boom"

    def test_sends_correct_params_to_events_endpoint(self) -> None:
        """Hits /events/keyset with tag_slug, date window, limit, and no cursor on first call."""
        from packages.valory.connections.polymarket_client.connection import (
            EVENTS_LIMIT,
        )

        conn = _make_connection()
        conn._request_with_retries = MagicMock(return_value=({"events": []}, None))

        conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )

        call_args = conn._request_with_retries.call_args
        actual_url = call_args[0][0]
        actual_params = call_args[1]["params"]

        assert actual_url == f"{GAMMA_API_BASE_URL}/events/keyset"
        assert actual_params["tag_slug"] == "politics"
        assert actual_params["end_date_min"] == "2025-01-01T00:00:00Z"
        assert actual_params["end_date_max"] == "2025-01-05T00:00:00Z"
        assert actual_params["limit"] == EVENTS_LIMIT
        assert "offset" not in actual_params
        assert "after_cursor" not in actual_params

    def test_event_with_no_tags_yields_empty_poly_tags(self) -> None:
        """Markets under an event with no tags get _poly_tags=[] (not missing)."""
        conn = _make_connection()
        events = [{"id": "e1", "markets": [{"id": "m1"}]}]
        conn._request_with_retries = MagicMock(return_value=({"events": events}, None))

        result, error = conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert error is None
        assert result[0]["_poly_tags"] == []

    def test_event_with_no_markets_contributes_nothing(self) -> None:
        """An event without a markets list is skipped."""
        conn = _make_connection()
        events = [
            {"id": "e1", "tags": [{"slug": "x"}]},
            {"id": "e2", "tags": [{"slug": "y"}], "markets": [{"id": "m1"}]},
        ]
        conn._request_with_retries = MagicMock(return_value=({"events": events}, None))

        result, error = conn._fetch_markets_by_tag_slug(
            "politics", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert error is None
        assert len(result) == 1
        assert result[0]["id"] == "m1"


# ---------------------------------------------------------------------------
# _fetch_market_by_slug
# ---------------------------------------------------------------------------


class TestFetchMarketBySlug:
    """Tests for _fetch_market_by_slug."""

    def test_success(self) -> None:
        """Returns market data on successful request."""
        conn = _make_connection()
        market_data = {"id": "m1", "slug": "test-market"}
        mock_response = MagicMock()
        mock_response.json.return_value = market_data

        with patch("requests.get", return_value=mock_response):
            result, error = conn._fetch_market_by_slug("test-market")

        assert result == market_data
        assert error is None

    def test_request_exception_returns_error(self) -> None:
        """Returns error on RequestException."""
        conn = _make_connection()
        with patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("timeout"),
        ):
            result, error = conn._fetch_market_by_slug("test-market")

        assert result is None
        assert "Error fetching market by slug" in error

    def test_generic_exception_returns_error(self) -> None:
        """Returns error on unexpected exception."""
        conn = _make_connection()
        with patch("requests.get", side_effect=RuntimeError("oops")):
            result, error = conn._fetch_market_by_slug("test-market")

        assert result is None
        assert "Unexpected error" in error

    def test_url_includes_slug_parameter(self) -> None:
        """_fetch_market_by_slug uses GAMMA_API_BASE_URL/markets/slug/{slug}.

        The slug is part of the URL path, not a query parameter. Placing the slug
        in the wrong location would silently return no results or 404.
        """
        conn = _make_connection()
        slug = "my-test-market"
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "m1"}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._fetch_market_by_slug(slug)

        url_called = mock_get.call_args[0][0]
        assert url_called == f"{GAMMA_API_BASE_URL}/markets/slug/{slug}"


# ---------------------------------------------------------------------------
# _get_positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    """Tests for _get_positions."""

    def test_returns_positions(self) -> None:
        """Returns list of positions on success."""
        conn = _make_connection()
        positions = [{"token": "tok1", "size": 10}]  # nosec B105
        mock_resp = MagicMock()
        mock_resp.json.return_value = positions
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp):
            result, error = conn._get_positions()

        assert result == positions
        assert error is None

    def test_includes_redeemable_param_when_set(self) -> None:
        """Includes 'redeemable' in params when explicitly provided."""
        conn = _make_connection()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._get_positions(redeemable=True)

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["redeemable"] is True

    def test_excludes_redeemable_when_none(self) -> None:
        """Does not include 'redeemable' in params when it is None."""
        conn = _make_connection()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._get_positions(redeemable=None)

        call_kwargs = mock_get.call_args[1]
        assert "redeemable" not in call_kwargs["params"]

    def test_safe_address_sent_as_user_param(self) -> None:
        """The safe address is passed as the 'user' query parameter."""
        conn = _make_connection()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._get_positions()

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["user"] == SAFE_ADDRESS

    def test_request_exception_returns_error(self) -> None:
        """Returns (None, error) on RequestException."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        with patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("fail"),
        ):
            result, error = conn._get_positions()

        assert result is None
        assert "Error fetching positions" in error

    def test_generic_exception_returns_error(self) -> None:
        """Returns (None, error) on generic Exception."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        with patch("requests.get", side_effect=RuntimeError("oops")):
            result, error = conn._get_positions()

        assert result is None
        assert "Unexpected error" in error

    def test_uses_data_api_positions_url(self) -> None:
        """_get_positions fetches from DATA_API_BASE_URL/positions, not a different base URL."""
        conn = _make_connection()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._get_positions()

        url_called = mock_get.call_args[0][0]
        assert url_called == f"{DATA_API_BASE_URL}/positions"


# ---------------------------------------------------------------------------
# _fetch_all_positions
# ---------------------------------------------------------------------------


class TestFetchAllPositions:
    """Tests for _fetch_all_positions."""

    def test_single_page(self) -> None:
        """Returns all positions when they fit in a single page."""
        conn = _make_connection()
        positions = [{"id": f"p{i}"} for i in range(10)]
        conn._get_positions = MagicMock(return_value=(positions, None))

        result, error = conn._fetch_all_positions()
        assert len(result) == 10
        assert error is None

    def test_multiple_pages(self) -> None:
        """Paginates and concatenates results from multiple pages."""
        conn = _make_connection()
        page1 = [{"id": f"p{i}"} for i in range(100)]
        page2 = [{"id": f"p{i}"} for i in range(5)]
        conn._get_positions = MagicMock(side_effect=[(page1, None), (page2, None)])

        result, error = conn._fetch_all_positions()
        assert len(result) == 105
        assert error is None

    def test_error_propagates(self) -> None:
        """Returns (None, error) when _get_positions fails."""
        conn = _make_connection()
        conn._get_positions = MagicMock(return_value=(None, "API error"))

        result, error = conn._fetch_all_positions()
        assert result is None
        assert error == "API error"

    def test_empty_positions(self) -> None:
        """Returns empty list when no positions exist."""
        conn = _make_connection()
        conn._get_positions = MagicMock(return_value=([], None))

        result, error = conn._fetch_all_positions()
        assert result == []
        assert error is None

    def test_generic_exception_returns_error(self) -> None:
        """Catches generic exceptions and returns error."""
        conn = _make_connection()
        conn._get_positions = MagicMock(side_effect=RuntimeError("crash"))

        result, error = conn._fetch_all_positions()
        assert result is None
        assert "Unexpected error" in error


# ---------------------------------------------------------------------------
# _get_trades
# ---------------------------------------------------------------------------


class TestGetTrades:
    """Tests for _get_trades."""

    def test_returns_trades(self) -> None:
        """Returns list of trades on success."""
        conn = _make_connection()
        trades = [{"conditionId": "cid1"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = trades
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp):
            result, error = conn._get_trades()

        assert result == trades
        assert error is None

    def test_safe_address_and_taker_only_params_sent(self) -> None:
        """safe_address is sent as 'user' and taker_only as 'takerOnly'."""
        conn = _make_connection()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._get_trades(taker_only=False)

        call_kwargs = mock_get.call_args[1]
        assert call_kwargs["params"]["user"] == SAFE_ADDRESS
        assert call_kwargs["params"]["takerOnly"] is False

    def test_request_exception_returns_error(self) -> None:
        """Returns (None, error) on RequestException."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        with patch(
            "requests.get",
            side_effect=requests.exceptions.RequestException("fail"),
        ):
            result, error = conn._get_trades()

        assert result is None
        assert "Error fetching trades" in error

    def test_generic_exception_returns_error(self) -> None:
        """Returns (None, error) on generic Exception."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        with patch("requests.get", side_effect=RuntimeError("oops")):
            result, error = conn._get_trades()

        assert result is None
        assert "Unexpected error" in error

    def test_uses_data_api_trades_url(self) -> None:
        """_get_trades fetches from DATA_API_BASE_URL/trades, not a different base URL."""
        conn = _make_connection()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}

        with patch("requests.get", return_value=mock_resp) as mock_get:
            conn._get_trades()

        url_called = mock_get.call_args[0][0]
        assert url_called == f"{DATA_API_BASE_URL}/trades"


# ---------------------------------------------------------------------------
# _fetch_all_trades
# ---------------------------------------------------------------------------


class TestFetchAllTrades:
    """Tests for _fetch_all_trades."""

    def test_single_page(self) -> None:
        """Returns all trades from a single page."""
        conn = _make_connection()
        trades = [{"conditionId": f"c{i}"} for i in range(10)]
        conn._get_trades = MagicMock(return_value=(trades, None))

        result, error = conn._fetch_all_trades()
        assert len(result) == 10
        assert error is None

    def test_multiple_pages(self) -> None:
        """Paginates and concatenates results."""
        conn = _make_connection()
        page1 = [{"conditionId": f"c{i}"} for i in range(100)]
        page2 = [{"conditionId": f"c{i}"} for i in range(50)]
        conn._get_trades = MagicMock(side_effect=[(page1, None), (page2, None)])

        result, error = conn._fetch_all_trades()
        assert len(result) == 150
        assert error is None

    def test_empty_trades(self) -> None:
        """Returns empty list when no trades exist."""
        conn = _make_connection()
        conn._get_trades = MagicMock(return_value=([], None))

        result, error = conn._fetch_all_trades()
        assert result == []
        assert error is None

    def test_error_propagates(self) -> None:
        """Returns (None, error) when _get_trades fails."""
        conn = _make_connection()
        conn._get_trades = MagicMock(return_value=(None, "fetch error"))

        result, error = conn._fetch_all_trades()
        assert result is None
        assert error == "fetch error"

    def test_generic_exception_returns_error(self) -> None:
        """Catches generic exceptions and returns error."""
        conn = _make_connection()
        conn._get_trades = MagicMock(side_effect=RuntimeError("crash"))

        result, error = conn._fetch_all_trades()
        assert result is None
        assert "Unexpected error" in error

    def test_full_page_triggers_next_page_fetch(self) -> None:
        """A full page (limit items) causes another request; an empty page stops pagination."""
        conn = _make_connection()
        # Return exactly 100 items (limit), triggering a follow-up request
        page1 = [{"conditionId": f"c{i}"} for i in range(100)]
        conn._get_trades = MagicMock(side_effect=[(page1, None), ([], None)])

        result, error = conn._fetch_all_trades()
        # Both pages fetched; empty second page ends pagination
        assert conn._get_trades.call_count == 2
        assert len(result) == 100
        assert error is None


# ---------------------------------------------------------------------------
# _redeem_positions
# ---------------------------------------------------------------------------


class TestRedeemPositions:
    """Tests for _redeem_positions."""

    def test_standard_market_success(self) -> None:
        """Redeems standard market positions successfully."""
        conn = _make_connection()
        tx_data = {"hash": "0xabc"}
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = tx_data
        conn.relayer_client.execute.return_value = result_mock

        result, error = conn._redeem_positions(
            condition_id="0x" + "ab" * 32,
            index_sets=[1, 2],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=False,
        )
        assert result == tx_data
        assert error is None
        conn.relayer_client.execute.assert_called_once()

    def test_neg_risk_market_success(self) -> None:
        """Redeems negative risk market positions successfully."""
        conn = _make_connection()
        tx_data = {"hash": "0xdef"}
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = tx_data
        conn.relayer_client.execute.return_value = result_mock

        result, error = conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[2],  # 2 = 1 << 1 -> outcome_index=1
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=True,
            size=100.0,
        )
        assert result == tx_data
        assert error is None

    def test_neg_risk_index_set_1_outcome_0(self) -> None:
        """index_sets=[1] maps to outcome_index=0 for neg risk."""
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        result, error = conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],  # 1 = 1 << 0 -> outcome_index=0
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=True,
            size=50.0,
        )
        assert error is None

    def test_neg_risk_empty_index_sets(self) -> None:
        """Empty index_sets handled gracefully for neg risk."""
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        result, error = conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=True,
            size=50.0,
        )
        assert error is None

    def test_no_relayer_client_returns_error(self) -> None:
        """Returns error when relayer_client is None."""
        conn = _make_connection()
        conn.relayer_client = None

        result, error = conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
        )
        assert result is None
        assert "not initialized" in error

    def test_exception_returns_error(self) -> None:
        """Returns (None, error) on generic exception."""
        conn = _make_connection()
        conn.relayer_client.execute.side_effect = RuntimeError("relay error")

        result, error = conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
        )
        assert result is None
        assert "Error redeeming positions" in error

    def test_standard_market_calldata_uses_ctf_selector(self) -> None:
        """Standard market uses 4-byte selector 01b7037c (redeemPositions(address,bytes32,bytes32,uint256[])).

        An incorrect selector would silently submit a no-op or wrong function call on-chain.
        The expected selector is independently computed from the ABI signature.
        """
        from eth_hash.auto import keccak

        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=False,
        )

        expected = keccak(b"redeemPositions(address,bytes32,bytes32,uint256[])")[
            :4
        ].hex()
        assert expected == "01b7037c"
        tx = conn.relayer_client.execute.call_args[1]["transactions"][0]
        assert tx.data[2:10] == expected

    def test_neg_risk_calldata_uses_adapter_selector(self) -> None:
        """Neg-risk market uses 4-byte selector dbeccb23 (redeemPositions(bytes32,uint256[])).

        The neg-risk adapter takes different arguments than the standard CTF contract.
        Using the wrong selector would silently fail on-chain.
        """
        from eth_hash.auto import keccak

        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=True,
            size=10.0,
        )

        expected = keccak(b"redeemPositions(bytes32,uint256[])")[:4].hex()
        assert expected == "dbeccb23"
        tx = conn.relayer_client.execute.call_args[1]["transactions"][0]
        assert tx.data[2:10] == expected

    def test_condition_id_0x_prefix_stripped(self) -> None:
        """A 0x-prefixed and non-prefixed condition_id produce identical calldata.

        The code calls removeprefix('0x') so both forms are normalised before
        encoding. This prevents silent calldata corruption when the caller uses
        0x-prefixed hex strings.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._redeem_positions(
            condition_id="0x" + "ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=False,
        )
        tx_with_prefix = conn.relayer_client.execute.call_args[1]["transactions"][0]

        conn.relayer_client.reset_mock()
        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=False,
        )
        tx_without_prefix = conn.relayer_client.execute.call_args[1]["transactions"][0]

        assert tx_with_prefix.data == tx_without_prefix.data

    def test_standard_market_targets_ctf_collateral_adapter(self) -> None:
        """Standard market redeem must target CtfCollateralAdapter, not raw CTF.

        Routing through the adapter unwraps USDC.e to pUSD inside the same
        transaction, so the Safe receives pUSD directly.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=False,
        )

        tx = conn.relayer_client.execute.call_args[1]["transactions"][0]
        assert tx.to == CTF_COLLATERAL_ADAPTER

    def test_neg_risk_targets_neg_risk_ctf_collateral_adapter(self) -> None:
        """Neg-risk redeem must target NegRiskCtfCollateralAdapter, not raw NegRiskAdapter."""
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=True,
            size=10.0,
        )

        tx = conn.relayer_client.execute.call_args[1]["transactions"][0]
        assert tx.to == NEG_RISK_CTF_COLLATERAL_ADAPTER

    def test_neg_risk_correct_redeem_amounts_for_outcome_1(self) -> None:
        """index_sets=[2] (1<<1) maps to outcome_index=1, yielding redeem_amounts=[0, size].

        The ABI encoding must place the amount at position 1 (the No outcome),
        not position 0. A bit-shift calculation error would silently redeem the
        wrong outcome.
        """
        from eth_abi import decode as abi_decode

        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[2],  # 2 = 1 << 1 → outcome_index = 1
            collateral_token=COLLATERAL_ADDRESS,
            is_neg_risk=True,
            size=50.0,
        )

        tx = conn.relayer_client.execute.call_args[1]["transactions"][0]
        # Skip "0x" and 4-byte selector, then ABI-decode the remaining args
        calldata_bytes = bytes.fromhex(tx.data[2:])
        args_bytes = calldata_bytes[4:]  # skip 4-byte selector
        _condition_id, redeem_amounts = abi_decode(["bytes32", "uint256[]"], args_bytes)
        assert list(redeem_amounts) == [0, 50]


# ---------------------------------------------------------------------------
# _encode_approve / _encode_set_approval_for_all
# ---------------------------------------------------------------------------


class TestEncodingMethods:
    """Tests for _encode_approve and _encode_set_approval_for_all."""

    def test_encode_approve_returns_correct_selector(self) -> None:
        """_encode_approve uses the ERC-20 approve(address,uint256) 4-byte selector.

        The selector is the first 4 bytes of keccak256('approve(address,uint256)').
        Encoding the wrong function signature would silently submit a no-op on-chain.
        """
        from eth_hash.auto import keccak

        conn = _make_connection()
        result = conn._encode_approve(CTF_EXCHANGE, MAX_UINT256)
        assert isinstance(result, str)
        assert result.startswith("0x")
        # Independently compute the expected 4-byte selector
        expected_selector = keccak(b"approve(address,uint256)")[:4].hex()
        # The selector must appear immediately after "0x"
        assert result[2:10] == expected_selector

    def test_encode_approve_deterministic(self) -> None:
        """Same inputs produce same encoding."""
        conn = _make_connection()
        r1 = conn._encode_approve(CTF_EXCHANGE, 1000)
        r2 = conn._encode_approve(CTF_EXCHANGE, 1000)
        assert r1 == r2

    def test_encode_approve_different_amounts_differ(self) -> None:
        """Different amounts produce different encodings."""
        conn = _make_connection()
        r1 = conn._encode_approve(CTF_EXCHANGE, 1000)
        r2 = conn._encode_approve(CTF_EXCHANGE, 2000)
        assert r1 != r2

    def test_encode_set_approval_for_all_returns_correct_selector(self) -> None:
        """_encode_set_approval_for_all uses the ERC-1155 setApprovalForAll(address,bool) selector.

        Wrong selector would silently submit a no-op transaction on-chain.
        """
        from eth_hash.auto import keccak

        conn = _make_connection()
        result = conn._encode_set_approval_for_all(CTF_EXCHANGE, True)
        assert isinstance(result, str)
        assert result.startswith("0x")
        # Independently compute the expected 4-byte selector
        expected_selector = keccak(b"setApprovalForAll(address,bool)")[:4].hex()
        assert result[2:10] == expected_selector

    def test_encode_set_approval_for_all_approved_vs_revoked(self) -> None:
        """True and False produce different encodings."""
        conn = _make_connection()
        r_approved = conn._encode_set_approval_for_all(CTF_EXCHANGE, True)
        r_revoked = conn._encode_set_approval_for_all(CTF_EXCHANGE, False)
        assert r_approved != r_revoked


# ---------------------------------------------------------------------------
# _set_approval
# ---------------------------------------------------------------------------


class TestSetApproval:
    """Tests for _set_approval."""

    def test_success(self) -> None:
        """Executes 8 approval transactions and returns transaction data."""
        conn = _make_connection()
        tx_data = {"hash": "0xabc"}
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = tx_data
        conn.relayer_client.execute.return_value = result_mock

        result, error = conn._set_approval()
        assert result == tx_data
        assert error is None

        # 8 transactions: the original 6 (collateral×3 + CTF×3 for v2 Exchange,
        # NegRisk Exchange, NegRiskAdapter) plus 2 ERC-1155 setApprovalForAll
        # for the CtfCollateralAdapter / NegRiskCtfCollateralAdapter pair.
        # No pUSD allowances are granted to the collateral adapters: their
        # redeem path doesn't pull ERC-20 from the Safe.
        call_kwargs = conn.relayer_client.execute.call_args[1]
        assert len(call_kwargs["transactions"]) == 8

    def test_no_relayer_client_returns_error(self) -> None:
        """Returns error when relayer_client is None."""
        conn = _make_connection()
        conn.relayer_client = None

        result, error = conn._set_approval()
        assert result is None
        assert "not initialized" in error

    def test_exception_returns_error(self) -> None:
        """Returns (None, error) on generic exception."""
        conn = _make_connection()
        conn.relayer_client.execute.side_effect = RuntimeError("relay error")

        result, error = conn._set_approval()
        assert result is None
        assert "Error setting approvals" in error

    def test_usdc_approve_transactions_target_usdc_contract(self) -> None:
        """ERC-20 approve transactions all target the collateral contract.

        These are the `approve(spender, MAX_UINT256)` calls — 3 in total, one
        per spender (CTF Exchange, NegRisk Exchange, NegRiskAdapter).
        Targeting the wrong contract would grant allowances to the wrong
        token address. The collateral adapters intentionally receive no
        ERC-20 allowance — only ERC-1155 operator rights.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._set_approval()

        txns = conn.relayer_client.execute.call_args[1]["transactions"]
        for idx in [0, 2, 4]:
            assert txns[idx].to == COLLATERAL_ADDRESS, f"txns[{idx}].to should be pUSD"

    def test_ctf_approval_transactions_target_ctf_contract(self) -> None:
        """ERC-1155 setApprovalForAll transactions all target the CTF contract.

        Five `setApprovalForAll(operator, True)` calls — one per operator
        (CTF Exchange, NegRisk Exchange, NegRiskAdapter, CtfCollateralAdapter,
        NegRiskCtfCollateralAdapter). Targeting the wrong contract would grant
        operator access on the wrong token.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._set_approval()

        txns = conn.relayer_client.execute.call_args[1]["transactions"]
        for idx in [1, 3, 5, 6, 7]:
            assert txns[idx].to == CTF_ADDRESS, f"txns[{idx}].to should be CTF"

    def test_includes_collateral_adapter_setapprovalforall(self) -> None:
        """The redeem-critical CTF.setApprovalForAll(adapter, true) is included for both adapters.

        Without ERC-1155 operator rights for the collateral adapters on the
        CTF, the adapters can't burn the Safe's position tokens during redeem
        and the call silently emits PayoutRedemption with payout=0.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._set_approval()

        txns = conn.relayer_client.execute.call_args[1]["transactions"]
        ctf_setApprovalForAll_selector = "0xa22cb465"
        ctf_op_targets = {
            t.data
            for t in txns
            if t.to == CTF_ADDRESS and t.data.startswith(ctf_setApprovalForAll_selector)
        }
        # Each setApprovalForAll(operator, true) calldata embeds the operator
        # address in the second 32-byte arg; check both adapters appear.
        assert any(
            CTF_COLLATERAL_ADAPTER[2:].lower() in d.lower() for d in ctf_op_targets
        ), "CtfCollateralAdapter setApprovalForAll missing"
        assert any(
            NEG_RISK_CTF_COLLATERAL_ADAPTER[2:].lower() in d.lower()
            for d in ctf_op_targets
        ), "NegRiskCtfCollateralAdapter setApprovalForAll missing"


# ---------------------------------------------------------------------------
# _check_erc20_allowance / _check_erc1155_approval
# ---------------------------------------------------------------------------


class TestOnChainChecks:
    """Tests for _check_erc20_allowance and _check_erc1155_approval."""

    def test_check_erc20_allowance(self) -> None:
        """Returns allowance as integer from eth_call."""
        conn = _make_connection()
        # Return 32 bytes representing uint256 = 1000
        allowance_bytes = (1000).to_bytes(32, byteorder="big")
        conn.w3.keccak.return_value = b"\x12\x34\x56\x78" + b"\x00" * 28
        conn.w3.to_checksum_address.return_value = COLLATERAL_ADDRESS
        conn.w3.eth.call.return_value = allowance_bytes

        result = conn._check_erc20_allowance(
            COLLATERAL_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE
        )
        assert result == 1000

    def test_check_erc1155_approval_true(self) -> None:
        """Returns True when eth_call returns 1."""
        conn = _make_connection()
        approved_bytes = (1).to_bytes(32, byteorder="big")
        conn.w3.keccak.return_value = b"\x12\x34\x56\x78" + b"\x00" * 28
        conn.w3.to_checksum_address.return_value = CTF_ADDRESS
        conn.w3.eth.call.return_value = approved_bytes

        result = conn._check_erc1155_approval(CTF_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)
        assert result is True

    def test_check_erc1155_approval_false(self) -> None:
        """Returns False when eth_call returns 0."""
        conn = _make_connection()
        not_approved_bytes = (0).to_bytes(32, byteorder="big")
        conn.w3.keccak.return_value = b"\x12\x34\x56\x78" + b"\x00" * 28
        conn.w3.to_checksum_address.return_value = CTF_ADDRESS
        conn.w3.eth.call.return_value = not_approved_bytes

        result = conn._check_erc1155_approval(CTF_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)
        assert result is False

    def test_check_erc20_allowance_calls_keccak_with_correct_signature(self) -> None:
        """_check_erc20_allowance calls w3.keccak with the exact ERC-20 allowance signature.

        Using the wrong ABI signature would produce an incorrect function selector,
        silently reading data from the wrong on-chain storage slot.
        """
        conn = _make_connection()
        conn.w3.keccak.return_value = b"\x12\x34\x56\x78" + b"\x00" * 28
        conn.w3.to_checksum_address.return_value = COLLATERAL_ADDRESS
        conn.w3.eth.call.return_value = (1000).to_bytes(32, byteorder="big")

        conn._check_erc20_allowance(COLLATERAL_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)

        conn.w3.keccak.assert_called_once_with(text="allowance(address,address)")

    def test_check_erc1155_approval_calls_keccak_with_correct_signature(self) -> None:
        """_check_erc1155_approval calls w3.keccak with the exact ERC-1155 signature.

        Using the wrong ABI signature would produce an incorrect selector and
        silently return stale or zero data instead of the real approval state.
        """
        conn = _make_connection()
        conn.w3.keccak.return_value = b"\x12\x34\x56\x78" + b"\x00" * 28
        conn.w3.to_checksum_address.return_value = CTF_ADDRESS
        conn.w3.eth.call.return_value = (1).to_bytes(32, byteorder="big")

        conn._check_erc1155_approval(CTF_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)

        conn.w3.keccak.assert_called_once_with(text="isApprovedForAll(address,address)")

    def test_check_erc1155_non_one_value_returns_false(self) -> None:
        """Any return value other than exactly 1 is treated as not approved.

        The ERC-1155 spec returns 1 for approved; the check is `== 1`. A value
        like 2 must not be treated as approved.
        """
        conn = _make_connection()
        conn.w3.keccak.return_value = b"\x12\x34\x56\x78" + b"\x00" * 28
        conn.w3.to_checksum_address.return_value = CTF_ADDRESS
        conn.w3.eth.call.return_value = (2).to_bytes(32, byteorder="big")

        result = conn._check_erc1155_approval(CTF_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)
        assert result is False


# ---------------------------------------------------------------------------
# _check_approval
# ---------------------------------------------------------------------------


class TestCheckApproval:
    """Tests for _check_approval."""

    def test_all_approvals_set(self) -> None:
        """Returns approval_status dict with all_approvals_set=True."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        conn._check_erc20_allowance = MagicMock(return_value=MAX_UINT256)
        conn._check_erc1155_approval = MagicMock(return_value=True)

        result, error = conn._check_approval()
        assert error is None
        assert result["all_approvals_set"] is True
        assert result["safe_address"] == SAFE_ADDRESS

    def test_some_approvals_missing(self) -> None:
        """Returns all_approvals_set=False when some approvals are missing."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        conn._check_erc20_allowance = MagicMock(return_value=0)  # no allowance
        conn._check_erc1155_approval = MagicMock(return_value=False)

        result, error = conn._check_approval()
        assert error is None
        assert result["all_approvals_set"] is False

    def test_partial_approvals(self) -> None:
        """Returns partial approval status correctly."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        # 3 USDC allowance checks: CTF Exchange, NegRisk Exchange, NegRiskAdapter.
        conn._check_erc20_allowance = MagicMock(
            side_effect=[MAX_UINT256, 0, MAX_UINT256]
        )
        # 5 ERC-1155 approval checks: CTF Exchange, NegRisk Exchange,
        # NegRiskAdapter, CtfCollateralAdapter, NegRiskCtfCollateralAdapter.
        conn._check_erc1155_approval = MagicMock(
            side_effect=[True, False, True, True, True]
        )

        result, error = conn._check_approval()
        assert error is None
        assert result["all_approvals_set"] is False
        assert result["usdc_allowances"]["ctf_exchange"] == MAX_UINT256
        assert result["usdc_allowances"]["neg_risk_ctf_exchange"] == 0
        assert result["ctf_approvals"]["ctf_collateral_adapter"] is True
        assert result["ctf_approvals"]["neg_risk_ctf_collateral_adapter"] is True

    def test_exception_returns_error(self) -> None:
        """Returns (None, error) on generic exception."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        conn._check_erc20_allowance = MagicMock(side_effect=RuntimeError("web3 fail"))

        result, error = conn._check_approval()
        assert result is None
        assert "Error checking approvals" in error

    def test_usdc_allowances_and_ctf_approvals_structure(self) -> None:
        """Response dict contains expected keys."""
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        conn._check_erc20_allowance = MagicMock(return_value=100)
        conn._check_erc1155_approval = MagicMock(return_value=True)

        result, _ = conn._check_approval()
        assert "usdc_allowances" in result
        assert "ctf_approvals" in result
        assert "ctf_exchange" in result["usdc_allowances"]
        assert "neg_risk_ctf_exchange" in result["usdc_allowances"]
        assert "neg_risk_adapter" in result["usdc_allowances"]
        # Collateral adapters intentionally absent from usdc_allowances —
        # they receive only ERC-1155 operator rights.
        assert "ctf_collateral_adapter" not in result["usdc_allowances"]
        assert "neg_risk_ctf_collateral_adapter" not in result["usdc_allowances"]
        assert "ctf_exchange" in result["ctf_approvals"]
        assert "neg_risk_ctf_exchange" in result["ctf_approvals"]
        assert "neg_risk_adapter" in result["ctf_approvals"]
        assert "ctf_collateral_adapter" in result["ctf_approvals"]
        assert "neg_risk_ctf_collateral_adapter" in result["ctf_approvals"]

    def test_allowance_of_1_passes_approval_check(self) -> None:
        """An allowance of exactly 1 satisfies the > 0 threshold for all_approvals_set.

        The threshold is `> 0`, NOT `== MAX_UINT256`. A non-maximum but positive
        allowance must not be treated as unapproved.
        """
        conn = _make_connection()
        conn.configuration.config.get.return_value = {"polygon": SAFE_ADDRESS}
        conn._check_erc20_allowance = MagicMock(
            return_value=1
        )  # minimal positive allowance
        conn._check_erc1155_approval = MagicMock(return_value=True)

        result, error = conn._check_approval()
        assert error is None
        assert result["all_approvals_set"] is True


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Resilience audit: BUG 5 -- JSONDecodeError bypasses retry logic
# ---------------------------------------------------------------------------


class TestRequestWithRetriesJsonDecodeError:
    """BUG 5: _request_with_retries catches RequestException but not JSONDecodeError.

    When Gamma API returns HTTP 200 with non-JSON body (e.g. HTML from CDN),
    response.json() raises json.JSONDecodeError (a ValueError subclass).
    This escapes the except clause and bypasses all retries.
    """

    def test_json_decode_error_caught_and_retried(self) -> None:
        """Verify JSONDecodeError from response.json() is caught alongside RequestException.

        A 200 response with non-JSON body (e.g. HTML from CDN) triggers retries
        and returns (None, error_msg) after exhausting attempts.
        """
        conn = _make_connection()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with (
            patch(
                "packages.valory.connections.polymarket_client.connection.requests.get",
                return_value=mock_response,
            ),
            patch(
                "packages.valory.connections.polymarket_client.connection.time.sleep",
            ),
        ):
            result, error = conn._request_with_retries("https://example.com/api")

        assert result is None
        assert error is not None


class TestFetchMarketBySlugJsonDecodeError:
    """BUG 5b: _fetch_market_by_slug has same JSONDecodeError gap.

    Unlike _request_with_retries, this method has a broad ``except Exception``
    fallback, so it won't crash -- but it still doesn't retry.
    """

    def test_json_decode_error_caught_by_broad_except(self) -> None:
        """Verify JSONDecodeError is caught by the broad except, returns (None, error_msg)."""
        conn = _make_connection()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)

        with patch(
            "packages.valory.connections.polymarket_client.connection.requests.get",
            return_value=mock_response,
        ):
            result, error = conn._fetch_market_by_slug("some-slug")

        assert result is None
        assert error is not None


# ---------------------------------------------------------------------------
# Resilience audit: BUG 22 -- json.loads outside try-except in on_send
# ---------------------------------------------------------------------------


class TestOnSendMalformedPayload:
    """BUG 22: json.loads(srr_message.payload) at line 253 is outside try-except.

    A malformed SRR payload raises JSONDecodeError in on_send(). No error
    response is sent. The agent behaviour waits forever for a response.
    """

    def test_malformed_payload_sends_error_response(self) -> None:
        """Malformed SRR payload is caught and an error response is sent."""
        from packages.valory.protocols.srr.message import SrrMessage

        conn = _make_connection()
        envelope = MagicMock()
        envelope.sender = "sender_address"
        envelope.to = "receiver_address"
        message = MagicMock(spec=SrrMessage)
        message.performative = SrrMessage.Performative.REQUEST
        message.payload = "not valid json{{"
        envelope.message = message

        dialogue_mock = MagicMock()
        response_msg = MagicMock(spec=SrrMessage)
        response_msg.to = "sender_address"
        response_msg.sender = "receiver_address"
        dialogue_mock.reply.return_value = response_msg
        conn.dialogues.update.return_value = dialogue_mock
        conn.put_envelope = MagicMock()

        # No exception -- error is handled gracefully
        conn.on_send(envelope)

        conn.logger.error.assert_called_once()
        conn.put_envelope.assert_called_once()
        # Verify error flag is set in the response
        reply_kwargs = dialogue_mock.reply.call_args
        assert reply_kwargs[1]["error"] is True


# ---------------------------------------------------------------------------
# Fetch Order Book
# ---------------------------------------------------------------------------


class TestFetchOrderBook:
    """Tests for _fetch_order_book handler."""

    def test_success(self) -> None:
        """Mock client returns order book with asks and bids."""
        conn = _make_connection()
        ask = MagicMock()
        ask.price = "0.55"
        ask.size = "100"
        bid = MagicMock()
        bid.price = "0.45"
        bid.size = "50"
        order_book = MagicMock()
        order_book.asks = [ask]
        order_book.bids = [bid]
        order_book.min_order_size = "5"
        conn.client.get_order_book.return_value = order_book

        result, error = conn._fetch_order_book("token_123")

        conn.client.get_order_book.assert_called_once_with("token_123")
        assert error is None
        assert result == {
            "asks": [{"price": "0.55", "size": "100"}],
            "bids": [{"price": "0.45", "size": "50"}],
            "min_order_size": "5",
        }

    def test_empty_book(self) -> None:
        """Empty asks and bids return empty lists."""
        conn = _make_connection()
        order_book = MagicMock()
        order_book.asks = []
        order_book.bids = []
        order_book.min_order_size = "5"
        conn.client.get_order_book.return_value = order_book

        result, error = conn._fetch_order_book("token_123")

        assert error is None
        assert result == {"asks": [], "bids": [], "min_order_size": "5"}

    def test_none_min_order_size(self) -> None:
        """None min_order_size returns None."""
        conn = _make_connection()
        order_book = MagicMock()
        order_book.asks = []
        order_book.bids = []
        order_book.min_order_size = None
        conn.client.get_order_book.return_value = order_book

        result, error = conn._fetch_order_book("token_123")

        assert error is None
        assert result["min_order_size"] is None

    def test_none_asks_bids(self) -> None:
        """None asks/bids are treated as empty lists."""
        conn = _make_connection()
        order_book = MagicMock()
        order_book.asks = None
        order_book.bids = None
        order_book.min_order_size = None
        conn.client.get_order_book.return_value = order_book

        result, error = conn._fetch_order_book("token_123")

        assert error is None
        assert result == {"asks": [], "bids": [], "min_order_size": None}

    def test_client_exception(self) -> None:
        """Client exception returns None with error message."""
        conn = _make_connection()
        conn.client.get_order_book.side_effect = Exception("API timeout")

        result, error = conn._fetch_order_book("token_123")

        assert result is None
        assert "API timeout" in error

    def test_v2_dict_response(self) -> None:
        """v2 ``get_order_book`` returns a plain dict with dict levels.

        Post-cutover this is the live path; the v1-attribute branch exists
        only for compatibility. Both the outer-dict branch and the nested
        ``_level_to_dict`` dict branch must handle it.
        """
        conn = _make_connection()
        conn.client.get_order_book.return_value = {
            "asks": [{"price": "0.55", "size": "100"}],
            "bids": [{"price": "0.45", "size": "50"}],
            "min_order_size": "5",
        }

        result, error = conn._fetch_order_book("token_123")

        assert error is None
        assert result == {
            "asks": [{"price": "0.55", "size": "100"}],
            "bids": [{"price": "0.45", "size": "50"}],
            "min_order_size": "5",
        }

    def test_v2_dict_response_missing_keys(self) -> None:
        """v2 dict response with absent keys falls back to empty/None."""
        conn = _make_connection()
        conn.client.get_order_book.return_value = {}

        result, error = conn._fetch_order_book("token_123")

        assert error is None
        assert result == {"asks": [], "bids": [], "min_order_size": None}


# ---------------------------------------------------------------------------
# _validate_builder_code
# ---------------------------------------------------------------------------


class TestValidateBuilderCode:
    """Shape-check for the operator-supplied builder_code.

    A silently-accepted malformed builder_code misattributes every order's
    revenue share, so the shape check must reject anything that isn't a
    ``0x``-prefixed 66-char bytes32 and blank it out with a WARNING.
    """

    def test_empty_string_returns_empty_no_warning(self) -> None:
        """Empty input is the 'disabled' case — no validation, no warning."""
        logger = MagicMock()
        assert _validate_builder_code("", logger) == ""
        logger.warning.assert_not_called()

    def test_none_returns_empty_no_warning(self) -> None:
        """None is also the 'disabled' case — tolerated silently."""
        logger = MagicMock()
        assert _validate_builder_code(None, logger) == ""
        logger.warning.assert_not_called()

    def test_well_formed_bytes32_passes(self) -> None:
        """0x-prefixed 66-char input is returned unchanged with no warning."""
        logger = MagicMock()
        code = "0x" + "a" * 64
        assert _validate_builder_code(code, logger) == code
        logger.warning.assert_not_called()

    def test_missing_0x_prefix_blanks_and_warns(self) -> None:
        """A 66-char string without the 0x prefix must be rejected."""
        logger = MagicMock()
        code = "a" * 66
        assert _validate_builder_code(code, logger) == ""
        logger.warning.assert_called_once()

    def test_truncated_bytes32_blanks_and_warns(self) -> None:
        """A 0x-prefixed but short (<66 chars) string must be rejected."""
        logger = MagicMock()
        code = "0x" + "a" * 32
        assert _validate_builder_code(code, logger) == ""
        logger.warning.assert_called_once()

    def test_too_long_bytes32_blanks_and_warns(self) -> None:
        """A 0x-prefixed but over-length (>66 chars) string must be rejected."""
        logger = MagicMock()
        code = "0x" + "a" * 80
        assert _validate_builder_code(code, logger) == ""
        logger.warning.assert_called_once()

    def test_non_hex_chars_after_0x_blanks_and_warns(self) -> None:
        """0x-prefixed, right length, but non-hex body must be rejected.

        Without a hex-content check, a misconfigured env var like
        ``0xZZ…`` (or an accidental substitution) would pass the shape
        gate and silently produce orders with bad attribution.
        """
        logger = MagicMock()
        code = "0x" + "Z" * 64
        assert _validate_builder_code(code, logger) == ""
        logger.warning.assert_called_once()

    def test_whitespace_stripped_before_validation(self) -> None:
        """Leading/trailing whitespace is tolerated (paste-from-UI case)."""
        logger = MagicMock()
        inner = "0x" + "ab" * 32
        assert _validate_builder_code(f"  {inner}\n", logger) == inner
        logger.warning.assert_not_called()

    def test_mixed_case_hex_passes(self) -> None:
        """Mixed-case hex (e.g. checksummed) passes without forcing lowercase."""
        logger = MagicMock()
        code = "0x" + "AbCd" * 16
        assert _validate_builder_code(code, logger) == code
        logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# SignedOrderV2 serialize / deserialize
# ---------------------------------------------------------------------------


class TestSignedOrderV2RoundTrip:
    """Round-trip serialize/deserialize must preserve IntEnum field types."""

    @staticmethod
    def _fresh_signed_order() -> Any:
        from py_clob_client_v2.order_utils import Side
        from py_clob_client_v2.order_utils.model.order_data_v2 import SignedOrderV2
        from py_clob_client_v2.order_utils.model.signature_type_v2 import (
            SignatureTypeV2,
        )

        return SignedOrderV2(
            salt="1",
            maker="0x0000000000000000000000000000000000000001",
            signer="0x0000000000000000000000000000000000000002",
            tokenId="tok",
            makerAmount="10",
            takerAmount="5",
            side=Side.BUY,
            signatureType=SignatureTypeV2.POLY_GNOSIS_SAFE,
            timestamp="1700000000000",
            metadata="0x" + "00" * 32,
            builder="0x" + "00" * 32,
            expiration="0",
            signature="0xdeadbeef",
        )

    def test_deserialize_restores_side_enum(self) -> None:
        """Side field must be a Side instance after round-trip, not a raw int."""
        from py_clob_client_v2.order_utils import Side

        from packages.valory.connections.polymarket_client.connection import (
            _deserialize_signed_order_v2,
            _serialize_signed_order_v2,
        )

        fresh = self._fresh_signed_order()
        rehydrated = _deserialize_signed_order_v2(_serialize_signed_order_v2(fresh))
        assert isinstance(rehydrated.side, Side)
        assert rehydrated.side is Side.BUY

    def test_deserialize_restores_signature_type_enum(self) -> None:
        """The signatureType field must be a SignatureTypeV2 instance after round-trip."""
        from py_clob_client_v2.order_utils.model.signature_type_v2 import (
            SignatureTypeV2,
        )

        from packages.valory.connections.polymarket_client.connection import (
            _deserialize_signed_order_v2,
            _serialize_signed_order_v2,
        )

        fresh = self._fresh_signed_order()
        rehydrated = _deserialize_signed_order_v2(_serialize_signed_order_v2(fresh))
        assert isinstance(rehydrated.signatureType, SignatureTypeV2)
        assert rehydrated.signatureType is SignatureTypeV2.POLY_GNOSIS_SAFE

    def test_deserialize_preserves_non_enum_fields(self) -> None:
        """Non-enum fields must survive the round-trip unchanged."""
        from packages.valory.connections.polymarket_client.connection import (
            _deserialize_signed_order_v2,
            _serialize_signed_order_v2,
        )

        fresh = self._fresh_signed_order()
        rehydrated = _deserialize_signed_order_v2(_serialize_signed_order_v2(fresh))
        assert rehydrated.salt == fresh.salt
        assert rehydrated.tokenId == fresh.tokenId
        assert rehydrated.makerAmount == fresh.makerAmount
        assert rehydrated.takerAmount == fresh.takerAmount
        assert rehydrated.signature == fresh.signature

    def test_deserialize_skips_already_typed_enums(self) -> None:
        """Idempotent on already-typed enums — no double conversion."""
        import dataclasses

        from py_clob_client_v2.order_utils import Side
        from py_clob_client_v2.order_utils.model.signature_type_v2 import (
            SignatureTypeV2,
        )

        from packages.valory.connections.polymarket_client.connection import (
            _deserialize_signed_order_v2,
        )

        payload = dataclasses.asdict(self._fresh_signed_order())
        payload["side"] = Side.BUY
        payload["signatureType"] = SignatureTypeV2.POLY_GNOSIS_SAFE
        rehydrated = _deserialize_signed_order_v2(payload)
        assert rehydrated.side is Side.BUY
        assert rehydrated.signatureType is SignatureTypeV2.POLY_GNOSIS_SAFE


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_max_uint256_value(self) -> None:
        """MAX_UINT256 is 2^256 - 1."""
        assert MAX_UINT256 == 2**256 - 1

    def test_parent_collection_id_is_32_zero_bytes(self) -> None:
        """PARENT_COLLECTION_ID is 32 zero bytes."""
        assert PARENT_COLLECTION_ID == b"\x00" * 32
        assert len(PARENT_COLLECTION_ID) == 32
