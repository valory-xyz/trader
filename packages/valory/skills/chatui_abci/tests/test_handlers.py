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

"""Tests for chatui_abci/handlers.py."""

import json
from typing import Optional
from unittest.mock import MagicMock, patch

from packages.valory.skills.chatui_abci.handlers import (
    ALLOWED_TOOLS_FIELD,
    AVAILABLE_TRADING_STRATEGIES,
    GENAI_API_KEY_NOT_SET_ERROR,
    GENAI_RATE_LIMIT_ERROR,
    HTTP_CONTENT_TYPE_MAP,
    HttpHandler,
    LLM_MESSAGE_FIELD,
    PREVIOUS_TRADING_TYPE_FIELD,
    SrrHandler,
    TRADING_TYPE_FIELD,
    UPDATED_PARAMS_FIELD,
)
from packages.valory.skills.chatui_abci.models import ChatuiConfig, TradingStrategyUI
from packages.valory.skills.chatui_abci.prompts import (
    FieldsThatCanBeRemoved,
    TradingStrategy,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECIMALS = 18
ABS_MIN = 10_000_000_000_000_000  # 0.01 wxDAI in base units
ABS_MAX = 2_000_000_000_000_000_000  # 2 wxDAI in base units
AVAILABLE_TOOLS = {"prediction-online", "prediction-offline", "claude-prediction"}


# ---------------------------------------------------------------------------
# Testable subclass
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
    available_tools: set = AVAILABLE_TOOLS,
    current_config: Optional[ChatuiConfig] = None,
) -> _TestableHttpHandler:
    """Return a _TestableHttpHandler wired with minimal mocks."""
    handler = object.__new__(_TestableHttpHandler)

    context = MagicMock()
    context.params.is_running_on_polymarket = False  # wxDAI / 18 decimals
    context.params.strategies_kwargs = {
        "absolute_min_bet_size": ABS_MIN,
        "absolute_max_bet_size": ABS_MAX,
    }
    handler.context = context  # type: ignore[assignment]

    shared_state = MagicMock()
    shared_state.chatui_config = current_config or ChatuiConfig()
    handler.shared_state = shared_state  # type: ignore[assignment]

    sync_data = MagicMock()
    sync_data.available_mech_tools = available_tools
    handler.synchronized_data = sync_data  # type: ignore[assignment]

    # Patch store helpers — no filesystem side-effects.
    handler._store_trading_strategy = MagicMock()  # type: ignore[method-assign]
    handler._store_allowed_tools = MagicMock()  # type: ignore[method-assign]
    handler._store_chatui_param_to_json = MagicMock()  # type: ignore[method-assign]

    return handler


# ---------------------------------------------------------------------------
# Trading strategy
# ---------------------------------------------------------------------------


class TestTradingStrategy:
    """Tests for trading strategy field processing."""

    def test_valid_strategy_stored(self) -> None:
        """Valid strategy must be stored and returned in params."""
        handler = _make_handler()
        strategy = next(iter(AVAILABLE_TRADING_STRATEGIES))
        params, issues = handler._process_updated_agent_config(
            {"trading_strategy": strategy}
        )
        assert issues == []
        assert params["trading_strategy"] == strategy
        handler._store_trading_strategy.assert_called_once_with(strategy)  # type: ignore[attr-defined]

    def test_invalid_strategy_adds_issue(self) -> None:
        """An unknown strategy must add an issue and not store anything."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"trading_strategy": "bogus-strategy"}
        )
        assert len(issues) == 1
        assert "Unsupported trading strategy" in issues[0]
        handler._store_trading_strategy.assert_not_called()  # type: ignore[attr-defined]
        assert "trading_strategy" not in params

    def test_absent_field_is_noop(self) -> None:
        """Missing trading_strategy field must be a no-op."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({})
        assert issues == []
        assert "trading_strategy" not in params
        handler._store_trading_strategy.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Allowed tools
# ---------------------------------------------------------------------------


class TestAllowedTools:
    """Tests for allowed_tools field processing."""

    def test_valid_list_stored(self) -> None:
        """A fully valid list must be stored as-is."""
        handler = _make_handler()
        tools = ["prediction-online", "prediction-offline"]
        params, issues = handler._process_updated_agent_config({"allowed_tools": tools})
        assert issues == []
        assert params[ALLOWED_TOOLS_FIELD] == tools
        handler._store_allowed_tools.assert_called_once_with(tools)  # type: ignore[attr-defined]

    def test_unknown_tools_dropped_and_issue_added(self) -> None:
        """Unknown tools must be dropped and a single issue added."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["prediction-online", "made-up-tool"]}
        )
        assert len(issues) == 1
        assert "made-up-tool" in issues[0]
        handler._store_allowed_tools.assert_called_once_with(["prediction-online"])  # type: ignore[attr-defined]
        assert params[ALLOWED_TOOLS_FIELD] == ["prediction-online"]

    def test_all_unknown_adds_issue_no_store(self) -> None:
        """All-unknown tools must add one issue and not store anything."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["fake-a", "fake-b"]}
        )
        assert len(issues) == 1
        handler._store_allowed_tools.assert_not_called()  # type: ignore[attr-defined]
        assert ALLOWED_TOOLS_FIELD not in params

    def test_empty_list_treated_as_clear(self) -> None:
        """An empty list must be treated as clearing allowed_tools to None."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({"allowed_tools": []})
        assert issues == []
        assert params[ALLOWED_TOOLS_FIELD] is None
        handler._store_allowed_tools.assert_called_once_with(None)  # type: ignore[attr-defined]

    def test_remove_clears_tools(self) -> None:
        """Remove field must clear allowed_tools to None."""
        handler = _make_handler(
            current_config=ChatuiConfig(allowed_tools=["prediction-online"])
        )
        params, issues = handler._process_updated_agent_config(
            {"removed_config_fields": [FieldsThatCanBeRemoved.ALLOWED_TOOLS.value]}
        )
        assert issues == []
        assert params[ALLOWED_TOOLS_FIELD] is None
        handler._store_allowed_tools.assert_called_once_with(None)  # type: ignore[attr-defined]

    def test_remove_takes_precedence_over_set(self) -> None:
        """Remove must take precedence when both allowed_tools and remove are present."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {
                "allowed_tools": ["prediction-online"],
                "removed_config_fields": [FieldsThatCanBeRemoved.ALLOWED_TOOLS.value],
            }
        )
        assert params[ALLOWED_TOOLS_FIELD] is None
        handler._store_allowed_tools.assert_called_once_with(None)  # type: ignore[attr-defined]

    def test_absent_field_is_noop(self) -> None:
        """Missing allowed_tools field must be a no-op."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({})
        assert ALLOWED_TOOLS_FIELD not in params
        handler._store_allowed_tools.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Fixed bet size
# ---------------------------------------------------------------------------


class TestFixedBetSize:
    """Tests for fixed_bet_size field processing."""

    _VALID = 0.05  # → 50_000_000_000_000_000 base units (within bounds)

    def test_valid_size_stored(self) -> None:
        """Valid fixed_bet_size must be stored and converted to base units."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"fixed_bet_size": self._VALID}
        )
        assert issues == []
        assert params["fixed_bet_size"] == self._VALID
        expected = int(self._VALID * 10**DECIMALS)
        handler._store_chatui_param_to_json.assert_any_call("fixed_bet_size", expected)  # type: ignore[attr-defined]

    def test_too_low_adds_issue(self) -> None:
        """A fixed_bet_size below the minimum must add an issue."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({"fixed_bet_size": 0.0})
        assert len(issues) == 1
        assert "out of bounds" in issues[0]
        assert "fixed_bet_size" not in params

    def test_too_high_adds_issue(self) -> None:
        """A fixed_bet_size above the maximum must add an issue."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({"fixed_bet_size": 999})
        assert len(issues) == 1
        assert "out of bounds" in issues[0]
        assert "fixed_bet_size" not in params

    def test_remove_clears_size(self) -> None:
        """Remove field must clear fixed_bet_size to None."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"removed_config_fields": [FieldsThatCanBeRemoved.FIXED_BET_SIZE.value]}
        )
        assert issues == []
        assert params["fixed_bet_size"] is None
        handler._store_chatui_param_to_json.assert_any_call("fixed_bet_size", None)  # type: ignore[attr-defined]
        assert handler.shared_state.chatui_config.fixed_bet_size is None  # type: ignore[attr-defined, union-attr]

    def test_absent_field_is_noop(self) -> None:
        """Missing fixed_bet_size field must be a no-op."""
        handler = _make_handler()
        params, _ = handler._process_updated_agent_config({})
        assert "fixed_bet_size" not in params


# ---------------------------------------------------------------------------
# Max bet size
# ---------------------------------------------------------------------------


class TestMaxBetSize:
    """Tests for max_bet_size field processing."""

    _VALID = 1.0  # → 1_000_000_000_000_000_000 base units (within bounds)

    def test_valid_size_stored(self) -> None:
        """Valid max_bet_size must be stored and converted to base units."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"max_bet_size": self._VALID}
        )
        assert issues == []
        assert params["max_bet_size"] == self._VALID
        expected = int(self._VALID * 10**DECIMALS)
        handler._store_chatui_param_to_json.assert_any_call("max_bet_size", expected)  # type: ignore[attr-defined]

    def test_too_high_adds_issue(self) -> None:
        """A max_bet_size above the cap must add an issue."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({"max_bet_size": 999})
        assert len(issues) == 1
        assert "out of bounds" in issues[0]
        assert "max_bet_size" not in params

    def test_remove_clears_size(self) -> None:
        """Remove field must clear max_bet_size to None."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"removed_config_fields": [FieldsThatCanBeRemoved.MAX_BET_SIZE.value]}
        )
        assert issues == []
        assert params["max_bet_size"] is None
        handler._store_chatui_param_to_json.assert_any_call("max_bet_size", None)  # type: ignore[attr-defined]
        assert handler.shared_state.chatui_config.max_bet_size is None  # type: ignore[attr-defined, union-attr]

    def test_absent_field_is_noop(self) -> None:
        """Missing max_bet_size field must be a no-op."""
        handler = _make_handler()
        params, _ = handler._process_updated_agent_config({})
        assert "max_bet_size" not in params


# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------


class TestBehavior:
    """Tests for the behavior field processing."""

    def test_behavior_forwarded_to_shared_state(self) -> None:
        """Behavior string must be forwarded to shared_state.update_agent_behavior."""
        handler = _make_handler()
        handler._process_updated_agent_config(
            {"behavior": "A conservative fixed-size trade strategy."}
        )
        handler.shared_state.update_agent_behavior.assert_called_once_with(  # type: ignore[attr-defined]
            "A conservative fixed-size trade strategy."
        )

    def test_absent_behavior_no_call(self) -> None:
        """Missing behavior field must not trigger update_agent_behavior."""
        handler = _make_handler()
        handler._process_updated_agent_config({})
        handler.shared_state.update_agent_behavior.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Return value / combined
# ---------------------------------------------------------------------------


class TestReturnValue:
    """Tests for the combined return value of _process_updated_agent_config."""

    def test_empty_config_returns_empty(self) -> None:
        """Empty input must return empty params and no issues."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config({})
        assert params == {}
        assert issues == []

    def test_multiple_valid_fields_all_present(self) -> None:
        """Multiple valid fields must all appear in returned params."""
        handler = _make_handler()
        strategy = next(iter(AVAILABLE_TRADING_STRATEGIES))
        params, issues = handler._process_updated_agent_config(
            {
                "trading_strategy": strategy,
                "allowed_tools": ["prediction-online"],
                "fixed_bet_size": 0.05,
            }
        )
        assert issues == []
        assert "trading_strategy" in params
        assert ALLOWED_TOOLS_FIELD in params
        assert "fixed_bet_size" in params

    def test_multiple_invalid_fields_accumulate_issues(self) -> None:
        """Each invalid field must contribute its own issue."""
        handler = _make_handler()
        _, issues = handler._process_updated_agent_config(
            {
                "trading_strategy": "bogus",
                "allowed_tools": ["nonexistent"],
                "fixed_bet_size": 999,
            }
        )
        assert len(issues) == 3

    def test_partial_unknown_tools_single_issue(self) -> None:
        """Partial unknown tools must produce exactly one issue."""
        handler = _make_handler()
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["prediction-online", "fake-tool"]}
        )
        assert len(issues) == 1
        assert params[ALLOWED_TOOLS_FIELD] == ["prediction-online"]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_http_content_type_map_contains_expected_extensions(self) -> None:
        """HTTP_CONTENT_TYPE_MAP must include common web extensions."""
        expected_keys = {".js", ".html", ".json", ".css", ".png", ".jpg", ".jpeg"}
        assert set(HTTP_CONTENT_TYPE_MAP.keys()) == expected_keys

    def test_available_trading_strategies_is_frozen(self) -> None:
        """AVAILABLE_TRADING_STRATEGIES must be a frozenset."""
        assert isinstance(AVAILABLE_TRADING_STRATEGIES, frozenset)

    def test_available_trading_strategies_contains_all_enum_values(self) -> None:
        """Every TradingStrategy enum value must be in the frozenset."""
        for strategy in TradingStrategy:
            assert strategy.value in AVAILABLE_TRADING_STRATEGIES


class TestHttpHandlerSetup:
    """Tests for HttpHandler.setup()."""

    def test_setup_adds_chatui_routes(self) -> None:
        """setup() must add chatui-prompt, configure_strategies, and features routes."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        handler.context.params.service_endpoint = "http://localhost:8000"
        handler.routes = {}

        # Patch the parent setup() and the hostname_regex property
        with patch.object(
            HttpHandler.__bases__[0], "setup", return_value=None
        ), patch.object(
            type(handler),
            "hostname_regex",
            new_callable=lambda: property(lambda self: r".*localhost(:\d+)?"),
        ):
            handler.setup()

        # Verify GET routes contain features handler
        get_routes = handler.routes.get(("get",), [])
        get_handler_funcs = [fn for _, fn in get_routes]
        assert handler._handle_get_features in get_handler_funcs

        # Verify HEAD routes contain features handler
        head_routes = handler.routes.get(("head",), [])
        head_handler_funcs = [fn for _, fn in head_routes]
        assert handler._handle_get_features in head_handler_funcs

        # Verify POST routes contain chatui prompt handlers
        post_routes = handler.routes.get(("post",), [])
        post_handler_funcs = [fn for _, fn in post_routes]
        assert handler._handle_chatui_prompt in post_handler_funcs
        # Both chatui-prompt and configure_strategies map to _handle_chatui_prompt
        assert post_handler_funcs.count(handler._handle_chatui_prompt) == 2


class TestHandleGetFeatures:
    """Tests for HttpHandler._handle_get_features()."""

    @staticmethod
    def _make_features_handler(
        use_x402: bool = False,
        genai_api_key: Optional[str] = None,
    ) -> _TestableHttpHandler:
        """Create a handler wired for features tests."""
        handler = _make_handler()
        handler.context.params.use_x402 = use_x402  # type: ignore[attr-defined]
        handler.context.params.genai_api_key = genai_api_key  # type: ignore[attr-defined]
        handler._send_ok_response = MagicMock()  # type: ignore[assignment]
        return handler

    def test_x402_enabled_chat_is_enabled(self) -> None:
        """When use_x402 is True, isChatEnabled must be True regardless of api_key."""
        handler = self._make_features_handler(use_x402=True, genai_api_key=None)
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": True}
        )

    def test_valid_api_key_chat_is_enabled(self) -> None:
        """A non-empty, non-placeholder api key must enable chat."""
        handler = self._make_features_handler(
            use_x402=False, genai_api_key="real-api-key"
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": True}
        )

    def test_none_api_key_chat_is_disabled(self) -> None:
        """None api_key must disable chat."""
        handler = self._make_features_handler(use_x402=False, genai_api_key=None)
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": False}
        )

    def test_empty_api_key_chat_is_disabled(self) -> None:
        """Empty string api_key must disable chat."""
        handler = self._make_features_handler(use_x402=False, genai_api_key="")
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": False}
        )

    def test_whitespace_api_key_chat_is_disabled(self) -> None:
        """Whitespace-only api_key must disable chat."""
        handler = self._make_features_handler(use_x402=False, genai_api_key="   ")
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": False}
        )

    def test_placeholder_str_api_key_chat_is_disabled(self) -> None:
        """Placeholder '${str:}' api_key must disable chat."""
        handler = self._make_features_handler(use_x402=False, genai_api_key="${str:}")
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": False}
        )

    def test_double_quoted_empty_api_key_chat_is_disabled(self) -> None:
        r"""Double-quoted empty string '\"\"' api_key must disable chat."""
        handler = self._make_features_handler(use_x402=False, genai_api_key='""')
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": False}
        )

    def test_use_x402_attribute_missing_defaults_false(self) -> None:
        """When use_x402 is not present on params at all, getattr fallback must be False."""
        handler = _make_handler()
        # Remove the use_x402 attribute so getattr falls back
        del handler.context.params.use_x402  # type: ignore[attr-defined]
        handler.context.params.genai_api_key = "valid-key"  # type: ignore[attr-defined]
        handler._send_ok_response = MagicMock()  # type: ignore[assignment]
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_get_features(http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once_with(  # type: ignore[attr-defined]
            http_msg, http_dialogue, {"isChatEnabled": True}
        )


# ---------------------------------------------------------------------------
# shared_state / round_sequence / synchronized_data properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests for the shared_state, round_sequence, and synchronized_data properties."""

    def test_shared_state_returns_context_state(self) -> None:
        """shared_state property must cast and return context.state."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        sentinel = MagicMock()
        handler.context.state = sentinel
        # Access the property from HttpHandler (not _TestableHttpHandler which shadows it)
        result = HttpHandler.shared_state.fget(handler)  # type: ignore[attr-defined, union-attr]
        assert result is sentinel

    def test_round_sequence_returns_shared_state_round_sequence(self) -> None:
        """round_sequence property must return shared_state.round_sequence."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        rs_sentinel = MagicMock()
        # shared_state property calls self.context.state, set it up
        handler.context.state.round_sequence = rs_sentinel
        # Wire shared_state so that round_sequence can chain through it
        handler.shared_state = handler.context.state  # type: ignore[misc]
        result = HttpHandler.round_sequence.fget(handler)  # type: ignore[union-attr]
        assert result is rs_sentinel

    def test_synchronized_data_returns_synced_data(self) -> None:
        """synchronized_data property must return a SynchronizedData from the DB."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        db_mock = MagicMock()
        handler.context.state.round_sequence.latest_synchronized_data.db = db_mock
        # Wire shared_state so that round_sequence and then synchronized_data can chain
        handler.shared_state = handler.context.state  # type: ignore[misc]
        result = HttpHandler.synchronized_data.fget(handler)  # type: ignore[attr-defined, union-attr]
        assert result.db is db_mock


class TestGetUiTradingStrategy:
    """Tests for _get_ui_trading_strategy()."""

    def test_none_returns_balanced(self) -> None:
        """None input must return BALANCED."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy(None)
        assert result == TradingStrategyUI.BALANCED

    def test_bet_amount_per_threshold_returns_balanced(self) -> None:
        """BET_AMOUNT_PER_THRESHOLD must map to BALANCED."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy(
            TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value
        )
        assert result == TradingStrategyUI.BALANCED

    def test_kelly_criterion_no_conf_returns_risky(self) -> None:
        """KELLY_CRITERION_NO_CONF must map to RISKY."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy(
            TradingStrategy.KELLY_CRITERION_NO_CONF.value
        )
        assert result == TradingStrategyUI.RISKY

    def test_unknown_strategy_returns_risky(self) -> None:
        """Any unknown strategy string must default to RISKY."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy("some_unknown_strategy")
        assert result == TradingStrategyUI.RISKY


class TestGetAvailableTools:
    """Tests for _get_available_tools()."""

    def test_returns_tools_on_success(self) -> None:
        """When synchronized_data is accessible, return available_mech_tools."""
        handler = _make_handler()
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        result = handler._get_available_tools(http_msg, http_dialogue)
        assert result == AVAILABLE_TOOLS

    def test_returns_none_and_sends_too_early_on_type_error(self) -> None:
        """When synchronized_data raises TypeError, return None and send 425."""
        handler = _make_handler()
        # Make accessing available_mech_tools raise TypeError
        type(handler.synchronized_data).available_mech_tools = property(  # type: ignore[attr-defined]
            lambda self: (_ for _ in ()).throw(TypeError("not ready"))
        )
        handler._send_too_early_request_response = MagicMock()  # type: ignore[assignment]
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        result = handler._get_available_tools(http_msg, http_dialogue)
        assert result is None
        handler._send_too_early_request_response.assert_called_once()  # type: ignore[attr-defined]


class TestHandleChatuiPrompt:
    """Tests for _handle_chatui_prompt()."""

    @staticmethod
    def _make_prompt_handler(
        prompt: str = "make me risky",
        current_config: Optional[ChatuiConfig] = None,
    ) -> _TestableHttpHandler:
        """Create a handler for prompt tests with body set."""
        handler = _make_handler(current_config=current_config)
        handler._send_bad_request_response = MagicMock()  # type: ignore[assignment]
        handler._send_chatui_llm_request = MagicMock()  # type: ignore[assignment]
        handler._get_available_tools = MagicMock(return_value=AVAILABLE_TOOLS)  # type: ignore[assignment]
        return handler

    @staticmethod
    def _make_http_msg(body_dict: dict) -> MagicMock:
        """Create a mock HttpMessage with body."""
        msg = MagicMock()
        msg.body = json.dumps(body_dict).encode("utf-8")
        return msg

    def test_empty_prompt_sends_bad_request(self) -> None:
        """An empty prompt must send a bad request response."""
        handler = self._make_prompt_handler()
        http_msg = self._make_http_msg({"prompt": ""})
        http_dialogue = MagicMock()
        handler._handle_chatui_prompt(http_msg, http_dialogue)
        handler._send_bad_request_response.assert_called_once()  # type: ignore[attr-defined]
        handler._send_chatui_llm_request.assert_not_called()  # type: ignore[attr-defined]

    def test_missing_prompt_key_sends_bad_request(self) -> None:
        """A body without the 'prompt' key must send a bad request response."""
        handler = self._make_prompt_handler()
        http_msg = self._make_http_msg({})
        http_dialogue = MagicMock()
        handler._handle_chatui_prompt(http_msg, http_dialogue)
        handler._send_bad_request_response.assert_called_once()  # type: ignore[attr-defined]

    def test_available_tools_none_returns_early(self) -> None:
        """When _get_available_tools returns None, prompt handling must return."""
        handler = self._make_prompt_handler()
        handler._get_available_tools = MagicMock(return_value=None)  # type: ignore[assignment]
        http_msg = self._make_http_msg({"prompt": "test"})
        http_dialogue = MagicMock()
        handler._handle_chatui_prompt(http_msg, http_dialogue)
        handler._send_chatui_llm_request.assert_not_called()  # type: ignore[attr-defined]
        handler._send_bad_request_response.assert_not_called()  # type: ignore[attr-defined]

    def test_valid_prompt_calls_send_chatui_llm_request(self) -> None:
        """A valid prompt must result in _send_chatui_llm_request being called."""
        handler = self._make_prompt_handler()
        http_msg = self._make_http_msg({"prompt": "make me risky"})
        http_dialogue = MagicMock()
        handler._handle_chatui_prompt(http_msg, http_dialogue)
        handler._send_chatui_llm_request.assert_called_once()  # type: ignore[attr-defined]
        call_kwargs = handler._send_chatui_llm_request.call_args  # type: ignore[attr-defined]
        assert "make me risky" in call_kwargs.kwargs.get(
            "prompt", call_kwargs[1].get("prompt", "")
        ) or "make me risky" in str(call_kwargs)

    def test_prompt_includes_current_config_values(self) -> None:
        """The formatted prompt must include current config values."""
        config = ChatuiConfig(
            trading_strategy="kelly_criterion_no_conf",
            allowed_tools=["prediction-online"],
            fixed_bet_size=50_000_000_000_000_000,
            max_bet_size=1_000_000_000_000_000_000,
        )
        handler = self._make_prompt_handler(current_config=config)
        http_msg = self._make_http_msg({"prompt": "status"})
        http_dialogue = MagicMock()
        handler._handle_chatui_prompt(http_msg, http_dialogue)
        prompt_arg = handler._send_chatui_llm_request.call_args  # type: ignore[attr-defined]
        prompt_str = str(prompt_arg)
        assert "kelly_criterion_no_conf" in prompt_str
        assert "prediction-online" in prompt_str


class TestSendChatuiLlmRequest:
    """Tests for _send_chatui_llm_request()."""

    def test_sends_srr_message_and_registers_callback(self) -> None:
        """Must create SrrMessage, put it in outbox, and register callback."""
        handler = _make_handler()
        mock_srr_dialogues = MagicMock()
        mock_request_msg = MagicMock()
        mock_srr_dialogue = MagicMock()
        mock_srr_dialogues.create.return_value = (
            mock_request_msg,
            mock_srr_dialogue,
        )
        handler.context.srr_dialogues = mock_srr_dialogues  # type: ignore[attr-defined]
        handler._send_message = MagicMock()  # type: ignore[assignment]

        http_msg = MagicMock()
        http_dialogue = MagicMock()

        handler._send_chatui_llm_request(
            prompt="test prompt",
            http_msg=http_msg,
            http_dialogue=http_dialogue,
        )

        mock_srr_dialogues.create.assert_called_once()
        handler._send_message.assert_called_once()  # type: ignore[attr-defined]
        call_args = handler._send_message.call_args  # type: ignore[attr-defined]
        assert call_args[0][0] is mock_request_msg
        assert call_args[0][1] is mock_srr_dialogue
        # The callback must be _handle_chatui_llm_response
        assert call_args[0][2] == handler._handle_chatui_llm_response
        # callback_kwargs must contain http_msg and http_dialogue
        callback_kwargs = call_args[0][3]
        assert callback_kwargs["http_msg"] is http_msg
        assert callback_kwargs["http_dialogue"] is http_dialogue

    def test_payload_contains_prompt_and_schema(self) -> None:
        """Payload sent via SRR must contain 'prompt' and 'schema'."""
        handler = _make_handler()
        mock_srr_dialogues = MagicMock()
        mock_srr_dialogues.create.return_value = (MagicMock(), MagicMock())
        handler.context.srr_dialogues = mock_srr_dialogues  # type: ignore[attr-defined]
        handler._send_message = MagicMock()  # type: ignore[assignment]

        handler._send_chatui_llm_request(
            prompt="hello", http_msg=MagicMock(), http_dialogue=MagicMock()
        )

        create_kwargs = mock_srr_dialogues.create.call_args
        payload_str = create_kwargs.kwargs.get(
            "payload", create_kwargs[1].get("payload", "")
        )
        payload = json.loads(payload_str)
        assert "prompt" in payload
        assert payload["prompt"] == "hello"
        assert "schema" in payload


class TestHandleChatuiLlmResponse:
    """Tests for _handle_chatui_llm_response()."""

    @staticmethod
    def _make_response_handler(
        trading_strategy: Optional[str] = None,
    ) -> _TestableHttpHandler:
        """Create a handler for response tests."""
        config = ChatuiConfig(trading_strategy=trading_strategy)
        handler = _make_handler(current_config=config)
        handler._send_ok_response = MagicMock()  # type: ignore[assignment]
        handler._handle_chatui_llm_error = MagicMock()  # type: ignore[assignment]
        return handler

    @staticmethod
    def _make_srr_msg(payload: dict) -> MagicMock:
        """Create a mock SrrMessage with payload."""
        msg = MagicMock()
        msg.payload = json.dumps(payload)
        return msg

    def test_error_in_response_delegates_to_error_handler(self) -> None:
        """When genai_response has 'error', must call _handle_chatui_llm_error."""
        handler = self._make_response_handler()
        srr_msg = self._make_srr_msg({"error": "something went wrong"})
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        handler._handle_chatui_llm_error.assert_called_once_with(  # type: ignore[attr-defined]
            "something went wrong", http_msg, http_dialogue
        )
        handler._send_ok_response.assert_not_called()  # type: ignore[attr-defined]

    def test_empty_updated_config_sends_ok_with_empty_params(self) -> None:
        """No updated_agent_config must send OK with empty updated_params."""
        handler = self._make_response_handler()
        srr_msg = self._make_srr_msg(
            {
                "response": json.dumps(
                    {"message": "No changes.", "updated_agent_config": {}}
                )
            }
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once()  # type: ignore[attr-defined]
        response_data = handler._send_ok_response.call_args[0][2]  # type: ignore[attr-defined]
        assert response_data[UPDATED_PARAMS_FIELD] == {}
        assert response_data[LLM_MESSAGE_FIELD] == "No changes."

    def test_missing_response_field_uses_empty_braces(self) -> None:
        """When 'response' key is absent, must default to '{}'."""
        handler = self._make_response_handler()
        srr_msg = self._make_srr_msg({})
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        # No error, empty config => sends OK with empty params
        handler._send_ok_response.assert_called_once()  # type: ignore[attr-defined]

    def test_valid_config_update_sends_ok_with_trading_type(self) -> None:
        """A valid config update must include TRADING_TYPE_FIELD in response."""
        handler = self._make_response_handler(
            trading_strategy=TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value,
        )
        strategy = TradingStrategy.KELLY_CRITERION_NO_CONF.value
        srr_msg = self._make_srr_msg(
            {
                "response": json.dumps(
                    {
                        "message": "Switched to risky.",
                        "updated_agent_config": {"trading_strategy": strategy},
                    }
                )
            }
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        handler._send_ok_response.assert_called_once()  # type: ignore[attr-defined]
        response_data = handler._send_ok_response.call_args[0][2]  # type: ignore[attr-defined]
        assert TRADING_TYPE_FIELD in response_data

    def test_strategy_change_includes_previous_trading_type(self) -> None:
        """Changing strategy must include PREVIOUS_TRADING_TYPE_FIELD in response."""
        handler = self._make_response_handler(
            trading_strategy=TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value,
        )
        strategy = TradingStrategy.KELLY_CRITERION_NO_CONF.value
        srr_msg = self._make_srr_msg(
            {
                "response": json.dumps(
                    {
                        "message": "Switched.",
                        "updated_agent_config": {"trading_strategy": strategy},
                    }
                )
            }
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        response_data = handler._send_ok_response.call_args[0][2]  # type: ignore[attr-defined]
        assert PREVIOUS_TRADING_TYPE_FIELD in response_data
        assert (
            response_data[PREVIOUS_TRADING_TYPE_FIELD]
            == TradingStrategyUI.BALANCED.value
        )

    def test_same_strategy_no_previous_trading_type(self) -> None:
        """When strategy does not change, PREVIOUS_TRADING_TYPE_FIELD must not appear."""
        current_strategy = TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value
        handler = self._make_response_handler(
            trading_strategy=current_strategy,
        )
        srr_msg = self._make_srr_msg(
            {
                "response": json.dumps(
                    {
                        "message": "No strategy change.",
                        "updated_agent_config": {
                            "trading_strategy": current_strategy,
                        },
                    }
                )
            }
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        response_data = handler._send_ok_response.call_args[0][2]  # type: ignore[attr-defined]
        assert PREVIOUS_TRADING_TYPE_FIELD not in response_data

    def test_issues_replace_llm_message_in_reasoning(self) -> None:
        """When issues exist, reasoning must contain joined issues instead of llm_message."""
        handler = self._make_response_handler()
        srr_msg = self._make_srr_msg(
            {
                "response": json.dumps(
                    {
                        "message": "Good change.",
                        "updated_agent_config": {
                            "trading_strategy": "bogus",
                        },
                    }
                )
            }
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        dialogue = MagicMock()
        handler._handle_chatui_llm_response(srr_msg, dialogue, http_msg, http_dialogue)
        response_data = handler._send_ok_response.call_args[0][2]  # type: ignore[attr-defined]
        assert "Unsupported trading strategy" in response_data[LLM_MESSAGE_FIELD]


class TestHandleChatuiLlmError:
    """Tests for _handle_chatui_llm_error()."""

    @staticmethod
    def _make_error_handler() -> _TestableHttpHandler:
        """Create a handler for error tests."""
        handler = _make_handler()
        handler._send_internal_server_error_response = MagicMock()  # type: ignore[assignment]
        handler._send_too_many_requests_response = MagicMock()  # type: ignore[assignment]
        return handler

    def test_api_key_not_set_error(self) -> None:
        """GENAI_API_KEY_NOT_SET_ERROR must trigger internal server error."""
        handler = self._make_error_handler()
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_chatui_llm_error(
            GENAI_API_KEY_NOT_SET_ERROR, http_msg, http_dialogue
        )
        handler._send_internal_server_error_response.assert_called_once()  # type: ignore[attr-defined]
        call_data = handler._send_internal_server_error_response.call_args[0][2]  # type: ignore[attr-defined]
        assert "No GENAI_API_KEY set." in call_data["error"]
        handler._send_too_many_requests_response.assert_not_called()  # type: ignore[attr-defined]

    def test_rate_limit_error(self) -> None:
        """GENAI_RATE_LIMIT_ERROR must trigger too many requests response."""
        handler = self._make_error_handler()
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_chatui_llm_error(
            f"Error {GENAI_RATE_LIMIT_ERROR} too many", http_msg, http_dialogue
        )
        handler._send_too_many_requests_response.assert_called_once()  # type: ignore[attr-defined]
        call_data = handler._send_too_many_requests_response.call_args[0][2]  # type: ignore[attr-defined]
        assert "Too many requests" in call_data["error"]

    def test_generic_error(self) -> None:
        """A generic error must trigger internal server error with generic message."""
        handler = self._make_error_handler()
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_chatui_llm_error(
            "something unexpected", http_msg, http_dialogue
        )
        handler._send_internal_server_error_response.assert_called_once()  # type: ignore[attr-defined]
        call_data = handler._send_internal_server_error_response.call_args[0][2]  # type: ignore[attr-defined]
        assert "An error occurred" in call_data["error"]

    def test_api_key_error_returns_before_rate_limit_check(self) -> None:
        """When error contains both API key and rate limit text, API key check wins."""
        handler = self._make_error_handler()
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        handler._handle_chatui_llm_error(
            f"{GENAI_API_KEY_NOT_SET_ERROR} {GENAI_RATE_LIMIT_ERROR}",
            http_msg,
            http_dialogue,
        )
        handler._send_internal_server_error_response.assert_called_once()  # type: ignore[attr-defined]
        handler._send_too_many_requests_response.assert_not_called()  # type: ignore[attr-defined]


class TestStoreChatuiParamToJson:
    """Tests for _store_chatui_param_to_json()."""

    def test_updates_json_store(self) -> None:
        """Must get current store, update it, and set it back."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        shared_state_mock = MagicMock()
        current_store = {"existing_key": "existing_value"}
        shared_state_mock._get_current_json_store.return_value = current_store
        handler.shared_state = shared_state_mock  # type: ignore[misc]

        # Call the real (un-mocked) method
        HttpHandler._store_chatui_param_to_json(handler, "new_param", 42)

        shared_state_mock._get_current_json_store.assert_called_once()
        shared_state_mock._set_json_store.assert_called_once()
        stored = shared_state_mock._set_json_store.call_args[0][0]
        assert stored["existing_key"] == "existing_value"
        assert stored["new_param"] == 42


class TestStoreTradingStrategy:
    """Tests for _store_trading_strategy()."""

    def test_stores_strategy_and_calls_json_store(self) -> None:
        """Must update chatui_config and call _store_chatui_param_to_json."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        shared_state_mock = MagicMock()
        shared_state_mock.chatui_config = ChatuiConfig()
        handler.shared_state = shared_state_mock  # type: ignore[misc]
        handler._store_chatui_param_to_json = MagicMock()  # type: ignore[assignment]

        HttpHandler._store_trading_strategy(handler, "kelly_criterion_no_conf")

        assert (
            shared_state_mock.chatui_config.trading_strategy
            == "kelly_criterion_no_conf"
        )
        handler._store_chatui_param_to_json.assert_called_once_with(  # type: ignore[attr-defined]
            "trading_strategy", "kelly_criterion_no_conf"
        )


class TestStoreAllowedTools:
    """Tests for _store_allowed_tools()."""

    def test_stores_tools_and_calls_json_store(self) -> None:
        """Must update chatui_config and call _store_chatui_param_to_json."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        shared_state_mock = MagicMock()
        shared_state_mock.chatui_config = ChatuiConfig()
        handler.shared_state = shared_state_mock  # type: ignore[misc]
        handler._store_chatui_param_to_json = MagicMock()  # type: ignore[assignment]

        tools = ["prediction-online"]
        HttpHandler._store_allowed_tools(handler, tools)

        assert shared_state_mock.chatui_config.allowed_tools == tools
        handler._store_chatui_param_to_json.assert_called_once_with(  # type: ignore[attr-defined]
            "allowed_tools", tools
        )

    def test_stores_none_when_clearing(self) -> None:
        """Passing None must clear allowed_tools."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()
        shared_state_mock = MagicMock()
        shared_state_mock.chatui_config = ChatuiConfig(allowed_tools=["old"])
        handler.shared_state = shared_state_mock  # type: ignore[misc]
        handler._store_chatui_param_to_json = MagicMock()  # type: ignore[assignment]

        HttpHandler._store_allowed_tools(handler, None)

        assert shared_state_mock.chatui_config.allowed_tools is None
        handler._store_chatui_param_to_json.assert_called_once_with(  # type: ignore[attr-defined]
            "allowed_tools", None
        )


# ---------------------------------------------------------------------------
# SrrHandler
# ---------------------------------------------------------------------------


class _TestableSrrHandler(SrrHandler):
    """Shadows read-only AEA properties with plain attributes for testing."""

    context = None  # type: ignore[assignment]


class TestSrrHandler:
    """Tests for SrrHandler.handle()."""

    @staticmethod
    def _make_srr_handler() -> _TestableSrrHandler:
        """Create a testable SrrHandler."""
        handler = object.__new__(_TestableSrrHandler)
        handler.context = MagicMock()  # type: ignore[assignment]
        handler.context.state.req_to_callback = {}  # type: ignore[attr-defined]
        handler.context.srr_dialogues = MagicMock()  # type: ignore[attr-defined]
        return handler

    @staticmethod
    def _make_srr_message(
        performative: str = "RESPONSE",
        nonce: str = "abc123",
    ) -> MagicMock:
        """Create a mock SrrMessage."""
        from packages.valory.protocols.srr.message import SrrMessage

        msg = MagicMock(spec=SrrMessage)
        msg.performative = SrrMessage.Performative.RESPONSE
        msg.dialogue_reference = (nonce, "")
        return msg

    def test_unrecognized_performative_logs_warning(self) -> None:
        """An unrecognized performative must log a warning and return."""
        handler = self._make_srr_handler()
        msg = MagicMock()
        msg.performative = "INVALID_PERFORMATIVE"
        msg.dialogue_reference = ("nonce", "")

        handler.handle(msg)

        handler.context.logger.warning.assert_called_once()  # type: ignore[attr-defined]

    def test_no_callback_delegates_to_super(self) -> None:
        """When no callback is registered for the nonce, must call super().handle()."""
        handler = self._make_srr_handler()
        msg = self._make_srr_message(nonce="unknown-nonce")
        # req_to_callback is empty, so pop returns (None, {})
        with patch.object(
            SrrHandler.__bases__[0], "handle", return_value=None
        ) as mock_super:
            handler.handle(msg)
            mock_super.assert_called_once_with(msg)

    def test_callback_invoked_with_kwargs(self) -> None:
        """When callback is registered, must invoke it with srr_msg, dialogue, and kwargs."""
        handler = self._make_srr_handler()
        nonce = "test-nonce-123"
        msg = self._make_srr_message(nonce=nonce)

        callback = MagicMock()
        extra_kwargs = {"http_msg": MagicMock(), "http_dialogue": MagicMock()}
        handler.context.state.req_to_callback[nonce] = (callback, extra_kwargs)  # type: ignore[attr-defined]

        mock_dialogue = MagicMock()
        handler.context.srr_dialogues.update.return_value = mock_dialogue  # type: ignore[attr-defined]

        handler.handle(msg)

        handler.context.srr_dialogues.update.assert_called_once_with(msg)  # type: ignore[attr-defined]
        callback.assert_called_once_with(
            msg,
            mock_dialogue,
            http_msg=extra_kwargs["http_msg"],
            http_dialogue=extra_kwargs["http_dialogue"],
        )

    def test_callback_popped_from_registry(self) -> None:
        """After handling, the nonce must be removed from req_to_callback."""
        handler = self._make_srr_handler()
        nonce = "pop-nonce"
        msg = self._make_srr_message(nonce=nonce)
        handler.context.state.req_to_callback[nonce] = (MagicMock(), {})  # type: ignore[attr-defined]
        handler.context.srr_dialogues.update.return_value = MagicMock()  # type: ignore[attr-defined]

        handler.handle(msg)

        assert nonce not in handler.context.state.req_to_callback  # type: ignore[attr-defined]

    def test_allowed_response_performatives(self) -> None:
        """allowed_response_performatives must include REQUEST and RESPONSE."""
        from packages.valory.protocols.srr.message import SrrMessage

        assert (
            SrrMessage.Performative.REQUEST in SrrHandler.allowed_response_performatives
        )
        assert (
            SrrMessage.Performative.RESPONSE
            in SrrHandler.allowed_response_performatives
        )
