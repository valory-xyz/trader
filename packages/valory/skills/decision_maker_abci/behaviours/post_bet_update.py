# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""This module contains the behaviour for the post-bet update round."""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PostBetUpdatePayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.post_bet_update import (
    PostBetUpdateRound,
)
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)


class PostBetUpdateBehaviour(DecisionMakerBaseBehaviour):
    """Run local-state bookkeeping after an Omen bet/sell tx settles.

    The legacy design used `RedeemBehaviour.async_act` as the
    post-tx-settlement hook for `BetPlacementRound` and
    `SellOutcomeTokensRound`. Under the always-redeem-first FSM
    restructure, redemption no longer runs after the bet, so this
    dedicated round provides the same hook: it dispatches to
    `update_bet_transaction_information` or
    `update_sell_transaction_information` based on the `tx_submitter`,
    then advances the round so the cycle can continue to the staking
    checkpoint.
    """

    matching_round = PostBetUpdateRound

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_submitter = self.synchronized_data.tx_submitter
            if tx_submitter == BetPlacementRound.auto_round_id():
                self.context.logger.info(
                    "Running post-bet bookkeeping after BetPlacementRound."
                )
                self.update_bet_transaction_information()
            elif tx_submitter == SellOutcomeTokensRound.auto_round_id():
                self.context.logger.info(
                    "Running post-sell bookkeeping after SellOutcomeTokensRound."
                )
                self.update_sell_transaction_information()
            else:
                self.context.logger.warning(
                    f"PostBetUpdateRound reached with unexpected "
                    f"tx_submitter={tx_submitter!r}; skipping bookkeeping."
                )

            payload = PostBetUpdatePayload(sender=self.context.agent_address, vote=True)

        yield from self.finish_behaviour(payload)
