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

"""This module contains the base behaviour for the 'decision_maker_abci' skill."""

import dataclasses
from abc import ABC
from datetime import datetime, timedelta
from typing import Any, Callable, Generator, List, Optional, cast

from aea.configurations.data_types import PublicId

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.mech.contract import Mech
from packages.valory.contracts.multisend.contract import MultiSendContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    BaseBehaviour,
    TimeoutException,
)
from packages.valory.skills.decision_maker_abci.models import (
    DecisionMakerParams,
    MultisendBatch,
    SharedState,
)
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


WaitableConditionType = Generator[None, None, bool]


# setting the safe gas to 0 means that all available gas will be used
# which is what we want in most cases
# more info here: https://safe-docs.dev.gnosisdev.com/safe/docs/contracts_tx_execution/
SAFE_GAS = 0
CID_PREFIX = "f01701220"
WXDAI = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"


def remove_fraction_wei(amount: int, fraction: float) -> int:
    """Removes the given fraction from the given integer amount and returns the value as an integer."""
    if 0 <= fraction <= 1:
        keep_percentage = 1 - fraction
        return int(amount * keep_percentage)
    raise ValueError(f"The given fraction {fraction!r} is not in the range [0, 1].")


class DecisionMakerBaseBehaviour(BaseBehaviour, ABC):
    """Represents the base class for the decision-making FSM behaviour."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.token_balance = 0
        self.wallet_balance = 0
        self.multisend_batches: List[MultisendBatch] = []
        self.multisend_data = b""
        self._safe_tx_hash = ""
        self._policy: Optional[EGreedyPolicy] = None

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    @property
    def shared_state(self) -> SharedState:
        """Get the shared state."""
        return cast(SharedState, self.context.state)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(self.round_sequence.last_round_transition_timestamp.timestamp())

    @property
    def safe_tx_hash(self) -> str:
        """Get the safe_tx_hash."""
        return self._safe_tx_hash

    @safe_tx_hash.setter
    def safe_tx_hash(self, safe_hash: str) -> None:
        """Set the safe_tx_hash."""
        length = len(safe_hash)
        if length != TX_HASH_LENGTH:
            raise ValueError(
                f"Incorrect length {length} != {TX_HASH_LENGTH} detected "
                f"when trying to assign a safe transaction hash: {safe_hash}"
            )
        self._safe_tx_hash = safe_hash[2:]

    @property
    def multi_send_txs(self) -> List[dict]:
        """Get the multisend transactions as a list of dictionaries."""
        return [dataclasses.asdict(batch) for batch in self.multisend_batches]

    @property
    def txs_value(self) -> int:
        """Get the total value of the transactions."""
        return sum(batch.value for batch in self.multisend_batches)

    @property
    def tx_hex(self) -> Optional[str]:
        """Serialize the safe tx to a hex string."""
        if self.safe_tx_hash == "":
            self.context.logger.error(
                "Cannot prepare a transaction without a transaction hash."
            )
            return None
        return hash_payload_to_hex(
            self.safe_tx_hash,
            self.txs_value,
            SAFE_GAS,
            self.params.multisend_address,
            self.multisend_data,
            SafeOperation.DELEGATE_CALL.value,
        )

    @property
    def policy(self) -> EGreedyPolicy:
        """Get the policy."""
        if self._policy is None:
            raise ValueError(
                "Attempting to retrieve the policy before it has been established."
            )
        return self._policy

    @property
    def is_first_period(self) -> bool:
        """Return whether it is the first period of the service."""
        return self.synchronized_data.period_count == 0

    @property
    def collateral_token(self) -> str:
        """Get the contract address of the token that the market maker supports."""
        return self.synchronized_data.sampled_bet.collateralToken

    @property
    def is_wxdai(self) -> bool:
        """Get whether the collateral address is wxDAI."""
        return self.collateral_token.lower() == WXDAI.lower()

    @staticmethod
    def wei_to_native(wei: int) -> float:
        """Convert WEI to native token."""
        return wei / 10**18

    def _collateral_amount_info(self, amount: int) -> str:
        """Get a description of the collateral token's amount."""
        return (
            f"{self.wei_to_native(amount)} wxDAI"
            if self.is_wxdai
            else f"{amount} WEI of the collateral token with address {self.collateral_token}"
        )

    def check_balance(self) -> WaitableConditionType:
        """Check the safe's balance."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.collateral_token,
            contract_id=str(ERC20.contract_id),
            contract_callable="check_balance",
            account=self.synchronized_data.safe_contract_address,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not calculate the balance of the safe: {response_msg}"
            )
            return False

        token = response_msg.raw_transaction.body.get("token", None)
        wallet = response_msg.raw_transaction.body.get("wallet", None)
        if token is None or wallet is None:
            self.context.logger.error(
                f"Something went wrong while trying to get the balance of the safe: {response_msg}"
            )
            return False

        self.token_balance = int(token)
        self.wallet_balance = int(wallet)

        native = self.wei_to_native(self.wallet_balance)
        collateral = self._collateral_amount_info(self.token_balance)
        self.context.logger.info(f"The safe has {native} xDAI and {collateral}.")
        return True

    def _calculate_kelly_bet_amount(
        self, x: int, y: int, p: float, c: float, b: int, f: float
    ) -> int:
        """Calculate the Kelly bet amount."""
        if b == 0 or x**2 * f == y**2 * f:
            self.context.logger.error(
                "Could not calculate Kelly bet amount. "
                "Either bankroll is 0 or pool token amount is distributed as x^2*f - y^2*f = 0:\n"
                f"Bankroll: {b}\n"
                f"Pool token amounts: {x}, {y}"
                f"Fee, fee fraction f: {1-f}, {f}"
            )
            return 0
        kelly_bet_amount = (
            -4 * x**2 * y
            + b * y**2 * p * c * f
            + 2 * b * x * y * p * c * f
            + b * x**2 * p * c * f
            - 2 * b * y**2 * f
            - 2 * b * x * y * f
            + (
                (
                    4 * x**2 * y
                    - b * y**2 * p * c * f
                    - 2 * b * x * y * p * c * f
                    - b * x**2 * p * c * f
                    + 2 * b * y**2 * f
                    + 2 * b * x * y * f
                )
                ** 2
                - (
                    4
                    * (x**2 * f - y**2 * f)
                    * (
                        -4 * b * x * y**2 * p * c
                        - 4 * b * x**2 * y * p * c
                        + 4 * b * x * y**2
                    )
                )
            )
            ** (1 / 2)
        ) / (2 * (x**2 * f - y**2 * f))
        return int(kelly_bet_amount)

    def get_max_bet_amount(self, a: int, x: int, y: int, f: float) -> int:
        """Get max bet amount based on available shares."""
        if x**2 * f**2 + 2 * x * y * f**2 + y**2 * f**2 == 0:
            self.context.logger.error(
                "Could not recalculate. "
                "Either bankroll is 0 or pool token amount is distributed such as "
                "x**2*f**2 + 2*x*y*f**2 + y**2*f**2 == 0:\n"
                f"Available tokens: {a}\n"
                f"Pool token amounts: {x}, {y}\n"
                f"Fee, fee fraction f: {1-f}, {f}"
            )
            return 0
        else:
            pre_root = -2 * x**2 + a * x - 2 * x * y
            sqrt = (
                4 * x**4
                + 8 * x**3 * y
                + a**2 * x**2
                + 4 * x**2 * y**2
                + 2 * a**2 * x * y
                + a**2 * y**2
            )
            numerator = y * (pre_root + sqrt**0.5 + a * y)
            denominator = f * (x**2 + 2 * x * y + y**2)
            new_bet_amount = numerator / denominator
            return int(new_bet_amount)

    def get_bet_amount(
        self,
        strategy: str,
        win_probability: float,
        confidence: float,
        selected_type_tokens_in_pool: int,
        other_tokens_in_pool: int,
        bet_fee: int,
    ) -> Generator[None, None, int]:
        """Get the bet amount given a specified trading strategy."""

        if strategy == "bet_amount_per_conf_threshold":
            self.context.logger.info(
                "Used trading strategy: Bet amount per confidence threshold"
            )
            threshold = round(confidence, 1)
            bet_amount = self.params.bet_amount_per_threshold[threshold]
            return bet_amount

        if strategy != "kelly_criterion":
            raise ValueError(f"Invalid trading strategy: {strategy}")

        self.context.logger.info("Used trading strategy: Kelly Criterion")
        # bankroll: the max amount of DAI available to trade
        yield from self.wait_for_condition_with_sleep(self.check_balance)
        bankroll = self.token_balance + self.wallet_balance
        # keep `floor_balance` xDAI in the bankroll
        floor_balance = 500000000000000000
        bankroll_adj = bankroll - floor_balance
        self.context.logger.info(f"Adjusted bankroll: {bankroll_adj} DAI")
        if bankroll_adj <= 0:
            self.context.logger.info(
                f"Bankroll ({bankroll_adj}) is less than the floor balance ({floor_balance}). "
                "Set bet amount to 0."
                "Top up safe with DAI or wait for redeeming."
            )
            return 0

        fee_fraction = 1 - self.wei_to_native(bet_fee)
        self.context.logger.info(f"Fee fraction: {fee_fraction}")
        kelly_bet_amount = self._calculate_kelly_bet_amount(
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            win_probability,
            confidence,
            bankroll_adj,
            fee_fraction,
        )
        if kelly_bet_amount < 0:
            self.context.logger.info(
                f"Invalid value for kelly bet amount: {kelly_bet_amount}\n"
                "Set bet amount to 0."
            )
            return 0

        self.context.logger.info(
            f"Kelly bet amount: {self.wei_to_native(kelly_bet_amount)} xDAI"
        )
        self.context.logger.info(
            f"Bet kelly fraction: {self.params.bet_kelly_fraction}"
        )
        adj_kelly_bet_amount = int(kelly_bet_amount * self.params.bet_kelly_fraction)
        self.context.logger.info(
            f"Adjusted Kelly bet amount: {self.wei_to_native(adj_kelly_bet_amount)} xDAI"
        )
        return adj_kelly_bet_amount

    def default_error(
        self, contract_id: str, contract_callable: str, response_msg: ContractApiMessage
    ) -> None:
        """Return a default contract interaction error message."""
        self.context.logger.error(
            f"Could not successfully interact with the {contract_id} contract "
            f"using {contract_callable!r}: {response_msg}"
        )

    def _propagate_contract_messages(self, response_msg: ContractApiMessage) -> None:
        """Propagate the contract's message to the logger, if exists.

        Contracts can only return one message at a time.

        :param response_msg: the response message from the contract method.
        :return: None
        """
        for level in ("info", "warning", "error"):
            msg = response_msg.raw_transaction.body.get(level, None)
            if msg is not None:
                logger = getattr(self.context.logger, level)
                logger(msg)
                return

    def contract_interact(
        self,
        performative: ContractApiMessage.Performative,
        contract_address: str,
        contract_public_id: PublicId,
        contract_callable: str,
        data_key: str,
        placeholder: str,
        **kwargs: Any,
    ) -> WaitableConditionType:
        """Interact with a contract."""
        contract_id = str(contract_public_id)
        response_msg = yield from self.get_contract_api_response(
            performative,
            contract_address,
            contract_id,
            contract_callable,
            **kwargs,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.default_error(contract_id, contract_callable, response_msg)
            return False

        self._propagate_contract_messages(response_msg)

        data = response_msg.raw_transaction.body.get(data_key, None)
        if data is None:
            self.default_error(contract_id, contract_callable, response_msg)
            return False

        setattr(self, placeholder, data)
        return True

    def _mech_contract_interact(
        self, contract_callable: str, data_key: str, placeholder: str, **kwargs: Any
    ) -> WaitableConditionType:
        """Interact with the mech contract."""
        status = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.mech_agent_address,
            contract_public_id=Mech.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _build_multisend_data(
        self,
    ) -> WaitableConditionType:
        """Get the multisend tx."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.multisend_address,
            contract_id=str(MultiSendContract.contract_id),
            contract_callable="get_tx_data",
            multi_send_txs=self.multi_send_txs,
        )
        expected_performative = ContractApiMessage.Performative.RAW_TRANSACTION
        if response_msg.performative != expected_performative:
            self.context.logger.error(
                f"Couldn't compile the multisend tx. "
                f"Expected response performative {expected_performative.value}, "  # type: ignore
                f"received {response_msg.performative.value}: {response_msg}"
            )
            return False

        multisend_data_str = response_msg.raw_transaction.body.get("data", None)
        if multisend_data_str is None:
            self.context.logger.error(
                f"Something went wrong while trying to prepare the multisend data: {response_msg}"
            )
            return False

        # strip "0x" from the response
        multisend_data_str = str(response_msg.raw_transaction.body["data"])[2:]
        self.multisend_data = bytes.fromhex(multisend_data_str)
        return True

    def _build_multisend_safe_tx_hash(self) -> WaitableConditionType:
        """Prepares and returns the safe tx hash for a multisend tx."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=self.params.multisend_address,
            value=self.txs_value,
            data=self.multisend_data,
            safe_tx_gas=SAFE_GAS,
            operation=SafeOperation.DELEGATE_CALL.value,
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                "Couldn't get safe tx hash. Expected response performative "
                f"{ContractApiMessage.Performative.STATE.value}, "  # type: ignore
                f"received {response_msg.performative.value}: {response_msg}."
            )
            return False

        tx_hash = response_msg.state.body.get("tx_hash", None)
        if tx_hash is None or len(tx_hash) != TX_HASH_LENGTH:
            self.context.logger.error(
                "Something went wrong while trying to get the buy transaction's hash. "
                f"Invalid hash {tx_hash!r} was returned."
            )
            return False

        # strip "0x" from the response hash
        self.safe_tx_hash = tx_hash
        return True

    def wait_for_condition_with_sleep(
        self,
        condition_gen: Callable[[], WaitableConditionType],
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
            self.context.logger.info(f"Retrying in {self.params.sleep_time} seconds.")
            yield from self.sleep(self.params.sleep_time)

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
