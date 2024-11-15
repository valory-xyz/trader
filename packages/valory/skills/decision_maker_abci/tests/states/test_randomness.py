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


"""This module contains test cases for the RandomnessRound class."""

import pytest

from packages.valory.skills.decision_maker_abci.rounds import RandomnessRound
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.transaction_settlement_abci.rounds import (
    RandomnessTransactionSubmissionRound,
)


class MockSynchronizedData:
    """A mock class for SynchronizedData to provide necessary attributes."""

    pass


class MockContext:
    """A mock class for context used in RandomnessTransactionSubmissionRound."""

    def __init__(self) -> None:
        """Initialize the MockContext with necessary attributes."""
        self.sender = "mock_sender"


class TestRandomnessRound:
    """Test suite for the RandomnessRound class."""

    @pytest.fixture
    def setup_randomness_round(self) -> RandomnessRound:
        """Fixture to set up a RandomnessRound instance."""
        context = MockContext()
        synchronized_data = MockSynchronizedData()
        return RandomnessRound(context=context, synchronized_data=synchronized_data)

    def test_randomness_round_properties(
        self, setup_randomness_round: RandomnessRound
    ) -> None:
        """Test the properties of the RandomnessRound class."""
        randomness_round = setup_randomness_round

        assert randomness_round.done_event == Event.DONE
        assert randomness_round.no_majority_event == Event.NO_MAJORITY

    def test_randomness_round_inherits_randomness_transaction_submission_round(
        self,
    ) -> None:
        """Test that RandomnessRound inherits from RandomnessTransactionSubmissionRound."""
        assert issubclass(RandomnessRound, RandomnessTransactionSubmissionRound)
