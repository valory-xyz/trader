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

"""Achievement checker for bets with payouts ROI above a threshold"""


from datetime import datetime
from packages.valory.skills.agent_performance_summary_abci.achievements_checker.base import AchievementsChecker
from packages.valory.skills.agent_performance_summary_abci.models import Achievement, Achievements, PredictionHistory


class BetPayoutChecker(AchievementsChecker):
    """Achievement checker for bets with payouts ROI above a threshold"""

    def __init__(
        self,
        achievement_type: str,
        roi_threshold: float = 2.0,
    ) -> None:
        """Initialize the achievement checker."""
        self._achievement_type = achievement_type
        self._roi_threshold = roi_threshold

    def achievement_type(self) -> str:
        """Returns a string representing the achievement type"""
        return self._achievement_type

    def update_achievements(self, achievements: Achievements, **kwargs) -> None:
        """Check if an achievement has been reached and populate `achievements`. Returns `True` if the achievements dictionary has been updated."""

        if "prediction_history" not in kwargs:
            raise ValueError("Missing 'prediction_history'")

        prediction_history: PredictionHistory = kwargs["prediction_history"]

        if prediction_history is None:
            return

        achievements_updated = False
        for bet in prediction_history.items:
            bet_amount = bet.get("bet_amount", 0)
            net_profit = bet.get("net_profit", 0)

            if bet_amount <= 0:
                continue

            roi = net_profit / bet_amount

            if roi <= self._roi_threshold:
                continue

            achievement_id = self.generate_achievement_id(bet["id"])

            if achievement_id in achievements.items:
                continue

            achievement = Achievement(
                achievement_id=achievement_id,
                type=self.type,
                title="High ROI on bet!",
                description=f"My agent bet on \"{bet['market']['title']}\" won a {roi:.2f}% ROI.",
                timestamp=int(datetime.fromisoformat(bet["settled_at"].replace("Z", "+00:00")).timestamp()),
                data=bet,
            )

            achievements.items[achievement_id] = achievement
            achievements_updated = True

        return achievements_updated

