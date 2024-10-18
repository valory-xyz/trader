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


"""This package contains the tests for Decision Maker"""

import pytest

from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.rounds import SamplingRound
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.market_manager_abci.rounds import UpdateBetsRound


# Mock classes to simulate required attributes
class MockSynchronizedData(SynchronizedData):
    """A mock class for SynchronizedData to provide necessary attributes."""

    sampled_bet_index = 0  # Default value for sampled_bet_index


class MockContext:
    """A mock class for context used in AbstractRound."""

    def __init__(self):
        """Mock function"""
        self.sender = "mock_sender"
        self.bets_hash = "mock_bets_hash"


class TestSamplingRound:
    """The class for testing Sampling Round"""

    @pytest.fixture
    def setup_sampling_round(self):
        """Fixture to set up a SamplingRound instance."""
        context = MockContext()
        synchronized_data = MockSynchronizedData(
            db=dict()
        )  # Passing a mock dictionary for 'db'
        return SamplingRound(context=context, synchronized_data=synchronized_data)

    def test_sampling_round_properties(self, setup_sampling_round):
        """Test the properties of the SamplingRound class."""
        sampling_round = setup_sampling_round

        assert sampling_round.payload_class == SamplingPayload
        assert sampling_round.done_event == Event.DONE
        assert sampling_round.none_event == Event.NONE
        assert sampling_round.no_majority_event == Event.NO_MAJORITY
        assert sampling_round.selection_key is not None

    def test_sampling_payload_initialization(self):
        """Test the initialization of the SamplingPayload."""
        # Adjust according to the actual initialization parameters
        payload = SamplingPayload(
            sender="mock_sender", bets_hash="mock_bets_hash", index=0
        )  # Added index
        assert payload is not None
        assert payload.sender == "mock_sender"
        assert payload.bets_hash == "mock_bets_hash"
        assert payload.index == 0  # Check that the index is correctly initialized

    def test_sampling_round_inherits_update_bets_round(self):
        """Test that SamplingRound inherits from UpdateBetsRound."""
        assert issubclass(SamplingRound, UpdateBetsRound)

    def test_sampling_round_selection_key(self, setup_sampling_round):
        """Test the selection key property of SamplingRound."""
        sampling_round = setup_sampling_round
        expected_selection_key = (
            UpdateBetsRound.selection_key,
            get_name(
                SynchronizedData.sampled_bet_index
            ),  # Pass the property, not the value
        )
        assert sampling_round.selection_key == expected_selection_key

    def test_sampling_round_event_handling(self, setup_sampling_round):
        """Test event handling in SamplingRound."""
        sampling_round = setup_sampling_round
        sampling_round.current_event = None  # Simulating an initial state

        # Assuming the event changes the round's state
        sampling_round.current_event = Event.DONE
        assert sampling_round.current_event == Event.DONE

        sampling_round.current_event = Event.NO_MAJORITY
        assert sampling_round.current_event == Event.NO_MAJORITY
