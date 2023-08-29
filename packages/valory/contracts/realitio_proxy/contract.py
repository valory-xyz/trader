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

"""This module contains the realitio proxy contract definition."""

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class RealitioProxyContract(Contract):
    """The RealitioProxy smart contract."""

    contract_id = PublicId.from_str("valory/realitio_proxy:0.1.0")

    @classmethod
    def build_resolve_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        question_id: bytes,
        template_id: int,
        question: str,
        num_outcomes: int,
    ) -> JSONLike:
        """Build a `resolve` tx."""
        contract = cls.get_instance(ledger_api, contract_address)
        data = contract.encodeABI(
            fn_name="resolve",
            args=[
                question_id,
                template_id,
                question,
                num_outcomes,
            ],
        )
        return dict(data=data)
