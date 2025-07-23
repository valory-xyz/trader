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

"""This module contains the behaviour for handling failed transactions."""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import HandleFailedTxPayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.mech_interact_abci.states.request import MechRequestRound


class HandleFailedTxBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents handle a failed transaction."""

    matching_round = HandleFailedTxRound

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            after_bet_attempt = self.synchronized_data.tx_submitter in (
                MechRequestRound.auto_round_id(),
                BetPlacementRound.auto_round_id(),
                SellOutcomeTokensRound.auto_round_id(),
            )
            submitter = HandleFailedTxRound.auto_round_id()
            payload = HandleFailedTxPayload(
                self.context.agent_address, after_bet_attempt, submitter
            )

        yield from self.finish_behaviour(payload)
