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
from typing import Set
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