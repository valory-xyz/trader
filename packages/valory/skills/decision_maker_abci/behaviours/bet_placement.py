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

"""This module contains the behaviour for sampling a bet."""

from typing import Any, Generator, Optional

from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WXDAI,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import BetPlacementPayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)


class BetPlacementBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = BetPlacementRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    @property
    def w_xdai_deficit(self) -> int:
        """Get the amount of missing wxDAI for placing the bet."""
        return self.investment_amount - self.token_balance

    def _build_exchange_tx(self) -> WaitableConditionType:
        """Exchange xDAI to wxDAI."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=WXDAI,
            contract_id=str(ERC20.contract_id),
            contract_callable="build_deposit_tx",
            chain_id=self.params.mech_chain_id,
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
        return self.build_approval_tx(
            amount=self.investment_amount,
            spender=self.market_maker_contract_address,
            token=self.collateral_token,
        )

    def _prepare_safe_tx(self) -> Generator[None, None, Optional[str]]:
        """Prepare the safe transaction for placing a bet and return the hex for the tx settlement skill."""
        yield from self.wait_for_condition_with_sleep(self._build_approval_tx)

        # based on past observations, the buy amount calculation usually fails because of the RPC misbehaving
        # if this happens, we do not want to retry as it won't get resolved soon. Instead, we exit this round.
        calculation_succeeded = yield from self._calc_buy_amount()
        if not calculation_succeeded:
            return None

        for step in (
            self._build_buy_tx,
            self._build_multisend_data,
            self._build_multisend_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        outcome = self.sampled_bet.get_outcome(self.outcome_index)
        investment = self._collateral_amount_info(self.investment_amount)
        self.context.logger.info(
            f"Preparing a multisig transaction to place a bet for {outcome!r}, with confidence "
            f"{self.synchronized_data.confidence!r}, for the amount of {investment}, which is equal to the amount of "
            f"{self.buy_amount!r} WEI of the conditional token corresponding to {outcome!r}."
        )

        return self.tx_hex

    def async_act(self) -> Generator:
        """Do the action."""
        agent = self.context.agent_address

        if self.benchmarking_mode.enabled:
            # simulate the bet placement
            with self.context.benchmark_tool.measure(self.behaviour_id).local():
                self.update_bet_transaction_information()
                payload = BetPlacementPayload(
                    agent, None, None, True, self.wallet_balance
                )
            yield from self.finish_behaviour(payload)

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self.wait_for_condition_with_sleep(self.check_balance)
            tx_submitter = betting_tx_hex = mocking_mode = wallet_balance = None

            can_exchange = (
                self.is_wxdai
                # no need to take fees into consideration because it is the safe's balance and the agents pay the fees
                and self.wallet_balance >= self.w_xdai_deficit
            )
            if self.token_balance < self.investment_amount and can_exchange:
                yield from self.wait_for_condition_with_sleep(self._build_exchange_tx)

            if self.token_balance >= self.investment_amount or can_exchange:
                tx_submitter = self.matching_round.auto_round_id()
                betting_tx_hex = yield from self._prepare_safe_tx()
                wallet_balance = self.wallet_balance

            payload = BetPlacementPayload(
                agent,
                tx_submitter,
                betting_tx_hex,
                mocking_mode,
                wallet_balance,
            )

        yield from self.finish_behaviour(payload)
