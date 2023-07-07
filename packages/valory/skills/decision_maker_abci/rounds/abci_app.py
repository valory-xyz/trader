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

from typing import Dict, Set

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
)
from packages.valory.skills.decision_maker_abci.rounds.base import Event
from packages.valory.skills.decision_maker_abci.rounds.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.decision_maker_abci.rounds.decision_maker import (
    DecisionMakerRound,
)
from packages.valory.skills.decision_maker_abci.rounds.final_states import (
    FinishedDecisionMakerRound,
    ImpossibleRound,
)
from packages.valory.skills.decision_maker_abci.rounds.sampling import SamplingRound


class DecisionMakerAbciApp(AbciApp[Event]):
    """DecisionMakerAbciApp

    Initial round: DecisionMakerRound

    Initial states: {DecisionMakerRound}

    Transition states:

    Final states: {FinishedDecisionMakerRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: AppState = SamplingRound
    initial_states: Set[AppState] = {SamplingRound}
    transition_function: AbciAppTransitionFunction = {
        SamplingRound: {
            Event.DONE: DecisionMakerRound,
            Event.NONE: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.NO_MAJORITY: SamplingRound,
        },
        DecisionMakerRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.MECH_RESPONSE_ERROR: BlacklistingRound,
            Event.NO_MAJORITY: DecisionMakerRound,
            Event.NON_BINARY: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.TIE: BlacklistingRound,
            Event.UNPROFITABLE: BlacklistingRound,
        },
        BlacklistingRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.NONE: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.NO_MAJORITY: BlacklistingRound,
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
