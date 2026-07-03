# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""BalanceTracker for the fixed-price native (xDAI / ETH) payment model."""

import logging

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/balance_tracker_fixed_price_native:0.1.0")

_logger = logging.getLogger(
    f"aea.packages.{PUBLIC_ID.author}.contracts.{PUBLIC_ID.name}.contract"
)


class BalanceTrackerFixedPriceNativeContract(Contract):
    """BalanceTracker for the fixed-price native payment model."""

    contract_id = PUBLIC_ID

    @classmethod
    def get_requester_balance(
        cls, ledger_api: LedgerApi, contract_address: str, requester: str
    ) -> JSONLike:
        """Get requester balance."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        requester_balance = contract_instance.functions.mapRequesterBalances(
            requester
        ).call()
        return {"requester_balance": requester_balance}

    @classmethod
    def build_deposit_for_data(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        account: str,
        amount: int,
    ) -> JSONLike:
        """Encode depositFor(account) calldata plus the tx value the caller must attach."""
        if amount <= 0:
            raise ValueError(
                f"build_deposit_for_data requires amount > 0 (got {amount}); "
                "the on-chain depositFor(address) is payable with no zero-value "
                "guard, so a value-less call silently credits zero."
            )
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encode_abi(
            abi_element_identifier="depositFor",
            args=[account],
        )
        return {"data": bytes.fromhex(data[2:]), "value": amount}  # type: ignore
