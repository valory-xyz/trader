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
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
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


class BaseCheckStopTradingRoundTestClass(BaseVotingRoundTest):
    """Base test class for CheckStopTradingRound."""
    _synchronized_data_class = SynchronizedData
    payload_class = CheckStopTradingPayload
    _event_class = Event

    def run_test(self, test_case: RoundTestCase, **kwargs: Any) -> None:
        """Run the test"""

        self.synchronized_data.update(**test_case.initial_data)

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )

        # Use the appropriate test method based on the expected exit event
        if test_case.event == Event.SKIP_TRADING:
            threshold_check = lambda x: x.positive_vote_threshold_reached
            test_method = self._test_voting_round_positive
        elif test_case.event == Event.NO_MAJORITY:
            threshold_check = lambda x: x.none_vote_threshold_reached
            test_method = self._test_voting_round_none
        else:
            raise ValueError(f"Unexpected event: {test_case.event}")

        self._complete_run(
            test_method(
                test_round=test_round,
                round_payloads=test_case.payloads,
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case.final_data
                ),
                synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
                exit_event=test_case.event,
            )
        )


class TestCheckStopTradingRound(BaseCheckStopTradingRoundTestClass):
    """Tests for CheckStopTradingRound."""

    round_class = CheckStopTradingRound  # Added this line

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