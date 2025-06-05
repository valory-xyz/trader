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

"""This module contains the conditional tokens contract definition."""

import concurrent.futures
from typing import List, Any, Dict, Union, Callable, Literal, Sequence, Optional

from eth_utils import event_abi_to_log_topic
from requests.exceptions import ReadTimeout as RequestsReadTimeoutError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError
from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from hexbytes import HexBytes
from web3._utils.events import get_event_data
from web3.contract import Contract as W3Contract
from web3.eth import Eth
from web3.types import BlockIdentifier, FilterParams, _Hash32, LogReceipt, ABIEvent

FIVE_MINUTES = 300.0
DEFAULT_OUTCOME_SLOT = 2
TOPIC_BYTES = 32
TOPIC_BYTEORDER: Literal["big"] = "big"


def pad_int_for_topic(value: int) -> HexBytes:
    """Convert an int to a 32-byte big-endian HexBytes object for use in a topic."""
    return HexBytes(value.to_bytes(TOPIC_BYTES, TOPIC_BYTEORDER))


def update_from_event(redeeming: Dict[str, Any], payouts: Dict[str, int]) -> None:
    """Update payouts dict using a redemption event log."""
    args = redeeming.get("args", {})
    condition_id = args.get("conditionId")
    payout = args.get("payout", 0)

    if not condition_id or payout == 0:
        return

    if isinstance(condition_id, bytes):
        condition_id = condition_id.hex()

    if isinstance(payout, bytes):
        payout = int.from_bytes(payout, byteorder=TOPIC_BYTEORDER)

    payouts[condition_id] = int(payout)


def get_logs(
    eth: Eth,
    contract_instance: W3Contract,
    event_abi: ABIEvent,
    topics: List[Optional[Union[_Hash32, Sequence[_Hash32]]]],
    from_block: BlockIdentifier = "earliest",
    to_block: BlockIdentifier = "latest",
) -> List[LogReceipt]:
    """Helper method to extract the events."""
    event_topic = event_abi_to_log_topic(event_abi)
    topics.insert(0, event_topic)

    filter_params: FilterParams = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": contract_instance.address,
        "topics": topics,
    }

    return eth.get_logs(filter_params)


class ConditionalTokensContract(Contract):
    """The ConditionalTokens smart contract."""

    contract_id = PublicId.from_str("valory/conditional_tokens:0.1.0")

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
    def check_redeemed(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        redeemer: str,
        from_block: int,
        to_block: int,
        collateral_tokens: List[str],
        parent_collection_ids: List[bytes],
        condition_ids: List[HexBytes],
        index_sets: List[List[int]],
        timeout: float = FIVE_MINUTES,
    ) -> JSONLike:
        """Filter to find out whether a position has already been redeemed."""

        eth = ledger_api.api.eth
        contract_instance = cls.get_instance(ledger_api, contract_address)
        event_abi = contract_instance.events.PayoutRedemption().abi
        to_checksum = ledger_api.api.to_checksum_address
        redeemer_checksummed = to_checksum(redeemer)
        collateral_tokens_checksummed = [
            to_checksum(token) for token in collateral_tokens
        ]
        topics = [
            redeemer_checksummed,
            collateral_tokens_checksummed,
            parent_collection_ids,
        ]

        def get_redeem_events() -> Union[List[Dict[str, Any]], str]:
            """Get the redeem events."""
            try:
                logs = get_logs(
                    eth, contract_instance, event_abi, topics, from_block, to_block
                )
            except (Urllib3ReadTimeoutError, RequestsReadTimeoutError):
                return (
                    "The RPC timed out! This usually happens if the filtering is too wide. "
                    f"The service tried to filter from block {from_block} to {to_block}. "
                    f"If this issue persists, please try lowering the `EVENT_FILTERING_BATCH_SIZE`!"
                )

            # we need to manually filter the unindexed inputs as we cannot add them in the topics of the filter params
            padded_index_sets = [
                [pad_int_for_topic(i) for i in indexes] for indexes in index_sets
            ]
            entries = [
                entry
                for log in logs
                if (entry := get_event_data(eth.codec, event_abi, log))["args"][
                    "conditionId"
                ]
                in condition_ids
                and entry["args"]["indexSets"] in padded_index_sets
            ]

            return entries

        redeemed, err = cls.execute_with_timeout(get_redeem_events, timeout)
        if err is not None:
            return dict(error=err)

        payouts = {}
        for redeeming in redeemed:
            update_from_event(redeeming, payouts)

        return dict(payouts=payouts)

    @classmethod
    def check_resolved(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        condition_id: HexBytes,
    ) -> JSONLike:
        """Check whether a position has already been resolved."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        payout_denominator = contract_instance.functions.payoutDenominator
        payout = payout_denominator(condition_id).call()
        if payout == 0:
            return dict(resolved=False)
        return dict(resolved=True)

    @classmethod
    def build_redeem_positions_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        collateral_token: str,
        parent_collection_id: bytes,
        condition_id: HexBytes,
        index_sets: List[int],
    ) -> JSONLike:
        """Build a `redeemPositions` tx."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI(
            fn_name="redeemPositions",
            args=[
                ledger_api.api.to_checksum_address(collateral_token),
                parent_collection_id,
                condition_id,
                index_sets,
            ],
        )
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
    def get_prepare_condition_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: str,
        oracle_contract: str,
        outcome_slot_count: int = DEFAULT_OUTCOME_SLOT,
    ) -> JSONLike:
        """Tx for preparing condition for marker maker."""
        kwargs = {
            "oracle": ledger_api.api.to_checksum_address(oracle_contract),
            "questionId": question_id,
            "outcomeSlotCount": outcome_slot_count,
        }
        return ledger_api.build_transaction(
            contract_instance=cls.get_instance(
                ledger_api=ledger_api, contract_address=contract_address
            ),
            method_name="prepareCondition",
            method_args=kwargs,
        )

    @classmethod
    def get_prepare_condition_tx_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: str,
        oracle_contract: str,
        outcome_slot_count: int = DEFAULT_OUTCOME_SLOT,
    ) -> JSONLike:
        """Tx for preparing condition for marker maker."""
        kwargs = {
            "oracle": ledger_api.api.to_checksum_address(oracle_contract),
            "questionId": question_id,
            "outcomeSlotCount": outcome_slot_count,
        }
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        data = contract_instance.encodeABI(fn_name="prepareCondition", kwargs=kwargs)
        return {"data": bytes.fromhex(data[2:])}

    @classmethod
    def calculate_condition_id(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        oracle_contract: str,
        question_id: str,
        outcome_slot_count: int,
    ) -> str:
        """Calculate condition ID."""
        return {
            "condition_id": ledger_api.api.solidity_keccak(
                ["address", "bytes32", "uint256"],
                [
                    ledger_api.api.to_checksum_address(oracle_contract),
                    bytes.fromhex(question_id[2:]),
                    outcome_slot_count,
                ],
            ).hex()
        }

    @classmethod
    def get_condition_id(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        tx_digest: str,  # retrieved from `prepareCondition` tx
    ) -> JSONLike:
        """Tx for preparing condition for marker maker."""
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        tx_receipt = ledger_api.api.eth.getTransactionReceipt(tx_digest)
        (log,) = contract_instance.events.ConditionPreparation().process_receipt(
            tx_receipt
        )
        return "0x" + log["args"]["conditionId"].hex()

    @classmethod
    def get_condition_preparation_events(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        condition_ids: List[HexBytes],
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Get condition preparation events."""
        eth = ledger_api.api.eth
        contract_instance = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        event_abi = contract_instance.events.ConditionPreparation().abi
        topics = [condition_ids]

        logs = get_logs(
            eth, contract_instance, event_abi, topics, from_block, to_block
        )
        entries = [get_event_data(eth.codec, event_abi, log) for log in logs]
        events = [
            {
                "tx_hash": entry["transactionHash"].hex(),
                "block_number": entry["blockNumber"],
                "condition_id": entry["args"]["conditionId"],
                "oracle": entry["args"]["oracle"],
                "question_id": entry["args"]["questionId"],
                "outcome_slot_count": entry["args"]["outcomeSlotCount"],
            }
            for entry in entries
        ]

        return {"data": events}

    @staticmethod
    def get_partitions(count: int) -> List[int]:
        """Calculate and return partitions."""
        return list(map(lambda x: 1 << x, range(count)))

    @classmethod
    def get_user_holdings(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        outcome_slot_count: int,
        condition_id: str,
        creator: str,
        collateral_token: str,
        market: str,
        parent_collection_id: str,
    ) -> JSONLike:
        """Returns user holding."""
        holdings = []
        shares = []
        instance = cls.get_instance(
            ledger_api=ledger_api,
            contract_address=contract_address,
        )
        for i in cls.get_partitions(count=outcome_slot_count):
            collection_id = int.from_bytes(
                instance.functions.getCollectionId(
                    parent_collection_id, condition_id, i
                ).call(),
                "big",
            )
            position_id = int.from_bytes(
                ledger_api.api.solidity_keccak(
                    ["address", "uint256"],
                    [
                        ledger_api.api.to_checksum_address(collateral_token),
                        collection_id,
                    ],
                ),
                "big",
            )
            holdings.append(
                instance.functions.balanceOf(
                    ledger_api.api.to_checksum_address(market),
                    position_id,
                ).call()
            )
            shares.append(
                instance.functions.balanceOf(
                    ledger_api.api.to_checksum_address(creator), position_id
                ).call()
            )
        return dict(
            holdings=holdings,
            shares=shares,
        )

    @classmethod
    def build_merge_positions_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        collateral_token: str,
        parent_collection_id: bytes,
        condition_id: bytes,
        outcome_slot_count: int,
        amount: int,
        **kwargs: Any,
    ) -> JSONLike:
        """Build mergePositions tx."""
        instance = cls.get_instance(ledger_api, contract_address)
        partition = cls.get_partitions(count=outcome_slot_count)
        data = instance.encodeABI(
            fn_name="mergePositions",
            args=[
                ledger_api.api.to_checksum_address(collateral_token),
                parent_collection_id,
                condition_id,
                partition,
                amount,
            ],
        )
        return dict(
            data=data,
        )
