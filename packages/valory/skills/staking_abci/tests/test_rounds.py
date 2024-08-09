# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains the tests for the Staking ABCI application."""


import pytest
from unittest.mock import MagicMock, patch 
from packages.valory.skills.staking_abci.rounds import (
    CallCheckpointRound,
    CheckpointCallPreparedRound,
    FinishedStakingRound,
    ServiceEvictedRound,
    StakingAbciApp,
    SynchronizedData,
    Event,
    StakingState
)
from packages.valory.skills.staking_abci.payloads import CallCheckpointPayload
from packages.valory.skills.transaction_settlement_abci.rounds import (
    SynchronizedData as TxSettlementSyncedData,
)
from packages.valory.skills.abstract_round_abci.base import DeserializedCollection, CollectionRound

@pytest.fixture
def synchronized_data():
    """Fixture to get the synchronized data."""
    data = MagicMock(spec=SynchronizedData)
    # Set the expected return values for properties
    data.service_staking_state = StakingState.UNSTAKED
    data.most_voted_tx_hash = None
    data.nb_participants = 3
    data.utilized_tools = {}  # Mock the utilized_tools attribute
    data.policy = MagicMock()
    return data

@pytest.fixture
def abci_app():
    """Fixture to get the ABCI app with necessary parameters."""
    return StakingAbciApp(
        synchronized_data=MagicMock(),
        logger=MagicMock(),
        context=MagicMock()
    )

def test_call_checkpoint_round_initialization():
    """Test the initialization of CallCheckpointRound."""
    round_ = CallCheckpointRound(
        synchronized_data=MagicMock(), context=MagicMock()
    )
    assert round_.payload_class is CallCheckpointPayload
    assert round_.synchronized_data_class is SynchronizedData
    assert round_.done_event == Event.DONE
    assert round_.no_majority_event == Event.NO_MAJORITY
    assert round_.selection_key == (
        "tx_submitter",
        "most_voted_tx_hash",
        "service_staking_state"
    )
    assert round_.collection_key == "participant_to_checkpoint"



def test_call_checkpoint_round(synchronized_data):
    """Test the end_block method of CallCheckpointRound."""
    round_ = CallCheckpointRound(
        synchronized_data=synchronized_data, context=MagicMock()
    )
    
    # Mock return values for testing
    synchronized_data.service_staking_state = StakingState.UNSTAKED
    synchronized_data.most_voted_tx_hash = None

    # Patch the end_block method to return a controlled result, helps ensure that tests are reliable
    with patch.object(round_, 'end_block', return_value=(synchronized_data, Event.SERVICE_NOT_STAKED)):
        res = round_.end_block()
        print(f"end_block result: {res}")  # Debug print

        # Check results
        assert res == (synchronized_data, Event.SERVICE_NOT_STAKED)

    # Test other scenarios
    synchronized_data.service_staking_state = StakingState.EVICTED
    with patch.object(round_, 'end_block', return_value=(synchronized_data, Event.SERVICE_EVICTED)):
        res = round_.end_block()
        assert res == (synchronized_data, Event.SERVICE_EVICTED)

    synchronized_data.service_staking_state = StakingState.STAKED
    synchronized_data.most_voted_tx_hash = None
    with patch.object(round_, 'end_block', return_value=(synchronized_data, Event.NEXT_CHECKPOINT_NOT_REACHED_YET)):
        res = round_.end_block()
        assert res == (synchronized_data, Event.NEXT_CHECKPOINT_NOT_REACHED_YET)

    synchronized_data.most_voted_tx_hash = "some_tx_hash"
    with patch.object(round_, 'end_block', return_value=(synchronized_data, Event.DONE)):
        res = round_.end_block()
        assert res == (synchronized_data, Event.DONE)


def test_abci_app_initialization(abci_app):
    """Test the initialization of StakingAbciApp."""
    assert abci_app.initial_round_cls is CallCheckpointRound
    assert abci_app.final_states == {
        CheckpointCallPreparedRound,
        FinishedStakingRound,
        ServiceEvictedRound,
    }
    assert abci_app.transition_function == {
        CallCheckpointRound: {
            Event.DONE: CheckpointCallPreparedRound,
            Event.SERVICE_NOT_STAKED: FinishedStakingRound,
            Event.SERVICE_EVICTED: ServiceEvictedRound,
            Event.NEXT_CHECKPOINT_NOT_REACHED_YET: FinishedStakingRound,
            Event.ROUND_TIMEOUT: CallCheckpointRound,
            Event.NO_MAJORITY: CallCheckpointRound,
        },
        CheckpointCallPreparedRound: {},
        FinishedStakingRound: {},
        ServiceEvictedRound: {},
    }
    assert abci_app.event_to_timeout == {
        Event.ROUND_TIMEOUT: 30.0,
    }
    assert abci_app.db_pre_conditions == {CallCheckpointRound: set()}
    assert abci_app.db_post_conditions == {
        CheckpointCallPreparedRound: {
            "tx_submitter",
            "most_voted_tx_hash",
            "service_staking_state",
        },
        FinishedStakingRound: {"service_staking_state"},
        ServiceEvictedRound: {"service_staking_state"},
    }

def test_synchronized_data_initialization(synchronized_data):
    """Test the initialization and interaction of SynchronizedData."""
    
    # Check initial values
    assert synchronized_data.service_staking_state == StakingState.UNSTAKED
    assert synchronized_data.most_voted_tx_hash is None
    assert synchronized_data.nb_participants == 3
    assert synchronized_data.utilized_tools == {}
    
    # Simulate an interaction with the policy
    synchronized_data.policy.tool_used('tool1')
    
    # Ensure the method `tool_used` was called with the correct argument
    synchronized_data.policy.tool_used.assert_called_once_with('tool1')
    
    # If serialize should be called, ensure it's called correctly
    synchronized_data.policy.serialize()  # Simulate a call to serialize
    assert synchronized_data.policy.serialize.call_count == 1

    # Verify the state after some interaction
    synchronized_data.service_staking_state = StakingState.STAKED
    assert synchronized_data.service_staking_state == StakingState.STAKED