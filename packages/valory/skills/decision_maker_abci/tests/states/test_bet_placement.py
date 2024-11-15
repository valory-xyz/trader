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

from typing import Any, Dict

import pytest

from packages.valory.skills.decision_maker_abci.states.base import Event
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
