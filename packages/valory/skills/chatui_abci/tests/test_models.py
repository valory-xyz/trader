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

"""Tests for packages/valory/skills/chatui_abci/models.py -- SharedState._ensure_chatui_store."""

from typing import Any, Dict
from unittest.mock import MagicMock

from packages.valory.skills.chatui_abci.models import ChatuiConfig, SharedState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_TRADING_STRATEGY = "kelly_criterion_no_conf"
DEFAULT_MAX_BET_SIZE = 2_000_000_000_000_000_000
DEFAULT_MIN_BET_SIZE = 10_000_000_000_000_000


class _TestableSharedState(SharedState):
    """Subclass that exposes a writable context for testing.

    SharedState inherits context as a read-only property from the AEA
    framework; this subclass overrides it with a plain attribute so tests
    can inject a MagicMock without touching the framework.
    """

    context = None  # type: ignore[assignment]  # shadows the parent property


def _make_shared_state(store: Dict[str, Any]) -> _TestableSharedState:
    """Return a _TestableSharedState wired with a mocked context.

    Bypasses the AEA framework by replacing only the attributes that
    _ensure_chatui_store() actually reads.
    """
    state = object.__new__(_TestableSharedState)
    state._chatui_config = None

    params = MagicMock()
    params.trading_strategy = DEFAULT_TRADING_STRATEGY
    params.strategies_kwargs = {
        "default_max_bet_size": DEFAULT_MAX_BET_SIZE,
        "absolute_min_bet_size": DEFAULT_MIN_BET_SIZE,
    }

    context = MagicMock()
    context.params = params
    state.context = context

    state._get_current_json_store = MagicMock(return_value=dict(store))
    state._set_json_store = MagicMock()

    return state


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestAllowedToolsMigration:
    """Tests for the mech_tool -> allowed_tools migration logic."""

    def test_legacy_mech_tool_migrated_to_single_element_list(self) -> None:
        """A store with only mech_tool must seed allowed_tools as a one-element list."""
        state = _make_shared_state({"mech_tool": "prediction-online"})
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools == ["prediction-online"]

    def test_legacy_mech_tool_null_yields_none(self) -> None:
        """A store with mech_tool=null must yield allowed_tools=None (not [None])."""
        state = _make_shared_state({"mech_tool": None})
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools is None

    def test_migration_persists_without_mech_tool_key(self) -> None:
        """After migration, the persisted store must contain allowed_tools and no mech_tool."""
        state = _make_shared_state({"mech_tool": "prediction-online"})
        state._ensure_chatui_store()

        persisted: dict = state._set_json_store.call_args[0][0]
        assert "allowed_tools" in persisted
        assert "mech_tool" not in persisted
        assert persisted["allowed_tools"] == ["prediction-online"]

    def test_existing_allowed_tools_list_is_respected(self) -> None:
        """A store already containing allowed_tools must not be re-migrated."""
        state = _make_shared_state({"allowed_tools": ["tool-a", "tool-b"]})
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools == ["tool-a", "tool-b"]

    def test_existing_allowed_tools_null_is_respected(self) -> None:
        """allowed_tools=null (key present) must stay None and not re-seed from mech_tool."""
        state = _make_shared_state({"allowed_tools": None})
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools is None

    def test_leftover_mech_tool_key_dropped_when_allowed_tools_present(self) -> None:
        """If both keys coexist, mech_tool must be dropped and allowed_tools wins."""
        state = _make_shared_state(
            {"allowed_tools": ["tool-a"], "mech_tool": "old-tool"}
        )
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools == ["tool-a"]
        persisted: dict = state._set_json_store.call_args[0][0]
        assert "mech_tool" not in persisted

    def test_migration_fires_only_once(self) -> None:
        """Calling _ensure_chatui_store twice must not re-read or re-persist the store."""
        state = _make_shared_state({"mech_tool": "prediction-online"})
        state._ensure_chatui_store()
        state._ensure_chatui_store()

        assert state._get_current_json_store.call_count == 1
        assert state._set_json_store.call_count == 1

    def test_fresh_store_no_tool_keys_gives_none(self) -> None:
        """A completely fresh store with no tool keys must result in allowed_tools=None."""
        state = _make_shared_state({})
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools is None

    def test_clear_then_reload_does_not_reseed(self) -> None:
        """
        Simulate the 'remove allowed_tools' -> reload cycle:
        After allowed_tools is cleared (written as null), the next load
        must NOT re-seed from any legacy mech_tool residue.
        """
        # Store already has allowed_tools=null (user cleared it)
        state = _make_shared_state({"allowed_tools": None})
        state._ensure_chatui_store()

        assert state._chatui_config.allowed_tools is None


# ---------------------------------------------------------------------------
# Default-filling tests
# ---------------------------------------------------------------------------


class TestEnsureChatuiStoreDefaults:
    """Tests for default values filled from params when the store is empty."""

    def test_max_bet_size_filled_from_params_when_missing(self) -> None:
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config.max_bet_size == DEFAULT_MAX_BET_SIZE

    def test_fixed_bet_size_filled_from_params_when_missing(self) -> None:
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config.fixed_bet_size == DEFAULT_MIN_BET_SIZE

    def test_trading_strategy_filled_from_yaml_when_missing(self) -> None:
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config.trading_strategy == DEFAULT_TRADING_STRATEGY

    def test_initial_trading_strategy_filled_from_yaml_when_missing(self) -> None:
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config.initial_trading_strategy == DEFAULT_TRADING_STRATEGY

    def test_trading_strategy_resets_when_yaml_changed(self) -> None:
        """If initial_trading_strategy differs from yaml, both fields must be updated."""
        state = _make_shared_state(
            {
                "trading_strategy": "bet_amount_per_threshold",
                "initial_trading_strategy": "bet_amount_per_threshold",
            }
        )
        state.context.params.trading_strategy = "kelly_criterion_no_conf"
        state._ensure_chatui_store()

        assert state._chatui_config.trading_strategy == "kelly_criterion_no_conf"
        assert (
            state._chatui_config.initial_trading_strategy == "kelly_criterion_no_conf"
        )

    def test_bad_store_data_resets_to_defaults(self) -> None:
        """A store with unrecognised keys must fall back to a clean ChatuiConfig."""
        state = _make_shared_state({"unknown_key": "garbage"})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert isinstance(state._chatui_config, ChatuiConfig)

    def test_config_persisted_to_json_on_load(self) -> None:
        """After loading, _set_json_store must be called exactly once."""
        state = _make_shared_state({})
        state._ensure_chatui_store()

        state._set_json_store.assert_called_once()
