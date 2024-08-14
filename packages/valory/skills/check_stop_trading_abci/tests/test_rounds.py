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

"""This module contains the tests for the check stop trading ABCI application."""

import pytest
import logging  # noqa: F401
from unittest.mock import MagicMock
from typing import Any, Dict, Callable, Set
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

from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingRound,
    Event,
    FinishedCheckStopTradingRound,
    FinishedWithSkipTradingRound,
    SynchronizedData,
    CheckStopTradingAbciApp
)
 

from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
)

@pytest.fixture
def synchronized_data():
    """Get the synchronized data"""
    return SynchronizedData(db=dict())


@pytest.fixture
def abci_app():
    """Fixture to get the ABCI app with necessary parameters."""
    # Create mocks for the required parameters
    synchronized_data = MagicMock()
    logger = MagicMock()
    context = MagicMock()

    # Instantiate CheckStopTradingAbciApp with mocked parameters
    return CheckStopTradingAbciApp(synchronized_data=synchronized_data, logger=logger, context=context)

class BaseCheckStopTradingRoundTestClass:
    """Base test class for CheckStopTradingRound."""

    synchronized_data: SynchronizedData
    round_class = CheckStopTradingRound
    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def _complete_run(self, test_func: Callable[[], None]) -> None:
        """Complete the run of the test."""
        test_func()

    def _test_round(
        self,
        test_round: CheckStopTradingRound,
        round_payloads: list,
        synchronized_data_update_fn: Callable[[SynchronizedData, Any], None],
        synchronized_data_attr_checks: Dict[str, Any],
        most_voted_payload: CheckStopTradingPayload,
        exit_event: Event,
    ) -> None:
        """Test the round processing."""
        for payload in round_payloads:
            test_round.process_payload(payload)

        synchronized_data_update_fn(self.synchronized_data, most_voted_payload)

        for attr, expected_value in synchronized_data_attr_checks.items():
            assert getattr(self.synchronized_data, attr) == expected_value

        assert test_round.event == exit_event

    def run_test(self, test_case: Dict[str, Any], **kwargs: Any) -> None:
        """Run the test using the provided test case."""
        self.synchronized_data.update(**test_case["initial_data"])

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=test_case["payloads"],
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case["final_data"]
                ),
                synchronized_data_attr_checks=test_case["synchronized_data_attr_checks"],
                most_voted_payload=test_case["most_voted_payload"],
                exit_event=test_case["event"],
            )
        )       


def test_check_stop_trading_round_initialization(synchronized_data):
    """Test the initialization of CheckStopTradingRound."""
    round_ = CheckStopTradingRound(
        synchronized_data=synchronized_data, context=MagicMock()
    )
    assert round_.payload_class is CheckStopTradingPayload
    assert round_.synchronized_data_class is SynchronizedData
    assert round_.done_event == Event.SKIP_TRADING
    assert round_.negative_event == Event.DONE
    assert round_.none_event == Event.NONE
    assert round_.no_majority_event == Event.NO_MAJORITY
    assert round_.collection_key == "participant_to_votes"


def test_finished_check_stop_trading_round_initialization():
    """Test the initialization of FinishedCheckStopTradingRound."""
    round_ = FinishedCheckStopTradingRound(
        synchronized_data=MagicMock(), context=MagicMock()
    )
    assert isinstance(round_, FinishedCheckStopTradingRound)


def test_finished_with_skip_trading_round_initialization():
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
    # Initialize SynchronizedData
    data = SynchronizedData(db=dict())

    # Test initial attributes
    assert data.db == {}

