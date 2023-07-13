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

from typing import Generator, Iterator, Optional

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

    @property
    def sampled_bet_idx(self) -> int:
        """
        Sample a bet and return its id.

        The sampling logic is relatively simple at the moment
        It simply selects the unprocessed bet with the largest liquidity.

        :return: the id of the sampled bet.
        """
        max_lq = max(self.available_bets, key=lambda bet: bet.usdLiquidityMeasure)
        return self.synchronized_data.bets.index(max_lq)

    def set_processed(self, idx: int) -> Optional[str]:
        """Update the bet's status for the given id to `PROCESSED`, and return the updated bets list, serialized."""
        bets = self.synchronized_data.bets
        bets[idx].status = BetStatus.PROCESSED
        return serialize_bets(bets)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            idx = self.sampled_bet_idx
            bets = self.set_processed(idx)
            payload = SamplingPayload(self.context.agent_address, bets, idx)

        yield from self.finish_behaviour(payload)
