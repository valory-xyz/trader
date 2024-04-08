# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
from typing import Dict, Optional, Set, Tuple, Type, cast

from packages.valory.contracts.service_staking_token.contract import StakingState
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
from packages.valory.skills.check_stop_trading_abci.payloads import CheckStopTradingPayload


class Event(Enum):
    """Event enumeration for the check stop trading skill."""

    DONE = "done"
    NONE = "none"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"
    SKIP_TRADING = "skip_trading"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    def _get_deserialized(self, key: str) -> DeserializedCollection:
        """Strictly get a collection and return it deserialized."""
        serialized = self.db.get_strict(key)
        return CollectionRound.deserialize_collection(serialized)

    @property
    def stop_trading(self) -> bool:
        """Get if the service must stop trading."""
        return bool(self.db.get("stop_trading", False))

    @property
    def participant_to_selection(self) -> DeserializedCollection:
        """Get the participants to selection round."""
        return self._get_deserialized("participant_to_selection")


class CheckStopTradingRound(CollectSameUntilThresholdRound):
    """A round for checking stop trading conditions."""

    payload_class = CheckStopTradingPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key = (get_name(SynchronizedData.stop_trading),)
    collection_key = get_name(SynchronizedData.participant_to_selection)

    def end_block(self) -> Optional[Tuple[SynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        stop_trading_payload = self.most_voted_payload

        if event == Event.DONE and stop_trading_payload == True:
            return synced_data, Event.SKIP_TRADING

        return synced_data, event


class FinishedCheckStopTradingRound(DegenerateRound, ABC):
    """A round that represents check stop trading has finished."""


class FinishedCheckStopTradingWithSkipTradingRound(DegenerateRound, ABC):
    """A round that represents check stop trading has finished with skip trading."""


class CheckStopTradingAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """CheckStopTradingAbciApp

    Initial round: CheckStopTradingRound

    Initial states: {CheckStopTradingRound}

    Transition states:
        0. CheckStopTradingRound
            - done: 1.
            - none: 0.
            - round timeout: 0.
            - no majority: 0.
            - skip trading: 2.
        1. FinishedCheckStopTradingRound
        2. FinishedCheckStopTradingWithSkipTradingRound

    Final states: {FinishedCheckStopTradingRound, FinishedCheckStopTradingWithSkipTradingRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = CheckStopTradingRound
    transition_function: AbciAppTransitionFunction = {
        CheckStopTradingRound: {
            Event.DONE: FinishedCheckStopTradingRound,
            Event.NONE: CheckStopTradingRound,
            Event.ROUND_TIMEOUT: CheckStopTradingRound,
            Event.NO_MAJORITY: CheckStopTradingRound,
            Event.SKIP_TRADING: FinishedCheckStopTradingWithSkipTradingRound,
        },
        FinishedCheckStopTradingRound: {},
        FinishedCheckStopTradingWithSkipTradingRound: {},
    }
    final_states: Set[AppState] = {
        FinishedCheckStopTradingRound,
        FinishedCheckStopTradingWithSkipTradingRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {CheckStopTradingRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedCheckStopTradingRound: set(),
        FinishedCheckStopTradingWithSkipTradingRound: set(),
    }
