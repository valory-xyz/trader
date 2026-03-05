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
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from packages.valory.connections.polymarket_client.connection import (
    CONDITIONAL_TOKENS_CONTRACT,
    DATA_API_BASE_URL,
    GAMMA_API_BASE_URL,
    MARKETS_LIMIT,
    MAX_UINT256,
    PARENT_COLLECTION_ID,
    POLYMARKET_CATEGORY_TAGS,
    PolymarketClientConnection,
    SrrDialogues,
)
from packages.valory.connections.polymarket_client.request_types import RequestType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAFE_ADDRESS = "0x0000000000000000000000000000000000000001"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"


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
    conn.usdc_address = USDC_ADDRESS
    conn.ctf_address = CTF_ADDRESS
    conn.ctf_exchange = CTF_EXCHANGE
    conn.neg_risk_ctf_exchange = NEG_RISK_CTF_EXCHANGE
    conn.neg_risk_adapter = NEG_RISK_ADAPTER
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

    def test_init(self) -> None:
        """Test SrrDialogues initialises without error."""
        dialogues = SrrDialogues(connection_id=MagicMock())
        assert dialogues is not None

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

    def test_place_bet_success_no_cache(self) -> None:
        """Places bet from scratch (no cached order) and returns response.

        The response must include 'signed_order_json' so the caller can retry
        with the same order if the submission fails later.
        """
        conn = _make_connection()
        signed_mock = MagicMock()
        order_dict = {"order": "data"}
        signed_mock.dict.return_value = order_dict
        conn.client.create_market_order.return_value = signed_mock
        conn.client.post_order.return_value = {"status": "matched"}

        response, error = conn._place_bet(token_id="tok123", amount=10.0)  # nosec B106
        assert error is None
        conn.client.create_market_order.assert_called_once()
        conn.client.post_order.assert_called_once()
        # The signed order JSON must be embedded in the response for potential retries
        assert "signed_order_json" in response
        assert json.loads(response["signed_order_json"]) == order_dict

    def test_place_bet_with_cached_order(self) -> None:
        """Uses cached signed order instead of creating a new one.

        When a cached order is provided the CLOB client must not create a fresh
        market order, and the cached JSON must be echoed back in the response so
        the caller can reconstruct the order if needed.
        """
        conn = _make_connection()
        cached = {
            "salt": "1",
            "maker": "0x0",
            "signer": "0x0",
            "taker": "0x0",
            "tokenId": "tok",
            "makerAmount": "10",
            "takerAmount": "5",
            "expiration": "0",
            "nonce": "0",
            "feeRateBps": "0",
            "side": "0",
            "signatureType": "2",
            "signature": "0xdeadbeef",
        }
        cached_json = json.dumps(cached)
        conn.client.post_order.return_value = {"status": "matched"}

        with patch(
            "packages.valory.connections.polymarket_client.connection.UtilsSignedOrder",
            MagicMock(return_value=MagicMock()),
        ):
            response, error = conn._place_bet(
                token_id="tok123",
                amount=10.0,
                cached_signed_order_json=cached_json,  # nosec B106
            )
        # Must reuse the cached order - no new order creation
        conn.client.create_market_order.assert_not_called()
        assert error is None
        # The cached JSON must be propagated back in the response
        assert response is not None
        assert "signed_order_json" in response
        assert response["signed_order_json"] == cached_json

    def test_place_bet_poly_api_exception_with_dict_error(self) -> None:
        """Test that PolyApiException with dict error_msg returns error in response.

        The response must also contain 'signed_order_json' so the caller can
        retry the submission with the same order (even though order creation
        failed before posting).
        """
        from py_clob_client.exceptions import PolyApiException

        conn = _make_connection()
        exc = PolyApiException(error_msg={"error": "duplicate order"})
        conn.client.create_market_order.side_effect = exc

        response, error = conn._place_bet(token_id="tok123", amount=5.0)  # nosec B106
        assert error == "duplicate order"
        assert "error" in response
        # signed_order_json must be present so the caller can cache and retry
        assert "signed_order_json" in response

    def test_place_bet_poly_api_exception_non_dict_error(self) -> None:
        """Test that PolyApiException with non-dict error_msg is formatted as 'Error placing bet: ...'."""
        from py_clob_client.exceptions import PolyApiException

        conn = _make_connection()
        exc = PolyApiException(error_msg="plain string error")
        conn.client.create_market_order.side_effect = exc

        response, error = conn._place_bet(token_id="tok123", amount=5.0)  # nosec B106
        # Non-dict error falls through to the f"Error placing bet: {e}" branch
        assert error is not None
        assert error.startswith("Error placing bet:")
        assert "error" in response

    def test_place_bet_post_order_none_response(self) -> None:
        """When post_order returns None, response is None but no crash."""
        conn = _make_connection()
        signed_mock = MagicMock()
        signed_mock.dict.return_value = {}
        conn.client.create_market_order.return_value = signed_mock
        conn.client.post_order.return_value = None

        response, error = conn._place_bet(token_id="tok123", amount=5.0)  # nosec B106
        assert error is None
        assert response is None


# ---------------------------------------------------------------------------
# _load_cache_file / _save_cache_file
# ---------------------------------------------------------------------------


class TestCacheFileMethods:
    """Tests for _load_cache_file and _save_cache_file."""

    def test_load_existing_cache_file(self) -> None:
        """Loads existing JSON cache file correctly."""
        conn = _make_connection()
        data = {"allowances_set": True, "tag_id_cache": {"politics": "42"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name
        try:
            result = conn._load_cache_file(tmp_path)
            assert result == data
        finally:
            os.unlink(tmp_path)

    def test_load_missing_cache_file_returns_defaults(self) -> None:
        """Returns default dict when file does not exist."""
        conn = _make_connection()
        result = conn._load_cache_file("/nonexistent/path/cache.json")
        assert result == {"allowances_set": False, "tag_id_cache": {}}

    def test_load_invalid_json_returns_defaults(self) -> None:
        """Returns default dict when file contains invalid JSON."""
        conn = _make_connection()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{")
            tmp_path = f.name
        try:
            result = conn._load_cache_file(tmp_path)
            assert result == {"allowances_set": False, "tag_id_cache": {}}
        finally:
            os.unlink(tmp_path)

    def test_save_cache_file_creates_file(self) -> None:
        """Saves cache data to file and creates parent directories."""
        conn = _make_connection()
        data = {"allowances_set": True, "tag_id_cache": {"politics": "7"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "subdir", "cache.json")
            conn._save_cache_file(cache_path, data)
            assert Path(cache_path).exists()
            with open(cache_path) as f:
                loaded = json.load(f)
            assert loaded == data

    def test_save_cache_file_handles_exception(self) -> None:
        """Logs error but does not raise when save fails."""
        conn = _make_connection()
        with patch("builtins.open", side_effect=OSError("disk full")):
            conn._save_cache_file("/tmp/test_cache.json", {})  # nosec B108
        conn.logger.error.assert_called_once()


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
# _fetch_tag_id
# ---------------------------------------------------------------------------


class TestFetchTagId:
    """Tests for _fetch_tag_id."""

    def test_returns_cached_tag_id(self) -> None:
        """Returns tag_id from in-memory cache without making API call."""
        conn = _make_connection()
        cache = {"politics": "99"}
        tag_id, error = conn._fetch_tag_id("politics", cache)
        assert tag_id == "99"
        assert error is None

    def test_fetches_tag_id_from_api_and_caches(self) -> None:
        """Fetches tag_id from API when not in cache, then caches it."""
        conn = _make_connection()
        cache = {}
        conn._request_with_retries = MagicMock(
            return_value=({"id": "42", "slug": "science"}, None)
        )
        tag_id, error = conn._fetch_tag_id("science", cache)
        assert tag_id == "42"
        assert error is None
        assert cache["science"] == "42"

    def test_api_error_propagates(self) -> None:
        """Returns (None, error_message) when API fails."""
        conn = _make_connection()
        conn._request_with_retries = MagicMock(
            return_value=(None, "connection refused")
        )
        tag_id, error = conn._fetch_tag_id("finance", {})
        assert tag_id is None
        assert "Error fetching tag" in error

    def test_no_id_in_response(self) -> None:
        """Returns error when API response lacks 'id' field."""
        conn = _make_connection()
        conn._request_with_retries = MagicMock(
            return_value=({"slug": "finance"}, None)  # no 'id' key
        )
        tag_id, error = conn._fetch_tag_id("finance", {})
        assert tag_id is None
        assert "No tag ID found" in error

    def test_updates_persistent_cache_file(self) -> None:
        """Updates persistent cache file when cache_file_path provided."""
        conn = _make_connection()
        cache = {}
        cache_data = {"allowances_set": False, "tag_id_cache": {}}
        conn._request_with_retries = MagicMock(return_value=({"id": "77"}, None))
        conn._save_cache_file = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_path = f.name
        try:
            tag_id, error = conn._fetch_tag_id(
                "technology", cache, cache_file_path=cache_path, cache_data=cache_data
            )
            assert tag_id == "77"
            conn._save_cache_file.assert_called_once()
        finally:
            os.unlink(cache_path)

    def test_initialises_missing_tag_id_cache_in_cache_data(self) -> None:
        """Handles cache_data without 'tag_id_cache' key by initialising it."""
        conn = _make_connection()
        cache = {}
        cache_data = {"allowances_set": False}  # no tag_id_cache
        conn._request_with_retries = MagicMock(return_value=({"id": "55"}, None))
        conn._save_cache_file = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_path = f.name
        try:
            tag_id, _ = conn._fetch_tag_id(
                "health", cache, cache_file_path=cache_path, cache_data=cache_data
            )
            assert cache_data["tag_id_cache"]["health"] == "55"
        finally:
            os.unlink(cache_path)

    def test_handles_none_tag_id_cache_in_cache_data(self) -> None:
        """Handles cache_data with tag_id_cache=None by re-initialising it."""
        conn = _make_connection()
        cache = {}
        cache_data = {"allowances_set": False, "tag_id_cache": None}
        conn._request_with_retries = MagicMock(return_value=({"id": "66"}, None))
        conn._save_cache_file = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            cache_path = f.name
        try:
            tag_id, _ = conn._fetch_tag_id(
                "business", cache, cache_file_path=cache_path, cache_data=cache_data
            )
            assert isinstance(cache_data["tag_id_cache"], dict)
            assert cache_data["tag_id_cache"]["business"] == "66"
        finally:
            os.unlink(cache_path)


# ---------------------------------------------------------------------------
# _fetch_markets_by_tag
# ---------------------------------------------------------------------------


class TestFetchMarketsByTag:
    """Tests for _fetch_markets_by_tag."""

    def test_returns_single_page(self) -> None:
        """Returns markets from a single page (less than MARKETS_LIMIT)."""
        conn = _make_connection()
        markets = [{"id": f"m{i}"} for i in range(5)]
        conn._request_with_retries = MagicMock(return_value=(markets, None))

        result, error = conn._fetch_markets_by_tag(
            "42", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert result == markets
        assert error is None

    def test_paginates_multiple_pages(self) -> None:
        """Paginates until a page with fewer than MARKETS_LIMIT items is returned."""
        conn = _make_connection()
        page1 = [{"id": f"m{i}"} for i in range(MARKETS_LIMIT)]
        page2 = [{"id": f"m{i}"} for i in range(10)]

        conn._request_with_retries = MagicMock(
            side_effect=[(page1, None), (page2, None)]
        )

        result, error = conn._fetch_markets_by_tag(
            "42", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert len(result) == MARKETS_LIMIT + 10
        assert error is None

    def test_api_error_propagates(self) -> None:
        """Returns (None, error) when API call fails."""
        conn = _make_connection()
        conn._request_with_retries = MagicMock(
            return_value=(None, "connection timeout")
        )
        result, error = conn._fetch_markets_by_tag(
            "42", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert result is None
        assert error == "connection timeout"

    def test_empty_response_stops_pagination(self) -> None:
        """Stops pagination when empty list is returned."""
        conn = _make_connection()
        conn._request_with_retries = MagicMock(return_value=([], None))
        result, error = conn._fetch_markets_by_tag(
            "42", "2025-01-01T00:00:00Z", "2025-01-05T00:00:00Z"
        )
        assert result == []
        assert error is None

    def test_sends_correct_params_to_gamma_api(self) -> None:
        """_fetch_markets_by_tag passes tag_id, dates, MARKETS_LIMIT, and offset=0 to the API.

        The API must receive all five required parameters. Using the wrong limit
        or missing the tag_id would silently return unrelated markets.
        """
        conn = _make_connection()
        conn._request_with_retries = MagicMock(return_value=([], None))

        tag_id = "42"
        end_date_min = "2025-01-01T00:00:00Z"
        end_date_max = "2025-01-05T00:00:00Z"
        conn._fetch_markets_by_tag(tag_id, end_date_min, end_date_max)

        call_args = conn._request_with_retries.call_args
        actual_url = call_args[0][0]
        actual_params = call_args[1]["params"]

        assert f"{GAMMA_API_BASE_URL}/markets" in actual_url
        assert actual_params["tag_id"] == tag_id
        assert actual_params["end_date_min"] == end_date_min
        assert actual_params["end_date_max"] == end_date_max
        assert actual_params["limit"] == MARKETS_LIMIT
        assert actual_params["offset"] == 0


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
        """Returns dict of category->markets with Yes/No filtering applied.

        Markets that do NOT have Yes/No outcomes or that are too old must be
        excluded from the result even if they are returned by the API.
        """
        conn = _make_connection()
        conn._load_cache_file = MagicMock(
            return_value={"allowances_set": False, "tag_id_cache": {}}
        )
        conn._fetch_tag_id = MagicMock(return_value=("tag123", None))
        # Mix: one valid Yes/No market and two that should be filtered out
        markets = [
            # passes both filters
            {
                "id": "m1",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["Yes","No"]',
            },
            # fails yes/no filter (multi-outcome)
            {
                "id": "m2",
                "createdAt": "2026-01-01T00:00:00Z",
                "outcomes": '["A","B","C"]',
            },
            # fails createdAt filter (too old - empty string < MIN_CREATED_AT)
            {"id": "m3", "createdAt": "", "outcomes": '["Yes","No"]'},
        ]
        conn._fetch_markets_by_tag = MagicMock(return_value=(markets, None))

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

    def test_tag_id_error_skips_category(self) -> None:
        """Category is skipped when tag_id fetch fails."""
        conn = _make_connection()
        conn._load_cache_file = MagicMock(
            return_value={"allowances_set": False, "tag_id_cache": {}}
        )
        conn._fetch_tag_id = MagicMock(return_value=(None, "tag not found"))
        conn._fetch_markets_by_tag = MagicMock()

        result, error = conn._fetch_markets()
        assert error is None
        assert result == {}  # All categories skipped
        conn._fetch_markets_by_tag.assert_not_called()

    def test_markets_fetch_error_continues_other_categories(self) -> None:
        """Continues to next category when market fetch fails for one."""
        conn = _make_connection()
        conn._load_cache_file = MagicMock(
            return_value={"allowances_set": False, "tag_id_cache": {}}
        )
        conn._fetch_tag_id = MagicMock(return_value=("tag123", None))
        # First category fails, rest succeed with empty list
        conn._fetch_markets_by_tag = MagicMock(
            side_effect=[(None, "api error")]
            + [([], None)] * (len(POLYMARKET_CATEGORY_TAGS) - 1)
        )

        result, error = conn._fetch_markets()
        assert error is None
        # All categories with successful fetch (empty) should be present
        assert len(result) == len(POLYMARKET_CATEGORY_TAGS) - 1

    def test_uses_cache_file_path(self) -> None:
        """Loads and uses tag_id cache from file when cache_file_path provided."""
        conn = _make_connection()
        cached_data = {
            "allowances_set": False,
            "tag_id_cache": {
                cat: f"id_{i}" for i, cat in enumerate(POLYMARKET_CATEGORY_TAGS)
            },
        }
        conn._load_cache_file = MagicMock(return_value=cached_data)
        conn._fetch_tag_id = MagicMock(
            side_effect=lambda cat, cache, *args, **kw: (cache.get(cat, None), None)
        )
        conn._fetch_markets_by_tag = MagicMock(return_value=([], None))

        result, error = conn._fetch_markets(
            cache_file_path="/tmp/cache.json"  # nosec B108
        )
        assert error is None
        conn._load_cache_file.assert_called_once_with("/tmp/cache.json")  # nosec B108

    def test_unexpected_exception_returns_error(self) -> None:
        """Catches unexpected exceptions and returns error message."""
        conn = _make_connection()
        conn._load_cache_file = MagicMock(side_effect=RuntimeError("disk full"))

        result, error = conn._fetch_markets(
            cache_file_path="/tmp/cache.json"  # nosec B108
        )
        assert result is None
        assert "Unexpected error" in error

    def test_none_tag_id_cache_in_loaded_data(self) -> None:
        """Handles loaded cache_data with tag_id_cache=None."""
        conn = _make_connection()
        conn._load_cache_file = MagicMock(
            return_value={"allowances_set": False, "tag_id_cache": None}
        )
        conn._fetch_tag_id = MagicMock(return_value=("tag123", None))
        conn._fetch_markets_by_tag = MagicMock(return_value=([], None))

        result, error = conn._fetch_markets(
            cache_file_path="/tmp/cache.json"  # nosec B108
        )
        assert error is None


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
        positions = [{"token": "tok1", "size": 10}]
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
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
            collateral_token=USDC_ADDRESS,
            is_neg_risk=False,
        )
        tx_with_prefix = conn.relayer_client.execute.call_args[1]["transactions"][0]

        conn.relayer_client.reset_mock()
        conn._redeem_positions(
            condition_id="ab" * 32,
            index_sets=[1],
            collateral_token=USDC_ADDRESS,
            is_neg_risk=False,
        )
        tx_without_prefix = conn.relayer_client.execute.call_args[1]["transactions"][0]

        assert tx_with_prefix.data == tx_without_prefix.data

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
            collateral_token=USDC_ADDRESS,
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
        """Executes 6 approval transactions and returns transaction data."""
        conn = _make_connection()
        tx_data = {"hash": "0xabc"}
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = tx_data
        conn.relayer_client.execute.return_value = result_mock

        result, error = conn._set_approval()
        assert result == tx_data
        assert error is None

        # 6 transactions should be passed
        call_kwargs = conn.relayer_client.execute.call_args[1]
        assert len(call_kwargs["transactions"]) == 6

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
        """ERC-20 approve transactions (indices 0, 2, 4) all target the USDC contract.

        These are the three `approve(ctf_exchange, MAX_UINT256)` calls. Targeting
        the wrong contract would grant allowances to the wrong token address.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._set_approval()

        txns = conn.relayer_client.execute.call_args[1]["transactions"]
        for idx in [0, 2, 4]:
            assert txns[idx].to == USDC_ADDRESS, f"txns[{idx}].to should be USDC"

    def test_ctf_approval_transactions_target_ctf_contract(self) -> None:
        """ERC-1155 setApprovalForAll transactions (indices 1, 3, 5) all target the CTF contract.

        These are the three `setApprovalForAll(spender, True)` calls. Targeting
        the wrong contract would grant operator access on the wrong token.
        """
        conn = _make_connection()
        result_mock = MagicMock()
        result_mock.get_transaction.return_value = {}
        conn.relayer_client.execute.return_value = result_mock

        conn._set_approval()

        txns = conn.relayer_client.execute.call_args[1]["transactions"]
        for idx in [1, 3, 5]:
            assert txns[idx].to == CTF_ADDRESS, f"txns[{idx}].to should be CTF"


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
        conn.w3.to_checksum_address.return_value = USDC_ADDRESS
        conn.w3.eth.call.return_value = allowance_bytes

        result = conn._check_erc20_allowance(USDC_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)
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
        conn.w3.to_checksum_address.return_value = USDC_ADDRESS
        conn.w3.eth.call.return_value = (1000).to_bytes(32, byteorder="big")

        conn._check_erc20_allowance(USDC_ADDRESS, SAFE_ADDRESS, CTF_EXCHANGE)

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
        # USDC allowances: first set, second and third not
        conn._check_erc20_allowance = MagicMock(
            side_effect=[MAX_UINT256, 0, MAX_UINT256]
        )
        conn._check_erc1155_approval = MagicMock(side_effect=[True, False, True])

        result, error = conn._check_approval()
        assert error is None
        assert result["all_approvals_set"] is False
        assert result["usdc_allowances"]["ctf_exchange"] == MAX_UINT256
        assert result["usdc_allowances"]["neg_risk_ctf_exchange"] == 0

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
        assert "ctf_exchange" in result["ctf_approvals"]
        assert "neg_risk_ctf_exchange" in result["ctf_approvals"]
        assert "neg_risk_adapter" in result["ctf_approvals"]

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


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_polymarket_category_tags_count(self) -> None:
        """POLYMARKET_CATEGORY_TAGS contains exactly 10 categories."""
        assert len(POLYMARKET_CATEGORY_TAGS) == 10

    def test_max_uint256_value(self) -> None:
        """MAX_UINT256 is 2^256 - 1."""
        assert MAX_UINT256 == 2**256 - 1

    def test_parent_collection_id_is_32_zero_bytes(self) -> None:
        """PARENT_COLLECTION_ID is 32 zero bytes."""
        assert PARENT_COLLECTION_ID == b"\x00" * 32
        assert len(PARENT_COLLECTION_ID) == 32

    def test_conditional_tokens_contract_is_checksummed(self) -> None:
        """CONDITIONAL_TOKENS_CONTRACT is a non-empty string."""
        assert isinstance(CONDITIONAL_TOKENS_CONTRACT, str)
        assert CONDITIONAL_TOKENS_CONTRACT.startswith("0x")
