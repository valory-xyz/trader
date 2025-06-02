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

"""This module contains the Realitio_v2_1 contract definition."""

import concurrent.futures
import logging
from typing import List, Tuple, Union, Dict, Callable, Any, Optional, Sequence

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from eth_typing import ChecksumAddress
from eth_utils import event_abi_to_log_topic
from requests.exceptions import ReadTimeout as RequestsReadTimeoutError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError
from web3._utils.events import get_event_data
from web3.eth import Eth
from web3.contract import Contract as W3Contract
from web3.exceptions import ContractLogicError
from web3.types import BlockIdentifier, FilterParams, ABIEvent, _Hash32, LogReceipt, EventData

ClaimParamsType = Tuple[
    List[bytes], List[ChecksumAddress], List[int], List[bytes]
]

FIVE_MINUTES = 300.0

PUBLIC_ID = PublicId.from_str("valory/realitio:0.1.0")
_logger = logging.getLogger(
    f"aea.packages.{PUBLIC_ID.author}.contracts.{PUBLIC_ID.name}.contract"
)

MARKET_FEE = 2.0
UNIT_SEPARATOR = chr(9247)


def format_answers(answers: List[str]) -> str:
    """Format answers."""
    return ",".join(map(lambda x: '"' + x + '"', answers))


def build_question(question_data: Dict) -> str:
    """Build question."""
    return UNIT_SEPARATOR.join(
        [
            question_data["question"],
            format_answers(question_data["answers"]),
            question_data["topic"],
            question_data["language"],
        ]
    )


def get_entries(
    eth: Eth,
    contract_instance: W3Contract,
    event_abi: ABIEvent,
    topics: List[Optional[Union[_Hash32, Sequence[_Hash32]]]],
    from_block: BlockIdentifier = "earliest",
    to_block: BlockIdentifier = "latest",
) -> List[EventData]:
    """Helper method to extract the events."""
    event_topic = event_abi_to_log_topic(event_abi)
    topics.insert(0, event_topic)

    filter_params: FilterParams = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": contract_instance.address,
        "topics": topics,
    }

    logs = eth.get_logs(filter_params)
    return [get_event_data(eth.codec, event_abi, log) for log in logs]


class RealitioContract(Contract):
    """The Realitio_v2_1 smart contract."""

    contract_id = PUBLIC_ID

    @staticmethod
    def execute_with_timeout(func: Callable, timeout: float) -> Any:
        """Execute a function with a timeout."""

        # Create a ProcessPoolExecutor with a maximum of 1 worker (process)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # Submit the function to the executor
            future = executor.submit(
                func,
            )

            try:
                # Wait for the result with a timeout
                data = future.result(timeout=timeout)
            except TimeoutError:
                # Handle the case where the execution times out
                err = f"The RPC didn't respond in {timeout}."
                return None, err

            # Check if an error occurred
            if isinstance(data, str):
                # Handle the case where the execution failed
                return None, data

            return data, None

    @classmethod
    def check_finalized(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
    ) -> JSONLike:
        """Check whether a market has been finalized."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        is_finalized = contract_instance.functions.isFinalized(question_id).call()
        return dict(finalized=is_finalized)

    @classmethod
    def get_claim_params(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: int,
        to_block: int,
        question_id: bytes,
        timeout: float = FIVE_MINUTES,
    ) -> Dict[str, Union[str, list]]:
        """Filters the `LogNewAnswer` event by question id to calculate the history hashes."""
        eth = ledger_api.api.eth
        contract_instance = cls.get_instance(ledger_api, contract_address)
        event_abi = contract_instance.events.LogNewAnswer().abi
        topics = [question_id]

        def get_claim_params() -> Any:
            """Get claim params."""
            try:
                return get_entries(eth, contract_instance, event_abi, topics, from_block, to_block)
            except (Urllib3ReadTimeoutError, RequestsReadTimeoutError):
                return (
                    "The RPC timed out! This usually happens if the filtering is too wide. "
                    f"The service tried to filter from block {from_block} to {to_block}. "
                    f"If this issue persists, please try lowering the `EVENT_FILTERING_BATCH_SIZE`!"
                )

        answered, err = cls.execute_with_timeout(get_claim_params, timeout=timeout)
        if err is not None:
            return dict(error=err)

        msg = (
            f"Found {len(answered)} answer(s) for question with id {question_id.hex()} "
            f"between blocks {from_block} and {to_block}."
        )
        return dict(info=msg, answered=answered)

    @classmethod
    def build_claim_winnings(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
        claim_params: ClaimParamsType,
    ) -> JSONLike:
        """Build `claimWinnings` transaction."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="claimWinnings",
            args=(question_id, *claim_params),
        )
        return dict(data=data)

    @classmethod
    def simulate_claim_winnings(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
        claim_params: ClaimParamsType,
        sender_address: str,
    ) -> JSONLike:
        """Simulate `claimWinnings` transaction."""
        data = cls.build_claim_winnings(ledger_api, contract_address, question_id, claim_params)["data"]
        try:
            ledger_api.api.eth.call(
                {
                    "from": ledger_api.api.to_checksum_address(sender_address),
                    "to": ledger_api.api.to_checksum_address(contract_address),
                    "data": data[2:],
                }
            )
            simulation_ok = True
        except (ValueError, ContractLogicError) as e:
            _logger.info(f"Simulation failed: {str(e)}")
            simulation_ok = False
        return dict(data=simulation_ok)

    @classmethod
    def get_history_hash(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
    ) -> JSONLike:
        """Get history hash for a question"""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.functions.getHistoryHash(question_id).call()
        return dict(data=data)

    @classmethod
    def get_raw_transaction(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """
        Handler method for the 'GET_RAW_TRANSACTION' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_raw_message(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> bytes:
        """
        Handler method for the 'GET_RAW_MESSAGE' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_state(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """
        Handler method for the 'GET_STATE' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_ask_question_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_data: Dict,
        opening_timestamp: int,
        timeout: int,
        arbitrator_contract: str,
        template_id: int = 2,
        question_nonce: int = 0,
    ) -> JSONLike:
        """Get ask question transaction."""
        question = build_question(question_data=question_data)
        kwargs = {
            "template_id": template_id,
            "question": question,
            "arbitrator": ledger_api.api.to_checksum_address(arbitrator_contract),
            "timeout": timeout,
            "opening_ts": opening_timestamp,
            "nonce": question_nonce,
        }
        return ledger_api.build_transaction(
            contract_instance=cls.get_instance(
                ledger_api=ledger_api, contract_address=contract_address
            ),
            method_name="askQuestion",
            method_args=kwargs,
        )

    @classmethod
    def get_ask_question_tx_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_data: Dict,
        opening_timestamp: int,
        timeout: int,
        arbitrator_contract: str,
        template_id: int = 2,
        question_nonce: int = 0,
    ) -> JSONLike:
        """Get ask question transaction."""
        question = build_question(question_data=question_data)
        kwargs = {
            "template_id": template_id,
            "question": question,
            "arbitrator": ledger_api.api.to_checksum_address(arbitrator_contract),
            "timeout": timeout,
            "opening_ts": opening_timestamp,
            "nonce": question_nonce,
        }
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        data = contract_instance.encodeABI(fn_name="askQuestion", kwargs=kwargs)
        return {"data": bytes.fromhex(data[2:])}  # type: ignore

    @classmethod
    def calculate_question_id(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_data: Dict,
        opening_timestamp: int,
        timeout: int,
        arbitrator_contract: str,
        sender: str,
        template_id: int = 2,
        question_nonce: int = 0,
    ) -> JSONLike:
        """Get ask question transaction."""
        question = build_question(question_data=question_data)
        content_hash = ledger_api.api.solidity_keccak(
            ["uint256", "uint32", "string"],
            [template_id, opening_timestamp, question],
        )
        question_id = ledger_api.api.solidity_keccak(
            ["bytes32", "address", "uint32", "address", "uint256"],
            [
                content_hash,
                ledger_api.api.to_checksum_address(arbitrator_contract),
                timeout,
                ledger_api.api.to_checksum_address(sender),
                question_nonce,
            ],
        )
        return {"question_id": question_id.hex()}

    @classmethod
    def get_question_events(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_ids: List[bytes],
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Get questions."""
        eth = ledger_api.api.eth
        contract = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        event_abi = contract.events.LogNewQuestion().abi
        topics = [question_ids]
        entries = get_entries(eth, contract, event_abi, topics, from_block, to_block)
        events = list(
            dict(
                tx_hash=entry["transactionHash"].hex(),
                block_number=entry["blockNumber"],
                question_id=entry["args"]["question_id"],
                user=entry["args"]["user"],
                template_id=entry["args"]["template_id"],
                question=entry["args"]["question"],
                content_hash=entry["args"]["content_hash"],
                arbitrator=entry["args"]["arbitrator"],
                timeout=entry["args"]["timeout"],
                opening_ts=entry["args"]["opening_ts"],
                nonce=entry["args"]["nonce"],
                created=entry["args"]["created"],
            )
            for entry in entries
        )
        return dict(data=events)

    @classmethod
    def get_submit_answer_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
        answer: bytes,
        max_previous: int,
    ) -> JSONLike:
        """Get submit answer transaction."""
        contract = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        data = contract.encodeABI(
            fn_name="submitAnswer",
            args=[
                question_id,
                answer,
                max_previous,
            ],
        )
        return dict(data=data)

    @classmethod
    def balance_of(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        address: str,
    ) -> JSONLike:
        """Get balance for an address"""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.functions.balanceOf(address).call()
        return dict(data=data)

    @classmethod
    def build_withdraw_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Build `withdraw` transaction."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="withdraw",
        )
        return dict(data=data)
