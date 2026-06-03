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

"""This module contains the Polymarket DepositWallet (CLOB v2) contract.

The DepositWallet (DW) is an ERC-1967 proxy owned by the agent EOA. Under
CLOB v2 it is the transient CLOB funder: the canonical Safe holds persistent
assets and the DW is empty at rest. This interface exposes only the two
on-chain surfaces the trader needs locally — the ``owner()`` read (used by
the setup gate to detect agent-EOA rotation and self-heal lost DW state) and
``execute`` encoding (single-call sweep helper). DW provisioning and relayed
batches go through the wildcard predict-api proxy, not this contract class.
"""

from typing import Any

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi


class DepositWalletContract(Contract):
    """Polymarket CLOB v2 DepositWallet proxy contract."""

    contract_id = PublicId.from_str("valory/deposit_wallet:0.1.0")

    @classmethod
    def get_raw_transaction(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """Handler for 'GET_RAW_TRANSACTION' (unused).

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_raw_message(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> bytes:
        """Handler for 'GET_RAW_MESSAGE' (unused).

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_state(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """Handler for 'GET_STATE' (unused).

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_owner(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
    ) -> JSONLike:
        """Read the DepositWallet owner.

        Used by the setup gate: a DW whose owner no longer matches the current
        agent EOA (mnemonic-recovery rotation) is re-provisioned under the new
        EOA, and the old DW is treated as inaccessible.

        :param ledger_api: the ledger api.
        :param contract_address: the DepositWallet proxy address.
        :return: ``{"owner": <address>}``.
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        owner = contract_instance.functions.owner().call()
        return dict(owner=owner)

    @classmethod
    def get_nonce(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
    ) -> JSONLike:
        """Read the DepositWallet's batch nonce (EIP-712 replay protection).

        The relayer ``execute(Batch, sig)`` envelope binds this nonce; the
        owner must read it on-chain before signing a sweep / approval batch.

        :param ledger_api: the ledger api.
        :param contract_address: the DepositWallet proxy address.
        :return: ``{"nonce": <int>}``.
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        nonce = contract_instance.functions.nonce().call()
        return dict(nonce=nonce)
