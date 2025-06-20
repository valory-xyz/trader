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

"""This package contains the tests for rounds of StakingAbciApp."""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    BaseTxPayload,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.staking_abci.payloads import CallCheckpointPayload
from packages.valory.skills.staking_abci.rounds import (
    CallCheckpointRound,
    CheckpointCallPreparedRound,
    Event,
    FinishedStakingRound,
    ServiceEvictedRound,
    StakingAbciApp,
    StakingState,
    SynchronizedData,
)


@pytest.fixture
def abci_app() -> StakingAbciApp:
    """Fixture for StakingAbciApp."""
    synchronized_data = MagicMock()
    logger = MagicMock()
    context = MagicMock()

    return StakingAbciApp(
        synchronized_data=synchronized_data, logger=logger, context=context
    )


DUMMY_SERVICE_STATE = {
    "service_staking_state": StakingState.UNSTAKED.value,
    "tx_submitter": "dummy_submitter",
    "tx_hash": "dummy_tx_hash",
    "ts_checkpoint": 0,
    "is_checkpoint_reached": True,
    "agent_ids": "[]",
    "service_id": None,
}


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_checkpoint_payloads(data: Dict) -> Mapping[str, CallCheckpointPayload]:
    """Get payloads."""
    return {
        participant: CallCheckpointPayload(
            participant,
            **data,
        )
        for participant in get_participants()
    }


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, BaseTxPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BaseStakingRoundTestClass(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for Staking rounds."""

    round_class = CallCheckpointRound
    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test"""
        # Set initial data
        self.synchronized_data.update(
            self._synchronized_data_class, **test_case.initial_data
        )

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=test_case.payloads,
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case.final_data
                ),
                synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
                most_voted_payload=test_case.most_voted_payload,
                exit_event=test_case.event,
            )
        )


class TestCallCheckpointRound(BaseStakingRoundTestClass):
    """Tests for CallCheckpointRound."""

    round_class = CallCheckpointRound

    @pytest.mark.parametrize(
        "test_case",
        [
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_checkpoint_payloads(
                    {
                        "service_staking_state": StakingState.STAKED.value,
                        "tx_submitter": "dummy_submitter",
                        "tx_hash": "dummy_tx_hash",
                        "ts_checkpoint": 0,
                        "is_checkpoint_reached": True,
                        "agent_ids": "[]",
                        "service_id": None,
                    }
                ),
                final_data={
                    "service_staking_state": StakingState.STAKED.value,
                    "tx_submitter": "dummy_submitter",
                    "tx_hash": "dummy_tx_hash",
                    "ts_checkpoint": 0,
                    "is_checkpoint_reached": True,
                    "agent_ids": "[]",
                    "service_id": None,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_SERVICE_STATE["tx_submitter"],
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state
                    == StakingState.STAKED.value,
                    lambda synchronized_data: synchronized_data.tx_submitter
                    == "dummy_submitter",
                ],
            ),
            RoundTestCase(
                name="Service not staked",
                initial_data={},
                payloads=get_checkpoint_payloads(DUMMY_SERVICE_STATE),
                final_data={},
                event=Event.SERVICE_NOT_STAKED,
                most_voted_payload=DUMMY_SERVICE_STATE["tx_submitter"],
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state
                    == 0,
                ],
            ),
            RoundTestCase(
                name="Service evicted",
                initial_data={},
                payloads=get_checkpoint_payloads(
                    {
                        "service_staking_state": StakingState.EVICTED.value,
                        "tx_submitter": "dummy_submitter",
                        "tx_hash": "dummy_tx_hash",
                        "ts_checkpoint": 0,
                        "is_checkpoint_reached": True,
                        "agent_ids": "[]",
                        "service_id": None,
                    }
                ),
                final_data={},
                event=Event.SERVICE_EVICTED,
                most_voted_payload=DUMMY_SERVICE_STATE["tx_submitter"],
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state
                    == 0,
                ],
            ),
            RoundTestCase(
                name="Next checkpoint not reached",
                initial_data={},
                payloads=get_checkpoint_payloads(
                    {
                        "service_staking_state": StakingState.STAKED.value,
                        "tx_submitter": "dummy_submitter",
                        "tx_hash": None,
                        "ts_checkpoint": 0,
                        "is_checkpoint_reached": True,
                        "agent_ids": "[]",
                        "service_id": None,
                    }
                ),
                final_data={},
                event=Event.NEXT_CHECKPOINT_NOT_REACHED_YET,
                most_voted_payload=DUMMY_SERVICE_STATE["tx_submitter"],
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state
                    == 0,
                ],
            ),
        ],
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run the test."""

        self.run_test(test_case)


class TestCheckpointCallPreparedRound:
    """Tests for CheckpointCallPreparedRound."""

    def test_checkpoint_call_prepared_round_initialization(self) -> None:
        """Test the initialization of CheckpointCallPreparedRound."""
        round_ = CheckpointCallPreparedRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, CheckpointCallPreparedRound)


class TestFinishedStakingRound:
    """Tests for FinishedStakingRound."""

    def test_finished_staking_round_initialization(self) -> None:
        """Test the initialization of FinishedStakingRound."""
        round_ = FinishedStakingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedStakingRound)


class TestServiceEvictedRound:
    """Tests for ServiceEvictedRound."""

    def test_service_evicted_round_initialization(self) -> None:
        """Test the initialization of ServiceEvictedRound."""
        round_ = ServiceEvictedRound(synchronized_data=MagicMock(), context=MagicMock())
        assert isinstance(round_, ServiceEvictedRound)


def test_staking_abci_app_initialization(abci_app: StakingAbciApp) -> None:
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
    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
    assert abci_app.db_pre_conditions == {CallCheckpointRound: set()}
    assert abci_app.db_post_conditions == {
        CheckpointCallPreparedRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
            get_name(SynchronizedData.service_staking_state),
            get_name(SynchronizedData.previous_checkpoint),
            get_name(SynchronizedData.is_checkpoint_reached),
        },
        FinishedStakingRound: {
            get_name(SynchronizedData.service_staking_state),
        },
        ServiceEvictedRound: {
            get_name(SynchronizedData.service_staking_state),
        },
    }


DUMMY_PARTICIPANT_TO_CHECKPOINT = json.dumps(
    {
        "agent_0": {"sender": "agent_0", "data": "checkpoint_1"},
        "agent_1": {"sender": "agent_1", "data": "checkpoint_2"},
    }
)


@pytest.mark.parametrize(
    "key,serialized_data,expected_result,property_to_check",
    [
        (
            "participant_to_checkpoint",
            DUMMY_PARTICIPANT_TO_CHECKPOINT,
            json.loads(DUMMY_PARTICIPANT_TO_CHECKPOINT),
            "participant_to_checkpoint",  # Corresponds to _get_deserialized method
        ),
    ],
)
@patch(
    "packages.valory.skills.staking_abci.rounds.CollectionRound.deserialize_collection"
)
def test_synchronized_data_get_deserialized(
    mock_deserialize_collection: MagicMock,
    key: str,
    serialized_data: str,
    expected_result: Mapping[str, Any],
    property_to_check: str,
) -> None:
    """Test the deserialization and property access in SynchronizedData."""
    # Mock the db.get_strict to return the serialized data
    mock_db = mock.MagicMock()
    mock_db.get_strict.return_value = serialized_data

    # Initialize SynchronizedData with the mocked db
    synchronized_data = SynchronizedData(db=mock_db)

    # Mock the deserialize_collection function to return the expected deserialized result
    mock_deserialize_collection.return_value = expected_result

    # Access the property using the appropriate property access method
    deserialized_data = synchronized_data.participant_to_checkpoint

    # Ensure that get_strict is called with the correct key
    mock_db.get_strict.assert_called_once_with(key)

    # Ensure that deserialize_collection is called with the correct serialized data
    mock_deserialize_collection.assert_called_once_with(serialized_data)
    assert deserialized_data == expected_result


def test_synchronized_data_tx_submitter() -> None:
    """Test the tx_submitter property in SynchronizedData."""
    mock_db = mock.MagicMock()
    mock_db.get_strict.return_value = "agent_0"

    synchronized_data = SynchronizedData(db=mock_db)

    assert synchronized_data.tx_submitter == "agent_0"
    mock_db.get_strict.assert_called_once_with("tx_submitter")


def test_synchronized_data_service_staking_state() -> None:
    """Test the service_staking_state property in SynchronizedData."""
    mock_db = mock.MagicMock()
    mock_db.get.return_value = 0

    synchronized_data = SynchronizedData(db=mock_db)

    staking_state = synchronized_data.service_staking_state
    assert isinstance(staking_state, StakingState)
    mock_db.get.assert_called_once_with("service_staking_state", 0)


def test_synchronized_data_initialization() -> None:
    """Test the initialization and attributes of SynchronizedData."""
    data = SynchronizedData(db=AbciAppDB(setup_data={"test": ["test"]}))
    assert data.db._data == {0: {"test": ["test"]}}
