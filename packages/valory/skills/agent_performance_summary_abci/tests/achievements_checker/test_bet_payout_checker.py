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

"""This module contains tests for the BetPayoutChecker class."""

import pytest

from packages.valory.skills.agent_performance_summary_abci.achievements_checker.bet_payout_checker import (
    BetPayoutChecker,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    Achievements,
    PredictionHistory,
)


class TestBetPayoutCheckerInit:
    """Tests for BetPayoutChecker initialization."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default values."""
        checker = BetPayoutChecker(achievement_type="high_roi")
        assert checker.achievement_type == "high_roi"
        assert checker._roi_threshold == 2.0
        assert checker._title_template == "High ROI on bet!"
        assert checker._description_template == "Agent closed a bet at {roi}\u00d7 ROI."

    def test_init_with_custom_values(self) -> None:
        """Test initialization with custom values."""
        checker = BetPayoutChecker(
            achievement_type="custom_roi",
            roi_threshold=5.0,
            title_template="Custom Title {roi}x",
            description_template="Custom description at {roi}x ROI.",
        )
        assert checker.achievement_type == "custom_roi"
        assert checker._roi_threshold == 5.0
        assert checker._title_template == "Custom Title {roi}x"
        assert checker._description_template == "Custom description at {roi}x ROI."


class TestBetPayoutCheckerAchievementType:
    """Tests for BetPayoutChecker.achievement_type property."""

    def test_achievement_type_returns_configured_value(self) -> None:
        """Test that achievement_type returns the configured value."""
        checker = BetPayoutChecker(achievement_type="test_type")
        assert checker.achievement_type == "test_type"

    def test_achievement_type_different_values(self) -> None:
        """Test achievement_type with different configured values."""
        checker_a = BetPayoutChecker(achievement_type="type_a")
        checker_b = BetPayoutChecker(achievement_type="type_b")
        assert checker_a.achievement_type == "type_a"
        assert checker_b.achievement_type == "type_b"


class TestBetPayoutCheckerUpdateAchievements:
    """Tests for BetPayoutChecker.update_achievements."""

    def _make_checker(
        self,
        roi_threshold: float = 2.0,
        title_template: str = "High ROI: {roi}x",
        description_template: str = "Agent achieved {roi}x ROI.",
    ) -> BetPayoutChecker:
        """Create a BetPayoutChecker with default test parameters."""
        return BetPayoutChecker(
            achievement_type="bet_payout",
            roi_threshold=roi_threshold,
            title_template=title_template,
            description_template=description_template,
        )

    def _make_bet(
        self,
        bet_id: str = "bet_1",
        bet_amount: float = 10.0,
        total_payout: float = 30.0,
        settled_at: str = "2024-01-15T12:00:00Z",
    ) -> dict:
        """Create a bet dict for testing."""
        return {
            "id": bet_id,
            "bet_amount": bet_amount,
            "total_payout": total_payout,
            "settled_at": settled_at,
        }

    def test_missing_prediction_history_kwarg_raises_value_error(self) -> None:
        """Test that missing prediction_history kwarg raises ValueError."""
        checker = self._make_checker()
        achievements = Achievements()
        with pytest.raises(ValueError, match="Missing 'prediction_history'"):
            checker.update_achievements(achievements)

    def test_prediction_history_is_none_returns_false(self) -> None:
        """Test that prediction_history=None returns False."""
        checker = self._make_checker()
        achievements = Achievements()
        result = checker.update_achievements(
            achievements, prediction_history=None
        )
        assert result is False

    def test_empty_prediction_history_returns_false(self) -> None:
        """Test that an empty prediction history returns False."""
        checker = self._make_checker()
        achievements = Achievements()
        prediction_history = PredictionHistory(items=[])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is False

    def test_bet_amount_zero_skipped(self) -> None:
        """Test that bets with bet_amount=0 are skipped."""
        checker = self._make_checker()
        achievements = Achievements()
        bet = self._make_bet(bet_amount=0, total_payout=100.0)
        prediction_history = PredictionHistory(items=[bet])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is False
        assert len(achievements.items) == 0

    def test_bet_amount_negative_skipped(self) -> None:
        """Test that bets with negative bet_amount are skipped."""
        checker = self._make_checker()
        achievements = Achievements()
        bet = self._make_bet(bet_amount=-5.0, total_payout=100.0)
        prediction_history = PredictionHistory(items=[bet])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is False
        assert len(achievements.items) == 0

    def test_roi_below_threshold_skipped(self) -> None:
        """Test that bets with ROI below threshold are skipped."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        # ROI = 15/10 = 1.5, which is <= 2.0
        bet = self._make_bet(bet_amount=10.0, total_payout=15.0)
        prediction_history = PredictionHistory(items=[bet])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is False
        assert len(achievements.items) == 0

    def test_roi_equal_to_threshold_skipped(self) -> None:
        """Test that bets with ROI exactly equal to threshold are skipped."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        # ROI = 20/10 = 2.0, which is equal to threshold (not strictly greater)
        bet = self._make_bet(bet_amount=10.0, total_payout=20.0)
        prediction_history = PredictionHistory(items=[bet])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is False
        assert len(achievements.items) == 0

    def test_roi_above_threshold_creates_achievement(self) -> None:
        """Test that bets with ROI above threshold create an achievement."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        # ROI = 30/10 = 3.0, which is > 2.0
        bet = self._make_bet(
            bet_id="bet_high_roi",
            bet_amount=10.0,
            total_payout=30.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is True
        assert len(achievements.items) == 1

        # Verify the achievement properties
        achievement = list(achievements.items.values())[0]
        assert achievement.achievement_type == "bet_payout"
        assert achievement.data == bet

    def test_already_existing_achievement_skipped(self) -> None:
        """Test that already existing achievements are not duplicated."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        bet = self._make_bet(
            bet_id="bet_existing",
            bet_amount=10.0,
            total_payout=30.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])

        # First call should create the achievement
        result1 = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result1 is True
        assert len(achievements.items) == 1

        # Second call with same bet should not create a duplicate
        result2 = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result2 is False
        assert len(achievements.items) == 1

    def test_title_formatting_with_roi(self) -> None:
        """Test that the title template is formatted with the ROI value."""
        checker = self._make_checker(
            roi_threshold=2.0,
            title_template="ROI: {roi}x on bet!",
        )
        achievements = Achievements()
        # ROI = 30/10 = 3.0
        bet = self._make_bet(
            bet_id="bet_format",
            bet_amount=10.0,
            total_payout=30.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])
        checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        achievement = list(achievements.items.values())[0]
        assert achievement.title == "ROI: 3x on bet!"

    def test_description_formatting_with_roi(self) -> None:
        """Test that the description template is formatted with the ROI value."""
        checker = self._make_checker(
            roi_threshold=2.0,
            description_template="Agent closed at {roi}x.",
        )
        achievements = Achievements()
        # ROI = 30/10 = 3.0
        bet = self._make_bet(
            bet_id="bet_desc",
            bet_amount=10.0,
            total_payout=30.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])
        checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        achievement = list(achievements.items.values())[0]
        assert achievement.description == "Agent closed at 3x."

    def test_roi_formatting_strips_trailing_zeros(self) -> None:
        """Test that ROI formatting strips trailing zeros properly."""
        checker = self._make_checker(
            roi_threshold=2.0,
            title_template="{roi}x",
        )
        achievements = Achievements()
        # ROI = 25/10 = 2.5
        bet = self._make_bet(
            bet_id="bet_strip",
            bet_amount=10.0,
            total_payout=25.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])
        checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        achievement = list(achievements.items.values())[0]
        assert achievement.title == "2.5x"

    def test_multiple_bets_some_qualify(self) -> None:
        """Test processing multiple bets where some qualify and some do not."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        bets = [
            self._make_bet(
                bet_id="low_roi", bet_amount=10.0, total_payout=15.0
            ),  # ROI 1.5 - skip
            self._make_bet(
                bet_id="high_roi",
                bet_amount=10.0,
                total_payout=30.0,
                settled_at="2024-01-15T12:00:00Z",
            ),  # ROI 3.0 - qualify
            self._make_bet(
                bet_id="zero_amount", bet_amount=0, total_payout=100.0
            ),  # zero amount - skip
        ]
        prediction_history = PredictionHistory(items=bets)
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is True
        assert len(achievements.items) == 1

    def test_achievement_id_is_deterministic(self) -> None:
        """Test that the same bet produces the same achievement ID."""
        checker = self._make_checker(roi_threshold=2.0)

        achievements1 = Achievements()
        achievements2 = Achievements()
        bet = self._make_bet(
            bet_id="deterministic_bet",
            bet_amount=10.0,
            total_payout=30.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])

        checker.update_achievements(
            achievements1, prediction_history=prediction_history
        )
        checker.update_achievements(
            achievements2, prediction_history=prediction_history
        )

        id1 = list(achievements1.items.keys())[0]
        id2 = list(achievements2.items.keys())[0]
        assert id1 == id2

    def test_achievement_timestamp_from_settled_at(self) -> None:
        """Test that the achievement timestamp is derived from the bet's settled_at field."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        bet = self._make_bet(
            bet_id="ts_bet",
            bet_amount=10.0,
            total_payout=30.0,
            settled_at="2024-01-15T12:00:00Z",
        )
        prediction_history = PredictionHistory(items=[bet])
        checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        achievement = list(achievements.items.values())[0]
        # 2024-01-15T12:00:00Z in Unix timestamp
        assert achievement.timestamp == 1705320000

    def test_bet_missing_bet_amount_defaults_to_zero(self) -> None:
        """Test that a bet missing bet_amount defaults to 0 and is skipped."""
        checker = self._make_checker(roi_threshold=2.0)
        achievements = Achievements()
        bet = {"id": "no_amount", "total_payout": 30.0, "settled_at": "2024-01-15T12:00:00Z"}
        prediction_history = PredictionHistory(items=[bet])
        result = checker.update_achievements(
            achievements, prediction_history=prediction_history
        )
        assert result is False
        assert len(achievements.items) == 0
