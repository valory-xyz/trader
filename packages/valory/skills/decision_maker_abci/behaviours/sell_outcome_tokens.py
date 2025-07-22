#!/usr/bin/env python3
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


"""This module contains the behaviour for selling a token."""
from typing import Any, Generator, Optional, cast

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    QueryingBehaviour,
)


class SellOutcomeTokensBehaviour(DecisionMakerBaseBehaviour, QueryingBehaviour):
    """A behaviour in which the agents sell a token."""

    matching_round = SellOutcomeTokensRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the sell token behaviour."""
        super().__init__(**kwargs)
        self.sell_amount: int = 0

    @property
    def market_maker_contract_address(self) -> str:
        """Get the contract address of the market maker on which the service is going to place the bet."""
        return self.sampled_bet.id

    @property
    def investment_amount(self) -> int:
        """Get the investment amount of the bet."""
        return self.synchronized_data.bet_amount

    @property
    def outcome_index(self) -> int:
        """Get the index of the outcome for which the service is going to sell token."""
        return cast(int, self.synchronized_data.vote)

    @property
    def collateral_token(self) -> str:
        """Get the collateral token."""
        return self.sampled_bet.collateralToken

    def _build_approval_tx(self) -> WaitableConditionType:
        """Build an ERC20 approve transaction."""
        status = yield from self.build_approval_tx(
            self.return_amount,
            self.market_maker_contract_address,
            self.collateral_token,
        )
        return status

    def _prepare_safe_tx(self) -> Generator[None, None, Optional[str]]:
        """Prepare the safe transaction for selling an outcome token and return the hex for the tx settlement skill."""
        yield from self.wait_for_condition_with_sleep(self._build_approval_tx)

        # based on past observations, the buy amount calculation usually fails because of the RPC misbehaving
        # if this happens, we do not want to retry as it won't get resolved soon. Instead, we exit this round.
        calculation_succeeded = yield from self._calc_sell_amount()
        if not calculation_succeeded:
            return None

        for step in (
            self._build_sell_tx,
            self._build_multisend_data,
            self._build_multisend_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        outcome = self.sampled_bet.get_outcome(self.outcome_index)
        investment = self._collateral_amount_info(self.return_amount)
        self.context.logger.info(
            f"Preparing a multisig transaction to sell the outcome token for {outcome!r}, with confidence "
            f"{self.synchronized_data.confidence!r}, for the amount of {investment}, which is equal to the amount of "
            f"{self.sell_amount!r} WEI of the conditional token corresponding to {outcome!r}."
        )

        return self.tx_hex

    @property
    def return_amount(self) -> int:
        """Get the return amount."""
        return self.sampled_bet.get_vote_amount(self.outcome_index)

    def async_act(self) -> Generator:
        """Do the action."""

        agent = self.context.agent_address

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self.update_sell_transaction_information()
            mocking_mode = None

            self.context.logger.info(
                "Preparing a multisig transaction to sell the outcome token"
            )

            tx_submitter = self.matching_round.auto_round_id()
            tx_hex = yield from self._prepare_safe_tx()
            self.context.logger.info("Finished preparing the safe transaction")

            payload = MultisigTxPayload(agent, tx_submitter, tx_hex, mocking_mode)

        yield from self.finish_behaviour(payload)
