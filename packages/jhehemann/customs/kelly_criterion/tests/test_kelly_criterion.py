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

"""Tests for the kelly_criterion custom strategy."""

from packages.jhehemann.customs.kelly_criterion.kelly_criterion import (
    REQUIRED_FIELDS,
    calculate_kelly_bet_amount,
    check_missing_fields,
    get_bet_amount_kelly,
    remove_irrelevant_fields,
    run,
    wei_to_native,
)

VALID_KWARGS = {
    "bet_kelly_fraction": 0.5,
    "bankroll": 10 * 10**18,
    "win_probability": 0.7,
    "confidence": 0.8,
    "selected_type_tokens_in_pool": 5 * 10**18,
    "other_tokens_in_pool": 5 * 10**18,
    "bet_fee": 2 * 10**16,
    "floor_balance": 10**18,
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

    def test_keeps_relevant_fields(self) -> None:
        """Relevant fields are kept, extra fields removed."""
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


class TestCalculateKellyBetAmount:
    """Tests for the Kelly criterion formula."""

    def test_b_zero_returns_zero(self) -> None:
        """When bankroll (b) is 0, bet amount is 0."""
        assert calculate_kelly_bet_amount(100, 100, 0.7, 0.8, 0, 0.98) == 0

    def test_denominator_zero_returns_zero(self) -> None:
        """When x == y and fee makes denominator zero, returns 0."""
        result = calculate_kelly_bet_amount(100, 100, 0.7, 0.8, 1000, 0.98)
        assert result == 0

    def test_positive_kelly_amount(self) -> None:
        """Unequal pools produce a calculable kelly bet amount."""
        result = calculate_kelly_bet_amount(
            4 * 10**18, 6 * 10**18, 0.7, 0.8, 10 * 10**18, 0.98
        )
        assert isinstance(result, int)


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
            floor_balance=10 * 10**18,
        )
        assert result["bet_amount"] == 0
        assert len(result["error"]) > 0

    def test_negative_kelly_returns_zero(self) -> None:
        """When kelly formula produces negative, returns 0."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.5,
            bankroll=6 * 10**18,
            win_probability=0.1,
            confidence=0.1,
            selected_type_tokens_in_pool=8 * 10**18,
            other_tokens_in_pool=2 * 10**18,
            bet_fee=2 * 10**16,
            floor_balance=10**18,
        )
        assert result["bet_amount"] == 0

    def test_below_min_bet_returns_zero(self) -> None:
        """When adjusted kelly < min_bet, bet is 0."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.001,
            bankroll=2 * 10**18,
            win_probability=0.6,
            confidence=0.6,
            selected_type_tokens_in_pool=4 * 10**18,
            other_tokens_in_pool=6 * 10**18,
            bet_fee=2 * 10**16,
            floor_balance=10**18,
            min_bet=10 * 10**18,
        )
        assert result["bet_amount"] == 0

    def test_above_max_bet_capped(self) -> None:
        """When adjusted kelly > max_bet, bet is capped."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=10.0,
            bankroll=100 * 10**18,
            win_probability=0.9,
            confidence=0.9,
            selected_type_tokens_in_pool=6 * 10**18,
            other_tokens_in_pool=4 * 10**18,
            bet_fee=0,
            floor_balance=0,
            max_bet=10**16,
        )
        assert result["bet_amount"] == 10**16

    def test_normal_bet(self) -> None:
        """When adjusted kelly is between min and max, returns it."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=1.0,
            bankroll=20 * 10**18,
            win_probability=0.9,
            confidence=0.9,
            selected_type_tokens_in_pool=3 * 10**18,
            other_tokens_in_pool=7 * 10**18,
            bet_fee=0,
            floor_balance=10**18,
            max_bet=100 * 10**18,
            min_bet=1,
        )
        assert result["bet_amount"] > 0

    def test_usdc_token_name(self) -> None:
        """Token name is USDC when token_decimals is 6."""
        result = get_bet_amount_kelly(
            bet_kelly_fraction=0.5,
            bankroll=10 * 10**6,
            win_probability=0.7,
            confidence=0.8,
            selected_type_tokens_in_pool=5 * 10**6,
            other_tokens_in_pool=5 * 10**6,
            bet_fee=2 * 10**4,
            floor_balance=10**6,
            token_decimals=6,
        )
        assert any("USDC" in msg for msg in result["info"])

    def test_xdai_token_name(self) -> None:
        """Token name is xDAI when token_decimals is 18."""
        result = get_bet_amount_kelly(**VALID_KWARGS)
        assert any("xDAI" in msg for msg in result["info"])


class TestRun:
    """Tests for run entry point."""

    def test_missing_fields_returns_error(self) -> None:
        """Missing required fields returns error."""
        result = run()
        assert "error" in result
        assert len(result["error"]) > 0

    def test_successful_run(self) -> None:
        """Successful run returns bet_amount."""
        result = run(**VALID_KWARGS)
        assert "bet_amount" in result

    def test_extra_kwargs_filtered(self) -> None:
        """Extra kwargs are filtered out before processing."""
        result = run(**VALID_KWARGS, extra_field="ignored")
        assert "bet_amount" in result

    def test_optional_fields_passed(self) -> None:
        """Optional fields are passed through."""
        result = run(**VALID_KWARGS, max_bet=10**18, min_bet=1, token_decimals=18)
        assert "bet_amount" in result
