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
from dataclasses import asdict
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.agent_performance_summary_abci.activity_goal import (
    update_activity_goal,
)
from packages.valory.skills.agent_performance_summary_abci.handlers import HttpMethod
from packages.valory.skills.agent_performance_summary_abci.models import (
    AGENT_PERFORMANCE_SUMMARY_FILE,
    read_activity_goal,
)
from packages.valory.skills.chatui_abci.handlers import (
    ALLOWED_TOOLS_FIELD,
    AVAILABLE_TRADING_STRATEGIES,
    GENAI_API_KEY_NOT_SET_ERROR,
    GENAI_RATE_LIMIT_ERROR,
    HTTP_CONTENT_TYPE_MAP,
    HttpHandler,
    LLM_MESSAGE_FIELD,
    MECH_DEPOSIT_REQUIRED_CODE,
    MECH_PRE_DEPOSIT_EOA_SHORT,
    ONE_REQUEST_AT_A_TIME,
    PREVIOUS_TRADING_TYPE_FIELD,
    SELECTED_MECHS_FIELD,
    SrrHandler,
    TRADING_TYPE_FIELD,
    UPDATED_PARAMS_FIELD,
)
from packages.valory.skills.chatui_abci.mech_templates import (
    NEVER_DELIVERED,
    PARAGRAPH_BREAK,
    PRICE_UNREADABLE,
    accept_line,
)
from packages.valory.skills.chatui_abci.models import (
    ChatuiConfig,
    Offer,
    SharedState,
    TradingStrategyUI,
    WITHDRAWAL_STATE_ARMED,
    WITHDRAWAL_STATE_COMPLETE,
    WITHDRAWAL_STATE_ERRORED,
    WITHDRAWAL_STATE_IDLE,
    WITHDRAWAL_STATE_SELLING,
)
from packages.valory.skills.chatui_abci.prompts import (
    FieldsThatCanBeRemoved,
    TradingStrategy,
)
from packages.valory.skills.mech_interact_abci.models import delivery_rate_bound
from packages.valory.skills.mech_interact_abci.payment_types import PaymentType

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

    context: Any = None  # type: ignore[assignment]
    shared_state: Any = None  # type: ignore[assignment]
    synchronized_data: Any = None  # type: ignore[assignment]
    # Re-declared as Any so tests can replace them with MagicMock and read
    # call_args / assert_called* without mypy chasing the parent signature.
    _store_chatui_param_to_json: Any = None  # type: ignore[assignment]
    _send_ok_response: Any = None  # type: ignore[assignment]
    _send_http_response: Any = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


NATIVE_TYPE_ID = "ba699a34be8fe0e7725e93dcbce1701b0211a8ca61330aaeb8a05bf2ec7abed1"
USDC_TYPE_ID = "6406bb5f31a732f898e1ce9fdd988a80a808d36ab5d9a4a4805a8be8d197d5e3"
NATIVE_RATE = 10**16  # 0.01 xDAI
USDC_RATE = 10000  # 0.01 USDC


def _make_handler(
    available_tools: set = AVAILABLE_TOOLS,
    current_config: Optional[ChatuiConfig] = None,
    available_mechs: Optional[set] = None,
    prediction_tools: Optional[set] = None,
    approved_mechs: Optional[list] = None,
    valid_mechs: Optional[set] = None,
    approved_rates: Optional[Dict[str, int]] = None,
    delivery_rate_caps: Optional[Dict[Any, int]] = None,
) -> _TestableHttpHandler:
    """Return a _TestableHttpHandler wired with minimal mocks.

    `valid_mechs` defaults to the discovered `available_mechs`; approved mechs
    without a rate given are taken as accepted at `NATIVE_RATE`.
    """
    handler = object.__new__(_TestableHttpHandler)

    context = MagicMock()
    context.params.is_running_on_polymarket = False  # wxDAI / 18 decimals
    context.params.delivery_rate_caps = (
        {PaymentType.NATIVE: NATIVE_RATE, PaymentType.TOKEN_USDC: USDC_RATE}
        if delivery_rate_caps is None
        else delivery_rate_caps
    )
    context.params.valid_mechs = frozenset(
        available_mechs or set() if valid_mechs is None else valid_mechs
    )
    context.params.strategies_kwargs = {
        "absolute_min_bet_size": ABS_MIN,
        "absolute_max_bet_size": ABS_MAX,
    }
    handler.context = context  # type: ignore[assignment]

    shared_state = MagicMock()
    shared_state.chatui_config = current_config or ChatuiConfig()
    rates = dict(approved_rates or {})
    for mech in approved_mechs or []:
        rates.setdefault(mech, NATIVE_RATE)
    shared_state.approved_mech_rates = rates
    shared_state.approved_mechs = list(rates)
    shared_state.approved_mech_payment_types = {}
    shared_state.mech_offers = {}
    shared_state.mech_refusals = {}
    shared_state.last_shown_mech = None
    shared_state.last_mech_list = []
    shared_state.available_prediction_tools = (
        frozenset(prediction_tools) if prediction_tools is not None else None
    )
    handler.shared_state = shared_state  # type: ignore[assignment]

    sync_data = MagicMock()
    sync_data.available_mech_tools = available_tools
    sync_data.available_valid_mechs = available_mechs or set()
    sync_data.mech_payment_types = {}
    handler.synchronized_data = sync_data  # type: ignore[assignment]

    # Patch store helpers — no filesystem side-effects.
    handler._store_trading_strategy = MagicMock()  # type: ignore[method-assign]
    handler._store_allowed_tools = MagicMock()  # type: ignore[method-assign]
    handler._store_selected_mechs = MagicMock()  # type: ignore[method-assign]
    handler._store_chatui_param_to_json = MagicMock()  # type: ignore[method-assign]

    return handler


MODEL_MESSAGE = "The model's own answer."


def _config_reply(
    mech_intent: Any = None,
    config: Optional[Dict[str, Any]] = None,
    message: str = MODEL_MESSAGE,
) -> str:
    """A config-chat reply carrying a mech intent, as the genai connection delivers it."""
    reply = {
        "message": message,
        "updated_agent_config": config,
        "mech_intent": mech_intent,
    }
    return json.dumps({"response": json.dumps(reply)})


def _intent(
    intent: Any = "none",
    address: Any = None,
    position: Any = None,
    last_shown: Any = None,
) -> str:
    """A config-chat reply whose mech intent is this one and which changes no config."""
    return _config_reply(
        {
            "intent": intent,
            "address": address,
            "position": position,
            "last_shown": last_shown,
        }
    )


def _answer_model(handler: _TestableHttpHandler, payload: str) -> None:
    """Hand the payload to the callback of the latest model request."""
    _, dialogue, callback, kwargs = handler._send_message.call_args[0]  # type: ignore[attr-defined]
    callback(SimpleNamespace(payload=payload), dialogue, **kwargs)


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

    def test_tool_names_in_the_issue_are_escaped(self) -> None:
        """Tool names are shown as text in the reply, whatever characters they hold."""
        handler = _make_handler()
        handler._available_tools = MagicMock(return_value=["r&d-tool"])  # type: ignore[method-assign]
        _, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["q&a-tool"]}
        )
        assert "r&amp;d-tool" in issues[0]
        assert "q&amp;a-tool" in issues[0]
        assert "r&d-tool" not in issues[0]

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

    def test_non_prediction_tool_rejected_when_prediction_set_published(self) -> None:
        """A tool the classifier rejected must be unpinnable.

        ``resolve-market`` is advertised on-chain (in available_mech_tools) but
        excluded from the suitability-filtered set, so the policy would never
        select it. Validating against the filtered set must reject the pin
        rather than store a tool that silently stalls tool selection.
        """
        handler = _make_handler(
            available_tools={"prediction-online", "resolve-market"},
            prediction_tools={"prediction-online"},
        )
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["resolve-market"]}
        )
        assert len(issues) == 1
        assert "resolve-market" in issues[0]
        handler._store_allowed_tools.assert_not_called()  # type: ignore[attr-defined]
        assert ALLOWED_TOOLS_FIELD not in params

    def test_prediction_tool_stored_against_filtered_set(self) -> None:
        """A tool in the suitability-filtered set must be accepted."""
        handler = _make_handler(
            available_tools={"prediction-online", "resolve-market"},
            prediction_tools={"prediction-online"},
        )
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["prediction-online"]}
        )
        assert issues == []
        assert params[ALLOWED_TOOLS_FIELD] == ["prediction-online"]
        handler._store_allowed_tools.assert_called_once_with(["prediction-online"])  # type: ignore[attr-defined]

    def test_validation_fallback_strips_the_mech_part_of_policy_keys(self) -> None:
        """The raw synced set holds (identity, tool) keys; pins are validated by tool name."""
        mech = "0x" + "a" * 40
        handler = _make_handler(
            available_tools={f"{mech}::prediction-online", f"{mech}::resolve-market"},
            prediction_tools=None,
        )
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["resolve-market"]}
        )
        assert issues == []
        assert params[ALLOWED_TOOLS_FIELD] == ["resolve-market"]
        assert handler._available_tools() == {"prediction-online", "resolve-market"}

    def test_validation_falls_back_to_mech_tools_when_unpublished(self) -> None:
        """With no filtered set published, validation uses available_mech_tools.

        Guards the cold-start / V1 / manifest-failure window: the user can still
        pin any advertised tool rather than being blocked by an absent filtered
        set.
        """
        handler = _make_handler(
            available_tools={"prediction-online", "resolve-market"},
            prediction_tools=None,
        )
        params, issues = handler._process_updated_agent_config(
            {"allowed_tools": ["resolve-market"]}
        )
        assert issues == []
        assert params[ALLOWED_TOOLS_FIELD] == ["resolve-market"]
        handler._store_allowed_tools.assert_called_once_with(["resolve-market"])  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Selected mechs
# ---------------------------------------------------------------------------


_AVAILABLE_MECHS = {
    "0x601024e27f1c67b28209e24272ced8a31fc8151f",
    "0xc05e7412439bd7e91730a6880e18d5d5873f632c",
}


class TestSelectedMechs:
    """Tests for selected_mechs field processing."""

    def test_valid_list_stored_lowercase(self) -> None:
        """Mixed-case input is normalized to lowercase before storage."""
        handler = _make_handler(available_mechs=_AVAILABLE_MECHS)
        params, issues = handler._process_updated_agent_config(
            {"selected_mechs": ["0X601024E27F1C67B28209E24272CED8A31FC8151F"]}
        )
        assert issues == []
        expected = ["0x601024e27f1c67b28209e24272ced8a31fc8151f"]
        assert params[SELECTED_MECHS_FIELD] == expected
        handler._store_selected_mechs.assert_called_once_with(expected)  # type: ignore[attr-defined]

    def test_unknown_mechs_dropped_and_issue_added(self) -> None:
        """Unknown mechs are dropped; the valid ones are still stored."""
        handler = _make_handler(available_mechs=_AVAILABLE_MECHS)
        params, issues = handler._process_updated_agent_config(
            {
                "selected_mechs": [
                    "0x601024e27f1c67b28209e24272ced8a31fc8151f",
                    "0xdeadbeef",
                ]
            }
        )
        assert len(issues) == 1
        assert "0xdeadbeef" in issues[0]
        handler._store_selected_mechs.assert_called_once_with(  # type: ignore[attr-defined]
            ["0x601024e27f1c67b28209e24272ced8a31fc8151f"]
        )

    def test_all_unknown_adds_issue_no_store(self) -> None:
        """If every mech is unknown, the store is not touched."""
        handler = _make_handler(available_mechs=_AVAILABLE_MECHS)
        params, issues = handler._process_updated_agent_config(
            {"selected_mechs": ["0xnotreal1", "0xnotreal2"]}
        )
        assert len(issues) == 1
        handler._store_selected_mechs.assert_not_called()  # type: ignore[attr-defined]
        assert SELECTED_MECHS_FIELD not in params

    def test_empty_list_treated_as_clear(self) -> None:
        """Empty list explicitly clears the pin to None."""
        handler = _make_handler(available_mechs=_AVAILABLE_MECHS)
        params, issues = handler._process_updated_agent_config({"selected_mechs": []})
        assert issues == []
        assert params[SELECTED_MECHS_FIELD] is None
        handler._store_selected_mechs.assert_called_once_with(None)  # type: ignore[attr-defined]

    def test_remove_clears_pin(self) -> None:
        """`removed_config_fields` entry clears the pin to None."""
        handler = _make_handler(
            available_mechs=_AVAILABLE_MECHS,
            current_config=ChatuiConfig(
                selected_mechs=["0x601024e27f1c67b28209e24272ced8a31fc8151f"]
            ),
        )
        params, issues = handler._process_updated_agent_config(
            {"removed_config_fields": [FieldsThatCanBeRemoved.SELECTED_MECHS.value]}
        )
        assert issues == []
        assert params[SELECTED_MECHS_FIELD] is None
        handler._store_selected_mechs.assert_called_once_with(None)  # type: ignore[attr-defined]

    def test_remove_takes_precedence_over_set(self) -> None:
        """Remove must win when both a list and a remove are present."""
        handler = _make_handler(available_mechs=_AVAILABLE_MECHS)
        params, _issues = handler._process_updated_agent_config(
            {
                "selected_mechs": ["0x601024e27f1c67b28209e24272ced8a31fc8151f"],
                "removed_config_fields": [FieldsThatCanBeRemoved.SELECTED_MECHS.value],
            }
        )
        assert params[SELECTED_MECHS_FIELD] is None
        handler._store_selected_mechs.assert_called_once_with(None)  # type: ignore[attr-defined]

    def test_absent_field_is_noop(self) -> None:
        """Missing selected_mechs field must be a no-op."""
        handler = _make_handler(available_mechs=_AVAILABLE_MECHS)
        params, issues = handler._process_updated_agent_config({})
        assert SELECTED_MECHS_FIELD not in params
        handler._store_selected_mechs.assert_not_called()  # type: ignore[attr-defined]


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
# Activity goal
# ---------------------------------------------------------------------------

GOAL_PERIOD_START = 1_791_331_200
GOAL_NOW = GOAL_PERIOD_START + 3_600


class TestActivityGoal:
    """Tests for setting the activity goal through the chat."""

    @staticmethod
    def _handler(
        store_path: Path, current_goal: Optional[int] = None, progress: int = 3
    ) -> _TestableHttpHandler:
        """Return a handler over ``store_path`` holding a published block."""
        handler = _make_handler(current_config=ChatuiConfig(activity_goal=current_goal))
        handler.context.params.store_path = store_path
        handler.context.params.default_activity_goal = 8
        handler.shared_state.synced_timestamp = GOAL_NOW
        update_activity_goal(
            store_path,
            8 if current_goal is None else current_goal,
            progress,
            GOAL_PERIOD_START,
            GOAL_PERIOD_START + 60,
            MagicMock(),
        )
        return handler

    @staticmethod
    def _info_lines(handler: _TestableHttpHandler) -> list:
        """Return the INFO messages logged about the goal."""
        return [
            call.args[0]
            for call in handler.context.logger.info.call_args_list
            if "ctivity goal" in call.args[0]
        ]

    @pytest.mark.parametrize("goal", [0, 20, 500])
    def test_valid_goal_is_persisted_and_published(
        self, tmp_path: Path, goal: int
    ) -> None:
        """A valid goal, however large, is stored and shown in the block at once."""
        handler = self._handler(tmp_path)

        params, issues = handler._process_updated_agent_config({"activity_goal": goal})

        assert issues == []
        assert params == {"activity_goal": goal}
        handler._store_chatui_param_to_json.assert_called_once_with(  # type: ignore[attr-defined]
            "activity_goal", goal
        )
        assert handler.shared_state.chatui_config.activity_goal == goal
        block = read_activity_goal(tmp_path)
        assert block is not None
        assert block.target == goal
        assert block.progress == 3
        assert block.period_start == GOAL_PERIOD_START
        assert block.is_met is (3 >= goal)
        assert block.updated_at == GOAL_NOW
        assert self._info_lines(handler) == [
            f"Activity goal changed from None to {goal} (None is the default, 8)."
        ]

    @pytest.mark.parametrize("goal", [True, False, 20.0, 2.5, -1, "20", [20]])
    def test_invalid_goal_declines_the_whole_reply(
        self, tmp_path: Path, goal: Any
    ) -> None:
        """An invalid goal adds an issue and nothing in the reply is written."""
        handler = self._handler(tmp_path, current_goal=5)
        block_before = (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).read_text()

        params, issues = handler._process_updated_agent_config(
            {
                "activity_goal": goal,
                "trading_strategy": TradingStrategy.FIXED_BET.value,
                "fixed_bet_size": 0.05,
                "behavior": "A steady strategy.",
            }
        )

        assert params == {}
        assert len(issues) == 1
        assert "Activity goal" in issues[0]
        handler._store_trading_strategy.assert_not_called()  # type: ignore[attr-defined]
        handler._store_chatui_param_to_json.assert_not_called()  # type: ignore[attr-defined]
        handler.shared_state.update_agent_behavior.assert_not_called()  # type: ignore[attr-defined]
        assert handler.shared_state.chatui_config.activity_goal == 5
        assert (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).read_text() == block_before
        lines = self._info_lines(handler)
        assert len(lines) == 1
        assert lines[0].startswith("Declined activity goal change")

    def test_removal_reverts_to_default(self, tmp_path: Path) -> None:
        """Removing the goal stores null and publishes the default target."""
        handler = self._handler(tmp_path, current_goal=20)

        params, issues = handler._process_updated_agent_config(
            {
                "activity_goal": 30,
                "removed_config_fields": [FieldsThatCanBeRemoved.ACTIVITY_GOAL.value],
            }
        )

        assert issues == []
        assert params == {"activity_goal": None}
        handler._store_chatui_param_to_json.assert_called_once_with(  # type: ignore[attr-defined]
            "activity_goal", None
        )
        assert handler.shared_state.chatui_config.activity_goal is None
        block = read_activity_goal(tmp_path)
        assert block is not None
        assert block.target == 8
        assert self._info_lines(handler) == [
            "Activity goal changed from 20 to None (None is the default, 8)."
        ]

    def test_publish_failure_keeps_the_reply_applied(self, tmp_path: Path) -> None:
        """A failed block write is logged; the reply's writes and the goal stand."""
        handler = self._handler(tmp_path, current_goal=5)

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.activity_goal.write_performance_summary_key",
            side_effect=OSError("disk full"),
        ):
            params, issues = handler._process_updated_agent_config(
                {"activity_goal": 20, "behavior": "A steady strategy."}
            )

        assert issues == []
        assert params == {"activity_goal": 20}
        handler.shared_state.update_agent_behavior.assert_called_once_with(  # type: ignore[attr-defined]
            "A steady strategy."
        )
        assert handler.shared_state.chatui_config.activity_goal == 20
        handler.context.logger.error.assert_called_once()
        assert "disk full" in handler.context.logger.error.call_args.args[0]

    def test_store_failure_is_reported_not_raised(self, tmp_path: Path) -> None:
        """A failed store write reports an issue instead of an unreadable reply."""
        handler = self._handler(tmp_path, current_goal=5)
        handler._store_chatui_param_to_json.side_effect = OSError("disk full")  # type: ignore[attr-defined]

        _, issues = handler._process_updated_agent_config(
            {"activity_goal": 20, "behavior": "A steady strategy."}
        )

        assert len(issues) == 1
        assert "could not be saved" in issues[0]
        handler.shared_state.update_agent_behavior.assert_called_once_with(  # type: ignore[attr-defined]
            "A steady strategy."
        )
        handler.context.logger.error.assert_called_once()
        assert "disk full" in handler.context.logger.error.call_args.args[0]

    @pytest.mark.parametrize(
        "block_content",
        [
            b"\xff\xfe",
            json.dumps(
                {
                    "activity_goal": {
                        "unit": "trades",
                        "target": 8,
                        "progress": "3",
                        "is_met": False,
                        "period_start": GOAL_PERIOD_START,
                        "updated_at": GOAL_NOW,
                        "last_met_at": None,
                    }
                }
            ).encode(),
        ],
        ids=["not_utf8", "wrongly_typed_block"],
    )
    def test_unusable_published_block_does_not_fail_the_reply(
        self, tmp_path: Path, block_content: bytes
    ) -> None:
        """An unreadable summary leaves the goal stored and is rebuilt later."""
        handler = self._handler(tmp_path, current_goal=5)
        (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).write_bytes(block_content)

        params, issues = handler._process_updated_agent_config({"activity_goal": 20})

        assert issues == []
        assert params == {"activity_goal": 20}
        assert handler.shared_state.chatui_config.activity_goal == 20
        assert read_activity_goal(tmp_path) is None

    def test_goal_stored_before_any_evaluation(self, tmp_path: Path) -> None:
        """Without a published block the goal is still stored; no block is invented."""
        handler = _make_handler()
        handler.context.params.store_path = tmp_path
        handler.context.params.default_activity_goal = 8
        handler.shared_state.synced_timestamp = GOAL_NOW

        _, issues = handler._process_updated_agent_config({"activity_goal": 4})

        assert issues == []
        assert handler.shared_state.chatui_config.activity_goal == 4
        assert not (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).exists()

    def test_absent_goal_is_noop(self, tmp_path: Path) -> None:
        """A reply that does not mention the goal leaves it alone."""
        handler = self._handler(tmp_path, current_goal=5)

        params, _ = handler._process_updated_agent_config({"behavior": "x"})

        assert "activity_goal" not in params
        assert handler.shared_state.chatui_config.activity_goal == 5


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
        handler.context = MagicMock()  # type: ignore[assignment]
        handler.context.params.service_endpoint = "http://localhost:8000"  # type: ignore[attr-defined]
        handler.routes = {}

        # Patch the parent setup() and the hostname_regex property
        with (
            patch.object(HttpHandler.__bases__[0], "setup", return_value=None),
            patch.object(
                type(handler),
                "hostname_regex",
                new_callable=lambda: property(lambda self: r".*localhost(:\d+)?"),
            ),
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
        handler.context = MagicMock()  # type: ignore[assignment]
        sentinel = MagicMock()
        handler.context.state = sentinel  # type: ignore[attr-defined]
        # Access the property from HttpHandler (not _TestableHttpHandler which shadows it)
        result = HttpHandler.shared_state.fget(handler)  # type: ignore[attr-defined, union-attr]
        assert result is sentinel

    def test_round_sequence_returns_shared_state_round_sequence(self) -> None:
        """round_sequence property must return shared_state.round_sequence."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()  # type: ignore[assignment]
        rs_sentinel = MagicMock()
        # shared_state property calls self.context.state, set it up
        handler.context.state.round_sequence = rs_sentinel  # type: ignore[attr-defined]
        # Wire shared_state so that round_sequence can chain through it
        handler.shared_state = handler.context.state  # type: ignore[attr-defined]
        result = HttpHandler.round_sequence.fget(handler)  # type: ignore[attr-defined, union-attr]
        assert result is rs_sentinel

    def test_synchronized_data_returns_synced_data(self) -> None:
        """synchronized_data property must return a SynchronizedData from the DB."""
        handler = object.__new__(_TestableHttpHandler)
        handler.context = MagicMock()  # type: ignore[assignment]
        db_mock = MagicMock()
        handler.context.state.round_sequence.latest_synchronized_data.db = db_mock  # type: ignore[attr-defined]
        # Wire shared_state so that round_sequence and then synchronized_data can chain
        handler.shared_state = handler.context.state  # type: ignore[attr-defined]
        result = HttpHandler.synchronized_data.fget(handler)  # type: ignore[attr-defined, union-attr]
        assert result.db is db_mock


class TestGetUiTradingStrategy:
    """Tests for _get_ui_trading_strategy()."""

    def test_none_returns_balanced(self) -> None:
        """None input must return BALANCED."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy(None)
        assert result == TradingStrategyUI.BALANCED

    def test_legacy_bet_amount_per_threshold_returns_balanced(self) -> None:
        """Legacy bet_amount_per_threshold must map to BALANCED."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy("bet_amount_per_threshold")
        assert result == TradingStrategyUI.BALANCED

    def test_legacy_kelly_criterion_no_conf_returns_risky(self) -> None:
        """Legacy kelly_criterion_no_conf must map to RISKY."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy("kelly_criterion_no_conf")
        assert result == TradingStrategyUI.RISKY

    def test_unknown_strategy_returns_risky(self) -> None:
        """Any unknown strategy string must default to RISKY."""
        handler = _make_handler()
        result = handler._get_ui_trading_strategy("some_unknown_strategy")
        assert result == TradingStrategyUI.RISKY


class TestStrategyMigration:
    """Tests for legacy strategy name migration."""

    def test_legacy_kelly_name_rejected_by_available_strategies(self) -> None:
        """kelly_criterion_no_conf must not be in AVAILABLE_TRADING_STRATEGIES."""
        from packages.valory.skills.chatui_abci.handlers import (
            AVAILABLE_TRADING_STRATEGIES,
        )

        assert "kelly_criterion_no_conf" not in AVAILABLE_TRADING_STRATEGIES

    def test_legacy_threshold_name_rejected_by_available_strategies(self) -> None:
        """bet_amount_per_threshold must not be in AVAILABLE_TRADING_STRATEGIES."""
        from packages.valory.skills.chatui_abci.handlers import (
            AVAILABLE_TRADING_STRATEGIES,
        )

        assert "bet_amount_per_threshold" not in AVAILABLE_TRADING_STRATEGIES

    def test_new_kelly_in_available_strategies(self) -> None:
        """kelly_criterion must be in AVAILABLE_TRADING_STRATEGIES."""
        from packages.valory.skills.chatui_abci.handlers import (
            AVAILABLE_TRADING_STRATEGIES,
        )

        assert "kelly_criterion" in AVAILABLE_TRADING_STRATEGIES

    def test_new_fixed_bet_in_available_strategies(self) -> None:
        """fixed_bet must be in AVAILABLE_TRADING_STRATEGIES."""
        from packages.valory.skills.chatui_abci.handlers import (
            AVAILABLE_TRADING_STRATEGIES,
        )

        assert "fixed_bet" in AVAILABLE_TRADING_STRATEGIES


class TestGetAvailableTools:
    """Tests for _get_available_tools()."""

    def test_returns_tools_on_success(self) -> None:
        """When synchronized_data is accessible, return available_mech_tools."""
        handler = _make_handler()
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        result = handler._get_available_tools(http_msg, http_dialogue)
        assert result == AVAILABLE_TOOLS

    def test_prefers_filtered_set_when_published(self) -> None:
        """The filtered set wins over the raw synced set when present."""
        handler = _make_handler(
            available_tools={"prediction-online", "resolve-market"},
            prediction_tools={"prediction-online"},
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        result = handler._get_available_tools(http_msg, http_dialogue)
        assert result == {"prediction-online"}

    def test_falls_back_to_mech_tools_when_unpublished(self) -> None:
        """With no filtered set published, return the raw synced set."""
        handler = _make_handler(
            available_tools={"prediction-online", "resolve-market"},
            prediction_tools=None,
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        result = handler._get_available_tools(http_msg, http_dialogue)
        assert result == {"prediction-online", "resolve-market"}

    def test_falls_back_to_mech_tools_when_published_set_empty(self) -> None:
        """An empty published set must fall back to raw, not "reject everything".

        An empty ``frozenset`` would otherwise make every pin invalid and brick
        ``configure_strategies``; it must read as "nothing published, fall back".
        """
        handler = _make_handler(
            available_tools={"prediction-online", "resolve-market"},
            prediction_tools=set(),  # published an empty frozenset
        )
        http_msg = MagicMock()
        http_dialogue = MagicMock()
        result = handler._get_available_tools(http_msg, http_dialogue)
        assert result == {"prediction-online", "resolve-market"}

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

    @pytest.mark.parametrize(
        "current_goal, published_progress, expected",
        [
            (
                None,
                3,
                [
                    "- Activity goal: 8 trades per staking epoch (the default)",
                    "Trades placed so far this epoch: 3.",
                    "Default: 8.",
                ],
            ),
            (
                20,
                None,
                [
                    "- Activity goal: 20 trades per staking epoch (set by the user)",
                    "Trades placed so far this epoch: not counted yet.",
                    "Default: 8.",
                ],
            ),
        ],
        ids=["default_with_progress", "user_goal_not_counted_yet"],
    )
    def test_prompt_includes_activity_goal(
        self,
        current_goal: Optional[int],
        published_progress: Optional[int],
        expected: list,
    ) -> None:
        """The prompt tells the model the current goal, the default and progress."""
        handler = self._make_prompt_handler(
            current_config=ChatuiConfig(activity_goal=current_goal)
        )
        handler.context.params.default_activity_goal = 8
        published = None
        if published_progress is not None:
            published = MagicMock(progress=published_progress)
        handler.shared_state.read_activity_goal_from_disk.return_value = published

        handler._handle_chatui_prompt(
            self._make_http_msg({"prompt": "what is my goal?"}), MagicMock()
        )

        prompt = handler._send_chatui_llm_request.call_args.kwargs["prompt"]  # type: ignore[attr-defined]
        for text in expected:
            assert text in prompt


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
            user_prompt="make me risky",
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
        assert callback_kwargs["user_prompt"] == "make me risky"

    def test_payload_contains_prompt_and_schema(self) -> None:
        """Payload sent via SRR must contain 'prompt' and 'schema'."""
        handler = _make_handler()
        mock_srr_dialogues = MagicMock()
        mock_srr_dialogues.create.return_value = (MagicMock(), MagicMock())
        handler.context.srr_dialogues = mock_srr_dialogues  # type: ignore[attr-defined]
        handler._send_message = MagicMock()  # type: ignore[assignment]

        handler._send_chatui_llm_request(
            prompt="hello",
            http_msg=MagicMock(),
            http_dialogue=MagicMock(),
            user_prompt="hello",
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
            trading_strategy=TradingStrategy.FIXED_BET.value,
        )
        strategy = TradingStrategy.KELLY_CRITERION.value
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
            trading_strategy=TradingStrategy.FIXED_BET.value,
        )
        strategy = TradingStrategy.KELLY_CRITERION.value
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
        current_strategy = TradingStrategy.FIXED_BET.value
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
        handler.context = MagicMock()  # type: ignore[assignment]
        shared_state_mock = MagicMock()
        current_store = {"existing_key": "existing_value"}
        shared_state_mock._get_current_json_store.return_value = current_store
        handler.shared_state = shared_state_mock  # type: ignore[assignment]

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
        handler.context = MagicMock()  # type: ignore[assignment]
        shared_state_mock = MagicMock()
        shared_state_mock.chatui_config = ChatuiConfig()
        handler.shared_state = shared_state_mock  # type: ignore[assignment]
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
        handler.context = MagicMock()  # type: ignore[assignment]
        shared_state_mock = MagicMock()
        shared_state_mock.chatui_config = ChatuiConfig()
        handler.shared_state = shared_state_mock  # type: ignore[assignment]
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
        handler.context = MagicMock()  # type: ignore[assignment]
        shared_state_mock = MagicMock()
        shared_state_mock.chatui_config = ChatuiConfig(allowed_tools=["old"])
        handler.shared_state = shared_state_mock  # type: ignore[assignment]
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


# ---------------------------------------------------------------------------
# Resilience audit: BUG 18 -- _handle_chatui_prompt json.loads crash
# ---------------------------------------------------------------------------


class TestHandleChatuiPromptMalformedJson:
    """BUG 18: _handle_chatui_prompt calls json.loads without try-except.

    A POST with non-JSON body raises json.JSONDecodeError that escapes
    to the framework. Combined with BUG 16, the HTTP client gets no response.
    """

    def test_malformed_json_body_sends_400(self) -> None:
        """Malformed POST body sends HTTP 400 Bad Request."""
        handler = _make_handler()
        handler._send_bad_request_response = MagicMock()  # type: ignore[method-assign]

        http_msg = MagicMock()
        http_msg.body = b"not valid json{{"
        http_dialogue = MagicMock()

        handler._handle_chatui_prompt(http_msg, http_dialogue)

        handler._send_bad_request_response.assert_called_once()
        call_args = handler._send_bad_request_response.call_args
        assert "Invalid JSON" in str(call_args)


# ---------------------------------------------------------------------------
# Withdrawal endpoints — POST /api/v1/withdrawal
# ---------------------------------------------------------------------------


def _make_withdrawal_handler(
    *,
    is_polymarket: bool = True,
    config: Optional[ChatuiConfig] = None,
) -> _TestableHttpHandler:
    """Return a handler configured for the withdrawal endpoint tests."""
    handler = object.__new__(_TestableHttpHandler)

    context = MagicMock()
    context.params.is_running_on_polymarket = is_polymarket
    handler.context = context  # type: ignore[assignment]

    shared_state = MagicMock()
    cfg = config or ChatuiConfig()
    shared_state.chatui_config = cfg
    # Model the disk view as a mutable dict that mirrors the in-memory cfg
    # at handler creation. This lets GET (which now reads from disk) see
    # the same state existing tests previously asserted on cfg directly.
    # Tests that exercise cfg/disk divergence overwrite ``return_value``
    # on the mock directly.
    disk_view: Dict[str, Any] = asdict(cfg)
    shared_state._get_current_json_store.return_value = disk_view
    handler.shared_state = shared_state  # type: ignore[assignment]

    # Wire the per-field persist mock so writes to "disk" are visible to
    # subsequent reads. Mirrors production: _store_chatui_param_to_json
    # does read-modify-write on the JSON store, so subsequent GETs see
    # the updated state.
    def _persist_to_disk_view(param_name: str, value: Any) -> None:
        disk_view[param_name] = value

    handler._store_chatui_param_to_json = MagicMock(  # type: ignore[method-assign]
        side_effect=_persist_to_disk_view
    )
    handler._send_ok_response = MagicMock()  # type: ignore[method-assign]
    handler._send_http_response = MagicMock()  # type: ignore[method-assign]
    return handler


class TestHandlePostWithdrawalPolymarket:
    """Tests for POST /api/v1/withdrawal on the Polymarket service."""

    def test_post_from_idle_arms_flag_and_state(self) -> None:
        """POST from idle must set withdrawal_mode=True and state=armed."""
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            )
        )

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        cfg = handler.shared_state.chatui_config
        assert cfg.withdrawal_mode is True
        assert cfg.withdrawal_state == WITHDRAWAL_STATE_ARMED

    def test_post_from_idle_resets_fills_and_errors(self) -> None:
        """POST from idle must reset fills and errors arrays (D21)."""
        starting_cfg = ChatuiConfig(
            withdrawal_mode=False,
            withdrawal_state=WITHDRAWAL_STATE_IDLE,
            withdrawal_fills=[
                {
                    "token_id": "x",
                    "shares_sold": 1.0,
                    "fill_price": 0.5,
                    "ts": 1,
                }  # nosec B105
            ],
            withdrawal_errors=[
                {
                    "token_id": "y",
                    "shares_remaining": 2.0,
                    "reason": "old",
                    "ts": 2,
                }  # nosec B105
            ],
        )
        handler = _make_withdrawal_handler(config=starting_cfg)

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        assert handler.shared_state.chatui_config.withdrawal_fills == []
        assert handler.shared_state.chatui_config.withdrawal_errors == []

    def test_post_from_idle_persists_each_changed_field(self) -> None:
        """POST from idle must persist withdrawal_mode, state, fills, errors."""
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            )
        )

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        persisted_calls = handler._store_chatui_param_to_json.call_args_list
        persisted_fields = {call.args[0] for call in persisted_calls}
        assert "withdrawal_mode" in persisted_fields
        assert "withdrawal_state" in persisted_fields
        assert "withdrawal_fills" in persisted_fields
        assert "withdrawal_errors" in persisted_fields

    def test_post_from_idle_returns_200_with_armed_status(self) -> None:
        """POST from idle returns 200 OK; payload mode == 'armed'."""
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            )
        )

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        handler._send_ok_response.assert_called_once()
        payload = handler._send_ok_response.call_args.args[2]
        assert payload["mode"] == WITHDRAWAL_STATE_ARMED

    @pytest.mark.parametrize(
        "live_state",
        [
            WITHDRAWAL_STATE_ARMED,
            WITHDRAWAL_STATE_SELLING,
            WITHDRAWAL_STATE_COMPLETE,
            WITHDRAWAL_STATE_ERRORED,
        ],
    )
    def test_post_from_non_idle_is_noop(self, live_state: str) -> None:
        """POST from any non-idle state must NOT mutate any field (D20 idempotency)."""
        starting_cfg = ChatuiConfig(
            withdrawal_mode=True,
            withdrawal_state=live_state,
            withdrawal_fills=[{"keep": True}],
            withdrawal_errors=[{"keep": True}],
        )
        handler = _make_withdrawal_handler(config=starting_cfg)

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        cfg = handler.shared_state.chatui_config
        assert cfg.withdrawal_mode is True
        assert cfg.withdrawal_state == live_state
        assert cfg.withdrawal_fills == [{"keep": True}]
        assert cfg.withdrawal_errors == [{"keep": True}]
        handler._store_chatui_param_to_json.assert_not_called()

    @pytest.mark.parametrize(
        "live_state",
        [
            WITHDRAWAL_STATE_ARMED,
            WITHDRAWAL_STATE_SELLING,
            WITHDRAWAL_STATE_COMPLETE,
            WITHDRAWAL_STATE_ERRORED,
        ],
    )
    def test_post_from_non_idle_returns_200_with_current_status(
        self, live_state: str
    ) -> None:
        """POST from any non-idle state returns 200 with current mode unchanged."""
        starting_cfg = ChatuiConfig(withdrawal_mode=True, withdrawal_state=live_state)
        handler = _make_withdrawal_handler(config=starting_cfg)

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        handler._send_ok_response.assert_called_once()
        payload = handler._send_ok_response.call_args.args[2]
        assert payload["mode"] == live_state


class TestHandlePostWithdrawalOmenstrat:
    """Tests for POST /api/v1/withdrawal on Omenstrat.

    The 501 reject from #942 (D27) was removed once the real Omen sweep
    behaviour landed — POST on Omenstrat now arms the same way Polystrat
    does. These tests prove venue parity at the HTTP boundary.
    """

    def test_post_on_omenstrat_arms_flag_and_state(self) -> None:
        """POST from idle on Omenstrat must arm just like Polystrat."""
        handler = _make_withdrawal_handler(
            is_polymarket=False,
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            ),
        )

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        cfg = handler.shared_state.chatui_config
        assert cfg.withdrawal_mode is True
        assert cfg.withdrawal_state == WITHDRAWAL_STATE_ARMED

    def test_post_on_omenstrat_returns_200(self) -> None:
        """POST on Omenstrat returns 200 OK (the 501 from #942 was dropped)."""
        handler = _make_withdrawal_handler(
            is_polymarket=False,
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            ),
        )

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        handler._send_ok_response.assert_called_once()
        # No 501 response should ever fire on the new path.
        handler._send_http_response.assert_not_called()

    def test_post_on_omenstrat_persists_each_changed_field(self) -> None:
        """POST on Omenstrat persists the same fields the Polystrat path does."""
        handler = _make_withdrawal_handler(
            is_polymarket=False,
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            ),
        )

        handler._handle_post_withdrawal(MagicMock(), MagicMock())

        persisted_fields = {
            call.args[0] for call in handler._store_chatui_param_to_json.call_args_list
        }
        assert "withdrawal_mode" in persisted_fields
        assert "withdrawal_state" in persisted_fields
        assert "withdrawal_fills" in persisted_fields
        assert "withdrawal_errors" in persisted_fields


# ---------------------------------------------------------------------------
# Withdrawal endpoints — GET /api/v1/withdrawal
# ---------------------------------------------------------------------------


class TestHandleGetWithdrawal:
    """Tests for GET /api/v1/withdrawal."""

    def test_get_idle_state_returns_idle_payload(self) -> None:
        """GET on a fresh agent must return mode=idle with empty arrays."""
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=False, withdrawal_state=WITHDRAWAL_STATE_IDLE
            )
        )

        handler._handle_get_withdrawal(MagicMock(), MagicMock())

        payload = handler._send_ok_response.call_args.args[2]
        assert payload["mode"] == WITHDRAWAL_STATE_IDLE
        assert payload["positions_total"] == 0
        assert payload["positions_sold"] == 0
        assert payload["positions_stuck"] == 0
        assert payload["fills"] == []
        assert payload["errors"] == []

    def test_get_includes_venue_polymarket(self) -> None:
        """GET on Polystrat must report venue='polymarket'."""
        handler = _make_withdrawal_handler(is_polymarket=True)

        handler._handle_get_withdrawal(MagicMock(), MagicMock())

        payload = handler._send_ok_response.call_args.args[2]
        assert payload["venue"] == "polymarket"

    def test_get_includes_venue_omen(self) -> None:
        """GET on Omenstrat must report venue='omen'."""
        handler = _make_withdrawal_handler(is_polymarket=False)

        handler._handle_get_withdrawal(MagicMock(), MagicMock())

        payload = handler._send_ok_response.call_args.args[2]
        assert payload["venue"] == "omen"

    def test_get_counts_derived_from_fills_and_errors(self) -> None:
        """positions_total = len(fills)+len(errors); _sold = len(fills); _stuck = len(errors)."""
        fills = [
            {
                "token_id": "a",
                "shares_sold": 1.0,
                "fill_price": 0.5,
                "ts": 1,
            },  # nosec B105
            {
                "token_id": "b",
                "shares_sold": 2.0,
                "fill_price": 0.6,
                "ts": 2,
            },  # nosec B105
        ]
        errors = [
            {
                "token_id": "c",
                "shares_remaining": 3.0,
                "reason": "x",
                "ts": 3,
            },  # nosec B105
        ]
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=True,
                withdrawal_state=WITHDRAWAL_STATE_SELLING,
                withdrawal_fills=fills,
                withdrawal_errors=errors,
            )
        )

        handler._handle_get_withdrawal(MagicMock(), MagicMock())

        payload = handler._send_ok_response.call_args.args[2]
        assert payload["positions_total"] == 3
        assert payload["positions_sold"] == 2
        assert payload["positions_stuck"] == 1
        assert payload["fills"] == fills
        assert payload["errors"] == errors

    def test_get_mirrors_state_from_config(self) -> None:
        """GET response 'mode' must equal the persisted withdrawal_state."""
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=True, withdrawal_state=WITHDRAWAL_STATE_COMPLETE
            )
        )

        handler._handle_get_withdrawal(MagicMock(), MagicMock())

        payload = handler._send_ok_response.call_args.args[2]
        assert payload["mode"] == WITHDRAWAL_STATE_COMPLETE

    def test_get_reflects_disk_writes_made_outside_post_handler(self) -> None:
        """GET must surface state and fills written to disk by another skill.

        Simulates the production hot path: POST arms the flag (cfg + disk),
        then ``decision_maker_abci`` writes ``withdrawal_state=selling`` and
        a fill record directly to ``chatui_param_store.json`` (bypassing
        chatui_abci's in-memory cfg, since it's a different skill). The next
        GET must return the disk values, not the cached cfg.
        """
        # In-memory cfg simulates the post-POST state: armed, no fills yet.
        handler = _make_withdrawal_handler(
            config=ChatuiConfig(
                withdrawal_mode=True,
                withdrawal_state=WITHDRAWAL_STATE_ARMED,
                withdrawal_fills=[],
                withdrawal_errors=[],
            )
        )
        # Simulate decision_maker_abci writing to disk after the sweep started:
        # state advanced to selling and one fill recorded. The chatui in-memory
        # cfg does NOT see these writes because the behaviour writes to disk
        # directly, not through chatui's SharedState.
        disk_fill = {
            "token_id": "0xabc",  # nosec B105
            "shares_sold": 60.0,
            "fill_price": 0.5,
            "ts": 100,
        }
        handler.shared_state._get_current_json_store.return_value = {
            "withdrawal_mode": True,
            "withdrawal_state": WITHDRAWAL_STATE_SELLING,
            "withdrawal_fills": [disk_fill],
            "withdrawal_errors": [],
        }

        handler._handle_get_withdrawal(MagicMock(), MagicMock())

        payload = handler._send_ok_response.call_args.args[2]
        # disk wins: the response reflects the behaviour's writes, not the
        # stale in-memory cfg.
        assert payload["mode"] == WITHDRAWAL_STATE_SELLING
        assert payload["fills"] == [disk_fill]
        assert payload["positions_sold"] == 1
        assert payload["positions_total"] == 1


# ---------------------------------------------------------------------------
# Withdrawal endpoints — route registration
# ---------------------------------------------------------------------------


class TestWithdrawalRouteRegistration:
    """The withdrawal routes must be registered by HttpHandler.setup()."""

    def _registered_routes(self) -> Dict[tuple, list]:  # type: ignore[name-defined]
        """Return the routes table after setup() runs against a mocked context."""
        from packages.valory.skills.agent_performance_summary_abci.handlers import (
            HttpHandler as BaseHttpHandler,
        )

        handler = object.__new__(_TestableHttpHandler)
        handler.routes = {}  # type: ignore[attr-defined]

        context = MagicMock()
        context.params.service_endpoint = "https://example.com"
        handler.context = context  # type: ignore[assignment]

        # Bypass the agent_performance_summary super().setup() so we don't
        # depend on its hostname_regex / route construction here.
        with patch.object(BaseHttpHandler, "setup", lambda self: None):
            handler.setup()
        return handler.routes  # type: ignore[no-any-return]

    def test_post_withdrawal_route_registered(self) -> None:
        """POST /api/v1/withdrawal must be registered with the post handler."""
        routes = self._registered_routes()
        post_routes = routes.get((HttpMethod.POST.value,), [])
        regex_strings = [pattern for pattern, _ in post_routes]
        assert any(
            "withdrawal" in p for p in regex_strings
        ), f"no /api/v1/withdrawal POST route registered; found: {regex_strings}"

    def test_get_withdrawal_route_registered(self) -> None:
        """GET /api/v1/withdrawal must be registered with the get handler."""
        routes = self._registered_routes()
        get_routes = routes.get((HttpMethod.GET.value,), [])
        regex_strings = [pattern for pattern, _ in get_routes]
        assert any(
            "withdrawal" in p for p in regex_strings
        ), f"no /api/v1/withdrawal GET route registered; found: {regex_strings}"


class TestAnUnreadableLlmReplyDoesNotStopTheAgent:
    """The prompt asks the model for JSON; nothing makes it comply.

    The service runs under ``stop_and_exit``, so an exception raised out
    of this handler ends the agent. One prompt answered in prose would
    stop trading until somebody restarted it.
    """

    @staticmethod
    def _handler() -> Any:
        handler = _make_handler()
        handler._send_internal_server_error_response = MagicMock()  # type: ignore[method-assign]
        handler._handle_chatui_llm_error = MagicMock()  # type: ignore[method-assign]
        handler._send_ok_response = MagicMock()  # type: ignore[method-assign]
        return handler

    @staticmethod
    def _reply(payload: Any) -> Any:
        message = MagicMock()
        message.payload = payload
        return message

    @pytest.mark.parametrize(
        "model_text",
        [
            pytest.param("I'm sorry, I can't help with that.", id="prose"),
            pytest.param('```json\n{"message": "hi"}\n```', id="fenced block"),
            pytest.param("", id="empty"),
            pytest.param("[1, 2, 3]", id="a list, not an object"),
            pytest.param('"just a string"', id="a bare string"),
        ],
    )
    def test_a_reply_that_is_not_a_json_object_is_answered_not_raised(
        self, model_text: str
    ) -> None:
        """Each of these used to raise straight out of the handler."""
        handler = self._handler()
        payload = json.dumps({"response": model_text})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        body = handler._send_internal_server_error_response.call_args[0][2]
        assert "error" in body

    def test_a_payload_that_is_not_json_at_all_is_answered_not_raised(self) -> None:
        """The connection encodes this, but a handler must not end the agent on it."""
        handler = self._handler()

        handler._handle_chatui_llm_response(
            self._reply("not json"), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()

    def test_a_well_formed_reply_is_still_processed(self) -> None:
        """The guard must not swallow the normal path."""
        handler = self._handler()
        payload = json.dumps(
            {"response": json.dumps({"message": "done", "updated_config": {}})}
        )

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_not_called()
        handler._send_ok_response.assert_called_once()

    @pytest.mark.parametrize(
        "reply",
        [
            pytest.param(
                {"updated_agent_config": "set it to balanced"},
                id="config as a string",
            ),
            pytest.param(
                {"updated_agent_config": ["balanced"]},
                id="config as a list",
            ),
            pytest.param(
                {"updated_agent_config": {"trading_strategy": ["balanced"]}},
                id="strategy as a list",
            ),
            pytest.param(
                {"updated_agent_config": {"allowed_tools": "one-tool"}},
                id="tools as a string",
            ),
            pytest.param(
                {"updated_agent_config": {"selected_mechs": "0xabc"}},
                id="mechs as a string",
            ),
            pytest.param(
                {"updated_agent_config": {"removed_config_fields": "allowed_tools"}},
                id="removals as a string",
            ),
        ],
    )
    def test_valid_json_of_the_wrong_shape_is_answered_not_raised(
        self, reply: Any
    ) -> None:
        """The update walks this object field by field, so a wrong type raises.

        Valid JSON shaped differently reads no better than prose, and the
        model is free to produce it, so it has to be answered the same way.
        """
        handler = self._handler()
        payload = json.dumps({"response": json.dumps(reply)})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._send_ok_response.assert_not_called()

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({"allowed_tools": [["a"]]}, id="tool name is a list"),
            pytest.param({"allowed_tools": [{"a": 1}]}, id="tool name is a dict"),
        ],
    )
    def test_a_list_of_the_right_type_holding_wrong_items_is_answered(
        self, config: Any
    ) -> None:
        """The container type is right, so checking types cannot catch these.

        Tool names are looked up against a set, so an unhashable item
        raises instead of reading as unknown. Item types that are merely
        surprising, a null or a dict among the mech names, are already
        tolerated and reported back as unrecognised, which is the wanted
        behaviour; it is the raising ones that needed a guard, and
        enumerating them would not be complete.
        """
        handler = self._handler()
        payload = json.dumps({"response": json.dumps({"updated_agent_config": config})})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._send_ok_response.assert_not_called()

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({"fixed_bet_size": "5"}, id="bet size is a quoted number"),
            pytest.param({"fixed_bet_size": [5]}, id="bet size is a list"),
            pytest.param({"max_bet_size": float("inf")}, id="bet size is infinity"),
        ],
    )
    def test_a_numeric_field_of_the_wrong_type_is_answered(self, config: Any) -> None:
        """The update scales these by the token decimals before comparing.

        A quoted number multiplies the string, a list multiplies the list, and
        an infinity cannot be made an integer, so each raises somewhere inside
        the update. Naming the fields one by one would not keep up with the
        config growing, which is why the update is wrapped as a whole.
        """
        handler = self._handler()
        payload = json.dumps({"response": json.dumps({"updated_agent_config": config})})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._send_ok_response.assert_not_called()

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param("[" * 1200 + "]" * 1200, id="deeply nested"),
            pytest.param("1" * 5000, id="integer over the digit limit"),
        ],
    )
    def test_a_reply_that_breaks_the_parser_itself_is_answered(
        self, payload: str
    ) -> None:
        """Neither of these raises JSONDecodeError.

        Deep nesting raises RecursionError, which derives from neither
        ValueError nor TypeError, and an oversized integer literal raises a
        plain ValueError. A crafted reply would otherwise still end the agent.
        """
        handler = self._handler()

        handler._handle_chatui_llm_response(
            self._reply(json.dumps({"response": payload})),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        handler._send_internal_server_error_response.assert_called_once()

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({"fixed_bet_size": True}, id="bet size is a bool"),
            pytest.param({"max_bet_size": float("nan")}, id="bet size is a nan"),
            pytest.param({"behavior": {"tone": "terse"}}, id="behavior is a dict"),
        ],
    )
    def test_values_that_pass_a_type_check_but_are_not_amounts(
        self, config: Any
    ) -> None:
        """A bool is an int in Python, so it reads as one unit of collateral.

        A NaN passes a range comparison without being an amount at all, and
        ``behavior`` was accepted whatever its type.
        """
        handler = self._handler()
        payload = json.dumps({"response": json.dumps({"updated_agent_config": config})})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._send_ok_response.assert_not_called()

    @pytest.mark.parametrize(
        "field",
        ["fixed_bet_size", "max_bet_size"],
    )
    def test_an_amount_beyond_the_float_range_is_answered(self, field: str) -> None:
        """An int is finite however long it is.

        So this is a value the update can read and reject with an issue,
        rather than a reply it cannot read at all. The readability check runs ahead of the handler's own catch, so asking
        whether such an int is finite the way a float is asked would end the
        agent here, before anything could turn it into an issue.

        :param field: the numeric config field carrying the amount.
        """
        handler = self._handler()
        handler._store_chatui_param_to_json = MagicMock()
        payload = json.dumps(
            {"response": json.dumps({"updated_agent_config": {field: 10**400}})}
        )

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_not_called()
        handler._send_ok_response.assert_called_once()
        assert field not in handler._send_ok_response.call_args[0][2]
        handler._store_chatui_param_to_json.assert_not_called()

    def test_a_field_failing_late_leaves_the_earlier_ones_unwritten(self) -> None:
        """The update is applied whole or not at all.

        The model decides this object's shape, so a later field can fail
        after earlier ones have been read. Writing as each field was read
        left the user with a half-changed config and an error, which is
        worse than the error alone.
        """
        handler = self._handler()
        handler._store_trading_strategy = MagicMock()
        handler._store_allowed_tools = MagicMock()
        handler._set_chatui_param = MagicMock()
        # Valid strategy first, then a bet size that raises when scaled.
        handler.get_units_and_decimals = MagicMock(side_effect=RuntimeError("boom"))
        payload = json.dumps(
            {
                "response": json.dumps(
                    {
                        "updated_agent_config": {
                            "trading_strategy": "kelly_criterion",
                            "fixed_bet_size": 5,
                        }
                    }
                )
            }
        )

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._store_trading_strategy.assert_not_called()
        handler._set_chatui_param.assert_not_called()

    def test_the_behaviour_text_waits_for_the_other_writes(self) -> None:
        """The behaviour text is part of the same whole-or-nothing update.

        Applied where it is read, it lands before the amounts it was meant to
        go with, so a write that fails leaves the agent told to behave one way
        about sizes it never took.
        """
        handler = self._handler()
        handler._set_chatui_param = MagicMock(side_effect=RuntimeError("boom"))
        payload = json.dumps(
            {
                "response": json.dumps(
                    {
                        "updated_agent_config": {
                            "behavior": "Trade conservatively.",
                            "fixed_bet_size": 0.05,
                        }
                    }
                )
            }
        )

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler.shared_state.update_agent_behavior.assert_not_called()

    def test_a_removal_field_of_the_wrong_type_does_not_clear_the_setting(
        self,
    ) -> None:
        """This one would pass silently rather than raise.

        The removal check is a membership test, and a bare string satisfies
        it by substring, so ``removed_config_fields: "allowed_tools"`` reads
        as a request to clear the tools. Nothing raises, so a guard around
        the update cannot see it; only checking the type can.
        """
        handler = self._handler()
        handler._store_allowed_tools = MagicMock()  # type: ignore[method-assign]
        payload = json.dumps(
            {
                "response": json.dumps(
                    {"updated_agent_config": {"removed_config_fields": "allowed_tools"}}
                )
            }
        )

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._store_allowed_tools.assert_not_called()

    @pytest.mark.parametrize(
        "reply",
        [
            pytest.param({"message": "done"}, id="no config at all"),
            pytest.param(
                {"message": "done", "updated_agent_config": {}}, id="empty config"
            ),
            pytest.param(
                {
                    "updated_agent_config": {
                        "trading_strategy": "balanced",
                        "allowed_tools": [],
                        "removed_config_fields": [],
                    }
                },
                id="right types throughout",
            ),
        ],
    )
    def test_a_reply_of_the_right_shape_is_not_turned_away(self, reply: Any) -> None:
        """A field being absent is fine; the update defaults each one."""
        handler = self._handler()
        payload = json.dumps({"response": json.dumps(reply)})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_not_called()

    def test_an_llm_error_reply_still_takes_the_error_path(self) -> None:
        """A reported error is not the same as an unreadable one."""
        handler = self._handler()
        payload = json.dumps({"error": "No GENAI_API_KEY set."})

        handler._handle_chatui_llm_response(
            self._reply(payload), MagicMock(), MagicMock(), MagicMock()
        )

        handler._handle_chatui_llm_error.assert_called_once()
        handler._send_internal_server_error_response.assert_not_called()


# The reply logged in #1050: every field the model had no reason to change,
# set to null as the prompt asks.
_ALL_FIELDS_UNCHANGED: Dict[str, Any] = {
    "trading_strategy": None,
    "allowed_tools": None,
    "selected_mechs": None,
    "fixed_bet_size": None,
    "max_bet_size": None,
    "removed_config_fields": [],
    "behavior": None,
}
_NULLABLE_CONFIG_FIELDS = [
    *HttpHandler._LLM_CONFIG_FIELD_TYPES,
    *HttpHandler._LLM_CONFIG_NUMERIC_FIELDS,
]


def _llm_payload(reply: Dict[str, Any]) -> MagicMock:
    """Wrap a model reply the way the genai connection delivers it."""
    message = MagicMock()
    message.payload = json.dumps({"response": json.dumps(reply)})
    return message


def _make_reply_handler(**handler_kwargs: Any) -> Any:
    """Return a handler whose HTTP answers can be inspected."""
    handler = _make_handler(**handler_kwargs)
    handler._send_internal_server_error_response = MagicMock()  # type: ignore[method-assign]
    handler._send_ok_response = MagicMock()  # type: ignore[method-assign]
    handler._send_http_response = MagicMock()  # type: ignore[method-assign]
    return handler


class TestANullFieldMeansLeaveItUnchanged:
    """The prompt tells the model to set every field it is not changing to null."""

    def test_a_reply_changing_nothing_is_answered_with_its_message(self) -> None:
        """All fields null is the normal answer to a question, not a bad reply."""
        handler = _make_reply_handler()
        reply = {"updated_agent_config": _ALL_FIELDS_UNCHANGED, "message": "Hello"}

        handler._handle_chatui_llm_response(
            _llm_payload(reply), MagicMock(), MagicMock(), MagicMock()
        )

        handler._send_internal_server_error_response.assert_not_called()
        body = handler._send_ok_response.call_args[0][2]
        assert body[LLM_MESSAGE_FIELD] == "Hello"
        handler._store_trading_strategy.assert_not_called()
        handler._store_allowed_tools.assert_not_called()
        handler._store_selected_mechs.assert_not_called()

    def test_the_one_field_that_is_set_is_applied(self) -> None:
        """Nulls around a real change must not stop the change."""
        handler = _make_reply_handler()
        strategy = next(iter(AVAILABLE_TRADING_STRATEGIES))
        config = {**_ALL_FIELDS_UNCHANGED, "trading_strategy": strategy}

        handler._handle_chatui_llm_response(
            _llm_payload({"updated_agent_config": config, "message": "Done"}),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        handler._send_internal_server_error_response.assert_not_called()
        handler._store_trading_strategy.assert_called_once_with(strategy)

    @pytest.mark.parametrize("field", _NULLABLE_CONFIG_FIELDS)
    def test_each_field_may_be_null(self, field: str) -> None:
        """No single field turns the reply unreadable by being null."""
        handler = _make_reply_handler()
        strategy = next(iter(AVAILABLE_TRADING_STRATEGIES))
        config = {"trading_strategy": strategy, field: None}
        expects_a_change = field != "trading_strategy"

        handler._handle_chatui_llm_response(
            _llm_payload({"updated_agent_config": config, "message": "Done"}),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        handler._send_internal_server_error_response.assert_not_called()
        handler._send_ok_response.assert_called_once()
        assert handler._store_trading_strategy.called is expects_a_change

    @pytest.mark.parametrize(
        "wrong",
        [
            pytest.param({"trading_strategy": ["balanced"]}, id="strategy as a list"),
            pytest.param({"allowed_tools": "one-tool"}, id="tools as a string"),
            pytest.param(
                {"removed_config_fields": "allowed_tools"}, id="removals as a string"
            ),
            pytest.param({"fixed_bet_size": "5"}, id="bet size as a string"),
            pytest.param({"max_bet_size": True}, id="bet size as a bool"),
            pytest.param({"max_bet_size": False}, id="bet size as a falsy bool"),
            pytest.param({"allowed_tools": ""}, id="tools as an empty string"),
            pytest.param({"trading_strategy": []}, id="strategy as an empty list"),
            pytest.param({"removed_config_fields": ""}, id="removals as empty string"),
        ],
    )
    def test_a_wrong_type_among_nulls_is_still_refused(self, wrong: Any) -> None:
        """Accepting null must not loosen what a set value has to be."""
        handler = _make_reply_handler()
        config = {**_ALL_FIELDS_UNCHANGED, **wrong}

        handler._handle_chatui_llm_response(
            _llm_payload({"updated_agent_config": config, "message": "Done"}),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        handler._send_internal_server_error_response.assert_called_once()
        handler._send_ok_response.assert_not_called()
        handler._store_trading_strategy.assert_not_called()

    def test_null_removals_do_not_clear_a_setting(self) -> None:
        """A null removal list removes nothing, the same as an empty one."""
        handler = _make_reply_handler(
            current_config=ChatuiConfig(allowed_tools=["prediction-online"])
        )

        params, issues = handler._process_updated_agent_config(
            {"removed_config_fields": None}
        )

        assert (params, issues) == ({}, [])
        handler._store_allowed_tools.assert_not_called()


class TestAnEmptyMechPreDepositIsExplained:
    """The user can fix an unfunded agent, so the answer has to say so."""

    @staticmethod
    def _error_payload(**extra: Any) -> MagicMock:
        message = MagicMock()
        message.payload = json.dumps(
            {"error": "mech pre-deposit required: available 0 < required 10", **extra}
        )
        return message

    @pytest.mark.parametrize(
        "on_polymarket,native_token",
        [
            pytest.param(False, "xDAI", id="omen"),
            pytest.param(True, "POL", id="polymarket"),
        ],
    )
    def test_it_names_the_token_to_add(
        self, on_polymarket: bool, native_token: str
    ) -> None:
        """The agent pays for the top-up in the chain's native token."""
        handler = _make_reply_handler()
        handler.context.params.is_running_on_polymarket = on_polymarket
        handler.context.shared_state = {MECH_PRE_DEPOSIT_EOA_SHORT: True}

        handler._handle_chatui_llm_response(
            self._error_payload(code=MECH_DEPOSIT_REQUIRED_CODE),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        args = handler._send_http_response.call_args[0]
        assert f"Add {native_token} to your agent" in args[2]["error"]
        assert args[3] == 402

    @pytest.mark.parametrize(
        "shared_state",
        [
            pytest.param({MECH_PRE_DEPOSIT_EOA_SHORT: False}, id="eoa funded"),
            pytest.param({}, id="no funding check yet"),
        ],
    )
    def test_a_funded_eoa_is_not_asked_for_money(
        self, shared_state: Dict[str, Any]
    ) -> None:
        """The top-up is on its way, or the chain refused it for a moment."""
        handler = _make_reply_handler()
        handler.context.shared_state = shared_state

        handler._handle_chatui_llm_response(
            self._error_payload(code=MECH_DEPOSIT_REQUIRED_CODE),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        args = handler._send_http_response.call_args[0]
        assert "temporarily unavailable" in args[2]["error"]
        assert "Add " not in args[2]["error"]
        assert args[3] == 402

    def test_it_is_not_reported_as_a_server_error(self) -> None:
        """A 500 reads as "the agent is broken", which topping up cannot fix."""
        handler = _make_reply_handler()
        handler._handle_chatui_llm_error = MagicMock()  # type: ignore[method-assign]

        handler._handle_chatui_llm_response(
            self._error_payload(code=MECH_DEPOSIT_REQUIRED_CODE),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        handler._handle_chatui_llm_error.assert_not_called()
        handler._send_internal_server_error_response.assert_not_called()
        handler._send_ok_response.assert_not_called()

    def test_the_balances_reach_the_agent_log(self) -> None:
        """They tell an empty deposit from one held up by requests in flight."""
        handler = _make_reply_handler()
        context = {"balance": 30, "reserved": 25, "available": 5, "required": 10}

        handler._handle_chatui_llm_response(
            self._error_payload(code=MECH_DEPOSIT_REQUIRED_CODE, context=context),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )

        logged = handler.context.logger.warning.call_args[0][0]
        assert str(context) in logged
        assert "available 0 < required 10" in logged

    @pytest.mark.parametrize(
        "extra",
        [
            pytest.param({}, id="no code"),
            pytest.param({"code": None}, id="null code"),
            pytest.param({"code": "something_else"}, id="another code"),
            pytest.param({"code": ""}, id="empty code"),
        ],
    )
    def test_any_other_error_keeps_the_generic_answer(self, extra: Any) -> None:
        """Only the marketplace's own code selects the funding message."""
        handler = _make_reply_handler()
        handler._handle_chatui_llm_error = MagicMock()  # type: ignore[method-assign]

        handler._handle_chatui_llm_response(
            self._error_payload(**extra), MagicMock(), MagicMock(), MagicMock()
        )

        handler._handle_chatui_llm_error.assert_called_once()
        handler._send_http_response.assert_not_called()


# ---------------------------------------------------------------------------
# Mech reports, the typed accept line and mech intents
# ---------------------------------------------------------------------------

THIRD_PARTY = "0x" + "b0" * 20
CHECKSUMMED = "0x" + "B0" * 20
OTHER_MECH = "0x" + "e0" * 20
VALORY_MECH = "0x" + "a0" * 20
OTHER_VALORY_MECH = "0x" + "c0" * 20
NATIVE = "0x" + NATIVE_TYPE_ID
NEVERMINED = "0x803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"
SUBGRAPH = "https://subgraph.example/marketplace-gnosis"
MARKETPLACE_API = "https://marketplace.example/api/erc8004"
CARD_URL = f"{MARKETPLACE_API}/gnosis/ai-agents/3786/agent-card.json"
STATE = ContractApiMessage.Performative.STATE
ERROR = ContractApiMessage.Performative.ERROR
ACCEPT_PHRASE = f"I accept 0.01 xDAI per request for {THIRD_PARTY}"
OFFER = Offer(THIRD_PARTY, NATIVE_RATE, NATIVE, "0.01 xDAI")
ABOVE_CAP = (
    "It charges 0.03 xDAI per request, above the 0.01 xDAI this agent allows, so "
    "it cannot be approved."
)
WHICH_MECH = "I couldn't tell which mech you mean."
NOTHING_TO_LIST = (
    "Your agent has no mechs to list yet. Send a mech's address to see its report."
)
LIST_FOOTER = "Refer to one by its number or its address."
# The checkpoint that starts the current staking epoch.
EPOCH = 1_700_000_000


def _record(address: str = THIRD_PARTY, **overrides: Any) -> Dict[str, Any]:
    """The marketplace subgraph's answer about the mech."""
    mech: Dict[str, Any] = {
        "address": address,
        "maxDeliveryRate": str(NATIVE_RATE),
        "paymentType": NATIVE,
        "receivedRequests": "644",
        "selfDeliveredFromReceived": "635",
        "deliveredByOthersFromReceived": "0",
        "service": {"id": "3786"},
    }
    mech.update(overrides)
    return {"data": {"meches": [mech], "createMeches": []}}


def _card(address: str = THIRD_PARTY) -> Dict[str, Any]:
    """The marketplace agent card of the mech's service."""
    return {
        "name": "Bob Mech",
        "skills": [{"name": "superforcaster"}],
        "provider": None,
        "metadata": {"serviceId": "3786", "mechAddress": f"eip155:100:{address}"},
    }


class _Wire:
    """The HTTP client and ledger connections: records what is sent and lets a test answer."""

    def __init__(self, context: Any) -> None:
        """Route the context's dialogues and callbacks through this wire."""
        self.sent: List[Dict[str, Any]] = []
        self.callbacks: Dict[str, Any] = {}
        context.requests.request_id_to_callback = self.callbacks
        context.http_dialogues.create.side_effect = self._create
        context.contract_api_dialogues.create.side_effect = self._create

    def _create(self, **kwargs: Any) -> Any:
        """Record the request and give it a dialogue with a fresh nonce."""
        nonce = f"nonce-{len(self.sent)}"
        self.sent.append(kwargs)
        dialogue = SimpleNamespace(
            dialogue_label=SimpleNamespace(dialogue_reference=(nonce, ""))
        )
        return SimpleNamespace(**kwargs), dialogue

    def _answer(self, message: Any) -> None:
        """Hand a reply to the callback of the oldest unanswered request."""
        nonce = next(iter(self.callbacks))
        self.callbacks.pop(nonce)(message, None)

    def answer_http(self, body: Any, status: int = 200) -> None:
        """Answer the oldest request with an HTTP response."""
        self._answer(
            SimpleNamespace(status_code=status, body=json.dumps(body).encode())
        )

    def answer_rate(self, rate: Any, performative: Any = STATE) -> None:
        """Answer the oldest request with a contract read of `maxDeliveryRate`."""
        body = {"max_delivery_rate": rate} if rate is not None else {}
        self._answer(
            SimpleNamespace(performative=performative, state=SimpleNamespace(body=body))
        )


def _mech_handler(
    approved: Optional[Dict[str, int]] = None,
    pin: Optional[List[str]] = None,
    discovered: Optional[set] = None,
    valid: Optional[set] = None,
    offers: Tuple[Offer, ...] = (),
    payment_types: Optional[Dict[str, str]] = None,
    discovered_types: Optional[Dict[str, str]] = None,
) -> Tuple[_TestableHttpHandler, _Wire]:
    """A handler whose connections are the wire; offers and approvals behave as in `SharedState`."""
    handler = _make_handler(
        current_config=ChatuiConfig(selected_mechs=pin),
        approved_rates=approved or {},
        available_mechs=discovered,
        valid_mechs=valid,
    )
    context = handler.context
    context.params.mech_chain_id = "gnosis"
    context.params.marketplace_api_url = MARKETPLACE_API
    context.params.default_activity_goal = 10
    context.mechs_subgraph.url = SUBGRAPH
    context.default_ledger_id = "ethereum"
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    handler._send_message = MagicMock()  # type: ignore[method-assign]
    handler._send_ok_response = MagicMock()
    handler.synchronized_data.mech_payment_types = dict(discovered_types or {})
    state = handler.shared_state
    state.read_activity_goal_from_disk.return_value = None
    state.record_mech_offer = partial(SharedState.record_mech_offer, state)
    state.drop_mech_offer = partial(SharedState.drop_mech_offer, state)
    state.record_mech_refusal = partial(SharedState.record_mech_refusal, state)
    for offer in offers:
        state.record_mech_offer(offer)

    def _set(rates: Dict[str, int]) -> None:
        state.approved_mech_rates = dict(rates)
        state.approved_mechs = list(rates)

    state.set_approved_mech_rates = MagicMock(side_effect=_set)
    state.approved_mech_payment_types = dict(payment_types or {})

    def _approve(address: str, rate: int, payment_type: Optional[str] = None) -> None:
        _set({**state.approved_mech_rates, address: rate})
        if payment_type:
            state.approved_mech_payment_types[address] = payment_type

    state.approve_mech = MagicMock(side_effect=_approve)
    return handler, _Wire(context)


def _prompt(handler: _TestableHttpHandler, text: str) -> None:
    """POST a chat message."""
    http_msg = MagicMock()
    http_msg.body = json.dumps({"prompt": text}).encode()
    handler._handle_chatui_prompt(http_msg, MagicMock())


def _reply(handler: _TestableHttpHandler) -> str:
    """The text of the one OK response sent, which carries no config update."""
    handler._send_ok_response.assert_called_once()
    body = handler._send_ok_response.call_args[0][2]
    assert body[UPDATED_PARAMS_FIELD] == {}
    return body[LLM_MESSAGE_FIELD]


def _chat(
    handler: _TestableHttpHandler,
    text: str,
    intent: str = "none",
    address: Optional[str] = None,
    position: Optional[int] = None,
    last_shown: Optional[bool] = None,
) -> None:
    """POST a chat message and answer the config call with this mech intent."""
    _prompt(handler, text)
    _answer_model(handler, _intent(intent, address, position, last_shown))


def _model_prompts(handler: _TestableHttpHandler) -> List[str]:
    """The prompts of the model requests sent, in order."""
    return [
        json.loads(call.kwargs["payload"])["prompt"]
        for call in handler.context.srr_dialogues.create.call_args_list
    ]


def _answer_report(
    wire: _Wire, address: str, live: Any = NATIVE_RATE, **record: Any
) -> None:
    """Answer the mech's record, card and, where read, live rate."""
    wire.answer_http(_record(address, **record))
    if wire.callbacks:
        wire.answer_http(_card(address))
    if wire.callbacks:
        wire.answer_rate(live)


def _report_for(
    handler: _TestableHttpHandler,
    wire: _Wire,
    address: str,
    live: Any = NATIVE_RATE,
    **record: Any,
) -> str:
    """Ask about the mech, answer what is read, and return the reply."""
    _chat(handler, f"tell me about {address}", "ask", address)
    _answer_report(wire, address, live, **record)
    return _reply(handler)


def _shown(
    handler: _TestableHttpHandler,
    wire: _Wire,
    address: str = THIRD_PARTY,
    live: Any = NATIVE_RATE,
    **record: Any,
) -> None:
    """Show the mech's report as an earlier turn of the chat."""
    _report_for(handler, wire, address, live, **record)
    handler._send_ok_response.reset_mock()


def _listed(handler: _TestableHttpHandler) -> None:
    """Show the numbered list as an earlier turn of the chat."""
    _chat(handler, "which mechs can my agent use?", "list")
    handler._send_ok_response.reset_mock()


class TestAskIntent:
    """The ask intent is answered with the mech's report, rendered by the handler."""

    def test_the_report_is_read_and_rendered_by_the_handler(self) -> None:
        """One intent call, two reads, the live rate, then the report; its offer is kept."""
        handler, wire = _mech_handler()
        _prompt(handler, f"what is {CHECKSUMMED}?")
        assert wire.sent == []
        _answer_model(handler, _intent("ask", CHECKSUMMED))
        assert [request["url"] for request in wire.sent] == [SUBGRAPH]
        assert THIRD_PARTY.encode() in wire.sent[0]["body"]
        wire.answer_http(_record())
        assert [request["url"] for request in wire.sent] == [SUBGRAPH, CARD_URL]
        handler._send_ok_response.assert_not_called()
        wire.answer_http(_card())
        assert wire.sent[-1]["callable"] == "get_max_delivery_rate"
        handler._send_ok_response.assert_not_called()
        wire.answer_rate(NATIVE_RATE)
        reply = _reply(handler)
        assert reply.startswith(f"Bob Mech, {THIRD_PARTY}, on Gnosis.<br><br>")
        assert reply.endswith(
            f"<br><br>To approve, reply yes, or reply exactly: {ACCEPT_PHRASE}"
        )
        assert handler.shared_state.mech_offers == {THIRD_PARTY: OFFER}
        assert handler.shared_state.last_shown_mech == THIRD_PARTY
        assert handler._send_message.call_count == 1  # type: ignore[attr-defined]
        handler.shared_state.approve_mech.assert_not_called()

    def test_a_report_without_an_offer_drops_the_one_kept(self) -> None:
        """The last report shown is what an approval can take up."""
        handler, wire = _mech_handler(offers=(OFFER,))
        reply = _report_for(handler, wire, THIRD_PARTY, selfDeliveredFromReceived="0")
        assert reply.endswith("so it cannot be approved.")
        assert handler.shared_state.mech_offers == {}
        assert handler.shared_state.mech_refusals == {THIRD_PARTY: NEVER_DELIVERED}

    def test_an_unreadable_record_is_answered_without_a_card_read(self) -> None:
        """A failed subgraph read ends the report at once; it is still the mech shown."""
        handler, wire = _mech_handler()
        _chat(handler, THIRD_PARTY, "ask", THIRD_PARTY)
        wire.answer_http({"errors": ["down"]}, status=500)
        assert len(wire.sent) == 1
        assert _reply(handler) == (
            f"{THIRD_PARTY} on Gnosis.<br><br>"
            "Its record cannot be read right now; try again later."
        )
        assert handler.shared_state.last_shown_mech == THIRD_PARTY

    def test_an_approved_pinned_mech_shows_the_agents_terms(self) -> None:
        """The accepted rate and the pin come from the agent's state."""
        handler, wire = _mech_handler(
            approved={THIRD_PARTY: NATIVE_RATE}, pin=[CHECKSUMMED]
        )
        reply = _report_for(handler, wire, THIRD_PARTY)
        assert reply.split(PARAGRAPH_BREAK)[-3:] == [
            "Approved at up to 0.01 xDAI per request.",
            "To stop using it, tell me to remove it.",
            "To stop pinning it, tell me to unpin it.",
        ]
        assert handler.shared_state.mech_offers == {}

    def test_a_price_raised_within_the_cap_is_offered_again(self) -> None:
        """The offer is bounded by the asset's cap, not by the rate accepted earlier."""
        handler, wire = _mech_handler(approved={THIRD_PARTY: NATIVE_RATE // 2})
        reply = _report_for(handler, wire, THIRD_PARTY)

        assert accept_line("0.01 xDAI", THIRD_PARTY) in reply.split(PARAGRAPH_BREAK)
        assert handler.shared_state.mech_offers[THIRD_PARTY].rate == NATIVE_RATE

    @pytest.mark.parametrize(
        "listed, live",
        [
            (NATIVE_RATE // 2, NATIVE_RATE),
            (NATIVE_RATE, NATIVE_RATE // 2),
            (NATIVE_RATE, None),
        ],
        ids=["live_higher", "listed_higher", "live_unreadable"],
    )
    def test_a_third_party_report_is_priced_at_the_higher_rate(
        self, listed: int, live: Any
    ) -> None:
        """The offer is the higher of the listed and live rates."""
        handler, wire = _mech_handler()
        reply = _report_for(
            handler, wire, THIRD_PARTY, live, maxDeliveryRate=str(listed)
        )
        assert "Paid with xDAI, up to 0.01 xDAI per request." in reply
        assert handler.shared_state.mech_offers[THIRD_PARTY].rate == NATIVE_RATE

    def test_a_listing_over_the_cap_is_refused_even_when_the_live_rate_is_not(
        self,
    ) -> None:
        """Discovery checks the listing, so a mech listed over the cap is never offered."""
        handler, wire = _mech_handler()
        reply = _report_for(
            handler,
            wire,
            THIRD_PARTY,
            NATIVE_RATE,
            maxDeliveryRate=str(NATIVE_RATE * 3),
        )
        assert reply.endswith(
            "It charges 0.03 xDAI per request, above the 0.01 xDAI this agent "
            "allows, so it cannot be approved."
        )
        assert handler.shared_state.mech_offers == {}

    @pytest.mark.parametrize(
        "listed, live",
        [
            (NATIVE_RATE // 2, NATIVE_RATE),
            (NATIVE_RATE, NATIVE_RATE // 2),
            (NATIVE_RATE, None),
        ],
        ids=["live_higher", "listed_higher", "live_unreadable"],
    )
    def test_an_approval_passes_the_delivery_rate_bound(
        self, listed: int, live: Any
    ) -> None:
        """The approved rate is one both discovery's listing check and the live check accept."""
        handler, wire = _mech_handler()
        reply = _report_for(
            handler, wire, THIRD_PARTY, live, maxDeliveryRate=str(listed)
        )
        handler._send_ok_response.reset_mock()
        _prompt(handler, reply.rsplit("reply exactly: ", 1)[1])
        wire.answer_rate(NATIVE_RATE if live is None else live)
        bound = delivery_rate_bound(
            THIRD_PARTY,
            NATIVE,
            handler.context.params.delivery_rate_caps,
            handler.shared_state.approved_mech_rates,
        )
        assert bound is not None
        assert listed <= bound
        assert live is None or live <= bound

    def test_a_mech_listed_without_a_price_is_not_offered(self) -> None:
        """Discovery skips a mech with no listed rate, so its live rate is not offered."""
        handler, wire = _mech_handler()
        _chat(handler, f"tell me about {THIRD_PARTY}", "ask", THIRD_PARTY)
        wire.answer_http(_record(maxDeliveryRate=None))
        wire.answer_http(_card())
        assert _reply(handler).endswith(PRICE_UNREADABLE)
        assert all(
            request.get("callable") != "get_max_delivery_rate" for request in wire.sent
        )
        assert handler.shared_state.mech_offers == {}

    @pytest.mark.parametrize(
        "record, status",
        [
            ({"data": {"meches": [], "createMeches": []}}, 200),
            ({"errors": ["down"]}, 500),
        ],
        ids=["not_indexed", "unavailable"],
    )
    def test_a_third_party_without_a_record_reads_no_live_rate(
        self, record: Dict[str, Any], status: int
    ) -> None:
        """Without a record there is no price to check."""
        handler, wire = _mech_handler()
        _chat(handler, THIRD_PARTY, "ask", THIRD_PARTY)
        wire.answer_http(record, status=status)
        _reply(handler)
        assert all(
            request.get("callable") != "get_max_delivery_rate" for request in wire.sent
        )

    def test_a_valory_mech_report_reads_no_live_rate(self) -> None:
        """A Valory mech is never offered, so its price is not checked."""
        handler, wire = _mech_handler(discovered={VALORY_MECH})
        _chat(handler, VALORY_MECH, "ask", VALORY_MECH)
        wire.answer_http(_record(VALORY_MECH))
        wire.answer_http(_card(VALORY_MECH))
        assert len(wire.sent) == 2
        _reply(handler)

    def test_a_discovered_valory_mech_gets_the_valory_ending(self) -> None:
        """A Valory mech is never offered; it can be pinned."""
        handler, wire = _mech_handler(discovered={VALORY_MECH})
        lines = _report_for(handler, wire, VALORY_MECH).split(PARAGRAPH_BREAK)
        assert lines[-2].startswith("This is a Valory mech the agent already uses")
        assert lines[-1] == "To add it to your pinned mechs, tell me to pin it."
        assert handler.shared_state.mech_offers == {}

    @pytest.mark.parametrize(
        "text",
        [
            f"compare {THIRD_PARTY} with {OTHER_MECH}",
            f"remove {THIRD_PARTY} {OTHER_MECH}",
        ],
    )
    def test_two_addresses_are_asked_one_at_a_time(self, text: str) -> None:
        """Nothing is read, written or sent to the model."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _prompt(handler, text)
        assert _reply(handler) == "Ask about one mech at a time."
        assert wire.sent == []
        handler._send_message.assert_not_called()  # type: ignore[attr-defined]
        handler.shared_state.approve_mech.assert_not_called()

    def test_the_same_mech_named_twice_is_one_address(self) -> None:
        """A checksummed and a lowercase spelling name the same mech."""
        handler, wire = _mech_handler()
        _chat(handler, f"{CHECKSUMMED} or {THIRD_PARTY}?", "ask", CHECKSUMMED)
        assert [request["url"] for request in wire.sent] == [SUBGRAPH]


class TestAccept:
    """A typed accept repeats an offer shown, and is saved once the live rate allows it."""

    @pytest.mark.parametrize("live", [NATIVE_RATE - 1, NATIVE_RATE, 0])
    def test_a_live_rate_no_higher_than_shown_saves_the_shown_rate(
        self, live: int
    ) -> None:
        """The shown rate is the most the agent pays, whatever the live rate below it."""
        handler, wire = _mech_handler(approved={OTHER_MECH: 1}, offers=(OFFER,))
        _prompt(handler, ACCEPT_PHRASE)
        handler._send_message.assert_not_called()  # type: ignore[attr-defined]
        assert len(wire.sent) == 1
        assert wire.sent[0]["contract_address"] == THIRD_PARTY
        assert wire.sent[0]["callable"] == "get_max_delivery_rate"
        handler.shared_state.approve_mech.assert_not_called()
        wire.answer_rate(live)
        handler.shared_state.approve_mech.assert_called_once_with(
            THIRD_PARTY, NATIVE_RATE, NATIVE
        )
        assert handler.shared_state.approved_mech_rates == {
            OTHER_MECH: 1,
            THIRD_PARTY: NATIVE_RATE,
        }
        assert _reply(handler) == (
            f"Approved {THIRD_PARTY} at up to 0.01 xDAI per request. "
            "Your agent can use it for its next mech requests."
        )
        assert handler.shared_state.mech_offers == {}

    @pytest.mark.parametrize(
        "phrase",
        [
            f"i ACCEPT 0.01   XDAI per request for {CHECKSUMMED}.",
            f"  I accept 0.01 xdai per request for {THIRD_PARTY}!  ",
        ],
    )
    def test_the_phrase_matches_whatever_its_case_spacing_or_checksum(
        self, phrase: str
    ) -> None:
        """The user may retype the line rather than copy it."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _prompt(handler, phrase)
        wire.answer_rate(NATIVE_RATE)
        handler.shared_state.approve_mech.assert_called_once_with(
            THIRD_PARTY, NATIVE_RATE, NATIVE
        )

    def test_a_re_approval_says_again(self) -> None:
        """Accepting a raised price overwrites the accepted rate."""
        handler, wire = _mech_handler(
            approved={THIRD_PARTY: NATIVE_RATE // 2}, offers=(OFFER,)
        )
        _prompt(handler, ACCEPT_PHRASE)
        wire.answer_rate(NATIVE_RATE)
        assert handler.shared_state.approved_mech_rates == {THIRD_PARTY: NATIVE_RATE}
        assert _reply(handler) == (
            f"Approved {THIRD_PARTY} again at up to 0.01 xDAI per request. "
            "Your agent can use it for its next mech requests."
        )

    @pytest.mark.parametrize(
        "stop_flag, target_met, goal, paused",
        [
            (True, True, SimpleNamespace(is_met=True, period_start=EPOCH), True),
            (True, False, SimpleNamespace(is_met=True, period_start=EPOCH), False),
            (False, True, SimpleNamespace(is_met=True, period_start=EPOCH), False),
            (True, True, SimpleNamespace(is_met=False, period_start=EPOCH), False),
            (True, True, SimpleNamespace(is_met=True, period_start=EPOCH - 1), False),
            (True, True, None, False),
        ],
        ids=[
            "paused",
            "activity_target_not_met",
            "stop_disabled",
            "goal_not_met",
            "goal_from_an_earlier_epoch",
            "no_goal",
        ],
    )
    def test_the_approval_says_when_the_mech_is_used(
        self, stop_flag: bool, target_met: bool, goal: Any, paused: bool
    ) -> None:
        """From the next epoch only when the agent skips trading for the rest of this one."""
        handler, wire = _mech_handler(offers=(OFFER,))
        handler.context.params.stop_trading_if_staking_kpi_met = stop_flag
        handler.synchronized_data.db = {
            "is_activity_target_met": target_met,
            "previous_checkpoint": EPOCH,
        }
        handler.shared_state.read_activity_goal_from_disk.return_value = goal
        _prompt(handler, ACCEPT_PHRASE)
        wire.answer_rate(NATIVE_RATE)
        when = (
            "Your agent has met its activity goal for this staking epoch, so it "
            "can use it from the next epoch."
            if paused
            else "Your agent can use it for its next mech requests."
        )
        assert _reply(handler) == (
            f"Approved {THIRD_PARTY} at up to 0.01 xDAI per request. {when}"
        )

    def test_an_approval_before_the_stop_vote_reads_as_trading(self) -> None:
        """Without this period's stop-trading result yet, the reply does not promise a wait."""
        handler, wire = _mech_handler(offers=(OFFER,))
        handler.context.params.stop_trading_if_staking_kpi_met = True
        handler.synchronized_data.db = {"previous_checkpoint": EPOCH}
        handler.shared_state.read_activity_goal_from_disk.return_value = (
            SimpleNamespace(is_met=True, period_start=EPOCH)
        )
        _prompt(handler, ACCEPT_PHRASE)
        wire.answer_rate(NATIVE_RATE)
        assert _reply(handler).endswith(
            "Your agent can use it for its next mech requests."
        )

    def test_a_higher_live_rate_saves_nothing_and_drops_the_offer(self) -> None:
        """What the user saw is not what the mech charges now."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _prompt(handler, ACCEPT_PHRASE)
        wire.answer_rate(NATIVE_RATE + 1)
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler) == (
            f"The listing is out of date: {THIRD_PARTY} now charges "
            "0.010000000000000001 xDAI per request. Ask about this mech again to "
            "see the new terms."
        )
        assert handler.shared_state.mech_offers == {}

    @pytest.mark.parametrize(
        "rate, performative", [(None, STATE), (NATIVE_RATE, ERROR), ("soon", STATE)]
    )
    def test_an_unreadable_live_rate_saves_nothing_and_keeps_the_offer(
        self, rate: Any, performative: Any
    ) -> None:
        """No live rate, no approval; the user can try the same line again."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _prompt(handler, ACCEPT_PHRASE)
        wire.answer_rate(rate, performative)
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler) == (
            f"I can't read what {THIRD_PARTY} charges right now, so nothing was "
            "approved. Try again later."
        )
        assert handler.shared_state.mech_offers == {THIRD_PARTY: OFFER}

    @pytest.mark.parametrize(
        "phrase, address, offers",
        [
            (
                f"I accept 0.02 xDAI per request for {THIRD_PARTY}",
                THIRD_PARTY,
                (OFFER,),
            ),
            (
                f"I accept 0.01 USDC per request for {THIRD_PARTY}",
                THIRD_PARTY,
                (OFFER,),
            ),
            (f"I accept 0.01 per request for {THIRD_PARTY}", THIRD_PARTY, (OFFER,)),
            (ACCEPT_PHRASE, THIRD_PARTY, ()),
            (f"I accept 0.01 xDAI per request for {OTHER_MECH}", OTHER_MECH, (OFFER,)),
        ],
    )
    def test_a_phrase_without_a_matching_offer_reads_and_saves_nothing(
        self, phrase: str, address: str, offers: Tuple[Offer, ...]
    ) -> None:
        """A wrong price, or a mech never offered, is refused before any read."""
        handler, wire = _mech_handler(offers=offers)
        _prompt(handler, phrase)
        assert wire.sent == []
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler) == (
            f"There is no offer at that price for {address}. "
            "Ask about the mech to see its current terms."
        )

    def test_an_offer_shown_by_a_report_can_be_accepted(self) -> None:
        """The line the report prints is the line that approves."""
        handler, wire = _mech_handler()
        reply = _report_for(handler, wire, THIRD_PARTY)
        phrase = reply.rsplit("reply exactly: ", 1)[1]
        handler._send_ok_response.reset_mock()
        _prompt(handler, phrase)
        wire.answer_rate(NATIVE_RATE)
        handler.shared_state.approve_mech.assert_called_once_with(
            THIRD_PARTY, NATIVE_RATE, NATIVE
        )
        assert handler._send_message.call_count == 1  # type: ignore[attr-defined]


class TestApproveIntent:
    """Approving takes an offer a report showed, at its price, once the live rate allows it."""

    @pytest.mark.parametrize("live", [NATIVE_RATE - 1, NATIVE_RATE])
    def test_approving_the_mech_just_shown_takes_its_offer(self, live: int) -> None:
        """The pronoun is the last mech shown; the shown rate is saved after the live read."""
        handler, wire = _mech_handler()
        _shown(handler, wire)
        _chat(handler, "let's use it", "approve", last_shown=True)
        assert wire.sent[-1]["callable"] == "get_max_delivery_rate"
        assert wire.sent[-1]["contract_address"] == THIRD_PARTY
        handler.shared_state.approve_mech.assert_not_called()
        wire.answer_rate(live)
        handler.shared_state.approve_mech.assert_called_once_with(
            THIRD_PARTY, NATIVE_RATE, NATIVE
        )
        assert _reply(handler) == (
            f"Approved {THIRD_PARTY} at up to 0.01 xDAI per request. "
            "Your agent can use it for its next mech requests."
        )

    def test_a_higher_live_rate_approves_nothing(self) -> None:
        """What the user saw is not what the mech charges now."""
        handler, wire = _mech_handler()
        _shown(handler, wire)
        _chat(handler, "yes", "approve", last_shown=True)
        wire.answer_rate(NATIVE_RATE + 1)
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler).startswith("The listing is out of date")

    def test_approving_a_mech_never_shown_shows_its_report_first(self) -> None:
        """No offer was shown, so the report comes first and ends with how to approve."""
        handler, wire = _mech_handler()
        _chat(handler, f"approve {THIRD_PARTY}", "approve", THIRD_PARTY)
        assert [request["url"] for request in wire.sent] == [SUBGRAPH]
        _answer_report(wire, THIRD_PARTY)
        assert _reply(handler).endswith(accept_line("0.01 xDAI", THIRD_PARTY))
        handler.shared_state.approve_mech.assert_not_called()
        assert handler.shared_state.mech_offers == {THIRD_PARTY: OFFER}

    @pytest.mark.parametrize(
        "record, live, reason",
        [
            ({"selfDeliveredFromReceived": "0"}, NATIVE_RATE, NEVER_DELIVERED),
            ({"maxDeliveryRate": str(NATIVE_RATE * 3)}, NATIVE_RATE * 3, ABOVE_CAP),
        ],
        ids=["never_delivered", "above_cap"],
    )
    def test_approving_after_a_refusal_repeats_the_reason(
        self, record: Dict[str, Any], live: int, reason: str
    ) -> None:
        """No read, nothing approved, and the refusal the report gave."""
        handler, wire = _mech_handler()
        _shown(handler, wire, THIRD_PARTY, live, **record)
        sent = len(wire.sent)
        _chat(handler, "yes", "approve", last_shown=True)
        assert len(wire.sent) == sent
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler) == (
            f"There is nothing to accept for {THIRD_PARTY}. {reason}"
        )

    @pytest.mark.parametrize("address", [THIRD_PARTY, None], ids=["pronoun", "none"])
    def test_a_reference_with_nothing_shown_asks_which_mech(
        self, address: Optional[str]
    ) -> None:
        """Nothing is read or approved; the list is offered to pick from."""
        handler, wire = _mech_handler(discovered={VALORY_MECH}, offers=(OFFER,))
        _chat(handler, "let's use it", "approve", address)
        assert _reply(handler) == PARAGRAPH_BREAK.join(
            [
                WHICH_MECH,
                f"Mechs your agent can use:<br>1. {VALORY_MECH}, Valory",
                LIST_FOOTER,
            ]
        )
        assert wire.sent == []
        handler.shared_state.approve_mech.assert_not_called()
        assert handler.shared_state.last_mech_list == [VALORY_MECH]

    def test_with_no_mechs_to_list_it_asks_for_an_address(self) -> None:
        """An empty list is not shown; the user is asked for an address."""
        handler, _ = _mech_handler()
        _chat(handler, "let's use it", "approve")
        assert _reply(handler) == PARAGRAPH_BREAK.join([WHICH_MECH, NOTHING_TO_LIST])


class TestListIntent:
    """The list intent is answered with a numbered list the handler builds and keeps."""

    def test_valory_then_approved_mechs_are_numbered_with_their_terms(self) -> None:
        """Valory mechs in address order with their payment method, then approvals in order."""
        handler, wire = _mech_handler(
            discovered={OTHER_VALORY_MECH, VALORY_MECH},
            approved={THIRD_PARTY: NATIVE_RATE, OTHER_MECH: 5},
            payment_types={THIRD_PARTY: NATIVE},
            discovered_types={VALORY_MECH: NATIVE},
            pin=[CHECKSUMMED],
        )
        _chat(handler, "which mechs can my agent use?", "list")
        assert _reply(handler) == PARAGRAPH_BREAK.join(
            [
                "Mechs your agent can use:<br>"
                f"1. {VALORY_MECH}, Valory, paid with xDAI<br>"
                f"2. {OTHER_VALORY_MECH}, Valory<br>"
                f"3. {THIRD_PARTY}, approved, up to 0.01 xDAI per request, pinned<br>"
                f"4. {OTHER_MECH}, approved; ask about it to see its price",
                LIST_FOOTER,
            ]
        )
        assert handler.shared_state.last_mech_list == [
            VALORY_MECH,
            OTHER_VALORY_MECH,
            THIRD_PARTY,
            OTHER_MECH,
        ]
        assert wire.sent == []
        assert handler._send_message.call_count == 1  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "kind, terms",
        [
            (NATIVE, "Valory, paid with xDAI"),
            (NEVERMINED, "Valory, paid with a Nevermined subscription"),
            ("unknown", "Valory, paid with an unrecognised payment method"),
        ],
        ids=["native", "nevermined", "unknown"],
    )
    def test_a_valory_mech_shows_its_discovered_payment_method(
        self, kind: str, terms: str
    ) -> None:
        """The method comes from what mech-interact discovered, with no new read."""
        handler, wire = _mech_handler(
            discovered={VALORY_MECH}, discovered_types={VALORY_MECH: kind}
        )
        _chat(handler, "list the mechs", "list")
        assert f"1. {VALORY_MECH}, {terms}" in _reply(handler)
        assert wire.sent == []

    def test_a_mech_both_discovered_and_approved_is_listed_once(self) -> None:
        """It is listed among the approvals, at its accepted price."""
        handler, _ = _mech_handler(
            discovered={THIRD_PARTY},
            approved={THIRD_PARTY: NATIVE_RATE},
            payment_types={THIRD_PARTY: NATIVE},
        )
        _chat(handler, "list the mechs", "list")
        assert handler.shared_state.last_mech_list == [THIRD_PARTY]

    def test_nothing_to_list_says_so(self) -> None:
        """An empty list is said plainly and kept empty."""
        handler, _ = _mech_handler()
        handler.shared_state.last_mech_list = [THIRD_PARTY]
        _chat(handler, "list the mechs", "list")
        assert _reply(handler) == NOTHING_TO_LIST
        assert handler.shared_state.last_mech_list == []

    def test_an_accept_records_the_payment_type_for_the_list(self) -> None:
        """What the report offered in is what the list shows later."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _prompt(handler, ACCEPT_PHRASE)
        wire.answer_rate(NATIVE_RATE)
        handler._send_ok_response.reset_mock()
        _chat(handler, "list the mechs", "list")
        assert f"1. {THIRD_PARTY}, approved, up to 0.01 xDAI per request" in _reply(
            handler
        )


class TestPositionReferences:
    """A position resolves to the address at that place in the last list shown."""

    def test_a_listed_position_is_reported(self) -> None:
        """The second item of the list is the mech read and shown."""
        handler, wire = _mech_handler(
            discovered={VALORY_MECH}, approved={THIRD_PARTY: NATIVE_RATE}
        )
        _listed(handler)
        _chat(handler, "tell me about the second one", "ask", position=2)
        assert THIRD_PARTY.encode() in wire.sent[0]["body"]
        _answer_report(wire, THIRD_PARTY)
        assert _reply(handler).startswith(f"Bob Mech, {THIRD_PARTY}, on Gnosis.")
        assert handler.shared_state.last_shown_mech == THIRD_PARTY

    def test_approving_a_listed_mech_with_no_offer_shows_its_report_first(
        self,
    ) -> None:
        """No report with an offer was shown for it, so nothing is approved yet."""
        handler, wire = _mech_handler(discovered={VALORY_MECH, OTHER_VALORY_MECH})
        _listed(handler)
        _chat(handler, "approve the second one", "approve", position=2)
        assert OTHER_VALORY_MECH.encode() in wire.sent[0]["body"]
        handler.shared_state.approve_mech.assert_not_called()

    @pytest.mark.parametrize(
        "address, position",
        [(None, None), (None, 2), (None, 0), (OTHER_MECH, None), (VALORY_MECH, 1)],
        ids=[
            "described_otherwise",
            "past_the_end",
            "position_zero",
            "address_not_named",
            "address_named_nowhere",
        ],
    )
    def test_an_unplaceable_reference_shows_the_list_again(
        self, address: Optional[str], position: Optional[int]
    ) -> None:
        """The list is shown again to pick a number from; nothing is read."""
        handler, wire = _mech_handler(discovered={VALORY_MECH})
        _listed(handler)
        handler.shared_state.last_mech_list = []
        _chat(handler, "the cheap one", "ask", address, position)
        assert _reply(handler).startswith(WHICH_MECH + PARAGRAPH_BREAK)
        assert f"1. {VALORY_MECH}, Valory" in _reply(handler)
        assert handler.shared_state.last_mech_list == [VALORY_MECH]
        assert wire.sent == []


class TestRemoveIntent:
    """Removing drops an approval and any pin on it."""

    def test_the_mech_just_shown_is_removed_and_unpinned(self) -> None:
        """The record and the pin forget the mech; other pins stay."""
        handler, _ = _mech_handler(
            approved={THIRD_PARTY: 1, OTHER_MECH: 2}, pin=[VALORY_MECH, THIRD_PARTY]
        )
        handler.shared_state.last_shown_mech = THIRD_PARTY
        _chat(handler, "stop using that one", "remove", last_shown=True)
        handler.shared_state.set_approved_mech_rates.assert_called_once_with(
            {OTHER_MECH: 2}
        )
        handler._store_selected_mechs.assert_called_once_with([VALORY_MECH])  # type: ignore[attr-defined]
        assert _reply(handler) == (
            f"Removed {THIRD_PARTY}. No new requests go to it from the next cycle; "
            "a request already sent to it can still be answered and bet on. "
            f"It was pinned, so {THIRD_PARTY} is unpinned; still pinned: {VALORY_MECH}."
        )

    def test_a_mech_never_approved_is_said_so(self) -> None:
        """Nothing is written."""
        handler, _ = _mech_handler(approved={OTHER_MECH: 2})
        _chat(handler, f"stop using {CHECKSUMMED}", "remove", CHECKSUMMED)
        handler.shared_state.set_approved_mech_rates.assert_not_called()
        assert _reply(handler) == (
            f"{THIRD_PARTY} is not approved, so there is nothing to remove."
        )


class TestTypedRemove:
    """`remove <address>` works without the model, so an approval can always be revoked."""

    @pytest.mark.parametrize(
        "text", [f"remove {CHECKSUMMED}", f"  Remove {THIRD_PARTY}. "]
    )
    def test_it_removes_without_a_model_call(self, text: str) -> None:
        """The approval and its pin go, and the model is not asked."""
        handler, _ = _mech_handler(approved={THIRD_PARTY: 1}, pin=[THIRD_PARTY])
        _prompt(handler, text)
        handler._send_message.assert_not_called()  # type: ignore[attr-defined]
        assert handler.shared_state.approved_mech_rates == {}
        assert _reply(handler).startswith(f"Removed {THIRD_PARTY}.")

    def test_a_mech_never_approved_is_said_so(self) -> None:
        """Nothing is written."""
        handler, _ = _mech_handler(approved={OTHER_MECH: 2})
        _prompt(handler, f"remove {THIRD_PARTY}")
        handler.shared_state.set_approved_mech_rates.assert_not_called()
        assert _reply(handler) == (
            f"{THIRD_PARTY} is not approved, so there is nothing to remove."
        )


class TestTheMechJustShownExpires:
    """A report counts as the mech just shown only when it was the reply right before."""

    @pytest.mark.parametrize(
        "between",
        [
            ("which mechs can my agent use?", "list"),
            ("stop using it", "remove"),
            ("go risky", "none"),
        ],
        ids=["list", "remove", "config"],
    )
    def test_yes_after_another_reply_approves_nothing(
        self, between: Tuple[str, str]
    ) -> None:
        """The report on screen is gone, so "yes" asks which mech instead of approving."""
        handler, wire = _mech_handler(approved={OTHER_MECH: 1})
        _shown(handler, wire)
        handler._send_ok_response.reset_mock()
        text, intent = between
        _chat(handler, text, intent, last_shown=intent == "remove" or None)
        handler._send_ok_response.reset_mock()
        _chat(handler, "yes", "approve", last_shown=True)
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler).startswith("I couldn't tell which mech you mean.")


class TestPinIntent:
    """Pinning and unpinning change the pin list for mechs the agent may use."""

    @pytest.mark.parametrize(
        "address, discovered, approved, pins, stored",
        [
            (VALORY_MECH, {VALORY_MECH}, {}, None, [VALORY_MECH]),
            (THIRD_PARTY, None, {THIRD_PARTY: 1}, None, [THIRD_PARTY]),
            (
                THIRD_PARTY,
                {VALORY_MECH},
                {THIRD_PARTY: 1},
                [VALORY_MECH],
                [VALORY_MECH, THIRD_PARTY],
            ),
        ],
    )
    def test_the_mech_just_shown_is_pinned_when_the_agent_may_use_it(
        self,
        address: str,
        discovered: Optional[set],
        approved: Dict[str, int],
        pins: Optional[List[str]],
        stored: List[str],
    ) -> None:
        """A discovered Valory mech or an approved one joins the pin list."""
        handler, _ = _mech_handler(approved=approved, pin=pins, discovered=discovered)
        handler.shared_state.last_shown_mech = address
        _chat(handler, "only use this one from now on", "pin", last_shown=True)
        handler._store_selected_mechs.assert_called_once_with(stored)  # type: ignore[attr-defined]
        assert _reply(handler) == (
            f"Pinned {address}. Mech requests now go only to your pinned mechs: "
            f"{', '.join(stored)}."
        )

    @pytest.mark.parametrize(
        "discovered, valid, approved",
        [
            (None, None, {}),
            ({THIRD_PARTY}, {VALORY_MECH}, {}),
            ({VALORY_MECH}, None, {OTHER_MECH: 1}),
        ],
    )
    def test_any_other_mech_is_not_pinned(
        self, discovered: Optional[set], valid: Optional[set], approved: Dict[str, int]
    ) -> None:
        """Unknown, discovered but not valid, or not approved: refused."""
        handler, _ = _mech_handler(
            approved=approved, discovered=discovered, valid=valid
        )
        _chat(handler, f"pin {THIRD_PARTY}", "pin", THIRD_PARTY)
        handler._store_selected_mechs.assert_not_called()  # type: ignore[attr-defined]
        assert _reply(handler) == (
            "I can only pin a Valory mech the agent uses or a mech you approved."
        )

    def test_an_already_pinned_mech_is_not_pinned_twice(self) -> None:
        """The list is left as it is."""
        handler, _ = _mech_handler(discovered={VALORY_MECH}, pin=[VALORY_MECH])
        _chat(handler, f"pin {VALORY_MECH}", "pin", VALORY_MECH)
        handler._store_selected_mechs.assert_not_called()  # type: ignore[attr-defined]
        assert _reply(handler) == (
            f"Pinned {VALORY_MECH}. Mech requests now go only to your pinned mechs: "
            f"{VALORY_MECH}."
        )

    def test_unpinning_one_of_several_keeps_the_rest(self) -> None:
        """Mech selection stays pinned to the others."""
        handler, _ = _mech_handler(pin=[VALORY_MECH, THIRD_PARTY])
        _chat(handler, f"unpin {CHECKSUMMED}", "unpin", CHECKSUMMED)
        handler._store_selected_mechs.assert_called_once_with([VALORY_MECH])  # type: ignore[attr-defined]
        assert (
            _reply(handler) == f"Unpinned {THIRD_PARTY}. Still pinned: {VALORY_MECH}."
        )

    def test_unpinning_the_last_pin_restores_normal_selection(self) -> None:
        """An empty pin list is stored as none."""
        handler, _ = _mech_handler(pin=[THIRD_PARTY])
        _chat(handler, f"unpin {THIRD_PARTY}", "unpin", THIRD_PARTY)
        handler._store_selected_mechs.assert_called_once_with(None)  # type: ignore[attr-defined]
        assert _reply(handler) == (
            f"Unpinned {THIRD_PARTY}. Mech selection is back to normal."
        )

    def test_unpinning_a_mech_not_pinned_says_so(self) -> None:
        """Nothing is written."""
        handler, _ = _mech_handler(pin=[VALORY_MECH])
        _chat(handler, f"unpin {THIRD_PARTY}", "unpin", THIRD_PARTY)
        handler._store_selected_mechs.assert_not_called()  # type: ignore[attr-defined]
        assert _reply(handler) == f"{THIRD_PARTY} is not pinned."


class TestAnAcceptAfterARefusal:
    """An accept for a mech whose last report made no offer is answered with why."""

    @pytest.mark.parametrize(
        "record, live, reason",
        [
            ({"selfDeliveredFromReceived": "0"}, NATIVE_RATE, NEVER_DELIVERED),
            ({"maxDeliveryRate": str(NATIVE_RATE * 3)}, NATIVE_RATE * 3, ABOVE_CAP),
        ],
        ids=["never_delivered", "above_cap"],
    )
    def test_the_reply_gives_the_report_reason(
        self, record: Dict[str, Any], live: int, reason: str
    ) -> None:
        """No read, nothing approved, and the refusal the report gave."""
        handler, wire = _mech_handler()
        _shown(handler, wire, THIRD_PARTY, live, **record)
        _prompt(handler, f"I accept 0.03 xDAI per request for {THIRD_PARTY}")
        assert len(wire.sent) == 3
        handler.shared_state.approve_mech.assert_not_called()
        assert (
            _reply(handler) == f"There is nothing to accept for {THIRD_PARTY}. {reason}"
        )


class TestAnUnreadableAccept:
    """A message that starts like an accept but doesn't parse gets a fixed answer."""

    @pytest.mark.parametrize(
        "text",
        [
            "I accept",
            "i accept 0.01 xDAI for " + THIRD_PARTY,
            f"I accept 0.01 xDAI per request for {THIRD_PARTY[:-1]}",
            f"I accept 0.01 xDAI per request for {THIRD_PARTY} and {OTHER_MECH}",
        ],
        ids=["bare", "missing_per_request", "short_address", "two_addresses"],
    )
    def test_it_is_not_sent_to_the_model(self, text: str) -> None:
        """Nothing is read, approved or sent to the model."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _prompt(handler, text)
        assert _reply(handler).startswith("I couldn't read that.")
        assert wire.sent == []
        handler._send_message.assert_not_called()  # type: ignore[attr-defined]
        handler.shared_state.approve_mech.assert_not_called()
        assert handler.shared_state.mech_offers == {THIRD_PARTY: OFFER}


class TestTheConfigPromptCarriesNoMechState:
    """The model gets no mech reports, chat addresses or offers."""

    def test_no_address_card_text_or_offer_from_the_chat_reaches_the_model(
        self,
    ) -> None:
        """Which mech was shown, the list and the offer stay in code."""
        handler, wire = _mech_handler(discovered={VALORY_MECH, OTHER_VALORY_MECH})
        _listed(handler)
        _shown(handler, wire)
        _prompt(handler, "let's use it")
        prompt = _model_prompts(handler)[-1]
        assert 'User prompt: "let\'s use it"' in prompt
        for text in (THIRD_PARTY, "Bob Mech", "superforcaster", "3786", "0.01 xDAI"):
            assert text not in prompt


class TestAReplyWithAMechIntent:
    """A reply whose mech intent resolves is carried out in code; its message and config are not used."""

    CONFIG = {
        "trading_strategy": "kelly_criterion",
        "fixed_bet_size": 0.5,
        "behavior": "Trades more.",
    }

    def test_a_mech_intent_with_a_config_change_does_neither(self) -> None:
        """Nothing is stored, no mech action runs, and the user is told to ask separately."""
        handler, _ = _mech_handler(discovered={VALORY_MECH})
        _prompt(handler, "show me the mechs and go risky")
        _answer_model(handler, _config_reply({"intent": "list"}, self.CONFIG))
        handler._store_trading_strategy.assert_not_called()  # type: ignore[attr-defined]
        handler._store_chatui_param_to_json.assert_not_called()
        handler.shared_state.update_agent_behavior.assert_not_called()
        assert _reply(handler) == ONE_REQUEST_AT_A_TIME
        assert handler.shared_state.last_mech_list == []
        handler.context.logger.warning.assert_called()

    @pytest.mark.parametrize(
        "reading", [{"intent": "delete", "address": THIRD_PARTY}, "approve"]
    )
    def test_an_unreadable_mech_intent_is_logged_and_answered_as_config(
        self, reading: Any
    ) -> None:
        """A garbled intent is not acted on, and the log shows it."""
        handler, _ = _mech_handler()
        _prompt(handler, "hello")
        _answer_model(handler, _config_reply(reading))
        assert _reply(handler) == MODEL_MESSAGE
        assert any(
            "unreadable mech intent" in str(call)
            for call in handler.context.logger.warning.call_args_list
        )

    def test_a_behaviour_line_alone_is_not_a_config_change(self) -> None:
        """The model's behaviour summary does not block a mech intent."""
        handler, _ = _mech_handler(discovered={VALORY_MECH})
        _prompt(handler, "show me the mechs")
        _answer_model(
            handler,
            _config_reply(
                {"intent": "list"}, {"behavior": "Trades.", "allowed_tools": []}
            ),
        )
        assert _reply(handler).startswith(
            f"Mechs your agent can use:<br>1. {VALORY_MECH}"
        )

    def test_the_same_config_update_without_an_intent_is_applied(self) -> None:
        """The update above is one the config chat would otherwise apply."""
        handler, _ = _mech_handler(discovered={VALORY_MECH})
        _prompt(handler, "go risky")
        _answer_model(handler, _config_reply(None, self.CONFIG))
        handler._store_trading_strategy.assert_called_once_with("kelly_criterion")  # type: ignore[attr-defined]

    def test_an_unplaceable_reference_ignores_the_message(self) -> None:
        """The handler asks which mech; the model's text is not shown."""
        handler, _ = _mech_handler()
        _chat(handler, "approve the cheap one", "approve")
        assert _reply(handler) == PARAGRAPH_BREAK.join([WHICH_MECH, NOTHING_TO_LIST])
        handler._send_ok_response.assert_called_once()


class TestAMessageWithNoMechIntent:
    """A reply with no mech intent is handled exactly as the config chat handles it."""

    @pytest.mark.parametrize("text", ["turn trading off for today", "yes"])
    def test_it_is_one_config_call_and_approves_nothing(self, text: str) -> None:
        """One model call; the model's message is the answer; no mech is read or approved."""
        handler, wire = _mech_handler(offers=(OFFER,))
        _chat(handler, text, "none")
        (prompt,) = _model_prompts(handler)
        assert f'User prompt: "{text}"' in prompt
        assert "Trading strategy" in prompt
        assert _reply(handler) == MODEL_MESSAGE
        assert wire.sent == []
        handler.shared_state.approve_mech.assert_not_called()
        assert handler.shared_state.mech_offers == {THIRD_PARTY: OFFER}

    @pytest.mark.parametrize(
        "mech_intent",
        [
            None,
            "approve",
            5,
            ["approve", THIRD_PARTY],
            {},
            {"address": THIRD_PARTY},
            {"intent": "delete", "address": THIRD_PARTY},
            {"intent": None, "address": THIRD_PARTY},
            {"intent": "APPROVE", "address": THIRD_PARTY},
            {"intent": "none", "address": THIRD_PARTY},
        ],
        ids=[
            "null",
            "string",
            "number",
            "list",
            "empty",
            "missing_intent",
            "unknown_intent",
            "null_intent",
            "wrong_case",
            "none_intent",
        ],
    )
    def test_an_invalid_mech_intent_is_a_normal_config_reply(
        self, mech_intent: Any
    ) -> None:
        """Nothing in the mech flow runs on a mech intent that can't be read."""
        handler, wire = _mech_handler(offers=(OFFER,))
        handler.shared_state.last_shown_mech = THIRD_PARTY
        _prompt(handler, "let's use it")
        _answer_model(handler, _config_reply(mech_intent))
        assert _reply(handler) == MODEL_MESSAGE
        assert wire.sent == []
        handler.shared_state.approve_mech.assert_not_called()

    def test_a_reply_without_the_field_is_a_normal_config_reply(self) -> None:
        """An older reply shape still reads; whatever it says, nothing is approved."""
        handler, _ = _mech_handler(offers=(OFFER,))
        _prompt(handler, "approve it")
        reply = {"message": "ok", "mech_action": {"confirm_approval": True}}
        _answer_model(handler, json.dumps({"response": json.dumps(reply)}))
        handler.shared_state.approve_mech.assert_not_called()
        assert _reply(handler) == "ok"

    @pytest.mark.parametrize(
        "approved, payment_types, listed",
        [
            (
                {THIRD_PARTY: NATIVE_RATE},
                {THIRD_PARTY: NATIVE},
                f"{THIRD_PARTY}, up to 0.01 xDAI per request",
            ),
            (
                {THIRD_PARTY: NATIVE_RATE},
                {},
                f"{THIRD_PARTY} (send its address to see its price)",
            ),
            ({}, {}, "None"),
        ],
        ids=["priced", "no_payment_type", "none"],
    )
    def test_the_prompt_lists_approved_mechs_apart_from_pins(
        self, approved: Dict[str, int], payment_types: Dict[str, str], listed: str
    ) -> None:
        """Approved mechs and pinned mechs are two labelled lines."""
        handler, _ = _mech_handler(
            approved=approved, payment_types=payment_types, pin=[VALORY_MECH]
        )
        _prompt(handler, "how do pins work?")
        prompt = _model_prompts(handler)[-1]
        assert f"- Approved third-party mechs: {listed}\n" in prompt
        assert f"- Pinned mechs: {VALORY_MECH}\n" in prompt
        assert "Selected mechs" not in prompt


class TestPinnableMechs:
    """Pins accept discovered Valory mechs and approved mechs."""

    def test_approved_mechs_are_pinnable_before_discovery(self) -> None:
        """An approval counts at once, before mech-interact lists the mech."""
        handler = _make_handler(
            available_mechs={VALORY_MECH}, approved_mechs=[THIRD_PARTY]
        )
        assert handler._get_available_valid_mechs() == {VALORY_MECH, THIRD_PARTY}
        params, issues = handler._process_updated_agent_config(
            {"selected_mechs": [THIRD_PARTY]}
        )
        assert issues == []
        assert params[SELECTED_MECHS_FIELD] == [THIRD_PARTY]

    def test_a_just_removed_mech_is_not_pinnable(self) -> None:
        """Still discovered this period but no longer approved: rejected."""
        handler = _make_handler(
            available_mechs={VALORY_MECH, THIRD_PARTY},
            valid_mechs={VALORY_MECH},
            approved_mechs=[],
        )
        assert handler._get_available_valid_mechs() == {VALORY_MECH}
