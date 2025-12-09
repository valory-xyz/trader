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
from typing import Any, Callable, Dict, Generator, Optional, cast

from aea.protocols.base import Message
from aea.protocols.dialogue.base import Dialogue
from hexbytes import HexBytes

from packages.valory.connections.polymarket.connection import (
    PUBLIC_ID as POLYMARKET_CONNECTION_PUBLIC_ID,
)
from packages.valory.connections.polymarket.request_types import RequestType
from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WXDAI,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import BetPlacementPayload
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)


class PolymarketBetPlacementBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = PolymarketBetPlacementRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    def _send_message(
        self,
        message: Message,
        dialogue: Dialogue,
        callback: Callable,
        callback_kwargs: Optional[Dict] = None,
    ) -> None:
        """
        Send a message and set up a callback for the response.

        :param message: the Message to send
        :param dialogue: the Dialogue context
        :param callback: the callback function upon response
        :param callback_kwargs: optional kwargs for the callback
        """
        self.context.outbox.put_message(message=message)
        nonce = dialogue.dialogue_label.dialogue_reference[0]
        self.shared_state.req_to_callback[nonce] = (callback, callback_kwargs or {})

    def _send_polymarket_request(
        self,
        request_type: RequestType,
        function_kwargs: Optional[Dict] = None,
    ) -> None:
        # Prepare payload data
        payload_data = {"request_type": request_type, "params": function_kwargs or {}}

        self.context.logger.info(f"Payload data: {payload_data}")

        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)
        request_srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(POLYMARKET_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(payload_data),
        )

        callback_kwargs = {}
        self._send_message(
            request_srr_message,
            srr_dialogue,
            self._handle_polymarket_response,
            callback_kwargs,
        )

    def _handle_polymarket_response(
        self,
        polymarket_response: SrrMessage,
        dialogue: Dialogue,  # pylint: disable=unused-argument
    ) -> None:
        """Handle the response from the Polymarket connection."""
        self.context.logger.info(
            f"Received response from Polymarket connection: {polymarket_response}"
        )
        pass

    def async_act(self) -> Generator:
        """Do the action."""
        agent = self.context.agent_address

        # if self.benchmarking_mode.enabled:
        #     # simulate the bet placement
        #     with self.context.benchmark_tool.measure(self.behaviour_id).local():
        #         self.update_bet_transaction_information()
        #         payload = BetPlacementPayload(
        #             agent, None, None, True, self.wallet_balance
        #         )
        #     yield from self.finish_behaviour(payload)

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # yield from self.wait_for_condition_with_sleep(self.check_balance)
            # tx_submitter = betting_tx_hex = mocking_mode = wallet_balance = None

            # can_exchange = (
            #     self.is_wxdai
            #     # no need to take fees into consideration because it is the safe's balance and the agents pay the fees
            #     and self.wallet_balance >= self.w_xdai_deficit
            # )
            # if self.token_balance < self.investment_amount and can_exchange:
            #     yield from self.wait_for_condition_with_sleep(self._build_exchange_tx)

            # if self.token_balance >= self.investment_amount or can_exchange:
            #     tx_submitter = self.matching_round.auto_round_id()
            #     betting_tx_hex = yield from self._prepare_safe_tx()
            #     wallet_balance = self.wallet_balance

            # TODO:
            token_id = "102735511844904020595410598611509756778804847927475574790355219881974202889557"
            amount = 1
            self._send_polymarket_request(
                RequestType.PLACE_BET, {"token_id": token_id, "amount": amount}
            )
            payload = BetPlacementPayload(
                agent,
                "tx_submitter",
                "betting_tx_hex",
                None,
                None,
                is_polymarket=True,
            )

        yield from self.finish_behaviour(payload)
