# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
                    "Polymarket builder program disabled - skipping connection call"
                )
                # Create payload without calling connection
                self.payload = PolymarketSetApprovalPayload(
                    self.context.agent_address,
                    None,
                    None,
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
            error_msg = response.error if response else "No response from Polymarket client"
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
            self.context.logger.info("Successfully set approvals for Polymarket contracts!")
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

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
