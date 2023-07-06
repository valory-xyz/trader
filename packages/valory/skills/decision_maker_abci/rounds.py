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
from typing import Dict, Set

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    DegenerateRound,
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionMakerPayload
from packages.valory.skills.market_manager_abci.bets import Bet
from packages.valory.skills.market_manager_abci.rounds import SynchronizedData as BaseSynchronizedData


class Event(Enum):
    """Event enumeration for the price estimation demo."""

    DONE = "done"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def sampled_bet(self) -> Bet:
        """Get the sampled bet."""


class DecisionMakerRound(CollectSameUntilThresholdRound):
    """A round in which the agents decide on the bet's answer."""

    payload_class = DecisionMakerPayload
    synchronized_data_class = BaseSynchronizedData


class FinishedDecisionMakerRound(DegenerateRound):
    """A round representing that decision-making has finished"""


class AgentDecisionMakerAbciApp(AbciApp[Event]):
    """AgentDecisionMakerAbciApp

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
            Event.NO_MAJORITY: DecisionMakerRound,
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
