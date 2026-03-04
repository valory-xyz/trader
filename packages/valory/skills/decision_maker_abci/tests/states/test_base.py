# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

import json
from enum import Enum
from typing import Optional, Tuple, cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    EGreedyPolicy,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class MechMetadata:
    """The class for test of Mech Data"""

    def __init__(self, request_id: str, data: str) -> None:
        """Initialize MechMetadata with request ID and data."""
        self.request_id = request_id
        self.data = data


@pytest.fixture
def mocked_db() -> MagicMock:
    """Fixture to mock the database."""
    return MagicMock()


@pytest.fixture
def sync_data(mocked_db: MagicMock) -> SynchronizedData:
    """Fixture for SynchronizedData."""
    return SynchronizedData(db=mocked_db)


def test_sampled_bet_index(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the sampled_bet_index property."""
    mocked_db.get_strict.return_value = "5"
    assert sync_data.sampled_bet_index == 5
    mocked_db.get_strict.assert_called_once_with("sampled_bet_index")


def test_is_mech_price_set(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the is_mech_price_set property."""
    mocked_db.get.return_value = True
    assert sync_data.is_mech_price_set is True
    mocked_db.get.assert_called_once_with("mech_price", False)


def test_available_mech_tools(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the available_mech_tools property."""
    mocked_db.get_strict.return_value = '["tool1", "tool2"]'
    assert sync_data.available_mech_tools == {"tool1", "tool2"}
    mocked_db.get_strict.assert_called_once_with("available_mech_tools")


def test_is_policy_set(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the is_policy_set property."""
    mocked_db.get.return_value = True
    assert sync_data.is_policy_set is True
    mocked_db.get.assert_called_once_with("policy", False)


def test_has_tool_selection_run(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the has_tool_selection_run property."""
    mocked_db.get.return_value = "tool1"
    assert sync_data.has_tool_selection_run is True
    mocked_db.get.assert_called_once_with("mech_tool", None)


def test_mech_tool(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the mech_tool property."""
    mocked_db.get_strict.return_value = "tool1"
    assert sync_data.mech_tool == "tool1"
    mocked_db.get_strict.assert_called_once_with("mech_tool")


def test_utilized_tools(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the utilized_tools property."""
    mocked_db.get_strict.return_value = '{"tx1": "tool1"}'
    assert sync_data.utilized_tools == {"tx1": "tool1"}
    mocked_db.get_strict.assert_called_once_with("utilized_tools")


def test_redeemed_condition_ids(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the redeemed_condition_ids property."""
    mocked_db.get.return_value = '["cond1", "cond2"]'
    assert sync_data.redeemed_condition_ids == {"cond1", "cond2"}
    mocked_db.get.assert_called_once_with("redeemed_condition_ids", None)


def test_payout_so_far(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the payout_so_far property."""
    mocked_db.get.return_value = "100"
    assert sync_data.payout_so_far == 100
    mocked_db.get.assert_called_once_with("payout_so_far", None)


def test_vote(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the vote property."""
    mocked_db.get_strict.return_value = "1"
    assert sync_data.vote == 1
    mocked_db.get_strict.assert_called_once_with("vote")


def test_confidence(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the confidence property."""
    mocked_db.get_strict.return_value = "0.9"
    assert sync_data.confidence == 0.9
    mocked_db.get_strict.assert_called_once_with("confidence")


def test_bet_amount(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the bet_amount property."""
    mocked_db.get_strict.return_value = "50"
    assert sync_data.bet_amount == 50
    mocked_db.get_strict.assert_called_once_with("bet_amount")


def test_is_profitable(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the is_profitable property."""
    mocked_db.get_strict.return_value = True
    assert sync_data.is_profitable is True
    mocked_db.get_strict.assert_called_once_with("is_profitable")


def test_tx_submitter(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the tx_submitter property."""
    mocked_db.get_strict.return_value = "submitter1"
    assert sync_data.tx_submitter == "submitter1"
    mocked_db.get_strict.assert_called_once_with("tx_submitter")


@patch("packages.valory.skills.decision_maker_abci.policy.EGreedyPolicy.deserialize")
def test_policy_property(
    mock_deserialize: MagicMock, sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test for policy property"""
    mock_policy_serialized = "serialized_policy_string"
    mocked_db.get_strict.return_value = mock_policy_serialized

    expected_policy = EGreedyPolicy(
        eps=0.1, consecutive_failures_threshold=1, quarantine_duration=0
    )
    mock_deserialize.return_value = expected_policy

    result = sync_data.policy

    mocked_db.get_strict.assert_called_once_with("policy")
    mock_deserialize.assert_called_once_with(mock_policy_serialized)
    assert result == expected_policy


def test_mech_requests(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the mech_requests property."""
    mocked_db.get.return_value = '[{"request_id": "1", "data": "request_data"}]'
    requests = json.loads(mocked_db.get.return_value)

    mech_requests = [
        MechMetadata(request_id=item["request_id"], data=item["data"])
        for item in requests
    ]

    assert len(mech_requests) == 1
    assert isinstance(mech_requests[0], MechMetadata)
    assert mech_requests[0].request_id == "1"


def test_weighted_accuracy(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the weighted_accuracy property."""
    selected_mech_tool = "tool1"
    policy_db_name = "policy"
    policy_mock = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=1,
        quarantine_duration=0,
        accuracy_store={selected_mech_tool: AccuracyInfo(requests=1)},
    ).serialize()
    mocked_db.get_strict = lambda name: (
        policy_mock if name == policy_db_name else selected_mech_tool
    )
    policy = EGreedyPolicy.deserialize(policy_mock)
    assert selected_mech_tool in policy.weighted_accuracy
    assert sync_data.weighted_accuracy == policy.weighted_accuracy[selected_mech_tool]


def test_mech_responses(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the mech_responses property."""

    # Mock the response with empty dictionaries to avoid field mismatches
    mocked_db.get.return_value = "[{}, {}]"

    # Access the mech_responses property
    responses = sync_data.mech_responses

    # Validate the responses length
    assert len(responses) == 2

    # Test when db.get() returns None
    mocked_db.get.return_value = None
    responses = sync_data.mech_responses
    assert responses == []

    # Test when db.get() returns an empty list
    mocked_db.get.return_value = "[]"
    responses = sync_data.mech_responses
    assert responses == []


def test_benchmarking_finished(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the benchmarking_finished property."""
    mocked_db.get_strict.return_value = True
    assert sync_data.benchmarking_finished is True
    mocked_db.get_strict.assert_called_once_with("benchmarking_finished")


def test_simulated_day(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the simulated_day property."""
    mocked_db.get_strict.return_value = False
    assert sync_data.simulated_day is False
    mocked_db.get_strict.assert_called_once_with("simulated_day")


def test_vote_none(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the vote property when it is None."""
    mocked_db.get_strict.return_value = None
    assert sync_data.vote is None


def test_previous_vote(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the previous_vote property."""
    mocked_db.get_strict.return_value = "2"
    assert sync_data.previous_vote == 2


def test_previous_vote_none(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the previous_vote property when None."""
    mocked_db.get_strict.return_value = None
    assert sync_data.previous_vote is None


def test_review_bets_for_selling_true(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test review_bets_for_selling when True."""
    mocked_db.get.return_value = True
    assert sync_data.review_bets_for_selling is True


def test_review_bets_for_selling_false(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test review_bets_for_selling when None."""
    mocked_db.get.return_value = None
    assert sync_data.review_bets_for_selling is False


def test_review_bets_for_selling_non_bool(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test review_bets_for_selling when value is not a bool."""
    mocked_db.get.return_value = "some_string"
    assert sync_data.review_bets_for_selling is False


def test_cached_signed_orders_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test cached_signed_orders when None."""
    mocked_db.get.return_value = None
    assert sync_data.cached_signed_orders == {}


def test_cached_signed_orders_with_data(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test cached_signed_orders with actual data."""
    mocked_db.get.return_value = '{"order1": "data1"}'
    assert sync_data.cached_signed_orders == {"order1": "data1"}


def test_weighted_accuracy_tool_not_in_store(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test weighted_accuracy raises when tool not in store."""
    selected_mech_tool = "nonexistent_tool"
    policy_mock = EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=1,
        quarantine_duration=0,
        accuracy_store={"tool1": AccuracyInfo(requests=1)},
    ).serialize()
    mocked_db.get_strict = lambda name: (
        policy_mock if name == "policy" else selected_mech_tool
    )
    with pytest.raises(ValueError, match="not available in the policy"):
        sync_data.weighted_accuracy


def test_did_transact_true(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test did_transact when tx_submitter is set."""
    mocked_db.get.return_value = "some_submitter"
    assert sync_data.did_transact is True


def test_did_transact_false(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test did_transact when tx_submitter is None."""
    mocked_db.get.return_value = None
    assert sync_data.did_transact is False


def test_mocking_mode(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the mocking_mode property."""
    mocked_db.get_strict.return_value = True
    assert sync_data.mocking_mode is True


def test_mocking_mode_none(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the mocking_mode property when None."""
    mocked_db.get_strict.return_value = None
    assert sync_data.mocking_mode is None


def test_next_mock_data_row(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the next_mock_data_row property."""
    mocked_db.get.return_value = 5
    assert sync_data.next_mock_data_row == 5


def test_next_mock_data_row_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the next_mock_data_row property when None."""
    mocked_db.get.return_value = None
    assert sync_data.next_mock_data_row == 1


def test_wallet_balance(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the wallet_balance property."""
    mocked_db.get.return_value = 1000
    assert sync_data.wallet_balance == 1000


def test_wallet_balance_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the wallet_balance property when None."""
    mocked_db.get.return_value = None
    assert sync_data.wallet_balance == 0


def test_decision_receive_timestamp(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the decision_receive_timestamp property."""
    mocked_db.get.return_value = 1234567890
    assert sync_data.decision_receive_timestamp == 1234567890


def test_decision_receive_timestamp_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the decision_receive_timestamp property when None."""
    mocked_db.get.return_value = None
    assert sync_data.decision_receive_timestamp == 0


def test_service_staking_state(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the service_staking_state property."""
    from packages.valory.skills.staking_abci.rounds import StakingState

    mocked_db.get.return_value = 0
    assert sync_data.service_staking_state == StakingState.UNSTAKED

    mocked_db.get.return_value = 1
    assert sync_data.service_staking_state == StakingState.STAKED

    mocked_db.get.return_value = 2
    assert sync_data.service_staking_state == StakingState.EVICTED


def test_is_staking_kpi_met(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the is_staking_kpi_met property."""
    mocked_db.get.return_value = True
    assert sync_data.is_staking_kpi_met is True


def test_after_bet_attempt(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the after_bet_attempt property."""
    mocked_db.get.return_value = True
    assert sync_data.after_bet_attempt is True


def test_should_be_sold_true(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the should_be_sold property when True."""
    mocked_db.get.return_value = True
    assert sync_data.should_be_sold is True


def test_should_be_sold_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the should_be_sold property when None."""
    mocked_db.get.return_value = None
    assert sync_data.should_be_sold is False


def test_should_be_sold_non_bool(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the should_be_sold property with non-bool value."""
    mocked_db.get.return_value = "some_string"
    assert sync_data.should_be_sold is False


def test_redeemed_condition_ids_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the redeemed_condition_ids property when None."""
    mocked_db.get.return_value = None
    assert sync_data.redeemed_condition_ids == set()


def test_payout_so_far_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the payout_so_far property when None."""
    mocked_db.get.return_value = None
    assert sync_data.payout_so_far == 0


def test_mech_requests_none(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the mech_requests property when None."""
    mocked_db.get.return_value = None
    requests = sync_data.mech_requests
    assert requests == []


def test_mech_requests_with_data(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the mech_requests property with valid serialized data."""
    mocked_db.get.return_value = "[]"
    requests = sync_data.mech_requests
    assert requests == []


def test_agreement_id(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the agreement_id property."""
    mocked_db.get_strict.return_value = "agreement_123"
    assert sync_data.agreement_id == "agreement_123"


def test_mech_price(sync_data: SynchronizedData, mocked_db: MagicMock) -> None:
    """Test the mech_price property."""
    mocked_db.get_strict.return_value = 100
    assert sync_data.mech_price == 100


def test_end_block(mocked_db: MagicMock) -> None:
    """Test the end_block logic in TxPreparationRound."""
    mocked_sync_data = MagicMock(spec=SynchronizedData)
    mock_context = MagicMock()
    round_instance = TxPreparationRound(
        synchronized_data=mocked_sync_data, context=mock_context
    )

    with patch.object(
        TxPreparationRound, "end_block", return_value=(mocked_sync_data, Event.DONE)
    ):
        result = round_instance.end_block()
        assert result == (mocked_sync_data, Event.DONE)

    with patch.object(
        TxPreparationRound, "end_block", return_value=(mocked_sync_data, Event.NONE)
    ):
        result = round_instance.end_block()
        assert result == (mocked_sync_data, Event.NONE)


def test_tx_preparation_round_end_block_returns_none() -> None:
    """Test TxPreparationRound end_block returns None when super returns None."""
    mock_synced_data = MagicMock(spec=SynchronizedData)
    mock_context = MagicMock()
    round_instance = TxPreparationRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(
        CollectSameUntilThresholdRound, "end_block", return_value=None
    ):
        result = round_instance.end_block()
    assert result is None


def test_tx_preparation_round_end_block_mocking_mode() -> None:
    """Test TxPreparationRound end_block with mocking_mode returns MOCK_TX."""
    mock_synced_data = MagicMock(spec=SynchronizedData)
    mock_synced_data.mocking_mode = True
    mock_context = MagicMock()
    round_instance = TxPreparationRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(
        CollectSameUntilThresholdRound,
        "end_block",
        return_value=(mock_synced_data, Event.DONE),
    ):
        result = round_instance.end_block()
    assert result is not None
    _, event = result
    assert event == Event.MOCK_TX


def test_tx_preparation_round_end_block_non_mocking_mode() -> None:
    """Test TxPreparationRound end_block without mocking_mode returns original event."""
    mock_synced_data = MagicMock(spec=SynchronizedData)
    mock_synced_data.mocking_mode = False
    mock_context = MagicMock()
    round_instance = TxPreparationRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(
        CollectSameUntilThresholdRound,
        "end_block",
        return_value=(mock_synced_data, Event.DONE),
    ):
        result = round_instance.end_block()
    assert result is not None
    _, event = result
    assert event == Event.DONE


def test_has_tool_selection_run_false(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test has_tool_selection_run when mech_tool is None."""
    mocked_db.get.return_value = None
    assert sync_data.has_tool_selection_run is False


def test_participant_to_decision(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the participant_to_decision property."""
    with patch.object(SynchronizedData, "_get_deserialized", return_value={"agent_0": "decision_0"}):
        result = sync_data.participant_to_decision
    assert result == {"agent_0": "decision_0"}


def test_participant_to_tx_prep(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the participant_to_tx_prep property."""
    with patch.object(SynchronizedData, "_get_deserialized", return_value={"agent_0": "tx_0"}):
        result = sync_data.participant_to_tx_prep
    assert result == {"agent_0": "tx_0"}


def test_participant_to_handle_failed_tx(
    sync_data: SynchronizedData, mocked_db: MagicMock
) -> None:
    """Test the participant_to_handle_failed_tx property."""
    with patch.object(SynchronizedData, "_get_deserialized", return_value={"agent_0": "failed_0"}):
        result = sync_data.participant_to_handle_failed_tx
    assert result == {"agent_0": "failed_0"}
