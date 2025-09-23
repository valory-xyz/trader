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

"""This package contains the tests for Decision Maker"""

from unittest.mock import MagicMock

from packages.valory.skills.abstract_round_abci.base import VotingRound
from packages.valory.skills.decision_maker_abci.rounds import CheckBenchmarkingModeRound
from packages.valory.skills.decision_maker_abci.states.base import Event


def test_check_benchmarking_mode_round_initialization() -> None:
    """Test the initialization of CheckBenchmarkingModeRound."""
    round_instance = CheckBenchmarkingModeRound(MagicMock(), MagicMock())

    # Test that the round is properly initialized with the correct event types
    assert round_instance.done_event == Event.BENCHMARKING_ENABLED
    assert round_instance.negative_event == Event.BENCHMARKING_DISABLED

    # Check that it inherits from VotingRound
    assert isinstance(round_instance, VotingRound)


def test_check_benchmarking_mode_round_events() -> None:
    """Test that the correct events are used in the CheckBenchmarkingModeRound."""
    round_instance = CheckBenchmarkingModeRound(MagicMock(), MagicMock())

    # Assert that the done_event is BENCHMARKING_ENABLED
    assert round_instance.done_event == Event.BENCHMARKING_ENABLED

    # Assert that the negative_event is BENCHMARKING_DISABLED
    assert round_instance.negative_event == Event.BENCHMARKING_DISABLED
