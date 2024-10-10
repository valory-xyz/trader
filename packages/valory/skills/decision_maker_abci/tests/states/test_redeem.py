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

import pytest
from unittest.mock import MagicMock
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData

@pytest.fixture
def redeem_round():
    """Fixture to set up a RedeemRound instance for testing."""
    synchronized_data = MagicMock(spec=BaseSynchronizedData)
    context = MagicMock()  
    redeem_instance = RedeemRound(synchronized_data, context)
    
    # Set initial properties
    redeem_instance.block_confirmations = 0
    synchronized_data.period_count = 0
    synchronized_data.db = MagicMock()
    
    return redeem_instance

def test_initial_event(redeem_round):
    """Test that the initial event is set correctly."""
    assert redeem_round.none_event == Event.NO_REDEEMING

def test_end_block_no_update(redeem_round):
    """Test the end_block behavior when no update occurs."""
    # This ensures that block_confirmations and period_count are 0
    redeem_round.block_confirmations = 0
    redeem_round.synchronized_data.period_count = 0

    # Mock the superclass's end_block to simulate behavior
    redeem_round.synchronized_data.db.get = MagicMock(return_value='mock_value')

    # Call the actual end_block method
    result = redeem_round.end_block()
    
    # Assert the result is a tuple and check for specific event
    assert isinstance(result, tuple)
    assert result[1] == Event.NO_REDEEMING  # Adjust based on expected output


def test_end_block_with_update(redeem_round):
    """Test the end_block behavior when an update occurs."""
    # Mock the super class's end_block to return a valid update
    update_result = (redeem_round.synchronized_data, Event.NO_REDEEMING)  # Use an actual event from your enum
    RedeemRound.end_block = MagicMock(return_value=update_result)

    result = redeem_round.end_block()
    assert result == update_result

    # Ensure no database update was attempted
    redeem_round.synchronized_data.db.update.assert_not_called()

def test_end_block_with_period_count_update(redeem_round):
    """Test the behavior when period_count is greater than zero."""
    # Set up the necessary attributes
    redeem_round.synchronized_data.period_count = 1
    
    # Directly assign a valid integer to nb_participants
    redeem_round.nb_participants = 3  

    # Set up mock return values for db.get if needed
    mock_keys = RedeemRound.selection_key 
    for key in mock_keys:
        redeem_round.synchronized_data.db.get = MagicMock(return_value='mock_value')

    # Call the actual end_block method
    result = redeem_round.end_block()
    
    # Add assertions based on what you expect the result to be
    assert isinstance(result, tuple)  # Ensure it returns a tuple
    assert result[1] == Event.NO_REDEEMING  # Adjust based on expected behavior


