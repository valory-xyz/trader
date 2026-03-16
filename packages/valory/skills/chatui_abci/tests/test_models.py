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

"""Tests for packages/valory/skills/chatui_abci/models.py."""

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.agent_performance_summary_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.chatui_abci.models import (
    CHATUI_PARAM_STORE,
    ChatuiConfig,
    ChatuiParams,
    SharedState,
)

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

    :param store: initial JSON store dict to load.
    :return: configured _TestableSharedState instance.
    """
    state = object.__new__(_TestableSharedState)
    state._chatui_config = None  # type: ignore[attr-defined]

    params = MagicMock()
    params.trading_strategy = DEFAULT_TRADING_STRATEGY
    params.strategies_kwargs = {
        "default_max_bet_size": DEFAULT_MAX_BET_SIZE,
        "absolute_min_bet_size": DEFAULT_MIN_BET_SIZE,
    }

    context = MagicMock()
    context.params = params
    state.context = context  # type: ignore[assignment]

    state._get_current_json_store = MagicMock(return_value=dict(store))  # type: ignore[method-assign]
    state._set_json_store = MagicMock()  # type: ignore[method-assign]

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

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools == ["prediction-online"]

    def test_legacy_mech_tool_null_yields_none(self) -> None:
        """A store with mech_tool=null must yield allowed_tools=None (not [None])."""
        state = _make_shared_state({"mech_tool": None})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools is None

    def test_migration_persists_without_mech_tool_key(self) -> None:
        """After migration, the persisted store must contain allowed_tools and no mech_tool."""
        state = _make_shared_state({"mech_tool": "prediction-online"})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        persisted: dict = state._set_json_store.call_args[0][0]  # type: ignore[attr-defined]
        assert "allowed_tools" in persisted
        assert "mech_tool" not in persisted
        assert persisted["allowed_tools"] == ["prediction-online"]

    def test_existing_allowed_tools_list_is_respected(self) -> None:
        """A store already containing allowed_tools must not be re-migrated."""
        state = _make_shared_state({"allowed_tools": ["tool-a", "tool-b"]})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools == ["tool-a", "tool-b"]

    def test_existing_allowed_tools_null_is_respected(self) -> None:
        """allowed_tools=null (key present) must stay None and not re-seed from mech_tool."""
        state = _make_shared_state({"allowed_tools": None})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools is None

    def test_leftover_mech_tool_key_dropped_when_allowed_tools_present(self) -> None:
        """If both keys coexist, mech_tool must be dropped and allowed_tools wins."""
        state = _make_shared_state(
            {"allowed_tools": ["tool-a"], "mech_tool": "old-tool"}
        )
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools == ["tool-a"]
        persisted: dict = state._set_json_store.call_args[0][0]  # type: ignore[attr-defined]
        assert "mech_tool" not in persisted

    def test_migration_fires_only_once(self) -> None:
        """Calling _ensure_chatui_store twice must not re-read or re-persist the store."""
        state = _make_shared_state({"mech_tool": "prediction-online"})
        state._ensure_chatui_store()
        state._ensure_chatui_store()

        assert state._get_current_json_store.call_count == 1  # type: ignore[attr-defined]
        assert state._set_json_store.call_count == 1  # type: ignore[attr-defined]

    def test_fresh_store_no_tool_keys_gives_none(self) -> None:
        """A completely fresh store with no tool keys must result in allowed_tools=None."""
        state = _make_shared_state({})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools is None

    def test_clear_then_reload_does_not_reseed(self) -> None:
        """Simulate the 'remove allowed_tools' -> reload cycle.

        After allowed_tools is cleared (written as null), the next load
        must NOT re-seed from any legacy mech_tool residue.
        """
        # Store already has allowed_tools=null (user cleared it)
        state = _make_shared_state({"allowed_tools": None})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.allowed_tools is None


# ---------------------------------------------------------------------------
# Default-filling tests
# ---------------------------------------------------------------------------


class TestEnsureChatuiStoreDefaults:
    """Tests for default values filled from params when the store is empty."""

    def test_max_bet_size_filled_from_params_when_missing(self) -> None:
        """Max bet size must be sourced from params when absent from the store."""
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config is not None
        assert state._chatui_config.max_bet_size == DEFAULT_MAX_BET_SIZE

    def test_fixed_bet_size_filled_from_params_when_missing(self) -> None:
        """Fixed bet size must be sourced from params when absent from the store."""
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config is not None
        assert state._chatui_config.fixed_bet_size == DEFAULT_MIN_BET_SIZE

    def test_trading_strategy_filled_from_yaml_when_missing(self) -> None:
        """Trading strategy must be sourced from YAML params when absent from the store."""
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config is not None
        assert state._chatui_config.trading_strategy == DEFAULT_TRADING_STRATEGY

    def test_initial_trading_strategy_filled_from_yaml_when_missing(self) -> None:
        """Initial trading strategy must be sourced from YAML params when absent from the store."""
        state = _make_shared_state({})
        state._ensure_chatui_store()
        assert state._chatui_config is not None
        assert state._chatui_config.initial_trading_strategy == DEFAULT_TRADING_STRATEGY

    def test_trading_strategy_resets_when_yaml_changed(self) -> None:
        """If initial_trading_strategy differs from yaml, both fields must be updated."""
        state = _make_shared_state(
            {
                "trading_strategy": "bet_amount_per_threshold",
                "initial_trading_strategy": "bet_amount_per_threshold",
            }
        )
        state.context.params.trading_strategy = "kelly_criterion_no_conf"  # type: ignore[attr-defined]
        state._ensure_chatui_store()

        assert state._chatui_config is not None
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

        state._set_json_store.assert_called_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ChatuiConfig dataclass tests
# ---------------------------------------------------------------------------


class TestChatuiConfig:
    """Tests for ChatuiConfig dataclass defaults and field assignment."""

    def test_default_values(self) -> None:
        """All fields must default to None."""
        config = ChatuiConfig()
        assert config.trading_strategy is None
        assert config.initial_trading_strategy is None
        assert config.allowed_tools is None
        assert config.fixed_bet_size is None
        assert config.max_bet_size is None

    def test_custom_values(self) -> None:
        """Fields must accept and store custom values."""
        config = ChatuiConfig(
            trading_strategy="kelly_criterion_no_conf",
            initial_trading_strategy="bet_amount_per_threshold",
            allowed_tools=["tool-a", "tool-b"],
            fixed_bet_size=100,
            max_bet_size=999,
        )
        assert config.trading_strategy == "kelly_criterion_no_conf"
        assert config.initial_trading_strategy == "bet_amount_per_threshold"
        assert config.allowed_tools == ["tool-a", "tool-b"]
        assert config.fixed_bet_size == 100
        assert config.max_bet_size == 999


# ---------------------------------------------------------------------------
# SharedState.__init__ tests
# ---------------------------------------------------------------------------


class TestSharedStateInit:
    """Tests for SharedState.__init__ (lines 72-74)."""

    def test_init_sets_chatui_config_to_none(self) -> None:
        """SharedState.__init__ must initialise _chatui_config to None."""
        mock_skill_context = MagicMock()
        with patch.object(BaseSharedState, "__init__", return_value=None):
            state = _TestableSharedState(skill_context=mock_skill_context)
        assert state._chatui_config is None

    def test_init_calls_super(self) -> None:
        """SharedState.__init__ must call BaseSharedState.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(BaseSharedState, "__init__", return_value=None) as mock_super:
            _TestableSharedState(skill_context=mock_skill_context)
        mock_super.assert_called_once()


# ---------------------------------------------------------------------------
# SharedState.chatui_config property tests
# ---------------------------------------------------------------------------


class TestChatuiConfigProperty:
    """Tests for SharedState.chatui_config property (lines 79-83)."""

    def test_property_returns_config_after_ensure(self) -> None:
        """chatui_config must return the config after _ensure_chatui_store sets it."""
        state = _make_shared_state({})
        # Access via property triggers _ensure_chatui_store, which sets _chatui_config
        config = state.chatui_config
        assert isinstance(config, ChatuiConfig)

    def test_property_raises_when_config_is_none_after_ensure(self) -> None:
        """chatui_config must raise ValueError if _chatui_config is still None after _ensure."""
        state = _make_shared_state({})
        # Override _ensure_chatui_store so it does NOT set _chatui_config
        state._ensure_chatui_store = MagicMock()  # type: ignore[method-assign]
        with pytest.raises(ValueError, match="The chat UI config has not been set!"):
            _ = state.chatui_config


# ---------------------------------------------------------------------------
# SharedState._get_current_json_store tests (real file I/O, lines 87-100)
# ---------------------------------------------------------------------------


class TestGetCurrentJsonStore:
    """Tests for SharedState._get_current_json_store with real temp files."""

    def _make_state_with_store_path(self, store_path: Path) -> _TestableSharedState:
        """Create a _TestableSharedState with a real store_path (no mocked I/O).

        :param store_path: directory for the JSON store file.
        :return: configured _TestableSharedState instance.
        """
        state = object.__new__(_TestableSharedState)
        state._chatui_config = None

        params = MagicMock()
        params.store_path = store_path

        context = MagicMock()
        context.params = params
        state.context = context  # type: ignore[assignment]

        return state

    def test_file_not_exists_returns_empty_dict(self, tmp_path: Path) -> None:
        """When the store file does not exist, return {} and log an error."""
        state = self._make_state_with_store_path(tmp_path)
        result = state._get_current_json_store()
        assert result == {}
        state.context.logger.error.assert_called_once()  # type: ignore[attr-defined]

    def test_valid_json_file_returns_dict(self, tmp_path: Path) -> None:
        """When the store file has valid JSON, return its contents."""
        store_file = tmp_path / CHATUI_PARAM_STORE
        expected = {"trading_strategy": "risky", "max_bet_size": 42}
        store_file.write_text(json.dumps(expected))

        state = self._make_state_with_store_path(tmp_path)
        result = state._get_current_json_store()
        assert result == expected

    def test_invalid_json_returns_empty_dict(self, tmp_path: Path) -> None:
        """When the store file has invalid JSON, return {} and log an error."""
        store_file = tmp_path / CHATUI_PARAM_STORE
        store_file.write_text("not-valid-json{{{")

        state = self._make_state_with_store_path(tmp_path)
        result = state._get_current_json_store()
        assert result == {}
        state.context.logger.error.assert_called_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# SharedState._set_json_store tests (real file I/O, lines 104-107)
# ---------------------------------------------------------------------------


class TestSetJsonStore:
    """Tests for SharedState._set_json_store with real temp files."""

    def test_write_and_read_back(self, tmp_path: Path) -> None:
        """_set_json_store must write valid JSON that can be read back."""
        state = object.__new__(_TestableSharedState)
        state._chatui_config = None  # type: ignore[attr-defined]

        params = MagicMock()
        params.store_path = tmp_path

        context = MagicMock()
        context.params = params
        state.context = context  # type: ignore[assignment]

        payload = {"trading_strategy": "balanced", "max_bet_size": 100}
        state._set_json_store(payload)

        store_file = tmp_path / CHATUI_PARAM_STORE
        assert store_file.exists()

        with open(store_file) as f:
            written = json.load(f)
        assert written == payload


# ---------------------------------------------------------------------------
# ChatuiParams.__init__ tests (lines 177-179)
# ---------------------------------------------------------------------------


class TestChatuiParamsInit:
    """Tests for ChatuiParams.__init__."""

    def test_init_sets_service_endpoint_and_genai_api_key(self) -> None:
        """Test that ChatuiParams init must extract service_endpoint and genai_api_key."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            params = ChatuiParams(
                skill_context=mock_skill_context,
                service_endpoint="https://example.com",
                genai_api_key="dummy",
            )
        assert params.service_endpoint == "https://example.com"
        assert params.genai_api_key == "dummy"

    def test_init_calls_super(self) -> None:
        """Test that ChatuiParams init must call BaseParams.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None) as mock_super:
            ChatuiParams(
                skill_context=mock_skill_context,
                service_endpoint="https://example.com",
                genai_api_key="dummy",
            )
        mock_super.assert_called_once()


# ---------------------------------------------------------------------------
# Branch coverage tests
# ---------------------------------------------------------------------------


class TestEnsureChatuiStoreBranches:
    """Tests for branch conditions in _ensure_chatui_store."""

    def test_valid_int_max_bet_size_skips_default(self) -> None:
        """When max_bet_size IS a valid int in store, don't overwrite with param default."""
        custom_max_bet = 5_000_000_000_000_000_000
        state = _make_shared_state({"max_bet_size": custom_max_bet})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.max_bet_size == custom_max_bet

    def test_valid_int_fixed_bet_size_skips_default(self) -> None:
        """When fixed_bet_size IS a valid int in store, don't overwrite with param default."""
        custom_fixed_bet = 50_000_000_000_000_000
        state = _make_shared_state({"fixed_bet_size": custom_fixed_bet})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.fixed_bet_size == custom_fixed_bet

    def test_initial_trading_strategy_matches_yaml_no_reset(self) -> None:
        """When initial_trading_strategy == YAML value, no reset should happen."""
        state = _make_shared_state(
            {
                "trading_strategy": "custom_strategy",
                "initial_trading_strategy": DEFAULT_TRADING_STRATEGY,
            }
        )
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        # Because initial_trading_strategy matches YAML, it stays as-is
        assert state._chatui_config.initial_trading_strategy == DEFAULT_TRADING_STRATEGY
        # trading_strategy also stays as the store value since no reset is triggered
        assert state._chatui_config.trading_strategy == "custom_strategy"

    def test_non_int_max_bet_size_resets_to_default(self) -> None:
        """When max_bet_size is a non-int string, overwrite with param default."""
        state = _make_shared_state({"max_bet_size": "not_an_int"})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.max_bet_size == DEFAULT_MAX_BET_SIZE

    def test_non_int_fixed_bet_size_resets_to_default(self) -> None:
        """When fixed_bet_size is a non-int string, overwrite with param default."""
        state = _make_shared_state({"fixed_bet_size": "not_an_int"})
        state._ensure_chatui_store()

        assert state._chatui_config is not None
        assert state._chatui_config.fixed_bet_size == DEFAULT_MIN_BET_SIZE
