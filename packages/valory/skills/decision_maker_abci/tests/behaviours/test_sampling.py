# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""Tests for SamplingBehaviour."""

import json
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.models import (
    AGENT_PERFORMANCE_SUMMARY_FILE,
)
from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    BOOK_CHECK_CANDIDATES,
    SamplingBehaviour,
    UNIX_DAY,
    UNIX_WEEK,
    WEEKDAYS,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus

NOW = 1700000000
COOLDOWN = 3600
LATEST_DECLINE_TS = 1700000000
EARLIER_DECLINE_TS = 1690000000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _return_gen(value):  # type: ignore[no-untyped-def]
    """Helper that creates a generator returning the given value."""
    yield  # type: ignore[no-untyped-def]
    return value


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a SamplingBehaviour with mocked dependencies."""
    behaviour = object.__new__(SamplingBehaviour)  # type: ignore[no-untyped-def]
    behaviour.should_rebet = False

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


def _goal_block(period_start: int, progress: int, target: int = 8) -> Dict[str, Any]:
    """Return a valid activity goal block."""
    return {
        "unit": "trades",
        "target": target,
        "progress": progress,
        "is_met": progress >= target,
        "period_start": period_start,
        "updated_at": period_start + 100,
        "last_met_at": None,
    }


def _write_goal_block(store_path: Path, block: Optional[Dict[str, Any]]) -> None:
    """Write a performance summary holding ``block`` as its activity goal."""
    summary = {} if block is None else {"activity_goal": block}
    (store_path / AGENT_PERFORMANCE_SUMMARY_FILE).write_text(json.dumps(summary))


def _make_mock_bet(  # type: ignore[no-untyped-def]
    bet_id="bet1",
    queue_status=QueueStatus.TO_PROCESS,  # type: ignore[no-untyped-def]
    n_bets=0,
    opening_timestamp=None,
    invested_amount=0,
    processed_timestamp=0,
    liquidity=100.0,
    outcome_prices=None,
    neg_risk=False,
    poly_tags=None,
):
    """Create a mock Bet object."""
    if opening_timestamp is None:
        opening_timestamp = int(time.time()) + 86400 * 7  # 7 days from now
    if outcome_prices is None:
        outcome_prices = [0.5, 0.5]
    if poly_tags is None:
        poly_tags = []

    bet = MagicMock(spec=Bet)
    bet.id = bet_id
    bet.queue_status = queue_status
    bet.n_bets = n_bets
    bet.openingTimestamp = opening_timestamp
    bet.invested_amount = invested_amount
    bet.processed_timestamp = processed_timestamp
    bet.scaledLiquidityMeasure = liquidity
    bet.outcomeTokenMarginalPrices = outcome_prices
    bet.neg_risk = neg_risk
    bet.poly_tags = poly_tags
    bet.ranked_at = 0
    bet.research_score = None
    bet.blacklist_forever = MagicMock()
    return bet


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSamplingConstants:
    """Tests for module-level constants."""

    def test_weekdays(self) -> None:
        """WEEKDAYS should be 7."""
        assert WEEKDAYS == 7

    def test_unix_day(self) -> None:
        """UNIX_DAY should be 86400."""
        assert UNIX_DAY == 60 * 60 * 24

    def test_unix_week(self) -> None:
        """UNIX_WEEK should be 7 * 86400."""
        assert UNIX_WEEK == WEEKDAYS * UNIX_DAY


class TestSamplingBehaviourInit:
    """Tests for SamplingBehaviour.__init__."""

    @patch(
        "packages.valory.skills.decision_maker_abci.behaviours.sampling.DecisionMakerBaseBehaviour.__init__",
        return_value=None,
    )
    @patch(
        "packages.valory.skills.decision_maker_abci.behaviours.sampling.QueryingBehaviour.__init__",
        return_value=None,
    )
    def test_init_sets_should_rebet(
        self, mock_querying_init: MagicMock, mock_dm_init: MagicMock
    ) -> None:
        """__init__ should set should_rebet to False."""
        behaviour = SamplingBehaviour.__new__(SamplingBehaviour)
        behaviour.__init__()  # type: ignore[misc]
        assert behaviour.should_rebet is False


class TestSamplingBehaviourSetup:
    """Tests for SamplingBehaviour.setup."""

    def test_setup_calls_read_bets(self) -> None:
        """Setup should call read_bets."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.setup()
        behaviour.read_bets.assert_called_once()


class TestSamplingBehaviourProperties:
    """Tests for SamplingBehaviour properties."""

    @pytest.mark.parametrize(
        ("target_met", "block", "expected"),
        [
            # staking side met, goal not met yet
            (True, _goal_block(1000, progress=3), False),
            # both met
            (True, _goal_block(1000, progress=8), True),
            # goal met, but in an earlier epoch
            (True, _goal_block(500, progress=8), False),
            # no block persisted yet
            (True, None, False),
            # goal met, staking side not met
            (False, _goal_block(1000, progress=8), False),
        ],
    )
    def test_kpi_is_met(
        self,
        tmp_path: Path,
        target_met: bool,
        block: Optional[Dict[str, Any]],
        expected: bool,
    ) -> None:
        """kpi_is_met needs the activity target and this epoch's activity goal."""
        _write_goal_block(tmp_path, block)
        behaviour = _make_behaviour()
        with (
            patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params,
        ):
            mock_sd.return_value = MagicMock(
                is_activity_target_met=target_met,
                is_staking_kpi_met=False,
                previous_checkpoint=1000,
            )
            mock_params.return_value = MagicMock(store_path=tmp_path)
            assert behaviour.kpi_is_met is expected

    def test_activity_goal_met_invalid_block(self, tmp_path: Path) -> None:
        """A block that contradicts its own counts reads as not met."""
        block = _goal_block(1000, progress=3)
        block["is_met"] = True
        _write_goal_block(tmp_path, block)
        behaviour = _make_behaviour()
        with (
            patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd,
            patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params,
        ):
            mock_sd.return_value = MagicMock(previous_checkpoint=1000)
            mock_params.return_value = MagicMock(store_path=tmp_path)
            assert behaviour.activity_goal_met is False

    def test_review_bets_for_selling(self) -> None:
        """review_bets_for_selling should return synchronized_data value."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(review_bets_for_selling=False)
            assert behaviour.review_bets_for_selling is False


class TestMultiBetsFallback:
    """Tests for _multi_bets_fallback_allowed."""

    def test_allowed_when_enabled_and_kpi_not_met(self) -> None:
        """Fallback should be allowed when enabled and KPI not met."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(enable_multi_bets_fallback=True)
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = False
                assert behaviour._multi_bets_fallback_allowed() is True

    def test_not_allowed_when_disabled(self) -> None:
        """Fallback should not be allowed when disabled."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(enable_multi_bets_fallback=False)
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = False
                assert behaviour._multi_bets_fallback_allowed() is False

    def test_not_allowed_when_kpi_met(self) -> None:
        """Fallback should not be allowed when KPI is met."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(enable_multi_bets_fallback=True)
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = True
                assert behaviour._multi_bets_fallback_allowed() is False


class TestProcessableBet:
    """Tests for processable_bet."""

    def test_expired_bet_not_processable(self) -> None:
        """An expired bet should not be processable."""
        behaviour = _make_behaviour()
        bet = _make_mock_bet()
        bet.queue_status = MagicMock()
        bet.queue_status.is_expired.return_value = True

        assert behaviour.processable_bet(bet, now=int(time.time())) is False

    def test_bet_outside_safe_range_gets_blacklisted(self) -> None:
        """A bet outside the safe voting range should be blacklisted."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(opening_timestamp=now + 10)  # Too close
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                sample_bets_closing_days=30,
                opening_margin=100,
                safe_voting_range=100,
            )
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = False
                with patch.object(
                    type(behaviour),
                    "review_bets_for_selling",
                    new_callable=PropertyMock,
                ) as mock_rbs:
                    mock_rbs.return_value = False
                    behaviour.processable_bet(bet, now=now)

        bet.blacklist_forever.assert_called_once()

    def test_no_bets_placed_and_selling_specific(self) -> None:
        """Bet with no bets placed and selling_specific should not be processable."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(n_bets=0, opening_timestamp=now + 86400 * 30)
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                sample_bets_closing_days=60,
                opening_margin=100,
                safe_voting_range=100,
            )
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = True
                with patch.object(
                    type(behaviour),
                    "review_bets_for_selling",
                    new_callable=PropertyMock,
                ) as mock_rbs:
                    mock_rbs.return_value = True
                    result = behaviour.processable_bet(bet, now=now)

        assert result is False

    def test_processable_with_bets_placed_and_selling_specific(self) -> None:
        """Bet with bets placed and selling_specific should be processable."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(
            n_bets=1,
            opening_timestamp=now + 86400 * 30,
            queue_status=QueueStatus.TO_PROCESS,
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                sample_bets_closing_days=60,
                opening_margin=100,
                safe_voting_range=100,
            )
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = True
                with patch.object(
                    type(behaviour),
                    "review_bets_for_selling",
                    new_callable=PropertyMock,
                ) as mock_rbs:
                    mock_rbs.return_value = True
                    result = behaviour.processable_bet(bet, now=now)

        assert result is True

    def test_processable_bet_within_ranges(self) -> None:
        """Bet within ranges and processable status should be processable."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(
            n_bets=0,
            opening_timestamp=now + 86400 * 5,
            queue_status=QueueStatus.TO_PROCESS,
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                sample_bets_closing_days=60,
                opening_margin=100,
                safe_voting_range=100,
            )
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = False
                with patch.object(
                    type(behaviour),
                    "review_bets_for_selling",
                    new_callable=PropertyMock,
                ) as mock_rbs:
                    mock_rbs.return_value = False
                    result = behaviour.processable_bet(bet, now=now)

        assert result is True


class TestClassifyProcessableBet:
    """Tests for _classify_processable_bet (observability mirror of processable_bet)."""

    @staticmethod
    def _patched(
        behaviour: SamplingBehaviour,
        bet: Bet,
        now: int,
        kpi_is_met: bool = False,
        review_bets_for_selling: bool = False,
        multi_bets_active: bool = False,
        sample_bets_closing_days: int = 60,
        opening_margin: int = 100,
        safe_voting_range: int = 100,
    ) -> str:
        """Run _classify_processable_bet with stubbed params/properties."""
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                sample_bets_closing_days=sample_bets_closing_days,
                opening_margin=opening_margin,
                safe_voting_range=safe_voting_range,
            )
            with patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi:
                mock_kpi.return_value = kpi_is_met
                with patch.object(
                    type(behaviour),
                    "review_bets_for_selling",
                    new_callable=PropertyMock,
                ) as mock_rbs:
                    mock_rbs.return_value = review_bets_for_selling
                    return behaviour._classify_processable_bet(
                        bet, now=now, multi_bets_active=multi_bets_active
                    )

    def test_classify_expired(self) -> None:
        """Expired bet should classify as 'expired'."""
        behaviour = _make_behaviour()
        bet = _make_mock_bet()
        bet.queue_status = MagicMock()
        bet.queue_status.is_expired.return_value = True

        assert self._patched(behaviour, bet, now=int(time.time())) == "expired"
        # observability mirror must NOT have side-effects
        bet.blacklist_forever.assert_not_called()

    def test_classify_wrong_mode_no_bets_selling_specific(self) -> None:
        """No bets placed under selling_specific should classify as 'wrong_mode'."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(n_bets=0, opening_timestamp=now + 86400 * 30)
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        assert (
            self._patched(
                behaviour,
                bet,
                now=now,
                kpi_is_met=True,
                review_bets_for_selling=True,
            )
            == "wrong_mode"
        )

    def test_classify_wrong_mode_when_mode_not_allowable(self) -> None:
        """bets_placed with neither multi-bets nor selling_specific should classify as 'wrong_mode'."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(n_bets=1, opening_timestamp=now + 86400 * 30)
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        assert (
            self._patched(
                behaviour,
                bet,
                now=now,
                multi_bets_active=False,
                kpi_is_met=False,
                review_bets_for_selling=False,
            )
            == "wrong_mode"
        )

    def test_classify_out_of_safe(self) -> None:
        """Bet too close to opening (inside safe voting range) classifies as 'out_of_safe'."""
        behaviour = _make_behaviour()
        now = int(time.time())
        # bet opens within (opening_margin + safe_voting_range) of now
        bet = _make_mock_bet(n_bets=0, opening_timestamp=now + 10)
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        assert (
            self._patched(
                behaviour, bet, now=now, opening_margin=100, safe_voting_range=100
            )
            == "out_of_safe"
        )

    def test_classify_out_of_open(self) -> None:
        """Bet within safe range but past sample_bets_closing_days classifies as 'out_of_open'."""
        behaviour = _make_behaviour()
        now = int(time.time())
        # safe range OK (far future opening), but past closing window
        # opening = now + 100 days; closing_days = 10; so within_opening = False
        bet = _make_mock_bet(n_bets=0, opening_timestamp=now + 86400 * 100)
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        assert (
            self._patched(
                behaviour,
                bet,
                now=now,
                sample_bets_closing_days=10,
                opening_margin=100,
                safe_voting_range=100,
            )
            == "out_of_open"
        )

    def test_classify_wrong_queue(self) -> None:
        """Bet in non-processable queue status (e.g. FRESH) classifies as 'wrong_queue'."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(n_bets=0, opening_timestamp=now + 86400 * 5)
        bet.queue_status = QueueStatus.FRESH
        bet.queue_status.is_expired = MagicMock(return_value=False)

        assert (
            self._patched(behaviour, bet, now=now, sample_bets_closing_days=60)
            == "wrong_queue"
        )

    def test_classify_processable(self) -> None:
        """Bet passing all checks classifies as 'processable'."""
        behaviour = _make_behaviour()
        now = int(time.time())
        bet = _make_mock_bet(n_bets=0, opening_timestamp=now + 86400 * 5)
        bet.queue_status = QueueStatus.TO_PROCESS
        bet.queue_status.is_expired = MagicMock(return_value=False)

        assert (
            self._patched(behaviour, bet, now=now, sample_bets_closing_days=60)
            == "processable"
        )


class TestDeclinedMarketCooldown:
    """Tests for the cooldown on markets declined without a position."""

    @staticmethod
    def _params(**overrides: Any) -> MagicMock:
        """Return params with wide sampling ranges and a 1 h cooldown."""
        values: Dict[str, Any] = dict(
            sample_bets_closing_days=60,
            opening_margin=100,
            safe_voting_range=100,
            declined_market_cooldown=COOLDOWN,
        )
        values.update(overrides)
        return MagicMock(**values)

    @pytest.mark.parametrize(
        "benchmarking, invested, declined_ago, cooldown, expected",
        (
            (False, 0, 60, COOLDOWN, True),
            (False, 0, COOLDOWN - 1, COOLDOWN, True),
            (False, 0, COOLDOWN, COOLDOWN, False),
            (False, 0, None, COOLDOWN, False),
            (False, 5, 60, COOLDOWN, False),
            (False, 0, 60, 0, False),
            (True, 0, 60, COOLDOWN, False),
            (False, 0, -60, COOLDOWN, False),
        ),
        ids=(
            "declined-a-minute-ago",
            "declined-just-inside",
            "cooldown-elapsed",
            "never-processed",
            "has-position",
            "cooldown-off",
            "benchmarking",
            "stamped-in-the-future",
        ),
    )
    def test_declined_recently(
        self,
        benchmarking: bool,
        invested: int,
        declined_ago: Optional[int],
        cooldown: int,
        expected: bool,
    ) -> None:
        """Only a no-position market processed less than the cooldown ago is cooling."""
        behaviour = _make_behaviour()
        behaviour.__dict__["_context"].benchmarking_mode.enabled = benchmarking
        bet = _make_mock_bet(
            invested_amount=invested,
            processed_timestamp=0 if declined_ago is None else NOW - declined_ago,
        )
        with patch.object(
            type(behaviour),
            "params",
            new_callable=PropertyMock,
            return_value=self._params(declined_market_cooldown=cooldown),
        ):
            assert behaviour._declined_recently(bet, NOW) is expected

    def test_cooling_bet_is_not_processable_and_classified(self) -> None:
        """A cooling bet is dropped by processable_bet and reported as cooling."""
        behaviour = _make_behaviour()
        behaviour.__dict__["_context"].benchmarking_mode.enabled = False
        bet = _make_mock_bet(
            queue_status=QueueStatus.REPROCESSED,
            opening_timestamp=NOW + 86400 * 5,
            processed_timestamp=NOW - 60,
        )
        with (
            patch.object(
                type(behaviour),
                "params",
                new_callable=PropertyMock,
                return_value=self._params(),
            ),
            patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi,
            patch.object(
                type(behaviour), "review_bets_for_selling", new_callable=PropertyMock
            ) as mock_rbs,
        ):
            mock_kpi.return_value = False
            mock_rbs.return_value = False
            assert behaviour.processable_bet(bet, now=NOW) is False
            assert (
                behaviour._classify_processable_bet(bet, NOW, multi_bets_active=False)
                == "cooling"
            )
            assert behaviour.processable_bet(bet, now=NOW + COOLDOWN) is True

    @pytest.mark.parametrize(
        "queue_status, opening_offset, expected",
        (
            (QueueStatus.FRESH, 86400 * 5, "wrong_queue"),
            (QueueStatus.REPROCESSED, 10, "out_of_safe"),
        ),
        ids=("wrong-queue-first", "out-of-safe-first"),
    )
    def test_cooling_has_lowest_precedence(
        self, queue_status: QueueStatus, opening_offset: int, expected: str
    ) -> None:
        """A cooling bet that also trips an earlier check reports the earlier class."""
        behaviour = _make_behaviour()
        behaviour.__dict__["_context"].benchmarking_mode.enabled = False
        bet = _make_mock_bet(
            queue_status=queue_status,
            opening_timestamp=NOW + opening_offset,
            processed_timestamp=NOW - 60,
        )
        with (
            patch.object(
                type(behaviour),
                "params",
                new_callable=PropertyMock,
                return_value=self._params(),
            ),
            patch.object(
                type(behaviour), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi,
            patch.object(
                type(behaviour), "review_bets_for_selling", new_callable=PropertyMock
            ) as mock_rbs,
        ):
            mock_kpi.return_value = False
            mock_rbs.return_value = False
            assert (
                behaviour._classify_processable_bet(bet, NOW, multi_bets_active=False)
                == expected
            )

    def test_small_pool_waits_out_the_cooldown(self) -> None:
        """Declining all of a 3-market pool leaves nothing to sample until the cooldown ends."""
        sampler = _make_behaviour()
        sampler.__dict__["_context"].benchmarking_mode.enabled = False
        bets = [
            Bet(
                id=f"m{i}",
                market="omen",
                title=f"market {i}",
                collateralToken="0x0",
                creator="0x0",
                fee=0,
                openingTimestamp=NOW + 86400 * 5,
                outcomeSlotCount=2,
                outcomeTokenAmounts=[10, 10],
                outcomeTokenMarginalPrices=[0.5, 0.5],
                outcomes=["Yes", "No"],
                scaledLiquidityMeasure=liquidity,
                queue_status=QueueStatus.REPROCESSED,
            )
            for i, liquidity in enumerate((900.0, 500.0, 300.0))
        ]
        sampler.bets = bets

        sampled: List[Optional[str]] = []
        with (
            patch.object(
                type(sampler),
                "params",
                new_callable=PropertyMock,
                return_value=self._params(),
            ),
            patch.object(
                type(sampler), "kpi_is_met", new_callable=PropertyMock
            ) as mock_kpi,
            patch.object(
                type(sampler), "review_bets_for_selling", new_callable=PropertyMock
            ) as mock_rbs,
        ):
            mock_kpi.return_value = False
            mock_rbs.return_value = False
            for now in (NOW, NOW + 96, NOW + 192, NOW + 288, NOW + COOLDOWN):
                available = [b for b in bets if sampler.processable_bet(b, now=now)]
                if not available:
                    sampled.append(None)
                    continue
                bet = bets[sampler._sampled_bet_idx(available)]
                sampled.append(bet.id)
                bet.processed_timestamp = now

        assert sampled == ["m0", "m1", "m2", None, "m0"]


class TestSortByPriorityLogic:
    """Tests for _sort_by_priority_logic."""

    def test_sort_by_invested_amount(self) -> None:
        """Bets should be sorted by invested_amount (descending)."""
        bet1 = _make_mock_bet(bet_id="a", invested_amount=100)
        bet2 = _make_mock_bet(bet_id="b", invested_amount=200)
        bet3 = _make_mock_bet(bet_id="c", invested_amount=50)

        sorted_bets = SamplingBehaviour._sort_by_priority_logic([bet1, bet2, bet3])
        assert sorted_bets[0].id == "b"
        assert sorted_bets[1].id == "a"
        assert sorted_bets[2].id == "c"


class TestGetBetsQueueWise:
    """Tests for _get_bets_queue_wise."""

    def test_splits_by_status(self) -> None:
        """Should correctly split bets into queue status groups."""
        bet1 = _make_mock_bet(queue_status=QueueStatus.TO_PROCESS)
        bet2 = _make_mock_bet(queue_status=QueueStatus.PROCESSED)
        bet3 = _make_mock_bet(queue_status=QueueStatus.REPROCESSED)

        to_process, processed, reprocessed = SamplingBehaviour._get_bets_queue_wise(
            [bet1, bet2, bet3]
        )
        assert len(to_process) == 1
        assert len(processed) == 1
        assert len(reprocessed) == 1

    def test_empty_lists_for_missing_statuses(self) -> None:
        """Should return empty lists for missing statuses."""
        bet1 = _make_mock_bet(queue_status=QueueStatus.TO_PROCESS)

        to_process, processed, reprocessed = SamplingBehaviour._get_bets_queue_wise(
            [bet1]
        )
        assert len(to_process) == 1
        assert len(processed) == 0
        assert len(reprocessed) == 0


class TestSampledBetIdx:
    """Tests for _sampled_bet_idx."""

    def test_returns_index_of_best_to_process_bet(self) -> None:
        """_sampled_bet_idx should return the index of the highest priority bet."""
        behaviour = _make_behaviour()
        bet1 = _make_mock_bet(
            bet_id="a",
            queue_status=QueueStatus.TO_PROCESS,
            invested_amount=100,
            liquidity=50.0,
        )
        bet2 = _make_mock_bet(
            bet_id="b",
            queue_status=QueueStatus.TO_PROCESS,
            invested_amount=200,
            liquidity=100.0,
        )
        behaviour.bets = [bet1, bet2]

        idx = behaviour._sampled_bet_idx([bet1, bet2])
        assert idx == 1  # bet2 has higher invested_amount

    def test_returns_index_from_processed_when_no_to_process(self) -> None:
        """Should pick from PROCESSED queue when TO_PROCESS is empty."""
        behaviour = _make_behaviour()
        bet1 = _make_mock_bet(
            bet_id="a",
            queue_status=QueueStatus.PROCESSED,
            invested_amount=100,
        )
        behaviour.bets = [bet1]

        idx = behaviour._sampled_bet_idx([bet1])
        assert idx == 0

    def test_returns_index_from_reprocessed_when_others_empty(self) -> None:
        """Should pick from REPROCESSED queue when TO_PROCESS and PROCESSED are empty."""
        behaviour = _make_behaviour()
        bet1 = _make_mock_bet(
            bet_id="a",
            queue_status=QueueStatus.REPROCESSED,
            invested_amount=100,
        )
        behaviour.bets = [bet1]

        idx = behaviour._sampled_bet_idx([bet1])
        assert idx == 0

    @pytest.mark.parametrize(
        "liquid_declined_at, other_declined_at",
        ((LATEST_DECLINE_TS, 0), (LATEST_DECLINE_TS, EARLIER_DECLINE_TS)),
        ids=("other-never-declined", "other-declined-earlier"),
    )
    def test_recently_declined_reprocessed_bet_is_not_sampled_next(
        self, liquid_declined_at: int, other_declined_at: int
    ) -> None:
        """Of two REPROCESSED bets, the one declined most recently goes last."""
        behaviour = _make_behaviour()
        liquid = _make_mock_bet(
            bet_id="liquid",
            queue_status=QueueStatus.REPROCESSED,
            processed_timestamp=liquid_declined_at,
            liquidity=1000.0,
        )
        other = _make_mock_bet(
            bet_id="other",
            queue_status=QueueStatus.REPROCESSED,
            processed_timestamp=other_declined_at,
            liquidity=10.0,
        )
        behaviour.bets = [liquid, other]

        idx = behaviour._sampled_bet_idx([liquid, other])
        assert behaviour.bets[idx].id == "other"


class TestSamplingBenchmarkingBet:
    """Tests for _sampling_benchmarking_bet."""

    def test_returns_none_when_mech_calls_exhausted(self) -> None:
        """Should return None when mech calls are at the limit."""
        behaviour = _make_behaviour()
        bet1 = _make_mock_bet(queue_status=QueueStatus.TO_PROCESS)
        behaviour.bets = [bet1]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.benchmarking_mech_calls = 5
            mock_ss.return_value = ss
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                bm = MagicMock()
                bm.nr_mech_calls = 5
                mock_bm.return_value = bm

                result = behaviour._sampling_benchmarking_bet([bet1])

        assert result is None

    def test_returns_index_when_mech_calls_remaining(self) -> None:
        """Should return bet index when mech calls have not been exhausted."""
        behaviour = _make_behaviour()
        bet1 = _make_mock_bet(
            bet_id="a",
            queue_status=QueueStatus.TO_PROCESS,
            invested_amount=100,
        )
        behaviour.bets = [bet1]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.benchmarking_mech_calls = 2
            mock_ss.return_value = ss
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                bm = MagicMock()
                bm.nr_mech_calls = 5
                mock_bm.return_value = bm

                result = behaviour._sampling_benchmarking_bet([bet1])

        assert result == 0


class TestSample:
    """Tests for _sample."""

    def _setup_behaviour_for_sample(  # type: ignore[no-untyped-def]
        self,
        bets=None,
        benchmarking_enabled=False,
        use_multi_bets_mode=False,
        enable_multi_bets_fallback=False,
        kpi_is_met=False,
        is_outcome_side_threshold_filter_enabled=False,
        outcome_side_threshold_filter_threshold=0.95,
        exclude_neg_risk_markets=False,
        is_running_on_polymarket=False,
        disabled_polymarket_tags=None,
        declined_market_cooldown=COOLDOWN,
    ):
        """Create a behaviour for _sample testing."""
        behaviour = _make_behaviour()
        if bets is None:
            bets = []
        behaviour.bets = bets

        params = MagicMock()
        params.use_multi_bets_mode = use_multi_bets_mode
        params.enable_multi_bets_fallback = enable_multi_bets_fallback
        params.sample_bets_closing_days = 60
        params.opening_margin = 100
        params.safe_voting_range = 100
        params.declined_market_cooldown = declined_market_cooldown
        params.is_outcome_side_threshold_filter_enabled = (
            is_outcome_side_threshold_filter_enabled
        )
        params.outcome_side_threshold_filter_threshold = (
            outcome_side_threshold_filter_threshold
        )
        params.exclude_neg_risk_markets = exclude_neg_risk_markets
        params.is_running_on_polymarket = is_running_on_polymarket
        params.disabled_polymarket_tags = disabled_polymarket_tags or []

        benchmarking_mode = MagicMock()
        benchmarking_mode.enabled = benchmarking_enabled

        shared_state = MagicMock()
        shared_state.liquidity_cache = {}

        return behaviour, params, benchmarking_mode, shared_state

    def test_no_bets_available_returns_none(self) -> None:
        """Should return None when no bets are available."""
        behaviour, params, bm, ss = self._setup_behaviour_for_sample(bets=[])

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=int(time.time()),
                ):
                    with patch.object(
                        type(behaviour),
                        "kpi_is_met",
                        new_callable=PropertyMock,
                        return_value=False,
                    ):
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            result = behaviour._sample()

        assert result is None

    def test_sample_returns_valid_index(self) -> None:
        """Should return the index of the sampled bet."""
        now = int(time.time())
        bet = _make_mock_bet(
            bet_id="a",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(bets=[bet])

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result == 0
        # No fallback fired here, so the top filter line must report
        # fallback_activated as False, only the strict breakdown line should
        # be emitted, and no fallback breakdown line should appear.
        log_calls = [str(c) for c in behaviour.context.logger.info.call_args_list]
        assert any(
            "filter=processable_bet " in call and "fallback_activated=False" in call
            for call in log_calls
        )
        assert any(
            "filter=processable_bet.breakdown.strict" in call for call in log_calls
        )
        assert not any(
            "filter=processable_bet.breakdown.fallback" in call for call in log_calls
        )

    def test_sample_skips_zero_liquidity(self) -> None:
        """Should skip bets with zero liquidity."""
        now = int(time.time())
        bet_zero = _make_mock_bet(
            bet_id="zero_liq",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=0,
        )
        bet_zero.queue_status.is_expired = MagicMock(return_value=False)
        bet_ok = _make_mock_bet(
            bet_id="ok",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
        )
        bet_ok.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_zero, bet_ok]
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result == 1

    def test_sample_all_zero_liquidity_returns_none(self) -> None:
        """Should return None when all bets have zero liquidity."""
        now = int(time.time())
        bet = _make_mock_bet(
            bet_id="zero",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=0,
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(bets=[bet])

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result is None

    def test_sample_outcome_side_threshold_filter(self) -> None:
        """Should skip bets that exceed outcome side threshold."""
        now = int(time.time())
        # Bet with a side exceeding threshold
        bet_skewed = _make_mock_bet(
            bet_id="skewed",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            outcome_prices=[0.99, 0.01],
        )
        bet_skewed.queue_status.is_expired = MagicMock(return_value=False)

        bet_ok = _make_mock_bet(
            bet_id="ok",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=80.0,
            outcome_prices=[0.5, 0.5],
        )
        bet_ok.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_skewed, bet_ok],
            is_outcome_side_threshold_filter_enabled=True,
            outcome_side_threshold_filter_threshold=0.95,
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result == 1

    def test_sample_exclude_neg_risk_skips_neg_risk_bet(self) -> None:
        """Should skip negRisk bets when exclude_neg_risk_markets is enabled."""
        now = int(time.time())
        bet_neg = _make_mock_bet(
            bet_id="neg",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            neg_risk=True,
        )
        bet_neg.queue_status.is_expired = MagicMock(return_value=False)

        bet_ok = _make_mock_bet(
            bet_id="ok",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=80.0,
            neg_risk=False,
        )
        bet_ok.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_neg, bet_ok],
            exclude_neg_risk_markets=True,
            is_running_on_polymarket=True,
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result == 1

    def test_sample_neg_risk_bet_passes_when_filter_disabled(self) -> None:
        """Should not skip negRisk bets when exclude_neg_risk_markets is disabled."""
        now = int(time.time())
        bet_neg = _make_mock_bet(
            bet_id="neg",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            neg_risk=True,
        )
        bet_neg.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_neg],
            exclude_neg_risk_markets=False,
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result == 0

    def test_sample_exclude_neg_risk_all_neg_risk_returns_none(self) -> None:
        """Should return None when all bets are negRisk and filter is enabled."""
        now = int(time.time())
        bet1 = _make_mock_bet(
            bet_id="neg1",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            neg_risk=True,
        )
        bet1.queue_status.is_expired = MagicMock(return_value=False)

        bet2 = _make_mock_bet(
            bet_id="neg2",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=80.0,
            neg_risk=True,
        )
        bet2.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet1, bet2],
            exclude_neg_risk_markets=True,
            is_running_on_polymarket=True,
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result is None

    @pytest.mark.parametrize(
        "fallback_enabled, zero_liquidity_left, expected_warning",
        (
            (False, False, "There were no unprocessed bets"),
            (True, False, "There were no unprocessed bets"),
            (False, True, "No valid bets found after liquidity validation"),
        ),
        ids=("fallback-off", "fallback-on", "zero-liquidity-left"),
    )
    def test_sample_all_cooling_waits(
        self, fallback_enabled: bool, zero_liquidity_left: bool, expected_warning: str
    ) -> None:
        """With every unheld market cooling, _sample returns None, even with the fallback on."""
        cooling = [
            Bet(
                id=f"m{i}",
                market="omen",
                title=f"market {i}",
                collateralToken="0x0",
                creator="0x0",
                fee=0,
                openingTimestamp=NOW + 86400 * 5,
                outcomeSlotCount=2,
                outcomeTokenAmounts=[10, 10],
                outcomeTokenMarginalPrices=[0.5, 0.5],
                outcomes=["Yes", "No"],
                scaledLiquidityMeasure=100.0,
                processed_timestamp=NOW - 60,
                queue_status=QueueStatus.REPROCESSED,
            )
            for i in range(3)
        ]
        held = _make_mock_bet(
            bet_id="held",
            queue_status=QueueStatus.REPROCESSED,
            n_bets=1,
            invested_amount=5,
            opening_timestamp=NOW + 86400 * 5,
        )
        dry = replace(cooling[0], id="dry", processed_timestamp=0)
        dry.scaledLiquidityMeasure = 0.0  # drained after discovery
        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[*cooling, dry if zero_liquidity_left else held],
            enable_multi_bets_fallback=fallback_enabled,
        )

        with (
            patch.object(
                type(behaviour),
                "params",
                new_callable=PropertyMock,
                return_value=params,
            ),
            patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ),
            patch.object(
                type(behaviour),
                "synced_timestamp",
                new_callable=PropertyMock,
                return_value=NOW,
            ),
            patch.object(
                type(behaviour),
                "shared_state",
                new_callable=PropertyMock,
                return_value=ss,
            ),
            patch.object(
                type(behaviour),
                "kpi_is_met",
                new_callable=PropertyMock,
                return_value=False,
            ),
            patch.object(
                type(behaviour),
                "review_bets_for_selling",
                new_callable=PropertyMock,
                return_value=False,
            ),
        ):
            result = behaviour._sample()

        assert result is None
        logger = behaviour.context.logger
        info_calls = [str(c) for c in logger.info.call_args_list]
        assert any(
            "breakdown.strict" in call and "cooling=3 " in call for call in info_calls
        )
        assert not any("fallback_activated=True" in call for call in info_calls)
        warning = str(logger.warning.call_args)
        assert expected_warning in warning
        assert "3 markets are cooling down for 3600s" in warning

    def test_sample_multi_bets_fallback(self) -> None:
        """Should use multi-bet fallback when no bets in single-bet mode."""
        now = int(time.time())
        # Bet with existing bets (n_bets > 0), which would be excluded in single mode
        # Use MagicMock for queue_status to avoid modifying enum instances
        qs = MagicMock()
        qs.is_expired.return_value = False
        qs.__eq__ = lambda self, other: other == QueueStatus.TO_PROCESS  # type: ignore[assignment, method-assign, misc]
        qs.__hash__ = lambda self: hash(QueueStatus.TO_PROCESS)  # type: ignore[assignment, method-assign, misc]
        # type: ignore[assignment, method-assign, misc]
        bet = _make_mock_bet(  # type: ignore[assignment, method-assign, misc]
            bet_id="multi",
            n_bets=1,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
        )
        bet.queue_status = qs

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet],
            use_multi_bets_mode=False,
            enable_multi_bets_fallback=True,
            kpi_is_met=False,
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result == 0
        # When fallback fires, top filter line must carry
        # fallback_activated=True, and both .breakdown.strict and
        # .breakdown.fallback must be emitted so operators can reconcile
        # the strict-mode and post-fallback views.
        log_calls = [str(c) for c in behaviour.context.logger.info.call_args_list]
        assert any(
            "filter=processable_bet " in call and "fallback_activated=True" in call
            for call in log_calls
        )
        assert any(
            "filter=processable_bet.breakdown.strict" in call for call in log_calls
        )
        assert any(
            "filter=processable_bet.breakdown.fallback" in call for call in log_calls
        )

    def test_sample_multi_bets_fallback_no_bets_found(self) -> None:
        """Should return None when fallback finds no bets either."""
        now = int(time.time())
        # Bet that fails both single and multi mode (e.g. outside safe range)
        bet = _make_mock_bet(
            bet_id="expired_like",
            n_bets=1,
            opening_timestamp=now + 50,  # within opening but not within safe range
            liquidity=100.0,
        )
        # Use a MagicMock for queue_status
        qs = MagicMock()
        qs.is_expired.return_value = False
        qs.__eq__ = lambda self, other: other == QueueStatus.TO_PROCESS  # type: ignore[assignment, method-assign, misc]
        qs.__hash__ = lambda self: hash(QueueStatus.TO_PROCESS)  # type: ignore[assignment, method-assign, misc]
        bet.queue_status = qs  # type: ignore[assignment, method-assign, misc]
        # type: ignore[assignment, method-assign, misc]
        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet],
            use_multi_bets_mode=False,
            enable_multi_bets_fallback=True,
            kpi_is_met=False,
        )
        # Make opening_margin + safe_voting_range large so bet is outside safe range
        params.opening_margin = 5000
        params.safe_voting_range = 5000

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        assert result is None

    def test_sample_benchmarking_mode(self) -> None:
        """Should use benchmarking mode to simulate timestamps."""
        now = int(time.time())
        # Need two bets so that _sampling_benchmarking_bet returns index 1 (truthy)
        # because _sample checks `if not idx:` which is True for idx=0
        bet_dummy = _make_mock_bet(
            bet_id="dummy",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=50.0,
        )
        bet_dummy.queue_status.is_expired = MagicMock(return_value=False)
        bet = _make_mock_bet(
            bet_id="bench",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            invested_amount=200,
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_dummy, bet], benchmarking_enabled=True
        )
        bm.enabled = True
        ss.get_simulated_now_timestamp = MagicMock(return_value=now)
        ss.benchmarking_mech_calls = 0

        bm.nr_mech_calls = 10

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "shared_state",
                    new_callable=PropertyMock,
                    return_value=ss,
                ):
                    with patch.object(
                        type(behaviour),
                        "kpi_is_met",
                        new_callable=PropertyMock,
                        return_value=False,
                    ):
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            result = behaviour._sample()

        assert result == 1

    def test_sample_benchmarking_mech_calls_exhausted(self) -> None:
        """Should return None when benchmarking mech calls are exhausted."""
        now = int(time.time())
        bet = _make_mock_bet(
            bet_id="bench",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet], benchmarking_enabled=True
        )
        bm.enabled = True
        ss.get_simulated_now_timestamp = MagicMock(return_value=now)
        ss.benchmarking_mech_calls = 5
        bm.nr_mech_calls = 5

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "shared_state",
                    new_callable=PropertyMock,
                    return_value=ss,
                ):
                    with patch.object(
                        type(behaviour),
                        "kpi_is_met",
                        new_callable=PropertyMock,
                        return_value=False,
                    ):
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            result = behaviour._sample()

        assert result is None

    def test_sample_skips_bet_with_disabled_tag(self) -> None:
        """A bet whose poly_tags intersect disabled_polymarket_tags is skipped."""
        now = int(time.time())
        bet_banned = _make_mock_bet(
            bet_id="banned",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            poly_tags=["politics", "hide-from-new"],
        )
        bet_banned.queue_status.is_expired = MagicMock(return_value=False)

        bet_ok = _make_mock_bet(
            bet_id="ok",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=80.0,
            poly_tags=["politics"],
        )
        bet_ok.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_banned, bet_ok],
            disabled_polymarket_tags=["hide-from-new"],
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        # Banned bet at index 0 must be skipped; the ok bet at index 1 is returned.
        assert result == 1

    def test_sample_skips_bet_case_insensitive(self) -> None:
        """Mixed-case tag on the bet matches a lowercase disabled slug."""
        now = int(time.time())
        bet_banned = _make_mock_bet(
            bet_id="banned",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            poly_tags=["Hide-From-New", "Politics"],
        )
        bet_banned.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_banned],
            disabled_polymarket_tags=["hide-from-new"],
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        # Only bet is banned → no valid sample.
        assert result is None

    def test_sample_empty_disabled_tags_allows_all(self) -> None:
        """With no disabled tags configured, no bet is filtered on tag grounds."""
        now = int(time.time())
        bet = _make_mock_bet(
            bet_id="a",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            poly_tags=["hide-from-new"],
        )
        bet.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet],
            disabled_polymarket_tags=[],
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        # Empty disable list → tag filter is a no-op; the bet is returned.
        assert result == 0

    def test_sample_orphan_legacy_bet_with_refreshed_tags_skipped(self) -> None:
        """Regression guard for the orphan legacy-bet case.

        Simulates the post-refresh state: a legacy bet that started with
        poly_tags=[] in multi_bets.json but got its tags refreshed via
        update_market_info during market_manager's _process_chunk. Together
        with test_update_market_info_copies_poly_tags in test_bets.py this
        proves the orphan-bet leak is closed end-to-end — the blacklist step
        is unnecessary because sampling catches it at read time.
        """
        now = int(time.time())
        # Post-refresh state — poly_tags populated by update_market_info.
        legacy_bet_refreshed = _make_mock_bet(
            bet_id="legacy",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            poly_tags=["hide-from-new"],
        )
        legacy_bet_refreshed.queue_status.is_expired = MagicMock(return_value=False)

        bet_ok = _make_mock_bet(
            bet_id="ok",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=80.0,
            poly_tags=[],
        )
        bet_ok.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[legacy_bet_refreshed, bet_ok],
            disabled_polymarket_tags=["hide-from-new"],
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        # The refreshed legacy bet (index 0) is skipped; the untagged ok bet
        # (index 1) is returned.
        assert result == 1

    def test_sample_strips_whitespace_around_tags(self) -> None:
        """Tags with leading/trailing whitespace still match after strip()+lower().

        Guards against silent bypass if Polymarket ever returns a tag like
        "  hide-from-new  " or if an operator pastes a disabled slug with
        trailing whitespace into the YAML.
        """
        now = int(time.time())
        bet_banned = _make_mock_bet(
            bet_id="banned",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=100.0,
            poly_tags=["  Hide-From-New  "],  # padded AND mixed case
        )
        bet_banned.queue_status.is_expired = MagicMock(return_value=False)

        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=[bet_banned],
            disabled_polymarket_tags=["hide-from-new"],
        )

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        # Padding and case both normalized away → bet is skipped.
        assert result is None

    def test_sample_prefilters_banned_bets_before_loop(self) -> None:
        """Banned bets are dropped from available_bets before the loop starts.

        Dropping them before the while-loop avoids re-sorting the candidate
        pool each time a banned bet is skipped.

        Discriminating assertion: wrap `_sampled_bet_idx` and assert it is
        called once (the pre-filter reduced 5 banned + 1 ok to [bet_ok],
        so one sort call returns index immediately). If the filter still
        lived inside the loop, `_sampled_bet_idx` would be called 6 times —
        once per banned bet + once for the final ok pick.
        """
        now = int(time.time())
        banned_bets = [
            _make_mock_bet(
                bet_id=f"banned{i}",
                queue_status=QueueStatus.TO_PROCESS,
                opening_timestamp=now + 86400 * 5,
                liquidity=100.0,
                poly_tags=["hide-from-new"],
            )
            for i in range(5)
        ]
        for b in banned_bets:
            b.queue_status.is_expired = MagicMock(return_value=False)

        bet_ok = _make_mock_bet(
            bet_id="ok",
            queue_status=QueueStatus.TO_PROCESS,
            opening_timestamp=now + 86400 * 5,
            liquidity=80.0,
            poly_tags=["politics"],
        )
        bet_ok.queue_status.is_expired = MagicMock(return_value=False)

        all_bets = banned_bets + [bet_ok]
        behaviour, params, bm, ss = self._setup_behaviour_for_sample(
            bets=all_bets,
            disabled_polymarket_tags=["hide-from-new"],
        )

        # Wrap _sampled_bet_idx so we can count how many times it ran.
        real_sampler = behaviour._sampled_bet_idx
        call_counter = MagicMock(side_effect=real_sampler)
        behaviour._sampled_bet_idx = call_counter  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock, return_value=params
        ):
            with patch.object(
                type(behaviour),
                "benchmarking_mode",
                new_callable=PropertyMock,
                return_value=bm,
            ):
                with patch.object(
                    type(behaviour),
                    "synced_timestamp",
                    new_callable=PropertyMock,
                    return_value=now,
                ):
                    with patch.object(
                        type(behaviour),
                        "shared_state",
                        new_callable=PropertyMock,
                        return_value=ss,
                    ):
                        with patch.object(
                            type(behaviour),
                            "kpi_is_met",
                            new_callable=PropertyMock,
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),
                                "review_bets_for_selling",
                                new_callable=PropertyMock,
                                return_value=False,
                            ):
                                result = behaviour._sample()

        # bet_ok is at index 5 in self.bets (5 banned bets precede it).
        assert result == 5
        # Pre-filter collapsed candidates to [bet_ok] → single sort call.
        assert call_counter.call_count == 1


class TestBenchmarkingIncDay:
    """Tests for _benchmarking_inc_day."""

    def test_returns_tuple(self) -> None:
        """_benchmarking_inc_day should return (benchmarking_finished, day_increased)."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.check_benchmarking_finished.return_value = False
            mock_ss.return_value = ss

            finished, day_increased = behaviour._benchmarking_inc_day()

        assert finished is False
        assert day_increased is True
        ss.increase_one_day_simulation.assert_called_once()

    def test_finished_true(self) -> None:
        """_benchmarking_inc_day should return True when benchmarking is finished."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.check_benchmarking_finished.return_value = True
            mock_ss.return_value = ss

            finished, day_increased = behaviour._benchmarking_inc_day()

        assert finished is True
        assert day_increased is True


class TestAsyncAct:
    """Tests for async_act."""

    def test_async_act_with_valid_sample(self) -> None:
        """async_act should create a payload with bets_hash when a bet is sampled."""
        behaviour = _make_behaviour()
        behaviour.bets = []
        behaviour.context.params.is_running_on_polymarket = False

        benchmark_ctx = MagicMock()
        behaviour.__dict__["_context"].benchmark_tool.measure.return_value = (
            benchmark_ctx
        )
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        bm = MagicMock()
        bm.enabled = False

        with patch.object(behaviour, "_sample", return_value=0):
            with patch.object(behaviour, "store_bets"):
                with patch.object(
                    behaviour, "hash_stored_bets", return_value="hash123"
                ):
                    with patch.object(
                        type(behaviour),
                        "benchmarking_mode",
                        new_callable=PropertyMock,
                        return_value=bm,
                    ):
                        with patch.object(
                            behaviour,
                            "finish_behaviour",
                            side_effect=lambda p: iter([None]),
                        ) as mock_finish:
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        mock_finish.assert_called_once()
        payload = mock_finish.call_args[0][0]
        assert isinstance(payload, SamplingPayload)
        assert payload.index == 0

    def test_async_act_with_no_sample(self) -> None:
        """async_act should create a payload with None bets_hash when no bet is sampled."""
        behaviour = _make_behaviour()
        behaviour.bets = []

        benchmark_ctx = MagicMock()
        behaviour.__dict__["_context"].benchmark_tool.measure.return_value = (
            benchmark_ctx
        )
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        bm = MagicMock()
        bm.enabled = False

        with patch.object(behaviour, "_sample", return_value=None):
            with patch.object(behaviour, "store_bets"):
                with patch.object(
                    type(behaviour),
                    "benchmarking_mode",
                    new_callable=PropertyMock,
                    return_value=bm,
                ):
                    with patch.object(
                        behaviour,
                        "finish_behaviour",
                        side_effect=lambda p: iter([None]),
                    ) as mock_finish:
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        mock_finish.assert_called_once()
        payload = mock_finish.call_args[0][0]
        assert isinstance(payload, SamplingPayload)
        assert payload.index is None

    def test_async_act_benchmarking_inc_day(self) -> None:
        """async_act should handle benchmarking day increment when sample is None."""
        behaviour = _make_behaviour()
        bet = _make_mock_bet(queue_status=QueueStatus.TO_PROCESS)
        bet.queue_status = MagicMock()
        bet.queue_status.move_to_fresh.return_value = QueueStatus.FRESH
        bet.queue_status.move_to_process = MagicMock(
            return_value=QueueStatus.TO_PROCESS
        )
        # Use a real QueueStatus so that the assignment chain works
        behaviour.bets = [bet]

        benchmark_ctx = MagicMock()
        behaviour.__dict__["_context"].benchmark_tool.measure.return_value = (
            benchmark_ctx
        )
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        bm = MagicMock()
        bm.enabled = True

        with patch.object(behaviour, "_sample", return_value=None):
            with patch.object(
                behaviour,
                "_benchmarking_inc_day",
                return_value=(True, True),
            ):
                with patch.object(behaviour, "store_bets"):
                    with patch.object(
                        type(behaviour),
                        "benchmarking_mode",
                        new_callable=PropertyMock,
                        return_value=bm,
                    ):
                        with patch.object(
                            behaviour,
                            "finish_behaviour",
                            side_effect=lambda p: iter([None]),
                        ) as mock_finish:
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        mock_finish.assert_called_once()
        payload = mock_finish.call_args[0][0]
        assert isinstance(payload, SamplingPayload)
        assert payload.benchmarking_finished is True
        assert payload.day_increased is True


YES_TOKEN = "yes_token"
NO_TOKEN = "no_token"
EMPTY_BOOK: Dict[str, Any] = {"asks": [], "bids": []}
NORMAL_BOOK: Dict[str, Any] = {
    "asks": [{"price": "0.52", "size": "100"}, {"price": "0.55", "size": "50"}],
    "bids": [{"price": "0.48", "size": "100"}],
}


def _book(ask: str, bid: Optional[str] = None) -> Dict[str, Any]:
    """Return a one-level book."""
    bids = [] if bid is None else [{"price": bid, "size": "10"}]
    return {"asks": [{"price": ask, "size": "10"}], "bids": bids}


def _book_bet(bet_id: str = "bet1", invested_amount: int = 0) -> Any:
    """Return a mock Polymarket bet with both outcome token ids."""
    bet = _make_mock_bet(bet_id=bet_id, invested_amount=invested_amount)
    bet.outcome_token_ids = {
        "Yes": f"{bet_id}_{YES_TOKEN}",
        "No": f"{bet_id}_{NO_TOKEN}",
    }
    return bet


def _book_behaviour(
    books: Dict[str, Any], spread_max: float = 0.1, spread_min: float = 0.0
) -> Tuple[SamplingBehaviour, MagicMock]:
    """Return a Polymarket behaviour whose connection serves ``books`` by token id."""
    behaviour = _make_behaviour()
    params = behaviour.context.params
    params.is_running_on_polymarket = True
    params.polymarket_spread_min = spread_min
    params.polymarket_spread_max = spread_max
    params.declined_market_cooldown = COOLDOWN
    behaviour.context.benchmarking_mode.enabled = False

    def _send(payload: Dict[str, Any]):  # type: ignore[no-untyped-def]
        return _return_gen(books.get(payload["params"]["token_id"]))

    send = MagicMock(side_effect=_send)
    behaviour.send_polymarket_connection_request = send  # type: ignore[method-assign]
    return behaviour, send


def _run(gen: Any) -> Any:
    """Exhaust a generator and return its value."""
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


class TestBookCanTakeBet:
    """Tests for the order-book check run before the mech request."""

    @pytest.mark.parametrize(
        "yes_book, no_book, expected, n_fetches",
        [
            (EMPTY_BOOK, EMPTY_BOOK, False, 2),
            (EMPTY_BOOK, NORMAL_BOOK, True, 2),
            (NORMAL_BOOK, EMPTY_BOOK, True, 1),
            (_book("0.99"), _book("0.999"), False, 2),
            (_book("0.99", "0.98"), _book("0.999", "0.99"), False, 2),
            # 0.75 - 0.5 is exactly 0.25 in binary floating point
            (_book("0.75", "0.5"), EMPTY_BOOK, True, 1),
            (_book("0.76", "0.5"), EMPTY_BOOK, False, 2),
            # a crossed book has a negative spread, rejected like the gate does
            (_book("0.4", "0.5"), EMPTY_BOOK, False, 2),
            # no bids: the spread gate is bypassed, so a bet can be placed
            (_book("0.5"), EMPTY_BOOK, True, 1),
            (NORMAL_BOOK, NORMAL_BOOK, True, 1),
            # the Yes side is out of band, the No side passes
            (_book("0.9", "0.5"), _book("0.5", "0.45"), True, 2),
        ],
    )
    def test_book_shapes(
        self,
        yes_book: Dict[str, Any],
        no_book: Dict[str, Any],
        expected: bool,
        n_fetches: int,
    ) -> None:
        """The market fails only when no side has a cheap enough ask in the band."""
        bet = _book_bet()
        behaviour, send = _book_behaviour(
            {f"bet1_{YES_TOKEN}": yes_book, f"bet1_{NO_TOKEN}": no_book},
            spread_max=0.25,
        )
        assert _run(behaviour._book_can_take_bet(bet)) is expected
        assert send.call_count == n_fetches
        fetched = [c.args[0]["params"]["token_id"] for c in send.call_args_list]
        assert fetched == [f"bet1_{YES_TOKEN}", f"bet1_{NO_TOKEN}"][:n_fetches]
        # a readable book never takes the error path
        behaviour.context.logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        "yes_book, no_book, reason",
        [
            (EMPTY_BOOK, EMPTY_BOOK, "Yes: no asks; No: no asks"),
            (_book("0.995"), _book("0.99"), "Yes: best ask 0.995; No: best ask 0.99"),
            (_book("0.7", "0.5"), _book("0.5", "0.3"), "Yes: spread 0.200"),
        ],
    )
    def test_failure_reason_is_logged(
        self, yes_book: Dict[str, Any], no_book: Dict[str, Any], reason: str
    ) -> None:
        """The skip line names the reason for each side."""
        behaviour, _ = _book_behaviour(
            {f"bet1_{YES_TOKEN}": yes_book, f"bet1_{NO_TOKEN}": no_book}
        )
        assert _run(behaviour._book_can_take_bet(_book_bet())) is False
        logged = behaviour.context.logger.info.call_args[0][0]
        assert reason in logged and "bet1" in logged

    @pytest.mark.parametrize("spread_min, expected", [(0.25, True), (0.26, False)])
    def test_spread_min_edge(self, spread_min: float, expected: bool) -> None:
        """A spread exactly at polymarket_spread_min passes; below it fails."""
        book = _book("0.75", "0.5")
        behaviour, _ = _book_behaviour(
            {f"bet1_{YES_TOKEN}": book, f"bet1_{NO_TOKEN}": book},
            spread_max=1.0,
            spread_min=spread_min,
        )
        assert _run(behaviour._book_can_take_bet(_book_bet())) is expected

    def test_bid_ask_spread_uses_best_levels(self) -> None:
        """The spread is the lowest ask minus the highest bid."""
        asks = [{"price": "0.7"}, {"price": "0.6"}, {"price": "0.8"}]
        bids = [{"price": "0.4"}, {"price": "0.5"}, {"price": "0.3"}]
        assert SamplingBehaviour.bid_ask_spread(asks, bids) == pytest.approx(0.1)

    def test_connection_exception_proceeds(self) -> None:
        """An exception raised at the connection boundary proceeds with the market."""
        behaviour, send = _book_behaviour({})
        send.side_effect = ValueError("boom")
        assert _run(behaviour._book_can_take_bet(_book_bet())) is True
        assert "boom" in behaviour.context.logger.warning.call_args[0][0]

    @pytest.mark.parametrize("spread_ask, expected", [("0.6", True), ("0.61", False)])
    def test_service_spread_max(self, spread_ask: str, expected: bool) -> None:
        """At the service band [0.0, 0.1], a 0.1 spread passes and 0.11 fails."""
        bet = _book_bet()
        book = _book(spread_ask, "0.5")
        behaviour, _ = _book_behaviour(
            {f"bet1_{YES_TOKEN}": book, f"bet1_{NO_TOKEN}": book}
        )
        assert _run(behaviour._book_can_take_bet(bet)) is expected

    @pytest.mark.parametrize(
        "response",
        [
            None,
            {"error": "No orderbook exists for the requested token id"},
            "unexpected",
            {"asks": [{"price": "None", "size": "1"}], "bids": []},
        ],
    )
    def test_unreadable_book_proceeds(self, response: Any) -> None:
        """A failed or unparseable fetch keeps today's behaviour: the market proceeds."""
        bet = _book_bet()
        behaviour, send = _book_behaviour(
            {f"bet1_{YES_TOKEN}": response, f"bet1_{NO_TOKEN}": EMPTY_BOOK}
        )
        assert _run(behaviour._book_can_take_bet(bet)) is True
        assert send.call_count == 1
        behaviour.context.logger.warning.assert_called_once()
        if isinstance(response, dict) and "error" in response:
            logged = behaviour.context.logger.warning.call_args[0][0]
            assert response["error"] in logged
            assert "KeyError" not in logged

    def test_malformed_json_proceeds(self) -> None:
        """A connection reply that is not JSON proceeds instead of crashing."""
        bet = _book_bet()
        behaviour = _make_behaviour()
        behaviour.context.params.polymarket_spread_min = 0.0
        behaviour.context.params.polymarket_spread_max = 0.1
        behaviour.context.srr_dialogues.create.return_value = (
            MagicMock(),
            MagicMock(),
        )
        reply = MagicMock(payload="{not json")
        with patch.object(
            behaviour, "do_connection_request", return_value=_return_gen(reply)
        ):
            assert _run(behaviour._book_can_take_bet(bet)) is True

    def test_no_token_ids_cannot_take_a_bet(self) -> None:
        """A Polymarket bet without outcome token ids has no book to bet on."""
        bet = _book_bet()
        bet.outcome_token_ids = None
        behaviour, send = _book_behaviour({})
        assert _run(behaviour._book_can_take_bet(bet)) is False
        send.assert_not_called()
        assert "no token ids" in behaviour.context.logger.info.call_args[0][0]


class TestAsyncActBookCheck:
    """Tests for the order-book check in async_act."""

    @staticmethod
    def _act(
        behaviour: SamplingBehaviour,
        sampled: Optional[List[Optional[int]]] = None,
        benchmarking: bool = False,
    ) -> Tuple[SamplingPayload, Any]:
        """Run async_act; ``_sample`` returns ``sampled`` in order, or runs for real."""
        bm = MagicMock()
        bm.enabled = benchmarking
        stored: List[List[int]] = []
        behaviour.__dict__["stored"] = stored
        props = {
            "benchmarking_mode": bm,
            "synced_timestamp": NOW,
            "kpi_is_met": False,
            "review_bets_for_selling": False,
            "shared_state": MagicMock(liquidity_cache={}),
        }
        with ExitStack() as stack:
            sample = None
            if sampled is not None:
                sample = stack.enter_context(
                    patch.object(behaviour, "_sample", side_effect=sampled)
                )
            for name, value in props.items():
                stack.enter_context(
                    patch.object(
                        type(behaviour),
                        name,
                        new_callable=PropertyMock,
                        return_value=value,
                    )
                )
            stack.enter_context(
                patch.object(
                    behaviour,
                    "store_bets",
                    side_effect=lambda: stored.append(
                        [b.processed_timestamp for b in behaviour.bets]
                    ),
                )
            )
            stack.enter_context(
                patch.object(behaviour, "hash_stored_bets", return_value="hash")
            )
            stack.enter_context(
                patch.object(
                    behaviour, "_benchmarking_inc_day", return_value=(False, False)
                )
            )
            finish = stack.enter_context(
                patch.object(
                    behaviour, "finish_behaviour", side_effect=lambda p: iter([None])
                )
            )
            _run(behaviour.async_act())
        return finish.call_args[0][0], sample

    def test_first_fails_second_passes(self) -> None:
        """The second candidate is sampled; the first is stamped and cools down."""
        bad, good = _book_bet("bad"), _book_bet("good")
        behaviour, send = _book_behaviour(
            {
                f"bad_{YES_TOKEN}": _book("0.999"),
                f"bad_{NO_TOKEN}": EMPTY_BOOK,
                f"good_{YES_TOKEN}": NORMAL_BOOK,
            }
        )
        behaviour.bets = [bad, good]
        payload, sample = self._act(behaviour, [0, 1])
        assert payload.index == 1
        assert payload.bets_hash == "hash"
        assert sample.call_count == 2
        assert send.call_count == 3
        assert bad.processed_timestamp == NOW
        assert good.processed_timestamp == 0
        assert behaviour._declined_recently(bad, NOW + 1)
        # the stamp is saved, so the cooldown carries into the next period
        assert behaviour.__dict__["stored"] == [[NOW, 0]]

    def test_stamped_market_is_not_resampled(self) -> None:
        """With the real _sample, a market failing its book makes way for the next."""
        bad = _book_bet("bad")
        good = _book_bet("good")
        for bet, liquidity in ((bad, 200.0), (good, 100.0)):
            bet.openingTimestamp = NOW + 86400 * 5
            bet.scaledLiquidityMeasure = liquidity
        behaviour, send = _book_behaviour({})
        send.side_effect = lambda payload: _return_gen(
            EMPTY_BOOK
            if payload["params"]["token_id"].startswith("bad")
            else NORMAL_BOOK
        )
        params = behaviour.context.params
        params.use_multi_bets_mode = False
        params.enable_multi_bets_fallback = False
        params.sample_bets_closing_days = 60
        params.opening_margin = 100
        params.safe_voting_range = 100
        params.is_outcome_side_threshold_filter_enabled = False
        params.exclude_neg_risk_markets = False
        params.disabled_polymarket_tags = []
        behaviour.bets = [bad, good]
        payload, _ = self._act(behaviour)
        assert payload.index == 1
        assert bad.processed_timestamp == NOW
        assert behaviour.__dict__["stored"] == [[NOW, 0]]

    def test_every_candidate_fails(self) -> None:
        """When every candidate within the cap fails, the cycle has no market."""
        bets = [_book_bet(f"b{i}") for i in range(BOOK_CHECK_CANDIDATES + 1)]
        behaviour, send = _book_behaviour({})
        send.side_effect = lambda payload: _return_gen(EMPTY_BOOK)
        behaviour.bets = bets
        payload, sample = self._act(behaviour, list(range(len(bets))))
        assert payload.index is None
        assert payload.bets_hash is None
        assert sample.call_count == BOOK_CHECK_CANDIDATES
        assert send.call_count == 2 * BOOK_CHECK_CANDIDATES
        stamped = [b.processed_timestamp for b in bets]
        assert stamped == [NOW] * BOOK_CHECK_CANDIDATES + [0]
        assert behaviour.__dict__["stored"] == [stamped]
        warning = behaviour.context.logger.warning.call_args[0][0]
        assert "failed the book check" in warning

    def test_nothing_sampled(self) -> None:
        """No sampled market means no book fetch."""
        behaviour, send = _book_behaviour({})
        behaviour.bets = []
        payload, _ = self._act(behaviour, [None])
        assert payload.index is None
        send.assert_not_called()

    def test_market_with_position_is_not_checked(self) -> None:
        """A market already holding a position (rebet, sell review) skips the check."""
        behaviour, send = _book_behaviour({})
        behaviour.bets = [_book_bet(invested_amount=10)]
        payload, _ = self._act(behaviour, [0])
        assert payload.index == 0
        send.assert_not_called()

    @pytest.mark.parametrize(
        "on_polymarket, benchmarking", [(False, False), (True, True)]
    )
    def test_omen_and_benchmarking_never_fetch(
        self, on_polymarket: bool, benchmarking: bool
    ) -> None:
        """On Omen or in benchmarking mode the sampled index is unchanged and no book is read."""
        bet = _book_bet()
        behaviour, send = _book_behaviour({f"bet1_{YES_TOKEN}": EMPTY_BOOK})
        behaviour.context.params.is_running_on_polymarket = on_polymarket
        behaviour.bets = [bet]
        payload, sample = self._act(behaviour, [0], benchmarking=benchmarking)
        assert payload.index == 0
        assert sample.call_count == 1
        send.assert_not_called()
        assert bet.processed_timestamp == 0
