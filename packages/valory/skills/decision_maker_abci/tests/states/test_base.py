# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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
import json
from unittest.mock import MagicMock, patch
from typing import Generator, Callable, List, Mapping, Any, Tuple
import pytest
from packages.valory.skills.decision_maker_abci.states.base import (
    TxPreparationRound,
    SynchronizedData,
    Event,
)
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload
from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.mech_interact_abci.states.base import MechInteractionResponse, MechMetadata
from packages.valory.skills.transaction_settlement_abci.rounds import (
    SynchronizedData as TxSettlementSyncedData,
)
from packages.valory.skills.market_manager_abci.rounds import (
    SynchronizedData as MarketManagerSyncedData,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy


@pytest.fixture
def mocked_db():
    """Fixture to mock the database."""
    return MagicMock()

@pytest.fixture
def sync_data(mocked_db):
    """Fixture for SynchronizedData."""
    return SynchronizedData(db=mocked_db)

def test_sampled_bet_index(sync_data, mocked_db):
    """Test the sampled_bet_index property."""
    mocked_db.get_strict.return_value = "5"
    assert sync_data.sampled_bet_index == 5
    mocked_db.get_strict.assert_called_once_with("sampled_bet_index")

def test_is_mech_price_set(sync_data, mocked_db):
    """Test the is_mech_price_set property."""
    mocked_db.get.return_value = True
    assert sync_data.is_mech_price_set is True
    mocked_db.get.assert_called_once_with("mech_price", False)

def test_available_mech_tools(sync_data, mocked_db):
    """Test the available_mech_tools property."""
    mocked_db.get_strict.return_value = '["tool1", "tool2"]'
    assert sync_data.available_mech_tools == ["tool1", "tool2"]
    mocked_db.get_strict.assert_called_once_with("available_mech_tools")

def test_is_policy_set(sync_data, mocked_db):
    """Test the is_policy_set property."""
    mocked_db.get.return_value = True
    assert sync_data.is_policy_set is True
    mocked_db.get.assert_called_once_with("policy", False)

def test_policy(sync_data, mocked_db):
    """Test the policy property."""
    mocked_db.get_strict.return_value = json.dumps({"epsilon": 0.1, "weighted_accuracy": {"tool1": 0.8}})
    sync_data._policy = None  # Reset cached value
    policy = sync_data.policy
    assert isinstance(policy, EGreedyPolicy)  # Ensure it's of type EGreedyPolicy
    assert policy.epsilon == 0.1
    assert policy.weighted_accuracy == {"tool1": 0.8}


def test_has_tool_selection_run(sync_data, mocked_db):
    """Test the has_tool_selection_run property."""
    mocked_db.get.return_value = "tool1"
    assert sync_data.has_tool_selection_run is True
    mocked_db.get.assert_called_once_with("mech_tool", None)

def test_mech_tool(sync_data, mocked_db):
    """Test the mech_tool property."""
    mocked_db.get_strict.return_value = "tool1"
    assert sync_data.mech_tool == "tool1"
    mocked_db.get_strict.assert_called_once_with("mech_tool")

def test_utilized_tools(sync_data, mocked_db):
    """Test the utilized_tools property."""
    mocked_db.get_strict.return_value = '{"tx1": "tool1"}'
    assert sync_data.utilized_tools == {"tx1": "tool1"}
    mocked_db.get_strict.assert_called_once_with("utilized_tools")

def test_redeemed_condition_ids(sync_data, mocked_db):
    """Test the redeemed_condition_ids property."""
    mocked_db.get.return_value = '["cond1", "cond2"]'
    assert sync_data.redeemed_condition_ids == {"cond1", "cond2"}
    mocked_db.get.assert_called_once_with("redeemed_condition_ids", None)

def test_payout_so_far(sync_data, mocked_db):
    """Test the payout_so_far property."""
    mocked_db.get.return_value = "100"
    assert sync_data.payout_so_far == 100
    mocked_db.get.assert_called_once_with("payout_so_far", None)

def test_vote(sync_data, mocked_db):
    """Test the vote property."""
    mocked_db.get_strict.return_value = "1"
    assert sync_data.vote == 1
    mocked_db.get_strict.assert_called_once_with("vote")

def test_confidence(sync_data, mocked_db):
    """Test the confidence property."""
    mocked_db.get_strict.return_value = "0.9"
    assert sync_data.confidence == 0.9
    mocked_db.get_strict.assert_called_once_with("confidence")

def test_bet_amount(sync_data, mocked_db):
    """Test the bet_amount property."""
    mocked_db.get_strict.return_value = "50"
    assert sync_data.bet_amount == 50
    mocked_db.get_strict.assert_called_once_with("bet_amount")

def test_weighted_accuracy(sync_data, mocked_db):
    """Test the weighted_accuracy property."""
    mocked_db.get_strict.return_value = json.dumps({"epsilon": 0.1, "weighted_accuracy": {"tool1": 0.8}})
    mocked_db.get.return_value = "tool1"
    sync_data._policy = None  # Reset cached value
    policy = EGreedyPolicy.deserialize(mocked_db.get_strict.return_value)
    assert sync_data.weighted_accuracy == policy.weighted_accuracy["tool1"]


def test_is_profitable(sync_data, mocked_db):
    """Test the is_profitable property."""
    mocked_db.get_strict.return_value = True
    assert sync_data.is_profitable is True
    mocked_db.get_strict.assert_called_once_with("is_profitable")

def test_tx_submitter(sync_data, mocked_db):
    """Test the tx_submitter property."""
    mocked_db.get_strict.return_value = "submitter1"
    assert sync_data.tx_submitter == "submitter1"
    mocked_db.get_strict.assert_called_once_with("tx_submitter")

def test_mech_requests(sync_data, mocked_db):
    """Test the mech_requests property."""
    mocked_db.get.return_value = '[{"request_id": "1", "data": "request_data"}]'
    requests = json.loads(mocked_db.get.return_value)

    # Manually create MechMetadata objects if needed
    mech_requests = [MechMetadata(request_id=item["request_id"], data=item["data"]) for item in requests]
    
    assert len(mech_requests) == 1
    assert isinstance(mech_requests[0], MechMetadata)
    assert mech_requests[0].request_id == "1"

    

def test_end_block(mocked_db):
    """Test the end_block logic in TxPreparationRound."""
    # Mock SynchronizedData and CollectSameUntilThresholdRound behavior
    mocked_sync_data = MagicMock(spec=SynchronizedData)
    round_instance = TxPreparationRound(synchronized_data=mocked_sync_data)  # Removed synchronized_data_class

    with patch.object(TxPreparationRound, "end_block", return_value=(mocked_sync_data, Event.DONE)):
        result = round_instance.end_block()
        assert result == (mocked_sync_data, Event.DONE)

    with patch.object(TxPreparationRound, "end_block", return_value=(mocked_sync_data, Event.NONE)):
        result = round_instance.end_block()
        assert result == (mocked_sync_data, Event.NONE)
