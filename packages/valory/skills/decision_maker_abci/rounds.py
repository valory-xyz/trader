# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the rounds for the decision-making."""

from enum import Enum
from typing import Dict, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    DeserializedCollection,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionMakerPayload
from packages.valory.skills.market_manager_abci.bets import Bet
from packages.valory.skills.market_manager_abci.rounds import (
    SynchronizedData as BaseSynchronizedData,
)


class Event(Enum):
    """Event enumeration for the price estimation demo."""

    DONE = "done"
    MECH_RESPONSE_ERROR = "mech_response_error"
    NON_BINARY = "non_binary"
    TIE = "tie"
    UNPROFITABLE = "unprofitable"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def sampled_bet(self) -> Bet:
        """Get the sampled bet."""
        raise NotImplementedError

    @property
    def non_binary(self) -> bool:
        """Get whether the question is non-binary."""
        return bool(self.db.get_strict("non_binary"))

    @property
    def vote(self) -> str:
        """Get the bet's vote."""
        vote = self.db.get_strict("vote")
        return self.sampled_bet.get_outcome(vote)

    @property
    def confidence(self) -> float:
        """Get the vote's confidence."""
        return float(self.db.get_strict("confidence"))

    @property
    def is_profitable(self) -> bool:
        """Get whether the current vote is profitable or not."""
        return bool(self.db.get_strict("is_profitable"))

    @property
    def participant_to_decision(self) -> DeserializedCollection:
        """Get the participants to decision-making."""
        return self._get_deserialized("participant_to_decision")


class DecisionMakerRound(CollectSameUntilThresholdRound):
    """A round in which the agents decide on the bet's answer."""

    payload_class = DecisionMakerPayload
    synchronized_data_class = BaseSynchronizedData

    done_event = Event.DONE
    none_event = Event.MECH_RESPONSE_ERROR
    no_majority_event = Event.NO_MAJORITY
    selection_key = (
        get_name(SynchronizedData.non_binary),
        get_name(SynchronizedData.vote),
        get_name(SynchronizedData.confidence),
        get_name(SynchronizedData.is_profitable),
    )
    collection_key = get_name(SynchronizedData.participant_to_decision)

    def end_block(self) -> Optional[Tuple[SynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        if event == Event.DONE and synced_data.non_binary:
            return synced_data, Event.NON_BINARY

        if event == Event.DONE and synced_data.vote is None:
            return synced_data, Event.TIE

        if event == Event.DONE and not synced_data.is_profitable:
            return synced_data, Event.UNPROFITABLE

        return synced_data, event


class FinishedDecisionMakerRound(DegenerateRound):
    """A round representing that decision-making has finished."""


class ImpossibleRound(DegenerateRound):
    """A round representing that decision-making is impossible with the given parametrization."""


class DecisionMakerAbciApp(AbciApp[Event]):
    """DecisionMakerAbciApp

    Initial round: DecisionMakerRound

    Initial states: {DecisionMakerRound}

    Transition states:

    Final states: {FinishedDecisionMakerRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: AppState = DecisionMakerRound
    initial_states: Set[AppState] = {DecisionMakerRound}
    transition_function: AbciAppTransitionFunction = {
        DecisionMakerRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.MECH_RESPONSE_ERROR: FinishedDecisionMakerRound,  # TODO blacklist and go back to sampling a bet
            Event.NO_MAJORITY: DecisionMakerRound,
            Event.NON_BINARY: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.TIE: FinishedDecisionMakerRound,  # TODO blacklist and go back to sampling a bet
            Event.UNPROFITABLE: FinishedDecisionMakerRound,  # TODO blacklist the sampled bet for duration set in config
        },
        FinishedDecisionMakerRound: {},
    }
    final_states: Set[AppState] = {
        FinishedDecisionMakerRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        DecisionMakerRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedDecisionMakerRound: set(),
    }
