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

"""Tests for HttpHandler._process_updated_agent_config in chatui_abci/handlers.py."""

from typing import Optional
from unittest.mock import MagicMock

from packages.valory.skills.chatui_abci.handlers import (
    ALLOWED_TOOLS_FIELD,
    AVAILABLE_TRADING_STRATEGIES,
    HttpHandler,
)
from packages.valory.skills.chatui_abci.models import ChatuiConfig
from packages.valory.skills.chatui_abci.prompts import FieldsThatCanBeRemoved

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
        assert handler.shared_state.chatui_config.fixed_bet_size is None  # type: ignore[attr-defined]

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
        assert handler.shared_state.chatui_config.max_bet_size is None  # type: ignore[attr-defined]

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
