# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains the class wrapping logic of the Relayer contract."""

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class RelayerContract(Contract):
    """The Relayer contract."""

    contract_id = PublicId.from_str("valory/relayer:0.1.0")

    @classmethod
    def build_operator_deposit_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        amount: int,
    ) -> JSONLike:
        """Build a deposit tx."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="operatorDeposit",
            args=[
                amount,
            ],
        )
        return dict(data=data)

    @classmethod
    def build_exec_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        to: str,
        data: bytes,
    ) -> JSONLike:
        """Build a execute tx."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="exec",
            args=[
                to,
                data,
            ],
        )
        return dict(data=data)
