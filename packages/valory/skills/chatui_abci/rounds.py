# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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

"""This module contains the rounds for the check stop trading ABCI application."""

from abc import ABC
from enum import Enum
from typing import Dict, Optional, Set, Tuple, Type

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    CollectionRound,
    DegenerateRound,
    DeserializedCollection,
    get_name,
)
from packages.valory.skills.chatui_abci.payloads import ChatuiPayload


class Event(Enum):
    """Event enumeration for the check stop trading skill."""

    DONE = "done"
    NONE = "none"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    def _get_deserialized(self, key: str) -> DeserializedCollection:
        """Strictly get a collection and return it deserialized."""
        serialized = self.db.get_strict(key)
        return CollectionRound.deserialize_collection(serialized)


class ChatuiLoadRound(CollectSameUntilThresholdRound):
    """A round for loading ChatUI config."""

    payload_class = ChatuiPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    negative_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_votes)
    selection_key = get_name(SynchronizedData.most_voted_keeper_address)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        if self.threshold_reached:
            synchronized_data = self.synchronized_data
            return synchronized_data, Event.DONE

        if not self.is_majority_possible(
            self.collection, self.synchronized_data.nb_participants
        ):
            return self.synchronized_data, Event.NO_MAJORITY

        return None


class FinishedChatuiLoadRound(DegenerateRound, ABC):
    """A round that represents check stop trading has finished."""


class ChatuiAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """ChatuiAbciApp

    Initial round: ChatuiLoadRound

    Initial states: {ChatuiLoadRound}

    Transition states:
        0. ChatuiLoadRound
            - done: 1.
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
