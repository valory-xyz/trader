# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This package contains the rounds of MechInteractAbciApp."""

from typing import Dict, Set

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    EventToTimeout,
    get_name,
)
from packages.valory.skills.mech_interact_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.mech_interact_abci.states.final_states import (
    FinishedMechRequestRound,
    FinishedMechRequestSkipRound,
    FinishedMechResponseRound,
    FinishedMechResponseTimeoutRound,
)
from packages.valory.skills.mech_interact_abci.states.request import MechRequestRound
from packages.valory.skills.mech_interact_abci.states.response import MechResponseRound


class MechInteractAbciApp(AbciApp[Event]):
    """MechInteractAbciApp

    Initial round: MechRequestRound

    Initial states: {MechRequestRound, MechResponseRound}

    Transition states:
        0. MechRequestRound
            - done: 2.
            - skip request: 5.
            - no majority: 0.
            - round timeout: 0.
        1. MechResponseRound
            - done: 3.
            - no majority: 1.
            - round timeout: 4.
        2. FinishedMechRequestRound
        3. FinishedMechResponseRound
        4. FinishedMechResponseTimeoutRound
        5. FinishedMechRequestSkipRound

    Final states: {FinishedMechRequestRound, FinishedMechRequestSkipRound, FinishedMechResponseRound, FinishedMechResponseTimeoutRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: AppState = MechRequestRound
    initial_states: Set[AppState] = {MechRequestRound, MechResponseRound}
    transition_function: AbciAppTransitionFunction = {
        MechRequestRound: {
            Event.DONE: FinishedMechRequestRound,
            Event.SKIP_REQUEST: FinishedMechRequestSkipRound,
            Event.NO_MAJORITY: MechRequestRound,
            Event.ROUND_TIMEOUT: MechRequestRound,
        },
        MechResponseRound: {
            Event.DONE: FinishedMechResponseRound,
            Event.NO_MAJORITY: MechResponseRound,
            Event.ROUND_TIMEOUT: FinishedMechResponseTimeoutRound,
        },
        FinishedMechRequestRound: {},
        FinishedMechResponseRound: {},
        FinishedMechResponseTimeoutRound: {},
        FinishedMechRequestSkipRound: {},
    }
    final_states: Set[AppState] = {
        FinishedMechRequestRound,
        FinishedMechResponseRound,
        FinishedMechResponseTimeoutRound,
        FinishedMechRequestSkipRound,
    }
    event_to_timeout: EventToTimeout = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    cross_period_persisted_keys: Set[str] = {get_name(SynchronizedData.mech_responses)}
    db_pre_conditions: Dict[AppState, Set[str]] = {
        # using `set(get_name(SynchronizedData.mech_requests))`
        # makes the checks complain that "db pre and post conditions intersect"
        MechRequestRound: set(),
        # we should be able to include `SynchronizedData.final_tx_hash` in the set below,
        # however, we can't, because the checks incorrectly report that "db pre and post conditions intersect"
        MechResponseRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedMechRequestRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
            get_name(SynchronizedData.mech_price),
        },
        FinishedMechRequestSkipRound: set(),
        FinishedMechResponseRound: set(get_name(SynchronizedData.mech_responses)),
        FinishedMechResponseTimeoutRound: set(),
    }
