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

"""Wrapper for the BalanceTrackerFixedPriceNative marketplace contract."""

from typing import Dict

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/balance_tracker_fixed_price_native:0.1.0")


class BalanceTrackerFixedPriceNative(Contract):
    """Balance tracker for the fixed-price native (xDAI / ETH) payment model.

    The native variant of the BalanceTracker contracts. Funds arrive via
    ``msg.value``; the ``depositFor`` function is ``payable`` and takes only
    the credited account as a parameter. The Safe-multisend caller supplies
    the amount through the ``value`` field of the transaction, not through
    the calldata.
    """

    contract_id = PUBLIC_ID

    @classmethod
    def get_balance(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        account: str,
    ) -> JSONLike:
        """Read the prepaid balance for ``account`` on this BalanceTracker.

        Mirrors the contract's ``mapRequesterBalances(account)`` getter.
        Returned value is in wei.

        :param ledger_api: the ledger API object.
        :param contract_address: the BalanceTracker contract address.
        :param account: the requester address whose balance to read.
        :return: ``{"balance": int}`` matching the ``GET_STATE`` shape.
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        account = ledger_api.api.to_checksum_address(account)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        balance = contract_instance.functions.mapRequesterBalances(account).call()
        return dict(balance=balance)

    @classmethod
    def build_deposit_for_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        account: str,
    ) -> Dict[str, bytes]:
        """Encode the calldata for ``depositFor(account)``.

        Returned as raw bytes ready to be paired with a non-zero ``value``
        in the Safe-multisend batch. The deposit amount is carried by
        ``msg.value`` on chain rather than by the calldata.

        :param ledger_api: the ledger API object.
        :param contract_address: the BalanceTracker contract address.
        :param account: the requester address being credited.
        :return: ``{"data": bytes}`` calldata for the multisend batch.
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        account = ledger_api.api.to_checksum_address(account)
        data = contract_instance.encode_abi("depositFor", args=(account,))
        return {"data": bytes.fromhex(data[2:])}
