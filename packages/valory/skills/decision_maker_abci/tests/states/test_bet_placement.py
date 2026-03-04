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

from typing import Any, Dict, Tuple, cast
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.decision_maker_abci.payloads import BetPlacementPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)


@pytest.fixture
def bet_placement_round() -> BetPlacementRound:
    """Fixture to set up a BetPlacementRound instance for testing."""
    synchronized_data: Dict[str, Any] = {}  # Added type annotation
    context: Dict[str, Any] = {}  # Added type annotation
    return BetPlacementRound(synchronized_data, context)


def test_initial_event(bet_placement_round: BetPlacementRound) -> None:
    """Test that the initial event is set correctly."""
    assert bet_placement_round.none_event == Event.INSUFFICIENT_BALANCE


def test_payload_class(bet_placement_round: BetPlacementRound) -> None:
    """Test that the payload class is BetPlacementPayload."""
    assert bet_placement_round.payload_class is BetPlacementPayload


def test_inherits_from_tx_preparation_round() -> None:
    """Test that BetPlacementRound inherits from TxPreparationRound."""
    assert issubclass(BetPlacementRound, TxPreparationRound)


def test_end_block_returns_none_when_super_returns_none() -> None:
    """Test end_block returns None when parent returns None."""
    mock_synced_data = MagicMock(spec=SynchronizedData)
    mock_context = MagicMock()
    round_instance = BetPlacementRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(TxPreparationRound, "end_block", return_value=None):
        result = round_instance.end_block()
    assert result is None


def test_end_block_done_with_tx_hash() -> None:
    """Test end_block with DONE event and valid tx hash."""
    mock_synced_data = MagicMock(spec=SynchronizedData)
    mock_synced_data.most_voted_tx_hash = "0xvalidhash"
    mock_context = MagicMock()
    round_instance = BetPlacementRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(
        TxPreparationRound, "end_block", return_value=(mock_synced_data, Event.DONE)
    ):
        with patch.object(
            BetPlacementRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=(None, None, None, 1000),
        ):
            result = round_instance.end_block()
    assert result is not None
    _, event = result
    assert event == Event.DONE


def test_end_block_done_without_tx_hash() -> None:
    """Test end_block with DONE event but no tx hash triggers CALC_BUY_AMOUNT_FAILED."""
    mock_synced_data = MagicMock(spec=SynchronizedData)
    mock_synced_data.most_voted_tx_hash = None
    mock_context = MagicMock()
    round_instance = BetPlacementRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(
        TxPreparationRound, "end_block", return_value=(mock_synced_data, Event.DONE)
    ):
        with patch.object(
            BetPlacementRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=(None, None, None, 500),
        ):
            result = round_instance.end_block()
    assert result is not None
    _, event = result
    assert event == Event.CALC_BUY_AMOUNT_FAILED
