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

"""Tests for the fixed_bet strategy."""

from packages.valory.customs.fixed_bet.fixed_bet import run


class TestRunValidation:
    """Tests for run() input validation."""

    def test_missing_required_fields(self) -> None:
        """Missing required fields returns error."""
        result = run()
        assert result["bet_amount"] == 0
        assert result["vote"] is None
        assert len(result["error"]) > 0

    def test_missing_bankroll(self) -> None:
        """Missing bankroll is reported."""
        result = run(floor_balance=0, p_yes=0.7)
        assert result["bet_amount"] == 0
        assert any("bankroll" in str(e) for e in result["error"])

    def test_missing_p_yes(self) -> None:
        """Missing p_yes is reported."""
        result = run(bankroll=10_000_000, floor_balance=0)
        assert result["bet_amount"] == 0
        assert any("p_yes" in str(e) for e in result["error"])


class TestRunBankroll:
    """Tests for bankroll / floor_balance interactions."""

    def test_bankroll_below_floor(self) -> None:
        """Bankroll <= floor_balance returns zero bet with vote still set."""
        result = run(
            bankroll=1_000_000, floor_balance=2_000_000, p_yes=0.7, bet_amount=500_000
        )
        assert result["bet_amount"] == 0
        assert result["vote"] == 0  # YES side still determined

    def test_bankroll_equal_to_floor(self) -> None:
        """Bankroll exactly equal to floor returns zero bet."""
        result = run(
            bankroll=1_000_000, floor_balance=1_000_000, p_yes=0.7, bet_amount=500_000
        )
        assert result["bet_amount"] == 0


class TestRunBetAmount:
    """Tests for bet amount configuration."""

    def test_returns_configured_amount(self) -> None:
        """Returns the configured bet_amount when within limits."""
        result = run(
            bankroll=10_000_000, floor_balance=0, p_yes=0.7, bet_amount=2_000_000
        )
        assert result["bet_amount"] == 2_000_000

    def test_no_bet_amount_configured(self) -> None:
        """No bet_amount and no min_bet returns zero."""
        result = run(bankroll=10_000_000, floor_balance=0, p_yes=0.7)
        assert result["bet_amount"] == 0

    def test_falls_back_to_min_bet(self) -> None:
        """Without bet_amount, falls back to min_bet."""
        result = run(bankroll=10_000_000, floor_balance=0, p_yes=0.7, min_bet=500_000)
        assert result["bet_amount"] == 500_000

    def test_capped_at_max_bet(self) -> None:
        """bet_amount capped at max_bet."""
        result = run(
            bankroll=10_000_000,
            floor_balance=0,
            p_yes=0.7,
            bet_amount=2_000_000,
            max_bet=500_000,
        )
        assert result["bet_amount"] == 500_000

    def test_capped_at_available_balance(self) -> None:
        """bet_amount capped at bankroll - floor_balance."""
        result = run(
            bankroll=2_000_000,
            floor_balance=1_700_000,
            p_yes=0.7,
            bet_amount=2_000_000,
        )
        assert result["bet_amount"] == 300_000

    def test_zero_bet_amount(self) -> None:
        """bet_amount=0 returns zero."""
        result = run(bankroll=10_000_000, floor_balance=0, p_yes=0.7, bet_amount=0)
        assert result["bet_amount"] == 0


class TestRunSideSelection:
    """Tests for vote / side selection."""

    def test_vote_yes_when_p_yes_higher(self) -> None:
        """p_yes > 0.5 → vote=0 (YES)."""
        result = run(
            bankroll=10_000_000, floor_balance=0, p_yes=0.7, bet_amount=1_000_000
        )
        assert result["vote"] == 0

    def test_vote_no_when_p_no_higher(self) -> None:
        """p_yes < 0.5 → vote=1 (NO)."""
        result = run(
            bankroll=10_000_000, floor_balance=0, p_yes=0.3, bet_amount=1_000_000
        )
        assert result["vote"] == 1

    def test_tie_returns_no_trade(self) -> None:
        """p_yes = 0.5 → tie, no bet."""
        result = run(
            bankroll=10_000_000, floor_balance=0, p_yes=0.5, bet_amount=1_000_000
        )
        assert result["bet_amount"] == 0
        assert result["vote"] is None


class TestRunReturnFormat:
    """Tests for return dict structure."""

    def test_successful_return_keys(self) -> None:
        """Successful bet has all expected keys."""
        result = run(
            bankroll=10_000_000, floor_balance=0, p_yes=0.7, bet_amount=1_000_000
        )
        assert "bet_amount" in result
        assert "vote" in result
        assert "info" in result
        assert "error" in result

    def test_error_return_keys(self) -> None:
        """Error result has bet_amount, vote, and error."""
        result = run()
        assert "bet_amount" in result
        assert "vote" in result
        assert "error" in result

    def test_unknown_kwargs_ignored(self) -> None:
        """Extra kwargs don't cause errors."""
        result = run(
            bankroll=10_000_000,
            floor_balance=0,
            p_yes=0.7,
            bet_amount=1_000_000,
            unknown_field="hello",
        )
        assert result["bet_amount"] == 1_000_000
