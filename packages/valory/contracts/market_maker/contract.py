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

"""This module contains the class to connect to a Market Maker contract."""

from typing import Any, Dict

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract as BaseContract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/market_maker:0.1.0")


class Contract(BaseContract):
    """Extended abstract definition of a contract."""

    @classmethod
    def _method_call(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        method_name: str,
        **kwargs: Any,
    ):
        """Call a contract's method.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :param method_name: the contract method to call
        :param kwargs: the contract call parameters
        :return: the call result
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        return ledger_api.contract_method_call(
            contract_instance,
            method_name,
            **kwargs,
        )

    @classmethod
    def _encode_abi(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        method_name: str,
        **kwargs: Any,
    ) -> Dict[str, bytes]:
        """Gets the encoded data for a contract's method call.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :param method_name: the contract method to call
        :param kwargs: the contract call parameters
        :return: the call result
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encodeABI(method_name, kwargs=kwargs)
        return {"data": bytes.fromhex(data[2:])}


class FixedProductMarketMakerContract(Contract):
    """The Market Maker contract."""

    contract_id = PUBLIC_ID

    @classmethod
    def calc_buy_amount(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        investment_amount: int,
        outcome_index: int,
    ) -> JSONLike:
        """
        Calculate the buy amount.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :param investment_amount: the amount the user is willing to invest for an answer
        :param outcome_index: the index of the answer's outcome that the user wants to vote for
        :return: the buy amount
        """
        amount = cls._method_call(
            ledger_api,
            contract_address,
            "calcBuyAmount",
            investmentAmount=investment_amount,
            outcomeIndex=outcome_index,
        )
        return dict(amount=amount)

    @classmethod
    def get_buy_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        investment_amount: int,
        outcome_index: int,
        min_outcome_tokens_to_buy: int,
    ) -> Dict[str, bytes]:
        """Gets the encoded arguments for a buy tx, which should only be called via the multisig.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :param investment_amount: the amount the user is willing to invest for an answer
        :param outcome_index: the index of the answer's outcome that the user wants to vote for
        :param min_outcome_tokens_to_buy: the output of the `calcBuyAmount` contract method
        """
        return cls._encode_abi(
            ledger_api,
            contract_address,
            "buy",
            investmentAmount=investment_amount,
            outcomeIndex=outcome_index,
            minOutcomeTokensToBuy=min_outcome_tokens_to_buy,
        )

    @classmethod
    def check_funding_removed(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: int,
        to_block: int,
        collateral_tokens: List[str],
        parent_collection_ids: List[bytes],
        condition_ids: List[HexBytes],
        index_sets: List[List[int]],
        timeout: float = FIVE_MINUTES,
    ) -> JSONLike:
        """Filter to find out whether a position has already been redeemed."""

        def get_funding_removed_events() -> Union[List[Dict[str, Any]], str]:
            """Get the redeem events."""
            contract_instance = cls.get_instance(ledger_api, contract_address)
            to_checksum = ledger_api.api.to_checksum_address
            redeemer_checksummed = to_checksum(redeemer)
            collateral_tokens_checksummed = [
                to_checksum(token) for token in collateral_tokens
            ]
            try:
                payout_filter = contract_instance.events.PayoutRedemption.build_filter()
                payout_filter.args.redeemer.match_single(redeemer_checksummed)
                payout_filter.args.collateralToken.match_any(
                    *collateral_tokens_checksummed
                )
                payout_filter.args.parentCollectionId.match_any(*parent_collection_ids)
                payout_filter.args.conditionId.match_any(*condition_ids)
                payout_filter.args.indexSets.match_any(*index_sets)
                payout_filter.fromBlock = from_block
                payout_filter.toBlock = to_block
                redeemed = list(payout_filter.deploy(ledger_api.api).get_all_entries())
                return redeemed

            except (Urllib3ReadTimeoutError, RequestsReadTimeoutError):
                msg = (
                    "The RPC timed out! This usually happens if the filtering is too wide. "
                    f"The service tried to filter from block {from_block} to {to_block}. "
                    f"If this issue persists, please try lowering the `EVENT_FILTERING_BATCH_SIZE`!"
                )
                return msg

        redeemed, err = cls.execute_with_timeout(get_redeem_events, timeout)
        if err is not None:
            return dict(error=err)

        payouts = {}
        for redeeming in redeemed:
            args = redeeming.get("args", {})
            condition_id = args.get("conditionId", None)
            payout = args.get("payout", 0)
            if condition_id is not None and payout > 0:
                if isinstance(condition_id, bytes):
                    condition_id = condition_id.hex()
                payouts[condition_id] = payout

        return dict(payouts=payouts)
