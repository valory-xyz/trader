# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the rounds for the agent performance summary ABCI application."""

from abc import ABC
from enum import Enum
from typing import Dict, Set, Type

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
from packages.valory.skills.agent_performance_summary_abci.payloads import (
    FetchPerformanceDataPayload,
)


class Event(Enum):
    """Events triggering state transitions in the Agent Performance Summary ABCI app."""

    DONE = "done"
    NONE = "none"
    FAIL = "fail"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"


class FetchPerformanceDataRound(VotingRound):
    """A round for fetching and saving Agent Performance summary."""

    payload_class = FetchPerformanceDataPayload
    synchronized_data_class = BaseSynchronizedData
    done_event = Event.DONE
    negative_event = Event.FAIL
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(BaseSynchronizedData.participant_to_votes)


class FinishedFetchPerformanceDataRound(DegenerateRound, ABC):
    """A terminal round indicating that performance data collection is complete."""


class AgentPerformanceSummaryAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """AgentPerformanceSummaryAbciApp

    Initial round: FetchPerformanceDataRound

    Initial states: {FetchPerformanceDataRound}

    Transition states:
        0. FetchPerformanceDataRound
            - done: 1.
            - none: 0.
            - fail: 1.
            - round timeout: 1.
            - no majority: 0.
        1. FinishedFetchPerformanceDataRound

    Final states: {FinishedFetchPerformanceDataRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = FetchPerformanceDataRound
    transition_function: AbciAppTransitionFunction = {
        FetchPerformanceDataRound: {
            Event.DONE: FinishedFetchPerformanceDataRound,
            Event.NONE: FetchPerformanceDataRound,
            Event.FAIL: FinishedFetchPerformanceDataRound,
            Event.ROUND_TIMEOUT: FinishedFetchPerformanceDataRound,
            Event.NO_MAJORITY: FetchPerformanceDataRound,
        },
        FinishedFetchPerformanceDataRound: {},
    }
    final_states: Set[AppState] = {
        FinishedFetchPerformanceDataRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {FetchPerformanceDataRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedFetchPerformanceDataRound: set(),
    }
