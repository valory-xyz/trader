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

"""This module contains the behaviour for sampling a bet."""

import json
from typing import Any, Generator, cast

from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.connection import (
    PUBLIC_ID as POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID,
)
from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    MultisendBatch,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketSetApprovalPayload,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_set_approval import (
    PolymarketSetApprovalRound,
)


class PolymarketSetApprovalBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents set approval for Polymarket."""

    matching_round = PolymarketSetApprovalRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Check if builder program is enabled
            if self.context.params.polymarket_builder_program_enabled:
                self.context.logger.info(
                    "Polymarket builder program enabled - calling connection to set approvals..."
                )
                # Call the polymarket client to set approvals
                yield from self._set_approval()
            else:
                self.context.logger.info(
                    "Polymarket builder program disabled - preparing approval transaction..."
                )
                # Prepare Safe transaction for approvals
                tx_submitter = self.matching_round.auto_round_id()
                tx_hash = yield from self._prepare_approval_tx()

                self.payload = PolymarketSetApprovalPayload(
                    self.context.agent_address,
                    tx_submitter,
                    tx_hash,
                    False,
                )

        yield from self.finish_behaviour(self.payload)

    def _set_approval(self) -> Generator[None, None, None]:
        """Set approval for Polymarket contracts."""
        # Get SRR dialogues
        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)

        # Create the request payload
        polymarket_set_approval_payload = {
            "request_type": RequestType.SET_APPROVAL.value,
            "params": {},
        }

        # Create the SRR message
        srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(polymarket_set_approval_payload),
        )

        # Send the request and wait for response
        response = yield from self.do_connection_request(srr_message, srr_dialogue)

        if response is None or response.error:
            error_msg = (
                response.error if response else "No response from Polymarket client"
            )
            self.context.logger.error(f"Error setting approvals: {error_msg}")
            self.payload = PolymarketSetApprovalPayload(
                self.context.agent_address,
                None,
                None,
                False,
            )
            return

        # Parse the response
        response_json = json.loads(response.payload)
        self.context.logger.info(f"Set approval response: {response_json}")

        # Check if the approval was successful
        success = response_json is not None and not response.error

        if success:
            self.context.logger.info(
                "Successfully set approvals for Polymarket contracts!"
            )
            self.context.logger.info(f"Transaction data: {response_json}")
        else:
            self.context.logger.error(f"Failed to set approvals: {response_json}")

        # Create the payload
        self.payload = PolymarketSetApprovalPayload(
            self.context.agent_address,
            None,
            None,
            False,
        )

    def _prepare_approval_tx(self) -> Generator[None, None, str]:
        """Prepare Safe transaction for setting approvals."""
        # Get contract addresses from params
        usdc_address = self.params.polymarket_usdc_address
        ctf_address = self.params.polymarket_ctf_address
        ctf_exchange_address = self.params.polymarket_ctf_exchange_address
        neg_risk_ctf_exchange_address = (
            self.params.polymarket_neg_risk_ctf_exchange_address
        )
        neg_risk_adapter_address = self.params.polymarket_neg_risk_adapter_address

        # Build approval transactions and add to multisend_batches (must match
        # polymarket_client _check_approval: 3 USDC allowances + 3 CTF setApprovalForAll)
        # 1. USDC approve for CTF Exchange
        usdc_approve_batch = MultisendBatch(
            to=usdc_address,
            data=HexBytes(
                self._build_erc20_approve_data(ctf_exchange_address, 2**256 - 1)
            ),
            value=0,
        )
        self.multisend_batches.append(usdc_approve_batch)

        # 2. CTF setApprovalForAll for CTF Exchange
        ctf_approve1_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(ctf_exchange_address, True)
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve1_batch)

        # 3. USDC approve for NegRisk CTF Exchange (required for usdc_allowances.neg_risk_ctf_exchange)
        usdc_approve_neg_risk_ctf_batch = MultisendBatch(
            to=usdc_address,
            data=HexBytes(
                self._build_erc20_approve_data(
                    neg_risk_ctf_exchange_address, 2**256 - 1
                )
            ),
            value=0,
        )
        self.multisend_batches.append(usdc_approve_neg_risk_ctf_batch)

        # 4. CTF setApprovalForAll for NegRisk CTF Exchange
        ctf_approve2_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(
                    neg_risk_ctf_exchange_address, True
                )
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve2_batch)

        # 5. USDC approve for NegRisk Adapter (required for usdc_allowances.neg_risk_adapter)
        usdc_approve_neg_risk_adapter_batch = MultisendBatch(
            to=usdc_address,
            data=HexBytes(
                self._build_erc20_approve_data(neg_risk_adapter_address, 2**256 - 1)
            ),
            value=0,
        )
        self.multisend_batches.append(usdc_approve_neg_risk_adapter_batch)

        # 6. CTF setApprovalForAll for NegRisk Adapter
        ctf_approve3_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(neg_risk_adapter_address, True)
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve3_batch)

        # Build the multisend transaction directly (no balance check needed for approvals)
        success = yield from self._build_multisend_data()
        if not success:
            self.context.logger.error("Failed to build multisend data for approvals")
            return ""

        success = yield from self._build_multisend_safe_tx_hash()
        if not success:
            self.context.logger.error("Failed to build safe tx hash for approvals")
            return ""

        return self.tx_hex

    def _build_erc20_approve_data(self, spender: str, amount: int) -> str:
        """Build ERC20 approve function data."""
        # approve(address spender, uint256 amount)
        function_signature = "0x095ea7b3"  # keccak256("approve(address,uint256)")[:4]
        spender_padded = spender[2:].zfill(64).lower()  # Remove 0x and pad to 32 bytes
        amount_hex = hex(amount)[2:].zfill(64)  # Convert to hex and pad
        return f"{function_signature}{spender_padded}{amount_hex}"

    def _build_set_approval_for_all_data(self, operator: str, approved: bool) -> str:
        """Build ERC1155 setApprovalForAll function data."""
        # setApprovalForAll(address operator, bool approved)
        function_signature = (
            "0xa22cb465"  # keccak256("setApprovalForAll(address,bool)")[:4]
        )
        operator_padded = operator[2:].zfill(64).lower()
        approved_value = "1" if approved else "0"
        approved_padded = approved_value.zfill(64)
        return f"{function_signature}{operator_padded}{approved_padded}"

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
