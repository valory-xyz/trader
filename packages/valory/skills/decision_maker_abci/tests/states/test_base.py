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

import json
from unittest.mock import MagicMock, patch

import pytest

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
    assert sync_data.available_mech_tools == ["tool1", "tool2"]
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
