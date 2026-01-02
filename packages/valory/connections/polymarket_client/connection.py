#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""Genai connection."""

import json
from typing import Any, Callable, Dict, Tuple, cast

from aea.configurations.base import PublicId
from aea.connections.base import BaseSyncConnection
from aea.mail.base import Envelope
from aea.protocols.base import Address, Message
from aea.protocols.dialogue.base import Dialogue
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.protocols.srr.dialogues import SrrDialogue
from packages.valory.protocols.srr.dialogues import SrrDialogues as BaseSrrDialogues
from packages.valory.protocols.srr.message import SrrMessage


PUBLIC_ID = PublicId.from_str("valory/polymarket_client:0.1.0")


class SrrDialogues(BaseSrrDialogues):
    """A class to keep track of SRR dialogues."""

    def __init__(self, **kwargs: Any) -> None:
        """
        Initialize dialogues.

        :param kwargs: keyword arguments
        """

        def role_from_first_message(  # pylint: disable=unused-argument
            message: Message, receiver_address: Address
        ) -> Dialogue.Role:
            """Infer the role of the agent from an incoming/outgoing first message

            :param message: an incoming/outgoing first message
            :param receiver_address: the address of the receiving agent
            :return: The role of the agent
            """
            return SrrDialogue.Role.CONNECTION

        BaseSrrDialogues.__init__(
            self,
            self_address=str(kwargs.pop("connection_id")),
            role_from_first_message=role_from_first_message,
            **kwargs,
        )


class PolymarketClientConnection(BaseSyncConnection):
    """Proxy to the functionality of the Genai library."""

    MAX_WORKER_THREADS = 1

    connection_id = PUBLIC_ID

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        """
        Initialize the connection.

        The configuration must be specified if and only if the following
        parameters are None: connection_id, excluded_protocols or restricted_to_protocols.

        Possible arguments:
        - configuration: the connection configuration.
        - data_dir: directory where to put local files.
        - identity: the identity object held by the agent.
        - crypto_store: the crypto store for encrypted communication.
        - restricted_to_protocols: the set of protocols ids of the only supported protocols for this connection.
        - excluded_protocols: the set of protocols ids that we want to exclude for this connection.

        :param args: arguments passed to component base
        :param kwargs: keyword arguments passed to component base
        """
        super().__init__(*args, **kwargs)
        self.connection_private_key = self.crypto_store.private_keys.get("ethereum")

        host = self.configuration.config.get("host")
        chain_id = self.configuration.config.get("chain_id")
        self.client = ClobClient(
            host,
            key=self.connection_private_key,
            chain_id=chain_id,
            signature_type=2,
            funder=self.safe_address,
        )
        self.client.set_api_creds(self.client.create_or_derive_api_creds())
        self.dialogues = SrrDialogues(connection_id=PUBLIC_ID)

    # TODO:
    @property
    def safe_address(self) -> Address:
        """Return the safe address."""
        return self.configuration.config.get("safe_contract_addresses").get("polygon")

    def main(self) -> None:
        """
        Run synchronous code in background.

        SyncConnection `main()` usage:
        The idea of the `main` method in the sync connection
        is to provide for a way to actively generate messages by the connection via the `put_envelope` method.

        A simple example is the generation of a message every second:
        ```
        while self.is_connected:
            envelope = make_envelope_for_current_time()
            self.put_enevelope(envelope)
            time.sleep(1)
        ```
        In this case, the connection will generate a message every second
        regardless of envelopes sent to the connection by the agent.
        For instance, this way one can implement periodically polling some internet resources
        and generate envelopes for the agent if some updates are available.
        Another example is the case where there is some framework that runs blocking
        code and provides a callback on some internal event.
        This blocking code can be executed in the main function and new envelops
        can be created in the event callback.
        """

    def on_send(self, envelope: Envelope) -> None:
        """
        Send an envelope.

        :param envelope: the envelope to send.
        """
        srr_message = cast(SrrMessage, envelope.message)

        dialogue = self.dialogues.update(srr_message)

        if srr_message.performative != SrrMessage.Performative.REQUEST:
            self.logger.error(
                f"Performative `{srr_message.performative.value}` is not supported."
            )
            return

        payload, error = self._route_request(
            payload=json.loads(srr_message.payload),
        )

        response_message = cast(
            SrrMessage,
            dialogue.reply(  # type: ignore
                performative=SrrMessage.Performative.RESPONSE,
                target_message=srr_message,
                payload=json.dumps(payload),
                error=error,
            ),
        )

        response_envelope = Envelope(
            to=envelope.sender,
            sender=envelope.to,
            message=response_message,
            context=envelope.context,
        )

        self.put_envelope(response_envelope)

    def on_connect(self) -> None:
        """
        Tear down the connection.

        Connection status set automatically.
        """

    def on_disconnect(self) -> None:
        """
        Tear down the connection.

        Connection status set automatically.
        """

    def _route_request(self, payload: Dict[str, Any]) -> Tuple[Any, str]:
        """Route the request to the appropriate method.

        :param payload: The request payload containing 'request_type' and 'params'
        :return: Tuple of (response_data, error_message)
        """
        request_type_str = payload.get("request_type")

        if not request_type_str:
            error_msg = "Missing 'request_type' in payload."
            self.logger.error(error_msg)
            return None, error_msg

        # Validate request type
        try:
            request_type = RequestType(request_type_str)
        except ValueError:
            valid_types = [rt.value for rt in RequestType]
            error_msg = f"Request type '{request_type_str}' not supported. Valid types: {valid_types}"
            self.logger.error(error_msg)
            return None, error_msg

        # Map request types to handler methods
        request_function_map: Dict[RequestType, Callable] = {
            RequestType.PLACE_BET: self._place_bet,
            RequestType.FETCH_MARKETS: self._fetch_markets,
            RequestType.FETCH_MARKET: self._fetch_market,
        }

        self.logger.info(f"Routing request of type: {request_type.value}")

        try:
            params = payload.get("params", {})
            response, error = request_function_map[request_type](**params)
            return response, bool(error)
        except TypeError as e:
            error_msg = f"Invalid parameters for '{request_type.value}': {str(e)}"
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Error executing '{request_type.value}': {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _test_connection(self) -> bool:
        """Test the connection to Polymarket."""
        try:
            ok = self.client.get_ok()
            self.logger.info(f"Polymarket connection test successful: {ok}")
            return True
        except Exception as e:
            self.logger.error(f"Polymarket connection test failed: {e}")
            return False

    def _place_bet(self, token_id: str, amount: float) -> None:
        """Place a bet on Polymarket."""

        mo = MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=BUY,
            order_type=OrderType.FOK,
        )
        signed = self.client.create_market_order(mo)
        try:
            resp: Dict = self.client.post_order(signed, OrderType.FOK)
            return resp, None
        except PolyApiException as e:
            self.logger.error(f"Error placing bet: {e}")
            return None, "Error placing bet: {e}"
        self.logger.info(f"Placed bet response: {resp}")
        if resp.get("errorMsg"):
            self.logger.error(f"Error placing bet: {resp['errorMsg']}")
            return None, resp["errorMsg"]

        return (
            resp["orderID"],
            resp["status"],
            resp.get("transactionHash") or resp.get("transactionsHashes"),
        )

    def _fetch_markets(self, next_cursor="MA==") -> Any:
        """Fetch current markets from Polymarket."""
        pass

    def _fetch_market(self, condition_id: str) -> Any:
        """Fetch a specific market from Polymarket."""
        pass
