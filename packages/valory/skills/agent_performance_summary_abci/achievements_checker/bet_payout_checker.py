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
from typing import Any

from packages.valory.skills.agent_performance_summary_abci.achievements_checker.base import (
    AchievementsChecker,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    BetStatus,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    Achievement,
    Achievements,
    PredictionHistory,
)


class BetPayoutChecker(AchievementsChecker):
    """Achievement checker for bets with payouts ROI above a threshold"""

    def __init__(
        self,
        achievement_type: str,
        roi_threshold: float = 2.0,
        title_template: str = "High ROI on bet!",
        description_template: str = "Agent closed a bet at {roi}\u00d7 ROI.",
        skip_settled_before_enabled: bool = False,
    ) -> None:
        """Initialize the achievement checker."""
        self._achievement_type = achievement_type
        self._roi_threshold = roi_threshold
        self._title_template = title_template
        self._description_template = description_template
        self._skip_settled_before_enabled = skip_settled_before_enabled

    @property
    def achievement_type(self) -> str:
        """Returns a string representing the achievement type"""
        return self._achievement_type

    def update_achievements(self, achievements: Achievements, **kwargs: Any) -> bool:
        """Check if an achievement has been reached and populate `achievements`. Returns `True` if the achievements dictionary has been updated."""

        if "prediction_history" not in kwargs:
            raise ValueError("Missing 'prediction_history'")

        prediction_history: PredictionHistory = kwargs["prediction_history"]

        achievements_updated = False
        if self._skip_settled_before_enabled and achievements.eligible_since is None:
            if "now" not in kwargs:
                raise ValueError("Missing 'now'")
            # First enabled run: wins settled before it are a backlog the
            # operator has long seen, so only later settlements qualify.
            achievements.eligible_since = int(kwargs["now"])
            achievements_updated = True

        if prediction_history is None:
            return achievements_updated

        for bet in prediction_history.items:
            # Sell-aware: only fire on resolved-and-redeemed wins. The
            # `status == WON` gate intentionally excludes:
            #   - LOST: a fully-sold-at-loss bet has total_payout > 0
            #     (realized proceeds) but is not a prediction win.
            #   - INVALID: a market refund may technically exceed the ROI
            #     threshold, but the achievement copy ("Agent closed a bet at
            #     {roi}x ROI") celebrates prediction wins, not cancellations.
            # The `settled_at is not None` gate excludes WON-via-PnL-sign-pre-
            # resolution (fully-sold-at-profit before the market resolved).
            if bet.get("status") != BetStatus.WON.value:
                continue
            if bet.get("settled_at") is None:
                continue

            bet_amount = bet.get("bet_amount", 0)
            total_payout = bet.get("total_payout", 0)

            if bet_amount <= 0:
                continue

            roi = total_payout / bet_amount

            if roi <= self._roi_threshold:
                continue

            settled_timestamp = int(
                datetime.fromisoformat(
                    bet["settled_at"].replace("Z", "+00:00")
                ).timestamp()
            )

            if (
                self._skip_settled_before_enabled
                and achievements.eligible_since is not None
                and settled_timestamp < achievements.eligible_since
            ):
                continue

            achievement_id = self.generate_achievement_id(bet["id"])

            if achievement_id in achievements.items:
                continue

            title = self._title_template.format(
                roi=f"{roi:.1f}".rstrip("0").rstrip("."),
            )
            description = self._description_template.format(
                roi=f"{roi:.1f}".rstrip("0").rstrip("."),
            )

            achievement = Achievement(
                achievement_id=achievement_id,
                achievement_type=self.achievement_type,
                title=title,
                description=description,
                timestamp=settled_timestamp,
                data=bet,
            )

            achievements.items[achievement_id] = achievement
            achievements_updated = True

        return achievements_updated
