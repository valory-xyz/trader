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

"""This module contains the conditional tokens contract definition."""

from typing import List

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from web3.types import BlockIdentifier


class ConditionalTokensContract(Contract):
    """The ConditionalTokens smart contract."""

    contract_id = PublicId.from_str("valory/conditional_tokens:0.1.0")

    @classmethod
    def check_redeemed(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        redeemer: str,
        collateral_token: str,
        parent_collection_id: bytes,
        condition_id: bytes,
        index_sets: List[int],
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Filter to find out whether a position has already been redeemed."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        to_checksum = ledger_api.api.to_checksum_address
        redeemer_checksummed = to_checksum(redeemer)
        collateral_token_checksummed = to_checksum(collateral_token)

        payout_filter = contract_instance.events.PayoutRedemption.build_filter()
        payout_filter.fromBlock = from_block
        payout_filter.toBlock = to_block
        payout_filter.args.redeemer.match_single(redeemer_checksummed)
        payout_filter.args.collateral_token.match_single(collateral_token_checksummed)
        payout_filter.args.parent_collection_id.match_single(parent_collection_id)
        payout_filter.args.condition_id.match_single(condition_id)
        payout_filter.args.index_sets.match_single(index_sets)

        redeemed = list(payout_filter.deploy(ledger_api.api).get_all_entries())
        n_redeemed = len(redeemed)

        if n_redeemed == 0:
            return dict(redeemed=False)
        return dict(redeemed=True)

    @classmethod
    def check_resolved(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        condition_id: str,
    ) -> JSONLike:
        """Check whether a position has already been resolved."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        payout_denominator = contract_instance.functions.payoutDenominator
        payout = payout_denominator(condition_id).call()
        if payout == 0:
            return dict(resolved=False)
        return dict(resolved=True)

    @classmethod
    def build_redeem_positions_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        collateral_token: str,
        parent_collection_id: bytes,
        condition_id: bytes,
        index_sets: List[int],
    ) -> JSONLike:
        """Build a `redeemPositions` tx."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI(
            fn_name="redeemPositions",
            args=[
                ledger_api.api.to_checksum_address(collateral_token),
                parent_collection_id,
                condition_id,
                index_sets,
            ],
        )
        return dict(data=data)
