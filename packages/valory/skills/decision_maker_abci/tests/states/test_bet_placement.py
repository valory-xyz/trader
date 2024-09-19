# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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
import pytest
from packages.valory.skills.decision_maker_abci.states.bet_placement import BetPlacementRound
from packages.valory.skills.decision_maker_abci.states.base import Event

@pytest.fixture
def bet_placement_round():
    """Fixture to set up a BetPlacementRound instance for testing."""
    synchronized_data = {}  # Example placeholder
    context = {}  # Example placeholder
    return BetPlacementRound(synchronized_data, context)

def test_initial_event(bet_placement_round):
    """Test that the initial event is set correctly."""
    assert bet_placement_round.none_event == Event.INSUFFICIENT_BALANCE


