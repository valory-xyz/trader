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

"""This module contains the behaviour for the blacklisting of the sampled bet."""

from typing import Generator, Optional

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.rounds import BlacklistingRound
from packages.valory.skills.market_manager_abci.bets import BetStatus, serialize_bets
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload


class BlacklistingBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = BlacklistingRound

    @property
    def synced_time(self) -> float:
        """Get the synchronized time among agents."""
        synced_time = self.shared_state.round_sequence.last_round_transition_timestamp
        return synced_time.timestamp()

    def _blacklist(self) -> Optional[str]:
        """Blacklist the sampled bet and return the updated version of the bets, serialized."""
        bets = self.synchronized_data.bets
        sampled_bet_id = self.synchronized_data.sampled_bet_id
        sampled_bet = bets[sampled_bet_id]
        sampled_bet.status = BetStatus.BLACKLISTED
        blacklist_expiration = self.synced_time + self.params.blacklisting_duration
        sampled_bet.blacklist_expiration = blacklist_expiration

        return serialize_bets(bets)

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload = UpdateBetsPayload(self.context.agent_address, self._blacklist())

        yield from self.finish_behaviour(payload)
