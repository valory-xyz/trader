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

"""Test for SamplingBehaviour."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path
from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    SamplingBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.bets import Bet
from packages.valory.skills.abstract_round_abci.test_tools.base import FSMBehaviourBaseCase
from packages.valory.skills.abstract_round_abci.base import AbciAppDB, BaseSynchronizedData

WEEKDAYS = 7
UNIX_DAY = 60 * 60 * 24
UNIX_WEEK = WEEKDAYS * UNIX_DAY


def create_bet(**kwargs) -> Bet:
    """Helper function to create a Bet instance with default values."""
    defaults = dict(
        id=1,
        market="market_1",
        title="Test Market",
        collateralToken="0xToken",
        creator="0xCreator",
        fee=0.01,
        outcomeSlotCount=2,
        outcomeTokenAmounts=[100, 200],
        outcomeTokenMarginalPrices=[0.5, 0.5],
        outcomes=["Outcome 1", "Outcome 2"],
        openingTimestamp=UNIX_DAY * 5,
        processed_timestamp=0,
        n_bets=0,
        scaledLiquidityMeasure=1,
    )
    defaults.update(kwargs)
    return Bet(**defaults)


class TestSamplingBehaviour(FSMBehaviourBaseCase):
    """Tests for the SamplingBehaviour class."""

    
    path_to_skill = Path(__file__).parent.parent # Update this path as per your skill structure
    behaviour_class = SamplingBehaviour
    next_behaviour_class = None  # Replace with the actual next behaviour if available

    def fast_forward(self, data: dict) -> None:
        """Fast-forward to the SamplingBehaviour."""
        self.fast_forward_to_behaviour(
            self.behaviour,
            self.behaviour_class.auto_behaviour_id(),
            BaseSynchronizedData(AbciAppDB(data_to_lists=data)),
        )

    def test_setup_rebetting_enabled(self) -> None:
        """Test setup when rebetting is enabled."""
        self.behaviour.context.params.rebet_chance = 1.0  # Ensure rebetting
        self.behaviour.bets = [create_bet(n_bets=1)]
        self.behaviour.synchronized_data = MagicMock(most_voted_randomness=1)
        self.behaviour.setup()
        assert self.behaviour.should_rebet is True
        self.behaviour.context.logger.info.assert_called_with("Rebetting enabled.")

    def test_setup_rebetting_disabled(self) -> None:
        """Test setup when rebetting is disabled."""
        self.behaviour.context.params.rebet_chance = 0.0  # Ensure no rebetting
        self.behaviour.bets = [create_bet(n_bets=0)]
        self.behaviour.synchronized_data = MagicMock(most_voted_randomness=1)
        self.behaviour.setup()
        assert self.behaviour.should_rebet is False
        self.behaviour.context.logger.info.assert_called_with("Rebetting disabled.")

    @pytest.mark.parametrize(
        "bet,n_bets,within_ranges,expected",
        [
            (create_bet(n_bets=0), 0, True, True),
            (create_bet(n_bets=1), 1, True, True),
            (create_bet(openingTimestamp=UNIX_DAY * 2), 0, False, False),
        ],
    )
    def test_processable_bet(self, bet: Bet, n_bets: int, within_ranges: bool, expected: bool) -> None:
        """Test the processable_bet method."""
        self.behaviour.should_rebet = n_bets > 0
        self.behaviour.synced_timestamp = UNIX_DAY * 3
        self.behaviour.params.sample_bets_closing_days = 7
        self.behaviour.params.safe_voting_range = UNIX_DAY * 10
        assert self.behaviour.processable_bet(bet) == expected

    def test_sample_no_available_bets(self) -> None:
        """Test sampling when no available bets."""
        self.behaviour.bets = [create_bet(scaledLiquidityMeasure=0)]
        idx = self.behaviour._sample()
        assert idx is None
        self.behaviour.context.logger.warning.assert_called_with(
            "There were no unprocessed bets with non-zero liquidity!"
        )

    def test_sample_successful(self) -> None:
        """Test successful sampling."""
        bet = create_bet()
        self.behaviour.bets = [bet]
        self.behaviour.synced_timestamp = UNIX_DAY * 2
        idx = self.behaviour._sample()
        assert idx == 0
        assert self.behaviour.bets[0].n_bets == 1
        self.behaviour.context.logger.info.assert_called_with(f"Sampled bet: {bet}")

    def test_async_act(self) -> None:
        """Test async_act method."""
        self.behaviour.bets = [create_bet()]
        self.fast_forward({"bets": self.behaviour.bets})
        self.behaviour.act_wrapper()
        payload = SamplingPayload(self.behaviour.context.agent_address, None, 0)
        assert isinstance(payload, SamplingPayload)