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

"""This package contains the tests for rounds of StakingAbciApp."""

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock
from typing import Any, Callable, Dict, FrozenSet, Hashable, Mapping, Optional, List
from unittest import mock

import pytest

from packages.valory.skills.abstract_round_abci.base import(
    BaseTxPayload, 
    AbciAppDB,
    get_name
    )
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.staking_abci.payloads import CallCheckpointPayload
from packages.valory.skills.staking_abci.rounds import (
    Event,
    SynchronizedData,
    CallCheckpointRound,
    CheckpointCallPreparedRound,
    FinishedStakingRound,
    ServiceEvictedRound,
    StakingAbciApp
)

@pytest.fixture
def abci_app() -> StakingAbciApp:
    """Fixture for StakingAbciApp."""
    synchronized_data = MagicMock()
    logger = MagicMock()
    context = MagicMock()
    
    return StakingAbciApp(
        synchronized_data=synchronized_data,
        logger=logger,
        context=context
    )

DUMMY_SERVICE_STATE = {
    "service_staking_state": 0,  # Assuming 0 means UNSTAKED
    "tx_submitter": "dummy_submitter",
    "most_voted_tx_hash": "dummy_tx_hash",
}

DUMMY_PARTICIPANT_TO_CHECKPOINT = {
    "agent_0": "checkpoint_0",
    "agent_1": "checkpoint_1",
}

def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_payloads(
    payload_cls: BaseTxPayload,
    data: Optional[str],
) -> Mapping[str, BaseTxPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(
            participant,
            tx_submitter="dummy_submitter",
            tx_hash="dummy_tx_hash",
            service_staking_state=0
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

    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def run_test(self, test_case: RoundTestCase, **kwargs: Any) -> None:
        """Run the test"""

        self.synchronized_data.update(**test_case.initial_data)

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        result = self._test_round(
            test_round=test_round,
            round_payloads=test_case.payloads,
            synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                **test_case.final_data
            ),
            synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
            most_voted_payload=test_case.most_voted_payload,
            exit_event=test_case.event,
        )

        # Debugging line: print result after running the test
        print(f"Test case {test_case.name} result: {result}")

        self._complete_run(result)


class TestCallCheckpointRound(BaseStakingRoundTestClass):
    """Tests for CallCheckpointRound."""

    round_class = CallCheckpointRound

    @pytest.mark.parametrize(
        "test_case",
        [
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CallCheckpointPayload,
                    data=json.dumps(DUMMY_SERVICE_STATE),
                ),
                final_data={
                    "service_staking_state": 0,
                    "tx_submitter": "dummy_submitter",
                    "most_voted_tx_hash": "dummy_tx_hash",
                },
                event=Event.DONE,
                most_voted_payload=json.dumps(DUMMY_SERVICE_STATE),
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state == 0,
                    lambda synchronized_data: synchronized_data.tx_submitter == "dummy_submitter",
                ],
            ),
            RoundTestCase(
                name="Service not staked",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CallCheckpointPayload,
                    data=json.dumps(DUMMY_SERVICE_STATE),
                ),
                final_data={},
                event=Event.SERVICE_NOT_STAKED,
                most_voted_payload=json.dumps(DUMMY_SERVICE_STATE),
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state == 0,
                ],
            ),
            RoundTestCase(
                name="Service evicted",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CallCheckpointPayload,
                    data=json.dumps(DUMMY_SERVICE_STATE),
                ),
                final_data={},
                event=Event.SERVICE_EVICTED,
                most_voted_payload=json.dumps(DUMMY_SERVICE_STATE),
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state == 0,
                ],
            ),
            RoundTestCase(
                name="Next checkpoint not reached",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CallCheckpointPayload,
                    data=json.dumps(DUMMY_SERVICE_STATE),
                ),
                final_data={},
                event=Event.NEXT_CHECKPOINT_NOT_REACHED_YET,
                most_voted_payload=json.dumps(DUMMY_SERVICE_STATE),
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.service_staking_state == 0,
                ],
            ),
        ],
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests with debugging."""
        # Print test case details
        print(f"Running test case: {test_case.name}")
        print(f"Initial Data: {test_case.initial_data}")
        print(f"Payloads: {test_case.payloads}")
        print(f"Final Data: {test_case.final_data}")
        print(f"Event: {test_case.event}")
        print(f"Most Voted Payload: {test_case.most_voted_payload}")

        # Run the test
        self.run_test(test_case)

    def run_test(self, test_case: RoundTestCase, **kwargs: Any) -> None:
        """Run the test with added debugging."""
        self.synchronized_data.update(**test_case.initial_data)

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        print("Starting _test_round...")
        result = self._test_round(
            test_round=test_round,
            round_payloads=test_case.payloads,
            synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                **test_case.final_data
            ),
            synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
            most_voted_payload=test_case.most_voted_payload,
            exit_event=test_case.event,
        )

        # Debugging line: print result after running the test
        print(f"Test case {test_case.name} result: {result}")

        self._complete_run(result)



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
        round_ = ServiceEvictedRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
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
        },
        FinishedStakingRound: {
            get_name(SynchronizedData.service_staking_state),
        },
        ServiceEvictedRound: {
            get_name(SynchronizedData.service_staking_state),
        },
    }

def test_synchronized_data_initialization() -> None:
    """Test the initialization and attributes of SynchronizedData."""
    data = SynchronizedData(db=AbciAppDB(setup_data={"test": ["test"]}))
    assert data.db._data == {0: {"test": ["test"]}}
