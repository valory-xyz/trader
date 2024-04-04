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

        # Note: the openingTimestamp is misleading as it is the closing timestamp of the bet
        if self.params.using_kelly:
            # get only bets that close in the next 48 hours
            self.bets = [
                bet
                for bet in self.bets
                if bet.openingTimestamp
                <= (
                    self.synced_timestamp
                    + self.params.sample_bets_closing_days * UNIX_DAY
                )
            ]

        return filter(lambda bet: bet.status == BetStatus.UNPROCESSED, self.bets)

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
        available_bets = list(self.available_bets)

        if len(available_bets) == 0:
            msg = "There were no unprocessed bets available to sample from!"
            self.context.logger.warning(msg)
            return None

        idx = self._sampled_bet_idx(available_bets)

        if self.bets[idx].scaledLiquidityMeasure == 0:
            msg = "There were no unprocessed bets with non-zero liquidity!"
            self.context.logger.warning(msg)
            return None

        # update the bet's status for the given id to `PROCESSED`
        self.bets[idx].status = BetStatus.PROCESSED
        msg = f"Sampled bet: {self.bets[idx]}"
        self.context.logger.info(msg)
        return idx

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            if self.synchronized_data.stop_trading:
                msg = "Stop trading"
                self.context.logger.info(msg)
                payload = SamplingPayload(self.context.agent_address, None, None)
            else:
                self.read_bets()
                idx = self._sample()
                self.store_bets()
                if idx is None:
                    bets_hash = None
                else:
                    bets_hash = self.hash_stored_bets()
                payload = SamplingPayload(self.context.agent_address, bets_hash, idx)

        yield from self.finish_behaviour(payload)
