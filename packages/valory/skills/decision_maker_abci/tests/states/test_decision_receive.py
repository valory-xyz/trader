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
import datetime
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
from unittest import mock

import pytest

from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.market_manager_abci.rounds import UpdateBetsPayload


DUMMY_DECISION_HASH = "dummy_decision_hash"
DUMMY_PARTICIPANT_TO_DECISION_HASH = json.dumps(
    {
        "agent_0": "decision_1",
        "agent_1": "decision_2",
        "agent_2": "decision_3",
    }
)
DUMMY_BETS_HASH = "dummy_bets_hash"  # Added a dummy bets hash


def get_participants() -> FrozenSet[str]:
    """Participants."""
    return frozenset([f"agent_{i}" for i in range(4)])


def get_payloads(
    vote: Optional[int],
    confidence: Optional[float],
    bet_amount: Optional[int],
    next_mock_data_row: Optional[int],
    is_profitable: Optional[bool],
    bets_hash: str,
    policy: str,
    should_be_sold: bool,
) -> Mapping[str, UpdateBetsPayload]:
    """Get payloads."""
    return {
        participant: DecisionReceivePayload(
            sender=participant,
            vote=vote,
            confidence=confidence,
            bet_amount=bet_amount,
            next_mock_data_row=next_mock_data_row,
            is_profitable=is_profitable,
            bets_hash=bets_hash,
            policy=policy,
            decision_received_timestamp=int(datetime.datetime.utcnow().timestamp()),
            should_be_sold=should_be_sold,
        )
        for participant in get_participants()
    }


@dataclass
class RoundTestCase:
    """RoundTestCase for DecisionReceiveRound."""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, UpdateBetsPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


class TestDecisionReceiveRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for DecisionReceiveRound."""

    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    vote=1,
                    confidence=80.0,
                    bet_amount=100,
                    next_mock_data_row=1,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={
                    "decision_hash": DUMMY_DECISION_HASH,
                    "participant_to_decision_hash": DUMMY_PARTICIPANT_TO_DECISION_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_DECISION_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.decision_hash,
                ],
            ),
            RoundTestCase(
                name="Should be sold decision",
                initial_data={"should_be_sold": True},
                payloads=get_payloads(
                    vote=1,
                    confidence=80.0,
                    bet_amount=100,
                    next_mock_data_row=1,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=True,
                ),
                final_data={
                    "decision_hash": DUMMY_DECISION_HASH,
                    "participant_to_decision_hash": DUMMY_PARTICIPANT_TO_DECISION_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_DECISION_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.decision_hash,
                ],
            ),
            RoundTestCase(
                name="Unprofitable decision",
                initial_data={"is_profitable": False},
                payloads=get_payloads(
                    vote=0,
                    confidence=50.0,
                    bet_amount=50,
                    next_mock_data_row=2,
                    is_profitable=False,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={
                    "decision_hash": DUMMY_DECISION_HASH,
                    "participant_to_decision_hash": DUMMY_PARTICIPANT_TO_DECISION_HASH,
                },
                event=Event.UNPROFITABLE,
                most_voted_payload=DUMMY_DECISION_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.decision_hash,
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    vote=None,
                    confidence=None,
                    bet_amount=None,
                    next_mock_data_row=None,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Tie event",
                initial_data={},
                payloads=get_payloads(
                    vote=None,
                    confidence=None,
                    bet_amount=None,
                    next_mock_data_row=None,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={},
                event=Event.TIE,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Mechanism response error",
                initial_data={"mocking_mode": True},
                payloads=get_payloads(
                    vote=None,
                    confidence=None,
                    bet_amount=None,
                    next_mock_data_row=None,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={},
                event=Event.MECH_RESPONSE_ERROR,
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

        test_round = DecisionReceiveRound(
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
