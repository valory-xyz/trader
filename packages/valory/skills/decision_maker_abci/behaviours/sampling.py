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
from typing import Generator, Iterator, List, Optional

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.bets import Bet, BetStatus


UNIX_DAY = 60 * 60 * 24


class SamplingBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = SamplingRound

    @property
    def available_bets(self) -> Iterator[Bet]:
        """Get an iterator of the unprocessed bets."""
        if self.params.using_kelly:
            # Filter for bets closing within the next `sample_bets_closing_days`
            self.bets = [
                bet
                for bet in self.bets
                if bet.openingTimestamp <= (self.synced_timestamp + self.params.sample_bets_closing_days * UNIX_DAY)
            ]

        # Filter for unprocessed and unskipped bets
        return filter(lambda bet: bet.status in {BetStatus.UNPROCESSED}, self.bets)

    def _is_profitable(self, bet: Bet) -> bool:
        """Determine if a bet is profitable."""
        return bet.potential_net_profit > 0 and bet.scaledLiquidityMeasure > 0

    def _sampled_bet_idx(self, bets: List[Bet]) -> int:
        """Sample a bet and return its index based on the highest liquidity."""
        return self.bets.index(max(bets, key=lambda bet: bet.scaledLiquidityMeasure))

    def _sample(self) -> Optional[int]:
        """Sample a bet, mark it as processed if profitable, and return its index."""
        available_bets = list(self.available_bets)

        if len(available_bets) == 0:
            self.context.logger.warning("No unprocessed bets available to sample from!")
            return None

        idx = self._sampled_bet_idx(available_bets)
        sampled_bet = self.bets[idx]

        if not self._is_profitable(sampled_bet):
            # Mark unprofitable bets as skipped
            sampled_bet.status = BetStatus.SKIPPED
            self.context.logger.info(f"Skipped bet due to lack of profitability: {sampled_bet}")
            return None

        # Mark as processed if profitable
        sampled_bet.status = BetStatus.PROCESSED
        self.context.logger.info(f"Sampled profitable bet: {sampled_bet}")
        return idx

    def async_act(self) -> Generator:
        """Perform the sampling action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self.read_bets()
            idx = self._sample()
            self.store_bets()
            bets_hash = self.hash_stored_bets() if idx is not None else None
            payload = SamplingPayload(self.context.agent_address, bets_hash, idx)

        yield from self.finish_behaviour(payload)