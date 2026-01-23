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

"""This module contains the PolymarketSwapUsdcBehaviour of the 'DecisionMakerAbci' skill."""

import json
from typing import Generator, Optional, cast

from packages.valory.contracts.gnosis_safe.contract import (
    GnosisSafeContract,
    SafeOperation,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.ledger_api import LedgerApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketSwapPayload
from packages.valory.skills.decision_maker_abci.rounds import PolymarketSwapUsdcRound
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)


SAFE_TX_GAS = 0
ETHER_VALUE = 0

# Polygon network constants
POLYGON_CHAIN_ID = 137
POL_ADDRESS = "0x0000000000000000000000000000000000001010"  # Native POL on Polygon
USDC_ADDRESS = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"  # USDC on Polygon
LIFI_QUOTE_URL = "https://li.quest/v1/quote"
HTTP_OK = [200]
INTEGRATOR = "valory"


class PolymarketSwapUsdcBehaviour(DecisionMakerBaseBehaviour):
    """PolymarketSwapUsdcBehaviour"""

    matching_round = PolymarketSwapUsdcRound

    def async_act(self) -> Generator:
        """Implement the act."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            agent = self.context.agent_address
            if not self.params.is_running_on_polymarket:
                self.context.logger.info(
                    "[SwapPOLBehaviour] Not running on Polymarket network. Skipping swap."
                )
                payload = PolymarketSwapPayload(
                    sender=agent,
                    tx_submitter=None,
                    tx_hash=None,
                    should_swap=False,
                )
                yield from self.send_a2a_transaction(payload)
                self.set_done()
                return
            tx_hash = yield from self.get_tx_hash()
            if tx_hash is None:
                tx_submitter = None
                should_swap = False
            else:
                tx_submitter = self.matching_round.auto_round_id()
                should_swap = True
            payload = PolymarketSwapPayload(
                sender=agent,
                tx_submitter=tx_submitter,
                tx_hash=tx_hash,
                should_swap=should_swap,
            )
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
        self.set_done()

    def _get_balance(self, address: str) -> Generator[None, None, Optional[int]]:
        """Get the POL balance of the provided address on Polygon"""
        ledger_api_response = yield from self.get_ledger_api_response(
            performative=LedgerApiMessage.Performative.GET_STATE,  # type: ignore
            ledger_callable="get_balance",
            account=address,
            chain_id="polygon",
        )
        if ledger_api_response.performative != LedgerApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Couldn't get balance. "
                f"Expected response performative {LedgerApiMessage.Performative.STATE.value}, "  # type: ignore
                f"received {ledger_api_response.performative.value}."
            )
            return None
        balance = cast(int, ledger_api_response.state.body.get("get_balance_result"))
        self.context.logger.info(f"balance: {balance / 10 ** 18} POL")
        return balance

    def _get_safe_tx_hash(
        self,
        to_address: str,
        data: bytes,
        value: int = ETHER_VALUE,
        safe_tx_gas: int = SAFE_TX_GAS,
        operation: int = SafeOperation.CALL.value,
    ) -> Generator[None, None, Optional[str]]:
        """Prepares and returns the safe tx hash."""
        response = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=to_address,  # the contract the safe will invoke
            value=value,
            data=data,
            safe_tx_gas=safe_tx_gas,
            operation=operation,
            chain_id="polygon",
        )
        if response.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Couldn't get safe hash. "
                f"Expected response performative {ContractApiMessage.Performative.STATE.value}, "  # type: ignore
                f"received {response.performative.value}."
            )
            return None

        # strip "0x" from the response hash
        tx_hash = cast(str, response.state.body["tx_hash"])[2:]
        return tx_hash

    def get_tx_hash(self) -> Generator[None, None, Optional[str]]:
        """Get the tx_hash for swapping POL to USDC."""
        safe_address = self.synchronized_data.safe_contract_address
        balance = yield from self._get_balance(safe_address)
        if balance is None:
            self.context.logger.error("[SwapPOLBehaviour] Couldn't get balance.")
            return None

        self.context.logger.info(
            f"[SwapPOLBehaviour] POL balance: {balance} wei ({balance / 10**18} POL)"
        )

        # Check if the balance is above threshold
        if balance <= self.params.pol_threshold_for_swap:
            self.context.logger.info(
                f"[SwapPOLBehaviour] Balance {balance} below or equal to threshold {self.params.pol_threshold_for_swap}."
            )
            return None

        self.context.logger.info("[SwapPOLBehaviour] Proceeding with swap")

        # Leave pol threshold in the safe for non-swap purposes
        balance_to_swap = balance - self.params.pol_threshold_for_swap
        self.context.logger.info(
            f"[SwapPOLBehaviour] Amount to swap: {balance_to_swap} wei ({balance_to_swap / 10**18} POL)"
        )

        # Get LiFi quote for POL -> USDC swap
        quote = yield from self._get_lifi_quote(safe_address, balance_to_swap)
        if quote is None:
            self.context.logger.error("[SwapPOLBehaviour] Failed to get LiFi quote.")
            return None

        # Extract transaction data from quote
        tx_request = quote.get("transactionRequest")
        if not tx_request:
            self.context.logger.error(
                "[SwapPOLBehaviour] No transaction request in quote."
            )
            return None

        lifi_contract = tx_request.get("to")
        tx_data_hex = tx_request.get("data")
        tx_value = (
            int(tx_request.get("value", "0"), 16)
            if isinstance(tx_request.get("value"), str)
            else tx_request.get("value", 0)
        )

        if not lifi_contract or not tx_data_hex:
            self.context.logger.error(
                "[SwapPOLBehaviour] Missing LiFi contract address or transaction data."
            )
            return None

        self.context.logger.info(f"[SwapPOLBehaviour] LiFi contract: {lifi_contract}")
        self.context.logger.info(
            f"[SwapPOLBehaviour] Transaction value: {tx_value} wei"
        )

        try:
            tx_data = bytes.fromhex(
                tx_data_hex[2:] if tx_data_hex.startswith("0x") else tx_data_hex
            )
        except Exception as e:
            self.context.logger.error(
                f"[SwapPOLBehaviour] Failed to decode transaction data: {e}"
            )
            return None

        # Create safe transaction directly to LiFi contract (no multisend needed for single call)
        safe_tx_hash = yield from self._get_safe_tx_hash(
            to_address=lifi_contract,
            data=tx_data,
            value=tx_value,  # POL value to send
            safe_tx_gas=SAFE_TX_GAS,
            operation=SafeOperation.CALL.value,
        )

        if safe_tx_hash is None:
            self.context.logger.error(
                "[SwapPOLBehaviour] _get_safe_tx_hash() output is None."
            )
            return None

        self.context.logger.info(f"[SwapPOLBehaviour] Safe tx hash: {safe_tx_hash}")

        tx_payload_data = hash_payload_to_hex(
            safe_tx_hash=safe_tx_hash,
            ether_value=tx_value,
            safe_tx_gas=SAFE_TX_GAS,
            to_address=lifi_contract,
            data=tx_data,
            operation=SafeOperation.CALL.value,
        )
        return tx_payload_data

    def _get_lifi_quote(
        self, from_address: str, amount: int
    ) -> Generator[None, None, Optional[dict]]:
        """Get a quote from LiFi for swapping POL to USDC."""
        params = {
            "fromChain": str(POLYGON_CHAIN_ID),
            "toChain": str(POLYGON_CHAIN_ID),
            "fromToken": POL_ADDRESS,
            "toToken": USDC_ADDRESS,
            "fromAmount": str(amount),
            "fromAddress": from_address,
            "toAddress": from_address,
            "integrator": INTEGRATOR,
        }

        self.context.logger.info(
            f"[SwapPOLBehaviour] Fetching LiFi quote with params: {params}"
        )

        response = yield from self.get_http_response(
            method="GET",
            url=LIFI_QUOTE_URL,
            headers={"accept": "application/json"},
            parameters=params,
        )

        if response.status_code not in HTTP_OK:
            self.context.logger.error(
                f"[SwapPOLBehaviour] LiFi API returned status {response.status_code}: {response.body!r}"
            )
            return None

        try:
            quote = json.loads(response.body)
            self.context.logger.info(
                "[SwapPOLBehaviour] Received LiFi quote successfully"
            )
            return quote
        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"[SwapPOLBehaviour] Failed to parse LiFi quote: {e}"
            )
            return None
