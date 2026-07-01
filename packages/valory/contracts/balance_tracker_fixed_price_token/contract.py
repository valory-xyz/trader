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

"""Wrapper for the BalanceTrackerFixedPriceToken marketplace contract."""

from typing import Dict

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/balance_tracker_fixed_price_token:0.1.0")


class BalanceTrackerFixedPriceToken(Contract):
    """Balance tracker for the fixed-price ERC20 token payment model.

    Exposes the two operations the off-chain request behaviour needs when
    auto-resolving a structured 402 challenge: read the requester's prepaid
    balance (to decide whether to retry-only, deposit-and-retry, or fail
    over the cap) and produce calldata for ``depositFor`` (one half of the
    Safe-multisend that approves and then funds the BalanceTracker).
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
        Returned value is in the token's smallest denomination.

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
    def get_token(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
    ) -> JSONLike:
        """Read the ERC20 ``token`` address this BalanceTracker accepts.

        The off-chain request behaviour cross-checks this against the
        ``asset`` field of a structured 402 challenge before approving
        any spend. Without the check a compromised mech could direct the
        Safe to approve an attacker-chosen token (or an arbitrary
        contract that happens to expose ``approve``); pinning the
        approval target to the marketplace's on-chain registry blocks
        that.

        :param ledger_api: the ledger API object.
        :param contract_address: the BalanceTracker contract address.
        :return: ``{"token": "0x…"}`` matching the ``GET_STATE`` shape.
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        token = contract_instance.functions.token().call()
        return dict(token=str(token))

    @classmethod
    def build_deposit_for_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        account: str,
        amount: int,
    ) -> Dict[str, bytes]:
        """Encode the calldata for ``depositFor(account, amount)``.

        Returned as raw bytes ready to drop into a Safe multisend batch
        alongside the ERC20 approval. The token transfer happens via
        ``transferFrom(msg.sender, ...)`` on the BalanceTracker side, so the
        approval must be granted by the same caller (the Safe) before this
        call lands.

        :param ledger_api: the ledger API object.
        :param contract_address: the BalanceTracker contract address.
        :param account: the requester address being credited.
        :param amount: the deposit amount in the token's smallest unit.
        :return: ``{"data": bytes}`` calldata for the multisend batch.
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        account = ledger_api.api.to_checksum_address(account)
        data = contract_instance.encode_abi("depositFor", args=(account, amount))
        return {"data": bytes.fromhex(data[2:])}
