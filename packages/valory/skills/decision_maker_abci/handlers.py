# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, cast
from urllib.parse import urlparse

import prometheus_client
from aea.protocols.base import Message
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from packages.valory.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.protocols.ipfs import IpfsMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import AbstractResponseHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
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
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.dialogues import (
    HttpDialogue,
    HttpDialogues,
)
from packages.valory.skills.decision_maker_abci.models import SharedState
from packages.valory.skills.decision_maker_abci.rounds import SynchronizedData


ABCIHandler = BaseABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler


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
AVERAGE_PERIOD_SECONDS = 10


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


class HttpHandler(
    BaseHttpHandler,
):
    """This implements the echo handler."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the behaviour."""
        super().__init__(**kwargs)
        self._time_since_last_successful_mech_tx: int = 0

    @property
    def time_since_last_successful_mech_tx(self) -> int:
        """Get the time since the last successful mech response in seconds."""
        return self._time_since_last_successful_mech_tx

    @time_since_last_successful_mech_tx.setter
    def time_since_last_successful_mech_tx(
        self, time_since_last_successful_mech_tx: int
    ) -> None:
        """Set the time since the last successful mech response in seconds."""
        self._time_since_last_successful_mech_tx = time_since_last_successful_mech_tx

    def setup(self) -> None:
        """Implement the setup."""
        config_uri_base_hostname = urlparse(
            self.context.params.service_endpoint
        ).hostname

        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        local_ip_regex = r"192\.168(\.\d{1,3}){2}"

        # Route regexes
        self.hostname_regex = rf".*({config_uri_base_hostname}|{propel_uri_base_hostname}|{local_ip_regex}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        self.handler_url_regex = rf"{self.hostname_regex}\/.*"
        health_url_regex = rf"{self.hostname_regex}\/healthcheck"
        metrics_url_regex = rf"{self.hostname_regex}\/metrics"

        # Routes
        self.routes = {
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                (health_url_regex, self._handle_get_health),
                (metrics_url_regex, self._handle_get_metrics),
            ],
        }

        self.json_content_header = "Content-Type: application/json\n"

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(
            db=self.context.state.round_sequence.latest_synchronized_data.db
        )

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
                f"The url {url} does not match the DynamicNFT HttpHandler's pattern"
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
            f"The message [{method}] {url} is intended for the DynamicNFT HttpHandler but did not match any valid pattern"
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

    def _handle_get_health(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """
        Handle a Http request of verb GET.

        :param http_msg: the http message
        :param http_dialogue: the http dialogue
        """
        seconds_since_last_transition = None
        is_tm_unhealthy = None
        is_transitioning_fast = None
        current_round = None
        rounds = None
        has_required_funds = self._check_required_funds()
        is_receiving_mech_responses = self._check_is_receiving_mech_responses()
        is_staking_kpi_met = self.synchronized_data.is_staking_kpi_met
        staking_status = self.synchronized_data.service_staking_state.name.lower()

        round_sequence = cast(SharedState, self.context.state).round_sequence

        if round_sequence._last_round_transition_timestamp:
            is_tm_unhealthy = cast(
                SharedState, self.context.state
            ).round_sequence.block_stall_deadline_expired

            current_time = datetime.now().timestamp()
            seconds_since_last_transition = current_time - datetime.timestamp(
                round_sequence._last_round_transition_timestamp
            )

            is_transitioning_fast = (
                not is_tm_unhealthy
                and seconds_since_last_transition
                < 2 * self.context.params.reset_pause_duration
            )

        if round_sequence._abci_app:
            current_round = round_sequence._abci_app.current_round.round_id
            rounds = [
                r.round_id for r in round_sequence._abci_app._previous_rounds[-25:]
            ]
            rounds.append(current_round)

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
        """Send an not found response"""
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
            < int(datetime.utcnow().timestamp())
            - self.context.params.expected_mech_response_time
        )

    def _handle_get_metrics(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle the /metrics endpoint."""

        self.set_metrics()
        # Generate the metrics data
        metrics_data = generate_latest(REGISTRY)

        # Create a response with the metrics data
        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=OK_CODE,
            status_text="Success",
            headers=f"Content-Type: {prometheus_client.CONTENT_TYPE_LATEST}\n{http_msg.headers}",
            body=metrics_data,
        )

        # Send response
        self.context.logger.info("Responding with metrics data")
        self.context.outbox.put_message(message=http_response)

    def set_metrics(self) -> None:
        """Set the metrics."""

        agent_address = self.context.agent_address
        safe_address = self.synchronized_data.safe_contract_address
        service_id = self.context.params.on_chain_service_id

        native_balance = DecisionMakerBaseBehaviour.wei_to_native(
            self.synchronized_data.wallet_balance
        )
        wxdai_balance = self.synchronized_data.token_balance
        staking_contract_available_slots = (
            self.synchronized_data.available_staking_slots
        )
        staking_state = self.synchronized_data.service_staking_state.value
        time_since_last_successful_mech_tx = (
            self.calculate_time_since_last_successful_mech_tx()
        )
        time_since_last_mech_tx_attempt = (
            self.calculate_time_since_last_mech_tx_attempt()
        )
        n_total_mech_requests = self.synchronized_data.n_mech_requests
        n_successful_mech_requests = len(self.synchronized_data.mech_responses)
        n_failed_mech_requests = n_total_mech_requests - n_successful_mech_requests

        NATIVE_BALANCE_GAUGE.labels(agent_address, safe_address, service_id).set(
            native_balance
        )
        WXDAI_BALANCE_GAUGE.labels(agent_address, safe_address, service_id).set(
            wxdai_balance
        )
        STAKING_CONTRACT_AVAILABLE_SLOTS_GAUGE.labels(
            agent_address, safe_address, service_id
        ).set(staking_contract_available_slots)
        STAKING_STATE_GAUGE.labels(agent_address, safe_address, service_id).set(
            staking_state
        )
        TIME_SINCE_LAST_SUCCESSFUL_MECH_TX_GAUGE.labels(
            agent_address, safe_address, service_id
        ).set(time_since_last_successful_mech_tx)
        TIME_SINCE_LAST_MECH_TX_ATTEMPT_GAUGE.labels(
            agent_address, safe_address, service_id
        ).set(time_since_last_mech_tx_attempt)
        TOTAL_MECH_TXS.labels(agent_address, safe_address, service_id).set(
            n_total_mech_requests
        )
        TOTAL_SUCCESSFUL_MECH_TXS.labels(agent_address, safe_address, service_id).set(
            n_successful_mech_requests
        )
        TOTAL_FAILED_MECH_TXS.labels(agent_address, safe_address, service_id).set(
            n_failed_mech_requests
        )

    def calculate_time_since_last_successful_mech_tx(self) -> int:
        """Calculate the time since the last successful mech transaction (mech response)."""

        previous_time_since_last_successful_mech_tx = (
            self.time_since_last_successful_mech_tx
        )
        mech_tx_ts = self.synchronized_data.decision_receive_timestamp
        now = int(datetime.now().timestamp())
        seconds_since_last_successful_mech_tx = 0

        if mech_tx_ts != 0:
            seconds_since_last_successful_mech_tx = now - mech_tx_ts
            self.time_since_last_successful_mech_tx = (
                seconds_since_last_successful_mech_tx
            )

        elif previous_time_since_last_successful_mech_tx != 0:
            seconds_since_last_successful_mech_tx = (
                now - previous_time_since_last_successful_mech_tx
            )

        return seconds_since_last_successful_mech_tx

    def calculate_time_since_last_mech_tx_attempt(self) -> int:
        """Calculate the time since the last attempted mech transaction (mech request)."""

        mech_tx_attempt_ts = self.synchronized_data.decision_request_timestamp
        now = int(datetime.now().timestamp())

        if mech_tx_attempt_ts == 0:
            return 0

        seconds_since_last_mech_tx_attempt = now - mech_tx_attempt_ts
        return seconds_since_last_mech_tx_attempt


REGISTRY = CollectorRegistry()

NATIVE_BALANCE_GAUGE = Gauge(
    "olas_agent_native_balance",
    "Native token balance in xDai",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

OLAS_BALANCE_GAUGE = Gauge(
    "olas_agent_olas_balance",
    "OLAS token balance",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

WXDAI_BALANCE_GAUGE = Gauge(
    "olas_agent_wxdai_balance",
    "WXDAI token balance",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

STAKING_CONTRACT_AVAILABLE_SLOTS_GAUGE = Gauge(
    "olas_staking_contract_available_slots",
    "Number of available slots in the staking contract",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

STAKING_STATE_GAUGE = Gauge(
    "olas_agent_staked",
    "Indicates if an agent is staked (1), not staked (0) or eviceted (2)",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

TIME_SINCE_LAST_SUCCESSFUL_MECH_TX_GAUGE = Gauge(
    "olas_agent_time_since_last_successful_tx",
    "Time in seconds since last successful mech transaction",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

TIME_SINCE_LAST_MECH_TX_ATTEMPT_GAUGE = Gauge(
    "olas_agent_time_since_last_mech_tx_attempt",
    "Time in seconds since last transaction attempt (successful or not)",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

TOTAL_MECH_TXS = Gauge(
    "olas_agent_txs",
    "Total number of transactions",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

TOTAL_SUCCESSFUL_MECH_TXS = Gauge(
    "olas_successful_agent_txs",
    "Total successful number of transactions",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)

TOTAL_FAILED_MECH_TXS = Gauge(
    "olas_failed_agent_txs",
    "Total failed number of transaction",
    ["agent_address", "safe_address", "service_id"],
    registry=REGISTRY,
)
