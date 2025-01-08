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

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
from unittest import mock

import pytest

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionRequestPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)


DUMMY_REQUEST_HASH = "dummy_request_hash"
DUMMY_PARTICIPANT_TO_SELECTION_HASH = json.dumps(
    {
        "agent_0": "selection_1",
        "agent_1": "selection_2",
        "agent_2": "selection_3",
    }
)


def get_participants() -> FrozenSet[str]:
    """Participants."""
    return frozenset([f"agent_{i}" for i in range(4)])


def get_payloads(data: Optional[str]) -> Mapping[str, BaseTxPayload]:
    """Get payloads."""
    return {
        participant: DecisionRequestPayload(participant, data)
        for participant in get_participants()
    }


@dataclass
class RoundTestCase:
    """RoundTestCase for DecisionRequestRound."""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, BaseTxPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


class TestDecisionRequestRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for DecisionRequestRound."""

    _synchronized_data_class = SynchronizedData  # Define the missing attribute

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(data=DUMMY_REQUEST_HASH),
                final_data={
                    "request_hash": DUMMY_REQUEST_HASH,
                    "participant_to_selection_hash": DUMMY_PARTICIPANT_TO_SELECTION_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_REQUEST_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.request_hash,
                ],
            ),
            RoundTestCase(
                name="Mocking mode",
                initial_data={"mocking_mode": True},
                payloads=get_payloads(data=DUMMY_REQUEST_HASH),
                final_data={
                    "request_hash": DUMMY_REQUEST_HASH,
                    "participant_to_selection_hash": DUMMY_PARTICIPANT_TO_SELECTION_HASH,
                },
                event=Event.MOCK_MECH_REQUEST,
                most_voted_payload=DUMMY_REQUEST_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.request_hash,
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(data=None),  # Simulating insufficient votes
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="None event",
                initial_data={},
                payloads=get_payloads(data=None),  # Simulating unsupported slots
                final_data={},
                event=Event.SLOTS_UNSUPPORTED_ERROR,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test."""
        self.synchronized_data.update(SynchronizedData, **test_case.initial_data)

        test_round = DecisionRequestRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

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
