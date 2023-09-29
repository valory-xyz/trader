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

from typing import List, Dict

from requests.exceptions import ReadTimeout as RequestsReadTimeoutError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError
from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from hexbytes import HexBytes
from web3.types import BlockIdentifier


DEFAULT_FROM_BLOCK = "earliest"
DEFAULT_TO_BLOCK = "latest"


class ConditionalTokensContract(Contract):
    """The ConditionalTokens smart contract."""

    contract_id = PublicId.from_str("valory/conditional_tokens:0.1.0")

    @classmethod
    def check_redeemed(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        redeemer: str,
        collateral_tokens: List[str],
        parent_collection_ids: List[bytes],
        condition_ids: List[HexBytes],
        index_sets: List[List[int]],
        from_block_numbers: Dict[HexBytes, BlockIdentifier],
        chunk_size: int = 10_000,
    ) -> JSONLike:
        """Filter to find out whether a position has already been redeemed."""
        earliest_block = DEFAULT_FROM_BLOCK
        earliest_condition_id = HexBytes("")

        for condition_id, from_block in from_block_numbers.items():
            if (
                isinstance(earliest_block, int)
                and earliest_block > from_block
                or earliest_block == DEFAULT_FROM_BLOCK
            ):
                earliest_block = from_block
                earliest_condition_id = condition_id

        contract_instance = cls.get_instance(ledger_api, contract_address)
        to_checksum = ledger_api.api.to_checksum_address
        redeemer_checksummed = to_checksum(redeemer)
        collateral_tokens_checksummed = [
            to_checksum(token) for token in collateral_tokens
        ]
        latest_block = ledger_api.api.eth.block_number
        try:
            redeemed = []
            for from_block in range(earliest_block, latest_block, chunk_size):
                to_block = min(from_block + chunk_size, latest_block)
                payout_filter = contract_instance.events.PayoutRedemption.build_filter()
                payout_filter.args.redeemer.match_single(redeemer_checksummed)
                payout_filter.args.collateralToken.match_any(*collateral_tokens_checksummed)
                payout_filter.args.parentCollectionId.match_any(*parent_collection_ids)
                payout_filter.args.conditionId.match_any(*condition_ids)
                payout_filter.args.indexSets.match_any(*index_sets)
                payout_filter.fromBlock = from_block
                payout_filter.toBlock = to_block
                redeemed_chunk = list(payout_filter.deploy(ledger_api.api).get_all_entries())
                redeemed.extend(redeemed_chunk)
        except (Urllib3ReadTimeoutError, RequestsReadTimeoutError):
            msg = (
                "The RPC timed out! This usually happens if the filtering is too wide. "
                f"The service tried to filter from block {earliest_block} to latest, "
                f"as the earliest market creation transaction took place at block {earliest_block}. "
                f"Did the creation happen too long in the past?\n"
                f"The market with condition id {earliest_condition_id!r} "
                f"is the oldest one and the block filtering was set based on it."
                "If the issue persists, try to decrease the value of `redeem_margin_days` "
                f"in the agent's configuration, based on the date corresponding to the block number {earliest_block}."
            )
            return dict(error=msg)

        payouts = {}
        for redeeming in redeemed:
            args = redeeming.get("args", {})
            condition_id = args.get("conditionId", None)
            payout = args.get("payout", 0)
            if condition_id is not None and payout > 0:
                payouts[condition_id] = payout

        return dict(payouts=payouts)

    @classmethod
    def check_resolved(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        condition_id: HexBytes,
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
        condition_id: HexBytes,
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
