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

"""This package contains the tests for the PreTxSettlementRound of TxSettlementMultiplexerAbciApp."""

import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    Type,
)
from unittest.mock import MagicMock, Mock

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    CollectionRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest,
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    PreTxSettlementRound,
    PostTxSettlementRound,
    Event,
    SynchronizedData,
)

DUMMY_PAYLOAD_DATA = {"example_key": "example_value"}


def get_participants() -> FrozenSet[str]:
    """Participants."""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])

def get_participant_to_votes(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, VotingPayload]:
    """participant_to_votes"""

    return {
        participant: VotingPayload(sender=participant, vote=vote)
        for participant in participants
    }


def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, Dict[str, Any]]:
    """participant_to_votes"""

    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote)
    )

def get_payloads(
    payload_cls: Type[VotingPayload],
    data: Optional[str],
) -> Mapping[str, VotingPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data is not None)
        for participant in get_participants()
    }

def get_dummy_tx_settlement_payload_serialized() -> str:
    """Dummy payload serialization"""
    return json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True)

@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, VotingPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BasePreTxSettlementRoundTest(BaseVotingRoundTest):
    """Base test class for TxSettlementMultiplexer rounds derived from VotingRound."""

    test_class: Type[VotingRound]
    test_payload: Type[VotingPayload]

    def _test_voting_round(
        self, vote: bool, expected_event: Any, threshold_check: Callable
    ) -> None:
        """Helper method to test voting rounds with positive or negative votes."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=get_participant_to_votes(self.participants, vote=vote),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                       self.participants, vote=vote 
                    )
                ),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.participant_to_votes.keys()
                ]
                if vote
                else [],
                exit_event=expected_event,
                threshold_check=threshold_check,
            )
        )

    def test_positive_votes(self) -> None:
        """Test PreTxSettlementRound for positive votes."""
        self._test_voting_round(
            vote= True,
            expected_event=Event.CHECKS_PASSED,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
        )

    def test_negative_votes(self) -> None:
        """Test PreTxSettlementRound for negative votes."""
        self._test_voting_round(
            vote= False,
            expected_event=Event.REFILL_REQUIRED,
            threshold_check=lambda x: x.negative_vote_threshold_reached,
        )


class TestPreTxSettlementRound(BasePreTxSettlementRoundTest):
    """Tests for PreTxSettlementRound."""

    test_class = PreTxSettlementRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=VotingPayload,
                    data=get_dummy_tx_settlement_payload_serialized(),
                ),
                final_data={},
                event=Event.CHECKS_PASSED,
                most_voted_payload=get_dummy_tx_settlement_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_tx_settlement_payload_serialized())
                    )    
                ],
            ),
            
            RoundTestCase(
                name="Negative votes",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=VotingPayload,
                    data=get_dummy_tx_settlement_payload_serialized(),
                ),
                final_data={},
                event=Event.REFILL_REQUIRED,
                most_voted_payload=get_dummy_tx_settlement_payload_serialized(),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        if test_case.event == Event.CHECKS_PASSED:
            self.test_positive_votes()
        elif test_case.event == Event.REFILL_REQUIRED:
            self.test_negative_votes()

class BasePostTxSettlementRoundTest(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for MarketManager rounds."""

    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event
    round_class = PostTxSettlementRound

    def run_test(self, test_case: RoundTestCase, **kwargs: Any) -> None:
        """Run the test"""

        # Set initial data
        self.synchronized_data.update(**test_case.initial_data)

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

class TestPostTxSettlementRound(BasePostTxSettlementRoundTest):
