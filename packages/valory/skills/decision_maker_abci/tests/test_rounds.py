# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""This module contains the test for rounds of decision maker"""
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
    CheckBenchmarkingModeRound,
)
from packages.valory.skills.decision_maker_abci.states.claim_subscription import (
    ClaimRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    BenchmarkingModeDisabledRound,
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedSubscriptionRound,
    FinishedWithoutDecisionRound,
)
from packages.valory.skills.decision_maker_abci.states.order_subscription import (
    SubscriptionRound,
)
from packages.valory.skills.decision_maker_abci.states.randomness import (
    BenchmarkingRandomnessRound,
    RandomnessRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)


@pytest.fixture
def setup_app() -> DecisionMakerAbciApp:
    """Set up the initial app instance for testing."""
    # Create mock objects for the required arguments
    synchronized_data = MagicMock(spec=SynchronizedData)
    logger = MagicMock()  # Mock logger
    context = MagicMock()  # Mock context

    # Initialize the app with the mocked dependencies
    return DecisionMakerAbciApp(synchronized_data, logger, context)


def test_initial_state(setup_app: DecisionMakerAbciApp) -> None:
    """Test the initial round of the application."""
    app = setup_app
    assert app.initial_round_cls == CheckBenchmarkingModeRound
    assert CheckBenchmarkingModeRound in app.initial_states


def test_check_benchmarking_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from CheckBenchmarkingModeRound."""
    app = setup_app
    transition_function = app.transition_function[CheckBenchmarkingModeRound]

    # Transition on benchmarking enabled
    assert (
        transition_function[Event.BENCHMARKING_ENABLED] == BenchmarkingRandomnessRound
    )

    # Transition on benchmarking disabled
    assert (
        transition_function[Event.BENCHMARKING_DISABLED]
        == BenchmarkingModeDisabledRound
    )

    # Test no majority
    assert transition_function[Event.NO_MAJORITY] == CheckBenchmarkingModeRound


def test_sampling_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from SamplingRound."""
    app = setup_app
    transition_function = app.transition_function[SamplingRound]

    # Transition on done
    assert transition_function[Event.DONE] == SubscriptionRound

    # Test none and no majority
    assert transition_function[Event.NONE] == FinishedWithoutDecisionRound
    assert transition_function[Event.NO_MAJORITY] == SamplingRound


def test_subscription_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from SubscriptionRound."""
    app = setup_app
    transition_function = app.transition_function[SubscriptionRound]

    # Transition on done
    assert transition_function[Event.DONE] == FinishedSubscriptionRound

    # Mock transaction cases
    assert transition_function[Event.MOCK_TX] == ToolSelectionRound
    assert transition_function[Event.NO_SUBSCRIPTION] == ToolSelectionRound


def test_claim_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from ClaimRound."""
    app = setup_app
    transition_function = app.transition_function[ClaimRound]

    # Test transition on done
    assert transition_function[Event.DONE] == ToolSelectionRound


def test_randomness_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from RandomnessRound."""
    app = setup_app
    transition_function = app.transition_function[RandomnessRound]

    # Transition on done
    assert transition_function[Event.DONE] == SamplingRound


def test_tool_selection_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from ToolSelectionRound."""
    app = setup_app
    transition_function = app.transition_function[ToolSelectionRound]

    # Test transition on done
    assert transition_function[Event.DONE] == DecisionRequestRound


def test_decision_request_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from DecisionRequestRound."""
    app = setup_app
    transition_function = app.transition_function[DecisionRequestRound]

    # Test transition on done
    assert transition_function[Event.DONE] == FinishedDecisionRequestRound
    assert transition_function[Event.MOCK_MECH_REQUEST] == DecisionReceiveRound


def test_decision_receive_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from DecisionReceiveRound."""
    app = setup_app
    transition_function = app.transition_function[DecisionReceiveRound]

    # Test transition on done
    assert transition_function[Event.DONE] == BetPlacementRound
    assert transition_function[Event.DONE_SELL] == SellOutcomeTokensRound
    assert transition_function[Event.DONE_NO_SELL] == FinishedDecisionMakerRound


def test_blacklisting_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from BlacklistingRound."""
    app = setup_app
    transition_function = app.transition_function[BlacklistingRound]

    # Test transition on done
    assert transition_function[Event.DONE] == FinishedWithoutDecisionRound


def test_bet_placement_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from BetPlacementRound."""
    app = setup_app
    transition_function = app.transition_function[BetPlacementRound]

    # Test transition on done
    assert transition_function[Event.DONE] == FinishedDecisionMakerRound


def test_redeem_round_transition(setup_app: DecisionMakerAbciApp) -> None:
    """Test transitions from RedeemRound."""
    app = setup_app
    transition_function = app.transition_function[RedeemRound]

    # Test transition on done
    assert transition_function[Event.DONE] == FinishedDecisionMakerRound


def test_final_states(setup_app: DecisionMakerAbciApp) -> None:
    """Test the final states of the application."""
    app = setup_app
    assert FinishedDecisionMakerRound in app.final_states
    assert BenchmarkingModeDisabledRound in app.final_states
    assert FinishedWithoutDecisionRound in app.final_states
