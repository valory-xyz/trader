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

"""This package contains the tests for rounds of MarketManagerAbciApp."""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
from unittest import mock

import pytest

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import (
    Event,
    SynchronizedData,
    UpdateBetsRound,
)

# Dummy data for testing
DUMMY_BETS_HASH = "dummy_bets_hash"
DUMMY_PARTICIPANT_TO_BETS_HASH = {
    "agent_0": "dummy_bets_0",
    "agent_1": "dummy_bets_1",
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
        participant: payload_cls(participant, data)
        for participant in get_participants()
    }


def get_dummy_update_bets_payload_serialized() -> str:
    """Dummy update bets payload"""
    return json.dumps(
        {
            "bets_hash": DUMMY_BETS_HASH,
            "participant_to_bets": DUMMY_PARTICIPANT_TO_BETS_HASH,
        },
        sort_keys=True,
    )


def get_dummy_update_bets_payload_error_serialized() -> str:
    """Dummy update bets payload error"""
    return json.dumps({"error": True}, sort_keys=True)


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


class BaseMarketManagerRoundTestClass(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for MarketManager rounds."""

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
        self._complete_run(result)


class TestUpdateBetsRound(BaseMarketManagerRoundTestClass):
    """Tests for UpdateBetsRound."""

    round_class = UpdateBetsRound

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=UpdateBetsPayload,
                    data=get_dummy_update_bets_payload_serialized(),
                ),
                final_data={
                    "bets_hash": DUMMY_BETS_HASH,
                    "participant_to_bets": DUMMY_PARTICIPANT_TO_BETS_HASH,
                },
                event=Event.DONE,
                most_voted_payload=get_dummy_update_bets_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.bets_hash == DUMMY_BETS_HASH,
                    lambda _synchronized_data: _synchronized_data.participant_to_bets_hash == DUMMY_PARTICIPANT_TO_BETS_HASH,
                ],
            ),
            RoundTestCase(
                name="Fetch error",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=UpdateBetsPayload,
                    data=get_dummy_update_bets_payload_error_serialized(),
                ),
                final_data={},
                event=Event.FETCH_ERROR,
                most_voted_payload=get_dummy_update_bets_payload_error_serialized(),
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads={},
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)
