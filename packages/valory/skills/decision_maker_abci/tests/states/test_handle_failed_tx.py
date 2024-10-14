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
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Type
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    CollectionRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)


# Helper functions
def get_participants() -> FrozenSet[str]:
    """Get participants for the test."""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_participant_to_votes(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, VotingPayload]:
    """Map participants to votes."""
    return {
        participant: VotingPayload(sender=participant, vote=vote)
        for participant in participants
    }


def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: bool
) -> Dict[str, Dict[str, Any]]:
    """Get serialized votes from participants."""
    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote)
    )


# Dummy Payload Data
DUMMY_PAYLOAD_DATA = {"vote": True}
MAX_PARTICIPANTS = 4


# Base test class for HandleFailedTxRound
class BaseHandleFailedTxRoundTest(BaseVotingRoundTest):
    """Base Test Class for HandleFailedTxRound"""

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
        """Test HandleFailedTxRound with positive votes."""
        self._test_voting_round(
            vote=True,
            expected_event=self._event_class.BLACKLIST,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
        )

    def test_negative_votes(self) -> None:
        """Test HandleFailedTxRound with negative votes."""
        self._test_voting_round(
            vote=False,
            expected_event=self._event_class.NO_OP,
            threshold_check=lambda x: x.negative_vote_threshold_reached,
        )


# Test class for HandleFailedTxRound
class TestHandleFailedTxRound(BaseHandleFailedTxRoundTest):
    """Tests for HandleFailedTxRound."""

    test_class = HandleFailedTxRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            # Parametrized test case for successful vote (BLACKLIST)
            {
                "name": "Happy path",
                "initial_data": {},
                "payloads": get_participant_to_votes(get_participants(), True),
                "final_data": {},
                "event": Event.BLACKLIST,
                "most_voted_payload": json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True),
                "synchronized_data_attr_checks": [
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True))
                    )
                ],
            },
            # Parametrized test case for no operation (NO_OP)
            {
                "name": "No majority",
                "initial_data": {},
                "payloads": get_participant_to_votes(get_participants(), False),
                "final_data": {},
                "event": Event.NO_OP,
                "most_voted_payload": json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True),
                "synchronized_data_attr_checks": [],
            },
        ),
    )
    def test_run(self, test_case: dict) -> None:
        """Run the parameterized tests."""
        if test_case["event"] == Event.BLACKLIST:
            self.test_positive_votes()
        elif test_case["event"] == Event.NO_OP:
            self.test_negative_votes()


# Additional tests for state initialization
class TestFinishedHandleFailedTxRound:
    """Tests for FinishedHandleFailedTxRound."""

    def test_initialization(self) -> None:
        """Test the initialization of FinishedHandleFailedTxRound."""
        round_ = HandleFailedTxRound(synchronized_data=MagicMock(), context=MagicMock())
        assert isinstance(round_, HandleFailedTxRound)
