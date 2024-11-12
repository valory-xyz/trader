#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.market_maker.contract import (
    FixedProductMarketMakerContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WXDAI,
    WaitableConditionType,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload


class SellTokenBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents sell a token."""

    # matching_round = SellTokenRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the sell token behaviour."""
        super().__init__(**kwargs)
        self.sell_amount = 0

    @property
    def market_maker_contract_address(self) -> str:
        """Get the contract address of the market maker on which the service is going to place the bet."""
        return self.sampled_bet.id

    @property
    def return_amount(self) -> int:
        """Get the return amount of the bet."""
        # TODO:
        #   this will need to be the amount that we have previously bet on an outcome
        return self.synchronized_data.bet_amount

    @property
    def outcome_index(self) -> int:
        """Get the index of the outcome for which the service is going to sell token."""
        return cast(int, self.synchronized_data.vote)

    def check_outcome_token_balance(self) -> WaitableConditionType:
        """Check the safe's balance for a particular outcome token."""

    def _build_exchange_tx(self) -> WaitableConditionType:
        """Exchange xDAI to wxDAI."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=WXDAI,
            contract_id=str(ERC20.contract_id),
            contract_callable="build_deposit_tx",
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.info(f"Could not build deposit tx: {response_msg}")
            return False

        approval_data = response_msg.state.body.get("data")
        if approval_data is None:
            self.context.logger.info(f"Could not build deposit tx: {response_msg}")
            return False

        batch = MultisendBatch(
            to=self.collateral_token,
            data=HexBytes(approval_data),
            value=self.w_xdai_deficit,
        )
        self.multisend_batches.append(batch)
        return True

    def _build_approval_tx(self) -> WaitableConditionType:
        """Build an ERC20 approve transaction."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.collateral_token,
            contract_id=str(ERC20.contract_id),
            contract_callable="build_approval_tx",
            spender=self.market_maker_contract_address,
            amount=self.return_amount,
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.info(f"Could not build approval tx: {response_msg}")
            return False

        approval_data = response_msg.state.body.get("data")
        if approval_data is None:
            self.context.logger.info(f"Could not build approval tx: {response_msg}")
            return False

        batch = MultisendBatch(
            to=self.market_maker_contract_address,
            data=HexBytes(approval_data),
        )
        self.multisend_batches.append(batch)
        return True

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

        # TODO: not sure this is the correct use of remove_fraction_wei, is sell amount in wxDAI?
        self.sell_amount = remove_fraction_wei(sell_amount, self.params.slippage)
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

            # TODO: there should be some kind of check here to verify the amount being sold is not more than the
            #  previously bought amount
            #  this needs to call balanceOf on the ERC20 contract
            #  use conditionaltokenaddress
            self.check_outcome_token_balance()

            if self.is_wxdai:
                tx_submitter = self.matching_round.auto_round_id()
                betting_tx_hex = yield from self._prepare_safe_tx()

            payload = MultisigTxPayload(
                agent, tx_submitter, betting_tx_hex, mocking_mode
            )

        yield from self.finish_behaviour(payload)
