# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 valory
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

"""This module contains the scaffold contract definition."""

from typing import Any, Dict, List

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from web3.types import BlockIdentifier


MARKET_FEE = 2.0
UNIT_SEPARATOR = "␟"


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


class RealtioContract(Contract):
    """The scaffold contract class for a smart contract."""

    contract_id = PublicId.from_str("valory/realtio:0.1.0")

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
        # TODO: consider using multicall2 or constructor trick instead of filters
        contract = cls.get_instance(
            ledger_api=ledger_api, contract_address=contract_address
        )
        entries = contract.events.LogNewQuestion.createFilter(
            fromBlock=from_block,
            toBlock=to_block,
            argument_filters=dict(question_id=question_ids),
        ).get_all_entries()
        events = list(
            dict(
                tx_hash=entry.transactionHash.hex(),
                block_number=entry.blockNumber,
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
    def build_claim_winnings(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
        history_hash: List[bytes],
        addresses: List[str],
        bonds: List[int],
        claim_amounts: List[bytes],
    ) -> JSONLike:
        """Build claim winnings transaction."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="claimWinnings",
            args=[
                question_id,
                history_hash,
                addresses,
                bonds,
                claim_amounts,
            ],
        )
        return dict(
            data=data,
        )
