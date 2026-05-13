#!/usr/bin/env python3
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

"""Models for the ChatUI ABCI application."""

import enum
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from aea.skills.base import SkillContext

from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.agent_performance_summary_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.chatui_abci.rounds import ChatuiAbciApp

CHATUI_PARAM_STORE = "chatui_param_store.json"

FILE_WRITE_MODE = "w"
FILE_READ_MODE = "r"
JSON_FILE_INDENT_LEVEL = 4

WITHDRAWAL_STATE_IDLE = "idle"
WITHDRAWAL_STATE_ARMED = "armed"
WITHDRAWAL_STATE_SELLING = "selling"
WITHDRAWAL_STATE_COMPLETE = "complete"
WITHDRAWAL_STATE_ERRORED = "errored"
WITHDRAWAL_STATES = frozenset(
    {
        WITHDRAWAL_STATE_IDLE,
        WITHDRAWAL_STATE_ARMED,
        WITHDRAWAL_STATE_SELLING,
        WITHDRAWAL_STATE_COMPLETE,
        WITHDRAWAL_STATE_ERRORED,
    }
)


class TradingStrategyUI(enum.Enum):
    """Trading strategy for the Agent's UI."""

    RISKY = "risky"
    BALANCED = "balanced"


@dataclass
class ChatuiConfig:
    """Parameters for the chat UI."""

    trading_strategy: Optional[str] = None
    initial_trading_strategy: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    selected_mechs: Optional[List[str]] = None
    fixed_bet_size: Optional[int] = None
    max_bet_size: Optional[int] = None
    withdrawal_mode: bool = False
    withdrawal_state: str = WITHDRAWAL_STATE_IDLE
    withdrawal_fills: List[Dict[str, Any]] = field(default_factory=list)
    withdrawal_errors: List[Dict[str, Any]] = field(default_factory=list)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls: Type[AbciApp] = ChatuiAbciApp

    def __init__(self, *args: Any, skill_context: SkillContext, **kwargs: Any) -> None:
        """Initialize the state."""
        super().__init__(*args, skill_context=skill_context, **kwargs)

        self._chatui_config: Optional[ChatuiConfig] = None

    def setup(self) -> None:
        """Set up the shared state and apply boot-time withdrawal flag auto-clear.

        Restart is the only way out of withdrawal mode: any boot with the flag
        set returns the agent to trading mode regardless of the persisted
        state. The fills/errors arrays are left intact so the FE can still
        surface the previous sweep's results until the user re-arms via POST.
        """
        super().setup()
        cfg = self.chatui_config
        if cfg.withdrawal_mode:
            self.context.logger.info(
                f"withdrawal: clearing flag on boot (state was {cfg.withdrawal_state})"
            )
            cfg.withdrawal_mode = False
            cfg.withdrawal_state = WITHDRAWAL_STATE_IDLE
            self._set_json_store(asdict(cfg))

    @property
    def chatui_config(self) -> ChatuiConfig:
        """Get the chat UI parameters."""
        self._ensure_chatui_store()

        if self._chatui_config is None:
            raise ValueError("The chat UI config has not been set!")
        return self._chatui_config

    def _get_current_json_store(self) -> Dict[str, Any]:
        """Get the current store."""
        chatui_store_path: Path = self.context.params.store_path / CHATUI_PARAM_STORE
        if not chatui_store_path.exists():
            self.context.logger.error(
                f"ChatUI JSON store {chatui_store_path!r} does not exist."
            )
            return {}
        with open(chatui_store_path, FILE_READ_MODE) as store_file:
            raw = store_file.read()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                self.context.logger.error(
                    f"{raw!r} is not valid JSON. Resetting the store."
                )
            return {}

    def _set_json_store(self, store: Dict[str, Any]) -> None:
        """Set the store with the chat UI parameters."""
        chatui_store_path = self.context.params.store_path / CHATUI_PARAM_STORE

        with open(chatui_store_path, FILE_WRITE_MODE) as f:
            json.dump(store, f, indent=JSON_FILE_INDENT_LEVEL)

    def _ensure_chatui_store(self) -> None:
        """Ensure that the chat UI store is set up correctly."""

        if self._chatui_config is not None:
            return

        current_store = self._get_current_json_store()

        # Migrate legacy mech_tool (single string) -> allowed_tools (list).
        # The migration only fires when the "allowed_tools" key is completely absent
        # from the store, so clearing the list (writing null) is preserved correctly.
        if "allowed_tools" not in current_store:
            old_mech_tool = current_store.pop("mech_tool", None)
            current_store["allowed_tools"] = [old_mech_tool] if old_mech_tool else None
        else:
            # Drop any leftover legacy key that would cause ChatuiConfig(**...) to fail.
            current_store.pop("mech_tool", None)

        try:
            self._chatui_config = ChatuiConfig(**current_store)
        except TypeError as e:
            self.context.logger.warning(
                f"Error while loading chat UI config from store: {e}. "
                "Resetting the store."
            )
            self._chatui_config = ChatuiConfig()
        trading_strategy_yaml = self.context.params.trading_strategy

        max_bet_size_store = self._chatui_config.max_bet_size
        if max_bet_size_store is None or not isinstance(max_bet_size_store, int):
            self._chatui_config.max_bet_size = self.context.params.strategies_kwargs[
                "default_max_bet_size"
            ]

        fixed_bet_size_store = self._chatui_config.fixed_bet_size
        if fixed_bet_size_store is None or not isinstance(fixed_bet_size_store, int):
            self._chatui_config.fixed_bet_size = self.context.params.strategies_kwargs[
                "absolute_min_bet_size"
            ]

        trading_strategy_store = self._chatui_config.trading_strategy
        initial_trading_strategy_store = self._chatui_config.initial_trading_strategy

        if trading_strategy_store is None or not isinstance(
            trading_strategy_store, str
        ):
            self._chatui_config.trading_strategy = trading_strategy_yaml

        if initial_trading_strategy_store is None or not isinstance(
            initial_trading_strategy_store, str
        ):
            self._chatui_config.initial_trading_strategy = trading_strategy_yaml

        # This is to ensure that changes made in the YAML file
        # are reflected in the store.
        if initial_trading_strategy_store != trading_strategy_yaml:
            # update the store with the YAML value
            self._chatui_config.trading_strategy = trading_strategy_yaml
            self._chatui_config.initial_trading_strategy = trading_strategy_yaml

        if self._chatui_config.withdrawal_state not in WITHDRAWAL_STATES:
            self.context.logger.warning(
                f"invalid withdrawal_state {self._chatui_config.withdrawal_state!r} "
                "on disk; resetting to idle"
            )
            self._chatui_config.withdrawal_state = WITHDRAWAL_STATE_IDLE
            self._chatui_config.withdrawal_mode = False

        self._set_json_store(asdict(self._chatui_config))


class ChatuiParams(BaseParams):
    """ChatUI parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.service_endpoint = self._ensure("service_endpoint", kwargs, str)
        self.genai_api_key = self._ensure("genai_api_key", kwargs, str)
        super().__init__(*args, **kwargs)
