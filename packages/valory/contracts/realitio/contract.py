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

"""This module contains the Realitio_v2_1 contract definition."""

from typing import List, Tuple, Union

from requests.exceptions import ReadTimeout as RequestsReadTimeoutError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError
from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from eth_typing import ChecksumAddress
from web3.constants import HASH_ZERO
from web3.types import BlockIdentifier

ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)


class RealitioContract(Contract):
    """The Realitio_v2_1 smart contract."""

    contract_id = PublicId.from_str("valory/realitio:0.1.0")

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
    def _get_claim_params(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier,
        question_id: bytes,
        chunk_size: int = 10_000,
    ) -> Union[str, Tuple[bytes, List[bytes], List[ChecksumAddress], List[int], List[bytes]]]:
        """Filters the `LogNewAnswer` event by question id to calculate the history hashes."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        to_block = ledger_api.api.eth.block_number

        try:
            answered = []
            for chunk in range(from_block, to_block, chunk_size):
                answer_filter = contract_instance.events.LogNewAnswer.build_filter()
                answer_filter.fromBlock = chunk
                answer_filter.toBlock = min(chunk + chunk_size, to_block)
                answer_filter.args.question_id.match_single(question_id)
                answered.extend(list(answer_filter.deploy(ledger_api.api).get_all_entries()))
        except (Urllib3ReadTimeoutError, RequestsReadTimeoutError):
            msg = (
                "The RPC timed out! This usually happens if the filtering is too wide. "
                f"The service tried to filter from block {from_block} to latest, "
                "as the market was created at this time. Did the market get created too long in the past?\n"
                "Please consider manually redeeming for the market with question id "
                f"{question_id!r} if this issue persists."
            )
            return msg
        else:
            n_answered = len(answered)

        if n_answered == 0:
            msg = f"No answers have been given for question with id {question_id.hex()}!"
            return msg

        history_hashes = []
        addresses = []
        bonds = []
        answers = []
        for i, answer in enumerate(reversed(answered)):
            # history_hashes second-last-to-first, the hash of each history entry, calculated as described here:
            # https://realitio.github.io/docs/html/contract_explanation.html#answer-history-entries.
            if i == n_answered - 1:
                history_hashes.append(ZERO_BYTES)
            else:
                history_hashes.append(answered[i + 1]["args"]["history_hash"])

            # last-to-first, the address of each answerer or commitment sender
            addresses.append(answer["args"]["user"])
            # last-to-first, the bond supplied with each answer or commitment
            bonds.append(answer["args"]["bond"])
            # last-to-first, each answer supplied, or commitment ID if the answer was supplied with commit->reveal
            answers.append(answer["args"]["answer"])

        return question_id, history_hashes, addresses, bonds, answers

    @classmethod
    def build_claim_winnings(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier,
        question_id: bytes,
    ) -> JSONLike:
        """Build `claimWinnings` transaction."""
        contract = cls.get_instance(ledger_api, contract_address)
        claim_params = cls._get_claim_params(
            ledger_api, contract_address, from_block, question_id
        )
        if isinstance(claim_params, str):
            return dict(error=claim_params)

        data = contract.encodeABI(
            fn_name="claimWinnings",
            args=claim_params,
        )
        return dict(data=data)

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
