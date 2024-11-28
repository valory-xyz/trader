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

"""This module contains the behaviour for the blacklisting of the sampled bet."""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import BlacklistingPayload
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)


class BlacklistingBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = BlacklistingRound

    @property
    def synced_time(self) -> float:
        """Get the synchronized time among agents."""
        synced_time = self.shared_state.round_sequence.last_round_transition_timestamp
        return synced_time.timestamp()

    def _blacklist(self) -> None:
        """Blacklist the sampled bet."""
        sampled_bet_index = self.synchronized_data.sampled_bet_index
        sampled_bet = self.bets[sampled_bet_index]
        # the question is blacklisted, i.e., we did not place a bet on it,
        # therefore, we decrease the number of bets which was increased on sampling
        sampled_bet.n_bets -= 1

    def setup(self) -> None:
        """Setup the behaviour"""
        self._policy = self.synchronized_data.policy

    def async_act(self) -> Generator:
        """Do the action."""
        # if the tool selection has not been run for the current period, do not do anything
        if not self.synchronized_data.has_tool_selection_run:
            policy = self.policy.serialize()
            payload = BlacklistingPayload(self.context.agent_address, None, policy)
            yield from self.finish_behaviour(payload)

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self.read_bets()
            self._blacklist()
            self.store_bets()
            bets_hash = (
                None if self.benchmarking_mode.enabled else self.hash_stored_bets()
            )
            policy = self.policy.serialize()
            payload = BlacklistingPayload(self.context.agent_address, bets_hash, policy)

        yield from self.finish_behaviour(payload)
