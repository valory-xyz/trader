# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for the VWAP utility module."""

import pytest

from packages.valory.skills.decision_maker_abci.utils.vwap import (
    VWAPResult,
    compute_vwap,
)


class TestComputeVwap:
    """Tests for compute_vwap."""

    def test_single_level_exact_fill(self) -> None:
        """Buy exactly what one ask level offers."""
        # Ask: 100 shares at $0.50 each = $50 notional
        asks = [(0.50, 100.0)]
        result = compute_vwap(asks, budget=50.0)
        assert result.vwap == pytest.approx(0.50)
        assert result.total_shares == pytest.approx(100.0)
        assert result.budget_spent == pytest.approx(50.0)
        assert result.fully_filled is True

    def test_single_level_partial_fill(self) -> None:
        """Budget is less than what the level offers."""
        # Ask: 100 shares at $0.50 = $50 notional, but only spend $25
        asks = [(0.50, 100.0)]
        result = compute_vwap(asks, budget=25.0)
        assert result.vwap == pytest.approx(0.50)
        assert result.total_shares == pytest.approx(50.0)
        assert result.budget_spent == pytest.approx(25.0)
        assert result.fully_filled is True

    def test_multi_level_walk(self) -> None:
        """Budget walks through multiple ask levels."""
        # Level 1: 100 shares at $0.40 = $40 notional
        # Level 2: 50 shares at $0.60 = $30 notional
        # Budget = $70 → consumes both fully
        # Shares: 100 + 50 = 150, VWAP = 70/150 = 0.4667
        asks = [(0.40, 100.0), (0.60, 50.0)]
        result = compute_vwap(asks, budget=70.0)
        assert result.vwap == pytest.approx(70.0 / 150.0)
        assert result.total_shares == pytest.approx(150.0)
        assert result.budget_spent == pytest.approx(70.0)
        assert result.fully_filled is True

    def test_multi_level_partial_second(self) -> None:
        """Budget exhausted partway through second level."""
        # Level 1: 100 shares at $0.40 = $40 notional (consume all)
        # Level 2: 50 shares at $0.60 = $30 notional (only $10 remaining)
        # Budget = $50
        # Shares from L1: 100, shares from L2: 10/0.60 = 16.667
        # Total shares: 116.667, VWAP = 50/116.667 = 0.4286
        asks = [(0.40, 100.0), (0.60, 50.0)]
        result = compute_vwap(asks, budget=50.0)
        expected_shares = 100.0 + 10.0 / 0.60
        assert result.vwap == pytest.approx(50.0 / expected_shares)
        assert result.total_shares == pytest.approx(expected_shares)
        assert result.budget_spent == pytest.approx(50.0)
        assert result.fully_filled is True

    def test_book_exhausted(self) -> None:
        """Budget exceeds total book depth — partial fill."""
        # Total notional = 0.50 * 100 = $50, budget = $80
        asks = [(0.50, 100.0)]
        result = compute_vwap(asks, budget=80.0)
        assert result.vwap == pytest.approx(0.50)
        assert result.total_shares == pytest.approx(100.0)
        assert result.budget_spent == pytest.approx(50.0)
        assert result.fully_filled is False

    def test_empty_book(self) -> None:
        """No asks at all — no liquidity."""
        result = compute_vwap([], budget=100.0)
        assert result.vwap == 0.0
        assert result.total_shares == 0.0
        assert result.budget_spent == 0.0
        assert result.fully_filled is False

    def test_zero_budget(self) -> None:
        """Zero budget — nothing to spend."""
        asks = [(0.50, 100.0)]
        result = compute_vwap(asks, budget=0.0)
        assert result.vwap == 0.0
        assert result.total_shares == 0.0
        assert result.budget_spent == 0.0
        assert result.fully_filled is True

    def test_asks_unsorted(self) -> None:
        """Asks not in ascending price order — should be sorted internally."""
        # Same as test_multi_level_walk but reversed
        asks = [(0.60, 50.0), (0.40, 100.0)]
        result = compute_vwap(asks, budget=70.0)
        assert result.vwap == pytest.approx(70.0 / 150.0)
        assert result.total_shares == pytest.approx(150.0)
        assert result.fully_filled is True

    def test_skip_zero_price_level(self) -> None:
        """Ask levels with price <= 0 are skipped."""
        asks = [(0.0, 100.0), (0.50, 100.0)]
        result = compute_vwap(asks, budget=50.0)
        assert result.vwap == pytest.approx(0.50)
        assert result.total_shares == pytest.approx(100.0)
        assert result.fully_filled is True

    def test_skip_zero_size_level(self) -> None:
        """Ask levels with size <= 0 are skipped."""
        asks = [(0.30, 0.0), (0.50, 100.0)]
        result = compute_vwap(asks, budget=50.0)
        assert result.vwap == pytest.approx(0.50)
        assert result.total_shares == pytest.approx(100.0)
        assert result.fully_filled is True

    def test_skip_negative_price(self) -> None:
        """Ask levels with negative price are skipped."""
        asks = [(-0.10, 50.0), (0.50, 100.0)]
        result = compute_vwap(asks, budget=50.0)
        assert result.vwap == pytest.approx(0.50)
        assert result.total_shares == pytest.approx(100.0)
        assert result.fully_filled is True

    def test_negative_budget_treated_as_zero(self) -> None:
        """Negative budget should behave like zero budget."""
        asks = [(0.50, 100.0)]
        result = compute_vwap(asks, budget=-10.0)
        assert result.vwap == 0.0
        assert result.total_shares == 0.0
        assert result.budget_spent == 0.0
        assert result.fully_filled is True

    def test_all_levels_invalid(self) -> None:
        """All ask levels invalid — same as empty book."""
        asks = [(0.0, 100.0), (-0.50, 50.0), (0.30, 0.0)]
        result = compute_vwap(asks, budget=100.0)
        assert result.vwap == 0.0
        assert result.total_shares == 0.0
        assert result.fully_filled is False

    def test_three_levels(self) -> None:
        """Walk through three price levels."""
        # L1: 10 shares at $0.30 = $3
        # L2: 20 shares at $0.50 = $10
        # L3: 30 shares at $0.70 = $21
        # Total: $34 for 60 shares
        asks = [(0.30, 10.0), (0.50, 20.0), (0.70, 30.0)]
        result = compute_vwap(asks, budget=34.0)
        assert result.total_shares == pytest.approx(60.0)
        assert result.vwap == pytest.approx(34.0 / 60.0)
        assert result.budget_spent == pytest.approx(34.0)
        assert result.fully_filled is True

    def test_vwap_result_dataclass(self) -> None:
        """Test that VWAPResult is a proper dataclass with expected fields."""
        r = VWAPResult(
            vwap=0.5, total_shares=100.0, budget_spent=50.0, fully_filled=True
        )
        assert r.vwap == 0.5
        assert r.total_shares == 100.0
        assert r.budget_spent == 50.0
        assert r.fully_filled is True
