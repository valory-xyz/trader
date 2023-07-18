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
    get_name,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    FinishedDecisionMakerRound,
    FinishedWithoutDecisionRound,
    ImpossibleRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)


class DecisionMakerAbciApp(AbciApp[Event]):
    """DecisionMakerAbciApp

    Initial round: SamplingRound

    Initial states: {BlacklistingRound, SamplingRound}

    Transition states:
        0. SamplingRound
            - done: 1.
            - none: 5.
            - no majority: 0.
            - round timeout: 0.
        1. DecisionRequestRound
            - done: 3.
            - slots unsupported error: 2.
            - no majority: 1.
            - non binary: 7.
            - tie: 2.
            - unprofitable: 2.
            - round timeout: 1.
        2. BlacklistingRound
            - done: 5.
            - none: 7.
            - no majority: 2.
            - round timeout: 2.
            - fetch error: 7.
        3. BetPlacementRound
            - done: 4.
            - insufficient balance: 6.
            - no majority: 3.
            - round timeout: 3.
        4. FinishedDecisionMakerRound
        5. FinishedWithoutDecisionRound
        6. RefillRequiredRound
        7. ImpossibleRound

    Final states: {FinishedDecisionMakerRound, FinishedWithoutDecisionRound, ImpossibleRound, RefillRequiredRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: AppState = SamplingRound
    initial_states: Set[AppState] = {SamplingRound, BlacklistingRound}
    transition_function: AbciAppTransitionFunction = {
        SamplingRound: {
            Event.DONE: DecisionRequestRound,
            Event.NONE: FinishedWithoutDecisionRound,
            Event.NO_MAJORITY: SamplingRound,
            Event.ROUND_TIMEOUT: SamplingRound,
        },
        DecisionRequestRound: {
            Event.DONE: BetPlacementRound,
            Event.SLOTS_UNSUPPORTED_ERROR: BlacklistingRound,
            Event.NO_MAJORITY: DecisionRequestRound,
            Event.NON_BINARY: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.TIE: BlacklistingRound,
            Event.UNPROFITABLE: BlacklistingRound,
            Event.ROUND_TIMEOUT: DecisionRequestRound,
        },
        BlacklistingRound: {
            Event.DONE: FinishedWithoutDecisionRound,
            Event.NONE: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.NO_MAJORITY: BlacklistingRound,
            Event.ROUND_TIMEOUT: BlacklistingRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            MarketManagerEvent.FETCH_ERROR: ImpossibleRound,
        },
        BetPlacementRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,  # degenerate round on purpose, owner must refill the safe
            Event.NO_MAJORITY: BetPlacementRound,
            Event.ROUND_TIMEOUT: BetPlacementRound,
        },
        FinishedDecisionMakerRound: {},
        FinishedWithoutDecisionRound: {},
        RefillRequiredRound: {},
        ImpossibleRound: {},
    }
    final_states: Set[AppState] = {
        FinishedDecisionMakerRound,
        FinishedWithoutDecisionRound,
        RefillRequiredRound,
        ImpossibleRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        BlacklistingRound: {
            get_name(SynchronizedData.bets),
        },
        SamplingRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedDecisionMakerRound: {
            get_name(SynchronizedData.sampled_bet_index),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedWithoutDecisionRound: {get_name(SynchronizedData.sampled_bet_index)},
        RefillRequiredRound: set(),
        ImpossibleRound: set(),
    }
