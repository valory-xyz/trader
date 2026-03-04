# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""This module contains tests for rounds of the agent_performance_summary_abci skill."""

from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    DegenerateRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.agent_performance_summary_abci.payloads import (
    FetchPerformanceDataPayload,
    UpdateAchievementsPayload,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
    Event,
    FetchPerformanceDataRound,
    FinishedFetchPerformanceDataRound,
    UpdateAchievementsRound,
)


class TestEvent:
    """Tests for the Event enum."""

    def test_done_value(self) -> None:
        """Test DONE event value."""
        assert Event.DONE.value == "done"

    def test_none_value(self) -> None:
        """Test NONE event value."""
        assert Event.NONE.value == "none"

    def test_fail_value(self) -> None:
        """Test FAIL event value."""
        assert Event.FAIL.value == "fail"

    def test_round_timeout_value(self) -> None:
        """Test ROUND_TIMEOUT event value."""
        assert Event.ROUND_TIMEOUT.value == "round_timeout"

    def test_no_majority_value(self) -> None:
        """Test NO_MAJORITY event value."""
        assert Event.NO_MAJORITY.value == "no_majority"

    def test_event_count(self) -> None:
        """Test that there are exactly 5 events."""
        assert len(Event) == 5


class TestFetchPerformanceDataRound:
    """Tests for FetchPerformanceDataRound."""

    def test_is_voting_round(self) -> None:
        """Test that FetchPerformanceDataRound is a VotingRound."""
        assert issubclass(FetchPerformanceDataRound, VotingRound)

    def test_payload_class(self) -> None:
        """Test payload_class attribute."""
        assert FetchPerformanceDataRound.payload_class is FetchPerformanceDataPayload

    def test_synchronized_data_class(self) -> None:
        """Test synchronized_data_class attribute."""
        assert (
            FetchPerformanceDataRound.synchronized_data_class is BaseSynchronizedData
        )

    def test_done_event(self) -> None:
        """Test done_event attribute."""
        assert FetchPerformanceDataRound.done_event == Event.DONE

    def test_negative_event(self) -> None:
        """Test negative_event attribute."""
        assert FetchPerformanceDataRound.negative_event == Event.FAIL

    def test_none_event(self) -> None:
        """Test none_event attribute."""
        assert FetchPerformanceDataRound.none_event == Event.NONE

    def test_no_majority_event(self) -> None:
        """Test no_majority_event attribute."""
        assert FetchPerformanceDataRound.no_majority_event == Event.NO_MAJORITY

    def test_collection_key(self) -> None:
        """Test collection_key attribute."""
        assert FetchPerformanceDataRound.collection_key == get_name(
            BaseSynchronizedData.participant_to_votes
        )


class TestUpdateAchievementsRound:
    """Tests for UpdateAchievementsRound."""

    def test_is_voting_round(self) -> None:
        """Test that UpdateAchievementsRound is a VotingRound."""
        assert issubclass(UpdateAchievementsRound, VotingRound)

    def test_payload_class(self) -> None:
        """Test payload_class attribute."""
        assert UpdateAchievementsRound.payload_class is UpdateAchievementsPayload

    def test_synchronized_data_class(self) -> None:
        """Test synchronized_data_class attribute."""
        assert UpdateAchievementsRound.synchronized_data_class is BaseSynchronizedData

    def test_done_event(self) -> None:
        """Test done_event attribute."""
        assert UpdateAchievementsRound.done_event == Event.DONE

    def test_negative_event(self) -> None:
        """Test negative_event attribute."""
        assert UpdateAchievementsRound.negative_event == Event.FAIL

    def test_none_event(self) -> None:
        """Test none_event attribute."""
        assert UpdateAchievementsRound.none_event == Event.NONE

    def test_no_majority_event(self) -> None:
        """Test no_majority_event attribute."""
        assert UpdateAchievementsRound.no_majority_event == Event.NO_MAJORITY

    def test_collection_key(self) -> None:
        """Test collection_key attribute."""
        assert UpdateAchievementsRound.collection_key == get_name(
            BaseSynchronizedData.participant_to_votes
        )


class TestFinishedFetchPerformanceDataRound:
    """Tests for FinishedFetchPerformanceDataRound."""

    def test_is_degenerate_round(self) -> None:
        """Test that FinishedFetchPerformanceDataRound is a DegenerateRound."""
        assert issubclass(FinishedFetchPerformanceDataRound, DegenerateRound)

    def test_initialization(self) -> None:
        """Test that FinishedFetchPerformanceDataRound can be instantiated."""
        round_ = FinishedFetchPerformanceDataRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedFetchPerformanceDataRound)


@pytest.fixture
def abci_app() -> AgentPerformanceSummaryAbciApp:
    """Fixture for AgentPerformanceSummaryAbciApp."""
    synchronized_data = MagicMock()
    logger = MagicMock()
    context = MagicMock()
    return AgentPerformanceSummaryAbciApp(
        synchronized_data=synchronized_data, logger=logger, context=context
    )


class TestAgentPerformanceSummaryAbciApp:
    """Tests for AgentPerformanceSummaryAbciApp."""

    def test_initial_round_cls(self, abci_app: AgentPerformanceSummaryAbciApp) -> None:
        """Test that the initial round class is FetchPerformanceDataRound."""
        assert abci_app.initial_round_cls is FetchPerformanceDataRound

    def test_final_states(self, abci_app: AgentPerformanceSummaryAbciApp) -> None:
        """Test final_states contains FinishedFetchPerformanceDataRound."""
        assert abci_app.final_states == {FinishedFetchPerformanceDataRound}

    def test_transition_function(
        self, abci_app: AgentPerformanceSummaryAbciApp
    ) -> None:
        """Test the transition function matches expected state transitions."""
        assert abci_app.transition_function == {
            FetchPerformanceDataRound: {
                Event.DONE: UpdateAchievementsRound,
                Event.NONE: FetchPerformanceDataRound,
                Event.FAIL: UpdateAchievementsRound,
                Event.ROUND_TIMEOUT: UpdateAchievementsRound,
                Event.NO_MAJORITY: FetchPerformanceDataRound,
            },
            UpdateAchievementsRound: {
                Event.DONE: FinishedFetchPerformanceDataRound,
                Event.NONE: FetchPerformanceDataRound,
                Event.FAIL: FinishedFetchPerformanceDataRound,
                Event.ROUND_TIMEOUT: FinishedFetchPerformanceDataRound,
                Event.NO_MAJORITY: FetchPerformanceDataRound,
            },
            FinishedFetchPerformanceDataRound: {},
        }

    def test_event_to_timeout(
        self, abci_app: AgentPerformanceSummaryAbciApp
    ) -> None:
        """Test event_to_timeout mapping."""
        assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}

    def test_db_pre_conditions(
        self, abci_app: AgentPerformanceSummaryAbciApp
    ) -> None:
        """Test db_pre_conditions."""
        assert abci_app.db_pre_conditions == {FetchPerformanceDataRound: set()}

    def test_db_post_conditions(
        self, abci_app: AgentPerformanceSummaryAbciApp
    ) -> None:
        """Test db_post_conditions."""
        assert abci_app.db_post_conditions == {
            FinishedFetchPerformanceDataRound: set(),
        }
