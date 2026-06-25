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

"""This module contains the behaviour for sampling a bet."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    QueryingBehaviour,
)

WEEKDAYS = 7
UNIX_DAY = 60 * 60 * 24
UNIX_WEEK = WEEKDAYS * UNIX_DAY


class SamplingBehaviour(DecisionMakerBaseBehaviour, QueryingBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = SamplingRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self.should_rebet: bool = False

    def setup(self) -> None:
        """Setup the behaviour."""
        self.read_bets()

    @property
    def kpi_is_met(self) -> bool:
        """Whether the agent has done its required work this epoch.

        Tracks the regime-aware activity target: in the old regime this equals
        the on-chain staking KPI, while in the new (decoupled-activity) regime
        it follows the off-chain target so multi-bets fallback and sell-review
        continue until the target (e.g. 8) is reached rather than stopping at
        the on-chain ~1.

        :return: whether the regime-aware activity target is met.
        """
        return self.synchronized_data.is_activity_target_met

    @property
    def review_bets_for_selling(self) -> bool:
        """Whether to review bets for selling."""
        return self.synchronized_data.review_bets_for_selling

    def _multi_bets_fallback_allowed(self) -> bool:
        return self.params.enable_multi_bets_fallback and not self.kpi_is_met

    def processable_bet(
        self, bet: Bet, now: int, multi_bets_active: bool = False
    ) -> bool:
        """Whether we can process the given bet."""

        if bet.queue_status.is_expired():
            return False

        selling_specific = self.kpi_is_met and self.review_bets_for_selling

        bets_placed = bool(bet.n_bets)
        if not bets_placed and selling_specific:
            # non-expired bet with no bets, not processable
            self.context.logger.info(f"Bet {bet.id} has no bets")
            return False

        bet_mode_allowable = multi_bets_active or not bets_placed or selling_specific

        within_opening_range = bet.openingTimestamp <= (
            now + self.params.sample_bets_closing_days * UNIX_DAY
        )
        safe_offset = self.params.opening_margin + self.params.safe_voting_range
        within_safe_range = now < bet.openingTimestamp - safe_offset
        if not within_safe_range:
            # The blacklist side-effect is tied to the true safety floor ONLY.
            # A market skipped purely for the optional horizon preference is
            # NOT blacklisted.
            bet.blacklist_forever()

        # Optional horizon floor (Polymarket-only operator preference): extend
        # the lower bound to the stricter of the safety floor and
        # ``min_bets_closing_days``. 0 = no-op (lower bound stays the safety
        # floor; ``within_min_range == within_safe_range``). Liveness-aware:
        # only applied while the activity target is on track, so a too-tight
        # window can never starve the staking KPI.
        apply_horizon = self.params.min_bets_closing_days > 0 and self.kpi_is_met
        lower_offset = max(
            safe_offset,
            self.params.min_bets_closing_days * UNIX_DAY if apply_horizon else 0,
        )
        within_min_range = now < bet.openingTimestamp - lower_offset
        within_ranges = within_opening_range and within_min_range

        # check if bet queue number is processable
        processable_statuses = {
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
        }
        bet_queue_processable = bet.queue_status in processable_statuses

        return bet_mode_allowable and within_ranges and bet_queue_processable

    def _classify_processable_bet(
        self, bet: Bet, now: int, multi_bets_active: bool
    ) -> str:
        """Classify the dominant rejection reason in the mirror's own precedence.

        Returns one of ``expired``, ``wrong_mode``, ``out_of_safe``,
        ``out_of_open``, ``out_of_open_min``, ``wrong_queue``,
        ``processable`` — the first one that trips, in that precedence
        order. Pure read; does NOT call ``blacklist_forever`` and does NOT
        mutate the bet — the real filter ``processable_bet`` still runs
        and is the source of truth.

        Caveat: ``processable_bet`` does NOT short-circuit on the last three
        conditions — it computes ``bet_mode_allowable / within_opening_range
        / within_safe_range / bet_queue_processable`` independently and ANDs
        them. It also has a ``blacklist_forever()`` side-effect on
        ``not within_safe_range`` regardless of the other conditions. So
        when a bet trips both ``wrong_mode`` and ``out_of_safe``, this
        classifier reports ``wrong_mode`` (precedence) while the actual
        side-effect blacklists the bet — and the bet will surface as
        ``expired`` in the next cycle's breakdown.

        :param bet: the bet to classify.
        :param now: current timestamp.
        :param multi_bets_active: whether multi-bets mode is active.
        :return: the dominant rejection reason, or ``processable``.
        """
        if bet.queue_status.is_expired():
            return "expired"
        selling_specific = self.kpi_is_met and self.review_bets_for_selling
        bets_placed = bool(bet.n_bets)
        if not bets_placed and selling_specific:
            return "wrong_mode"
        bet_mode_allowable = multi_bets_active or not bets_placed or selling_specific
        if not bet_mode_allowable:
            return "wrong_mode"
        within_safe_range = (
            now
            < bet.openingTimestamp
            - self.params.opening_margin
            - self.params.safe_voting_range
        )
        if not within_safe_range:
            return "out_of_safe"
        within_opening_range = bet.openingTimestamp <= (
            now + self.params.sample_bets_closing_days * UNIX_DAY
        )
        if not within_opening_range:
            return "out_of_open"
        # Mirror of the optional horizon floor in ``processable_bet``. Only
        # fires for markets the true safety floor lets through but the
        # operator's horizon preference rejects (and only while liveness-aware
        # gate is active — i.e. ``kpi_is_met`` is true). Read-only; no
        # blacklist.
        if (
            self.params.min_bets_closing_days > 0
            and self.kpi_is_met
            and bet.openingTimestamp
            < now + self.params.min_bets_closing_days * UNIX_DAY
        ):
            return "out_of_open_min"
        processable_statuses = {
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
        }
        if bet.queue_status not in processable_statuses:
            return "wrong_queue"
        return "processable"

    @staticmethod
    def _sort_by_priority_logic(bets: List[Bet]) -> List[Bet]:
        """
        Sort bets based on the priority logic.

        :param bets: the bets to sort.
        :return: the sorted list of bets.
        """
        return sorted(
            bets,
            key=lambda bet: (
                bet.invested_amount,
                -bet.processed_timestamp,  # Increasing order of processed_timestamp
                bet.scaledLiquidityMeasure,
                bet.openingTimestamp,
            ),
            reverse=True,
        )

    @staticmethod
    def _get_bets_queue_wise(bets: List[Bet]) -> Tuple[List[Bet], List[Bet], List[Bet]]:
        """Return a dictionary of bets with queue status as key."""

        bets_by_status: Dict[QueueStatus, List[Bet]] = defaultdict(list)

        for bet in bets:
            bets_by_status[bet.queue_status].append(bet)

        return (
            bets_by_status[QueueStatus.TO_PROCESS],
            bets_by_status[QueueStatus.PROCESSED],
            bets_by_status[QueueStatus.REPROCESSED],
        )

    def _sampled_bet_idx(self, bets: List[Bet]) -> int:
        """
        Sample a bet and return its index.

        The sampling logic follows the specified priority logic:
        1. Filter out all the bets that have a processed_timestamp != 0 to get a list of new bets.
        2. If the list of new bets is not empty:
           2.1 Order the list in decreasing order of liquidity (highest liquidity first).
           2.2 For bets with the same liquidity, order them in decreasing order of market closing time (openingTimestamp).
        3. If the list of new bets is empty:
           3.1 Order the bets in decreasing order of invested_amount.
           3.2 For bets with the same invested_amount, order them in increasing order of processed_timestamp (least recently processed first).
           3.3 For bets with the same invested_amount and processed_timestamp, order them in decreasing order of liquidity.
           3.4 For bets with the same invested_amount, processed_timestamp, and liquidity, order them in decreasing order of market closing time (openingTimestamp).

        :param bets: the bets' values to compare for the sampling.
        :return: the index of the sampled bet, out of all the available bets, not only the given ones.
        """

        to_process_bets, processed_bets, reprocessed_bets = self._get_bets_queue_wise(
            bets
        )

        # pick the first queue status that has bets in it
        bets_to_sort: List[Bet] = to_process_bets or processed_bets or reprocessed_bets

        sorted_bets = self._sort_by_priority_logic(bets_to_sort)

        return self.bets.index(sorted_bets[0])

    def _sampling_benchmarking_bet(self, bets: List[Bet]) -> Optional[int]:
        """Sample bet for benchmarking"""
        to_process_bets, processed_bets, reprocessed_bets = self._get_bets_queue_wise(
            bets
        )

        self.context.logger.info(f"TO_PROCESS_LEN: {len(to_process_bets)}")
        self.context.logger.info(f"PROCESSED_LEN: {len(processed_bets)}")
        self.context.logger.info(f"REPROCESSED_LEN: {len(reprocessed_bets)}")

        self.context.logger.info(
            f"MECH CALLS MADE: {self.shared_state.benchmarking_mech_calls}"
        )

        if (
            self.shared_state.benchmarking_mech_calls
            == self.benchmarking_mode.nr_mech_calls
        ):
            return None

        bets_to_sort: List[Bet] = to_process_bets or processed_bets or reprocessed_bets
        sorted_bets = self._sort_by_priority_logic(bets_to_sort)

        return self.bets.index(sorted_bets[0])

    def _sample(self) -> Optional[int]:
        """Sample a bet, mark it as processed, and return its index."""
        # modify time "NOW" in benchmarking mode
        if self.benchmarking_mode.enabled:
            safe_voting_range = (
                self.params.opening_margin + self.params.safe_voting_range
            )
            now = self.shared_state.get_simulated_now_timestamp(
                self.bets, safe_voting_range
            )
            self.context.logger.info(f"Simulating date: {datetime.fromtimestamp(now)}")
        else:
            now = self.synced_timestamp

        # Strict-mode breakdown (observability only — pure read pass).
        # Captured BEFORE the side-effecting processable_bet call so
        # out_of_safe bets are still classified as out_of_safe rather than
        # the `expired` they'll appear as after blacklist_forever fires.
        # No bet/list mutation — populates a fresh local dict.
        strict_breakdown: Dict[str, int] = defaultdict(int)
        for bet in self.bets:
            strict_breakdown[
                self._classify_processable_bet(
                    bet,
                    now=now,
                    multi_bets_active=self.params.use_multi_bets_mode,
                )
            ] += 1

        # First, try to find bets in strict mode (no fallback) for single bet mode. But allow mutli-bets directly if enabled.
        available_bets = list(
            filter(
                lambda bet: self.processable_bet(
                    bet, now=now, multi_bets_active=self.params.use_multi_bets_mode
                ),
                self.bets,
            )
        )

        # If no bets available and fallback is enabled, try again with fallback
        fallback_activated = False
        if len(available_bets) <= 0 and self._multi_bets_fallback_allowed():
            self.context.logger.info(
                "No bets available in single-bet mode, checking with multi-bet fallback enabled..."
            )
            available_bets = list(
                filter(
                    lambda bet: self.processable_bet(
                        bet,
                        now=now,
                        multi_bets_active=True,
                    ),
                    self.bets,
                )
            )
            if len(available_bets) > 0:
                fallback_activated = True
                self.context.logger.info(
                    f"Multi-bet fallback activated: {len(available_bets)} bets now available"
                )

        # Fallback-mode breakdown (only when fallback actually produced
        # bets). Pure-read pass, classified with multi_bets_active=True so
        # the `processable` count reconciles with the post-fallback `kept`.
        # Bets that strict's blacklist_forever side-effect just killed will
        # appear here as `expired` rather than `out_of_safe` — that's the
        # post-filter state, by design.
        fallback_breakdown: Optional[Dict[str, int]] = None
        if fallback_activated:
            fallback_breakdown = defaultdict(int)
            for bet in self.bets:
                fallback_breakdown[
                    self._classify_processable_bet(bet, now=now, multi_bets_active=True)
                ] += 1

        self.context.logger.info(
            f"[POLYSTRAT] filter=processable_bet "
            f"input={len(self.bets)} "
            f"dropped={len(self.bets) - len(available_bets)} "
            f"kept={len(available_bets)} "
            f"fallback_activated={fallback_activated}"
        )
        self.context.logger.info(
            f"[POLYSTRAT] filter=processable_bet.breakdown.strict "
            f"expired={strict_breakdown['expired']} "
            f"wrong_mode={strict_breakdown['wrong_mode']} "
            f"out_of_safe={strict_breakdown['out_of_safe']} "
            f"out_of_open={strict_breakdown['out_of_open']} "
            f"wrong_queue={strict_breakdown['wrong_queue']} "
            f"processable={strict_breakdown['processable']}"
        )
        if fallback_breakdown is not None:
            self.context.logger.info(
                f"[POLYSTRAT] filter=processable_bet.breakdown.fallback "
                f"expired={fallback_breakdown['expired']} "
                f"wrong_mode={fallback_breakdown['wrong_mode']} "
                f"out_of_safe={fallback_breakdown['out_of_safe']} "
                f"out_of_open={fallback_breakdown['out_of_open']} "
                f"wrong_queue={fallback_breakdown['wrong_queue']} "
                f"processable={fallback_breakdown['processable']}"
            )

        if len(available_bets) == 0:
            msg = "There were no unprocessed bets available to sample from!"
            self.context.logger.warning(msg)
            return None

        if self.benchmarking_mode.enabled:
            idx = self._sampling_benchmarking_bet(available_bets)
            if not idx:
                return None

        # Policy filter: reject candidates whose Polymarket tags are on the
        # operator-configured disable list. Normalize both sides — strip
        # whitespace + lowercase — so tag casing drift or accidental
        # whitespace upstream doesn't silently break the match. Pre-filter
        # the candidate pool once here rather than per-iteration inside the
        # while-loop so we avoid redundant priority-sorting of bets we've
        # already decided to skip.
        disabled_tags = {
            t.strip().lower() for t in self.params.disabled_polymarket_tags
        }
        if disabled_tags:
            before = len(available_bets)
            available_bets = [
                bet
                for bet in available_bets
                if not (disabled_tags & {t.strip().lower() for t in bet.poly_tags})
            ]
            skipped = before - len(available_bets)
            self.context.logger.info(
                f"[POLYSTRAT] filter=disabled_tag "
                f"input={before} dropped={skipped} "
                f"kept={len(available_bets)} slugs={len(disabled_tags)}"
            )
            if not available_bets:
                msg = (
                    f"All {before} candidate bets were dropped by the "
                    f"disabled-tag filter!"
                )
                self.context.logger.warning(msg)
                return None

        # In-loop drop counters (per-iteration sequential funnel: zero_liq →
        # outcome_skew → neg_risk). Emitted as [POLYSTRAT] roll-up rows at
        # both exit paths.
        in_loop_iterations = 0
        in_loop_zero_liq = 0
        in_loop_skew = 0
        in_loop_neg_risk = 0

        # Loop until we find a valid bet or run out of options
        while available_bets:
            in_loop_iterations += 1
            # sample a bet using the priority logic
            idx = self._sampled_bet_idx(available_bets)
            sampled_bet = self.bets[idx]

            # Check liquidity
            liquidity = sampled_bet.scaledLiquidityMeasure
            if liquidity == 0:
                msg = f"Sampled bet {sampled_bet.id} has zero liquidity, skipping"
                self.context.logger.warning(msg)
                available_bets.remove(sampled_bet)
                in_loop_zero_liq += 1
                continue

            # This is to avoid sampling bets where the market is already heavily
            # skewed towards one outcome, results in unfavorable risk to reward ratio
            if self.params.is_outcome_side_threshold_filter_enabled:
                self.context.logger.info(
                    f"Sampled bet {sampled_bet.id} has liquidity {liquidity} and outcome token marginal prices {sampled_bet.outcomeTokenMarginalPrices}"
                )
                if any(
                    side > self.params.outcome_side_threshold_filter_threshold
                    for side in sampled_bet.outcomeTokenMarginalPrices
                ):
                    available_bets.remove(sampled_bet)
                    in_loop_skew += 1
                    continue

            if (
                self.params.is_running_on_polymarket
                and self.params.exclude_neg_risk_markets
                and sampled_bet.neg_risk
            ):
                msg = f"Sampled bet {sampled_bet.id} is a negRisk market, skipping"
                self.context.logger.info(msg)
                available_bets.remove(sampled_bet)
                in_loop_neg_risk += 1
                continue

            # Valid bet found
            self.shared_state.liquidity_cache[sampled_bet.id] = liquidity
            self.context.logger.info(
                f"[POLYSTRAT] filter=in_loop_zero_liq "
                f"input={in_loop_iterations} dropped={in_loop_zero_liq} "
                f"kept={in_loop_iterations - in_loop_zero_liq}"
            )
            self.context.logger.info(
                f"[POLYSTRAT] filter=in_loop_outcome_skew "
                f"input={in_loop_iterations - in_loop_zero_liq} "
                f"dropped={in_loop_skew} "
                f"kept={in_loop_iterations - in_loop_zero_liq - in_loop_skew}"
            )
            self.context.logger.info(
                f"[POLYSTRAT] filter=in_loop_neg_risk "
                f"input={in_loop_iterations - in_loop_zero_liq - in_loop_skew} "
                f"dropped={in_loop_neg_risk} kept=1"
            )
            msg = f"Sampled bet: {sampled_bet}"
            self.context.logger.info(msg)
            return idx

        # No valid bets found
        self.context.logger.info(
            f"[POLYSTRAT] filter=in_loop_zero_liq "
            f"input={in_loop_iterations} dropped={in_loop_zero_liq} "
            f"kept={in_loop_iterations - in_loop_zero_liq}"
        )
        self.context.logger.info(
            f"[POLYSTRAT] filter=in_loop_outcome_skew "
            f"input={in_loop_iterations - in_loop_zero_liq} "
            f"dropped={in_loop_skew} "
            f"kept={in_loop_iterations - in_loop_zero_liq - in_loop_skew}"
        )
        self.context.logger.info(
            f"[POLYSTRAT] filter=in_loop_neg_risk "
            f"input={in_loop_iterations - in_loop_zero_liq - in_loop_skew} "
            f"dropped={in_loop_neg_risk} kept=0"
        )
        msg = "No valid bets found after liquidity validation!"
        self.context.logger.warning(msg)
        return None

    def _benchmarking_inc_day(self) -> Tuple[bool, bool]:
        """Increase the simulated day in benchmarking mode."""
        self.context.logger.info(
            "No more markets to bet in the simulated day. Increasing simulated day."
        )
        self.shared_state.increase_one_day_simulation()
        benchmarking_finished = self.shared_state.check_benchmarking_finished()
        if benchmarking_finished:
            self.context.logger.info("No more days to simulate in benchmarking mode.")

        self.shared_state.benchmarking_mech_calls = 0

        day_increased = True

        return benchmarking_finished, day_increased

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            idx = self._sample()
            benchmarking_finished = None
            day_increased = None

            # day increase simulation and benchmarking finished check
            if idx is None and self.benchmarking_mode.enabled:
                benchmarking_finished, day_increased = self._benchmarking_inc_day()
                for bet in self.bets:
                    bet.queue_status = bet.queue_status.move_to_fresh()
                    bet.queue_status = bet.queue_status.move_to_process()

            self.store_bets()

            if idx is None:
                bets_hash = None
            else:
                bets_hash = self.hash_stored_bets()

            payload = SamplingPayload(
                self.context.agent_address,
                bets_hash,
                idx,
                benchmarking_finished,
                day_increased,
            )

        yield from self.finish_behaviour(payload)
