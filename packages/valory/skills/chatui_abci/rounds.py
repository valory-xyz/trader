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

"""This module contains the rounds for the chat UI ABCI application."""

import json
from abc import ABC
from enum import Enum
from typing import Dict, Optional, Set, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    DegenerateRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.chatui_abci.payloads import ChatuiPayload

SERIALIZED_EMPTY_PIN = "[]"
SELECTED_MECHS_DB_KEY = "selected_mechs"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def available_mech_tools(self) -> Set[str]:
        """Get all the available mech tools."""
        tools = self.db.get_strict("available_mech_tools")
        return set(json.loads(tools))

    @property
    def available_valid_mechs(self) -> Set[str]:
        """Get the addresses of mechs currently visible to mech-interact.

        Read from the same `mechs_info` key written by mech_interact_abci's
        MechInformationRound. Addresses are lowercased to match the format
        produced by the Autonolas subgraph and the `valid_mechs`
        normalization in mech-interact.
        """
        raw = self.db.get("mechs_info", "[]")
        if not isinstance(raw, str):
            return set()
        try:
            mechs = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return set()
        return {
            str(m["address"]).lower()
            for m in (mechs or [])
            if isinstance(m, dict) and m.get("address")
        }


class Event(Enum):
    """Event enumeration for the chat UI skill."""

    DONE = "done"
    FAIL = "fail"
    NONE = "none"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"


class ChatuiLoadRound(VotingRound):
    """A round for loading ChatUI config."""

    payload_class = ChatuiPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    negative_event = Event.FAIL
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_votes)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, "Enum"]]:
        """Process the end of the block.

        On positive vote threshold, publish the consumer-set
        ``selected_mechs`` pin into synchronized data alongside the
        usual vote collection. mech-interact's MechInformationRound
        reads this key on the same FSM iteration, so the pin is
        always fresh before discovery runs — avoiding the stale-pin
        loop where pinned_mechs_offline kept failing on a value the
        user had already cleared.

        :return: the updated synchronized data and the resulting event,
            or ``None`` if no threshold has been reached yet.
        """
        if self.positive_vote_threshold_reached:
            positive_payloads = [
                cast(ChatuiPayload, p)
                for p in self.collection.values()
                if getattr(p, "vote", None) is True
            ]
            # Single-agent assumption: only the receiving agent's
            # chatui_config carries the pin, so the dict-order pick is
            # uniquely determined. On a future multi-agent migration
            # this must switch to a consensus rule (e.g. most_common)
            # to stay deterministic across peers.
            raw_pin = positive_payloads[0].selected_mechs if positive_payloads else None
            selected_mechs = raw_pin if raw_pin is not None else SERIALIZED_EMPTY_PIN
            synchronized_data = self.synchronized_data.update(
                synchronized_data_class=self.synchronized_data_class,
                **{
                    self.collection_key: self.serialized_collection,
                    SELECTED_MECHS_DB_KEY: selected_mechs,
                },
            )
            return synchronized_data, self.done_event
        if self.negative_vote_threshold_reached:
            return self.synchronized_data, self.negative_event
        if self.none_vote_threshold_reached:
            return self.synchronized_data, self.none_event
        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, self.no_majority_event
        return None


class FinishedChatuiLoadRound(DegenerateRound, ABC):
    """A round that represents chat UI loading has finished."""


class ChatuiAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """ChatuiAbciApp

    Initial round: ChatuiLoadRound

    Initial states: {ChatuiLoadRound}

    Transition states:
        0. ChatuiLoadRound
            - done: 1.
            - fail: 0.
            - none: 0.
            - round timeout: 0.
            - no majority: 0.
        1. FinishedChatuiLoadRound

    Final states: {FinishedChatuiLoadRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = ChatuiLoadRound
    transition_function: AbciAppTransitionFunction = {
        ChatuiLoadRound: {
            Event.DONE: FinishedChatuiLoadRound,
            Event.FAIL: ChatuiLoadRound,
            Event.NONE: ChatuiLoadRound,
            Event.ROUND_TIMEOUT: ChatuiLoadRound,
            Event.NO_MAJORITY: ChatuiLoadRound,
        },
        FinishedChatuiLoadRound: {},
    }
    final_states: Set[AppState] = {
        FinishedChatuiLoadRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {ChatuiLoadRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedChatuiLoadRound: set(),
    }
