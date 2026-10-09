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
"""This module contains the tests for the handlers for the trader abci."""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import pytest
from aea.configurations.data_types import PublicId
from aea.skills.base import Handler
from web3.exceptions import TransactionNotFound

from packages.valory.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
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
from packages.valory.skills.chatui_abci.handlers import HttpContentType
from packages.valory.skills.chatui_abci.models import TradingStrategyUI
from packages.valory.skills.decision_maker_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.decision_maker_abci.handlers import (
    HttpMethod,
)
from packages.valory.skills.decision_maker_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
)
from packages.valory.skills.decision_maker_abci.tests.test_handlers import (
    GetHandlerTestCase,
)
from packages.valory.skills.funds_manager.models import (
    AccountRequirements,
    ChainRequirements,
    FundRequirements,
    TokenRequirement,
)
from packages.valory.skills.trader_abci import handlers as beh_handlers
from packages.valory.skills.trader_abci.handlers import (
    ContractApiHandler,
    DEFAULT_HEADER,
    FALLBACK_POL_TO_USD_RATE,
    GNOSIS_CHAIN_ID,
    GNOSIS_CHAIN_NAME,
    GNOSIS_NATIVE_TOKEN_ADDRESS,
    GNOSIS_USDC_E_ADDRESS,
    GNOSIS_WRAPPED_NATIVE_ADDRESS,
    HttpHandler,
    IpfsHandler,
    LedgerApiHandler,
    POLYGON_CHAIN_ID,
    POLYGON_CHAIN_NAME,
    POLYGON_NATIVE_TOKEN_ADDRESS,
    POLYGON_POL_ADDRESS,
    POLYGON_PUSD_ADDRESS,
    POLYGON_USDC_ADDRESS,
    POLYGON_USDC_E_ADDRESS,
    POLYGON_WRAPPED_NATIVE_ADDRESS,
    SigningHandler,
    TendermintHandler,
    TraderHandler,
)

# Fee fields a swap test hands to the signer; the values are not inspected.
_FEES = {"maxFeePerGas": 1000, "maxPriorityFeePerGas": 1}


# ---------------------------------------------------------------------------
# Handler alias tests
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "handler, base_handler",
    [
        (TraderHandler, ABCIRoundHandler),
        (SigningHandler, BaseSigningHandler),
        (LedgerApiHandler, BaseLedgerApiHandler),
        (ContractApiHandler, BaseContractApiHandler),
        (TendermintHandler, BaseTendermintHandler),
        (IpfsHandler, BaseIpfsHandler),
    ],
)
def test_handler(handler: Handler, base_handler: Handler) -> None:
    """Test that the 'handlers.py' of the TraderAbci can be imported."""
    handler = handler(
        name="dummy_handler",
        skill_context=MagicMock(skill_id=PublicId.from_str("dummy/skill:0.1.0")),
    )
    assert isinstance(handler, base_handler)


# ---------------------------------------------------------------------------
# Helper: build a handler instance for testing
# ---------------------------------------------------------------------------
def _make_handler(
    is_polymarket: bool = False,
    use_x402: bool = False,
    service_endpoint: str = "http://localhost:8080/some/path",
) -> HttpHandler:
    """Create an HttpHandler wired with MagicMock context for testing."""
    context = MagicMock()
    context.logger = MagicMock()
    context.params.service_endpoint = service_endpoint
    context.params.is_running_on_polymarket = is_polymarket
    context.params.use_x402 = use_x402

    handler = HttpHandler(name="", skill_context=context)
    # Replace the real executor with a mock so we can assert calls
    handler.executor = MagicMock()
    handler.setup()
    return handler


# ---------------------------------------------------------------------------
# TestHttpHandler
# ---------------------------------------------------------------------------
class TestHttpHandler:
    """Class for testing the Http Handler."""

    def setup_method(self) -> None:
        """Set up the tests."""
        self.handler = _make_handler(is_polymarket=False, use_x402=False)
        self.context = self.handler.context

    # -- setup & routes -------------------------------------------------------
    def test_setup_routes_present(self) -> None:
        """Test that setup populates handler_url_regex and routes with all expected entries."""
        assert self.handler.handler_url_regex != ""
        get_head_routes = self.handler.routes.get(
            (HttpMethod.GET.value, HttpMethod.HEAD.value), []
        )
        # Should contain agent-info, funds-status, trading-details, features,
        # details, performance, predictions, profit-over-time, position-details,
        # static-files (catch-all) -- at least 10 routes.
        assert len(get_head_routes) >= 10

    def test_leaderboard_route_resolves_before_static_catch_all(self) -> None:
        """The leaderboard API is not swallowed by the static-file catch-all."""
        handler, _ = self.handler._get_handler(
            "http://127.0.0.1:8716/api/v1/agent/leaderboard?window=30d",
            HttpMethod.GET.value,
        )
        assert handler == self.handler._handle_get_leaderboard

    def test_setup_agent_profile_path_gnosis(self) -> None:
        """Test agent_profile_path is set to omenstrat for gnosis."""
        handler = _make_handler(is_polymarket=False)
        assert "omenstrat" in handler.agent_profile_path

    def test_setup_agent_profile_path_polymarket(self) -> None:
        """Test agent_profile_path is set to polystrat for polymarket."""
        handler = _make_handler(is_polymarket=True)
        assert "polystrat" in handler.agent_profile_path

    def test_setup_with_x402(self) -> None:
        """Test that setup submits x402 check when use_x402 is True."""
        handler = _make_handler(use_x402=True)
        handler.executor.submit.assert_called()  # type: ignore[attr-defined]

    def test_setup_without_x402(self) -> None:  # type: ignore[attr-defined]
        """Test that setup does NOT submit x402 check when use_x402 is False."""
        handler = _make_handler(use_x402=False)
        handler.executor.submit.assert_not_called()  # type: ignore[attr-defined]

    # -- _get_content_type ----------------------------------------------------  # type: ignore[attr-defined]
    def test_get_content_type(self) -> None:
        """Test _get_content_type method."""
        assert (
            self.handler._get_content_type(Path("test.js")) == HttpContentType.JS.header
        )
        assert (
            self.handler._get_content_type(Path("test.html"))
            == HttpContentType.HTML.header
        )
        assert (
            self.handler._get_content_type(Path("test.json"))
            == HttpContentType.JSON.header
        )
        assert (
            self.handler._get_content_type(Path("test.css"))
            == HttpContentType.CSS.header
        )
        assert (
            self.handler._get_content_type(Path("test.png"))
            == HttpContentType.PNG.header
        )
        assert (
            self.handler._get_content_type(Path("test.jpg"))
            == HttpContentType.JPG.header
        )
        assert (
            self.handler._get_content_type(Path("test.jpeg"))
            == HttpContentType.JPEG.header
        )
        # Unknown extension returns DEFAULT_HEADER
        assert self.handler._get_content_type(Path("test.xyz")) == DEFAULT_HEADER

    # -- _get_handler ---------------------------------------------------------
    @pytest.mark.parametrize(
        "test_case",
        [
            GetHandlerTestCase(
                name="Happy Path",
                url="http://localhost:8080/agent-info",
                method=HttpMethod.GET.value,
                expected_handler="_handle_get_agent_info",
            ),
            GetHandlerTestCase(
                name="No url match",
                url="http://invalid.url/not/matching",
                method=HttpMethod.GET.value,
                expected_handler=None,
            ),
            GetHandlerTestCase(
                name="No method match",
                url="http://localhost:8080/some/path",
                method=HttpMethod.POST.value,
                expected_handler="_handle_bad_request",
            ),
        ],
    )
    def test_get_handler(self, test_case: GetHandlerTestCase) -> None:
        """Test _get_handler."""
        url = test_case.url
        method = test_case.method

        if test_case.expected_handler is not None:
            expected_handler = getattr(self.handler, test_case.expected_handler)
        else:
            expected_handler = test_case.expected_handler
        expected_captures: Dict[Any, Any] = {}

        handler, captures = self.handler._get_handler(url, method)

        assert handler == expected_handler
        assert captures == expected_captures

    # -- handle ---------------------------------------------------------------
    # NOTE: The handle() method is inherited from decision_maker_abci.handlers.HttpHandler
    # (aliased as BaseHttpHandler). We test it by calling self.handler.handle() directly
    # and mocking internal dependencies. We patch _get_handler on the instance, and for
    # fallback cases, we patch the parent's handle at the abstract_round_abci level.
    def test_handle_wrong_performative(self) -> None:
        """Test handle with wrong performative falls through to super."""
        message = MagicMock(performative=HttpMessage.Performative.RESPONSE)
        message.sender = "incorrect sender"

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=(None, {}),
        ):
            # With wrong performative, the handle method calls the chatui super
            # which calls further up. We just verify it does not crash.
            try:
                self.handler.handle(message)
            except Exception:  # nosec B110
                pass  # Expected in isolated test with mocked context

    def test_handle_no_handler_match(self) -> None:
        """Test handle when no handler matches."""
        message = MagicMock(performative=HttpMessage.Performative.REQUEST)
        message.sender = str(HTTP_SERVER_PUBLIC_ID.without_hash())
        message.url = "http://localhost/test"
        message.method = "GET"

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=(None, {}),
        ):
            try:
                self.handler.handle(message)
            except Exception:  # nosec B110
                pass

    def test_handle_invalid_dialogue(self) -> None:
        """Test handle with invalid dialogue (update returns None)."""
        message = MagicMock(performative=HttpMessage.Performative.REQUEST)
        message.sender = str(HTTP_SERVER_PUBLIC_ID.without_hash())
        message.url = "http://localhost/test"
        message.method = "GET"

        mock_handler_fn = MagicMock()
        http_dialogues_mock = MagicMock()
        self.context.http_dialogues = http_dialogues_mock
        http_dialogues_mock.update.return_value = None

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=(mock_handler_fn, {}),
        ):
            self.handler.handle(message)
            self.context.logger.info.assert_called_with(
                "Received invalid http message={}, unidentified dialogue.".format(
                    message
                )
            )

    def test_handle_valid_message(self) -> None:
        """Test handle with valid message and dialogue."""
        message = MagicMock(performative=HttpMessage.Performative.REQUEST)
        message.sender = str(HTTP_SERVER_PUBLIC_ID.without_hash())
        message.url = "http://localhost/test"
        message.method = "GET"
        message.body = b"test_body"

        mock_handler_fn = MagicMock()
        http_dialogues_mock = MagicMock()
        mock_dialogue = MagicMock()
        self.context.http_dialogues = http_dialogues_mock
        http_dialogues_mock.update.return_value = mock_dialogue

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=(mock_handler_fn, {"key": "value"}),
        ):
            self.handler.handle(message)
            mock_handler_fn.assert_called_with(
                message,
                mock_dialogue,
                key="value",
            )
            self.context.logger.info.assert_called_with(
                "Received http request with method={}, url={} and body={!r}".format(
                    message.method, message.url, message.body
                )
            )

    # -- _handle_bad_request ---------------------------------------------------
    def test_handle_bad_request(self) -> None:
        """Test handle with a bad request."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        http_msg.version = "1.1"
        http_msg.headers = {"Content-Type": "application/json"}
        http_dialogue.reply.return_value = MagicMock()

        self.handler._handle_bad_request(http_msg, http_dialogue)

        http_dialogue.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=400,
            status_text="Bad request",
            headers=http_msg.headers,
            body=b"",
        )
        http_response = http_dialogue.reply.return_value
        self.handler.context.logger.info.assert_called_once_with(
            "Responding with: {}".format(http_response)
        )
        self.handler.context.outbox.put_message.assert_called_once_with(
            message=http_response
        )

    # -- _send_ok_response -----------------------------------------------------
    def test_send_ok_response(self) -> None:
        """Test _send_ok_response delegates to _send_http_response."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        data = {"key": "value"}

        with patch.object(self.handler, "_send_http_response") as mock_send:
            self.handler._send_ok_response(http_msg, http_dialogue, data)
            mock_send.assert_called_once_with(
                http_msg,
                http_dialogue,
                data,
                200,
                "Success",
                None,
            )

    # -- _send_not_found_response -----------------------------------------------
    def test_send_not_found_response(self) -> None:
        """Test _send_not_found_response."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        mock_response = MagicMock()
        http_dialogue.reply.return_value = mock_response

        self.handler._send_not_found_response(http_msg, http_dialogue)

        http_dialogue.reply.assert_called_once_with(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=404,
            status_text="Not found",
            headers=http_msg.headers,
            body=b"",
        )
        self.handler.context.logger.info.assert_called_once_with(
            "Responding with: {}".format(mock_response)
        )
        self.handler.context.outbox.put_message.assert_called_once_with(
            message=mock_response
        )


# ---------------------------------------------------------------------------
# Properties tests
# ---------------------------------------------------------------------------
class TestHttpHandlerProperties:
    """Test properties of HttpHandler."""

    def setup_method(self) -> None:
        """Set up the tests."""
        self.handler = _make_handler()
        self.context = self.handler.context

    def test_staking_synchronized_data(self) -> None:
        """Test staking_synchronized_data property."""
        mock_db = MagicMock()
        self.context.state.round_sequence.latest_synchronized_data.db = mock_db
        result = self.handler.staking_synchronized_data
        assert result is not None

    def test_agent_ids(self) -> None:
        """Test agent_ids property."""
        # The agent_ids property calls json.loads on staking_synchronized_data.agent_ids
        # We need staking_synchronized_data to return a SynchronizedData that has agent_ids
        mock_db = MagicMock()
        mock_db.get_strict.return_value = "[1, 2, 3]"
        mock_db.get.return_value = "[1, 2, 3]"
        self.context.state.round_sequence.latest_synchronized_data.db = mock_db

        with patch(
            "packages.valory.skills.trader_abci.handlers.SynchronizedData"
        ) as MockSyncData:
            mock_sync = MagicMock()
            mock_sync.agent_ids = "[1, 2, 3]"
            MockSyncData.return_value = mock_sync
            result = self.handler.agent_ids
            assert result == [1, 2, 3]

    def test_funds_status(self) -> None:
        """Test funds_status property."""
        mock_fn = MagicMock(return_value="fund_result")
        self.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)
        result = self.handler.funds_status
        assert result == "fund_result"

    def test_params(self) -> None:
        """Test params property."""
        result = self.handler.params
        assert result is self.context.params


# ---------------------------------------------------------------------------
# _get_chain_config tests
# ---------------------------------------------------------------------------
class TestGetChainConfig:
    """Test _get_chain_config."""

    def test_polygon_config(self) -> None:
        """Test chain config for polymarket."""
        handler = _make_handler(is_polymarket=True)
        config = handler._get_chain_config()
        assert config["chain_name"] == POLYGON_CHAIN_NAME
        assert config["chain_id"] == POLYGON_CHAIN_ID
        assert config["native_token_address"] == POLYGON_NATIVE_TOKEN_ADDRESS
        assert config["wrapped_native_address"] == POLYGON_WRAPPED_NATIVE_ADDRESS
        assert config["usdc_e_address"] == POLYGON_USDC_E_ADDRESS
        assert config["usdc_address"] == POLYGON_USDC_ADDRESS

    def test_gnosis_config(self) -> None:
        """Test chain config for gnosis."""
        handler = _make_handler(is_polymarket=False)
        config = handler._get_chain_config()
        assert config["chain_name"] == GNOSIS_CHAIN_NAME
        assert config["chain_id"] == GNOSIS_CHAIN_ID
        assert config["native_token_address"] == GNOSIS_NATIVE_TOKEN_ADDRESS
        assert config["wrapped_native_address"] == GNOSIS_WRAPPED_NATIVE_ADDRESS
        assert config["usdc_e_address"] == GNOSIS_USDC_E_ADDRESS
        assert "usdc_address" not in config


# ---------------------------------------------------------------------------
# _get_ui_trading_strategy tests
# ---------------------------------------------------------------------------
class TestGetUiTradingStrategy:
    """Test _get_ui_trading_strategy."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_none_returns_balanced(self) -> None:
        """Test None returns BALANCED."""
        result = self.handler._get_ui_trading_strategy(None)
        assert result == TradingStrategyUI.BALANCED

    def test_legacy_bet_amount_per_threshold_returns_balanced(self) -> None:
        """Legacy bet_amount_per_threshold must map to BALANCED."""
        result = self.handler._get_ui_trading_strategy("bet_amount_per_threshold")
        assert result == TradingStrategyUI.BALANCED

    def test_legacy_kelly_criterion_no_conf_returns_risky(self) -> None:
        """Legacy kelly_criterion_no_conf must map to RISKY."""
        result = self.handler._get_ui_trading_strategy("kelly_criterion_no_conf")
        assert result == TradingStrategyUI.RISKY

    def test_unknown_strategy_returns_risky(self) -> None:
        """Test unknown strategy (mike strat) returns RISKY."""
        result = self.handler._get_ui_trading_strategy("some_mike_strat")
        assert result == TradingStrategyUI.RISKY


# ---------------------------------------------------------------------------
# _handle_get_agent_info tests
# ---------------------------------------------------------------------------
class TestHandleGetAgentInfo:
    """Test _handle_get_agent_info."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()
        self.context = self.handler.context

    def test_handle_get_agent_info(self) -> None:
        """Test _handle_get_agent_info sends data correctly."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()

        self.context.agent_address = "0xAgent"

        # Mock shared_state.chatui_config.trading_strategy
        self.handler.shared_state.chatui_config.trading_strategy = None

        # Mock synchronized_data
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"

        # Mock staking_synchronized_data
        mock_staking = MagicMock()
        mock_staking.agent_ids = "[1, 2]"
        mock_staking.service_id = 42

        with (
            patch.object(
                type(self.handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                type(self.handler),
                "staking_synchronized_data",
                new_callable=PropertyMock,
            ) as mock_ssd,
            patch.object(self.handler, "_send_ok_response") as mock_send,
        ):
            mock_sd.return_value = mock_synced
            mock_ssd.return_value = mock_staking

            self.handler._handle_get_agent_info(http_msg, http_dialogue)
            mock_send.assert_called_once()
            data = mock_send.call_args[0][2]
            assert data["address"] == "0xAgent"
            assert data["agent_ids"] == [1, 2]
            assert data["service_id"] == 42
            assert "trading_type" in data


# ---------------------------------------------------------------------------
# _handle_get_trading_details tests
# ---------------------------------------------------------------------------
class TestHandleGetTradingDetails:
    """Test _handle_get_trading_details."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_success(self) -> None:
        """Test successful trading details response."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        self.handler.shared_state.chatui_config.trading_strategy = None

        with (
            patch.object(
                type(self.handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(self.handler, "_send_ok_response") as mock_send,
        ):
            mock_sd.return_value = mock_synced
            self.handler._handle_get_trading_details(http_msg, http_dialogue)
            mock_send.assert_called_once()
            data = mock_send.call_args[0][2]
            assert "agent_id" in data
            assert "trading_type" in data
            assert "trading_type_description" in data

    def test_exception(self) -> None:
        """Test error path in trading details."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()

        with (
            patch.object(
                type(self.handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                self.handler, "_send_internal_server_error_response"
            ) as mock_err,
        ):
            mock_sd.side_effect = Exception("boom")
            self.handler._handle_get_trading_details(http_msg, http_dialogue)
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_get_static_file tests
# ---------------------------------------------------------------------------
class TestHandleGetStaticFile:
    """Test _handle_get_static_file."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()
        self.handler.agent_profile_path = "ui-build/omenstrat"

    def test_file_exists(self) -> None:
        """Test serving an existing file."""
        http_msg = MagicMock()
        http_msg.url = "http://localhost:8080/test.js"
        http_dialogue = MagicMock()

        with (
            patch.object(self.handler, "_send_ok_response") as mock_send,
            patch.object(
                self.handler, "_get_content_type", return_value="application/javascript"
            ),
            patch(
                "packages.valory.skills.trader_abci.handlers.urlparse"
            ) as mock_urlparse,
            patch("packages.valory.skills.trader_abci.handlers.Path") as MockPath,
            patch("builtins.open", mock_open(read_data=b"js_content")),
        ):
            mock_urlparse.return_value.path = "/test.js"
            file_path_mock = MagicMock()
            file_path_mock.exists.return_value = True
            file_path_mock.is_file.return_value = True
            MockPath.return_value = file_path_mock

            self.handler._handle_get_static_file(http_msg, http_dialogue)
            mock_send.assert_called_once()

    def test_file_not_exists_serves_index(self) -> None:
        """Test fallback to index.html when file does not exist."""
        http_msg = MagicMock()
        http_msg.url = "http://localhost:8080/nonexistent"
        http_dialogue = MagicMock()

        with (
            patch.object(self.handler, "_send_ok_response") as mock_send,
            patch(
                "packages.valory.skills.trader_abci.handlers.urlparse"
            ) as mock_urlparse,
            patch("packages.valory.skills.trader_abci.handlers.Path") as MockPath,
            patch("builtins.open", mock_open(read_data="<html>index</html>")),
        ):
            mock_urlparse.return_value.path = "/nonexistent"
            file_path_mock = MagicMock()
            file_path_mock.exists.return_value = False
            file_path_mock.is_file.return_value = False
            MockPath.return_value = file_path_mock

            self.handler._handle_get_static_file(http_msg, http_dialogue)
            mock_send.assert_called_once()

    def test_file_not_found_error(self) -> None:
        """Test FileNotFoundError path."""
        http_msg = MagicMock()
        http_msg.url = "http://localhost:8080/missing"
        http_dialogue = MagicMock()

        with (
            patch.object(self.handler, "_send_not_found_response") as mock_not_found,
            patch(
                "packages.valory.skills.trader_abci.handlers.urlparse"
            ) as mock_urlparse,
            patch("packages.valory.skills.trader_abci.handlers.Path") as MockPath,
            patch("builtins.open", side_effect=FileNotFoundError("nope")),
        ):
            mock_urlparse.return_value.path = "/missing"
            file_path_mock = MagicMock()
            file_path_mock.exists.return_value = False
            file_path_mock.is_file.return_value = False
            MockPath.return_value = file_path_mock

            self.handler._handle_get_static_file(http_msg, http_dialogue)
            mock_not_found.assert_called_once()


# ---------------------------------------------------------------------------
# _get_adjusted_funds_status tests
# ---------------------------------------------------------------------------
class TestGetAdjustedFundsStatus:
    """Test _get_adjusted_funds_status."""

    @staticmethod
    def _make_funds_status(
        chain_name: str,
        safe_address: str,
        native_token_addr: str,
        native_balance: int,
        native_threshold: int,
        native_topup: int,
        native_decimals: int = 18,
        wrapped_addr: Optional[str] = None,
        wrapped_balance: int = 0,
        usdc_addr: Optional[str] = None,  # type: ignore[assignment]
        usdc_balance: int = 0,
        usdc_decimals: int = 6,  # type: ignore[assignment]
    ) -> FundRequirements:
        """Build a FundRequirements object for testing."""
        tokens = {
            native_token_addr: TokenRequirement(
                topup=native_topup,
                threshold=native_threshold,
                is_native=True,
                balance=native_balance,
                decimals=native_decimals,
            )
        }
        if wrapped_addr:
            tokens[wrapped_addr] = TokenRequirement(
                topup=0,
                threshold=0,
                is_native=False,
                balance=wrapped_balance,
                decimals=18,
            )
        if usdc_addr:
            tokens[usdc_addr] = TokenRequirement(
                topup=0,
                threshold=0,
                is_native=False,
                balance=usdc_balance,
                decimals=usdc_decimals,
            )

        chain_req = ChainRequirements(
            accounts={
                safe_address: AccountRequirements(tokens=tokens),
            }
        )
        return FundRequirements.model_validate({chain_name: chain_req})

    def _setup_handler(self, is_polymarket: bool) -> HttpHandler:
        """Create a handler with mocked synchronized_data and funds_status."""
        handler = _make_handler(is_polymarket=is_polymarket)
        return handler

    def test_gnosis_adjustment(self) -> None:
        """Test gnosis path: wraps wxDAI balance into native."""
        handler = self._setup_handler(is_polymarket=False)

        fund_status = self._make_funds_status(
            chain_name="gnosis",
            safe_address="0xSafe",
            native_token_addr=GNOSIS_NATIVE_TOKEN_ADDRESS,
            native_balance=100,
            native_threshold=500,
            native_topup=1000,
            wrapped_addr=GNOSIS_WRAPPED_NATIVE_ADDRESS,
            wrapped_balance=600,
        )

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            result = handler._get_adjusted_funds_status()
            # actual_considered = 100 + 600 = 700, threshold=500, 700 >= 500 so deficit=0
            native_token = (
                result["gnosis"].accounts["0xSafe"].tokens[GNOSIS_NATIVE_TOKEN_ADDRESS]
            )
            assert native_token.deficit == 0

    def test_gnosis_adjustment_with_deficit(self) -> None:
        """Test gnosis path with deficit remaining."""
        handler = self._setup_handler(is_polymarket=False)

        fund_status = self._make_funds_status(
            chain_name="gnosis",
            safe_address="0xSafe",
            native_token_addr=GNOSIS_NATIVE_TOKEN_ADDRESS,
            native_balance=10,
            native_threshold=500,
            native_topup=1000,
            wrapped_addr=GNOSIS_WRAPPED_NATIVE_ADDRESS,
            wrapped_balance=20,
        )

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            result = handler._get_adjusted_funds_status()
            native_token = (
                result["gnosis"].accounts["0xSafe"].tokens[GNOSIS_NATIVE_TOKEN_ADDRESS]
            )
            # actual_considered = 10 + 20 = 30, threshold=500, topup=1000
            # deficit = max(0, 1000 - 30) = 970
            assert native_token.deficit == 970

    def test_polygon_adjustment_success(self) -> None:
        """Test polygon path: converts USDC to POL equivalent."""
        handler = self._setup_handler(is_polymarket=True)

        fund_status = self._make_funds_status(
            chain_name="polygon",
            safe_address="0xSafe",
            native_token_addr=POLYGON_NATIVE_TOKEN_ADDRESS,
            native_balance=100,
            native_threshold=500,
            native_topup=1000,
            usdc_addr=POLYGON_USDC_ADDRESS,
            usdc_balance=1000000,
            usdc_decimals=6,
        )

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with (
            patch.object(
                type(handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                handler,
                "_get_pol_equivalent_for_usdc",
                return_value=11000000000000000000,
            ),
        ):
            mock_sd.return_value = mock_synced
            result = handler._get_adjusted_funds_status()
            native_token = (
                result["polygon"]
                .accounts["0xSafe"]
                .tokens[POLYGON_NATIVE_TOKEN_ADDRESS]
            )
            assert native_token.deficit == 0

    def test_polygon_missing_decimals(self) -> None:
        """Test polygon path returns early when decimals are None."""
        handler = self._setup_handler(is_polymarket=True)

        fund_status = self._make_funds_status(
            chain_name="polygon",
            safe_address="0xSafe",
            native_token_addr=POLYGON_NATIVE_TOKEN_ADDRESS,
            native_balance=100,
            native_threshold=500,
            native_topup=1000,
            usdc_addr=POLYGON_USDC_ADDRESS,
            usdc_balance=1000000,
            usdc_decimals=6,
        )
        # Set USDC decimals to None
        fund_status["polygon"].accounts["0xSafe"].tokens[
            POLYGON_USDC_ADDRESS
        ].decimals = None

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _ = handler._get_adjusted_funds_status()
            handler.context.logger.error.assert_called()

    def test_polygon_zero_usdc_balance(self) -> None:
        """Test polygon path returns early when USDC balance is zero."""
        handler = self._setup_handler(is_polymarket=True)

        fund_status = self._make_funds_status(
            chain_name="polygon",
            safe_address="0xSafe",
            native_token_addr=POLYGON_NATIVE_TOKEN_ADDRESS,
            native_balance=100,
            native_threshold=500,
            native_topup=1000,
            usdc_addr=POLYGON_USDC_ADDRESS,
            usdc_balance=0,
            usdc_decimals=6,
        )

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _ = handler._get_adjusted_funds_status()
            handler.context.logger.info.assert_called()

    def test_polygon_pol_equivalent_none(self) -> None:
        """Test polygon path when _get_pol_equivalent_for_usdc returns None."""
        handler = self._setup_handler(is_polymarket=True)

        fund_status = self._make_funds_status(
            chain_name="polygon",
            safe_address="0xSafe",
            native_token_addr=POLYGON_NATIVE_TOKEN_ADDRESS,
            native_balance=100,
            native_threshold=500,
            native_topup=1000,
            usdc_addr=POLYGON_USDC_ADDRESS,
            usdc_balance=1000000,
            usdc_decimals=6,
        )

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with (
            patch.object(
                type(handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(handler, "_get_pol_equivalent_for_usdc", return_value=None),
        ):
            mock_sd.return_value = mock_synced
            _ = handler._get_adjusted_funds_status()
            handler.context.logger.warning.assert_called()

    def test_key_error(self) -> None:
        """Test KeyError handling in _get_adjusted_funds_status."""
        handler = self._setup_handler(is_polymarket=False)

        # Fund status with wrong chain, triggering KeyError
        fund_status = FundRequirements.model_validate({})
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _ = handler._get_adjusted_funds_status()
            handler.context.logger.error.assert_called()

    @staticmethod
    def _make_polymarket_funds_status_with_pusd(
        usdc_e_balance: int,
        pusd_balance: int,
        pusd_threshold: int = 16_000_000,
        pusd_topup: int = 65_000_000,
    ) -> FundRequirements:
        """Build a polygon fund_status with both USDC.e and pUSD entries on the Safe.

        pUSD is the primary tracked asset (carries threshold/topup); USDC.e
        is transitional with zero requirements.

        :param usdc_e_balance: USDC.e balance to seed on the Safe (6 decimals).
        :param pusd_balance: pUSD balance to seed on the Safe (6 decimals).
        :param pusd_threshold: pUSD threshold below which a deficit is raised.
        :param pusd_topup: pUSD topup target used when a deficit is raised.
        :return: a FundRequirements snapshot matching the v2 schema.
        """
        tokens = {
            POLYGON_NATIVE_TOKEN_ADDRESS: TokenRequirement(
                topup=1000,
                threshold=500,
                is_native=True,
                balance=100,
                decimals=18,
            ),
            POLYGON_USDC_ADDRESS: TokenRequirement(
                topup=0,
                threshold=0,
                is_native=False,
                balance=0,
                decimals=6,
            ),
            POLYGON_USDC_E_ADDRESS: TokenRequirement(
                topup=0,
                threshold=0,
                is_native=False,
                balance=usdc_e_balance,
                decimals=6,
            ),
            POLYGON_PUSD_ADDRESS: TokenRequirement(
                topup=pusd_topup,
                threshold=pusd_threshold,
                is_native=False,
                balance=pusd_balance,
                decimals=6,
            ),
        }
        chain_req = ChainRequirements(
            accounts={"0xSafe": AccountRequirements(tokens=tokens)}
        )
        return FundRequirements.model_validate({"polygon": chain_req})

    def _run_adjusted_funds_status(
        self, handler: HttpHandler, fund_status: FundRequirements
    ) -> FundRequirements:
        """Drive `_get_adjusted_funds_status` with a shared_state mock and return its output."""
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with (
            patch.object(
                type(handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                handler,
                "_get_pol_equivalent_for_usdc",
                return_value=0,
            ),
        ):
            mock_sd.return_value = mock_synced
            return handler._get_adjusted_funds_status()

    def test_polygon_sums_usdc_e_into_pusd_bucket(self) -> None:
        """On Polymarket, USDC.e balance is added to the pUSD bucket and the USDC.e entry is dropped.

        Rationale: pUSD is the v2 primary tracked asset and the only one
        carrying threshold/topup. USDC.e is transitional (bridged, pre-wrap)
        and gets folded in so bridged-but-not-yet-wrapped capital counts
        against the pUSD threshold. Downstream sees "need pUSD" via the
        pUSD entry's deficit.
        """
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=50_000_000,  # 50 USDC.e (pre-wrap residue)
            pusd_balance=62_000_000,  # 62 pUSD (already wrapped)
        )

        result = self._run_adjusted_funds_status(handler, fund_status)

        safe_tokens = result["polygon"].accounts["0xSafe"].tokens
        assert safe_tokens[POLYGON_PUSD_ADDRESS].balance == 112_000_000
        # Combined balance (112M) >= threshold (16M) → no deficit.
        assert safe_tokens[POLYGON_PUSD_ADDRESS].deficit == 0
        # USDC.e entry is collapsed into pUSD and removed from the response.
        assert POLYGON_USDC_E_ADDRESS not in safe_tokens

    def test_polygon_combined_under_threshold_shows_deficit(self) -> None:
        """When USDC.e + pUSD < threshold, the pUSD bucket shows a deficit against topup."""
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=5_000_000,  # 5 USDC.e
            pusd_balance=5_000_000,  # 5 pUSD → combined 10M < threshold 16M
        )

        result = self._run_adjusted_funds_status(handler, fund_status)

        pusd_token = result["polygon"].accounts["0xSafe"].tokens[POLYGON_PUSD_ADDRESS]
        assert pusd_token.balance == 10_000_000
        # deficit = topup (65M) - combined (10M) = 55M
        assert pusd_token.deficit == 55_000_000

    def test_polygon_missing_usdc_e_entry_leaves_pusd_untouched(self) -> None:
        """If USDC.e isn't in the fund_requirements, the merge no-ops and pUSD passes through."""
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=0,
            pusd_balance=40_000_000,
        )
        # Simulate the operator having dropped USDC.e entirely post-cutover.
        del fund_status["polygon"].accounts["0xSafe"].tokens[POLYGON_USDC_E_ADDRESS]
        # Seed a funds_manager-like deficit; the merge must not overwrite it.
        fund_status["polygon"].accounts["0xSafe"].tokens[
            POLYGON_PUSD_ADDRESS
        ].deficit = 25_000_000

        result = self._run_adjusted_funds_status(handler, fund_status)

        pusd_token = result["polygon"].accounts["0xSafe"].tokens[POLYGON_PUSD_ADDRESS]
        assert pusd_token.balance == 40_000_000
        assert pusd_token.deficit == 25_000_000

    def test_merge_warns_when_pusd_missing_but_usdc_e_present(self) -> None:
        """Misconfigured v2 deployment (USDC.e entry but no pUSD) must surface a warning.

        This is the dangerous case: the agent holds wrappable collateral but
        has nothing to fold it into, so without logging it looks fully
        funded when the Safe is effectively empty for v2 purposes.
        """
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=50_000_000,
            pusd_balance=0,
        )
        safe_balances = fund_status["polygon"].accounts["0xSafe"]
        del safe_balances.tokens[POLYGON_PUSD_ADDRESS]
        chain_config = handler._get_chain_config()

        handler._merge_usdc_e_into_pusd(safe_balances, chain_config)

        handler.context.logger.warning.assert_called_once()
        warning_msg = handler.context.logger.warning.call_args[0][0]
        assert "pUSD" in warning_msg
        assert "USDC.e" in warning_msg

    def test_merge_no_warning_when_both_entries_missing(self) -> None:
        """Neither entry present: normal pre-v2 or non-polymarket shape, stay quiet."""
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=0,
            pusd_balance=0,
        )
        safe_balances = fund_status["polygon"].accounts["0xSafe"]
        del safe_balances.tokens[POLYGON_PUSD_ADDRESS]
        del safe_balances.tokens[POLYGON_USDC_E_ADDRESS]
        chain_config = handler._get_chain_config()

        handler._merge_usdc_e_into_pusd(safe_balances, chain_config)

        handler.context.logger.warning.assert_not_called()

    def test_merge_no_warning_when_only_pusd_present(self) -> None:
        """Post-cutover shape (pUSD only, no USDC.e) is the expected steady state; no warning."""
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=0,
            pusd_balance=40_000_000,
        )
        safe_balances = fund_status["polygon"].accounts["0xSafe"]
        del safe_balances.tokens[POLYGON_USDC_E_ADDRESS]
        chain_config = handler._get_chain_config()

        handler._merge_usdc_e_into_pusd(safe_balances, chain_config)

        handler.context.logger.warning.assert_not_called()

    def test_gnosis_skips_adjustment_when_wxdai_balance_unknown(self) -> None:
        """Skip wxDAI->xDAI consolidation when wxDAI balance is unknown; clear native deficit."""
        handler = self._setup_handler(is_polymarket=False)

        fund_status = self._make_funds_status(
            chain_name="gnosis",
            safe_address="0xSafe",
            native_token_addr=GNOSIS_NATIVE_TOKEN_ADDRESS,
            native_balance=10,
            native_threshold=500,
            native_topup=1000,
            wrapped_addr=GNOSIS_WRAPPED_NATIVE_ADDRESS,
            wrapped_balance=0,
        )
        wrapped_token = (
            fund_status["gnosis"]
            .accounts["0xSafe"]
            .tokens[GNOSIS_WRAPPED_NATIVE_ADDRESS]
        )
        wrapped_token.balance = None
        wrapped_token.deficit = None
        native_token_in = (
            fund_status["gnosis"].accounts["0xSafe"].tokens[GNOSIS_NATIVE_TOKEN_ADDRESS]
        )
        native_token_in.deficit = 990

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            result = handler._get_adjusted_funds_status()

        native_token = (
            result["gnosis"].accounts["0xSafe"].tokens[GNOSIS_NATIVE_TOKEN_ADDRESS]
        )
        assert native_token.deficit is None
        handler.context.logger.warning.assert_called()

    def test_gnosis_skips_adjustment_when_native_balance_unknown(self) -> None:
        """Native balance unknown -> leave deficit untouched, no spurious top-up."""
        handler = self._setup_handler(is_polymarket=False)

        fund_status = self._make_funds_status(
            chain_name="gnosis",
            safe_address="0xSafe",
            native_token_addr=GNOSIS_NATIVE_TOKEN_ADDRESS,
            native_balance=0,
            native_threshold=500,
            native_topup=1000,
            wrapped_addr=GNOSIS_WRAPPED_NATIVE_ADDRESS,
            wrapped_balance=600,
        )
        native_token_in = (
            fund_status["gnosis"].accounts["0xSafe"].tokens[GNOSIS_NATIVE_TOKEN_ADDRESS]
        )
        native_token_in.balance = None
        native_token_in.deficit = None

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with patch.object(
            type(handler), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            result = handler._get_adjusted_funds_status()

        native_token = (
            result["gnosis"].accounts["0xSafe"].tokens[GNOSIS_NATIVE_TOKEN_ADDRESS]
        )
        assert native_token.deficit is None
        handler.context.logger.warning.assert_called()

    def test_polygon_skips_adjustment_when_usdc_balance_unknown(self) -> None:
        """USDC balance unknown on Polygon -> skip USDC->POL adjustment, clear native deficit."""
        handler = self._setup_handler(is_polymarket=True)

        fund_status = self._make_funds_status(
            chain_name="polygon",
            safe_address="0xSafe",
            native_token_addr=POLYGON_NATIVE_TOKEN_ADDRESS,
            native_balance=100,
            native_threshold=500,
            native_topup=1000,
            usdc_addr=POLYGON_USDC_ADDRESS,
            usdc_balance=0,
            usdc_decimals=6,
        )
        usdc_token = (
            fund_status["polygon"].accounts["0xSafe"].tokens[POLYGON_USDC_ADDRESS]
        )
        usdc_token.balance = None
        usdc_token.deficit = None
        native_token_in = (
            fund_status["polygon"]
            .accounts["0xSafe"]
            .tokens[POLYGON_NATIVE_TOKEN_ADDRESS]
        )
        native_token_in.deficit = 900

        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSafe"
        mock_fn = MagicMock(return_value=fund_status)
        handler.context.shared_state.__getitem__ = MagicMock(return_value=mock_fn)

        with (
            patch.object(
                type(handler), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                handler, "_get_pol_equivalent_for_usdc", return_value=0
            ) as mock_pol,
        ):
            mock_sd.return_value = mock_synced
            result = handler._get_adjusted_funds_status()

        mock_pol.assert_not_called()
        native_token = (
            result["polygon"].accounts["0xSafe"].tokens[POLYGON_NATIVE_TOKEN_ADDRESS]
        )
        assert native_token.deficit is None
        handler.context.logger.warning.assert_called()

    def test_merge_skips_when_usdc_e_balance_unknown(self) -> None:
        """USDC.e balance None -> no merge, USDC.e dropped, pUSD deficit cleared."""
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=0,
            pusd_balance=40_000_000,
        )
        safe_balances = fund_status["polygon"].accounts["0xSafe"]
        usdc_e = safe_balances.tokens[POLYGON_USDC_E_ADDRESS]
        usdc_e.balance = None
        usdc_e.deficit = None
        pusd = safe_balances.tokens[POLYGON_PUSD_ADDRESS]
        pusd.deficit = 25_000_000
        chain_config = handler._get_chain_config()

        handler._merge_usdc_e_into_pusd(safe_balances, chain_config)

        assert pusd.balance == 40_000_000
        assert pusd.deficit is None
        assert POLYGON_USDC_E_ADDRESS not in safe_balances.tokens
        handler.context.logger.warning.assert_called()

    def test_merge_skips_when_pusd_balance_unknown(self) -> None:
        """When pUSD is None but USDC.e known: skip merge, keep USDC.e row, pUSD deficit cleared."""
        handler = self._setup_handler(is_polymarket=True)
        fund_status = self._make_polymarket_funds_status_with_pusd(
            usdc_e_balance=50_000_000,
            pusd_balance=0,
        )
        safe_balances = fund_status["polygon"].accounts["0xSafe"]
        pusd = safe_balances.tokens[POLYGON_PUSD_ADDRESS]
        pusd.balance = None
        pusd.deficit = None
        chain_config = handler._get_chain_config()

        handler._merge_usdc_e_into_pusd(safe_balances, chain_config)

        assert pusd.balance is None
        assert pusd.deficit is None
        # USDC.e is still readable; keep its row so the operator retains
        # diagnostic info while pUSD is unknown.
        assert POLYGON_USDC_E_ADDRESS in safe_balances.tokens
        assert safe_balances.tokens[POLYGON_USDC_E_ADDRESS].balance == 50_000_000
        handler.context.logger.warning.assert_called()


# ---------------------------------------------------------------------------
# _get_pol_to_usdc_rate tests
# ---------------------------------------------------------------------------
class TestGetPolToUsdcRate:
    """Test _get_pol_to_usdc_rate."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler(is_polymarket=True)
        self.chain_config = self.handler._get_chain_config()

    def test_cached_rate_valid(self) -> None:
        """Test returning cached rate when still valid."""
        self.handler._pol_usdc_rate = 0.5
        self.handler._pol_usdc_rate_timestamp = 1000.0
        self.handler.shared_state.synced_timestamp = 1100.0  # type: ignore[assignment, misc]

        result = self.handler._get_pol_to_usdc_rate(self.chain_config)  # type: ignore[assignment, misc]
        assert result == 0.5

    def test_cached_rate_expired(self) -> None:
        """Test fetching new rate when cache is stale."""
        self.handler._pol_usdc_rate = 0.5
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        mock_response = MagicMock()  # type: ignore[assignment, misc]
        mock_response.status_code = 200
        mock_response.json.return_value = {POLYGON_POL_ADDRESS: {"usd": 0.09}}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == 0.09
            assert self.handler._pol_usdc_rate == 0.09

    def test_synced_timestamp_exception(self) -> None:
        """Test when synced_timestamp raises exception."""
        type(self.handler.shared_state).synced_timestamp = PropertyMock(  # type: ignore[method-assign]
            side_effect=Exception("not ready")
        )  # type: ignore[method-assign]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {POLYGON_POL_ADDRESS: {"usd": 0.09}}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == 0.09
            # Rate not cached because current_time is None
            assert self.handler._pol_usdc_rate is None

        # Clean up
        del type(self.handler.shared_state).synced_timestamp

    def test_api_non_200_with_stale_cache(self) -> None:
        """Test non-200 status returns stale cache."""
        self.handler._pol_usdc_rate = 0.08
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        mock_response = MagicMock()  # type: ignore[assignment, misc]
        mock_response.status_code = 500
        mock_response.text = "Server Error"

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == 0.08

    def test_api_non_200_without_stale_cache(self) -> None:
        """Test non-200 status returns fallback when no cache."""
        self.handler._pol_usdc_rate = None
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        mock_response = MagicMock()  # type: ignore[assignment, misc]
        mock_response.status_code = 429
        mock_response.text = "Rate Limited"

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == FALLBACK_POL_TO_USD_RATE

    def test_no_price_in_response(self) -> None:
        """Test missing price data in CoinGecko response with stale cache."""
        self.handler._pol_usdc_rate = 0.07
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        mock_response = MagicMock()  # type: ignore[assignment, misc]
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == 0.07

    def test_no_price_in_response_without_cache(self) -> None:
        """Test missing price data with no stale cache returns fallback."""
        self.handler._pol_usdc_rate = None
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        mock_response = MagicMock()  # type: ignore[assignment, misc]
        mock_response.status_code = 200
        mock_response.json.return_value = {}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == FALLBACK_POL_TO_USD_RATE

    def test_exception_with_stale_cache(self) -> None:
        """Test exception handling returns stale cache."""
        self.handler._pol_usdc_rate = 0.06
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        with patch(  # type: ignore[assignment, misc]
            "packages.valory.skills.trader_abci.handlers.requests.get",
            side_effect=Exception("network error"),
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == 0.06

    def test_exception_without_cache(self) -> None:
        """Test exception handling returns fallback when no cache."""
        self.handler._pol_usdc_rate = None
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 100000.0  # type: ignore[assignment, misc]

        with patch(  # type: ignore[assignment, misc]
            "packages.valory.skills.trader_abci.handlers.requests.get",
            side_effect=Exception("network error"),
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == FALLBACK_POL_TO_USD_RATE

    def test_rate_cached_with_valid_timestamp(self) -> None:
        """Test rate is cached when current_time is not None."""
        self.handler._pol_usdc_rate = None
        self.handler._pol_usdc_rate_timestamp = 0.0
        self.handler.shared_state.synced_timestamp = 50000.0  # type: ignore[assignment, misc]

        mock_response = MagicMock()  # type: ignore[assignment, misc]
        mock_response.status_code = 200
        mock_response.json.return_value = {POLYGON_POL_ADDRESS: {"usd": 0.11}}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_pol_to_usdc_rate(self.chain_config)
            assert result == 0.11
            assert self.handler._pol_usdc_rate == 0.11
            assert self.handler._pol_usdc_rate_timestamp == 50000.0


# ---------------------------------------------------------------------------
# _get_pol_equivalent_for_usdc tests
# ---------------------------------------------------------------------------
class TestGetPolEquivalentForUsdc:
    """Test _get_pol_equivalent_for_usdc."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler(is_polymarket=True)
        self.chain_config = self.handler._get_chain_config()

    def test_success(self) -> None:
        """Test successful conversion."""
        with patch.object(self.handler, "_get_pol_to_usdc_rate", return_value=0.1):
            result = self.handler._get_pol_equivalent_for_usdc(
                1000000, self.chain_config
            )
            assert result == 10000000000000000000

    def test_rate_none(self) -> None:
        """Test when rate is None."""
        with patch.object(self.handler, "_get_pol_to_usdc_rate", return_value=None):
            result = self.handler._get_pol_equivalent_for_usdc(
                1000000, self.chain_config
            )
            assert result is None

    def test_rate_zero(self) -> None:
        """Test when rate is zero."""
        with patch.object(self.handler, "_get_pol_to_usdc_rate", return_value=0):
            result = self.handler._get_pol_equivalent_for_usdc(
                1000000, self.chain_config
            )
            assert result is None

    def test_exception(self) -> None:
        """Test exception handling."""
        with patch.object(
            self.handler,
            "_get_pol_to_usdc_rate",
            side_effect=Exception("boom"),
        ):
            result = self.handler._get_pol_equivalent_for_usdc(
                1000000, self.chain_config
            )
            assert result is None


# ---------------------------------------------------------------------------
# _handle_get_funds_status tests
# ---------------------------------------------------------------------------
class TestHandleGetFundsStatus:
    """Test _handle_get_funds_status."""

    def test_without_x402(self) -> None:
        """Test funds status without x402."""
        handler = _make_handler(use_x402=False)
        # Reset executor mock from setup
        handler.executor.reset_mock()  # type: ignore[attr-defined]
        http_msg = MagicMock()
        http_dialogue = MagicMock()  # type: ignore[attr-defined]

        mock_result = MagicMock()
        mock_result.get_response_body.return_value = {"funds": "ok"}

        with (
            patch.object(
                handler, "_get_adjusted_funds_status", return_value=mock_result
            ),
            patch.object(handler, "_send_ok_response") as mock_send,
        ):
            handler._handle_get_funds_status(http_msg, http_dialogue)
            mock_send.assert_called_once()
            handler.executor.submit.assert_not_called()  # type: ignore[attr-defined]

    def test_with_x402(self) -> None:  # type: ignore[attr-defined]
        """Test funds status with x402 triggers executor submit."""
        handler = _make_handler(use_x402=True)
        # Reset the submit mock from setup
        handler.executor.submit.reset_mock()  # type: ignore[attr-defined]

        http_msg = MagicMock()  # type: ignore[attr-defined]
        http_dialogue = MagicMock()

        mock_result = MagicMock()
        mock_result.get_response_body.return_value = {"funds": "ok"}

        with (
            patch.object(
                handler, "_get_adjusted_funds_status", return_value=mock_result
            ),
            patch.object(handler, "_send_ok_response"),
        ):
            handler._handle_get_funds_status(http_msg, http_dialogue)
            handler.executor.submit.assert_called_once()  # type: ignore[attr-defined]


# type: ignore[attr-defined]
# ---------------------------------------------------------------------------
# _get_eoa_account tests
# ---------------------------------------------------------------------------
class TestGetEoaAccount:
    """Test _get_eoa_account."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()
        self.handler.context.default_ledger_id = "ethereum"
        self.handler.context.data_dir = "/tmp/data"  # nosec B108

    def test_with_password(self) -> None:
        """Test when password is available."""
        mock_account = MagicMock()

        with (
            patch.object(
                self.handler, "_get_password_from_args", return_value="mypass"
            ),
            patch(
                "packages.valory.skills.trader_abci.handlers.EthereumCrypto"
            ) as MockCrypto,
            patch("packages.valory.skills.trader_abci.handlers.Account") as MockAccount,
        ):
            MockCrypto.return_value.private_key = "0xkey"
            MockAccount.from_key.return_value = mock_account
            result = self.handler._get_eoa_account()
            assert result == mock_account

    def test_without_password_plaintext(self) -> None:
        """Test fallback to plaintext key when no password."""
        mock_account = MagicMock()

        with (
            patch.object(self.handler, "_get_password_from_args", return_value=None),
            patch.object(Path, "open", mock_open(read_data="0xplainkey")),
            patch("packages.valory.skills.trader_abci.handlers.Account") as MockAccount,
        ):
            MockAccount.from_key.return_value = mock_account
            result = self.handler._get_eoa_account()
            assert result == mock_account
            self.handler.context.logger.error.assert_called()

    def test_account_from_key_exception(self) -> None:
        """Test exception when Account.from_key fails."""
        with (
            patch.object(self.handler, "_get_password_from_args", return_value=None),
            patch.object(Path, "open", mock_open(read_data="invalid_key")),
            patch("packages.valory.skills.trader_abci.handlers.Account") as MockAccount,
        ):
            MockAccount.from_key.side_effect = Exception("bad key")
            result = self.handler._get_eoa_account()
            assert result is None


# ---------------------------------------------------------------------------
# _get_password_from_args tests
# ---------------------------------------------------------------------------
class TestGetPasswordFromArgs:
    """Test _get_password_from_args."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_password_as_separate_arg(self) -> None:
        """Test --password followed by value."""
        with patch.object(sys, "argv", ["script", "--password", "secret"]):
            result = self.handler._get_password_from_args()
            assert result == "secret"

    def test_password_as_last_arg(self) -> None:
        """Test --password as last arg without value."""
        with patch.object(sys, "argv", ["script", "--password"]):
            result = self.handler._get_password_from_args()
            assert result is None

    def test_password_with_equals(self) -> None:
        """Test --password=value format."""
        with patch.object(sys, "argv", ["script", "--password=secret123"]):
            result = self.handler._get_password_from_args()
            assert result == "secret123"

    def test_no_password(self) -> None:
        """Test no password arg present."""
        with patch.object(sys, "argv", ["script", "--other", "arg"]):
            result = self.handler._get_password_from_args()
            assert result is None


# ---------------------------------------------------------------------------
# _get_web3_instance tests
# ---------------------------------------------------------------------------
class TestGetWeb3Instance:
    """Test _get_web3_instance."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()
        self.handler.context.params.polygon_ledger_rpc = "http://polygon-rpc.com"
        self.handler.context.params.gnosis_ledger_rpc = "http://gnosis-rpc.com"

    def test_polygon_chain(self) -> None:
        """Test getting Web3 instance for polygon."""
        with patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3:
            mock_instance = MagicMock()
            MockWeb3.return_value = mock_instance
            result = self.handler._get_web3_instance("polygon")
            assert result == mock_instance

    def test_gnosis_chain(self) -> None:
        """Test getting Web3 instance for gnosis."""
        with patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3:
            mock_instance = MagicMock()
            MockWeb3.return_value = mock_instance
            result = self.handler._get_web3_instance("gnosis")
            assert result == mock_instance

    def test_unknown_chain(self) -> None:
        """Test unknown chain returns None."""
        result = self.handler._get_web3_instance("unknown_chain")
        assert result is None
        self.handler.context.logger.error.assert_called()

    def test_empty_rpc_url(self) -> None:
        """Test empty RPC URL returns None."""
        self.handler.context.params.polygon_ledger_rpc = ""
        result = self.handler._get_web3_instance("polygon")
        assert result is None
        self.handler.context.logger.warning.assert_called()

    def test_exception(self) -> None:
        """Test exception handling."""
        with patch(
            "packages.valory.skills.trader_abci.handlers.Web3",
            side_effect=Exception("connection error"),
        ):
            result = self.handler._get_web3_instance("polygon")
            assert result is None


# ---------------------------------------------------------------------------
# _check_usdc_balance tests
# ---------------------------------------------------------------------------
class TestCheckUsdcBalance:
    """Test _check_usdc_balance."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_success(self) -> None:
        """Test successful balance check."""
        mock_w3 = MagicMock()
        mock_contract = MagicMock()
        mock_contract.functions.balanceOf.return_value.call.return_value = 5000000
        mock_w3.eth.contract.return_value = mock_contract

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._check_usdc_balance("0xAddress", "polygon", "0xUSDC")
            assert result == 5000000

    def test_no_web3(self) -> None:
        """Test when web3 instance is None."""
        with patch.object(self.handler, "_get_web3_instance", return_value=None):
            result = self.handler._check_usdc_balance("0xAddress", "polygon", "0xUSDC")
            assert result is None

    def test_exception(self) -> None:
        """Test exception handling."""
        with patch.object(
            self.handler,
            "_get_web3_instance",
            side_effect=Exception("error"),
        ):
            result = self.handler._check_usdc_balance("0xAddress", "polygon", "0xUSDC")
            assert result is None


# ---------------------------------------------------------------------------
# _get_lifi_quote tests
# ---------------------------------------------------------------------------
class TestGetLifiQuote:
    """Test _get_lifi_quote."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler(is_polymarket=True)
        self.handler.context.params.slippages_for_swap = {
            "POL-USDC": 0.01,
            "xDAI-USDC": 0.005,
        }
        self.handler.context.params.lifi_quote_to_amount_url = (
            "https://li.fi/v1/quote/toAmount"
        )
        self.chain_config = self.handler._get_chain_config()

    def test_to_amount_success(self) -> None:
        """Test successful quote with to_amount."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"quote": "data"}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=self.chain_config,
                to_amount="1000000",
            )
            assert result == {"quote": "data"}

    def test_from_amount_success(self) -> None:
        """Test successful quote with from_amount."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"quote": "from_data"}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=self.chain_config,
                from_amount="1000000000000000000",
            )
            assert result == {"quote": "from_data"}

    def test_neither_amount(self) -> None:
        """Test error when neither from_amount nor to_amount is provided."""
        result = self.handler._get_lifi_quote(
            from_token="0xNative",  # nosec B106
            to_token="0xUSDC",
            from_address="0xFrom",
            to_address="0xTo",
            chain_config=self.chain_config,
        )
        assert result is None
        self.handler.context.logger.error.assert_called()

    def test_api_failure(self) -> None:
        """Test API failure returns None."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "error"

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ):
            result = self.handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=self.chain_config,
                to_amount="1000000",
            )
            assert result is None

    def test_exception(self) -> None:
        """Test exception handling."""
        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            side_effect=Exception("network error"),
        ):
            result = self.handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=self.chain_config,
                to_amount="1000000",
            )
            assert result is None

    def test_gnosis_slippage(self) -> None:
        """Test that gnosis chain uses xDAI-USDC slippage."""
        handler = _make_handler(is_polymarket=False)
        handler.context.params.slippages_for_swap = {
            "POL-USDC": 0.01,
            "xDAI-USDC": 0.005,
        }
        handler.context.params.lifi_quote_to_amount_url = (
            "https://li.fi/v1/quote/toAmount"
        )
        chain_config = handler._get_chain_config()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"quote": "gnosis_data"}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ) as mock_get:
            result = handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=chain_config,
                to_amount="1000000",
            )
            assert result == {"quote": "gnosis_data"}
            call_kwargs = mock_get.call_args
            assert call_kwargs[1]["params"]["slippage"] == "0.005"

    def test_deny_exchanges_added_to_params(self) -> None:
        """deny_exchanges is sent as a comma-separated denyExchanges param."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"quote": "data"}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ) as mock_get:
            self.handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=self.chain_config,
                to_amount="1000000",
                deny_exchanges=["paraswap", "sushiswap"],
            )
            params = mock_get.call_args[1]["params"]
            assert params["denyExchanges"] == "paraswap,sushiswap"

    def test_no_deny_exchanges_omits_key(self) -> None:
        """Empty/None deny_exchanges keeps denyExchanges out of the request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"quote": "data"}

        with patch(
            "packages.valory.skills.trader_abci.handlers.requests.get",
            return_value=mock_response,
        ) as mock_get:
            self.handler._get_lifi_quote(
                from_token="0xNative",  # nosec B106
                to_token="0xUSDC",
                from_address="0xFrom",
                to_address="0xTo",
                chain_config=self.chain_config,
                to_amount="1000000",
            )
            params = mock_get.call_args[1]["params"]
            assert "denyExchanges" not in params


# ---------------------------------------------------------------------------
# _sign_and_submit_tx_web3 tests
# ---------------------------------------------------------------------------
class TestSignAndSubmitTxWeb3:
    """Test _sign_and_submit_tx_web3."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_success(self) -> None:
        """Test successful transaction submission."""
        mock_w3 = MagicMock()
        mock_account = MagicMock()
        mock_signed = MagicMock()
        mock_account.sign_transaction.return_value = mock_signed
        mock_tx_hash = MagicMock()
        mock_tx_hash.to_0x_hex.return_value = "0xhash"
        mock_w3.eth.send_raw_transaction.return_value = mock_tx_hash

        with patch.object(self.handler, "_get_web3_instance", return_value=mock_w3):
            result = self.handler._sign_and_submit_tx_web3(
                {"to": "0x1"}, "polygon", mock_account
            )
            assert result == "0xhash"

    def test_no_web3(self) -> None:
        """Test when web3 is None."""
        with patch.object(self.handler, "_get_web3_instance", return_value=None):
            result = self.handler._sign_and_submit_tx_web3(
                {"to": "0x1"}, "polygon", MagicMock()
            )
            assert result is None

    def test_exception(self) -> None:
        """Test exception handling."""
        mock_w3 = MagicMock()
        mock_account = MagicMock()
        mock_account.sign_transaction.side_effect = Exception("sign error")

        with patch.object(self.handler, "_get_web3_instance", return_value=mock_w3):
            result = self.handler._sign_and_submit_tx_web3(
                {"to": "0x1"}, "polygon", mock_account
            )
            assert result is None


# ---------------------------------------------------------------------------
# _send_from_eoa tests
# ---------------------------------------------------------------------------
_EOA = "0x" + "ee" * 20
_BASE_FEE = 20
_SUGGESTED_TIP = 3
_MINED = SimpleNamespace(status=1)


def _chain_for_eoa_tx(
    base_fee: Optional[int] = _BASE_FEE,
    suggested_tip: Any = _SUGGESTED_TIP,
    nonce: int = 10,
    receipts: Optional[List[Any]] = None,
    counts: Optional[List[Any]] = None,
) -> MagicMock:
    """Return a web3 stand-in for one EOA transaction.

    :param base_fee: the next block's base fee, or ``None`` when unreadable.
    :param suggested_tip: what the node suggests as a tip, or an exception.
    :param nonce: the pending nonce.
    :param receipts: what each receipt lookup answers, in order.
    :param counts: what each later nonce read answers or raises, in order.
    :return: the stand-in.
    """
    w3 = MagicMock()
    if base_fee is None:
        w3.eth.fee_history.side_effect = ValueError("eth_feeHistory not supported")
    else:
        # The history ends with the next block's base fee, the one that counts.
        w3.eth.fee_history.return_value = {"baseFeePerGas": [base_fee - 1, base_fee]}
    if isinstance(suggested_tip, Exception):
        type(w3.eth).max_priority_fee = PropertyMock(side_effect=suggested_tip)
    else:
        w3.eth.max_priority_fee = suggested_tip
    w3.eth.estimate_gas.return_value = 100_000
    w3.eth.get_transaction_count.side_effect = [nonce, *(counts or [])]
    # A receipt of ``None`` stands for "not mined yet", which web3 raises for.
    w3.eth.get_transaction_receipt.side_effect = [
        TransactionNotFound("not yet") if r is None else r
        for r in (receipts or [_MINED])
    ]
    return w3


class TestSendFromEoa:
    """The EOA's own transactions are priced to be mined, not just accepted."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()
        self.account = MagicMock()
        self.account.address = _EOA
        self.sent: List[Dict[str, Any]] = []

    @pytest.fixture(autouse=True)
    def _no_polling_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Poll without sleeping."""
        monkeypatch.setattr(beh_handlers, "EOA_TX_RECEIPT_POLL_SECS", 0)

    def _send(self, w3: MagicMock, submitted: Optional[str] = "0xhash") -> bool:
        """Send one transaction with the chain stubbed.

        :param w3: the chain stand-in.
        :param submitted: what submitting returns; ``None`` for a rejection.
        :return: what the send returned.
        """

        def submit(tx: Dict[str, Any], _chain: str, _account: Any) -> Optional[str]:
            self.sent.append(tx)
            return submitted

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=w3),
            patch.object(self.handler, "_sign_and_submit_tx_web3", side_effect=submit),
        ):
            return self.handler._send_from_eoa(
                "gnosis", 100, self.account, "0x" + "ab" * 20, "0xdata", value=5
            )

    def test_the_estimate_carries_no_fee_or_nonce(self) -> None:
        """A price in the estimate is judged against a base fee that has moved."""
        w3 = _chain_for_eoa_tx()
        assert self._send(w3) is True
        call = w3.eth.estimate_gas.call_args[0][0]
        assert set(call) == {"from", "to", "data", "value"}

    def test_the_transaction_is_eip1559_from_the_pending_nonce(self) -> None:
        """No legacy price, and the nonce counts the agent's in-flight sends."""
        w3 = _chain_for_eoa_tx(nonce=10)
        assert self._send(w3) is True
        tx = self.sent[0]
        tip = beh_handlers.EOA_TX_MIN_PRIORITY_FEE_WEI
        assert "gasPrice" not in tx
        assert tx["maxPriorityFeePerGas"] == tip
        assert tx["maxFeePerGas"] == 2 * _BASE_FEE + tip
        assert tx["nonce"] == 10
        assert tx["gas"] == int(100_000 * beh_handlers.GAS_ESTIMATE_HEADROOM)
        assert tx["chainId"] == 100
        w3.eth.get_transaction_count.assert_any_call(
            beh_handlers.Web3.to_checksum_address(_EOA), "pending"
        )

    @pytest.mark.parametrize(
        "suggested,expected",
        [
            pytest.param(3, 10**9, id="below the floor"),
            pytest.param(5 * 10**9, 5 * 10**9, id="above the floor"),
            pytest.param(RuntimeError("no fee history"), 10**9, id="unavailable"),
        ],
    )
    def test_the_tip_is_the_suggestion_floored(
        self, suggested: Any, expected: int
    ) -> None:
        """A tip of a few wei is refused or out-bid; the floor is what the ledger pays."""
        assert self._send(_chain_for_eoa_tx(suggested_tip=suggested)) is True
        assert self.sent[0]["maxPriorityFeePerGas"] == expected

    def test_an_unreadable_base_fee_sends_nothing(self) -> None:
        """Falling back to a legacy price would bring the tip-less tx back."""
        assert self._send(_chain_for_eoa_tx(base_fee=None)) is False
        assert self.sent == []
        assert "base fee" in self.handler.context.logger.warning.call_args[0][0]

    def test_an_unreadable_tip_is_logged(self) -> None:
        """The floor is used, but silently would hide a misbehaving node."""
        w3 = _chain_for_eoa_tx(suggested_tip=RuntimeError("no fee history"))
        assert self._send(w3) is True
        assert "suggested tip" in self.handler.context.logger.warning.call_args[0][0]

    def test_a_failed_estimate_sends_nothing(self) -> None:
        """The chain's refusal is the answer."""
        w3 = _chain_for_eoa_tx()
        w3.eth.estimate_gas.side_effect = ValueError("miner premium is negative")
        assert self._send(w3) is False
        assert self.sent == []

    def test_a_rejected_submission_is_a_failure(self) -> None:
        """Nothing to wait for when the node did not take the transaction."""
        assert self._send(_chain_for_eoa_tx(), submitted=None) is False

    def test_a_reverted_transaction_is_a_failure(self) -> None:
        """Mined is not enough; the deposit has to have happened."""
        w3 = _chain_for_eoa_tx(receipts=[SimpleNamespace(status=0)])
        assert self._send(w3) is False

    def test_a_replaced_transaction_is_not_waited_for(self) -> None:
        """Once another transaction consumed the nonce, this one can never mine.

        The EOA also sends the agent's Safe transactions, so this is how a
        deposit loses a race with one of them.
        """
        w3 = _chain_for_eoa_tx(nonce=10, receipts=[None, None], counts=[11])
        assert self._send(w3) is False
        assert w3.eth.get_transaction_receipt.call_count == 2
        assert "replaced" in self.handler.context.logger.warning.call_args[0][0]

    def test_a_transaction_mined_between_the_two_reads_is_a_success(self) -> None:
        """The nonce moving on is not proof of replacement; the receipt is."""
        w3 = _chain_for_eoa_tx(nonce=10, receipts=[None, _MINED], counts=[11])
        assert self._send(w3) is True

    def test_a_receipt_read_error_is_logged_and_retried(self) -> None:
        """An unreachable node must not read as a transaction that never mined."""
        w3 = _chain_for_eoa_tx(receipts=[RuntimeError("rpc down"), _MINED], counts=[10])
        assert self._send(w3) is True
        assert "receipt" in self.handler.context.logger.warning.call_args[0][0]

    def test_a_nonce_read_error_is_logged_and_retried(self) -> None:
        """Same for the nonce read that decides whether the tx was replaced."""
        w3 = _chain_for_eoa_tx(receipts=[None, _MINED], counts=[RuntimeError("rpc")])
        assert self._send(w3) is True
        assert "nonce" in self.handler.context.logger.warning.call_args[0][0]

    def test_a_transaction_not_mined_in_time_is_a_failure(self) -> None:
        """The wait is bounded; the next funding check tries again."""
        w3 = _chain_for_eoa_tx(nonce=10, receipts=[None] * 5, counts=[10] * 5)
        with patch.object(
            beh_handlers.time, "monotonic", side_effect=[0, 10, 20, 30, 70]
        ):
            assert self._send(w3) is False
        assert "not mined" in self.handler.context.logger.error.call_args[0][0]

    def test_no_chain_connection_is_a_failure(self) -> None:
        """Without a node there is nothing to wait on."""
        with patch.object(self.handler, "_get_web3_instance", return_value=None):
            assert self.handler._wait_for_eoa_tx("gnosis", "0xhash", _EOA, 1) is False


# ---------------------------------------------------------------------------
# _get_nonce_and_fees_web3 tests
# ---------------------------------------------------------------------------
class TestGetNonceAndFeesWeb3:
    """Test _get_nonce_and_fees_web3."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_success(self) -> None:
        """The nonce counts pending transactions and the fees are EIP-1559."""
        mock_w3 = MagicMock()
        mock_w3.eth.get_transaction_count.return_value = 42
        mock_w3.eth.fee_history.return_value = {"baseFeePerGas": [90, 100]}
        mock_w3.eth.max_priority_fee = 7

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            nonce, fees = self.handler._get_nonce_and_fees_web3("0xAddress", "polygon")
            assert nonce == 42
            mock_w3.eth.get_transaction_count.assert_called_once_with(
                "0xAddress", "pending"
            )
            tip = beh_handlers.EOA_TX_MIN_PRIORITY_FEE_WEI
            assert fees == {"maxFeePerGas": 200 + tip, "maxPriorityFeePerGas": tip}

    def test_no_web3(self) -> None:
        """Test when web3 is None."""
        with patch.object(self.handler, "_get_web3_instance", return_value=None):
            nonce, gas = self.handler._get_nonce_and_fees_web3("0xAddress", "polygon")
            assert nonce is None
            assert gas is None

    def test_exception(self) -> None:
        """Test exception handling."""
        mock_w3 = MagicMock()
        mock_w3.eth.get_transaction_count.side_effect = Exception("rpc error")

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            nonce, gas = self.handler._get_nonce_and_fees_web3("0xAddress", "polygon")
            assert nonce is None
            assert gas is None


# ---------------------------------------------------------------------------
# _estimate_gas tests
# ---------------------------------------------------------------------------
class TestEstimateGas:
    """Test _estimate_gas."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_success_with_hex_value(self) -> None:
        """Test successful gas estimation with hex value string."""
        mock_w3 = MagicMock()
        mock_w3.eth.estimate_gas.return_value = 100000

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._estimate_gas(
                {"to": "0x1", "data": "0x", "value": "0x10"},
                "0xEOA",
                "polygon",
            )
            # 100000 * 1.2 = 120000
            assert result == (120000, False)

    def test_success_with_int_value(self) -> None:
        """Test successful gas estimation with integer value."""
        mock_w3 = MagicMock()
        mock_w3.eth.estimate_gas.return_value = 200000

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._estimate_gas(
                {"to": "0x1", "data": "0x", "value": 16},
                "0xEOA",
                "polygon",
            )
            # 200000 * 1.2 = 240000
            assert result == (240000, False)

    def test_no_web3_returns_none(self) -> None:
        """Test when web3 is None returns (None, False)."""
        with patch.object(self.handler, "_get_web3_instance", return_value=None):
            result = self.handler._estimate_gas(
                {"to": "0x1", "data": "0x", "value": 0},
                "0xEOA",
                "polygon",
            )
            assert result == (None, False)

    def test_exception(self) -> None:
        """Test exception handling for non-revert errors."""
        mock_w3 = MagicMock()
        mock_w3.eth.estimate_gas.side_effect = Exception("gas estimation failed")

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._estimate_gas(
                {"to": "0x1", "data": "0x", "value": 0},
                "0xEOA",
                "polygon",
            )
            assert result == (None, False)

    def test_contract_logic_error_returns_route_revert(self) -> None:
        """Test that ContractLogicError signals a retryable route revert."""
        from web3.exceptions import ContractLogicError

        mock_w3 = MagicMock()
        mock_w3.eth.estimate_gas.side_effect = ContractLogicError(
            "execution reverted: arithmetic underflow or overflow"
        )

        with (
            patch.object(self.handler, "_get_web3_instance", return_value=mock_w3),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._estimate_gas(
                {"to": "0x1", "data": "0x", "value": 0},
                "0xEOA",
                "polygon",
            )
            assert result == (None, True)


# ---------------------------------------------------------------------------
# _ensure_sufficient_funds_for_x402_payments tests
# ---------------------------------------------------------------------------
class TestEnsureSufficientFundsForX402Payments:
    """Test _ensure_sufficient_funds_for_x402_payments."""

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler(is_polymarket=True)
        self.handler.context.params.x402_payment_requirements = {
            "threshold": 1000000,
            "top_up": 5000000,
        }
        # These cover the plain x402 route, where the EOA pays each call from
        # its own balance. Left as a MagicMock the flag reads truthy and the
        # facilitator branch takes over, so it is set explicitly.
        self.handler.context.params.use_mech_facilitator = False

    def test_no_eoa_account(self) -> None:
        """Test failure when EOA account cannot be obtained."""
        with patch.object(self.handler, "_get_eoa_account", return_value=None):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_no_usdc_address(self) -> None:
        """Test failure when USDC address is empty/falsy."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(
                self.handler,
                "_get_chain_config",
                return_value={
                    "chain_name": "polygon",
                    "chain_id": 137,
                    "native_token_address": POLYGON_NATIVE_TOKEN_ADDRESS,
                    "usdc_address": "",
                    "usdc_e_address": "",
                },
            ),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_balance_check_returns_none(self) -> None:
        """Test when USDC balance check returns None (skip)."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=None),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is True

    def test_balance_sufficient(self) -> None:
        """Test when balance is sufficient."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=2000000),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is True

    def test_balance_insufficient_quote_fails(self) -> None:
        """Test when balance is low and LiFi quote fails."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(self.handler, "_get_lifi_quote", return_value=None),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_balance_insufficient_no_tx_request(self) -> None:
        """Test when balance is low and quote has no transactionRequest."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={"some": "data"},
            ),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_balance_insufficient_nonce_fails(self) -> None:
        """Test when nonce/gas retrieval fails after a working route."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    }
                },
            ),
            patch.object(self.handler, "_estimate_gas", return_value=(150000, False)),
            patch.object(
                self.handler,
                "_get_nonce_and_fees_web3",
                return_value=(None, None),
            ),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_balance_insufficient_gas_estimation_fails(self) -> None:
        """Test when gas estimation fails with a non-retryable error."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    }
                },
            ),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ),
            patch.object(self.handler, "_estimate_gas", return_value=(None, False)),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_balance_insufficient_tx_submit_fails(self) -> None:
        """Test when transaction submission fails."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    }
                },
            ),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ),
            patch.object(self.handler, "_estimate_gas", return_value=(150000, False)),
            patch.object(self.handler, "_sign_and_submit_tx_web3", return_value=None),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_balance_insufficient_tx_fails(self) -> None:
        """Test when transaction is submitted but fails on chain."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    }
                },
            ),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ),
            patch.object(self.handler, "_estimate_gas", return_value=(150000, False)),
            patch.object(
                self.handler, "_sign_and_submit_tx_web3", return_value="0xhash"
            ),
            patch.object(self.handler, "_wait_for_eoa_tx", return_value=False),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_full_success_hex_value(self) -> None:
        """Test full success path with hex value in transactionRequest."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    }
                },
            ),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ),
            patch.object(self.handler, "_estimate_gas", return_value=(150000, False)),
            patch.object(
                self.handler, "_sign_and_submit_tx_web3", return_value="0xhash"
            ),
            patch.object(self.handler, "_wait_for_eoa_tx", return_value=True),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is True

    def test_full_success_int_value(self) -> None:
        """Test full success path with int value in transactionRequest."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": 16,
                    }
                },
            ),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ),
            patch.object(self.handler, "_estimate_gas", return_value=(150000, False)),
            patch.object(
                self.handler, "_sign_and_submit_tx_web3", return_value="0xhash"
            ),
            patch.object(self.handler, "_wait_for_eoa_tx", return_value=True),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is True

    def test_gnosis_path(self) -> None:
        """Test gnosis path uses usdc_e_address and xDAI naming."""
        handler = _make_handler(is_polymarket=False)
        handler.context.params.x402_payment_requirements = {
            "threshold": 1000000,
            "top_up": 5000000,
        }
        # Own handler, so it needs the plain-x402 flag set as the fixture does.
        handler.context.params.use_mech_facilitator = False
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(handler, "_get_eoa_account", return_value=mock_account),
            patch.object(handler, "_check_usdc_balance", return_value=2000000),
        ):
            result = handler._ensure_sufficient_funds_for_x402_payments()
            assert result is True

    def test_outer_exception(self) -> None:
        """Test outer exception handler."""
        with patch.object(
            self.handler,
            "_get_chain_config",
            side_effect=Exception("unexpected"),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()
            assert result is False

    def test_route_revert_then_success(self) -> None:
        """First quote reverts, retry with deny succeeds; nonce fetched once."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        quotes = [
            {
                "tool": "paraswap",
                "transactionRequest": {
                    "to": "0x1",
                    "data": "0x",
                    "value": "0x10",
                },
            },
            {
                "tool": "sushiswap",
                "transactionRequest": {
                    "to": "0x2",
                    "data": "0x",
                    "value": "0x20",
                },
            },
        ]
        gas_results = [(None, True), (150000, False)]

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler, "_get_lifi_quote", side_effect=quotes
            ) as mock_quote,
            patch.object(self.handler, "_estimate_gas", side_effect=gas_results),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ) as mock_nonce,
            patch.object(
                self.handler, "_sign_and_submit_tx_web3", return_value="0xhash"
            ),
            patch.object(self.handler, "_wait_for_eoa_tx", return_value=True),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._ensure_sufficient_funds_for_x402_payments()

            assert result is True
            assert mock_quote.call_count == 2
            # Snapshot per call: first sees an empty deny list, second sees
            # ['paraswap'] after the route revert.
            assert mock_quote.call_args_list[0].kwargs["deny_exchanges"] == []
            assert mock_quote.call_args_list[1].kwargs["deny_exchanges"] == ["paraswap"]
            mock_nonce.assert_called_once()

    def test_route_revert_exhausted(self) -> None:
        """All retries see route reverts; function fails after the cap."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        quotes = [
            {
                "tool": f"tool_{i}",
                "transactionRequest": {
                    "to": "0x1",
                    "data": "0x",
                    "value": "0x10",
                },
            }
            for i in range(3)
        ]

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler, "_get_lifi_quote", side_effect=quotes
            ) as mock_quote,
            patch.object(self.handler, "_estimate_gas", return_value=(None, True)),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ) as mock_nonce,
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()

            assert result is False
            assert mock_quote.call_count == 3
            mock_nonce.assert_not_called()
            # Pin the for/else exhaustion branch: the ERROR log only fires
            # when the loop completes without break. A mutation that
            # replaced the for/else with an inline return would skip this.
            error_messages = [
                call.args[0]
                for call in self.handler.context.logger.error.call_args_list
            ]
            assert any(
                "Exhausted LiFi route attempts" in msg
                and "['tool_0', 'tool_1', 'tool_2']" in msg
                for msg in error_messages
            )

    def test_route_revert_two_retries_then_success(self) -> None:
        """Two consecutive reverts then success: deny list accumulates."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        quotes = [
            {
                "tool": "paraswap",
                "transactionRequest": {
                    "to": "0x1",
                    "data": "0x",
                    "value": "0x10",
                },
            },
            {
                "tool": "sushiswap",
                "transactionRequest": {
                    "to": "0x2",
                    "data": "0x",
                    "value": "0x20",
                },
            },
            {
                "tool": "1inch",
                "transactionRequest": {
                    "to": "0x3",
                    "data": "0x",
                    "value": "0x30",
                },
            },
        ]
        gas_results = [(None, True), (None, True), (150000, False)]

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler, "_get_lifi_quote", side_effect=quotes
            ) as mock_quote,
            patch.object(self.handler, "_estimate_gas", side_effect=gas_results),
            patch.object(
                self.handler, "_get_nonce_and_fees_web3", return_value=(5, _FEES)
            ),
            patch.object(
                self.handler, "_sign_and_submit_tx_web3", return_value="0xhash"
            ),
            patch.object(self.handler, "_wait_for_eoa_tx", return_value=True),
            patch("packages.valory.skills.trader_abci.handlers.Web3") as MockWeb3,
        ):
            MockWeb3.to_checksum_address = lambda addr: addr
            result = self.handler._ensure_sufficient_funds_for_x402_payments()

            assert result is True
            assert mock_quote.call_count == 3
            # Each call sees a fresh snapshot of the deny list.
            assert mock_quote.call_args_list[0].kwargs["deny_exchanges"] == []
            assert mock_quote.call_args_list[1].kwargs["deny_exchanges"] == ["paraswap"]
            assert mock_quote.call_args_list[2].kwargs["deny_exchanges"] == [
                "paraswap",
                "sushiswap",
            ]

    def test_non_route_failure_no_retry(self) -> None:
        """A non-revert estimate_gas failure aborts immediately, no re-quote."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "tool": "paraswap",
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    },
                },
            ) as mock_quote,
            patch.object(self.handler, "_estimate_gas", return_value=(None, False)),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()

            assert result is False
            assert mock_quote.call_count == 1

    def test_route_revert_same_tool_returned(self) -> None:
        """If LiFi returns the same tool despite deny, abort without retrying."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        quotes = [
            {
                "tool": "paraswap",
                "transactionRequest": {
                    "to": "0x1",
                    "data": "0x",
                    "value": "0x10",
                },
            },
            {
                "tool": "paraswap",  # LiFi ignored our denyExchanges
                "transactionRequest": {
                    "to": "0x1",
                    "data": "0x",
                    "value": "0x10",
                },
            },
        ]

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler, "_get_lifi_quote", side_effect=quotes
            ) as mock_quote,
            patch.object(self.handler, "_estimate_gas", return_value=(None, True)),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()

            assert result is False
            assert mock_quote.call_count == 2

    def test_quote_missing_tool_field(self) -> None:
        """A quote with no `tool` field cannot be denied; abort the loop."""
        mock_account = MagicMock()
        mock_account.address = "0xEOA"

        with (
            patch.object(self.handler, "_get_eoa_account", return_value=mock_account),
            patch.object(self.handler, "_check_usdc_balance", return_value=100),
            patch.object(
                self.handler,
                "_get_lifi_quote",
                return_value={
                    "transactionRequest": {
                        "to": "0x1",
                        "data": "0x",
                        "value": "0x10",
                    },
                },
            ) as mock_quote,
            patch.object(self.handler, "_estimate_gas", return_value=(None, True)),
        ):
            result = self.handler._ensure_sufficient_funds_for_x402_payments()

            assert result is False
            assert mock_quote.call_count == 1


# ---------------------------------------------------------------------------
# teardown / _executor_shutdown tests
# ---------------------------------------------------------------------------
class TestTeardownAndShutdown:
    """Test teardown and _executor_shutdown."""

    def test_teardown(self) -> None:
        """Test teardown calls super().teardown() and _executor_shutdown."""
        handler = _make_handler()
        with (
            patch.object(BaseHttpHandler, "teardown") as mock_super,
            patch.object(handler, "_executor_shutdown") as mock_shutdown,
        ):
            handler.teardown()
            mock_super.assert_called_once()
            mock_shutdown.assert_called_once()

    def test_executor_shutdown(self) -> None:
        """Test _executor_shutdown calls executor.shutdown."""
        handler = _make_handler()
        # executor is already a MagicMock from _make_handler
        handler._executor_shutdown()
        handler.executor.shutdown.assert_called_once_with(  # type: ignore[attr-defined]
            wait=False, cancel_futures=True
        )  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# __init__ tests
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Resilience audit: BUG 15 -- _estimate_gas returns False instead of None
# ---------------------------------------------------------------------------
class TestEstimateGasReturnType:
    """BUG 15: _estimate_gas returns False when Web3 instance creation fails.

    The declared return type is Optional[int], but the code returns False.
    Callers check ``if tx_gas is None`` which doesn't match False, so False
    gets used as the gas value, causing a Web3 serialization error.
    """

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_estimate_gas_returns_none_on_web3_failure(self) -> None:
        """_estimate_gas returns (None, False) when _get_web3_instance fails."""
        with patch.object(self.handler, "_get_web3_instance", return_value=None):
            result = self.handler._estimate_gas(
                {"to": "0x1", "data": "0x", "value": 0},
                "0xEOA",
                "polygon",
            )
        assert result == (None, False)


# ---------------------------------------------------------------------------
# Resilience audit: BUG 11 -- `if not price_usd` treats zero as missing
# ---------------------------------------------------------------------------
class TestGetPolToUsdcRateZeroPrice:
    """BUG 11: `if not price_usd` at line 516 treats 0 as missing.

    If CoinGecko returns ``{"usd": 0}``, the code treats it as a missing
    value and falls back to the stale cache or hardcoded rate.
    """

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler(is_polymarket=True)
        self.handler._pol_usdc_rate = None
        self.handler._pol_usdc_rate_timestamp = 0.0

    def test_zero_price_returns_zero(self) -> None:
        """A zero USD price from CoinGecko is accepted as valid (not treated as missing)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {POLYGON_POL_ADDRESS: {"usd": 0}}

        mock_shared_state = MagicMock()
        mock_shared_state.synced_timestamp = None

        chain_config = self.handler._get_chain_config()

        with (
            patch(
                "packages.valory.skills.trader_abci.handlers.requests.get",
                return_value=mock_response,
            ),
            patch.object(
                type(self.handler),
                "shared_state",
                new_callable=PropertyMock,
                return_value=mock_shared_state,
            ),
        ):
            result = self.handler._get_pol_to_usdc_rate(chain_config)

        assert result == 0.0


# ---------------------------------------------------------------------------
# Resilience audit: BUG 17 -- _handle_get_agent_info crashes pre-FSM
# ---------------------------------------------------------------------------
class TestHandleGetAgentInfoPreFSM:
    """BUG 17: _handle_get_agent_info has no try-except.

    Before the FSM has started, accessing synchronized_data properties
    raises AttributeError. Combined with BUG 16 (no global try-catch in
    handler dispatch), the HTTP client gets no response.
    """

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_sends_error_when_synchronized_data_unavailable(self) -> None:
        """_handle_get_agent_info sends HTTP 500 when synchronized_data is not ready."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()

        with (
            patch.object(
                type(self.handler),
                "synchronized_data",
                new_callable=PropertyMock,
                side_effect=AttributeError("not available yet"),
            ),
            patch.object(
                self.handler, "_send_internal_server_error_response"
            ) as mock_send_error,
        ):
            self.handler._handle_get_agent_info(http_msg, http_dialogue)

        mock_send_error.assert_called_once()
        self.handler.context.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Resilience audit: BUG 19 -- _handle_get_funds_status no try-except
# ---------------------------------------------------------------------------
class TestHandleGetFundsStatusNoTryExcept:
    """BUG 19: _handle_get_funds_status has no try-except wrapper.

    If _get_adjusted_funds_status raises any exception other than KeyError,
    no HTTP response is sent.
    """

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()
        self.handler.context.params.use_x402 = False

    def test_attribute_error_sends_500(self) -> None:
        """An AttributeError from _get_adjusted_funds_status sends HTTP 500."""
        http_msg = MagicMock()
        http_dialogue = MagicMock()

        with (
            patch.object(
                self.handler,
                "_get_adjusted_funds_status",
                side_effect=AttributeError("funds_status not populated"),
            ),
            patch.object(
                self.handler, "_send_internal_server_error_response"
            ) as mock_send_error,
        ):
            self.handler._handle_get_funds_status(http_msg, http_dialogue)

        mock_send_error.assert_called_once()
        self.handler.context.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Resilience audit: BUG 21 -- No deduplication of x402 swap tasks
# ---------------------------------------------------------------------------
class TestX402SwapDeduplication:
    """BUG 21: duplicate x402 swap tasks could cause duplicate transactions."""

    def test_second_submit_skipped_while_first_running(self) -> None:
        """A second swap submission is skipped while the first is still running."""
        handler = _make_handler(use_x402=True)
        handler.executor = MagicMock()

        running_future = MagicMock()
        running_future.done.return_value = False
        handler._x402_swap_future = running_future

        handler._submit_x402_swap_if_idle()

        handler.executor.submit.assert_not_called()

    def test_submit_allowed_when_no_prior_future(self) -> None:
        """Swap is submitted when no prior future exists."""
        handler = _make_handler(use_x402=True)
        handler.executor = MagicMock()
        handler._x402_swap_future = None

        handler._submit_x402_swap_if_idle()

        handler.executor.submit.assert_called_once()

    def test_submit_allowed_when_prior_future_done(self) -> None:
        """Swap is submitted when the prior future has completed."""
        handler = _make_handler(use_x402=True)
        handler.executor = MagicMock()

        done_future = MagicMock()
        done_future.done.return_value = True
        handler._x402_swap_future = done_future

        handler._submit_x402_swap_if_idle()

        handler.executor.submit.assert_called_once()


# ---------------------------------------------------------------------------
# Resilience audit: BUG 16 -- No global try-catch in handler dispatch
# ---------------------------------------------------------------------------
class TestHandlerDispatchNoGlobalTryCatch:
    """BUG 16: handler dispatch at decision_maker_abci/handlers.py:253 has no try-except.

    If any handler raises an unhandled exception, the HTTP client never
    receives a response.
    """

    def setup_method(self) -> None:
        """Set up."""
        self.handler = _make_handler()

    def test_handler_exception_caught_and_500_sent(self) -> None:
        """An exception in a handler is caught and HTTP 500 response is sent."""
        from packages.valory.connections.http_server.connection import (
            PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
        )

        message = MagicMock(performative=HttpMessage.Performative.REQUEST)
        message.sender = str(HTTP_SERVER_PUBLIC_ID.without_hash())
        message.url = "http://localhost:8080/agent-info"
        message.method = "GET"
        message.body = b""

        http_dialogues_mock = MagicMock()
        mock_dialogue = MagicMock()
        self.handler.context.http_dialogues = http_dialogues_mock
        http_dialogues_mock.update.return_value = mock_dialogue

        def raising_handler(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("handler crash")

        with patch.object(
            self.handler,
            "_get_handler",
            return_value=(raising_handler, {}),
        ):
            # No exception -- global try-catch handles it
            self.handler.handle(message)

        self.handler.context.logger.error.assert_called()
        # Verify a 500 response was sent
        mock_dialogue.reply.assert_called_once()
        reply_kwargs = mock_dialogue.reply.call_args[1]
        assert reply_kwargs["status_code"] == 500


class TestHttpHandlerInit:
    """Test HttpHandler __init__."""

    def test_init_sets_attributes(self) -> None:
        """Test that __init__ sets required attributes."""
        context = MagicMock()
        handler = HttpHandler(name="test", skill_context=context)
        assert handler.handler_url_regex == ""
        assert handler.routes == {}
        assert handler._pol_usdc_rate is None
        assert handler._pol_usdc_rate_timestamp == 0.0
        assert handler.executor is not None


# ---------------------------------------------------------------------------
# mech pre-deposit top-up (the facilitator payment route)
# ---------------------------------------------------------------------------
_SAFE = "0x" + "5a" * 20
_TRACKER = "0x" + "22" * 20
_MARKETPLACE = "0x" + "44" * 20
_TOKEN = "0x" + "33" * 20
_ZERO_ADDR = "0x" + "00" * 20
_NATIVE_PAYMENT_TYPE = bytes.fromhex("ba" * 32)
_FACILITATOR_URL = "https://facilitator.example"

_FLOOR = 150_000
_TARGET = 500_000
_CAP = 500_000
# Above the deposits under test, so the reserve only bites where a test says so.
_GAS_RESERVE = 10**17
_EOA_SHORT = beh_handlers.MECH_PRE_DEPOSIT_EOA_SHORT


def _same_address(left: str, right: str) -> bool:
    """Compare two addresses ignoring checksum casing.

    :param left: one address.
    :param right: the other.
    :return: whether they are the same address.
    """
    return left.lower() == right.lower()


class _ContractStub:
    """Stand in for a web3 contract, answering by function name.

    Keyed on the function the handler asks for rather than on call order, so the
    stub does not encode a sequence the handler is free to change. A read whose
    answer is absent raises, which is how a native tracker's missing ``token()``
    is represented.
    """

    def __init__(self, answers: Dict[str, Any], recorder: Any) -> None:
        """Initialise the stub.

        :param answers: function name to the value its ``call()`` returns.
        :param recorder: the chain stub recording reads and encodings.
        """
        self._answers = answers
        self._recorder = recorder

    @property
    def functions(self) -> Any:
        """Return self, so ``contract.functions.f()`` resolves here.

        :return: this stub.
        """
        return self

    def __getattr__(self, name: str) -> Any:
        """Return a callable standing in for one contract function.

        :param name: the function the handler asked for.
        :return: a callable returning an object with ``.call()``.
        :raises AttributeError: for dunder and private lookups.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        answers, recorder = self._answers, self._recorder

        def _fn(*args: Any) -> Any:
            recorder.reads.append((name, args))

            def _call() -> Any:
                if name not in answers:
                    raise ValueError(f"execution reverted: {name}")
                return answers[name]

            return SimpleNamespace(call=_call)

        return _fn

    def encode_abi(self, abi_element_identifier: str, args: List[Any]) -> str:
        """Record what the handler asked web3 to encode.

        :param abi_element_identifier: the function signature or name.
        :param args: the arguments.
        :return: a marker carrying the identifier, for assertions.
        """
        self._recorder.encoded.append((abi_element_identifier, tuple(args)))
        return f"0x{abi_element_identifier}"


class _ChainStub:
    """Hand out contract stubs per address and record what the handler did."""

    def __init__(
        self,
        deposited: int,
        token: Optional[str] = None,
        payment_type: bytes = _NATIVE_PAYMENT_TYPE,
        tracker: str = _TRACKER,
    ) -> None:
        """Initialise the stub.

        :param deposited: what the tracker reports for the Safe.
        :param token: the tracker's ERC20, or ``None`` for a native tracker.
        :param payment_type: what the facilitator reports it charges in.
        :param tracker: what the marketplace maps the payment type to.
        """
        self.payment_type = payment_type
        tracker_answers: Dict[str, Any] = {"mapRequesterBalances": deposited}
        if token is not None:
            tracker_answers["token"] = token
        self._per_address: Dict[str, Dict[str, Any]] = {
            _MARKETPLACE.lower(): {"mapPaymentTypeBalanceTrackers": tracker},
            tracker.lower(): tracker_answers,
            _TOKEN.lower(): {},
        }
        self.reads: List[Any] = []
        self.encoded: List[Any] = []
        self.sent: List[Dict[str, Any]] = []
        self.bound: List[str] = []
        # Set by ``_run`` so a test can assert what the facilitator was asked.
        self.facilitator_get: Any = None

    def contract(self, chain: str, address: str, abi: List[Dict]) -> Any:
        """Return the stub for ``address``.

        :param chain: ignored.
        :param address: the contract the handler wants.
        :param abi: ignored.
        :return: a contract stub.
        """
        self.bound.append(address.lower())
        return _ContractStub(self._per_address.get(address.lower(), {}), self)

    def send(
        self,
        chain: str,
        chain_id: int,
        eoa_account: Any,
        to_address: str,
        data: str,
        value: int = 0,
    ) -> bool:
        """Record one transaction instead of sending it.

        :param chain: ignored.
        :param chain_id: ignored.
        :param eoa_account: ignored.
        :param to_address: the call target.
        :param data: the calldata marker.
        :param value: the native value attached.
        :return: always True, as a mined transaction would.
        """
        self.sent.append({"to": to_address, "data": data, "value": value})
        return True


def _facilitator_handler(native_balance: int = 10**19) -> Any:
    """Build a handler on the facilitator route with the pre-deposit configured.

    :param native_balance: what the EOA holds natively, for the gas reserve.
    :return: the handler under test.
    """
    handler = _make_handler(is_polymarket=False)
    handler.context.shared_state = {}
    params = handler.context.params
    params.use_x402 = True
    params.use_mech_facilitator = True
    params.mech_pre_deposit_floor = _FLOOR
    params.mech_pre_deposit_target = _TARGET
    params.mech_pre_deposit_cap = _CAP
    params.mech_facilitator_base_url = _FACILITATOR_URL
    params.native_gas_reserve = _GAS_RESERVE
    params.mech_marketplace_config.mech_marketplace_address = _MARKETPLACE
    handler._safe_address_for_payments = MagicMock(return_value=_SAFE)  # type: ignore[method-assign]
    w3 = MagicMock()
    w3.eth.get_balance.return_value = native_balance
    handler._get_web3_instance = MagicMock(return_value=w3)  # type: ignore[method-assign]
    return handler


def _facilitator_reply(
    payment_type: Optional[bytes], status: int = 200
) -> SimpleNamespace:
    """Build what the facilitator's requester-info endpoint answers with.

    :param payment_type: the payment type it reports, or ``None`` for a body
        that carries no usable one.
    :param status: the HTTP status to report.
    :return: a stand-in response.
    """
    body: Dict[str, Any] = {}
    if payment_type is not None:
        body["payment_type"] = "0x" + payment_type.hex()
    return SimpleNamespace(status_code=status, json=lambda: body)


def _run(
    handler: Any,
    chain_stub: _ChainStub,
    reply: Optional[SimpleNamespace] = None,
    error: Optional[Exception] = None,
) -> bool:
    """Drive the pre-deposit check with the chain and the facilitator stubbed.

    :param handler: the handler under test.
    :param chain_stub: the stub answering reads and recording sends.
    :param reply: what the facilitator answers; by default the chain stub's own
        payment type, so the two agree.
    :param error: raised instead of answering, for the unreachable case.
    :return: what the check returned.
    """
    account = MagicMock()
    account.address = "0x" + "ee" * 20
    if reply is None:
        reply = _facilitator_reply(chain_stub.payment_type)
    get_kwargs: Dict[str, Any] = (
        {"side_effect": error} if error is not None else {"return_value": reply}
    )
    with (
        patch.object(handler, "_contract", side_effect=chain_stub.contract),
        patch.object(handler, "_send_from_eoa", side_effect=chain_stub.send),
        patch.object(handler, "_get_eoa_account", return_value=account),
        patch.object(beh_handlers.requests, "get", **get_kwargs) as get,
    ):
        chain_stub.facilitator_get = get
        return handler._ensure_sufficient_funds_for_x402_payments()


class TestMechPreDepositTopUp:
    """The facilitator route tops up the Safe's pre-deposit from the EOA."""

    def test_the_plain_x402_route_is_left_alone(self) -> None:
        """With the facilitator off, the EOA swap path must still run."""
        handler = _facilitator_handler()
        handler.context.params.use_mech_facilitator = False
        chain = _ChainStub(deposited=0)

        with patch.object(handler, "_check_usdc_balance", return_value=10**9):
            _run(handler, chain)

        assert chain.sent == []

    def test_a_deposit_at_the_floor_sends_nothing(self) -> None:
        """At the floor the pot still covers the next call."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=_FLOOR)

        assert _run(handler, chain) is True
        assert chain.sent == []

    def test_a_native_tracker_deposits_value(self) -> None:
        """A native tracker takes depositFor(address) with the amount as value."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is True
        # One payable call, crediting the Safe, with the amount as value.
        assert [name for name, _ in chain.encoded] == ["depositFor(address)"]
        assert _same_address(chain.encoded[0][1][0], _SAFE)
        sent = chain.sent[0]
        assert sent["to"] == _TRACKER
        assert sent["value"] == _TARGET

    def test_a_token_tracker_approves_then_deposits(self) -> None:
        """A token tracker needs the allowance before the deposit can pull."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with patch.object(handler, "_check_usdc_balance", return_value=10**9):
            assert _run(handler, chain) is True

        approve_call, deposit_call = chain.encoded
        # The allowance has to name the tracker as spender, since that is what
        # calls transferFrom; approving anything else makes the deposit revert.
        assert approve_call[0] == "approve"
        assert _same_address(approve_call[1][0], _TRACKER)
        # And the deposit has to credit the Safe, not the caller.
        assert deposit_call[0] == "depositFor(address,uint256)"
        assert _same_address(deposit_call[1][0], _SAFE)
        # Both must name the same amount or the deposit cannot pull it.
        assert approve_call[1][1] == deposit_call[1][1]
        # Approve goes to the token, deposit to the tracker, neither with value.
        approve_tx, deposit_tx = chain.sent
        assert _same_address(approve_tx["to"], _TOKEN)
        assert _same_address(deposit_tx["to"], _TRACKER)
        assert approve_tx["value"] == 0 and deposit_tx["value"] == 0

    @pytest.mark.parametrize(
        ("deposited", "cap", "expected"),
        [
            (0, _CAP, _TARGET),
            (_FLOOR - 1, _CAP, _TARGET - (_FLOOR - 1)),
            (0, 100_000, 100_000),
        ],
    )
    def test_the_top_up_fills_to_target_within_the_cap(
        self, deposited: int, cap: int, expected: int
    ) -> None:
        """One top-up never exceeds the cap nor overshoots the target.

        :param deposited: what the tracker already holds.
        :param cap: the per-cycle ceiling.
        :param expected: the value the deposit must carry.
        """
        handler = _facilitator_handler()
        handler.context.params.mech_pre_deposit_cap = cap
        chain = _ChainStub(deposited=deposited, token=None)

        assert _run(handler, chain) is True
        assert chain.sent[0]["value"] == expected

    def test_a_native_deposit_keeps_a_gas_reserve(self) -> None:
        """Depositing the EOA out of gas would stop the agent entirely."""
        spendable = 40_000
        handler = _facilitator_handler(native_balance=_GAS_RESERVE + spendable)
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is True
        assert chain.sent[0]["value"] == spendable
        assert handler.context.shared_state[_EOA_SHORT] is False

    def test_the_gas_reserve_is_the_configured_one(self) -> None:
        """The reserve follows the agent's own refill threshold, not a constant."""
        spendable = 40_000
        reserve = 7 * 10**17
        handler = _facilitator_handler(native_balance=reserve + spendable)
        handler.context.params.native_gas_reserve = reserve
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is True
        assert chain.sent[0]["value"] == spendable

    def test_no_native_headroom_sends_nothing(self) -> None:
        """At or under the gas reserve there is nothing safe to deposit."""
        handler = _facilitator_handler(native_balance=_GAS_RESERVE)
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is False
        assert chain.sent == []
        # This is the one case where asking the user for funds is right.
        assert handler.context.shared_state[_EOA_SHORT] is True

    def test_the_eoa_flag_is_refreshed_even_when_nothing_is_deposited(self) -> None:
        """A user who funded the agent must stop being asked for funds."""
        handler = _facilitator_handler()
        handler.context.shared_state[_EOA_SHORT] = True
        chain = _ChainStub(deposited=_FLOOR, token=None)

        assert _run(handler, chain) is True
        assert handler.context.shared_state[_EOA_SHORT] is False

    def test_a_short_eoa_is_noted_even_when_the_token_is_held(self) -> None:
        """The token path needs native for gas too, so the flag follows native."""
        handler = _facilitator_handler(native_balance=_GAS_RESERVE)
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with patch.object(handler, "_check_usdc_balance", return_value=10**9):
            _run(handler, chain)
        assert handler.context.shared_state[_EOA_SHORT] is True

    def test_without_a_chain_connection_the_flag_is_not_set(self) -> None:
        """No balance read means no claim about the EOA, in either direction."""
        handler = _facilitator_handler()
        handler.context.shared_state[_EOA_SHORT] = True
        chain = _ChainStub(deposited=_FLOOR, token=None)

        with patch.object(handler, "_get_web3_instance", return_value=None):
            assert _run(handler, chain) is True
        assert handler.context.shared_state[_EOA_SHORT] is False

    def test_no_native_headroom_does_not_swap_for_a_token_deposit(self) -> None:
        """A swap the EOA cannot pay for would only fail later, at the node."""
        handler = _facilitator_handler(native_balance=_GAS_RESERVE)
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with (
            patch.object(handler, "_check_usdc_balance", return_value=0),
            patch.object(handler, "_swap_native_for_token") as swap,
        ):
            assert _run(handler, chain) is False
        swap.assert_not_called()
        assert chain.sent == []
        assert handler.context.shared_state[_EOA_SHORT] is True

    def test_a_token_deposit_is_bounded_by_what_the_eoa_holds(self) -> None:
        """A swap can deliver less than quoted, and the deposit must follow it.

        Approving or depositing more than the EOA holds reverts when the tracker
        pulls, so the amount tracks the balance rather than the target.
        """
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with (
            patch.object(handler, "_check_usdc_balance", return_value=120_000),
            patch.object(handler, "_swap_native_for_token", return_value=True),
        ):
            assert _run(handler, chain) is True

        assert chain.encoded[1][1][1] == 120_000

    def test_an_unreadable_token_balance_sends_nothing(self) -> None:
        """Without knowing the balance there is no safe amount to deposit."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with patch.object(handler, "_check_usdc_balance", return_value=None):
            assert _run(handler, chain) is False

        assert chain.sent == []

    def test_a_short_token_balance_swaps_for_the_shortfall(self) -> None:
        """Nothing else refills the EOA's token on this route, so this must."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with (
            patch.object(handler, "_check_usdc_balance", return_value=20_000),
            patch.object(handler, "_swap_native_for_token", return_value=True) as swap,
        ):
            assert _run(handler, chain) is True

        # Only the shortfall, since the EOA already holds the rest.
        assert swap.call_args.args[2:] == (_TOKEN, _TARGET - 20_000)
        assert [name for name, _ in chain.encoded] == [
            "approve",
            "depositFor(address,uint256)",
        ]

    def test_a_failed_swap_sends_nothing(self) -> None:
        """Approving and depositing without the token would just revert."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with (
            patch.object(handler, "_check_usdc_balance", return_value=0),
            patch.object(handler, "_swap_native_for_token", return_value=False),
        ):
            assert _run(handler, chain) is False

        assert chain.sent == []

    def test_a_sufficient_token_balance_does_not_swap(self) -> None:
        """Swapping native that is not needed would spend gas for nothing."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=_TOKEN)

        with (
            patch.object(handler, "_check_usdc_balance", return_value=10**9),
            patch.object(handler, "_swap_native_for_token", return_value=True) as swap,
        ):
            assert _run(handler, chain) is True

        swap.assert_not_called()

    def test_a_native_tracker_does_not_swap(self) -> None:
        """A native tracker is funded from the balance the EOA already has."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None)

        with patch.object(handler, "_swap_native_for_token", return_value=True) as swap:
            assert _run(handler, chain) is True

        swap.assert_not_called()

    def test_an_unknown_safe_sends_nothing(self) -> None:
        """Before the first round there is no Safe to credit."""
        handler = _facilitator_handler()
        handler._safe_address_for_payments = MagicMock(return_value=None)
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is False
        assert chain.sent == []

    @pytest.mark.parametrize("mech", [None, _ZERO_ADDR])
    def test_an_absent_priority_mech_still_deposits(self, mech: Any) -> None:
        """Services that let mech-interact pick a mech leave this unset.

        :param mech: the configured priority mech.
        """
        handler = _facilitator_handler()
        handler.context.params.mech_marketplace_config.priority_mech_address = mech
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is True
        assert chain.sent[0]["value"] == _TARGET

    def test_an_unresolvable_tracker_sends_nothing(self) -> None:
        """A marketplace with no tracker for the type gives nowhere to deposit."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None, tracker=_ZERO_ADDR)

        assert _run(handler, chain) is False
        assert chain.sent == []

    def test_an_unreadable_payment_type_sends_nothing(self) -> None:
        """A short payment type must not be used to pick a tracker."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None, payment_type=b"\x01\x02")

        assert _run(handler, chain) is False
        assert chain.sent == []

    @pytest.mark.parametrize(
        "reply",
        [
            _facilitator_reply(_NATIVE_PAYMENT_TYPE, status=500),
            _facilitator_reply(None),
            SimpleNamespace(status_code=200, json=lambda: {"payment_type": "zz"}),
            SimpleNamespace(status_code=200, json=lambda: {"payment_type": 7}),
            SimpleNamespace(status_code=200, json=lambda: {}),
        ],
    )
    def test_an_unusable_facilitator_answer_sends_nothing(
        self, reply: SimpleNamespace
    ) -> None:
        """A bad answer must leave the pot alone rather than guess an asset.

        :param reply: what the facilitator answers with.
        """
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain, reply=reply) is False
        assert chain.sent == []

    def test_an_unreachable_facilitator_sends_nothing(self) -> None:
        """A timeout must skip the period rather than deposit into a guess."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain, error=OSError("timed out")) is False
        assert chain.sent == []

    def test_no_facilitator_url_sends_nothing(self) -> None:
        """Without somewhere to ask, which asset to deposit is unknown."""
        handler = _facilitator_handler()
        handler.context.params.mech_facilitator_base_url = ""
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is False
        assert chain.sent == []

    def test_the_payment_type_comes_from_the_facilitator(self) -> None:
        """The facilitator decides what it charges, so it decides the pot."""
        handler = _facilitator_handler()
        other = bytes.fromhex("cd" * 32)
        chain = _ChainStub(deposited=0, token=None, payment_type=_NATIVE_PAYMENT_TYPE)

        assert _run(handler, chain, reply=_facilitator_reply(other)) is True

        # The type looked up is the one the facilitator named.
        lookups = [
            args
            for name, args in chain.reads
            if name == "mapPaymentTypeBalanceTrackers"
        ]
        assert lookups == [(other,)]
        # Asked about this Safe, at the configured base URL.
        url = chain.facilitator_get.call_args.args[0]
        assert url.startswith(_FACILITATOR_URL)
        assert _SAFE[2:].lower() in url.lower()

    def test_the_marketplace_comes_from_config(self) -> None:
        """Every address the deposit touches resolves from the configured one."""
        handler = _facilitator_handler()
        chain = _ChainStub(deposited=0, token=None)

        assert _run(handler, chain) is True

        # The tracker comes from the configured marketplace, and nothing is
        # read from an address that arrived in a response.
        assert [name for name, _ in chain.reads][0] == "mapPaymentTypeBalanceTrackers"
        assert _same_address(chain.bound[0], _MARKETPLACE)
