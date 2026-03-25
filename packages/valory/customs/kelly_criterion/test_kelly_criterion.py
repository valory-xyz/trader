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

"""Tests for the kelly_criterion strategy."""

import pytest

from packages.valory.customs.kelly_criterion.kelly_criterion import (
    fpmm_execution,
    optimize_side,
    run,
    walk_book,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Shared orderbook: 3 ask levels at 0.55, 0.57, 0.60
SAMPLE_ASKS = [
    {"price": "0.55", "size": "100"},
    {"price": "0.57", "size": "100"},
    {"price": "0.60", "size": "100"},
]

# Base valid CLOB kwargs (Polymarket-style, USDC 6 decimals)
CLOB_KWARGS = {
    "bankroll": 10_000_000,  # 10 USDC
    "p_yes": 0.70,
    "market_type": "clob",
    "floor_balance": 0,
    "price_yes": 0.55,
    "price_no": 0.45,
    "token_decimals": 6,
    "max_bet": 5_000_000,  # 5 USDC
    "n_bets": 1,
    "min_edge": 0.03,
    "orderbook_asks_yes": SAMPLE_ASKS,
    "orderbook_asks_no": [
        {"price": "0.45", "size": "100"},
        {"price": "0.47", "size": "100"},
    ],
}

# Base valid FPMM kwargs (Omen-style, xDAI 18 decimals)
FPMM_KWARGS = {
    "bankroll": int(2e18),  # 2 xDAI
    "p_yes": 0.65,
    "market_type": "fpmm",
    "floor_balance": int(0.5e18),
    "price_yes": 0.50,
    "price_no": 0.50,
    "token_decimals": 18,
    "tokens_yes": int(100e18),
    "tokens_no": int(100e18),
    "bet_fee": int(0.02e18),  # 2% fee
    "max_bet": int(8e17),
    "n_bets": 1,
    "min_edge": 0.03,
}


# ---------------------------------------------------------------------------
# walk_book
# ---------------------------------------------------------------------------


class TestWalkBook:
    """Tests for CLOB orderbook walking."""

    def test_single_level_full_fill(self) -> None:
        """Single ask level, budget covers the entire level."""
        asks = [{"price": "0.50", "size": "10"}]
        cost, shares = walk_book(asks, spend=10.0)
        assert cost == pytest.approx(5.0)
        assert shares == pytest.approx(10.0)

    def test_multi_level_walks_cheapest_first(self) -> None:
        """Multiple levels are consumed cheapest-first."""
        asks = [
            {"price": "0.60", "size": "10"},
            {"price": "0.50", "size": "10"},
        ]
        # Budget 5.0 fills the 0.50 level entirely (cost=5.0, shares=10)
        cost, shares = walk_book(asks, spend=5.0)
        assert cost == pytest.approx(5.0)
        assert shares == pytest.approx(10.0)

    def test_partial_fill_mid_level(self) -> None:
        """Budget exhausts partway through a level."""
        asks = [{"price": "0.50", "size": "100"}]
        cost, shares = walk_book(asks, spend=3.0)
        assert cost == pytest.approx(3.0)
        assert shares == pytest.approx(6.0)  # 3.0 / 0.50

    def test_multi_level_accumulation(self) -> None:
        """Walk across three levels and accumulate shares."""
        # Total book: 0.55*100 + 0.57*100 + 0.60*100 = 172 USDC for 300 shares
        # Budget 150 fills L1 (55) + L2 (57) + partial L3: (150-112)/0.60
        cost, shares = walk_book(SAMPLE_ASKS, spend=150.0)
        assert cost == pytest.approx(150.0)
        expected_shares = 100 + 100 + (150 - 55 - 57) / 0.60
        assert shares == pytest.approx(expected_shares)

    def test_empty_asks(self) -> None:
        """Empty asks returns zero."""
        cost, shares = walk_book([], spend=10.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_zero_spend(self) -> None:
        """Zero spend returns zero."""
        cost, shares = walk_book(SAMPLE_ASKS, spend=0.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_negative_spend(self) -> None:
        """Negative spend returns zero."""
        cost, shares = walk_book(SAMPLE_ASKS, spend=-5.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_zero_price_level_skipped(self) -> None:
        """Level with price=0 is skipped."""
        asks = [
            {"price": "0", "size": "100"},
            {"price": "0.50", "size": "10"},
        ]
        cost, shares = walk_book(asks, spend=10.0)
        assert cost == pytest.approx(5.0)
        assert shares == pytest.approx(10.0)

    def test_zero_size_level_skipped(self) -> None:
        """Level with size=0 is skipped."""
        asks = [
            {"price": "0.50", "size": "0"},
            {"price": "0.60", "size": "10"},
        ]
        cost, shares = walk_book(asks, spend=10.0)
        assert cost == pytest.approx(6.0)
        assert shares == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# fpmm_execution
# ---------------------------------------------------------------------------


class TestFpmmExecution:
    """Tests for FPMM constant-product execution model."""

    def test_basic_calculation(self) -> None:
        """Known inputs produce correct shares via the formula."""
        # shares = alpha*b + x - x*y/(y + alpha*b)
        b, x, y, alpha = 1.0, 100.0, 100.0, 0.98
        cost, shares = fpmm_execution(b, x, y, alpha)
        assert cost == pytest.approx(1.0)
        expected = 0.98 * 1.0 + 100.0 - 100.0 * 100.0 / (100.0 + 0.98 * 1.0)
        assert shares == pytest.approx(expected)

    def test_zero_bet(self) -> None:
        """Zero bet returns zero."""
        cost, shares = fpmm_execution(0.0, 100.0, 100.0, 1.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_negative_bet(self) -> None:
        """Negative bet returns zero."""
        cost, shares = fpmm_execution(-1.0, 100.0, 100.0, 1.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_zero_y_reserve(self) -> None:
        """Zero y reserve returns zero (no opposite tokens)."""
        cost, shares = fpmm_execution(1.0, 100.0, 0.0, 1.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_negative_denominator(self) -> None:
        """Negative alpha making denominator <= 0 returns zero."""
        cost, shares = fpmm_execution(1.0, 100.0, 1.0, alpha=-2.0)
        assert cost == 0.0
        assert shares == 0.0

    def test_no_fee(self) -> None:
        """Alpha=1.0 means no fee."""
        b, x, y = 2.0, 50.0, 50.0
        cost, shares = fpmm_execution(b, x, y, alpha=1.0)
        expected = 1.0 * 2.0 + 50.0 - 50.0 * 50.0 / (50.0 + 1.0 * 2.0)
        assert shares == pytest.approx(expected)

    def test_equal_pools_symmetric(self) -> None:
        """Equal pool reserves (50/50 market)."""
        b, x, y, alpha = 1.0, 100.0, 100.0, 1.0
        cost, shares = fpmm_execution(b, x, y, alpha)
        assert cost == pytest.approx(1.0)
        assert shares > 0

    def test_shares_always_nonnegative(self) -> None:
        """Shares should never be negative."""
        # Small bet on extremely skewed pool
        _, shares = fpmm_execution(0.001, 1000.0, 1.0, 0.5)
        assert shares >= 0.0


# ---------------------------------------------------------------------------
# optimize_side
# ---------------------------------------------------------------------------


class TestOptimizeSide:
    """Tests for grid-search optimizer."""

    def test_clob_finds_positive_g_improvement(self) -> None:
        """CLOB scenario with strong edge finds a bet that beats no-trade."""
        best_spend, best_shares, best_g, g_baseline = optimize_side(
            p=0.70,
            w_bet=5.0,
            b_min=0.1,
            b_max=5.0,
            fee=0.01,
            grid_points=100,
            market_type="clob",
            asks=SAMPLE_ASKS,
        )
        assert best_spend > 0
        assert best_shares > 0
        assert best_g > g_baseline

    def test_fpmm_finds_positive_g_improvement(self) -> None:
        """FPMM scenario with edge finds a bet that beats no-trade."""
        best_spend, best_shares, best_g, g_baseline = optimize_side(
            p=0.65,
            w_bet=0.8,
            b_min=0.001,
            b_max=0.8,
            fee=0.01,
            grid_points=100,
            market_type="fpmm",
            x=100.0,
            y=100.0,
            alpha=0.98,
        )
        assert best_spend > 0
        assert best_shares > 0
        assert best_g > g_baseline

    def test_no_edge_returns_baseline(self) -> None:
        """Very high fee wipes out any potential edge."""
        best_spend, _, best_g, g_baseline = optimize_side(
            p=0.51,
            w_bet=5.0,
            b_min=0.1,
            b_max=5.0,
            fee=100.0,  # absurd fee
            grid_points=100,
            market_type="clob",
            asks=[{"price": "0.50", "size": "1000"}],
        )
        assert best_spend == 0.0
        assert best_g == g_baseline

    def test_zero_w_bet(self) -> None:
        """Zero per-bet bankroll returns baseline."""
        best_spend, _, best_g, g_baseline = optimize_side(
            p=0.70,
            w_bet=0.0,
            b_min=0.1,
            b_max=5.0,
            fee=0.01,
            grid_points=100,
            market_type="clob",
            asks=SAMPLE_ASKS,
        )
        assert best_spend == 0.0

    def test_zero_b_max(self) -> None:
        """Zero max bet returns baseline."""
        best_spend, _, _, _ = optimize_side(
            p=0.70,
            w_bet=5.0,
            b_min=0.0,
            b_max=0.0,
            fee=0.01,
            grid_points=100,
            market_type="clob",
            asks=SAMPLE_ASKS,
        )
        assert best_spend == 0.0

    def test_grid_points_clamped_minimum(self) -> None:
        """Grid points < 2 is clamped to 2."""
        best_spend, _, best_g, g_baseline = optimize_side(
            p=0.70,
            w_bet=5.0,
            b_min=0.1,
            b_max=3.0,
            fee=0.01,
            grid_points=1,
            market_type="clob",
            asks=SAMPLE_ASKS,
        )
        # Should still produce a result (2 grid points: b_min and b_max)
        assert best_g >= g_baseline

    def test_b_min_clamped_to_b_max(self) -> None:
        """When b_min > b_max, b_min is clamped to b_max."""
        best_spend, _, _, _ = optimize_side(
            p=0.70,
            w_bet=5.0,
            b_min=10.0,  # > b_max
            b_max=3.0,
            fee=0.01,
            grid_points=100,
            market_type="clob",
            asks=SAMPLE_ASKS,
        )
        # Should not crash; evaluates only at b_max
        assert best_spend >= 0.0


# ---------------------------------------------------------------------------
# run — missing / invalid inputs
# ---------------------------------------------------------------------------


class TestRunValidation:
    """Tests for run() input validation."""

    def test_missing_required_fields(self) -> None:
        """Missing required fields returns error."""
        result = run()
        assert result["bet_amount"] == 0
        assert result["vote"] is None
        assert "error" in result
        assert len(result["error"]) > 0

    def test_missing_single_field(self) -> None:
        """Missing one required field is reported."""
        kwargs = {**CLOB_KWARGS}
        del kwargs["bankroll"]
        result = run(**kwargs)
        assert result["bet_amount"] == 0
        assert any("bankroll" in str(e) for e in result["error"])

    def test_bankroll_below_floor(self) -> None:
        """Bankroll <= floor_balance returns no trade."""
        result = run(**{**CLOB_KWARGS, "bankroll": 1_000_000, "floor_balance": 2_000_000})
        assert result["bet_amount"] == 0

    def test_zero_bankroll(self) -> None:
        """Zero bankroll returns no trade."""
        result = run(**{**CLOB_KWARGS, "bankroll": 0})
        assert result["bet_amount"] == 0

    def test_invalid_p_yes_above_one(self) -> None:
        """p_yes > 1 returns error."""
        result = run(**{**CLOB_KWARGS, "p_yes": 1.5})
        assert result["bet_amount"] == 0
        assert len(result["error"]) > 0

    def test_invalid_p_yes_negative(self) -> None:
        """p_yes < 0 returns error."""
        result = run(**{**CLOB_KWARGS, "p_yes": -0.1})
        assert result["bet_amount"] == 0

    def test_invalid_p_yes_exactly_zero(self) -> None:
        """p_yes = 0 returns error (boundary)."""
        result = run(**{**CLOB_KWARGS, "p_yes": 0.0})
        assert result["bet_amount"] == 0

    def test_invalid_p_yes_exactly_one(self) -> None:
        """p_yes = 1.0 returns error (boundary)."""
        result = run(**{**CLOB_KWARGS, "p_yes": 1.0})
        assert result["bet_amount"] == 0

    def test_unknown_kwargs_no_crash(self) -> None:
        """Extra unknown kwargs are silently ignored."""
        result = run(**{**CLOB_KWARGS, "unknown_field": "hello"})
        assert "bet_amount" in result


# ---------------------------------------------------------------------------
# run — edge / oracle prob filters
# ---------------------------------------------------------------------------


class TestRunFilters:
    """Tests for edge and oracle probability filters."""

    def test_edge_below_min_edge_clob(self) -> None:
        """CLOB: small edge rejected by pre-filter."""
        result = run(
            **{
                **CLOB_KWARGS,
                "p_yes": 0.56,  # edge vs best ask 0.55 = 0.01 < min_edge 0.03
            }
        )
        assert result["bet_amount"] == 0

    def test_edge_below_min_edge_fpmm(self) -> None:
        """FPMM: small edge rejected by pre-filter."""
        result = run(
            **{
                **FPMM_KWARGS,
                "p_yes": 0.52,  # edge vs price 0.50 = 0.02 < min_edge 0.03
            }
        )
        assert result["bet_amount"] == 0

    def test_oracle_prob_below_min(self) -> None:
        """Both sides rejected when neither meets min_oracle_prob."""
        result = run(
            **{
                **CLOB_KWARGS,
                "p_yes": 0.50,
                "min_oracle_prob": 0.6,  # neither side reaches 0.6
            }
        )
        assert result["bet_amount"] == 0

    def test_min_oracle_prob_zero_allows_all(self) -> None:
        """min_oracle_prob=0 disables the filter."""
        result = run(
            **{
                **CLOB_KWARGS,
                "p_yes": 0.70,
                "min_oracle_prob": 0.0,
            }
        )
        # YES side should pass (edge 0.70-0.55=0.15 > 0.03)
        assert result["bet_amount"] > 0


# ---------------------------------------------------------------------------
# run — CLOB scenarios
# ---------------------------------------------------------------------------


class TestRunClob:
    """Tests for run() with CLOB market type."""

    def test_positive_bet(self) -> None:
        """Standard CLOB scenario produces a positive bet."""
        result = run(**CLOB_KWARGS)
        assert result["bet_amount"] > 0
        assert result["vote"] == 0  # YES side (p_yes=0.70 > p_no=0.30)
        assert result["g_improvement"] > 0
        assert result["expected_profit"] > 0

    def test_no_orderbook_returns_zero(self) -> None:
        """Missing orderbook for the viable side returns no trade."""
        kwargs = {**CLOB_KWARGS, "orderbook_asks_yes": None}
        result = run(**kwargs)
        # YES has no orderbook; NO has prob 0.30 < min_oracle_prob 0.5
        assert result["bet_amount"] == 0

    def test_empty_orderbook_returns_zero(self) -> None:
        """Empty orderbook list returns no trade."""
        kwargs = {**CLOB_KWARGS, "orderbook_asks_yes": []}
        result = run(**kwargs)
        assert result["bet_amount"] == 0

    def test_insufficient_depth_for_min_order_shares(self) -> None:
        """Book depth < min_order_shares returns no trade."""
        kwargs = {
            **CLOB_KWARGS,
            "orderbook_asks_yes": [{"price": "0.55", "size": "2"}],
            "min_order_shares": 10.0,  # need 10 but only 2 available
        }
        result = run(**kwargs)
        assert result["bet_amount"] == 0

    def test_clob_zero_price_level_in_venue_min_calc(self) -> None:
        """Zero-price level skipped during venue min spend calculation."""
        kwargs = {
            **CLOB_KWARGS,
            "orderbook_asks_yes": [
                {"price": "0", "size": "100"},  # skipped
                {"price": "0.55", "size": "100"},
                {"price": "0.57", "size": "100"},
            ],
        }
        result = run(**kwargs)
        # Should still work — zero-price level is skipped
        assert result["bet_amount"] > 0

    def test_return_format(self) -> None:
        """Result dict has all required keys."""
        result = run(**CLOB_KWARGS)
        assert "bet_amount" in result
        assert "vote" in result
        assert "expected_profit" in result
        assert "g_improvement" in result
        assert "info" in result
        assert "error" in result


# ---------------------------------------------------------------------------
# run — FPMM scenarios
# ---------------------------------------------------------------------------


class TestRunFpmm:
    """Tests for run() with FPMM market type."""

    def test_positive_bet(self) -> None:
        """Standard FPMM scenario produces a positive bet."""
        result = run(**FPMM_KWARGS)
        assert result["bet_amount"] > 0
        assert result["vote"] == 0  # YES side (p_yes=0.65)
        assert result["g_improvement"] > 0

    def test_equal_pools_with_edge(self) -> None:
        """50/50 pool with p_yes edge should bet YES."""
        result = run(**FPMM_KWARGS)
        assert result["vote"] == 0

    def test_both_sides_evaluated_fpmm(self) -> None:
        """With min_oracle_prob=0, both sides reach the FPMM edge filter."""
        result = run(
            **{
                **FPMM_KWARGS,
                "p_yes": 0.55,
                "min_oracle_prob": 0.0,
                "min_edge": 0.0,
            }
        )
        info_text = " ".join(result.get("info", []))
        assert "yes:" in info_text
        assert "no:" in info_text

    def test_usdc_decimals(self) -> None:
        """FPMM with token_decimals=6 (hypothetical) uses USDC scale."""
        kwargs = {
            **FPMM_KWARGS,
            "bankroll": 10_000_000,
            "floor_balance": 0,
            "tokens_yes": 100_000_000,
            "tokens_no": 100_000_000,
            "bet_fee": 20_000,
            "max_bet": 5_000_000,
            "token_decimals": 6,
        }
        result = run(**kwargs)
        assert any("USDC" in msg for msg in result.get("info", []))


# ---------------------------------------------------------------------------
# run — side selection
# ---------------------------------------------------------------------------


class TestRunSideSelection:
    """Tests for strategy-driven side selection."""

    def test_vote_yes_when_p_yes_dominant(self) -> None:
        """p_yes=0.70 with edge → vote=0 (YES)."""
        result = run(**CLOB_KWARGS)
        assert result["vote"] == 0

    def test_vote_no_when_p_no_dominant(self) -> None:
        """p_yes=0.30 → p_no=0.70, NO side has edge → vote=1."""
        kwargs = {
            **CLOB_KWARGS,
            "p_yes": 0.30,
            "price_yes": 0.45,
            "price_no": 0.55,
            "orderbook_asks_yes": [
                {"price": "0.45", "size": "100"},
                {"price": "0.47", "size": "100"},
            ],
            "orderbook_asks_no": SAMPLE_ASKS,
        }
        result = run(**kwargs)
        assert result["vote"] == 1

    def test_both_sides_evaluated_in_info(self) -> None:
        """Info logs show both sides were considered."""
        # Use min_oracle_prob=0 so both sides are evaluated
        kwargs = {
            **CLOB_KWARGS,
            "p_yes": 0.55,
            "min_oracle_prob": 0.0,
            "min_edge": 0.0,
            "orderbook_asks_no": [
                {"price": "0.45", "size": "100"},
                {"price": "0.47", "size": "100"},
            ],
        }
        result = run(**kwargs)
        info_text = " ".join(result.get("info", []))
        assert "yes:" in info_text
        assert "no:" in info_text


# ---------------------------------------------------------------------------
# run — n_bets effect
# ---------------------------------------------------------------------------


class TestRunNBets:
    """Tests for n_bets bankroll depth parameter."""

    def test_higher_n_bets_allows_larger_bet(self) -> None:
        """Higher n_bets → larger W_bet → potentially larger bet."""
        result_n1 = run(**{**CLOB_KWARGS, "n_bets": 1})
        result_n5 = run(**{**CLOB_KWARGS, "n_bets": 5})
        # With n_bets=5, W_bet = min(5*5, 10) = 10 vs min(1*5, 10) = 5
        # Larger W_bet should allow at least as large a bet
        assert result_n5["bet_amount"] >= result_n1["bet_amount"]


# ---------------------------------------------------------------------------
# run — max_bet constraint
# ---------------------------------------------------------------------------


class TestRunMaxBet:
    """Tests for max_bet constraint."""

    def test_bet_capped_at_max_bet(self) -> None:
        """Bet amount cannot exceed max_bet in wei."""
        result = run(**{**CLOB_KWARGS, "max_bet": 100_000})  # 0.10 USDC
        assert result["bet_amount"] <= 100_000
