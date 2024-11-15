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
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    CollectionRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import ClaimPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.claim_subscription import (
    ClaimRound,
)


# Dummy payload data
DUMMY_PAYLOAD_DATA = {"vote": True}


# Data class for test cases
@dataclass
class RoundTestCase:
    """Data class to hold round test case details."""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, ClaimPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


# Maximum participants
MAX_PARTICIPANTS: int = 4


# Helper functions for payloads and participants
def get_participants() -> FrozenSet[str]:
    """Get participants for the test."""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_participant_to_votes(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, ClaimPayload]:
    """Map participants to votes."""
    return {
        participant: ClaimPayload(sender=participant, vote=vote)
        for participant in participants
    }


def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, Dict[str, Any]]:
    """Get serialized votes from participants."""
    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote)
    )


def get_payloads(
    payload_cls: Type[ClaimPayload], data: Optional[str]
) -> Mapping[str, ClaimPayload]:
    """Generate payloads for the test."""
    return {
        participant: payload_cls(participant, data is not None)
        for participant in get_participants()
    }


def get_dummy_claim_payload_serialized() -> str:
    """Get serialized dummy payload."""
    return json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True)


# Base test class for ClaimRound
class BaseClaimRoundTest(BaseVotingRoundTest):
    """Base Test Class for ClaimRound"""

    test_class: Type[VotingRound]
    test_payload: Type[ClaimPayload]

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
                synchronized_data_update_fn=lambda synchronized_data, test_round: synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants, vote=vote
                    )
                ),
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.participant_to_votes.keys()
                ]
                if vote
                else [],
                exit_event=expected_event,
                threshold_check=threshold_check,
            )
        )

    def test_positive_votes(self) -> None:
        """Test ClaimRound with positive votes."""
        self._test_voting_round(
            vote=True,
            expected_event=self._event_class.DONE,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
        )

    def test_negative_votes(self) -> None:
        """Test ClaimRound with negative votes."""
        self._test_voting_round(
            vote=False,
            expected_event=self._event_class.SUBSCRIPTION_ERROR,
            threshold_check=lambda x: x.negative_vote_threshold_reached,
        )


# Test class for ClaimRound
class TestClaimRound(BaseClaimRoundTest):
    """Tests for ClaimRound."""

    test_class = ClaimRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    ClaimPayload, get_dummy_claim_payload_serialized()
                ),
                final_data={},
                event=Event.DONE,
                most_voted_payload=get_dummy_claim_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_claim_payload_serialized())
                    )
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    ClaimPayload, get_dummy_claim_payload_serialized()
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=get_dummy_claim_payload_serialized(),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run the parameterized tests."""
        if test_case.event == Event.DONE:
            self.test_positive_votes()
        elif test_case.event == Event.NO_MAJORITY:
            self.test_negative_votes()


# Test for SynchronizedData initialization
def test_synchronized_data_initialization() -> None:
    """Test SynchronizedData initialization."""
    data = SynchronizedData(db=AbciAppDB(setup_data={"test": ["test"]}))
    assert data.db._data == {0: {"test": ["test"]}}
