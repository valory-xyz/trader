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

"""This module contains the behaviour for sampling a bet."""

from datetime import datetime, timedelta
from typing import Any, Callable, Generator, Optional, cast

from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.contracts.market_maker.contract import (
    FixedProductMarketMakerContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import TimeoutException
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import BetPlacementPayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


# setting the safe gas to 0 means that all available gas will be used
# which is what we want in most cases
# more info here: https://safe-docs.dev.gnosisdev.com/safe/docs/contracts_tx_execution/
_SAFE_GAS = 0
# hardcoded to 0 because we don't need to send any ETH when betting
_ETHER_VALUE = 0


class BetPlacementBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = BetPlacementRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0
        self.buy_data = b""
        self.safe_tx_hash = ""

    @property
    def market_maker_contract_address(self) -> str:
        """Get the contract address of the market maker on which the service is going to place the bet."""
        return self.synchronized_data.sampled_bet.id

    @property
    def investment_amount(self) -> int:
        """Get the investment amount of the bet."""
        return self.params.get_bet_amount(self.synchronized_data.confidence)

    @property
    def outcome_index(self) -> int:
        """Get the index of the outcome that the service is going to place a bet on."""
        return cast(int, self.synchronized_data.vote)

    def _calc_buy_amount(self) -> Generator[None, None, bool]:
        """Calculate the buy amount of the conditional token."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.market_maker_contract_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="calc_buy_amount",
            investment_amount=self.investment_amount,
            outcome_index=self.outcome_index,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not calculate the buy amount: {response_msg}"
            )
            return False

        buy_amount = response_msg.raw_transaction.body.get("amount", None)
        if buy_amount is None:
            self.context.logger.error(
                f"Something went wrong while trying to get the buy amount for the conditional token: {response_msg}"
            )
            return False

        self.buy_amount = buy_amount
        return True

    def _build_buy_data(self) -> Generator[None, None, bool]:
        """Get the buy tx data encoded."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.market_maker_contract_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="get_buy_data",
            investment_amount=self.investment_amount,
            outcome_index=self.outcome_index,
            min_outcome_tokens_to_buy=self.buy_amount,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not get the data for the buy transaction: {response_msg}"
            )
            return False

        buy_data = response_msg.raw_transaction.body.get("data", None)
        if buy_data is None:
            self.context.logger.error(
                "Something went wrong while trying to encode the buy data."
            )
            return False

        self.buy_data = buy_data
        return True

    def _build_safe_tx_hash(self) -> Generator[None, None, bool]:
        """Prepares and returns the safe tx hash."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=self.market_maker_contract_address,
            value=_ETHER_VALUE,
            data=self.buy_data,
            safe_tx_gas=_SAFE_GAS,
        )

        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                "Couldn't get safe tx hash. Expected response performative "
                f"{ContractApiMessage.Performative.RAW_TRANSACTION.value}, received {response_msg}."  # type: ignore
            )
            return False

        tx_hash = response_msg.raw_transaction.body.get("tx_hash", None)
        if tx_hash is None or len(tx_hash) != TX_HASH_LENGTH:
            self.context.logger.error(
                "Something went wrong while trying to get the buy transaction's hash. "
                f"Invalid hash {tx_hash!r} was returned."
            )
            return False

        # strip "0x" from the response hash
        self.safe_tx_hash = tx_hash[2:]
        return True

    def wait_for_condition_with_sleep(
        self,
        condition_gen: Callable[[], Generator[None, None, bool]],
        timeout: Optional[float] = None,
    ) -> Generator[None, None, None]:
        """Wait for a condition to happen and sleep in-between checks.

        This is a modified version of the base `wait_for_condition` method which:
            1. accepts a generator that creates the condition instead of a callable
            2. sleeps in-between checks

        :param condition_gen: a generator of the condition to wait for
        :param timeout: the maximum amount of time to wait
        :yield: None
        """

        deadline = (
            datetime.now() + timedelta(0, timeout)
            if timeout is not None
            else datetime.max
        )

        while True:
            condition_satisfied = yield from condition_gen()
            if condition_satisfied:
                break
            if timeout is not None and datetime.now() > deadline:
                raise TimeoutException()
            self.context.logger.error(f"Retrying in {self.params.sleep_time} seconds.")
            yield from self.sleep(self.params.sleep_time)

    def _prepare_safe_tx(self) -> Generator[None, None, str]:
        """Prepare the safe transaction for placing a bet and return the hex for the tx settlement skill."""
        for step in (
            self._calc_buy_amount,
            self._build_buy_data,
            self._build_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        return hash_payload_to_hex(
            self.safe_tx_hash,
            _ETHER_VALUE,
            _SAFE_GAS,
            self.market_maker_contract_address,
            self.buy_data,
        )

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            betting_tx_hex = yield from self._prepare_safe_tx()
            payload = BetPlacementPayload(self.context.agent_address, betting_tx_hex)

        yield from self.finish_behaviour(payload)
