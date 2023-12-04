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
import concurrent.futures
from typing import List, Tuple, Union, Dict, Callable, Any

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from eth_typing import ChecksumAddress
from requests.exceptions import ReadTimeout as RequestsReadTimeoutError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

ClaimParamsType = Tuple[
    List[bytes], List[ChecksumAddress], List[int], List[bytes]
]

FIVE_MINUTES = 300.0


class RealitioContract(Contract):
    """The Realitio_v2_1 smart contract."""

    contract_id = PublicId.from_str("valory/realitio:0.1.0")

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
                # Wait for the result with a 5-minute timeout
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
        contract_instance = cls.get_instance(ledger_api, contract_address)

        def get_claim_params() -> Any:
            """Get claim params."""
            try:
                answer_filter = contract_instance.events.LogNewAnswer.build_filter()
                answer_filter.fromBlock = from_block
                answer_filter.toBlock = to_block
                answer_filter.args.question_id.match_single(question_id)
                answered = list(answer_filter.deploy(ledger_api.api).get_all_entries())
                return answered
            except (Urllib3ReadTimeoutError, RequestsReadTimeoutError):
                msg = (
                    "The RPC timed out! This usually happens if the filtering is too wide. "
                    f"The service tried to filter from block {from_block} to {to_block}. "
                    f"If this issue persists, please try lowering the `EVENT_FILTERING_BATCH_SIZE`!"
                )
                return msg

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
