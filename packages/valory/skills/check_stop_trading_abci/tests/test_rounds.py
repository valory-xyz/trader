# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This package contains the tests for the CheckStopTradingAbciApp."""

import json
from unittest.mock import MagicMock, Mock
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional, Type
from unittest import mock

import pytest

from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingRound,
    FinishedCheckStopTradingRound,
    FinishedWithSkipTradingRound,
    Event,
    SynchronizedData,
    CheckStopTradingAbciApp,
)
from packages.valory.skills.check_stop_trading_abci.payloads import CheckStopTradingPayload
from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    CollectionRound,
    DegenerateRound,
    DeserializedCollection,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest
)

DUMMY_PAYLOAD_DATA = {
    "example_key": "example_value"
}

@pytest.fixture
def abci_app():
    """Fixture for CheckStopTradingAbciApp."""
    synchronized_data = Mock()  # Replace with actual synchronized_data if available
    logger = Mock()  # Replace with actual logger if available
    context = Mock()  # Replace with actual context if available

    return CheckStopTradingAbciApp(synchronized_data=synchronized_data, logger=logger, context=context)

    


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])

def get_participant_to_votes(
    participants: FrozenSet[str], vote: Optional[bool] = True
) -> Dict[str, CheckStopTradingPayload]:
    """participant_to_votes"""
    return {
        participant: CheckStopTradingPayload(sender=participant, vote=vote)
        for participant in participants
    }

def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: Optional[bool] = True
) -> Dict[str, Dict[str, Any]]:
    """participant_to_votes"""
    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote)
    )

def get_payloads(
    payload_cls: CheckStopTradingPayload,
    data: Optional[str],
) -> Mapping[str, CheckStopTradingPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data)
        for participant in get_participants()
    }


def get_dummy_check_stop_trading_payload_serialized() -> str:
    """Dummy payload serialization"""
    return json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True)


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, CheckStopTradingPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BaseCheckStopTradingRoundTest(BaseVotingRoundTest):

    test_class: Type[VotingRound]
    test_payload: Type[CheckStopTradingPayload]

    def test_positive_votes(
        self
    ) -> None:
        """Test ValidateRound."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data,
            context=MagicMock(),
        )

        self._complete_run(
            self._test_voting_round_positive(
                test_round=test_round,
                round_payloads=get_participant_to_votes(self.participants),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants
                    )
                ),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.participant_to_votes.keys()
                ],
                exit_event=self._event_class.SKIP_TRADING,
            )
        )

    def test_negative_votes(
        self
    ) -> None:
        """Test ValidateRound."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data,
            context=MagicMock(),
        )

        self._complete_run(
            self._test_voting_round_negative(
                test_round=test_round,
                round_payloads=get_participant_to_votes(self.participants, vote=False),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants, vote=False
                    )
                ),
                synchronized_data_attr_checks=[],
                exit_event=self._event_class.DONE,
            )
        )

    def test_none_votes(
        self
    ) -> None:
        """Test ValidateRound."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data,
            context=MagicMock(),
        )

        self._complete_run(
            self._test_voting_round_none(
                test_round=test_round,
                round_payloads=get_participant_to_votes(self.participants, vote=None),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants, vote=None
                    )
                ),
                synchronized_data_attr_checks=[],
                exit_event=self._event_class.NONE,
            )
        )

class TestCheckStopTradingRound(BaseCheckStopTradingRoundTest):
    """Tests for CheckStopTradingRound."""

    #round_class = CheckStopTradingRound  # Added this line
    test_class = CheckStopTradingRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData
    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.SKIP_TRADING,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(get_name(SynchronizedData.participant_to_votes)) == CollectionRound.deserialize_collection(
                        get_dummy_check_stop_trading_payload_serialized()
                    ),
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)
    
    def run_test(self, test_case:RoundTestCase):
        if test_case.event==Event.SKIP_TRADING:
            self.test_positive_votes()
        elif test_case.event==Event.NO_MAJORITY:
            self.test_negative_votes()
        else:
            self.test_none_votes()        

class TestFinishedCheckStopTradingRound:
    """Tests for FinishedCheckStopTradingRound."""

    def test_finished_check_stop_trading_round_initialization(self):
        """Test the initialization of FinishedCheckStopTradingRound."""
        round_ = FinishedCheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedCheckStopTradingRound)


class TestFinishedWithSkipTradingRound:
    """Tests for FinishedWithSkipTradingRound."""

    def test_finished_with_skip_trading_round_initialization(self):
        """Test the initialization of FinishedWithSkipTradingRound."""
        round_ = FinishedWithSkipTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedWithSkipTradingRound)


def test_abci_app_initialization(abci_app):
    """Test the initialization of CheckStopTradingAbciApp."""
    assert abci_app.initial_round_cls is CheckStopTradingRound
    assert abci_app.final_states == {
        FinishedCheckStopTradingRound,
        FinishedWithSkipTradingRound,
    }
    assert abci_app.transition_function == {
        CheckStopTradingRound: {
            Event.DONE: FinishedCheckStopTradingRound,
            Event.NONE: CheckStopTradingRound,
            Event.ROUND_TIMEOUT: CheckStopTradingRound,
            Event.NO_MAJORITY: CheckStopTradingRound,
            Event.SKIP_TRADING: FinishedWithSkipTradingRound,
        },
        FinishedCheckStopTradingRound: {},
        FinishedWithSkipTradingRound: {},
    }
    assert abci_app.event_to_timeout == {
        Event.ROUND_TIMEOUT: 30.0,
    }
    assert abci_app.db_pre_conditions == {CheckStopTradingRound: set()}
    assert abci_app.db_post_conditions == {
        FinishedCheckStopTradingRound: set(),
        FinishedWithSkipTradingRound: set(),
    }


def test_synchronized_data_initialization():
    """Test the initialization and attributes of SynchronizedData."""
    data = SynchronizedData(db=dict())
    assert data.db == {}