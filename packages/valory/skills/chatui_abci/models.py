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
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Type

from aea.skills.base import SkillContext

from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.agent_performance_summary_abci.activity_goal import (
    is_valid_activity_goal,
)
from packages.valory.skills.agent_performance_summary_abci.feed import FeedEntry
from packages.valory.skills.agent_performance_summary_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    write_json_atomically,
)
from packages.valory.skills.chatui_abci.rounds import ChatuiAbciApp

CHATUI_PARAM_STORE = "chatui_param_store.json"
# Kept apart from the chat config, whose loader resets on unknown keys, so an
# older version reading the config never sees it.
APPROVED_MECHS_STORE = "approved_mechs.json"
ADDRESS_PATTERN = re.compile(r"0x[0-9a-f]{40}")
ACTIVITY_GOAL_FIELD = "activity_goal"
MAX_MECH_OFFERS = 20
# A message whose answer never came back stops blocking its resend after this.
ANSWERING_TIMEOUT_SECONDS = 300

FILE_READ_MODE = "r"

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
    # Trades per staking epoch; ``None`` means the ``default_activity_goal`` param.
    activity_goal: Optional[int] = None


def _keep_newest(store: Dict[str, Any], key: str, value: Any) -> None:
    """Store the value as the newest, dropping the oldest beyond `MAX_MECH_OFFERS`."""
    store.pop(key, None)
    store[key] = value
    while len(store) > MAX_MECH_OFFERS:
        del store[next(iter(store))]


@dataclass(frozen=True)
class Offer:
    """The terms a report showed for a mech, which a typed accept must repeat."""

    address: str
    rate: int
    payment_type: str
    price_text: str


@dataclass(frozen=True)
class ConfigChange:
    """One setting a chat change sets, as the user reads it."""

    setting: str
    before: str
    after: str


@dataclass(frozen=True)
class ConfigProposal:
    """A config change from the chat, kept unapplied until the user confirms it."""

    config: Dict[str, Any]
    changes: List[ConfigChange]


@dataclass(frozen=True)
class ChatTurn:
    """A chat message being answered: Pearl's id for it and its line as written.

    ``proposal`` is the change its reply asks to confirm, kept here until that
    reply is written so that a turn which fails leaves nothing to confirm.
    ``applied_change`` marks a reply acknowledging a change already applied,
    which a resend must report rather than answer anew. ``attempt`` tells this
    answer apart from a resend's, and survives ``replace``.
    """

    client_id: str
    message: FeedEntry
    proposal: Optional[ConfigProposal] = None
    applied_change: bool = False
    attempt: object = field(default_factory=object, compare=False, repr=False)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls: Type[AbciApp] = ChatuiAbciApp

    def __init__(self, *args: Any, skill_context: SkillContext, **kwargs: Any) -> None:
        """Initialize the state."""
        super().__init__(*args, skill_context=skill_context, **kwargs)

        self._chatui_config: Optional[ChatuiConfig] = None
        self._approved_mech_rates: Optional[Dict[str, int]] = None
        # In memory only: the last offer shown per lowercase address, oldest first.
        self.mech_offers: Dict[str, Offer] = {}
        # In memory only: why the last report for an address made no offer.
        self.mech_refusals: Dict[str, str] = {}

        # Suitability-filtered tool set published by the decision-maker's
        # ToolSelectionBehaviour each round (the post-classifier, pre-pin
        # universe). The ChatUI validates and displays tool pins against this
        # so a user cannot pin a tool the policy would never select. It stays
        # None until the first ToolSelectionRound runs; consumers fall back to
        # the raw `available_mech_tools` synced-data set in that window.
        self.available_prediction_tools: Optional[FrozenSet[str]] = None

        # In memory only, so a restart drops them: the attempt answering each
        # chat message and when it started, and the change waiting for confirmation.
        self._answering: Dict[str, Tuple[object, float]] = {}
        self.config_proposal: Optional[ConfigProposal] = None
        # The acknowledgement of an applied change whose reply could not be
        # written, by client id, for the resend to write.
        self.unsaved_replies: Dict[str, str] = {}

    def is_answering(self, client_id: str) -> bool:
        """Return whether the message with this client id is still being answered."""
        answering = self._answering.get(client_id)
        return (
            answering is not None
            and time.time() - answering[1] < ANSWERING_TIMEOUT_SECONDS
        )

    def start_answering(self, turn: ChatTurn) -> None:
        """Mark the turn's message as being answered by it."""
        self._answering[turn.client_id] = (turn.attempt, time.time())

    def finish_answering(self, turn: ChatTurn) -> None:
        """Mark the turn's message as no longer being answered, unless a resend took it over."""
        answering = self._answering.get(turn.client_id)
        if answering is not None and answering[0] is turn.attempt:
            del self._answering[turn.client_id]

    def take_config_proposal(self) -> Optional[ConfigProposal]:
        """Return the change waiting for confirmation and forget it: it gets one reply."""
        proposal, self.config_proposal = self.config_proposal, None
        return proposal

    def restore_config_proposal(self, proposal: ConfigProposal) -> None:
        """Put back a change its confirmation could not decide, unless a newer one is waiting."""
        if self.config_proposal is None:
            self.config_proposal = proposal

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

    @property
    def approved_mech_rates(self) -> Dict[str, int]:
        """Get the accepted per-request rate, in the asset's smallest unit, by lowercase approved address."""
        if self._approved_mech_rates is None:
            self._approved_mech_rates = self._read_approved_mech_rates()
        return dict(self._approved_mech_rates)

    @property
    def approved_mechs(self) -> List[str]:
        """Get the approved mechs' lowercase addresses, in approval order."""
        return list(self.approved_mech_rates)

    def set_approved_mech_rates(self, rates: Dict[str, int]) -> None:
        """Replace the approved record on disk and in memory, addresses lowercased."""
        approved = {str(mech).lower(): int(rate) for mech, rate in rates.items()}
        write_json_atomically(
            self.context.params.store_path / APPROVED_MECHS_STORE, approved
        )
        self._approved_mech_rates = approved

    def approve_mech(self, address: str, rate: int) -> None:
        """Record the mech as approved at this rate, replacing any earlier one."""
        rates = self.approved_mech_rates
        rates[str(address).lower()] = int(rate)
        self.set_approved_mech_rates(rates)

    def record_mech_offer(self, offer: Offer) -> None:
        """Keep the offer as the newest for its address, holding at most `MAX_MECH_OFFERS`."""
        self.mech_refusals.pop(offer.address, None)
        _keep_newest(self.mech_offers, offer.address, offer)

    def record_mech_refusal(self, address: str, reason: str) -> None:
        """Keep why the last report for the address made no offer, holding at most `MAX_MECH_OFFERS`."""
        self.mech_offers.pop(address, None)
        _keep_newest(self.mech_refusals, address, reason)

    def drop_mech_offer(self, offer: Offer) -> None:
        """Forget the offer, unless a newer one has replaced it."""
        if self.mech_offers.get(offer.address) == offer:
            del self.mech_offers[offer.address]

    def _read_approved_mech_rates(self) -> Dict[str, int]:
        """Read the approved mechs; a missing or unreadable file means none."""
        path: Path = self.context.params.store_path / APPROVED_MECHS_STORE
        if not path.exists():
            return {}
        try:
            with open(path, FILE_READ_MODE) as store_file:
                raw = json.loads(store_file.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.context.logger.error(
                f"Approved mechs file {path!r} is unreadable: {e}."
            )
            return {}
        if not isinstance(raw, dict):
            self.context.logger.error(
                f"Approved mechs file {path!r} is not an object of address to rate."
            )
            return {}
        approved: Dict[str, int] = {}
        for mech, rate in raw.items():
            address = str(mech).lower()
            if not ADDRESS_PATTERN.fullmatch(address):
                continue
            if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
                continue
            approved[address] = rate
        return approved

    def _get_current_json_store(self) -> Dict[str, Any]:
        """Get the current store."""
        chatui_store_path: Path = self.context.params.store_path / CHATUI_PARAM_STORE
        if not chatui_store_path.exists():
            self.context.logger.error(
                f"ChatUI JSON store {chatui_store_path!r} does not exist."
            )
            return {}
        try:
            with open(chatui_store_path, FILE_READ_MODE) as store_file:
                return json.loads(store_file.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.context.logger.error(
                f"ChatUI JSON store {chatui_store_path!r} is not valid JSON: {e}. "
                "Resetting the store."
            )
        return {}

    def _set_json_store(self, store: Dict[str, Any]) -> None:
        """Set the store with the chat UI parameters."""
        write_json_atomically(
            self.context.params.store_path / CHATUI_PARAM_STORE, store
        )

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

        if (
            self._chatui_config.activity_goal is not None
            and not is_valid_activity_goal(self._chatui_config.activity_goal)
        ):
            self.context.logger.warning(
                f"invalid activity_goal {self._chatui_config.activity_goal!r} "
                "on disk; resetting to the default"
            )
            self._chatui_config.activity_goal = None

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
