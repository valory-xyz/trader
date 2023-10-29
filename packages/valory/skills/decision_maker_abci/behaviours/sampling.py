# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

import time

from typing import Generator, Iterator, List, Optional, Tuple

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetStatus,
    serialize_bets,
)


class SamplingBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = SamplingRound

    @property
    def available_bets(self) -> Iterator[Bet]:
        """Get an iterator of the unprocessed bets."""
        bets = self.synchronized_data.bets
        return filter(lambda bet: bet.status == BetStatus.UNPROCESSED, bets)

    def _sampled_bet_idx(self, bets: List[Bet]) -> int:
        """
        Sample a bet and return its id.

        The sampling logic is relatively simple at the moment
        It simply selects the unprocessed bet with the largest liquidity.

        :param bets: the bets' values to compare for the sampling.
        :return: the id of the sampled bet, out of all the available bets, not only the given ones.
        """
        # Get only bets that close in the next 48 hours
        # Note: the openingTimestamp is misleading as it is the closing timestamp of the bet
        
        if self.params.sample_bets_closing_days <= 0:
            msg = "The number of days to sample bets from must be positive!"
            self.context.logger.warning(msg)
            return None
        short_term_bets = filter(lambda bet: bet.openingTimestamp <= (time.time() + self.params.sample_bets_closing_days*60*60*24), bets)
        short_term_bets_list = list(short_term_bets)
        if len(short_term_bets_list) == 0:
            return None
        self.context.logger.info(f"Short term bets: {short_term_bets_list}")
        return self.synchronized_data.bets.index(max(short_term_bets_list))

    def _set_processed(self, idx: int) -> Optional[str]:
        """Update the bet's status for the given id to `PROCESSED`, and return the updated bets list, serialized."""
        bets = self.synchronized_data.bets
        bets[idx].status = BetStatus.PROCESSED
        return serialize_bets(bets)

    def _sample(self) -> Tuple[Optional[str], Optional[int]]:
        """Sample a bet and return the bets, serialized, with the sampled bet marked as processed, and its index."""
        available_bets = list(self.available_bets)

        if len(available_bets) == 0:
            msg = "There were no unprocessed bets available to sample from!"
            self.context.logger.warning(msg)
            return None, None

        idx = self._sampled_bet_idx(available_bets)
        
        if idx is None:
            msg = "There were no unprocessed bets that close within the next 48 hours available to sample from!"
            self.context.logger.warning(msg)
            return None, None
        elif self.synchronized_data.bets[idx].scaledLiquidityMeasure == 0:
            msg = "There were no unprocessed bets with non-zero liquidity!"
            self.context.logger.warning(msg)
            return None, None

        bets = self._set_processed(idx)
        msg = f"Sampled bet: {self.synchronized_data.bets[idx]}"
        self.context.logger.info(msg)
        return bets, idx

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload = SamplingPayload(self.context.agent_address, *self._sample())

        yield from self.finish_behaviour(payload)
