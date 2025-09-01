# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the behaviour for preparing a sell from called from sampling."""

from typing import Any, Generator, Optional

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PrepareSellPayload
from packages.valory.skills.decision_maker_abci.states.prepare_sell import (
    PrepareSellRound,
)


class PrepareSellBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents prepare a tx to sell the outcome tokens."""

    matching_round = PrepareSellRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the prepare sell behaviour."""
        super().__init__(**kwargs)

    @property
    def vote(self) -> Optional[int]:
        """Get the vote."""

        bet = self.sampled_bet
        self.context.logger.debug(f"Bet: {bet}")
        self.context.logger.debug(f"Bet.prediction_response: {bet.prediction_response}")
        self.context.logger.debug(f"Vote: {bet.vote}")
        return bet.vote

    def async_act(self) -> Generator:
        """Do the action."""
        vote = bet_amount = None

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            if self.vote is not None:
                vote = self.vote
                is_a_no = vote == 0
                outcome = self.sampled_bet.no if is_a_no else self.sampled_bet.yes
                bet = self.sampled_bet
                self.context.logger.debug(f"Outcome: {outcome}")
                self.context.logger.debug(f"Bet.investments: {bet.investments}")
                bet_amount = sum(bet.investments.get(outcome, []))
                self.context.logger.debug(f"Bet amount: {bet_amount}")
                # bet amount here is incorrect and should be a collateral amount
                vote = bool(vote)

            payload = PrepareSellPayload(
                self.context.agent_address,
                vote,
                bet_amount,
            )

        yield from self.finish_behaviour(payload)
