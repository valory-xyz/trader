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

"""This module contains the class to connect to an TRANSFER_NFT_CONDITION token contract."""

from typing import Dict

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
    def build_fulfill_for_delegate_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        agreement_id: str,
        did: str,
        nft_holder: str,
        nft_receiver: str,
        nft_amount: int,
        lock_payment_condition: str,
        nft_contract_address: str,
        transfer: bool,
        expiration_block: int,
    ) -> Dict[str, bytes]:
        """Build an TransferNftCondition approval."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI("fulfillForDelegate", args=(
            bytes.fromhex(agreement_id[2:]),
            bytes.fromhex(did[2:]),
            Web3.to_checksum_address(nft_holder),
            Web3.to_checksum_address(nft_receiver),
            nft_amount,
            bytes.fromhex(lock_payment_condition[2:]),
            Web3.to_checksum_address(nft_contract_address),
            transfer,
            expiration_block,
        ))
        return {"data": bytes.fromhex(data[2:])}
