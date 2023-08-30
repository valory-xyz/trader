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

from typing import List

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class RealitioContract(Contract):
    """The Realitio_v2_1 smart contract."""

    contract_id = PublicId.from_str("valory/realitio:0.1.0")

    @classmethod
    def build_claim_winnings(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
        history_hashes: List[bytes],
        addresses: List[str],
        bonds: List[int],
        answers: List[bytes],
    ) -> JSONLike:
        """Build `claimWinnings` transaction."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="claimWinnings",
            args=[
                question_id,
                history_hashes,
                [ledger_api.api.to_checksum_address(a) for a in addresses],
                bonds,
                answers,
            ],
        )
        return dict(data=data)
