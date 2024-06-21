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
from packages.valory.skills.market_manager_abci.bets import BetStatus


TX_COST_APPROX = int(1e15)


class BlacklistingBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = BlacklistingRound

    @property
    def synced_time(self) -> float:
        """Get the synchronized time among agents."""
        synced_time = self.shared_state.round_sequence.last_round_transition_timestamp
        return synced_time.timestamp()

    def _blacklist(self) -> None:
        """Update the policy and blacklist the sampled bet."""
        # calculate the penalty
        if self.synchronized_data.is_mech_price_set:
            # impose a penalty equivalent to the mech's price on the tool responsible for blacklisting the market
            penalty_wei = self.synchronized_data.mech_price
        elif self.benchmarking_mode.enabled:
            # penalize using the simulated mech's cost
            penalty_wei = self.benchmarking_mode.mech_cost
        else:
            # if the price has not been set or a nevermined subscription is used, penalize using a small amount,
            # approximating the cost of a transaction
            penalty_wei = -TX_COST_APPROX

        # update the policy to penalize the most recently utilized mech tool
        tool_idx = self.synchronized_data.mech_tool_idx
        penalty = -self.wei_to_native(penalty_wei)
        penalty *= self.params.tool_punishment_multiplier
        self.policy.add_reward(tool_idx, penalty)

        if self.benchmarking_mode.enabled:
            # skip blacklisting the market as we should be based solely on the input data of the simulation
            return

        # blacklist the sampled bet
        sampled_bet_index = self.synchronized_data.sampled_bet_index
        sampled_bet = self.bets[sampled_bet_index]
        sampled_bet.status = BetStatus.BLACKLISTED
        blacklist_expiration = self.synced_time + self.params.blacklisting_duration
        sampled_bet.blacklist_expiration = blacklist_expiration

    def setup(self) -> None:
        """Setup the behaviour"""
        self._policy = self.synchronized_data.policy
        self._acc_policy = self.synchronized_data.acc_policy

    def async_act(self) -> Generator:
        """Do the action."""
        # if the tool selection has not been run for the current period, do not do anything
        if not self.synchronized_data.has_tool_selection_run:
            policy = self.policy.serialize()
            acc_policy = self.acc_policy.serialize()
            payload = BlacklistingPayload(
                self.context.agent_address, None, policy, acc_policy
            )
            yield from self.finish_behaviour(payload)

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self.read_bets()
            self._blacklist()
            self.store_bets()
            bets_hash = (
                None if self.benchmarking_mode.enabled else self.hash_stored_bets()
            )
            policy = self.policy.serialize()
            acc_policy = self.acc_policy.serialize()
            payload = BlacklistingPayload(
                self.context.agent_address, bets_hash, policy, acc_policy
            )

        yield from self.finish_behaviour(payload)
