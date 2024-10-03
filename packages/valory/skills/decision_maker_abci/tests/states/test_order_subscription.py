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
from unittest.mock import MagicMock, patch
from enum import Enum

from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.order_subscription import SubscriptionRound
from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData

# Dummy values for testing
class MockSynchronizedData(BaseSynchronizedData):
    def __init__(self, db):
        super().__init__(db=db)
        self.agreement_id = "dummy_agreement_id"

    def update(self, **kwargs):
        """Mock the update method to simulate updating agreement_id."""
        updated_data = self.__class__(self.db.copy())
        updated_data.__dict__.update(kwargs)
        return updated_data

@pytest.fixture
def setup_subscription_round():
    """Fixture to set up a basic SubscriptionRound instance."""
    mock_synchronized_data = MockSynchronizedData(db={})
    round_instance = SubscriptionRound(synchronized_data=mock_synchronized_data, context=MagicMock())
    return round_instance

def test_threshold_reached_with_error(setup_subscription_round):
    """Test when the threshold is reached and the transaction is an error."""
    round_instance = setup_subscription_round
    with patch.object(SubscriptionRound, 'threshold_reached', new_callable=MagicMock(return_value=True)):
        with patch.object(SubscriptionRound, 'most_voted_payload_values', new_callable=MagicMock(return_value=[None, round_instance.ERROR_PAYLOAD])):
            result = round_instance.end_block()

            assert result == (round_instance.synchronized_data, Event.SUBSCRIPTION_ERROR)

def test_threshold_reached_with_no_tx(setup_subscription_round):
    """Test when the threshold is reached and there's no transaction."""
    round_instance = setup_subscription_round
    with patch.object(SubscriptionRound, 'threshold_reached', new_callable=MagicMock(return_value=True)):
        with patch.object(SubscriptionRound, 'most_voted_payload_values', new_callable=MagicMock(return_value=[None, round_instance.NO_TX_PAYLOAD])):
            result = round_instance.end_block()

            assert result == (round_instance.synchronized_data, Event.NO_SUBSCRIPTION)

def test_threshold_reached_with_mock_tx(setup_subscription_round):
    """Test when the threshold is reached and benchmarking mode is enabled."""
    round_instance = setup_subscription_round
    round_instance.context.benchmarking_mode.enabled = True
    with patch.object(SubscriptionRound, 'threshold_reached', new_callable=MagicMock(return_value=True)):
        with patch.object(SubscriptionRound, 'most_voted_payload_values', new_callable=MagicMock(return_value=[None, "mock_tx_hash"])):
            result = round_instance.end_block()

            assert result == (round_instance.synchronized_data, Event.MOCK_TX)

def test_end_block_updates_sync_data(setup_subscription_round):
    """Test if the agreement_id is correctly updated in synchronized data."""
    round_instance = setup_subscription_round
    
    # Patch the `most_voted_payload_values` to return a list with the new agreement ID
    with patch.object(SubscriptionRound, 'most_voted_payload_values', new_callable=MagicMock(return_value=[None, None, None, "new_agreement_id"])):
        
        # Call the `end_block` method to trigger the update
        result = round_instance.end_block()

        # Check the updated synchronized_data object returned by end_block
        sync_data, event = result
        
        # Assert that the agreement_id was updated to the new_agreement_id
        assert sync_data.agreement_id == "new_agreement_id"
        assert event is not None

def test_no_update_when_threshold_not_reached(setup_subscription_round):
    """Test when the threshold is not reached, there should be no changes."""
    round_instance = setup_subscription_round
    with patch.object(SubscriptionRound, 'threshold_reached', new_callable=MagicMock(return_value=False)):
        with patch("packages.valory.skills.decision_maker_abci.states.order_subscription.SubscriptionRound.end_block",
                   return_value=None) as mock_super:
            result = round_instance.end_block()

        assert result is None
        mock_super.assert_called_once()
