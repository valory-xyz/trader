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

import time
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    SamplingBehaviour,
    UNIX_DAY,
    UNIX_WEEK,
    WEEKDAYS,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus

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

    def test_kpi_is_met(self) -> None:
        """kpi_is_met should return synchronized_data value."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_staking_kpi_met=True)
            assert behaviour.kpi_is_met is True

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
