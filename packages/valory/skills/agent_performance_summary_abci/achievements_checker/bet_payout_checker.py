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
from logging import Logger, getLogger
from typing import Any, Dict, Optional

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

_default_logger = getLogger(__name__)


class BetPayoutChecker(AchievementsChecker):
    """Achievement checker for bets with payouts ROI above a threshold"""

    def __init__(
        self,
        achievement_type: str,
        roi_threshold: float = 2.0,
        title_template: str = "High ROI on bet!",
        description_template: str = "Agent closed a bet at {roi}\u00d7 ROI.",
        skip_settled_before_enabled: bool = False,
        require_remaining_shares: bool = False,
    ) -> None:
        """Initialize the achievement checker."""
        self._achievement_type = achievement_type
        self._roi_threshold = roi_threshold
        self._title_template = title_template
        self._description_template = description_template
        self._skip_settled_before_enabled = skip_settled_before_enabled
        self._require_remaining_shares = require_remaining_shares

    @property
    def achievement_type(self) -> str:
        """Returns a string representing the achievement type"""
        return self._achievement_type

    def update_achievements(self, achievements: Achievements, **kwargs: Any) -> bool:
        """Check if an achievement has been reached and populate `achievements`. Returns `True` if the achievements dictionary has been updated."""

        if "prediction_history" not in kwargs:
            raise ValueError("Missing 'prediction_history'")

        prediction_history: PredictionHistory = kwargs["prediction_history"]

        # A degraded read returns no history. Never persist a watermark-only
        # update in that case: it would replace the stored summary with defaults.
        if prediction_history is None:
            return False

        logger: Logger = kwargs.get("logger", _default_logger)
        achievements_updated = False
        eligible_since = 0
        if self._skip_settled_before_enabled:
            if achievements.eligible_since is None:
                if "now" not in kwargs:
                    raise ValueError("Missing 'now'")
                # Omen settled_at is the answer-posted time, not finalization
                # or redemption time. The agreed rollout cutoff also excludes
                # answers posted before enablement that finalize afterwards.
                achievements.eligible_since = int(kwargs["now"])
                achievements_updated = True
                logger.info(
                    f"{self.achievement_type}: recording wins settled at or after "
                    f"eligible_since={achievements.eligible_since}."
                )
            eligible_since = achievements.eligible_since

        for bet in prediction_history.items:
            # One malformed persisted item must not fail the round every cycle.
            try:
                achievement = self._new_achievement(
                    bet, achievements, eligible_since, logger
                )
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                bet_id = bet.get("id") if isinstance(bet, dict) else None
                logger.warning(
                    f"{self.achievement_type}: skipping malformed bet {bet_id!r}: {e!r}"
                )
                continue

            if achievement is None:
                continue

            achievements.items[achievement.achievement_id] = achievement
            achievements_updated = True

        return achievements_updated

    def _new_achievement(
        self,
        bet: Dict[str, Any],
        achievements: Achievements,
        eligible_since: int,
        logger: Logger,
    ) -> Optional[Achievement]:
        """Return the achievement a bet newly qualifies for, or `None`."""
        # Sell-aware: only fire on resolved-and-redeemed wins. The
        # `status == WON` gate intentionally excludes:
        #   - LOST: a fully-sold-at-loss bet has total_payout > 0
        #     (realized proceeds) but is not a prediction win.
        #   - INVALID: a market refund may technically exceed the ROI
        #     threshold, but the achievement copy ("Agent closed a bet at
        #     {roi}x ROI") celebrates prediction wins, not cancellations.
        if bet.get("status") != BetStatus.WON.value:
            return None
        if bet.get("settled_at") is None:
            return None

        bet_amount = bet.get("bet_amount", 0)
        total_payout = bet.get("total_payout", 0)

        if bet_amount <= 0:
            return None

        roi = total_payout / bet_amount

        if roi <= self._roi_threshold:
            return None

        achievement_id = self.generate_achievement_id(bet["id"])

        if achievement_id in achievements.items:
            return None

        roi_text = f"{roi:.1f}".rstrip("0").rstrip(".")

        # A sale-profit WON can acquire settled_at once any answer is
        # posted. Omen additionally requires FIFO shares still held; legacy
        # history without that marker waits for the next history refresh.
        if self._require_remaining_shares and not bet.get("has_remaining_shares"):
            logger.info(
                f"{self.achievement_type}: skipping bet {bet['id']} at {roi_text}x "
                f"ROI: has_remaining_shares={bet.get('has_remaining_shares')!r}."
            )
            return None

        settled_timestamp = int(
            datetime.fromisoformat(bet["settled_at"].replace("Z", "+00:00")).timestamp()
        )

        if settled_timestamp < eligible_since:
            logger.info(
                f"{self.achievement_type}: skipping bet {bet['id']} at {roi_text}x "
                f"ROI: settled at {settled_timestamp}, before "
                f"eligible_since={eligible_since}."
            )
            return None

        return Achievement(
            achievement_id=achievement_id,
            achievement_type=self.achievement_type,
            title=self._title_template.format(roi=roi_text),
            description=self._description_template.format(roi=roi_text),
            timestamp=settled_timestamp,
            data=bet,
        )
