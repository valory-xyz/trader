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

"""This module contains the base behaviour for the 'decision_maker_abci' skill."""

import dataclasses
import json
import os
from abc import ABC
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple, cast

from aea.configurations.data_types import PublicId
from aea.protocols.base import Message
from aea.protocols.dialogue.base import Dialogue
from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.contracts.market_maker.contract import (
    FixedProductMarketMakerContract,
)
from packages.valory.contracts.mech.contract import Mech
from packages.valory.contracts.mech_mm.contract import MechMM
from packages.valory.contracts.multisend.contract import MultiSendContract
from packages.valory.contracts.transfer_nft_condition.contract import (
    TransferNftCondition,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.ipfs import IpfsMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviour_utils import TimeoutException
from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader
from packages.valory.skills.decision_maker_abci.models import (
    AccuracyInfoFields,
    BenchmarkingMockData,
    DecisionMakerParams,
    L0_END_FIELD,
    L0_START_FIELD,
    L1_END_FIELD,
    L1_START_FIELD,
    LiquidityInfo,
    MultisendBatch,
    SharedState,
)
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData
from packages.valory.skills.decision_maker_abci.utils.nevermined import (
    no_did_prefixed,
    zero_x_transformer,
)
from packages.valory.skills.market_manager_abci.behaviours import BetsManagerBehaviour
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    CONFIDENCE_FIELD,
    P_NO_FIELD,
    P_YES_FIELD,
    PredictionResponse,
)
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
BET_AMOUNT_FIELD = "bet_amount"
SUPPORTED_STRATEGY_LOG_LEVELS = ("info", "warning", "error")
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
NEW_LINE = "\n"
QUOTE = '"'
TWO_QUOTES = '""'
INIT_LIQUIDITY_INFO = LiquidityInfo()


class TradingOperation(str, Enum):
    """Trading operation."""

    BUY = "buy"
    SELL = "sell"


def remove_fraction_wei(amount: int, fraction: float) -> int:
    """Removes the given fraction from the given integer amount and returns the value as an integer."""
    if 0 <= fraction <= 1:
        keep_percentage = 1 - fraction
        return int(amount * keep_percentage)
    raise ValueError(f"The given fraction {fraction!r} is not in the range [0, 1].")


class DecisionMakerBaseBehaviour(BetsManagerBehaviour, ABC):
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
        self._inflight_strategy_req: Optional[str] = None

        self.sell_amount: int = 0
        self.buy_amount: int = 0

    @property
    def subscription_params(self) -> Dict[str, Any]:
        """Get the subscription params."""
        return self.params.mech_to_subscription_params

    @property
    def did(self) -> str:
        """Get the did."""
        subscription_params = self.subscription_params
        return subscription_params["did"]

    @property
    def token_address(self) -> str:
        """Get the token address."""
        subscription_params = self.subscription_params
        return subscription_params["token_address"]

    @property
    def market_maker_contract_address(self) -> str:
        """Get the contract address of the market maker on which the service is going to place the bet."""
        return self.sampled_bet.id

    @property
    def investment_amount(self) -> int:
        """Get the investment amount of the bet."""
        return self.synchronized_data.bet_amount

    @property
    def return_amount(self) -> int:
        """Get the return amount."""
        return self.sampled_bet.get_vote_amount(self.outcome_index)

    @property
    def outcome_index(self) -> int:
        """Get the index of the outcome that the service is going to place a bet on."""
        return cast(int, self.synchronized_data.vote)

    def strategy_exec(self, strategy: str) -> Optional[Tuple[str, str]]:
        """Get the executable strategy file's content."""
        return self.shared_state.strategies_executables.get(strategy, None)

    def execute_strategy(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Execute the strategy and return the results."""
        trading_strategy = kwargs.pop("trading_strategy", None)
        if trading_strategy is None:
            self.context.logger.error(f"No trading strategy was given in {kwargs=}!")
            return {BET_AMOUNT_FIELD: 0}

        strategy = self.strategy_exec(trading_strategy)
        if strategy is None:
            self.context.logger.error(
                f"No executable was found for {trading_strategy=}!"
            )
            return {BET_AMOUNT_FIELD: 0}

        strategy_exec, callable_method = strategy
        if callable_method in globals():
            del globals()[callable_method]

        exec(strategy_exec, globals())  # pylint: disable=W0122  # nosec
        method = globals().get(callable_method, None)
        if method is None:
            self.context.logger.error(
                f"No {callable_method!r} method was found in {trading_strategy} strategy's executable."
            )
            return {BET_AMOUNT_FIELD: 0}

        return method(*args, **kwargs)

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    @property
    def mock_data(self) -> BenchmarkingMockData:
        """Return the mock data for the benchmarking mode."""
        mock_data = self.shared_state.mock_data
        if mock_data is None:
            raise ValueError("Attempted to access the mock data while being empty!")
        return mock_data

    @property
    def acc_info_fields(self) -> AccuracyInfoFields:
        """Return the accuracy information fieldnames."""
        return cast(AccuracyInfoFields, self.context.acc_info_fields)

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
        return (
            self.synchronized_data.period_count == 0
            and not self.benchmarking_mode.enabled
            or self.shared_state.mock_data is None
        )

    @property
    def sampled_bet(self) -> Bet:
        """Get the sampled bet and reset the bets list."""
        self.read_bets()
        bet_index = self.synchronized_data.sampled_bet_index
        return self.bets[bet_index]

    @property
    def collateral_token(self) -> str:
        """Get the contract address of the token that the market maker supports."""
        return self.sampled_bet.collateralToken

    @property
    def is_wxdai(self) -> bool:
        """Get whether the collateral address is wxDAI."""
        return self.collateral_token.lower() == WXDAI.lower()

    @staticmethod
    def wei_to_native(wei: int) -> float:
        """Convert WEI to native token."""
        return wei / 10**18

    def get_active_sampled_bet(self) -> Bet:
        """Function to get the selected bet that is active without reseting self.bets."""
        bet_index = self.synchronized_data.sampled_bet_index
        if len(self.bets) == 0:
            msg = "The length of self.bets is 0"
            self.context.logger.info(msg)
            self.read_bets()

        return self.bets[bet_index]

    def _collateral_amount_info(self, amount: int) -> str:
        """Get a description of the collateral token's amount."""
        is_wxdai = True if self.benchmarking_mode.enabled else self.is_wxdai

        return (
            f"{self.wei_to_native(amount)} wxDAI"
            if is_wxdai
            else f"{amount} WEI of the collateral token with address {self.collateral_token}"
        )

    def _report_balance(self) -> None:
        """Report the balances of the native and the collateral tokens."""
        native = self.wei_to_native(self.wallet_balance)
        collateral = self._collateral_amount_info(self.token_balance)
        self.context.logger.info(f"The safe has {native} xDAI and {collateral}.")

    def _mock_balance_check(self) -> None:
        """Mock the balance of the native and the collateral tokens."""
        self.token_balance = self.benchmarking_mode.collateral_balance
        self.wallet_balance = self.benchmarking_mode.native_balance
        self._report_balance()

    def check_balance(self) -> WaitableConditionType:
        """Check the safe's balance."""
        if self.benchmarking_mode.enabled:
            self._mock_balance_check()
            return True

        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.collateral_token,
            contract_id=str(ERC20.contract_id),
            contract_callable="check_balance",
            account=self.synchronized_data.safe_contract_address,
            chain_id=self.params.mech_chain_id,
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
        self._report_balance()
        return True

    def update_bet_transaction_information(self) -> None:
        """Get whether the bet's invested amount should be updated."""
        sampled_bet = self.sampled_bet
        # Update bet transaction timestamp
        sampled_bet.processed_timestamp = self.synced_timestamp
        # Update Queue number for priority logic
        sampled_bet.queue_status = sampled_bet.queue_status.next_status()

        # Update the bet's invested amount
        updated = sampled_bet.update_investments(self.synchronized_data.bet_amount)
        if not updated:
            self.context.logger.error("Could not update the investments!")

        # the bets are stored here, but we do not update the hash in the synced db in the redeeming round
        # this will need to change if this sovereign agent is ever converted to a multi-agent service
        self.store_bets()

    def update_sell_transaction_information(self) -> None:
        """Get whether the bet's invested amount should be updated."""
        sampled_bet = self.sampled_bet
        # Update bet transaction timestamp
        sampled_bet.processed_timestamp = self.synced_timestamp
        # Update Queue number for priority logic
        sampled_bet.queue_status = sampled_bet.queue_status.next_status()

        updated = sampled_bet.update_investments(0)
        if not updated:
            self.context.logger.error("Could not update the investments!")

        # the bets are stored here, but we do not update the hash in the synced db in the redeeming round
        # this will need to change if this sovereign agent is ever converted to a multi-agent service
        self.store_bets()

    def send_message(
        self, msg: Message, dialogue: Dialogue, callback: Callable
    ) -> None:
        """Send a message."""
        self.context.outbox.put_message(message=msg)
        nonce = dialogue.dialogue_label.dialogue_reference[0]
        self.shared_state.req_to_callback[nonce] = callback
        self.shared_state.in_flight_req = True

    def _handle_get_strategy(self, message: IpfsMessage, _: Dialogue) -> None:
        """Handle get strategy response."""
        strategy_req = self._inflight_strategy_req
        if strategy_req is None:
            self.context.logger.error(f"No strategy request to handle for {message=}.")
            return

        # store the executable and remove the hash from the mapping because we have downloaded it
        _component_yaml, strategy_exec, callable_method = ComponentPackageLoader.load(
            message.files
        )

        self.shared_state.strategies_executables[strategy_req] = (
            strategy_exec,
            callable_method,
        )
        self.shared_state.strategy_to_filehash.pop(strategy_req)
        self._inflight_strategy_req = None

    def download_next_strategy(self) -> None:
        """Download the strategies one by one.

        The next strategy in the list is downloaded each time this method is called.

        We download all the strategies,
        because in the future we will perform some complicated logic,
        where we utilize more than one, e.g., in case the default fails
        or is weaker than another depending on the situation.

        :return: None
        """
        if self._inflight_strategy_req is not None:
            # there already is a req in flight
            return
        if len(self.shared_state.strategy_to_filehash) == 0:
            # no strategies pending to be fetched
            return
        for strategy, file_hash in self.shared_state.strategy_to_filehash.items():
            self.context.logger.info(f"Fetching {strategy} strategy...")
            ipfs_msg, message = self._build_ipfs_get_file_req(file_hash)
            self._inflight_strategy_req = strategy
            self.send_message(ipfs_msg, message, self._handle_get_strategy)
            return

    def download_strategies(self) -> Generator:
        """Download all the strategies, if not yet downloaded."""
        while len(self.shared_state.strategy_to_filehash) > 0:
            self.download_next_strategy()
            yield from self.sleep(self.params.sleep_time)

    def get_bet_amount(
        self,
        win_probability: float,
        confidence: float,
        selected_type_tokens_in_pool: int,
        other_tokens_in_pool: int,
        bet_fee: int,
        weighted_accuracy: float,
    ) -> Generator[None, None, int]:
        """Get the bet amount given a specified trading strategy."""
        yield from self.download_strategies()
        yield from self.wait_for_condition_with_sleep(self.check_balance)

        # accessing `self.shared_state.chatui_config` calls `self._ensure_chatui_store()` which ensures `trading_strategy` can never be `None`
        next_strategy: str = self.shared_state.chatui_config.trading_strategy  # type: ignore[assignment]

        tried_strategies: Set[str] = set()
        while True:
            self.context.logger.info(f"Used trading strategy: {next_strategy}")
            # the following are always passed to a strategy script, which may choose to ignore any
            kwargs: Dict[str, Any] = self.params.strategies_kwargs
            kwargs.update(
                {
                    "trading_strategy": next_strategy,
                    "bankroll": self.token_balance + self.wallet_balance,
                    "win_probability": win_probability,
                    "confidence": confidence,
                    "selected_type_tokens_in_pool": selected_type_tokens_in_pool,
                    "other_tokens_in_pool": other_tokens_in_pool,
                    "bet_fee": bet_fee,
                    "weighted_accuracy": weighted_accuracy,
                }
            )
            results = self.execute_strategy(**kwargs)
            for level in SUPPORTED_STRATEGY_LOG_LEVELS:
                logger = getattr(self.context.logger, level, None)
                if logger is not None:
                    for log in results.get(level, []):
                        logger(log)
            bet_amount = results.get(BET_AMOUNT_FIELD, None)
            if bet_amount is None:
                self.context.logger.error(
                    f"Required field {BET_AMOUNT_FIELD!r} was not returned by {next_strategy} strategy."
                    "Setting bet amount to 0."
                )
                bet_amount = 0

            tried_strategies.update({next_strategy})
            strategies_names = set(self.shared_state.strategies_executables)
            remaining_strategies = strategies_names - tried_strategies
            if (
                bet_amount > 0
                or len(remaining_strategies) == 0
                or not self.params.use_fallback_strategy
            ):
                break

            next_strategy = remaining_strategies.pop()
            self.context.logger.warning(
                f"Using fallback strategy {next_strategy} as the previous one returned {bet_amount}."
            )

        return bet_amount

    def default_error(
        self, contract_id: str, contract_callable: str, response_msg: ContractApiMessage
    ) -> None:
        """Return a default contract interaction error message."""
        self.context.logger.error(
            f"Could not successfully interact with the {contract_id} contract "
            f"using {contract_callable!r}: {response_msg}"
        )

    def _propagate_contract_messages(self, response_msg: ContractApiMessage) -> bool:
        """Propagate the contract's message to the logger, if exists.

        Contracts can only return one message at a time.

        :param response_msg: the response message from the contract method.
        :return: whether a message has been propagated.
        """
        for level in ("info", "warning", "error"):
            msg = response_msg.raw_transaction.body.get(level, None)
            if msg is not None:
                logger = getattr(self.context.logger, level)
                logger(msg)
                return True
        return False

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
            chain_id=self.params.mech_chain_id,
            **kwargs,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.default_error(contract_id, contract_callable, response_msg)
            return False

        propagated = self._propagate_contract_messages(response_msg)
        data = response_msg.raw_transaction.body.get(data_key, None)
        if data is None:
            if not propagated:
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
            contract_address=self.params.mech_contract_address,
            contract_public_id=Mech.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _mech_mm_contract_interact(
        self, contract_callable: str, data_key: str, placeholder: str, **kwargs: Any
    ) -> WaitableConditionType:
        """Interact with the mech mm contract."""
        status = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.mech_marketplace_config.priority_mech_address,
            contract_public_id=MechMM.contract_id,
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
            chain_id=self.params.mech_chain_id,
        )
        expected_performative = ContractApiMessage.Performative.RAW_TRANSACTION
        if response_msg.performative != expected_performative:
            self.context.logger.error(
                "Couldn't compile the multisend tx. "  # type: ignore
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
            chain_id=self.params.mech_chain_id,
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                "Couldn't get safe tx hash. Expected response performative "  # type: ignore
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
        sleep_time_override: Optional[int] = None,
    ) -> Generator[None, None, None]:
        """Wait for a condition to happen and sleep in-between checks.

        This is a modified version of the base `wait_for_condition` method which:
            1. accepts a generator that creates the condition instead of a callable
            2. sleeps in-between checks

        :param condition_gen: a generator of the condition to wait for
        :param timeout: the maximum amount of time to wait
        :param sleep_time_override: override for the sleep time.
            If None is given, the default value is used, which is the RPC timeout set in the configuration.
        :yield: None
        """

        deadline = (
            datetime.now() + timedelta(0, timeout)
            if timeout is not None
            else datetime.max
        )

        sleep_time = sleep_time_override or self.params.rpc_sleep_time
        while True:
            condition_satisfied = yield from condition_gen()
            if condition_satisfied:
                break
            if timeout is not None and datetime.now() > deadline:
                raise TimeoutException()
            self.context.logger.info(f"Retrying in {sleep_time} seconds.")
            yield from self.sleep(sleep_time)

    def _write_benchmark_results(
        self,
        prediction_response: PredictionResponse,
        bet_amount: Optional[float] = None,
        liquidity_info: LiquidityInfo = INIT_LIQUIDITY_INFO,
    ) -> None:
        """Write the results to the benchmarking file."""
        add_headers = False
        results_path = self.params.store_path / self.benchmarking_mode.results_filename
        if not os.path.isfile(results_path):
            add_headers = True

        with open(results_path, "a") as results_file:
            if add_headers:
                headers = (
                    self.benchmarking_mode.question_id_field,
                    self.benchmarking_mode.question_field,
                    self.benchmarking_mode.answer_field,
                    P_YES_FIELD,
                    P_NO_FIELD,
                    CONFIDENCE_FIELD,
                    self.benchmarking_mode.bet_amount_field,
                    L0_START_FIELD,
                    L1_START_FIELD,
                    L0_END_FIELD,
                    L1_END_FIELD,
                )
                row = ",".join(headers) + NEW_LINE
                results_file.write(row)

            results = (
                self.mock_data.id,
                # reintroduce duplicate quotes and quote the question
                # as it may contain commas which are also used as separators
                QUOTE + self.mock_data.question.replace(QUOTE, TWO_QUOTES) + QUOTE,
                self.mock_data.answer,
                prediction_response.p_yes,
                prediction_response.p_no,
                prediction_response.confidence,
                bet_amount,
                liquidity_info.l0_start,
                liquidity_info.l1_start,
                liquidity_info.l0_end,
                liquidity_info.l1_end,
            )
            results_text = tuple(str(res) for res in results)
            row = ",".join(results_text) + NEW_LINE
            results_file.write(row)

    def _calc_token_amount(
        self,
        operation: TradingOperation,
        amount_field: str,
        amount_param_name: str,
    ) -> WaitableConditionType:
        """Calculate the token amount for buying/selling."""

        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.market_maker_contract_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable=f"calc_{operation.value}_amount",
            outcome_index=self.outcome_index,
            chain_id=self.params.mech_chain_id,
            **{
                amount_param_name: self.investment_amount,
            },  # type: ignore
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not calculate the {operation} amount: {response_msg}"
            )
            return False

        token_amount = response_msg.raw_transaction.body.get(amount_field, None)
        if token_amount is None:
            self.context.logger.error(
                f"Something went wrong while trying to get the {amount_field} for the conditional token: {response_msg}"
            )
            return False

        if operation == TradingOperation.BUY:
            self.buy_amount = remove_fraction_wei(token_amount, self.params.slippage)
        else:
            self.sell_amount = remove_fraction_wei(token_amount, self.params.slippage)

        return True

    def _calc_buy_amount(self) -> WaitableConditionType:
        """Calculate the buy amount of the conditional token."""
        return self._calc_token_amount(
            operation=TradingOperation.BUY,
            amount_field="amount",
            amount_param_name="investment_amount",
        )

    def _calc_sell_amount(self) -> WaitableConditionType:
        """Calculate the sell amount of the conditional token."""
        return self._calc_token_amount(
            operation=TradingOperation.SELL,
            amount_field="amount",
            amount_param_name="return_amount",
        )

    def _build_token_tx(self, operation: TradingOperation) -> WaitableConditionType:
        """Get the tx data encoded for buying or selling tokens."""
        params: Dict[str, Any] = {
            "performative": ContractApiMessage.Performative.GET_STATE,  # type: ignore
            "contract_address": self.market_maker_contract_address,
            "contract_id": str(FixedProductMarketMakerContract.contract_id),
            "contract_callable": f"get_{operation.value}_data",
            "outcome_index": self.outcome_index,
            "chain_id": self.params.mech_chain_id,
        }

        if operation == TradingOperation.BUY:
            params.update(
                {
                    "investment_amount": self.investment_amount,
                    "min_outcome_tokens_to_buy": self.buy_amount,
                }
            )
        else:
            params.update(
                {
                    "return_amount": self.return_amount,
                    "max_outcome_tokens_to_sell": self.sell_amount,
                }
            )

        response_msg = yield from self.get_contract_api_response(**params)

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Could not get the data for the {operation} transaction: {response_msg}"
            )
            return False

        tx_data = response_msg.state.body.get("data", None)
        if tx_data is None:
            self.context.logger.error(
                f"Something went wrong while trying to encode the {operation} data: {response_msg}"
            )
            return False

        batch = MultisendBatch(
            to=self.market_maker_contract_address,
            data=HexBytes(tx_data),
        )
        self.multisend_batches.append(batch)
        return True

    def _build_buy_tx(self) -> WaitableConditionType:
        """Get the buy tx data encoded."""
        return self._build_token_tx(TradingOperation.BUY)

    def _build_sell_tx(self) -> WaitableConditionType:
        """Get the sell tx data encoded."""
        return self._build_token_tx(TradingOperation.SELL)

    def build_approval_tx(
        self, amount: int, spender: str, token: str
    ) -> WaitableConditionType:
        """Build an ERC20 approve transaction."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.collateral_token,
            contract_id=str(ERC20.contract_id),
            contract_callable="build_approval_tx",
            spender=spender,
            amount=amount,
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.info(f"Could not build approval tx: {response_msg}")
            return False

        approval_data = response_msg.state.body.get("data")
        if approval_data is None:
            self.context.logger.info(f"Could not build approval tx: {response_msg}")
            return False

        batch = MultisendBatch(
            to=token,
            data=HexBytes(approval_data),
        )
        self.multisend_batches.append(batch)
        return True

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class BaseSubscriptionBehaviour(DecisionMakerBaseBehaviour, ABC):
    """Base class for subscription behaviours."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `BaseSubscriptionBehaviour`."""
        super().__init__(**kwargs)
        self.balance: int = 0

    @property
    def escrow_payment_condition_address(self) -> str:
        """Get the escrow payment address."""
        subscription_params = self.subscription_params
        return subscription_params["escrow_payment_condition_address"]

    @property
    def lock_payment_condition_address(self) -> str:
        """Get the lock payment address."""
        subscription_params = self.subscription_params
        return subscription_params["lock_payment_condition_address"]

    @property
    def transfer_nft_condition_address(self) -> str:
        """Get the transfer nft condition address."""
        subscription_params = self.subscription_params
        return subscription_params["transfer_nft_condition_address"]

    @property
    def order_address(self) -> str:
        """Get the order address."""
        subscription_params = self.subscription_params
        return subscription_params["order_address"]

    @property
    def purchase_amount(self) -> int:
        """Get the purchase amount."""
        subscription_params = self.subscription_params
        return int(subscription_params["nft_amount"])

    @property
    def price(self) -> int:
        """Get the price."""
        subscription_params = self.subscription_params
        return int(subscription_params["price"])

    @property
    def payment_token(self) -> str:
        """Get the payment token."""
        subscription_params = self.subscription_params
        return subscription_params["payment_token"]

    @property
    def is_xdai(self) -> bool:
        """
        Check if the payment token is xDAI.

        When the payment token for the subscription is xdai (the native token of the chain),
        nevermined sets the payment address to the zeroAddress.

        :return: True if the payment token is xDAI, False otherwise.
        """
        return self.payment_token == ZERO_ADDRESS

    @property
    def base_url(self) -> str:
        """Get the base url."""
        subscription_params = self.subscription_params
        return subscription_params["base_url"]

    def _resolve_did(self) -> Generator[None, None, Optional[Dict[str, Any]]]:
        """Resolve and parse the did."""
        did_url = f"{self.base_url}/{self.did}"
        response = yield from self.get_http_response(
            method="GET",
            url=did_url,
            headers={"accept": "application/json"},
        )
        if response.status_code != 200:
            self.context.logger.error(
                f"Could not retrieve data from did url {did_url}. "
                f"Received status code {response.status_code}."
            )
            return None
        try:
            data = json.loads(response.body)
        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"Could not parse response from nervermined api, "
                f"the following error was encountered {type(e).__name__}: {e}"
            )
            return None

        return data

    def _get_nft_balance(
        self, token: str, address: str, did: str
    ) -> Generator[None, None, bool]:
        """Prepare an approval tx."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=token,
            contract_public_id=TransferNftCondition.contract_id,
            contract_callable="balance_of",
            data_key="data",
            placeholder="balance",
            address=address,
            did=did,
        )
        return result

    def _has_positive_nft_balance(self) -> Generator[None, None, bool]:
        """Check if the agent has a non-zero balance of the NFT."""
        result = yield from self._get_nft_balance(
            self.token_address,
            self.synchronized_data.safe_contract_address,
            zero_x_transformer(no_did_prefixed(self.did)),
        )
        if not result:
            self.context.logger.warning("Failed to get balance")
            return False

        return self.balance > 0
