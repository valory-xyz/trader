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

"""Wrapper for the MechMarketplace contract, used by the off-chain dispatch path."""

from typing import cast

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/mech_marketplace:0.1.0")


class MechMarketplace(Contract):
    """Read-only wrapper for the MechMarketplace marketplace contract.

    The off-chain request behaviour reads ``mapNonces`` and ``chainId``
    here before signing each attempt: the locally-derived ``request_id``
    must match what the contract will compute at settlement, and the
    EIP-712 domain separator binds to the marketplace's immutable chain id.
    The contract is not written to from this wrapper; settlement still goes
    through the existing on-chain submission paths.
    """

    contract_id = PUBLIC_ID

    @classmethod
    def get_nonce(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender: str,
    ) -> JSONLike:
        """Read ``mapNonces(sender)`` on the marketplace.

        The off-chain request behaviour reads this before signing each
        attempt so the locally-derived ``request_id`` matches the value the
        contract will compute at settlement. The slot is bumped at
        ``deliverMarketplaceWithSignatures`` time, not at request time, so
        the same nonce is reused across the deposit-then-retry round-trip.

        :param ledger_api: the ledger API object.
        :param contract_address: the marketplace contract address.
        :param sender: the requester address (the Safe / EOA owning the
            prepaid balance) whose nonce slot to read.
        :return: a ``{"nonce": int}`` dict matching the framework's
            ``GET_STATE`` response shape.
        """
        ledger_api = cast(EthereumApi, ledger_api)
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        sender = ledger_api.api.to_checksum_address(sender)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        nonce = contract_instance.functions.mapNonces(sender).call()
        return dict(nonce=int(nonce))

    @classmethod
    def get_chain_id(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Read the immutable ``chainId`` constant baked into the marketplace.

        Used to assemble the EIP-712 domain separator client-side when
        deriving ``request_id`` so the hash binds to the same chain the
        contract validates against at settlement.

        :param ledger_api: the ledger API object.
        :param contract_address: the marketplace contract address.
        :return: a ``{"chain_id": int}`` dict matching the framework's
            ``GET_STATE`` response shape.
        """
        ledger_api = cast(EthereumApi, ledger_api)
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        chain_id = contract_instance.functions.chainId().call()
        return dict(chain_id=int(chain_id))

    @classmethod
    def get_balance_tracker(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        payment_type: bytes,
    ) -> JSONLike:
        """Read ``mapPaymentTypeBalanceTrackers(paymentType)`` on the marketplace.

        The off-chain request behaviour uses this to validate that the
        ``payTo`` address advertised in a structured 402 body actually
        matches the canonical BalanceTracker the marketplace registered
        for the mech's ``paymentType``. Without this check a malicious or
        compromised mech could redirect the auto-deposit (capped per cycle
        but recurring) to an attacker-controlled address. The result is
        the on-chain truth; settlement still goes through the existing
        on-chain submission paths.

        :param ledger_api: the ledger API object.
        :param contract_address: the marketplace contract address.
        :param payment_type: the 32-byte ``paymentType`` selector read off
            the mech (matches the ``paymentType`` constant the marketplace
            uses to key its tracker registry).
        :return: a ``{"balance_tracker": "0x…"}`` dict matching the
            framework's ``GET_STATE`` response shape. ``0x0…0`` means the
            marketplace has no tracker registered for this paymentType.
        """
        ledger_api = cast(EthereumApi, ledger_api)
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        tracker = contract_instance.functions.mapPaymentTypeBalanceTrackers(
            payment_type
        ).call()
        return dict(balance_tracker=str(tracker))
