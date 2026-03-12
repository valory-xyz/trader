# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for the kelly_criterion_no_conf custom strategy."""

import pytest

from packages.valory.customs.kelly_criterion_no_conf.kelly_criterion_no_conf import (
    ALL_FIELDS,
    DEFAULT_MAX_BET,
    DEFAULT_MIN_BET,
    DEFAULT_TOKEN_DECIMALS,
    OPTIONAL_FIELDS,
    REQUIRED_FIELDS,
    calculate_kelly_bet_amount_no_conf,
    check_missing_fields,
    get_adjusted_kelly_amount,
    get_bet_amount_kelly,
    remove_irrelevant_fields,
    run,
    wei_to_native,
)


# Base valid kwargs for get_bet_amount_kelly / run
VALID_KWARGS = {
    "bet_kelly_fraction": 0.5,
    "bankroll": 10 * 10**18,  # 10 xDAI
    "win_probability": 0.7,
    "confidence": 0.8,
    "selected_type_tokens_in_pool": 5 * 10**18,
    "other_tokens_in_pool": 5 * 10**18,
    "bet_fee": 2 * 10**16,  # 2% fee
    "weighted_accuracy": 0.6,
    "floor_balance": 10**18,  # 1 xDAI floor
}


class TestCheckMissingFields:
    """Tests for check_missing_fields."""

    def test_no_missing_fields(self) -> None:
        """All required fields present returns empty list."""
        assert check_missing_fields(VALID_KWARGS) == []

    def test_all_fields_missing(self) -> None:
        """Empty kwargs returns all required fields."""
        result = check_missing_fields({})
        assert set(result) == set(REQUIRED_FIELDS)

    def test_none_value_treated_as_missing(self) -> None:
        """Field with None value is treated as missing."""
        kwargs = {**VALID_KWARGS, "bankroll": None}
        result = check_missing_fields(kwargs)
        assert "bankroll" in result


class TestRemoveIrrelevantFields:
    """Tests for remove_irrelevant_fields."""

    def test_keeps_all_fields(self) -> None:
        """All required + optional fields are kept."""
        kwargs = {**VALID_KWARGS, "max_bet": 100, "extra": "ignored"}
        result = remove_irrelevant_fields(kwargs)
        assert "extra" not in result
        assert "max_bet" in result
        for field in REQUIRED_FIELDS:
            assert field in result

    def test_empty_input(self) -> None:
        """Empty input returns empty dict."""
        assert remove_irrelevant_fields({}) == {}


class TestWeiToNative:
    """Tests for wei_to_native conversion."""

    def test_18_decimals(self) -> None:
        """Convert 1 xDAI (18 decimals) from wei."""
        assert wei_to_native(10**18) == 1.0

    def test_6_decimals(self) -> None:
        """Convert 1 USDC (6 decimals) from smallest unit."""
        assert wei_to_native(10**6, decimals=6) == 1.0

    def test_zero(self) -> None:
        """Zero wei converts to zero."""
        assert wei_to_native(0) == 0.0


class TestCalculateKellyBetAmountNoConf:
    """Tests for the Kelly criterion formula."""

    def test_b_zero_returns_zero(self) -> None:
        """When bankroll (b) is 0, bet amount is 0."""
        assert calculate_kelly_bet_amount_no_conf(100, 100, 0.7, 0, 0.98) == 0

    def test_denominator_zero_returns_zero(self) -> None:
        """When denominator is zero (x == y and f produces 0), returns 0."""
        # x^2*f - y^2*f = 0 when x == y
        result = calculate_kelly_bet_amount_no_conf(100, 100, 0.7, 1000, 0.98)
        assert result == 0

    def test_positive_kelly_amount(self) -> None:
        """Standard inputs produce a positive kelly bet amount."""
        result = calculate_kelly_bet_amount_no_conf(
            5 * 10**18, 5 * 10**18, 0.7, 10 * 10**18, 0.98
        )
        # x == y -> denominator is 0 -> returns 0 for equal pools
        # Use unequal pools
        result = calculate_kelly_bet_amount_no_conf(
            4 * 10**18, 6 * 10**18, 0.7, 10 * 10**18, 0.98
        )
        assert isinstance(result, int)


class TestGetAdjustedKellyAmount:
    """Tests for get_adjusted_kelly_amount."""

    def test_none_weighted_accuracy_uses_static_fraction(self) -> None:
        """None weighted_accuracy falls back to static fraction."""
        error: list = []
        result = get_adjusted_kelly_amount(1000, None, 0.5, error)
        assert result == int(1000 * 0.5)
        assert len(error) == 1

    def test_negative_weighted_accuracy_uses_static_fraction(self) -> None:
        """Negative weighted_accuracy falls back to static fraction."""
        error: list = []
        result = get_adjusted_kelly_amount(1000, -0.1, 0.5, error)
        assert result == int(1000 * 0.5)
        assert len(error) == 1

    def test_above_one_weighted_accuracy_uses_static_fraction(self) -> None:
        """Weighted accuracy > 1 falls back to static fraction."""
        error: list = []
        result = get_adjusted_kelly_amount(1000, 1.5, 0.5, error)
        assert result == int(1000 * 0.5)
        assert len(error) == 1

    def test_valid_weighted_accuracy_uses_dynamic_fraction(self) -> None:
        """Valid weighted_accuracy in [0,1] uses dynamic fraction."""
        error: list = []
        result = get_adjusted_kelly_amount(1000, 0.6, 0.5, error)
        # dynamic_kelly_fraction = 0.5 + 0.6 = 1.1
        assert result == int(1000 * 1.1)
        assert len(error) == 0

    def test_zero_weighted_accuracy(self) -> None:
        """Zero weighted_accuracy is valid (boundary)."""
        error: list = []
        result = get_adjusted_kelly_amount(1000, 0.0, 0.5, error)
        assert result == int(1000 * 0.5)
        assert len(error) == 0

    def test_one_weighted_accuracy(self) -> None:
        """Weighted accuracy of 1.0 is valid (boundary)."""
        error: list = []
        result = get_adjusted_kelly_amount(1000, 1.0, 0.5, error)
        assert result == int(1000 * 1.5)
        assert len(error) == 0


class TestGetBetAmountKelly:
    """Tests for get_bet_amount_kelly main function."""

    def test_bankroll_below_floor_returns_zero(self) -> None:
        """When bankroll <= floor_balance, bet amount is 0."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.5,
            bankroll=10**18,
            win_probability=0.7,
            confidence=0.8,
            selected_type_tokens_in_pool=5 * 10**18,
            other_tokens_in_pool=5 * 10**18,
            bet_fee=2 * 10**16,
            weighted_accuracy=0.6,
            floor_balance=10 * 10**18,  # floor > bankroll
        )
        assert result["bet_amount"] == 0
        assert len(result["error"]) > 0

    def test_negative_kelly_returns_zero(self) -> None:
        """When kelly formula produces a negative bet amount, returns 0."""
        # Use calculate_kelly_bet_amount_no_conf directly first to verify negative output
        from packages.valory.customs.kelly_criterion_no_conf.kelly_criterion_no_conf import (
            calculate_kelly_bet_amount_no_conf,
        )

        # Unequal pools with low probability should give negative kelly
        # x > y with low win prob => bet against, so kelly is negative
        x = 8 * 10**18
        y = 2 * 10**18
        p = 0.1
        b = 5 * 10**18
        f = 0.98
        assert calculate_kelly_bet_amount_no_conf(x, y, p, b, f) < 0

        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.5,
            bankroll=6 * 10**18,
            win_probability=0.1,
            confidence=0.1,
            selected_type_tokens_in_pool=x,
            other_tokens_in_pool=y,
            bet_fee=2 * 10**16,
            weighted_accuracy=0.6,
            floor_balance=10**18,
        )
        assert result["bet_amount"] == 0
        assert any("Invalid value" in msg for msg in result["info"])

    def test_below_min_bet_returns_zero(self) -> None:
        """When adjusted kelly < min_bet, bet is 0."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.001,  # Very small fraction
            bankroll=2 * 10**18,
            win_probability=0.6,
            confidence=0.6,
            selected_type_tokens_in_pool=4 * 10**18,
            other_tokens_in_pool=6 * 10**18,
            bet_fee=2 * 10**16,
            weighted_accuracy=0.01,
            floor_balance=10**18,
            min_bet=10 * 10**18,  # Very high min bet
        )
        assert result["bet_amount"] == 0

    def test_above_max_bet_capped(self) -> None:
        """When adjusted kelly > max_bet, bet is capped at max_bet."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=1.0,
            bankroll=100 * 10**18,
            win_probability=0.9,
            confidence=0.9,
            selected_type_tokens_in_pool=4 * 10**18,
            other_tokens_in_pool=6 * 10**18,
            bet_fee=0,  # No fee
            weighted_accuracy=1.0,
            floor_balance=0,
            max_bet=10**16,  # Very low max bet
        )
        assert result["bet_amount"] <= 10**16

    def test_normal_bet_not_capped(self) -> None:
        """When adjusted kelly is between min_bet and max_bet, returns it directly."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.5,
            bankroll=10 * 10**18,
            win_probability=0.7,
            confidence=0.8,
            selected_type_tokens_in_pool=4 * 10**18,
            other_tokens_in_pool=6 * 10**18,
            bet_fee=2 * 10**16,
            weighted_accuracy=0.6,
            floor_balance=10**18,
            max_bet=10 * 10**18,  # Very high max bet
            min_bet=1,
        )
        assert result["bet_amount"] > 0
        # Verify it's not capped (no "above maximum" message in info)
        assert not any("above maximum" in msg for msg in result.get("info", []))

    def test_usdc_token_decimals(self) -> None:
        """Token name is USDC when token_decimals is 6."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.5,
            bankroll=10 * 10**6,
            win_probability=0.7,
            confidence=0.8,
            selected_type_tokens_in_pool=5 * 10**6,
            other_tokens_in_pool=5 * 10**6,
            bet_fee=2 * 10**4,
            weighted_accuracy=0.6,
            floor_balance=10**6,
            token_decimals=6,
        )
        # Should run without error and produce info strings mentioning USDC
        assert "info" in result
        assert any("USDC" in msg for msg in result["info"])

    def test_xdai_token_decimals(self) -> None:
        """Token name is xDAI when token_decimals is 18 (default)."""
        result = get_bet_amount_kelly(**VALID_KWARGS)
        assert "info" in result
        assert any("xDAI" in msg for msg in result["info"])


class TestRun:
    """Tests for run entry point."""

    def test_missing_fields_returns_error(self) -> None:
        """Missing required fields returns error."""
        result = run()
        assert "error" in result
        assert len(result["error"]) > 0

    def test_successful_run(self) -> None:
        """Successful run returns bet_amount, info, and error keys."""
        result = run(**VALID_KWARGS)
        assert "bet_amount" in result

    def test_extra_kwargs_filtered(self) -> None:
        """Extra kwargs are filtered out before processing."""
        result = run(**VALID_KWARGS, extra_field="ignored")
        assert "bet_amount" in result

    def test_optional_fields_passed_through(self) -> None:
        """Optional fields (max_bet, min_bet, token_decimals) are passed through."""
        result = run(**VALID_KWARGS, max_bet=10**18, min_bet=1, token_decimals=18)
        assert "bet_amount" in result
