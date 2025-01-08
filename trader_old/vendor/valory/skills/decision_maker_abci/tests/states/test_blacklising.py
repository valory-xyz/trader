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
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.decision_maker_abci.payloads import BlacklistingPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.market_manager_abci.rounds import UpdateBetsRound


@pytest.fixture
def mocked_context() -> MagicMock:
    """Fixture to mock the context."""
    context = MagicMock()
    context.benchmarking_mode.enabled = False  # Default for the test
    return context


@pytest.fixture
def mocked_synchronized_data() -> MagicMock:
    """Fixture to mock the synchronized data."""
    return MagicMock(spec=SynchronizedData)


@pytest.fixture
def blacklisting_round(
    mocked_context: MagicMock, mocked_synchronized_data: MagicMock
) -> BlacklistingRound:
    """Fixture to create an instance of BlacklistingRound."""
    return BlacklistingRound(
        context=mocked_context, synchronized_data=mocked_synchronized_data
    )


def test_blacklisting_round_initialization(
    blacklisting_round: BlacklistingRound,
) -> None:
    """Test the initialization of the BlacklistingRound."""
    assert blacklisting_round.done_event == Event.DONE
    assert blacklisting_round.none_event == Event.NONE
    assert blacklisting_round.no_majority_event == Event.NO_MAJORITY
    assert blacklisting_round.payload_class == BlacklistingPayload
    assert isinstance(blacklisting_round.selection_key, tuple)
    assert len(blacklisting_round.selection_key) == 2


def test_blacklisting_round_end_block_done_event_no_benchmarking(
    blacklisting_round: BlacklistingRound, mocked_context: MagicMock
) -> None:
    """Test end_block when event is DONE and benchmarking is disabled."""
    # Mock the superclass end_block to return DONE event
    synced_data = MagicMock(spec=SynchronizedData)
    with patch.object(
        UpdateBetsRound, "end_block", return_value=(synced_data, Event.DONE)
    ) as mock_super_end_block:
        result = blacklisting_round.end_block()

        mock_super_end_block.assert_called_once()
        assert result == (synced_data, Event.DONE)
        assert not mocked_context.benchmarking_mode.enabled  # Benchmarking disabled


def test_blacklisting_round_end_block_done_event_with_benchmarking(
    blacklisting_round: BlacklistingRound, mocked_context: MagicMock
) -> None:
    """Test end_block when event is DONE and benchmarking is enabled."""
    # Set benchmarking mode to enabled
    mocked_context.benchmarking_mode.enabled = True

    # Mock the superclass end_block to return DONE event
    synced_data = MagicMock(spec=SynchronizedData)
    with patch.object(
        UpdateBetsRound, "end_block", return_value=(synced_data, Event.DONE)
    ) as mock_super_end_block:
        result = blacklisting_round.end_block()

        mock_super_end_block.assert_called_once()
        assert result == (
            synced_data,
            Event.MOCK_TX,
        )  # Should return MOCK_TX since benchmarking is enabled
        assert mocked_context.benchmarking_mode.enabled  # Benchmarking enabled


def test_blacklisting_round_end_block_none_event(
    blacklisting_round: BlacklistingRound,
) -> None:
    """Test end_block when the superclass returns None."""
    # Mock the superclass end_block to return None
    with patch.object(
        UpdateBetsRound, "end_block", return_value=None
    ) as mock_super_end_block:
        result = blacklisting_round.end_block()

        mock_super_end_block.assert_called_once()
        assert result is None  # Should return None when the superclass returns None
