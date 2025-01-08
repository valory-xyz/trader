# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This module contains the class to connect to an TRANSFER_NFT_CONDITION token contract."""

from typing import Dict, List

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from web3 import Web3

PUBLIC_ID = PublicId.from_str("valory/transfer_nft_condition:0.1.0")


class TransferNftCondition(Contract):
    """The TransferNftCondition contract."""

    contract_id = PUBLIC_ID

    @classmethod
    def build_order_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        agreement_id: str,
        did: str,
        condition_ids: List[str],
        time_locks: List[int],
        time_outs: List[int],
        consumer: str,
        index: int,
        reward_address: str,
        token_address: str,
        amounts: List[int],
        receives: List[str],
    ) -> Dict[str, bytes]:
        """Build an TransferNftCondition approval."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("createAgreementAndPayEscrow", args=(
            bytes.fromhex(agreement_id[2:]),
            bytes.fromhex(did[2:]),
            [bytes.fromhex(condition_id[2:]) for condition_id in condition_ids],
            time_locks,
            time_outs,
            Web3.to_checksum_address(consumer),
            index,
            Web3.to_checksum_address(reward_address),
            Web3.to_checksum_address(token_address),
            amounts,
            [Web3.to_checksum_address(receive) for receive in receives],
        ))
        return {"data": bytes.fromhex(data[2:])}

    @classmethod
    def balance_of(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        address: str,
        did: str,
    ) -> JSONLike:
        """Get the balance of an address."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        balance = contract_instance.functions.balanceOf(
            Web3.to_checksum_address(address),
            int(did, 16)
        ).call()
        return dict(data=balance)

    @classmethod
    def is_approved_for_all(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        account: str,
        operator: str,
    ) -> JSONLike:
        """Get the balance of an address."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        is_approved = contract_instance.functions.isApprovedForAll(
            Web3.to_checksum_address(account),
            Web3.to_checksum_address(operator),
        ).call()
        return dict(data=is_approved)

    @classmethod
    def build_set_approval_for_all_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        operator: str,
        approved: bool,
    ) -> Dict[str, bytes]:
        """Build an TransferNftCondition approval."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("setApprovalForAll", args=(
            Web3.to_checksum_address(operator),
            approved,
        ))
        return {"data": bytes.fromhex(data[2:])}

