# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

import logging
from typing import Any, Dict, List

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract as BaseContract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from hexbytes import HexBytes

from packages.valory.contracts.conditional_tokens.contract import (
    ConditionalTokensContract,
)

_logger = logging.getLogger(__name__)

PUBLIC_ID = PublicId.from_str("valory/market_maker:0.1.0")

# FPMMSell event topic0 — the keccak of the canonical event signature
# "FPMMSell(address,uint256,uint256,uint256,uint256)". Hardcoded to
# avoid re-computing per call; verified by the parse_sell_events tests
# in the contract's test_contract.py.
FPMM_SELL_TOPIC0 = HexBytes(
    "0xadcf2a240ed9300d681d9a3f5382b6c1beed1b7e46643e0c7b42cbe6e2d766b4"
)
_ADDRESS_HEX_LEN = 40
_WORD_BYTES = 32


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
        data = contract_instance.encode_abi(method_name, kwargs=kwargs)
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
        :return: the encoded transaction arguments
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
    def calc_sell_amount(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        return_amount: int,
        outcome_index: int,
    ) -> JSONLike:
        """Calculate the sell amount.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :param return_amount: the amount the user will have returned
        :param outcome_index: the index of the answer's outcome that the user wants to sell for
        :return: the outcomeTokenSellAmount
        """
        outcome_token_sell_amount = cls._method_call(
            ledger_api,
            contract_address,
            "calcSellAmount",
            returnAmount=return_amount,
            outcomeIndex=outcome_index,
        )
        return dict(amount=outcome_token_sell_amount)

    @classmethod
    def get_sell_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        return_amount: int,
        outcome_index: int,
        max_outcome_tokens_to_sell: int,
    ) -> Dict[str, bytes]:
        """Gets the encoded arguments for a sell tx, which should only be called via the multisig.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :param return_amount: the amount the user have returned
        :param outcome_index: the index of the answer's outcome that the user wants to sell tokens for
        :param max_outcome_tokens_to_sell: the output of the `calcSellAmount` contract method
        :return: the encoded transaction arguments
        """
        return cls._encode_abi(
            ledger_api,
            contract_address,
            "sell",
            returnAmount=return_amount,
            outcomeIndex=outcome_index,
            maxOutcomeTokensToSell=max_outcome_tokens_to_sell,
        )

    @classmethod
    def parse_sell_events(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,  # noqa: ARG003 - unused but required by framework
        receipt: Dict[str, Any],
    ) -> JSONLike:
        """Decode every ``FPMMSell`` log present in ``receipt``.

        Malformed logs (wrong topic count, missing ``data`` / ``address``,
        truncated payload, or any other shape that breaks decoding) are
        skipped individually with a warning rather than failing the whole
        call. Without this, a single non-conformant log would raise out
        through the framework's dispatch wrapper as
        ``"parse_sell_events dispatch failed"``, taking the entire
        receipt's audit trail with it.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address (unused; logs are filtered by topic)
        :param receipt: the transaction receipt dict
        :return: ``{"events": [{seller, fpmm, outcome_index, return_amount,
            fee_amount, outcome_tokens_sold}, ...]}``
        """
        events: List[Dict[str, Any]] = []
        for idx, log in enumerate(receipt.get("logs", []) or []):
            topics = log.get("topics", []) or []
            if not topics or HexBytes(topics[0]) != FPMM_SELL_TOPIC0:
                continue

            # Structural guards: tailored diagnostics for the common
            # malformations. FPMMSell signature is
            # (indexed seller, returnAmount, feeAmount, indexed outcomeIndex,
            # outcomeTokensSold) -> 3 topics (topic0 + seller + outcomeIndex)
            # and 3 words of data (96 bytes hex-decoded).
            if len(topics) < 3:
                _logger.warning(
                    "parse_sell_events: dropping log idx=%s with only %d "
                    "topics (need >=3); txHash=%s",
                    idx,
                    len(topics),
                    log.get("transactionHash"),
                )
                continue
            address = log.get("address")
            if not address:
                _logger.warning(
                    "parse_sell_events: dropping log idx=%s missing "
                    "'address'; txHash=%s",
                    idx,
                    log.get("transactionHash"),
                )
                continue
            data_hex = log.get("data")
            if not data_hex:
                _logger.warning(
                    "parse_sell_events: dropping log idx=%s from %s "
                    "missing 'data'; txHash=%s",
                    idx,
                    address,
                    log.get("transactionHash"),
                )
                continue

            # Safety net: any unexpected shape (truncated data, bad
            # hex, non-numeric topic) is logged and skipped without
            # losing the rest of the receipt.
            try:
                seller_padded = HexBytes(topics[1]).hex()
                seller = "0x" + seller_padded[-_ADDRESS_HEX_LEN:]
                outcome_index = int(HexBytes(topics[2]).hex(), 16)
                data = HexBytes(data_hex)
                return_amount = int.from_bytes(data[:_WORD_BYTES], "big")
                fee_amount = int.from_bytes(data[_WORD_BYTES : 2 * _WORD_BYTES], "big")
                outcome_tokens_sold = int.from_bytes(
                    data[2 * _WORD_BYTES : 3 * _WORD_BYTES], "big"
                )
                events.append(
                    {
                        "seller": ledger_api.api.to_checksum_address(seller),
                        "fpmm": ledger_api.api.to_checksum_address(address),
                        "outcome_index": outcome_index,
                        "return_amount": return_amount,
                        "fee_amount": fee_amount,
                        "outcome_tokens_sold": outcome_tokens_sold,
                    }
                )
            except (ValueError, TypeError) as exc:
                _logger.warning(
                    "parse_sell_events: dropping log idx=%s from %s; "
                    "decode failed: %r; txHash=%s",
                    idx,
                    address,
                    exc,
                    log.get("transactionHash"),
                )
                continue
        return {"events": events}

    @classmethod
    def get_pool_balances_via_ct(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        conditional_tokens_address: str,
        collateral_token: str,
        condition_id: str,
    ) -> JSONLike:
        """Read the FPMM's per-outcome ERC1155 reserves from ConditionalTokens.

        The Olas/Omen FPMM build does not expose ``getPoolBalances()`` (see
        §13.8 of the withdrawal spec), so we derive each outcome's
        ``positionId`` and read ``balanceOf(fpmm, positionId)`` on the
        ConditionalTokens contract instead.

        :param ledger_api: the ledger API object
        :param contract_address: the FPMM address whose pool balances are read
        :param conditional_tokens_address: the CT contract address
        :param collateral_token: the FPMM's collateral token address (wxDAI on
            Olas-touched Omen)
        :param condition_id: the FPMM's condition id (bytes32 hex)
        :return: ``{"balances": [outcome_0_balance, outcome_1_balance, ...]}``
        """
        ct_instance = ConditionalTokensContract.get_instance(
            ledger_api=ledger_api, contract_address=conditional_tokens_address
        )
        condition_id_b = HexBytes(condition_id)
        slot_count = int(
            ct_instance.functions.getOutcomeSlotCount(condition_id_b).call()
        )
        fpmm_checksum = ledger_api.api.to_checksum_address(contract_address)
        collateral_checksum = ledger_api.api.to_checksum_address(collateral_token)
        parent_collection_id = b"\x00" * _WORD_BYTES

        balances: List[int] = []
        for outcome_index in range(slot_count):
            collection_id = ct_instance.functions.getCollectionId(
                parent_collection_id, condition_id_b, 1 << outcome_index
            ).call()
            collection_id_int = int.from_bytes(collection_id, "big")
            position_id = int.from_bytes(
                ledger_api.api.solidity_keccak(
                    ["address", "uint256"],
                    [collateral_checksum, collection_id_int],
                ),
                "big",
            )
            balance = int(
                ct_instance.functions.balanceOf(fpmm_checksum, position_id).call()
            )
            balances.append(balance)
        return {"balances": balances}
