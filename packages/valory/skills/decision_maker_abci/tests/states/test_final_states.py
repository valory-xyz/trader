# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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


"""This package contains the tests for Decision Maker"""

from typing import Any, Dict, List, Tuple

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    BaseSynchronizedData,
    DegenerateRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    BenchmarkingDoneRound,
    BenchmarkingModeDisabledRound,
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    ImpossibleRound,
    RefillRequiredRound,
)


class MockSynchronizedData(BaseSynchronizedData):
    """A mock class for SynchronizedData."""

    def __init__(self, db: AbciAppDB) -> None:
        """Mock function"""
        super().__init__(db)  # Pass db to the parent class


class MockContext:
    """A mock class for context used in the rounds."""

    def __init__(self) -> None:
        """Mock function"""
        self.some_attribute = "mock_value"  # Add any necessary attributes here


class TestFinalStates:
    """The class for test of Final States"""

    @pytest.fixture
    def setup_round(self) -> Tuple[MockSynchronizedData, MockContext]:
        """Fixture to set up a round instance."""
        setup_data: Dict[str, List[Any]] = {}
        mock_db = AbciAppDB(setup_data)
        synchronized_data = MockSynchronizedData(db=mock_db)  # Provide a mock db value
        context = MockContext()
        return synchronized_data, context

    def test_benchmarking_mode_disabled_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of BenchmarkingModeDisabledRound."""
        synchronized_data, context = setup_round
        round_instance = BenchmarkingModeDisabledRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, BenchmarkingModeDisabledRound)
        assert isinstance(round_instance, DegenerateRound)

    def test_finished_decision_maker_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of FinishedDecisionMakerRound."""
        synchronized_data, context = setup_round
        round_instance = FinishedDecisionMakerRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, FinishedDecisionMakerRound)
        assert isinstance(round_instance, DegenerateRound)

    def test_finished_decision_request_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of FinishedDecisionRequestRound."""
        synchronized_data, context = setup_round
        round_instance = FinishedDecisionRequestRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, FinishedDecisionRequestRound)
        assert isinstance(round_instance, DegenerateRound)

    def test_finished_without_redeeming_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of FinishedWithoutRedeemingRound."""
        synchronized_data, context = setup_round
        round_instance = FinishedWithoutRedeemingRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, FinishedWithoutRedeemingRound)
        assert isinstance(round_instance, DegenerateRound)

    def test_finished_without_decision_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of FinishedWithoutDecisionRound."""
        synchronized_data, context = setup_round
        round_instance = FinishedWithoutDecisionRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, FinishedWithoutDecisionRound)
        assert isinstance(round_instance, DegenerateRound)

    def test_refill_required_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of RefillRequiredRound."""
        synchronized_data, context = setup_round
        round_instance = RefillRequiredRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, RefillRequiredRound)
        assert isinstance(round_instance, DegenerateRound)

    def test_benchmarking_done_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of BenchmarkingDoneRound and its end_block method."""
        synchronized_data, context = setup_round
        round_instance = BenchmarkingDoneRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, BenchmarkingDoneRound)
        assert isinstance(round_instance, DegenerateRound)

        # Test the end_block method
        with pytest.raises(SystemExit):
            round_instance.end_block()  # Should exit the program

    def test_impossible_round(
        self, setup_round: Tuple[MockSynchronizedData, MockContext]
    ) -> None:
        """Test instantiation of ImpossibleRound."""
        synchronized_data, context = setup_round
        round_instance = ImpossibleRound(
            context=context, synchronized_data=synchronized_data
        )
        assert isinstance(round_instance, ImpossibleRound)
        assert isinstance(round_instance, DegenerateRound)
