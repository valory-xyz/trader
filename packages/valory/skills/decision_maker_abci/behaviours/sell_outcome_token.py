#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

from hexbytes import HexBytes

from packages.valory.contracts.market_maker.contract import (
    FixedProductMarketMakerContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload
from packages.valory.skills.decision_maker_abci.states.sell_outcome_token import (
    SellOutcomeTokenRound,
)


class SellTokenBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents sell a token."""

    matching_round = SellOutcomeTokenRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the sell token behaviour."""
        super().__init__(**kwargs)
        self.sell_amount: float = 0.0

    @property
    def market_maker_contract_address(self) -> str:
        """Get the contract address of the market maker on which the service is going to place the bet."""
        return self.sampled_bet.id

    @property
    def outcome_index(self) -> int:
        """Get the index of the outcome for which the service is going to sell token."""
        return cast(int, self.synchronized_data.previous_vote)

    @property
    def return_amount(self) -> int:
        """Get the amount expected to be returned after the sell tx."""
        previous_vote = self.synchronized_data.previous_vote

        if previous_vote == 0:
            return self.sampled_bet.invested_amount_yes

        else:
            return self.sampled_bet.invested_amount_no

    def _build_approval_tx(self) -> WaitableConditionType:
        """Build an ERC20 approve transaction."""
        status = yield from self.build_approval_tx(
            self.return_amount,
            self.market_maker_contract_address,
            self.sampled_bet.get_outcome(self.outcome_index),
        )
        return status

    def _calc_sell_amount(self) -> WaitableConditionType:
        """Calculate the sell amount of the conditional token."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.market_maker_contract_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="calc_sell_amount",
            return_amount=self.return_amount,
            outcome_index=self.outcome_index,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not calculate the sell amount: {response_msg}"
            )
            return False

        sell_amount = response_msg.raw_transaction.body.get(
            "outcomeTokenSellAmount", None
        )
        if sell_amount is None:
            self.context.logger.error(
                f"Something went wrong while trying to get the outcomeTokenSellAmount amount for the conditional token: {response_msg}"
            )
            return False

        self.sell_amount = sell_amount
        return True

    def _build_sell_tx(self) -> WaitableConditionType:
        """Get the sell tx data encoded."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.market_maker_contract_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="get_sell_data",
            return_amount=self.return_amount,
            outcome_index=self.outcome_index,
            max_outcome_tokens_to_sell=self.sell_amount,
        )
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Could not get the data for the buy transaction: {response_msg}"
            )
            return False

        sell_data = response_msg.state.body.get("data", None)
        if sell_data is None:
            self.context.logger.error(
                f"Something went wrong while trying to encode the buy data: {response_msg}"
            )
            return False

        batch = MultisendBatch(
            to=self.market_maker_contract_address,
            data=HexBytes(sell_data),
        )
        self.multisend_batches.append(batch)
        return True

    def _prepare_safe_tx(self) -> Generator[None, None, Optional[str]]:
        """Prepare the safe transaction for selling an outcome token and return the hex for the tx settlement skill."""
        for step in (
            self._build_approval_tx,
            self._calc_sell_amount,
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

    def async_act(self) -> Generator:
        """Do the action."""

        agent = self.context.agent_address

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_submitter = betting_tx_hex = mocking_mode = None

            # if the vote is the same as the previous vote then there is no change in the supported outcome, so we
            # should not sell
            if self.synchronized_data.vote == self.synchronized_data.previous_vote:
                payload = MultisigTxPayload(
                    agent, tx_submitter, betting_tx_hex, mocking_mode
                )

                yield from self.finish_behaviour(payload)

            tx_submitter = self.matching_round.auto_round_id()
            betting_tx_hex = yield from self._prepare_safe_tx()

            payload = MultisigTxPayload(
                agent, tx_submitter, betting_tx_hex, mocking_mode
            )

        yield from self.finish_behaviour(payload)
