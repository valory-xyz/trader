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


"""This module contains the handlers for the 'agent_performance_summary' skill."""

import json
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from typing import Any, Dict, Union, cast
from urllib.parse import urlparse

import requests

from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.abstract_round_abci.handlers import ABCIRoundHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    IpfsHandler as BaseIpfsHandler,
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
from packages.valory.skills.agent_performance_summary_abci.dialogues import (
    HttpDialogue,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_TRADER_AGENT_DETAILS_QUERY,
)
from packages.valory.skills.staking_abci.rounds import SynchronizedData


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


class HttpContentType(Enum):
    """Enum for HTTP content types."""

    JSON = "application/json"

    @property
    def header(self) -> str:
        """Return the HTTP header for the content type."""
        return f"Content-Type: {self.value}\n"


AgentPerformanceSummaryABCIHandler = ABCIRoundHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler
IpfsHandler = BaseIpfsHandler


class HttpHandler(BaseHttpHandler):
    """HTTP handler for agent performance summary endpoints."""

    SUPPORTED_PROTOCOL = HttpMessage.protocol_id

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the handler."""
        super().__init__(**kwargs)
        self.handler_url_regex: str = ""
        self.routes: Dict[tuple, list] = {}

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(
            db=self.context.state.round_sequence.latest_synchronized_data.db
        )

    def setup(self) -> None:
        """Setup the handler."""
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
        
        agent_details_url_regex = rf"{hostname_regex}\/api\/v1\/agent\/details"

        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                *(self.routes.get((HttpMethod.GET.value, HttpMethod.HEAD.value), []) or []),
                (
                    agent_details_url_regex,
                    self._handle_get_agent_details,
                ),
            ],
        }

    def _handle_get_agent_details(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle GET /api/v1/agent/details request."""
        try:
            # Get the safe contract address
            safe_address = self.synchronized_data.safe_contract_address.lower()
            
            # Prepare the GraphQL query
            query_payload = {
                "query": GET_TRADER_AGENT_DETAILS_QUERY,
                "variables": {"id": safe_address}
            }
            
            # Get the subgraph URL from params
            subgraph_url = self.context.params.olas_agents_subgraph_url
            
            # Make synchronous request to subgraph
            response = requests.post(
                subgraph_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.context.logger.error(
                    f"Failed to fetch agent details from subgraph: {response.status_code}"
                )
                self._send_internal_server_error_response(
                    http_msg,
                    http_dialogue,
                    {"error": "Failed to fetch agent details from subgraph"}
                )
                return
            
            response_data = response.json()
            
            # Extract trader agent data
            trader_agent = response_data.get("data", {}).get("traderAgent")
            
            if not trader_agent:
                self.context.logger.warning(
                    f"No trader agent found for address: {safe_address}"
                )
                self._send_not_found_response(
                    http_msg,
                    http_dialogue
                )
                return
            
            # Format the response according to API spec
            formatted_response = {
                "id": trader_agent.get("id", safe_address),
                "created_at": self._format_timestamp(trader_agent.get("blockTimestamp")),
                "last_active_at": self._format_timestamp(trader_agent.get("lastActive")),
            }
            
            self.context.logger.info(f"Sending agent details: {formatted_response}")
            self._send_ok_response(http_msg, http_dialogue, formatted_response)
            
        except Exception as e:
            self.context.logger.error(f"Error fetching agent details: {str(e)}")
            self._send_internal_server_error_response(
                http_msg,
                http_dialogue,
                {"error": "Internal server error while fetching agent details"}
            )

    def _format_timestamp(self, timestamp: str) -> str:
        """
        Format a Unix timestamp to ISO 8601 format.
        
        :param timestamp: Unix timestamp as string
        :return: ISO 8601 formatted timestamp
        """
        if not timestamp:
            return ""
        
        try:
            # Convert to int if it's a string
            timestamp_int = int(timestamp)
            # Convert to datetime and format as ISO 8601
            dt = datetime.utcfromtimestamp(timestamp_int)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError) as e:
            self.context.logger.error(f"Error formatting timestamp {timestamp}: {e}")
            return ""

    def _send_http_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict],
        status_code: int,
        status_text: str,
    ) -> None:
        """Generic method to send HTTP responses."""
        headers = HttpContentType.JSON.header if isinstance(data, dict) else ""
        headers += http_msg.headers

        # Convert dictionary to JSON string
        if isinstance(data, dict):
            data = json.dumps(data)

        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=status_code,
            status_text=status_text,
            headers=headers,
            body=data.encode("utf-8") if isinstance(data, str) else data,
        )

        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_ok_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict],
    ) -> None:
        """Send an OK response with the provided data."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.OK.value,
            "Success",
        )

    def _send_not_found_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
    ) -> None:
        """Send a NOT FOUND response."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            {"error": "Agent not found"},
            HTTPStatus.NOT_FOUND.value,
            "Not Found",
        )

    def _send_internal_server_error_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict],
    ) -> None:
        """Handle a Http internal server error response."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.INTERNAL_SERVER_ERROR.value,
            HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
        )
