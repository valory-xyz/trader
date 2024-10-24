# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

import random
from typing import Any, Generator, List, Optional

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.bets import Bet


WEEKDAYS = 7
UNIX_DAY = 60 * 60 * 24
UNIX_WEEK = WEEKDAYS * UNIX_DAY


class SamplingBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = SamplingRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self.should_rebet: bool = False

    def setup(self) -> None:
        """Setup the behaviour."""
        self.read_bets()
        has_bet_in_the_past = any(bet.n_bets > 0 for bet in self.bets)
        if has_bet_in_the_past:
            random.seed(self.synchronized_data.most_voted_randomness)
            self.should_rebet = random.random() <= self.params.rebet_chance  # nosec
        rebetting_status = "enabled" if self.should_rebet else "disabled"
        self.context.logger.info(f"Rebetting {rebetting_status}.")

    def processable_bet(self, bet: Bet) -> bool:
        """Whether we can process the given bet."""
        now = self.synced_timestamp
        # Note: `openingTimestamp` is the timestamp when a question stops being available for voting.
        within_opening_range = bet.openingTimestamp <= (
            now + self.params.sample_bets_closing_days * UNIX_DAY
        )
        within_safe_range = now < bet.openingTimestamp + self.params.safe_voting_range
        within_ranges = within_opening_range and within_safe_range

        # create a filter based on whether we can rebet or not
        lifetime = bet.openingTimestamp - now
        t_rebetting = (lifetime // UNIX_WEEK) + UNIX_DAY
        can_rebet = now >= bet.processed_timestamp + t_rebetting
        bet_id = bet.id

        # if we should not rebet we need to ignore markets that have been bet upon in the past
        if not self.should_rebet:
            if bet.n_bets != 0:
                return False
            else:
                # filter for changed liquidity on previously processed markets to avoid resampling the same market repeatedly
                if bet.processed_timestamp > 0:
                    scaled_liquidity_changed = (
                        bet.scaledLiquidityMeasure
                        != self.shared_state.bet_selection_stats.get(bet_id, {}).get(
                            "scaledLiquidityMeasure", 0
                        )
                    )
                    return within_ranges and can_rebet and scaled_liquidity_changed
                else:
                    return within_ranges and can_rebet

        else:
            # if we should rebet, we should have at least one bet processed in the past
            if not bool(bet.n_bets):
                return False
            else:
                self.context.logger.info(
                    f"Prediction response vote: {bet.prediction_response}"
                )
                outcome_index = bet.prediction_response.vote
                if outcome_index is not None:
                    outcome_liquidity_change = (
                        bet.outcomeTokenAmounts[outcome_index]
                        != self.shared_state.bet_selection_stats.get(bet_id, {}).get(
                            "outcome_token_amounts", [0, 0]
                        )[outcome_index]
                    )
                    return within_ranges and can_rebet and outcome_liquidity_change
                else:
                    # market cannot be processed as it doesn't actually have a previous bet
                    return False

    def _sampled_bet_idx(self, bets: List[Bet]) -> int:
        """
        Sample a bet and return its id.

        The sampling logic is relatively simple at the moment.
        It simply selects the unprocessed bet with the largest liquidity.

        :param bets: the bets' values to compare for the sampling.
        :return: the id of the sampled bet, out of all the available bets, not only the given ones.
        """
        return self.bets.index(max(bets))

    def _sample(self) -> Optional[int]:
        """Sample a bet, mark it as processed, and return its index."""
        available_bets = list(filter(self.processable_bet, self.bets))

        # store the bet selection stats for each processable bet at the time of sampling
        for bet in available_bets:
            self.shared_state.bet_selection_stats[bet.id] = {
                "scaled_liquidity_measure": bet.scaledLiquidityMeasure,
                "outcome_token_amounts": bet.outcomeTokenAmounts,
            }

        if len(available_bets) == 0:
            msg = "There were no unprocessed bets available to sample from!"
            self.context.logger.warning(msg)
            return None

        idx = self._sampled_bet_idx(available_bets)

        if self.bets[idx].scaledLiquidityMeasure == 0:
            msg = "There were no unprocessed bets with non-zero liquidity!"
            self.context.logger.warning(msg)
            return None

        # update the bet's timestamp of processing and its number of rebets for the given id
        self.bets[idx].processed_timestamp = self.synced_timestamp
        self.bets[idx].n_bets += 1
        msg = f"Sampled bet: {self.bets[idx]}"
        self.context.logger.info(msg)
        return idx

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            idx = self._sample()
            if idx is None:
                bets_hash = None
            else:
                bets_hash = self.hash_stored_bets()
            payload = SamplingPayload(self.context.agent_address, bets_hash, idx)

        yield from self.finish_behaviour(payload)
