# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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

"""This module contains the handler for the 'decision_maker_abci' skill."""

import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, cast
from urllib.parse import urlparse

from aea.protocols.base import Message

from packages.valory.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.protocols.ipfs import IpfsMessage
from packages.valory.skills.abstract_round_abci.base import RoundSequence
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import AbstractResponseHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.chatui_abci.handlers import HttpHandler as BaseHttpHandler
from packages.valory.skills.decision_maker_abci.dialogues import (
    HttpDialogue,
    HttpDialogues,
)
from packages.valory.skills.decision_maker_abci.models import SharedState
from packages.valory.skills.decision_maker_abci.rounds import SynchronizedData
from packages.valory.skills.decision_maker_abci.rounds_info import (
    load_rounds_info_with_transitions,
)


ABCIHandler = BaseABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler


FSM_REPR_MAX_DEPTH = 25


class IpfsHandler(AbstractResponseHandler):
    """IPFS message handler."""

    SUPPORTED_PROTOCOL = IpfsMessage.protocol_id
    allowed_response_performatives = frozenset({IpfsMessage.Performative.IPFS_HASH})
    custom_support_performative = IpfsMessage.Performative.FILES

    @property
    def shared_state(self) -> SharedState:
        """Get the parameters."""
        return cast(SharedState, self.context.state)

    def handle(self, message: IpfsMessage) -> None:
        """
        Implement the reaction to an IPFS message.

        :param message: the message
        :return: None
        """
        self.context.logger.debug(f"Received message: {message}")
        self.shared_state.in_flight_req = False

        if message.performative != self.custom_support_performative:
            return super().handle(message)

        dialogue = self.context.ipfs_dialogues.update(message)
        nonce = dialogue.dialogue_label.dialogue_reference[0]
        callback = self.shared_state.req_to_callback.pop(nonce)
        callback(message, dialogue)


OK_CODE = 200
NOT_FOUND_CODE = 404
BAD_REQUEST_CODE = 400
TOO_EARLY_CODE = 425
AVERAGE_PERIOD_SECONDS = 10


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


class HttpHandler(BaseHttpHandler):
    """This implements the echo handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the HTTP handler."""
        super().__init__(**kwargs)
        self.handler_url_regex: str = ""
        self.routes: Dict[tuple, list] = {}
        self.json_content_header: str = ""
        self.rounds_info: Dict = {}

    def setup(self) -> None:
        """Implement the setup."""
        super().setup()
        config_uri_base_hostname = urlparse(
            self.context.params.service_endpoint
        ).hostname

        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        local_ip_regex = r"192\.168(\.\d{1,3}){2}"

        # Route regexes
        hostname_regex = rf".*({config_uri_base_hostname}|{propel_uri_base_hostname}|{local_ip_regex}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        self.handler_url_regex = rf"{hostname_regex}\/.*"
        health_url_regex = rf"{hostname_regex}\/healthcheck"

        # Routes
        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                (health_url_regex, self._handle_get_health),
            ],
        }

        self.json_content_header = "Content-Type: application/json\n"

        self.rounds_info = load_rounds_info_with_transitions()

    @property
    def round_sequence(self) -> RoundSequence:
        """Return the round sequence."""
        return self.context.state.round_sequence

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(db=self.round_sequence.latest_synchronized_data.db)

    def _get_handler(self, url: str, method: str) -> Tuple[Optional[Callable], Dict]:
        """Check if an url is meant to be handled in this handler

        We expect url to match the pattern {hostname}/.*,
        where hostname is allowed to be localhost, 127.0.0.1 or the service_endpoint's hostname.

        :param url: the url to check
        :param method: the method
        :returns: the handling method if the message is intended to be handled by this handler, None otherwise, and the regex captures
        """
        # Check base url
        if not re.match(self.handler_url_regex, url):
            self.context.logger.info(
                f"The url {url} does not match the HttpHandler's pattern"
            )
            return None, {}

        # Check if there is a route for this request
        for methods, routes in self.routes.items():
            if method not in methods:
                continue

            for route in routes:
                # Routes are tuples like (route_regex, handle_method)
                m = re.match(route[0], url)
                if m:
                    return route[1], m.groupdict()

        # No route found
        self.context.logger.info(
            f"The message [{method}] {url} is intended for the HttpHandler but did not match any valid pattern"
        )
        return self._handle_bad_request, {}

    def handle(self, message: Message) -> None:
        """
        Implement the reaction to an envelope.

        :param message: the message
        """
        http_msg = cast(HttpMessage, message)

        # Check if this is a request sent from the http_server skill
        if (
            http_msg.performative != HttpMessage.Performative.REQUEST
            or message.sender != str(HTTP_SERVER_PUBLIC_ID.without_hash())
        ):
            super().handle(message)
            return

        # Check if this message is for this skill. If not, send to super()
        handler, kwargs = self._get_handler(http_msg.url, http_msg.method)
        if not handler:
            super().handle(message)
            return

        # Retrieve dialogues
        http_dialogues = cast(HttpDialogues, self.context.http_dialogues)
        http_dialogue = cast(HttpDialogue, http_dialogues.update(http_msg))

        # Invalid message
        if http_dialogue is None:
            self.context.logger.info(
                "Received invalid http message={}, unidentified dialogue.".format(
                    http_msg
                )
            )
            return

        # Handle message
        self.context.logger.info(
            "Received http request with method={}, url={} and body={!r}".format(
                http_msg.method,
                http_msg.url,
                http_msg.body,
            )
        )
        handler(http_msg, http_dialogue, **kwargs)

    def _handle_bad_request(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a Http bad request.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=BAD_REQUEST_CODE,
            status_text="Bad request",
            headers=http_msg.headers,
            body=b"",
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _has_transitioned(self) -> bool:
        """Check if the agent has transitioned."""
        try:
            return bool(self.round_sequence.last_round_transition_height)
        except ValueError:
            return False

    def _handle_too_early(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a request when the FSM's loop has not started yet.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=TOO_EARLY_CODE,
            status_text="The state machine has not started yet! Please try again later...",
            headers=http_msg.headers,
            body=b"",
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _handle_get_health(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a Http request of verb GET.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        if not self._has_transitioned():
            self._handle_too_early(http_msg, http_dialogue)
            return

        has_required_funds = self._check_required_funds()
        is_receiving_mech_responses = self._check_is_receiving_mech_responses()
        is_staking_kpi_met = self.synchronized_data.is_staking_kpi_met
        staking_status = self.synchronized_data.service_staking_state.name.lower()

        round_sequence = self.round_sequence
        is_tm_unhealthy = round_sequence.block_stall_deadline_expired

        current_time = datetime.now().timestamp()
        seconds_since_last_transition = current_time - datetime.timestamp(
            round_sequence.last_round_transition_timestamp
        )

        abci_app = self.round_sequence.abci_app
        previous_rounds = abci_app._previous_rounds
        previous_round_cls = type(previous_rounds[-1])
        previous_round_events = abci_app.transition_function.get(
            previous_round_cls, {}
        ).keys()
        previous_round_timeouts = {
            abci_app.event_to_timeout.get(event, -1) for event in previous_round_events
        }
        last_round_timeout = max(previous_round_timeouts)
        is_transitioning_fast = (
            not is_tm_unhealthy
            and seconds_since_last_transition < 2 * last_round_timeout
        )

        rounds = [r.round_id for r in previous_rounds[-FSM_REPR_MAX_DEPTH:]] + [
            round_sequence.current_round_id
        ]

        data = {
            "seconds_since_last_transition": seconds_since_last_transition,
            "is_tm_healthy": not is_tm_unhealthy,
            "period": self.synchronized_data.period_count,
            "reset_pause_duration": self.context.params.reset_pause_duration,
            "rounds": rounds,
            "is_transitioning_fast": is_transitioning_fast,
            "agent_health": {
                "is_making_on_chain_transactions": is_receiving_mech_responses,
                "is_staking_kpi_met": is_staking_kpi_met,
                "has_required_funds": has_required_funds,
                "staking_status": staking_status,
            },
            "rounds_info": self.rounds_info,
        }

        self._send_ok_response(http_msg, http_dialogue, data)

    def _send_ok_response(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue, data: Dict
    ) -> None:
        """Send an OK response with the provided data"""
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=OK_CODE,
            status_text="Success",
            headers=f"{self.json_content_header}{http_msg.headers}",
            body=json.dumps(data).encode("utf-8"),
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_not_found_response(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Send a not found response"""
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=NOT_FOUND_CODE,
            status_text="Not found",
            headers=http_msg.headers,
            body=b"",
        )
        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _check_required_funds(self) -> bool:
        """Check the agent has enough funds."""
        return (
            self.synchronized_data.wallet_balance
            > self.context.params.agent_balance_threshold
        )

    def _check_is_receiving_mech_responses(self) -> bool:
        """Check the agent is making on chain transactions."""
        # Checks the most recent decision receive timestamp, which can only be returned after making a mech call
        # (an on chain transaction)
        return (
            self.synchronized_data.decision_receive_timestamp
            < int(datetime.now(timezone.utc).timestamp())
            - self.context.params.expected_mech_response_time
        )
