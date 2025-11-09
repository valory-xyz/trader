# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
        """Whether the kpi is met."""
        return self.synchronized_data.is_staking_kpi_met

    @property
    def review_bets_for_selling(self) -> bool:
        """Whether to review bets for selling."""
        return self.synchronized_data.review_bets_for_selling

    def processable_bet(self, bet: Bet, now: int) -> bool:
        """Whether we can process the given bet."""

        if bet.queue_status.is_expired():
            return False

        selling_specific = self.kpi_is_met and self.review_bets_for_selling

        bets_placed = bool(bet.n_bets)
        if not bets_placed and selling_specific:
            # non-expired bet with no bets, not processable
            self.context.logger.info(f"Bet {bet.id} has no bets")
            return False

        bet_mode_allowable = (
            self.params.use_multi_bets_mode or not bets_placed or selling_specific
        )

        within_opening_range = bet.openingTimestamp <= (
            now + self.params.sample_bets_closing_days * UNIX_DAY
        )
        within_safe_range = (
            now
            < bet.openingTimestamp
            - self.params.opening_margin
            - self.params.safe_voting_range
        )
        if not within_safe_range:
            bet.blacklist_forever()

        within_ranges = within_opening_range and within_safe_range

        # check if bet queue number is processable
        processable_statuses = {
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
        }
        bet_queue_processable = bet.queue_status in processable_statuses

        return bet_mode_allowable and within_ranges and bet_queue_processable

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

        # filter in only the bets that are processable and have a queue_status that allows them to be sampled
        available_bets = list(
            filter(
                lambda bet: self.processable_bet(bet, now=now),
                self.bets,
            )
        )
        if len(available_bets) == 0:
            msg = "There were no unprocessed bets available to sample from!"
            self.context.logger.warning(msg)
            return None

        if self.benchmarking_mode.enabled:
            idx = self._sampling_benchmarking_bet(available_bets)
            if not idx:
                return None

        # sample a bet using the priority logic
        idx = self._sampled_bet_idx(available_bets)
        sampled_bet = self.bets[idx]

        # fetch the liquidity of the sampled bet and cache it
        liquidity = sampled_bet.scaledLiquidityMeasure
        if liquidity == 0:
            msg = "There were no unprocessed bets with non-zero liquidity!"
            self.context.logger.warning(msg)
            return None
        self.shared_state.liquidity_cache[sampled_bet.id] = liquidity

        msg = f"Sampled bet: {sampled_bet}"
        self.context.logger.info(msg)
        return idx

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
