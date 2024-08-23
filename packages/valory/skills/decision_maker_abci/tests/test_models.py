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
"""This file contains tests for the models of decision maker skill."""

import pytest

from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext
from packages.valory.skills.decision_maker_abci.models import (
    BenchmarkingMockData,
    LiquidityInfo,
    RedeemingProgress,
    SharedState,
)


class TestLiquidityInfo:
    """Test LiquidityInfo of DecisionMakerAbci."""

    def setup(self) -> None:
        """Set up tests."""
        self.liquidity_info = LiquidityInfo(l0_end=1, l1_end=1, l0_start=1, l1_start=1)

    def test_validate_end_information_raises(self) -> None:
        """Test validate end information of LiquidityInfo raises."""

        self.liquidity_info.l0_end = None
        self.liquidity_info.l0_end = None
        with pytest.raises(ValueError):
            self.liquidity_info.validate_end_information()

    def test_validate_end_information(self) -> None:
        """Test validate end information of LiquidityInfo."""
        assert self.liquidity_info.validate_end_information() == (1, 1)

    def test_get_new_prices(self) -> None:
        """Test get new prices of LiquidityInfo."""
        assert self.liquidity_info.get_new_prices() == [0.5, 0.5]

    def test_get_end_liquidity(self) -> None:
        """Test get_end_liquidity of LiquidityInfo."""
        assert self.liquidity_info.get_end_liquidity() == [1, 1]


class TestRedeemingProgress:
    """Test RedeemingProgress of DecisionMakerAbci."""

    def setup(self) -> None:
        """Set up tests."""
        self.redeeming_progress = RedeemingProgress()

    def test_check_finished(self) -> None:
        """Test check finished."""
        self.redeeming_progress.check_started = True
        self.redeeming_progress.check_from_block = "latest"
        assert self.redeeming_progress.check_finished is True

    def test_claim_finished(self) -> None:
        """Test claim finished."""
        self.redeeming_progress.claim_started = True
        self.redeeming_progress.claim_from_block = "latest"
        assert self.redeeming_progress.claim_finished is True

    def test_claim_params(self) -> None:
        """Test claim params."""
        self.redeeming_progress.answered = [
            {"args": {"history_hash": "h1", "user": "u1", "bond": "b1", "answer": "a1"}}
        ]
        claim_params = self.redeeming_progress.claim_params
        assert claim_params == ([b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'],
                                ['u1'],
                                ['b1'],
                                ['a1'])


class TestSharedState:
    """Test SharedState of DecisionMakerAbci."""

    def setup(self) -> None:
        """Set up tests."""
        self.shared_state = SharedState(name="", skill_context=DummyContext())
        self.shared_state.mock_data = BenchmarkingMockData(
            id="dummy_id", question="dummy_question", answer="dummy_answer", p_yes=1.1
        )
        self.shared_state.liquidity_prices = {"dummy_id": [1.1]}
        self.shared_state.liquidity_amounts = {"dummy_id": [1]}
        self.shared_state.liquidity_data = {"current_liquidity_prices": [1.1]}

    def test_initialization(self) -> None:
        """Test initialization."""
        SharedState(name="", skill_context=DummyContext())

    def test_mock_question_id(self) -> None:
        """Test mock_question_id."""
        mock_question_id = self.shared_state.mock_question_id
        assert mock_question_id == "dummy_id"

    def test_get_liquidity_info(self) -> None:
        """Test _get_liquidity_info."""
        liquidity_data = {"dummy_id": [1]}
        liquidity_info = self.shared_state._get_liquidity_info(liquidity_data)
        assert liquidity_info == [1]

    def test_current_liquidity_prices(self) -> None:
        """Test current_liquidity_prices."""
        current_liquidity_prices = self.shared_state.current_liquidity_prices
        assert current_liquidity_prices == [1.1]

    def test_current_liquidity_prices_setter(self) -> None:
        """Test current_liquidity_prices setter."""
        self.shared_state.current_liquidity_prices = [2.1]
        assert self.shared_state.liquidity_prices == {'dummy_id': [2.1]}

    def test_current_liquidity_amounts(self) -> None:
        """Test current_liquidity_amounts."""
        current_liquidity_amounts = self.shared_state.current_liquidity_amounts
        assert current_liquidity_amounts == [1]

    def test_current_liquidity_amounts_setter(self) -> None:
        """Test current_liquidity_prices setter."""
        self.shared_state.current_liquidity_amounts = [2]
        assert self.shared_state.liquidity_amounts == {"dummy_id": [2]}
