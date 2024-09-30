import pytest
from unittest.mock import MagicMock, patch
from collections import Counter
from packages.valory.skills.decision_maker_abci.states.order_subscription import SubscriptionRound
from packages.valory.skills.decision_maker_abci.states.base import Event

@pytest.fixture
def mock_context():
    """Fixture for the context."""
    context = MagicMock()
    context.benchmarking_mode.enabled = False
    return context

@pytest.fixture
def mock_sync_data():
    """Fixture for the synchronized data."""
    return MagicMock()

@pytest.fixture
def subscription_round(mock_sync_data, mock_context):
    """Fixture for SubscriptionRound."""
    round_instance = SubscriptionRound(synchronized_data=mock_sync_data, context=mock_context)

    # Mocking the payload_values_count property to return a Counter
    def mock_payload_values_count():
        return Counter({
            ("payload_1",): 2,
            ("payload_2",): 1,
        })

    # Use a property to mock payload_values_count
    round_instance.payload_values_count = property(mock_payload_values_count)

    # Mocking the most_voted_payload_values property
    round_instance.most_voted_payload_values = MagicMock(return_value=((), "valid_tx_hash", "", "agreement_id"))

    # Mocking the threshold_reached property
    round_instance.threshold_reached = True

    return round_instance

def test_end_block_valid_tx(subscription_round):
    """Test end_block with a valid transaction hash."""
    subscription_round.most_voted_payload_values = ((), "valid_tx_hash", "", "agreement_id")
    
    sync_data, event = subscription_round.end_block()
    
    assert event != Event.SUBSCRIPTION_ERROR
    assert subscription_round.synchronized_data.update.called
    assert subscription_round.synchronized_data.update.call_args[1]['agreement_id'] == "agreement_id"

def test_end_block_no_tx(subscription_round):
    """Test end_block when there is no transaction payload."""
    subscription_round.most_voted_payload_values = ((), SubscriptionRound.NO_TX_PAYLOAD, "", "agreement_id")
    
    sync_data, event = subscription_round.end_block()
    
    assert event == Event.NO_SUBSCRIPTION
    subscription_round.synchronized_data.update.assert_not_called()

def test_end_block_error_tx(subscription_round):
    """Test end_block when the transaction hash is an error payload."""
    subscription_round.most_voted_payload_values = ((), SubscriptionRound.ERROR_PAYLOAD, "", "agreement_id")
    
    sync_data, event = subscription_round.end_block()
    
    assert event == Event.SUBSCRIPTION_ERROR
    subscription_round.synchronized_data.update.assert_not_called()

def test_end_block_benchmarking_mode(subscription_round, mock_context):
    """Test end_block in benchmarking mode."""
    mock_context.benchmarking_mode.enabled = True
    
    sync_data, event = subscription_round.end_block()
    
    assert event == Event.MOCK_TX
    subscription_round.synchronized_data.update.assert_not_called()

def test_end_block_threshold_not_reached(subscription_round):
    """Test end_block when the threshold is not reached."""
    subscription_round.threshold_reached = False
    assert subscription_round.end_block() is None
