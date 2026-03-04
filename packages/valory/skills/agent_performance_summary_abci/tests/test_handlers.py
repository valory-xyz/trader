# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for agent_performance_summary_abci/handlers.py."""

import json
import time
from dataclasses import asdict
from datetime import datetime
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.agent_performance_summary_abci.handlers import (
    DEFAULT_HEADER,
    DEFAULT_PAGE_SIZE,
    ISO_TIMESTAMP_FORMAT,
    MAX_PAGE_SIZE,
    PREDICTION_STATUS_ALL,
    PREDICTION_STATUS_INVALID,
    PREDICTION_STATUS_LOST,
    PREDICTION_STATUS_PENDING,
    PREDICTION_STATUS_WON,
    SECONDS_PER_DAY,
    VALID_PREDICTION_STATUSES,
    AgentPerformanceSummaryABCIHandler,
    ContractApiHandler,
    HttpContentType,
    HttpHandler,
    HttpMethod,
    IpfsHandler,
    LedgerApiHandler,
    SigningHandler,
    TendermintHandler,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AgentDetails,
    AgentPerformanceData,
    AgentPerformanceSummary,
    PerformanceMetricsData,
    PerformanceStatsData,
    PredictionHistory,
    ProfitDataPoint,
    ProfitOverTimeData,
)


# ---------------------------------------------------------------------------
# Testable subclass: shadows read-only AEA properties with plain attributes
# ---------------------------------------------------------------------------


class _TestableHttpHandler(HttpHandler):
    """Shadows read-only AEA properties with plain attributes for testing."""

    context = None  # type: ignore[assignment]
    shared_state = None  # type: ignore[assignment]
    synchronized_data = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _make_handler(
    is_running_on_polymarket: bool = False,
    service_endpoint: str = "http://localhost:8080",
    safe_address: str = "0xabc123",
    store_path: str = "/tmp/test_store",
) -> _TestableHttpHandler:
    """Return a _TestableHttpHandler wired with minimal mocks."""
    handler = object.__new__(_TestableHttpHandler)

    context = MagicMock()
    context.params.service_endpoint = service_endpoint
    context.params.is_running_on_polymarket = is_running_on_polymarket
    context.params.store_path = store_path
    context.logger = MagicMock()
    context.outbox = MagicMock()
    handler.context = context

    shared_state = MagicMock()
    shared_state.read_existing_performance_summary.return_value = (
        AgentPerformanceSummary()
    )
    handler.shared_state = shared_state  # type: ignore[misc]

    sync_data = MagicMock()
    sync_data.safe_contract_address = safe_address
    handler.synchronized_data = sync_data  # type: ignore[misc]

    handler.handler_url_regex = ""
    handler.routes = {}

    return handler


def _make_http_msg(
    url: str = "http://localhost:8080/api/v1/agent/details",
    headers: str = "",
    version: str = "1.1",
) -> MagicMock:
    """Create a mock HttpMessage."""
    msg = MagicMock(spec=HttpMessage)
    msg.url = url
    msg.headers = headers
    msg.version = version
    return msg


def _make_http_dialogue() -> MagicMock:
    """Create a mock HttpDialogue."""
    dialogue = MagicMock()
    dialogue.reply.return_value = MagicMock()
    dialogue.dialogue_label.dialogue_reference = ("ref0", "ref1")
    return dialogue


# ---------------------------------------------------------------------------
# Test constants and enums
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_default_header(self) -> None:
        """Test DEFAULT_HEADER is the HTML content type header."""
        assert DEFAULT_HEADER == "Content-Type: text/html\n"

    def test_default_page_size(self) -> None:
        """Test DEFAULT_PAGE_SIZE value."""
        assert DEFAULT_PAGE_SIZE == 10

    def test_max_page_size(self) -> None:
        """Test MAX_PAGE_SIZE value."""
        assert MAX_PAGE_SIZE == 100

    def test_iso_timestamp_format(self) -> None:
        """Test ISO_TIMESTAMP_FORMAT value."""
        assert ISO_TIMESTAMP_FORMAT == "%Y-%m-%dT%H:%M:%SZ"

    def test_prediction_statuses(self) -> None:
        """Test prediction status constants."""
        assert PREDICTION_STATUS_PENDING == "pending"
        assert PREDICTION_STATUS_WON == "won"
        assert PREDICTION_STATUS_LOST == "lost"
        assert PREDICTION_STATUS_INVALID == "invalid"
        assert PREDICTION_STATUS_ALL == "all"

    def test_valid_prediction_statuses(self) -> None:
        """Test VALID_PREDICTION_STATUSES list."""
        assert VALID_PREDICTION_STATUSES == [
            "pending",
            "won",
            "lost",
            "invalid",
        ]

    def test_seconds_per_day(self) -> None:
        """Test SECONDS_PER_DAY value."""
        assert SECONDS_PER_DAY == 86400


class TestHttpMethod:
    """Tests for HttpMethod enum."""

    def test_get(self) -> None:
        """Test GET value."""
        assert HttpMethod.GET.value == "get"

    def test_head(self) -> None:
        """Test HEAD value."""
        assert HttpMethod.HEAD.value == "head"

    def test_post(self) -> None:
        """Test POST value."""
        assert HttpMethod.POST.value == "post"


class TestHttpContentType:
    """Tests for HttpContentType enum."""

    def test_html(self) -> None:
        """Test HTML content type."""
        assert HttpContentType.HTML.value == "text/html"

    def test_js(self) -> None:
        """Test JS content type."""
        assert HttpContentType.JS.value == "application/javascript"

    def test_json(self) -> None:
        """Test JSON content type."""
        assert HttpContentType.JSON.value == "application/json"

    def test_css(self) -> None:
        """Test CSS content type."""
        assert HttpContentType.CSS.value == "text/css"

    def test_png(self) -> None:
        """Test PNG content type."""
        assert HttpContentType.PNG.value == "image/png"

    def test_jpg(self) -> None:
        """Test JPG content type."""
        assert HttpContentType.JPG.value == "image/jpeg"

    def test_jpeg(self) -> None:
        """Test JPEG content type."""
        assert HttpContentType.JPEG.value == "image/jpeg"

    def test_header_property(self) -> None:
        """Test header property for each content type."""
        assert HttpContentType.HTML.header == "Content-Type: text/html\n"
        assert HttpContentType.JSON.header == "Content-Type: application/json\n"
        assert HttpContentType.JS.header == "Content-Type: application/javascript\n"
        assert HttpContentType.CSS.header == "Content-Type: text/css\n"
        assert HttpContentType.PNG.header == "Content-Type: image/png\n"
        assert HttpContentType.JPG.header == "Content-Type: image/jpeg\n"
        assert HttpContentType.JPEG.header == "Content-Type: image/jpeg\n"


# ---------------------------------------------------------------------------
# Test handler aliases
# ---------------------------------------------------------------------------


class TestHandlerAliases:
    """Tests verifying handler aliases map to the correct base classes."""

    def test_abci_handler(self) -> None:
        """Test AgentPerformanceSummaryABCIHandler alias."""
        assert AgentPerformanceSummaryABCIHandler is BaseABCIRoundHandler

    def test_signing_handler(self) -> None:
        """Test SigningHandler alias."""
        assert SigningHandler is BaseSigningHandler

    def test_ledger_api_handler(self) -> None:
        """Test LedgerApiHandler alias."""
        assert LedgerApiHandler is BaseLedgerApiHandler

    def test_contract_api_handler(self) -> None:
        """Test ContractApiHandler alias."""
        assert ContractApiHandler is BaseContractApiHandler

    def test_tendermint_handler(self) -> None:
        """Test TendermintHandler alias."""
        assert TendermintHandler is BaseTendermintHandler

    def test_ipfs_handler(self) -> None:
        """Test IpfsHandler alias."""
        assert IpfsHandler is BaseIpfsHandler


# ---------------------------------------------------------------------------
# Test HttpHandler initialization
# ---------------------------------------------------------------------------


class TestHttpHandlerInit:
    """Tests for HttpHandler initialization."""

    def test_init(self) -> None:
        """Test __init__ sets handler_url_regex and routes."""
        ctx = MagicMock()
        handler = HttpHandler(name="test", skill_context=ctx)
        assert handler.handler_url_regex == ""
        assert handler.routes == {}

    def test_supported_protocol(self) -> None:
        """Test SUPPORTED_PROTOCOL is set correctly."""
        assert HttpHandler.SUPPORTED_PROTOCOL == HttpMessage.protocol_id

    def test_inherits_base_http_handler(self) -> None:
        """Test that HttpHandler inherits from BaseHttpHandler."""
        assert issubclass(HttpHandler, BaseHttpHandler)


# ---------------------------------------------------------------------------
# Test HttpHandler properties
# ---------------------------------------------------------------------------


class TestHttpHandlerProperties:
    """Tests for HttpHandler properties."""

    def test_hostname_regex_localhost(self) -> None:
        """Test hostname_regex with localhost service endpoint."""
        handler = _make_handler(service_endpoint="http://localhost:8080/some/path")
        regex = handler.hostname_regex
        assert "localhost" in regex
        assert "propel" in regex
        assert r"192\.168" in regex
        assert "127.0.0.1" in regex
        assert "0.0.0.0" in regex

    def test_hostname_regex_custom_host(self) -> None:
        """Test hostname_regex with a custom hostname."""
        handler = _make_handler(service_endpoint="http://myserver.example.com:9090/api")
        regex = handler.hostname_regex
        assert regex.startswith(".*(myserver.example.com")

    def test_hostname_regex_https(self) -> None:
        """Test hostname_regex with HTTPS endpoint."""
        handler = _make_handler(service_endpoint="https://secure.example.com/api")
        regex = handler.hostname_regex
        assert regex.startswith(".*(secure.example.com")

    def test_shared_state_property(self) -> None:
        """Test shared_state property returns cast state."""
        handler = _make_handler()
        result = handler.shared_state
        assert result is not None

    def test_synchronized_data_property(self) -> None:
        """Test synchronized_data property."""
        handler = _make_handler()
        result = handler.synchronized_data
        assert result is not None

    def test_real_synchronized_data_property(self) -> None:
        """Test the real synchronized_data property on the base HttpHandler class."""
        ctx = MagicMock()
        handler = HttpHandler(name="test", skill_context=ctx)
        result = handler.synchronized_data
        assert result is not None

    def test_real_shared_state_property(self) -> None:
        """Test the real shared_state property on the base HttpHandler class."""
        ctx = MagicMock()
        handler = HttpHandler(name="test", skill_context=ctx)
        result = handler.shared_state
        assert result is not None


# ---------------------------------------------------------------------------
# Test HttpHandler.setup()
# ---------------------------------------------------------------------------


class TestHttpHandlerSetup:
    """Tests for HttpHandler.setup()."""

    def test_setup_registers_routes(self) -> None:
        """Test that setup registers all expected API routes."""
        handler = _make_handler()
        # Manually call setup; we need to mock super().setup()
        with patch.object(BaseHttpHandler, "setup"):
            handler.setup()

        get_head_key = (HttpMethod.GET.value, HttpMethod.HEAD.value)
        assert get_head_key in handler.routes

        routes = handler.routes[get_head_key]
        route_handlers = [h for _, h in routes]

        assert handler._handle_get_agent_details in route_handlers
        assert handler._handle_get_agent_performance in route_handlers
        assert handler._handle_get_predictions in route_handlers
        assert handler._handle_get_profit_over_time in route_handlers
        assert handler._handle_get_position_details in route_handlers

    def test_setup_route_regexes_contain_api_paths(self) -> None:
        """Test that route regexes contain expected API paths."""
        handler = _make_handler()
        with patch.object(BaseHttpHandler, "setup"):
            handler.setup()

        get_head_key = (HttpMethod.GET.value, HttpMethod.HEAD.value)
        route_regexes = [regex for regex, _ in handler.routes[get_head_key]]

        api_paths = [
            r"\/api\/v1\/agent\/details",
            r"\/api\/v1\/agent\/performance",
            r"\/api\/v1\/agent\/prediction-history",
            r"\/api\/v1\/agent\/profit-over-time",
            r"\/api\/v1\/agent\/position-details\/",
        ]
        for path in api_paths:
            assert any(
                path in regex for regex in route_regexes
            ), f"API path {path} not found in route regexes"

    def test_setup_preserves_existing_routes(self) -> None:
        """Test that setup preserves routes from the base class."""
        handler = _make_handler()
        existing_route = ("some_regex", MagicMock())
        handler.routes = {
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [existing_route],
            ("post",): [("post_regex", MagicMock())],
        }

        with patch.object(BaseHttpHandler, "setup"):
            handler.setup()

        get_head_key = (HttpMethod.GET.value, HttpMethod.HEAD.value)
        routes = handler.routes[get_head_key]
        # The existing route should be preserved
        assert existing_route in routes
        # post routes should also be preserved
        assert ("post",) in handler.routes


# ---------------------------------------------------------------------------
# Test _send_http_response
# ---------------------------------------------------------------------------


class TestSendHttpResponse:
    """Tests for _send_http_response."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_msg = _make_http_msg()
        self.http_dialogue = _make_http_dialogue()

    def test_send_dict_data(self) -> None:
        """Test sending dict data auto-serializes to JSON."""
        data = {"key": "value"}
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, data, 200, "OK"
        )
        self.http_dialogue.reply.assert_called_once()
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == json.dumps(data).encode("utf-8")
        assert call_kwargs.kwargs["status_code"] == 200

    def test_send_list_data(self) -> None:
        """Test sending list data auto-serializes to JSON."""
        data = [{"a": 1}, {"b": 2}]
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, data, 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == json.dumps(data).encode("utf-8")

    def test_send_string_data(self) -> None:
        """Test sending string data encodes to UTF-8."""
        data = "hello world"
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, data, 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == b"hello world"

    def test_send_bytes_data(self) -> None:
        """Test sending bytes data is passed through directly."""
        data = b"raw bytes"
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, data, 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == b"raw bytes"

    def test_json_content_type_for_dict(self) -> None:
        """Test JSON content-type header is used for dict data."""
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, {"a": 1}, 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert "application/json" in call_kwargs.kwargs["headers"]

    def test_html_content_type_for_string(self) -> None:
        """Test HTML content-type header is used for string data."""
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, "html data", 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert "text/html" in call_kwargs.kwargs["headers"]

    def test_custom_content_type(self) -> None:
        """Test custom content-type is used when provided."""
        custom_ct = "Content-Type: text/plain\n"
        self.handler._send_http_response(
            self.http_msg,
            self.http_dialogue,
            "data",
            200,
            "OK",
            content_type=custom_ct,
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert "text/plain" in call_kwargs.kwargs["headers"]

    def test_message_put_in_outbox(self) -> None:
        """Test response message is put in outbox."""
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, "ok", 200, "OK"
        )
        self.handler.context.outbox.put_message.assert_called_once()

    def test_key_error_handled(self) -> None:
        """Test KeyError during reply is handled gracefully."""
        self.http_dialogue.reply.side_effect = KeyError("test error")
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, "ok", 200, "OK"
        )
        self.handler.context.logger.error.assert_called_once()

    def test_generic_exception_handled(self) -> None:
        """Test generic exception during reply is handled gracefully."""
        self.http_dialogue.reply.side_effect = RuntimeError("unexpected")
        self.handler._send_http_response(
            self.http_msg, self.http_dialogue, "ok", 200, "OK"
        )
        self.handler.context.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Test convenience response methods
# ---------------------------------------------------------------------------


class TestConvenienceResponseMethods:
    """Tests for convenience response methods."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_msg = _make_http_msg()
        self.http_dialogue = _make_http_dialogue()

    def test_send_ok_response(self) -> None:
        """Test _send_ok_response sends 200 with Success status."""
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_ok_response(
                self.http_msg, self.http_dialogue, {"ok": True}
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                {"ok": True},
                200,
                "Success",
                None,
            )

    def test_send_ok_response_with_content_type(self) -> None:
        """Test _send_ok_response with custom content type."""
        custom_ct = "Content-Type: text/plain\n"
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_ok_response(
                self.http_msg, self.http_dialogue, "text", content_type=custom_ct
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                "text",
                200,
                "Success",
                custom_ct,
            )

    def test_send_bad_request_response(self) -> None:
        """Test _send_bad_request_response sends 400."""
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_bad_request_response(
                self.http_msg, self.http_dialogue, {"error": "bad"}
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                {"error": "bad"},
                400,
                "Bad Request",
                None,
            )

    def test_send_bad_request_response_with_content_type(self) -> None:
        """Test _send_bad_request_response with custom content type."""
        custom_ct = "Content-Type: text/plain\n"
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_bad_request_response(
                self.http_msg, self.http_dialogue, "err", content_type=custom_ct
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                "err",
                400,
                "Bad Request",
                custom_ct,
            )

    def test_send_too_early_request_response(self) -> None:
        """Test _send_too_early_request_response sends 425."""
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_too_early_request_response(
                self.http_msg, self.http_dialogue, {"error": "too early"}
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                {"error": "too early"},
                425,
                "Too Early",
                None,
            )

    def test_send_too_early_request_response_with_content_type(self) -> None:
        """Test _send_too_early_request_response with custom content type."""
        custom_ct = "Content-Type: text/xml\n"
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_too_early_request_response(
                self.http_msg, self.http_dialogue, "e", content_type=custom_ct
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                "e",
                425,
                "Too Early",
                custom_ct,
            )

    def test_send_too_many_requests_response(self) -> None:
        """Test _send_too_many_requests_response sends 429."""
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_too_many_requests_response(
                self.http_msg, self.http_dialogue, {"error": "rate limited"}
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                {"error": "rate limited"},
                429,
                "Too Many Requests",
                None,
            )

    def test_send_too_many_requests_response_with_content_type(self) -> None:
        """Test _send_too_many_requests_response with custom content type."""
        custom_ct = "Content-Type: text/plain\n"
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_too_many_requests_response(
                self.http_msg, self.http_dialogue, "r", content_type=custom_ct
            )
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                "r",
                429,
                "Too Many Requests",
                custom_ct,
            )

    def test_send_not_found_response(self) -> None:
        """Test _send_not_found_response sends 404."""
        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_not_found_response(self.http_msg, self.http_dialogue)
            mock_send.assert_called_once_with(
                self.http_msg,
                self.http_dialogue,
                {"error": "Agent not found"},
                404,
                "Not Found",
            )


# ---------------------------------------------------------------------------
# Test _send_internal_server_error_response
# ---------------------------------------------------------------------------


class TestSendInternalServerErrorResponse:
    """Tests for _send_internal_server_error_response."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_msg = _make_http_msg()
        self.http_dialogue = _make_http_dialogue()

    def test_dict_data(self) -> None:
        """Test with dict data."""
        data = {"error": "something went wrong"}
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, data
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["status_code"] == 500
        assert call_kwargs.kwargs["body"] == json.dumps(data).encode("utf-8")
        assert "application/json" in call_kwargs.kwargs["headers"]

    def test_list_data(self) -> None:
        """Test with list data."""
        data = [{"error": "e1"}]
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, data
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == json.dumps(data).encode("utf-8")
        assert "application/json" in call_kwargs.kwargs["headers"]

    def test_string_data(self) -> None:
        """Test with string data."""
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, "error text"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == b"error text"
        assert "text/html" in call_kwargs.kwargs["headers"]

    def test_bytes_data(self) -> None:
        """Test with bytes data."""
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, b"raw error"
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert call_kwargs.kwargs["body"] == b"raw error"

    def test_custom_content_type(self) -> None:
        """Test with custom content type."""
        custom_ct = "Content-Type: text/plain\n"
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, "err", content_type=custom_ct
        )
        call_kwargs = self.http_dialogue.reply.call_args
        assert "text/plain" in call_kwargs.kwargs["headers"]

    def test_message_put_in_outbox(self) -> None:
        """Test response is placed in outbox."""
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, "err"
        )
        self.handler.context.outbox.put_message.assert_called_once()

    def test_logger_called(self) -> None:
        """Test logger.info is called with the response."""
        self.handler._send_internal_server_error_response(
            self.http_msg, self.http_dialogue, "err"
        )
        self.handler.context.logger.info.assert_called()


# ---------------------------------------------------------------------------
# Test _send_message
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Tests for _send_message."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()

    def test_send_message_puts_message_in_outbox(self) -> None:
        """Test _send_message puts message in outbox."""
        message = MagicMock()
        dialogue = MagicMock()
        dialogue.dialogue_label.dialogue_reference = ("nonce123", "ref1")
        callback = MagicMock()

        self.handler._send_message(message, dialogue, callback)

        self.handler.context.outbox.put_message.assert_called_once_with(
            message=message
        )

    def test_send_message_stores_callback(self) -> None:
        """Test _send_message stores callback in req_to_callback."""
        message = MagicMock()
        dialogue = MagicMock()
        dialogue.dialogue_label.dialogue_reference = ("nonce123", "ref1")
        callback = MagicMock()

        self.handler._send_message(message, dialogue, callback)

        self.handler.context.state.req_to_callback.__setitem__.assert_called_once_with(
            "nonce123", (callback, {})
        )

    def test_send_message_stores_callback_kwargs(self) -> None:
        """Test _send_message stores callback with kwargs."""
        message = MagicMock()
        dialogue = MagicMock()
        dialogue.dialogue_label.dialogue_reference = ("nonce456", "ref1")
        callback = MagicMock()
        kwargs = {"key": "value"}

        self.handler._send_message(message, dialogue, callback, kwargs)

        self.handler.context.state.req_to_callback.__setitem__.assert_called_once_with(
            "nonce456", (callback, kwargs)
        )


# ---------------------------------------------------------------------------
# Test _handle_get_agent_details
# ---------------------------------------------------------------------------


class TestHandleGetAgentDetails:
    """Tests for _handle_get_agent_details."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_msg = _make_http_msg()
        self.http_dialogue = _make_http_dialogue()

    def test_returns_details_when_available(self) -> None:
        """Test returns agent details when they are available."""
        details = AgentDetails(
            id="agent-1",
            created_at="2024-01-01T00:00:00Z",
            last_active_at="2024-06-01T12:00:00Z",
        )
        summary = AgentPerformanceSummary(agent_details=details)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_details(self.http_msg, self.http_dialogue)
            mock_ok.assert_called_once()
            response_data = mock_ok.call_args[0][2]
            assert response_data["id"] == "agent-1"
            assert response_data["created_at"] == "2024-01-01T00:00:00Z"
            assert response_data["last_active_at"] == "2024-06-01T12:00:00Z"

    def test_returns_error_when_details_missing(self) -> None:
        """Test returns 500 error when agent details are not available."""
        summary = AgentPerformanceSummary(agent_details=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(
            self.handler, "_send_internal_server_error_response"
        ) as mock_err:
            self.handler._handle_get_agent_details(self.http_msg, self.http_dialogue)
            mock_err.assert_called_once()
            error_data = mock_err.call_args[0][2]
            assert "error" in error_data

    def test_logs_response(self) -> None:
        """Test logger is called with agent details."""
        details = AgentDetails(id="test-id")
        summary = AgentPerformanceSummary(agent_details=details)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response"):
            self.handler._handle_get_agent_details(self.http_msg, self.http_dialogue)
            self.handler.context.logger.info.assert_called()


# ---------------------------------------------------------------------------
# Test _handle_get_agent_performance
# ---------------------------------------------------------------------------


class TestHandleGetAgentPerformance:
    """Tests for _handle_get_agent_performance."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_dialogue = _make_http_dialogue()

    def _make_performance_summary(
        self,
        metrics: Optional[PerformanceMetricsData] = None,
        stats: Optional[PerformanceStatsData] = None,
    ) -> AgentPerformanceSummary:
        """Create a summary with performance data."""
        perf = AgentPerformanceData(
            metrics=metrics
            or PerformanceMetricsData(
                all_time_profit=100.0,
                roi=10.5,
                available_funds=500.0,
            ),
            stats=stats or PerformanceStatsData(predictions_made=50, prediction_accuracy=75.0),
        )
        return AgentPerformanceSummary(agent_performance=perf)

    def test_default_window_and_currency(self) -> None:
        """Test default window is 'lifetime' and currency is 'USD'."""
        http_msg = _make_http_msg(url="http://localhost:8080/api/v1/agent/performance")
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "lifetime"
            assert response["currency"] == "USD"

    def test_custom_window_7d(self) -> None:
        """Test window=7d query parameter."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?window=7d"
        )
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "7d"

    def test_custom_window_30d(self) -> None:
        """Test window=30d query parameter."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?window=30d"
        )
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "30d"

    def test_custom_window_90d(self) -> None:
        """Test window=90d query parameter."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?window=90d"
        )
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "90d"

    def test_custom_currency(self) -> None:
        """Test custom currency query parameter."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?currency=EUR"
        )
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["currency"] == "EUR"

    def test_multiple_query_params(self) -> None:
        """Test both window and currency query parameters."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?window=30d&currency=ETH"
        )
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "30d"
            assert response["currency"] == "ETH"

    def test_invalid_window_returns_bad_request(self) -> None:
        """Test invalid window parameter returns 400."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?window=invalid"
        )

        with patch.object(self.handler, "_send_bad_request_response") as mock_bad:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            mock_bad.assert_called_once()
            error_data = mock_bad.call_args[0][2]
            assert "Invalid window parameter" in error_data["error"]

    def test_no_performance_data_returns_error(self) -> None:
        """Test returns 500 when performance data is unavailable."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance"
        )
        summary = AgentPerformanceSummary(agent_performance=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(
            self.handler, "_send_internal_server_error_response"
        ) as mock_err:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            mock_err.assert_called_once()

    def test_response_includes_agent_id(self) -> None:
        """Test response includes the safe_contract_address as agent_id."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance"
        )
        summary = self._make_performance_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["agent_id"] == "0xabc123"

    def test_response_includes_metrics_and_stats(self) -> None:
        """Test response contains metrics and stats dicts."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance"
        )
        metrics = PerformanceMetricsData(all_time_profit=200.0, roi=15.0)
        stats = PerformanceStatsData(predictions_made=100, prediction_accuracy=80.0)
        summary = self._make_performance_summary(metrics=metrics, stats=stats)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["metrics"]["all_time_profit"] == 200.0
            assert response["stats"]["predictions_made"] == 100

    def test_performance_with_none_metrics(self) -> None:
        """Test performance data with None metrics returns empty dict."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance"
        )
        perf = AgentPerformanceData(metrics=None, stats=None)
        summary = AgentPerformanceSummary(agent_performance=perf)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["metrics"] == {}
            assert response["stats"] == {}

    def test_exception_returns_internal_error(self) -> None:
        """Test exception in handler returns 500."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance"
        )
        self.handler.shared_state.read_existing_performance_summary.side_effect = (
            RuntimeError("DB error")
        )

        with patch.object(
            self.handler, "_send_internal_server_error_response"
        ) as mock_err:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            mock_err.assert_called_once()
            error_data = mock_err.call_args[0][2]
            assert "Failed to fetch performance data" in error_data["error"]


# ---------------------------------------------------------------------------
# Test _parse_query_params
# ---------------------------------------------------------------------------


class TestParseQueryParams:
    """Tests for _parse_query_params."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()

    def test_no_query_params(self) -> None:
        """Test no query parameters returns defaults."""
        msg = _make_http_msg(url="http://localhost/api/v1/agent/predictions")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page == 1
        assert page_size == DEFAULT_PAGE_SIZE
        assert status_filter is None

    def test_page_param(self) -> None:
        """Test page parameter."""
        msg = _make_http_msg(url="http://localhost/api?page=3")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page == 3

    def test_page_size_param(self) -> None:
        """Test page_size parameter."""
        msg = _make_http_msg(url="http://localhost/api?page_size=25")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page_size == 25

    def test_page_size_capped_at_max(self) -> None:
        """Test page_size is capped at MAX_PAGE_SIZE."""
        msg = _make_http_msg(url="http://localhost/api?page_size=500")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page_size == MAX_PAGE_SIZE

    def test_status_filter_param(self) -> None:
        """Test status filter parameter."""
        msg = _make_http_msg(url="http://localhost/api?status=won")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert status_filter == "won"

    def test_all_params_combined(self) -> None:
        """Test all params together."""
        msg = _make_http_msg(
            url="http://localhost/api?page=2&page_size=20&status=pending"
        )
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page == 2
        assert page_size == 20
        assert status_filter == "pending"

    def test_invalid_page_value(self) -> None:
        """Test invalid page value falls back to default."""
        msg = _make_http_msg(url="http://localhost/api?page=abc")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page == 1  # Falls back to default due to ValueError

    def test_invalid_page_size_value(self) -> None:
        """Test invalid page_size value falls back to default."""
        msg = _make_http_msg(url="http://localhost/api?page_size=xyz")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page_size == DEFAULT_PAGE_SIZE  # Falls back to default

    def test_param_without_equals(self) -> None:
        """Test parameter without equals sign is ignored."""
        msg = _make_http_msg(url="http://localhost/api?flagonly&page=2")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert page == 2

    def test_param_with_equals_in_value(self) -> None:
        """Test parameter where value contains equals sign."""
        msg = _make_http_msg(url="http://localhost/api?status=a=b&page=1")
        page, page_size, status_filter = self.handler._parse_query_params(msg)
        assert status_filter == "a=b"


# ---------------------------------------------------------------------------
# Test _filter_and_paginate
# ---------------------------------------------------------------------------


class TestFilterAndPaginate:
    """Tests for _filter_and_paginate."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.items = [
            {"id": "1", "status": "won"},
            {"id": "2", "status": "lost"},
            {"id": "3", "status": "won"},
            {"id": "4", "status": "pending"},
            {"id": "5", "status": "lost"},
        ]

    def test_no_filter_no_pagination(self) -> None:
        """Test no filter, return all items."""
        result = self.handler._filter_and_paginate(self.items, None, 0, 100)
        assert len(result) == 5

    def test_status_filter_won(self) -> None:
        """Test filtering by 'won' status."""
        result = self.handler._filter_and_paginate(self.items, "won", 0, 100)
        assert len(result) == 2
        assert all(item["status"] == "won" for item in result)

    def test_status_filter_lost(self) -> None:
        """Test filtering by 'lost' status."""
        result = self.handler._filter_and_paginate(self.items, "lost", 0, 100)
        assert len(result) == 2

    def test_status_filter_pending(self) -> None:
        """Test filtering by 'pending' status."""
        result = self.handler._filter_and_paginate(self.items, "pending", 0, 100)
        assert len(result) == 1

    def test_status_filter_all(self) -> None:
        """Test 'all' status filter returns everything."""
        result = self.handler._filter_and_paginate(
            self.items, PREDICTION_STATUS_ALL, 0, 100
        )
        assert len(result) == 5

    def test_pagination_skip(self) -> None:
        """Test pagination with skip."""
        result = self.handler._filter_and_paginate(self.items, None, 2, 100)
        assert len(result) == 3
        assert result[0]["id"] == "3"

    def test_pagination_page_size(self) -> None:
        """Test pagination with page_size limit."""
        result = self.handler._filter_and_paginate(self.items, None, 0, 2)
        assert len(result) == 2

    def test_pagination_skip_and_page_size(self) -> None:
        """Test pagination with both skip and page_size."""
        result = self.handler._filter_and_paginate(self.items, None, 1, 2)
        assert len(result) == 2
        assert result[0]["id"] == "2"
        assert result[1]["id"] == "3"

    def test_skip_beyond_items(self) -> None:
        """Test skip beyond available items returns empty."""
        result = self.handler._filter_and_paginate(self.items, None, 10, 10)
        assert len(result) == 0

    def test_filter_and_paginate_combined(self) -> None:
        """Test filtering with pagination."""
        result = self.handler._filter_and_paginate(self.items, "won", 0, 1)
        assert len(result) == 1
        assert result[0]["status"] == "won"

    def test_empty_items(self) -> None:
        """Test with empty items list."""
        result = self.handler._filter_and_paginate([], None, 0, 10)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Test _handle_get_predictions
# ---------------------------------------------------------------------------


class TestHandleGetPredictions:
    """Tests for _handle_get_predictions."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_dialogue = _make_http_dialogue()

    def test_serves_from_stored_history(self) -> None:
        """Test predictions served from stored history when available."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history"
        )
        items = [
            {"id": "1", "status": "won"},
            {"id": "2", "status": "lost"},
        ]
        history = PredictionHistory(
            total_predictions=2,
            stored_count=2,
            items=items,
        )
        summary = AgentPerformanceSummary(prediction_history=history)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()
            response = mock_ok.call_args[0][2]
            assert response["total"] == 2
            assert len(response["items"]) == 2
            assert response["page"] == 1
            assert response["page_size"] == DEFAULT_PAGE_SIZE

    def test_serves_from_stored_history_with_status_filter(self) -> None:
        """Test predictions served from stored history with status filter."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?status=won"
        )
        items = [
            {"id": "1", "status": "won"},
            {"id": "2", "status": "lost"},
        ]
        history = PredictionHistory(
            total_predictions=2,
            stored_count=2,
            items=items,
        )
        summary = AgentPerformanceSummary(prediction_history=history)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert len(response["items"]) == 1
            assert response["items"][0]["status"] == "won"

    def test_invalid_status_filter_returns_bad_request(self) -> None:
        """Test invalid status filter returns 400."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?status=bogus"
        )

        with patch.object(self.handler, "_send_bad_request_response") as mock_bad:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_bad.assert_called_once()
            error_data = mock_bad.call_args[0][2]
            assert "Invalid status parameter" in error_data["error"]

    def test_fetches_from_subgraph_when_no_stored_history(self) -> None:
        """Test falls back to subgraph when stored history is empty."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history"
        )
        summary = AgentPerformanceSummary(prediction_history=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        mock_result = {
            "total_predictions": 5,
            "items": [{"id": str(i)} for i in range(5)],
        }

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ) as mock_ok:
            MockFetcher.return_value.fetch_predictions.return_value = mock_result
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()
            response = mock_ok.call_args[0][2]
            assert response["total"] == 5

    def test_fetches_from_subgraph_when_skip_exceeds_stored(self) -> None:
        """Test falls back to subgraph when page/skip exceeds stored items."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?page=100"
        )
        history = PredictionHistory(
            total_predictions=5,
            stored_count=5,
            items=[{"id": str(i)} for i in range(5)],
        )
        summary = AgentPerformanceSummary(prediction_history=history)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        mock_result = {
            "total_predictions": 5,
            "items": [],
        }

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ) as mock_ok:
            MockFetcher.return_value.fetch_predictions.return_value = mock_result
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()

    def test_fetches_from_subgraph_with_status_all(self) -> None:
        """Test fetching from subgraph with 'all' status passes None to fetcher."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?status=all"
        )
        summary = AgentPerformanceSummary(prediction_history=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        # status=all is not in VALID_PREDICTION_STATUSES, so it's invalid
        # Wait: looking at the code, status_filter "all" is NOT in VALID_PREDICTION_STATUSES
        # so it should return bad request. Let me check... Yes, "all" is not in
        # VALID_PREDICTION_STATUSES, it triggers bad_request first.
        # Actually no, the check is: `if status_filter and status_filter not in VALID_PREDICTION_STATUSES`
        # and VALID_PREDICTION_STATUSES does NOT include "all". So "all" would be rejected.
        # But wait - in the subgraph path, there's also
        # `status_filter if status_filter != PREDICTION_STATUS_ALL else None`.
        # This means "all" is expected as a valid value but it IS filtered out.
        # Actually the check comes first, and "all" is not in VALID_PREDICTION_STATUSES,
        # so it would be a bad request.

        with patch.object(self.handler, "_send_bad_request_response") as mock_bad:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_bad.assert_called_once()

    def test_fetches_from_subgraph_when_stored_count_zero(self) -> None:
        """Test falls back to subgraph when stored_count is 0."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history"
        )
        history = PredictionHistory(total_predictions=0, stored_count=0, items=[])
        summary = AgentPerformanceSummary(prediction_history=history)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        mock_result = {"total_predictions": 0, "items": []}

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ) as mock_ok:
            MockFetcher.return_value.fetch_predictions.return_value = mock_result
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()

    def test_exception_returns_internal_error(self) -> None:
        """Test exception returns 500."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history"
        )
        self.handler.shared_state.read_existing_performance_summary.side_effect = (
            RuntimeError("unexpected")
        )

        with patch.object(
            self.handler, "_send_internal_server_error_response"
        ) as mock_err:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            mock_err.assert_called_once()
            error_data = mock_err.call_args[0][2]
            assert "Failed to fetch predictions" in error_data["error"]

    def test_pagination_params_forwarded(self) -> None:
        """Test pagination parameters are forwarded correctly."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?page=2&page_size=5"
        )
        summary = AgentPerformanceSummary(prediction_history=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        mock_result = {"total_predictions": 10, "items": [{"id": "6"}]}

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ) as mock_ok:
            MockFetcher.return_value.fetch_predictions.return_value = mock_result
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)

            # Verify fetcher was called with correct skip and first
            call_kwargs = MockFetcher.return_value.fetch_predictions.call_args
            assert call_kwargs.kwargs["first"] == 5
            assert call_kwargs.kwargs["skip"] == 5  # (2-1) * 5

    def test_response_includes_currency_field(self) -> None:
        """Test response includes currency field."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history"
        )
        items = [{"id": "1", "status": "won"}]
        history = PredictionHistory(
            total_predictions=1, stored_count=1, items=items
        )
        summary = AgentPerformanceSummary(prediction_history=history)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["currency"] == "USD"

    def test_subgraph_path_with_no_status_filter(self) -> None:
        """Test subgraph path passes None for status_filter when not set."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history"
        )
        summary = AgentPerformanceSummary(prediction_history=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        mock_result = {"total_predictions": 0, "items": []}

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ):
            MockFetcher.return_value.fetch_predictions.return_value = mock_result
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)

            call_kwargs = MockFetcher.return_value.fetch_predictions.call_args
            assert call_kwargs.kwargs["status_filter"] is None

    def test_subgraph_path_with_valid_status_filter(self) -> None:
        """Test subgraph path passes status filter correctly."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?status=won"
        )
        summary = AgentPerformanceSummary(prediction_history=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        mock_result = {"total_predictions": 0, "items": []}

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ):
            MockFetcher.return_value.fetch_predictions.return_value = mock_result
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)

            call_kwargs = MockFetcher.return_value.fetch_predictions.call_args
            assert call_kwargs.kwargs["status_filter"] == "won"


# ---------------------------------------------------------------------------
# Test _handle_get_profit_over_time
# ---------------------------------------------------------------------------


class TestHandleGetProfitOverTime:
    """Tests for _handle_get_profit_over_time."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_dialogue = _make_http_dialogue()

    def _make_profit_summary(
        self, data_points: Optional[List[ProfitDataPoint]] = None
    ) -> AgentPerformanceSummary:
        """Create summary with profit data."""
        if data_points is None:
            data_points = [
                ProfitDataPoint(
                    date="2024-01-01",
                    timestamp=1704067200,
                    daily_profit=10.0,
                    cumulative_profit=10.0,
                ),
                ProfitDataPoint(
                    date="2024-01-02",
                    timestamp=1704153600,
                    daily_profit=5.0,
                    cumulative_profit=15.0,
                ),
            ]
        profit = ProfitOverTimeData(
            last_updated=1704153600,
            total_days=len(data_points),
            data_points=data_points,
        )
        return AgentPerformanceSummary(profit_over_time=profit)

    def test_default_window_lifetime(self) -> None:
        """Test default window is 'lifetime'."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        summary = self._make_profit_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "lifetime"

    def test_window_7d(self) -> None:
        """Test window=7d query parameter."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time?window=7d"
        )
        summary = self._make_profit_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(
            self.handler, "_filter_profit_data_by_window"
        ) as mock_filter, patch.object(self.handler, "_send_ok_response"):
            mock_filter.return_value = []
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            mock_filter.assert_called_once()
            assert mock_filter.call_args[0][1] == "7d"

    def test_invalid_window_returns_bad_request(self) -> None:
        """Test invalid window returns 400."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time?window=invalid"
        )

        with patch.object(self.handler, "_send_bad_request_response") as mock_bad:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            mock_bad.assert_called_once()
            error_data = mock_bad.call_args[0][2]
            assert "Invalid window parameter" in error_data["error"]

    def test_no_profit_data_returns_empty(self) -> None:
        """Test empty profit data returns empty points array."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        summary = AgentPerformanceSummary(profit_over_time=None)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["points"] == []
            assert response["window"] == "lifetime"

    def test_profit_data_with_no_data_points_returns_empty(self) -> None:
        """Test profit data with empty data_points returns empty points."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        profit = ProfitOverTimeData(last_updated=0, total_days=0, data_points=[])
        summary = AgentPerformanceSummary(profit_over_time=profit)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["points"] == []

    def test_response_format_with_data_points(self) -> None:
        """Test response format includes timestamp and delta_profit."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        summary = self._make_profit_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert len(response["points"]) == 2
            point = response["points"][0]
            assert "timestamp" in point
            assert "delta_profit" in point
            assert point["delta_profit"] == 10.0

    def test_response_includes_agent_id(self) -> None:
        """Test response includes agent_id."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        summary = self._make_profit_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["agent_id"] == "0xabc123"
            assert response["currency"] == "USD"

    def test_exception_returns_internal_error(self) -> None:
        """Test exception returns 500."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        self.handler.shared_state.read_existing_performance_summary.side_effect = (
            RuntimeError("DB error")
        )

        with patch.object(
            self.handler, "_send_internal_server_error_response"
        ) as mock_err:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            mock_err.assert_called_once()
            error_data = mock_err.call_args[0][2]
            assert "Failed to fetch profit over time data" in error_data["error"]

    def test_query_param_without_equals_sign(self) -> None:
        """Test profit-over-time with a query param that has no = sign."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time?flagonly&window=7d"
        )
        summary = self._make_profit_summary()
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(
            self.handler, "_filter_profit_data_by_window"
        ) as mock_filter, patch.object(self.handler, "_send_ok_response"):
            mock_filter.return_value = []
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            # The flagonly param should be skipped, window=7d should be parsed
            assert mock_filter.call_args[0][1] == "7d"


# ---------------------------------------------------------------------------
# Test _filter_profit_data_by_window
# ---------------------------------------------------------------------------


class TestFilterProfitDataByWindow:
    """Tests for _filter_profit_data_by_window."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()

    def test_lifetime_returns_all_points(self) -> None:
        """Test 'lifetime' window returns all data points unchanged."""
        points = [
            ProfitDataPoint(
                date="2024-01-01", timestamp=1704067200, daily_profit=10.0,
                cumulative_profit=10.0,
            ),
            ProfitDataPoint(
                date="2024-06-01", timestamp=1717200000, daily_profit=20.0,
                cumulative_profit=30.0,
            ),
        ]
        result = self.handler._filter_profit_data_by_window(points, "lifetime")
        assert result == points

    def test_7d_window_filters_recent(self) -> None:
        """Test 7d window filters to recent data points."""
        now = int(datetime.utcnow().timestamp())
        recent_point = ProfitDataPoint(
            date="2024-12-30",
            timestamp=now - (2 * SECONDS_PER_DAY),
            daily_profit=5.0,
            cumulative_profit=5.0,
        )
        old_point = ProfitDataPoint(
            date="2024-01-01",
            timestamp=now - (30 * SECONDS_PER_DAY),
            daily_profit=10.0,
            cumulative_profit=10.0,
        )
        points = [old_point, recent_point]

        result = self.handler._filter_profit_data_by_window(points, "7d")
        # Should return 7 data points (gap-filled days)
        assert len(result) == 7

    def test_30d_window(self) -> None:
        """Test 30d window returns 30 data points."""
        now = int(datetime.utcnow().timestamp())
        points = [
            ProfitDataPoint(
                date=datetime.utcfromtimestamp(
                    now - (i * SECONDS_PER_DAY)
                ).strftime("%Y-%m-%d"),
                timestamp=now - (i * SECONDS_PER_DAY),
                daily_profit=1.0,
                cumulative_profit=float(i),
            )
            for i in range(5)
        ]

        result = self.handler._filter_profit_data_by_window(points, "30d")
        assert len(result) == 30

    def test_90d_window(self) -> None:
        """Test 90d window returns 90 data points."""
        now = int(datetime.utcnow().timestamp())
        points = [
            ProfitDataPoint(
                date=datetime.utcfromtimestamp(now).strftime("%Y-%m-%d"),
                timestamp=now,
                daily_profit=1.0,
                cumulative_profit=1.0,
            )
        ]

        result = self.handler._filter_profit_data_by_window(points, "90d")
        assert len(result) == 90

    def test_no_data_in_window_returns_zeros(self) -> None:
        """Test window with no data in range returns zero-filled points."""
        # Create points that are very old (outside any window)
        points = [
            ProfitDataPoint(
                date="2020-01-01",
                timestamp=1577836800,
                daily_profit=10.0,
                cumulative_profit=10.0,
            )
        ]

        result = self.handler._filter_profit_data_by_window(points, "7d")
        assert len(result) == 7
        for point in result:
            assert point.daily_profit == 0.0
            assert point.cumulative_profit == 0.0

    def test_gap_filling_with_last_known_cumulative(self) -> None:
        """Test gap filling uses last known cumulative profit."""
        now = int(datetime.utcnow().timestamp())
        cutoff = now - (6 * SECONDS_PER_DAY)  # 7d window cutoff

        # Create a point on the first day of the window
        day0_date = datetime.utcfromtimestamp(cutoff).strftime("%Y-%m-%d")
        points = [
            ProfitDataPoint(
                date=day0_date,
                timestamp=cutoff,
                daily_profit=10.0,
                cumulative_profit=10.0,
            )
        ]

        result = self.handler._filter_profit_data_by_window(points, "7d")
        assert len(result) == 7
        # First day should have the actual profit
        assert result[0].daily_profit == 10.0
        assert result[0].cumulative_profit == 10.0
        # Subsequent gap-filled days should have 0 daily but maintain cumulative
        for point in result[1:]:
            assert point.daily_profit == 0.0
            assert point.cumulative_profit == 10.0

    def test_invalid_window_returns_all_points(self) -> None:
        """Test unknown window key returns all data points (days_map gives 0)."""
        points = [
            ProfitDataPoint(
                date="2024-01-01", timestamp=1704067200, daily_profit=10.0,
                cumulative_profit=10.0,
            ),
        ]
        result = self.handler._filter_profit_data_by_window(points, "unknown")
        assert result == points

    def test_data_lookup_by_date(self) -> None:
        """Test that data points are matched by date string."""
        now = int(datetime.utcnow().timestamp())
        cutoff = now - (6 * SECONDS_PER_DAY)

        day2_ts = cutoff + (2 * SECONDS_PER_DAY)
        day2_date = datetime.utcfromtimestamp(day2_ts).strftime("%Y-%m-%d")

        points = [
            ProfitDataPoint(
                date=day2_date,
                timestamp=day2_ts,
                daily_profit=15.0,
                cumulative_profit=15.0,
            )
        ]

        result = self.handler._filter_profit_data_by_window(points, "7d")
        assert len(result) == 7
        # Day 2 should have the actual data
        assert result[2].daily_profit == 15.0

    def test_cumulative_profit_rounding(self) -> None:
        """Test cumulative profit is rounded to 3 decimal places."""
        now = int(datetime.utcnow().timestamp())
        cutoff = now - (6 * SECONDS_PER_DAY)

        day0_date = datetime.utcfromtimestamp(cutoff).strftime("%Y-%m-%d")
        points = [
            ProfitDataPoint(
                date=day0_date,
                timestamp=cutoff,
                daily_profit=1.123456789,
                cumulative_profit=1.123456789,
            )
        ]

        result = self.handler._filter_profit_data_by_window(points, "7d")
        assert result[0].cumulative_profit == round(1.123456789, 3)

    def test_multiple_data_points_in_window(self) -> None:
        """Test multiple actual data points within the window."""
        now = int(datetime.utcnow().timestamp())
        cutoff = now - (6 * SECONDS_PER_DAY)

        day0_date = datetime.utcfromtimestamp(cutoff).strftime("%Y-%m-%d")
        day1_date = datetime.utcfromtimestamp(cutoff + SECONDS_PER_DAY).strftime(
            "%Y-%m-%d"
        )

        points = [
            ProfitDataPoint(
                date=day0_date,
                timestamp=cutoff,
                daily_profit=10.0,
                cumulative_profit=10.0,
            ),
            ProfitDataPoint(
                date=day1_date,
                timestamp=cutoff + SECONDS_PER_DAY,
                daily_profit=5.0,
                cumulative_profit=15.0,
            ),
        ]

        result = self.handler._filter_profit_data_by_window(points, "7d")
        assert len(result) == 7
        assert result[0].daily_profit == 10.0
        assert result[0].cumulative_profit == 10.0
        assert result[1].daily_profit == 5.0
        assert result[1].cumulative_profit == 15.0
        # Gap-filled days maintain last cumulative
        for point in result[2:]:
            assert point.cumulative_profit == 15.0


# ---------------------------------------------------------------------------
# Test _handle_get_position_details
# ---------------------------------------------------------------------------


class TestHandleGetPositionDetails:
    """Tests for _handle_get_position_details."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_dialogue = _make_http_dialogue()

    def test_valid_position_details_omen(self) -> None:
        """Test fetching position details for Omen (non-polymarket)."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet123"
        )
        position_data = {"bet_id": "bet123", "status": "won", "profit": 10.0}

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_ok_response"
        ) as mock_ok:
            MockFetcher.return_value.fetch_position_details.return_value = (
                position_data
            )
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()
            assert mock_ok.call_args[0][2] == position_data

    def test_valid_position_details_polymarket(self) -> None:
        """Test fetching position details for Polymarket."""
        handler = _make_handler(is_running_on_polymarket=True)
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet456"
        )
        position_data = {"bet_id": "bet456", "platform": "polymarket"}

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PolymarketPredictionsFetcher"
        ) as MockFetcher, patch.object(handler, "_send_ok_response") as mock_ok:
            MockFetcher.return_value.fetch_position_details.return_value = (
                position_data
            )
            handler._handle_get_position_details(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()

    def test_position_not_found(self) -> None:
        """Test returns 404 when position is not found."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/nonexistent"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_not_found_response"
        ) as mock_not_found:
            MockFetcher.return_value.fetch_position_details.return_value = None
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)
            mock_not_found.assert_called_once()

    def test_invalid_url_format(self) -> None:
        """Test returns 400 for invalid URL format (no bet ID)."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/"
        )

        with patch.object(self.handler, "_send_bad_request_response") as mock_bad:
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)
            mock_bad.assert_called_once()
            error_data = mock_bad.call_args[0][2]
            assert "Invalid URL format" in error_data["error"]

    def test_exception_returns_internal_error(self) -> None:
        """Test exception returns 500."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet789"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(
            self.handler, "_send_internal_server_error_response"
        ) as mock_err:
            MockFetcher.return_value.fetch_position_details.side_effect = RuntimeError(
                "DB error"
            )
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)
            mock_err.assert_called_once()
            error_data = mock_err.call_args[0][2]
            assert "Failed to fetch position details" in error_data["error"]

    def test_bet_id_extracted_from_url(self) -> None:
        """Test bet ID is correctly extracted from URL."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/0xabc?extra=param"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(self.handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"id": "ok"}
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)

            call_args = MockFetcher.return_value.fetch_position_details.call_args
            assert call_args[0][0] == "0xabc"

    def test_safe_address_passed_to_fetcher(self) -> None:
        """Test safe_contract_address is lowercased and passed to fetcher."""
        handler = _make_handler(safe_address="0xABC123")
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet1"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"ok": True}
            handler._handle_get_position_details(http_msg, self.http_dialogue)

            call_args = MockFetcher.return_value.fetch_position_details.call_args
            assert call_args[0][1] == "0xabc123"

    def test_store_path_passed_to_fetcher(self) -> None:
        """Test store_path is passed to fetcher."""
        handler = _make_handler(store_path="/custom/store/path")
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet1"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"ok": True}
            handler._handle_get_position_details(http_msg, self.http_dialogue)

            call_args = MockFetcher.return_value.fetch_position_details.call_args
            assert call_args[0][2] == "/custom/store/path"

    def test_fetcher_receives_context(self) -> None:
        """Test PredictionsFetcher is created with correct context and logger."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet1"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(self.handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"ok": True}
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)

            MockFetcher.assert_called_once_with(
                self.handler.context, self.handler.context.logger
            )

    def test_polymarket_fetcher_receives_context(self) -> None:
        """Test PolymarketPredictionsFetcher is created with correct context."""
        handler = _make_handler(is_running_on_polymarket=True)
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet1"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PolymarketPredictionsFetcher"
        ) as MockFetcher, patch.object(handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"ok": True}
            handler._handle_get_position_details(http_msg, self.http_dialogue)

            MockFetcher.assert_called_once_with(
                handler.context, handler.context.logger
            )

    def test_logs_bet_id(self) -> None:
        """Test logs the bet ID being fetched."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/bet999"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(self.handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"ok": True}
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)

            # Check that logger was called with bet ID info
            log_calls = [
                str(call) for call in self.handler.context.logger.info.call_args_list
            ]
            assert any("bet999" in call for call in log_calls)


# ---------------------------------------------------------------------------
# Test _handle_get_profit_over_time timestamp formatting
# ---------------------------------------------------------------------------


class TestProfitOverTimeTimestampFormatting:
    """Tests for timestamp formatting in profit-over-time endpoint."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_dialogue = _make_http_dialogue()

    def test_timestamps_are_iso_formatted(self) -> None:
        """Test that timestamps in response are ISO formatted."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        # Use a known timestamp: 2024-01-01 00:00:00 UTC = 1704067200
        points = [
            ProfitDataPoint(
                date="2024-01-01",
                timestamp=1704067200,
                daily_profit=10.0,
                cumulative_profit=10.0,
            )
        ]
        profit = ProfitOverTimeData(
            last_updated=1704067200, total_days=1, data_points=points
        )
        summary = AgentPerformanceSummary(profit_over_time=profit)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["points"][0]["timestamp"] == "2024-01-01T00:00:00Z"

    def test_delta_profit_is_cumulative_profit(self) -> None:
        """Test that delta_profit field uses cumulative_profit value."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time"
        )
        points = [
            ProfitDataPoint(
                date="2024-01-01",
                timestamp=1704067200,
                daily_profit=10.0,
                cumulative_profit=42.5,
            )
        ]
        profit = ProfitOverTimeData(
            last_updated=1704067200, total_days=1, data_points=points
        )
        summary = AgentPerformanceSummary(profit_over_time=profit)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["points"][0]["delta_profit"] == 42.5


# ---------------------------------------------------------------------------
# Test edge cases and integration-like scenarios
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and integration scenarios."""

    def setup(self) -> None:
        """Set up test fixtures."""
        self.handler = _make_handler()
        self.http_dialogue = _make_http_dialogue()

    def test_agent_details_with_none_fields(self) -> None:
        """Test agent details with all None fields."""
        details = AgentDetails(id=None, created_at=None, last_active_at=None)
        summary = AgentPerformanceSummary(agent_details=details)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )
        http_msg = _make_http_msg()

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_details(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["id"] is None
            assert response["created_at"] is None
            assert response["last_active_at"] is None

    def test_send_http_response_with_request_headers(self) -> None:
        """Test that request headers are appended to response headers."""
        http_msg = _make_http_msg(headers="X-Custom: value")
        self.handler._send_http_response(
            http_msg, self.http_dialogue, {"data": 1}, 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args.kwargs
        assert "X-Custom: value" in call_kwargs["headers"]

    def test_internal_error_response_with_request_headers(self) -> None:
        """Test internal error appends request headers."""
        http_msg = _make_http_msg(headers="X-Request-Id: 123")
        self.handler._send_internal_server_error_response(
            http_msg, self.http_dialogue, {"error": "test"}
        )
        call_kwargs = self.http_dialogue.reply.call_args.kwargs
        assert "X-Request-Id: 123" in call_kwargs["headers"]

    def test_performance_endpoint_with_param_without_value(self) -> None:
        """Test performance endpoint handles params without = sign."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/performance?flagonly"
        )
        perf = AgentPerformanceData(
            metrics=PerformanceMetricsData(), stats=PerformanceStatsData()
        )
        summary = AgentPerformanceSummary(agent_performance=perf)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_agent_performance(http_msg, self.http_dialogue)
            mock_ok.assert_called_once()
            response = mock_ok.call_args[0][2]
            assert response["window"] == "lifetime"
            assert response["currency"] == "USD"

    def test_profit_over_time_with_window_30d(self) -> None:
        """Test 30d window parameter for profit-over-time."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time?window=30d"
        )
        now = int(datetime.utcnow().timestamp())
        points = [
            ProfitDataPoint(
                date=datetime.utcfromtimestamp(now).strftime("%Y-%m-%d"),
                timestamp=now,
                daily_profit=5.0,
                cumulative_profit=5.0,
            )
        ]
        profit = ProfitOverTimeData(
            last_updated=now, total_days=1, data_points=points
        )
        summary = AgentPerformanceSummary(profit_over_time=profit)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "30d"

    def test_profit_over_time_with_window_90d(self) -> None:
        """Test 90d window parameter for profit-over-time."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/profit-over-time?window=90d"
        )
        now = int(datetime.utcnow().timestamp())
        points = [
            ProfitDataPoint(
                date=datetime.utcfromtimestamp(now).strftime("%Y-%m-%d"),
                timestamp=now,
                daily_profit=5.0,
                cumulative_profit=5.0,
            )
        ]
        profit = ProfitOverTimeData(
            last_updated=now, total_days=1, data_points=points
        )
        summary = AgentPerformanceSummary(profit_over_time=profit)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_profit_over_time(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["window"] == "90d"
            assert len(response["points"]) == 90

    def test_position_details_url_with_hex_id(self) -> None:
        """Test position details with hex address as ID."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/position-details/0x1234567890abcdef"
        )

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.handlers.PredictionsFetcher"
        ) as MockFetcher, patch.object(self.handler, "_send_ok_response"):
            MockFetcher.return_value.fetch_position_details.return_value = {"ok": True}
            self.handler._handle_get_position_details(http_msg, self.http_dialogue)
            call_args = MockFetcher.return_value.fetch_position_details.call_args
            assert call_args[0][0] == "0x1234567890abcdef"

    def test_filter_profit_data_empty_list(self) -> None:
        """Test _filter_profit_data_by_window with empty list for non-lifetime."""
        result = self.handler._filter_profit_data_by_window([], "7d")
        # Empty filtered_points triggers the zero-fill branch
        assert len(result) == 7
        for point in result:
            assert point.daily_profit == 0.0
            assert point.cumulative_profit == 0.0

    def test_filter_profit_data_empty_list_30d(self) -> None:
        """Test _filter_profit_data_by_window with empty list for 30d."""
        result = self.handler._filter_profit_data_by_window([], "30d")
        assert len(result) == 30

    def test_filter_profit_data_empty_list_90d(self) -> None:
        """Test _filter_profit_data_by_window with empty list for 90d."""
        result = self.handler._filter_profit_data_by_window([], "90d")
        assert len(result) == 90

    def test_filter_profit_data_empty_list_lifetime(self) -> None:
        """Test _filter_profit_data_by_window with empty list for lifetime."""
        result = self.handler._filter_profit_data_by_window([], "lifetime")
        assert result == []

    def test_predictions_served_from_history_with_pagination(self) -> None:
        """Test stored history pagination works correctly."""
        http_msg = _make_http_msg(
            url="http://localhost:8080/api/v1/agent/prediction-history?page=2&page_size=2"
        )
        items = [
            {"id": str(i), "status": "won"} for i in range(5)
        ]
        history = PredictionHistory(
            total_predictions=5, stored_count=5, items=items
        )
        summary = AgentPerformanceSummary(prediction_history=history)
        self.handler.shared_state.read_existing_performance_summary.return_value = (
            summary
        )

        with patch.object(self.handler, "_send_ok_response") as mock_ok:
            self.handler._handle_get_predictions(http_msg, self.http_dialogue)
            response = mock_ok.call_args[0][2]
            assert response["page"] == 2
            assert response["page_size"] == 2
            # page 2, page_size 2 -> skip=2, so items[2:4]
            assert len(response["items"]) == 2
            assert response["items"][0]["id"] == "2"
            assert response["items"][1]["id"] == "3"

    def test_send_http_response_with_version(self) -> None:
        """Test _send_http_response passes version from request."""
        http_msg = _make_http_msg(version="2.0")
        self.handler._send_http_response(
            http_msg, self.http_dialogue, "ok", 200, "OK"
        )
        call_kwargs = self.http_dialogue.reply.call_args.kwargs
        assert call_kwargs["version"] == "2.0"

    def test_profit_data_zero_fill_daily_mech_requests(self) -> None:
        """Test zero-filled profit data points have daily_mech_requests=0."""
        result = self.handler._filter_profit_data_by_window([], "7d")
        for point in result:
            assert point.daily_mech_requests == 0
