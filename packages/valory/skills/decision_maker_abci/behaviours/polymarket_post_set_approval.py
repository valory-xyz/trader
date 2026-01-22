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

from packages.valory.connections.polymarket_client.connection import (
    PUBLIC_ID as POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID,
)
from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketPostSetApprovalPayload,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_post_set_approval import (
    PolymarketPostSetApprovalRound,
)


class PolymarketPostSetApprovalBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents post set approval for Polymarket."""

    matching_round = PolymarketPostSetApprovalRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self.context.logger.info("Post set approval round - checking approvals...")
            
            # Check if approvals were set successfully
            yield from self._check_approval()

        yield from self.finish_behaviour(self.payload)

    def _check_approval(self) -> Generator[None, None, None]:
        """Check if approvals were set successfully."""
        # Get SRR dialogues
        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)

        # Create the request payload
        polymarket_check_approval_payload = {
            "request_type": RequestType.CHECK_APPROVAL.value,
            "params": {},
        }

        # Create the SRR message
        srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(polymarket_check_approval_payload),
        )

        # Send the request and wait for response
        response = yield from self.do_connection_request(srr_message, srr_dialogue)

        if response is None or response.error:
            error_msg = (
                response.error if response else "No response from Polymarket client"
            )
            self.context.logger.error(f"Error checking approvals: {error_msg}")
            self.payload = PolymarketPostSetApprovalPayload(
                self.context.agent_address,
                "error",
            )
            self._write_allowances_file(False)
            return

        # Parse the response
        response_json = json.loads(response.payload)
        self.context.logger.info(f"Approval check response: {response_json}")

        # Check if all approvals are set
        all_approvals_set = response_json.get("all_approvals_set", False)

        if all_approvals_set:
            self.context.logger.info("✅ All approvals are set successfully!")
            self.context.logger.info(
                f"USDC Allowances: {response_json.get('usdc_allowances', {})}"
            )
            self.context.logger.info(
                f"CTF Approvals: {response_json.get('ctf_approvals', {})}"
            )
        else:
            self.context.logger.warning(
                f"⚠️  Some approvals may not be set correctly: {response_json}"
            )

        # Create the payload with approval check result
        vote = "success" if all_approvals_set else "partial"
        self.payload = PolymarketPostSetApprovalPayload(
            self.context.agent_address,
            vote,
        )
        
        # Write the allowances file to persist the state
        self._write_allowances_file(all_approvals_set)

    def _write_allowances_file(self, allowances_set: bool) -> None:
        """Write the allowances file to persist the approval state."""
        allowances_path = self.params.store_path / "polymarket.json"
        allowances_data = {"allowances_set": allowances_set}
        
        try:
            with open(allowances_path, "w") as f:
                json.dump(allowances_data, f, indent=2)
            self.context.logger.info(
                f"Wrote allowances file: allowances_set={allowances_set}"
            )
        except Exception as e:
            self.context.logger.error(
                f"Failed to write allowances file: {e}"
            )

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
