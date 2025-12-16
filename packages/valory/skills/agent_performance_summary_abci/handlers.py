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
from dataclasses import asdict
from enum import Enum
from http import HTTPStatus
from typing import Any, Callable, Dict, List, Optional, Union, cast
from urllib.parse import urlparse

from aea.protocols.base import Message
from aea.protocols.dialogue.base import Dialogue

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
from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_TRADER_AGENT_DETAILS_QUERY,
    GET_TRADER_AGENT_PERFORMANCE_QUERY,
    GET_PREDICTION_HISTORY_QUERY,
    GET_FPMM_PAYOUTS_QUERY,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import PredictionsFetcher



# Constants
DEFAULT_MECH_FEE = 10000000000000000  # 0.01 xDAI in wei (1e16)
WEI_TO_NATIVE = 10**18
WXDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
GRAPHQL_BATCH_SIZE = 1000  # Max items per GraphQL query
INVALID_ANSWER_HEX = "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
PREDICT_BASE_URL = "https://predict.olas.network/questions"
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
PREDICTION_STATUS_PENDING = "pending"
PREDICTION_STATUS_WON = "won"
PREDICTION_STATUS_LOST = "lost"
PREDICTION_STATUS_ALL = "all"
VALID_PREDICTION_STATUSES = [PREDICTION_STATUS_PENDING, PREDICTION_STATUS_WON, PREDICTION_STATUS_LOST]


class HttpMethod(Enum):
    """Http methods"""

    GET = "get"
    HEAD = "head"
    POST = "post"


class HttpContentType(Enum):
    """Enum for HTTP content types."""

    HTML = "text/html"
    JS = "application/javascript"
    JSON = "application/json"
    CSS = "text/css"
    PNG = "image/png"
    JPG = "image/jpeg"
    JPEG = "image/jpeg"

    @property
    def header(self) -> str:
        """Return the HTTP header for the content type."""
        return f"Content-Type: {self.value}\n"


DEFAULT_HEADER = HttpContentType.HTML.header


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
    def synchronized_data(self) -> BaseSynchronizedData:
        """Return the synchronized data."""
        return BaseSynchronizedData(
            db=self.context.state.round_sequence.latest_synchronized_data.db
        )

    @property
    def shared_state(self):
        """Get the shared state."""
        from packages.valory.skills.agent_performance_summary_abci.models import SharedState
        return cast(SharedState, self.context.state)

    @property
    def hostname_regex(self) -> str:
        """Build and return hostname regex pattern."""
        config_uri_base_hostname = urlparse(
            self.context.params.service_endpoint
        ).hostname

        propel_uri_base_hostname = (
            r"https?:\/\/[a-zA-Z0-9]{16}.agent\.propel\.(staging\.)?autonolas\.tech"
        )

        local_ip_regex = r"192\.168(\.\d{1,3}){2}"

        # Route regexes
        hostname_regex = rf".*({config_uri_base_hostname}|{propel_uri_base_hostname}|{local_ip_regex}|localhost|127.0.0.1|0.0.0.0)(:\d+)?"
        return hostname_regex

    def setup(self) -> None:
        """Setup the handler."""
        super().setup()
        
        agent_details_url_regex = rf"{self.hostname_regex}\/api\/v1\/agent\/details"
        agent_performance_url_regex = rf"{self.hostname_regex}\/api\/v1\/agent\/performance"
        agent_predictions_url_regex = rf"{self.hostname_regex}\/api\/v1\/agent\/predictions-history"

        self.routes = {
            **self.routes,  # persisting routes from base class
            (HttpMethod.GET.value, HttpMethod.HEAD.value): [
                *(self.routes.get((HttpMethod.GET.value, HttpMethod.HEAD.value), []) or []),
                (
                    agent_details_url_regex,
                    self._handle_get_agent_details,
                ),
                (
                    agent_performance_url_regex,
                    self._handle_get_agent_performance,
                ),
                (
                    agent_predictions_url_regex,
                    self._handle_get_predictions,
                ),
            ],
        }

    def _handle_get_agent_details(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle GET /api/v1/agent/details request."""
        summary = self.shared_state.read_existing_performance_summary()
        details = summary.agent_details
        
        if not details or not details.id:
            self._send_internal_server_error_response(
                http_msg, 
                http_dialogue,
                {"error": "Agent details not available. Data may not have been fetched yet or there was an error retrieving it."}
            )
            return
            
        formatted_response = {
            "id": details.id,
            "created_at": details.created_at,
            "last_active_at": details.last_active_at,
        }
        
        self.context.logger.info(f"Responding with agent details: {formatted_response}")
        self._send_ok_response(http_msg, http_dialogue, formatted_response)

    def _send_http_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        status_code: int,
        status_text: str,
        content_type: Optional[str] = None,
    ) -> None:
        """Generic method to send HTTP responses."""
        headers = content_type or (
            HttpContentType.JSON.header
            if isinstance(data, (dict, list))
            else DEFAULT_HEADER
        )
        headers += http_msg.headers

        # Convert dictionary or list to JSON string
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        try:
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
        except KeyError as e:
            self.context.logger.error(f"KeyError: {e}")
        except Exception as e:
            self.context.logger.error(f"Error: {e}")

    def _send_too_early_request_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a HTTP too early request response."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.TOO_EARLY.value,
            HTTPStatus.TOO_EARLY.phrase,
            content_type,
        )

    def _send_too_many_requests_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a HTTP too many requests response."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.TOO_MANY_REQUESTS.value,
            HTTPStatus.TOO_MANY_REQUESTS.phrase,
            content_type,
        )

    def _send_internal_server_error_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a Http internal server error response."""
        headers = content_type or (
            HttpContentType.JSON.header
            if isinstance(data, (dict, list))
            else DEFAULT_HEADER
        )
        headers += http_msg.headers

        # Convert dictionary or list to JSON string
        if isinstance(data, (dict, list)):
            data = json.dumps(data)

        http_response = http_dialogue.reply(
            performative=HttpMessage.Performative.RESPONSE,
            target_message=http_msg,
            version=http_msg.version,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
            status_text=HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
            headers=headers,
            body=data.encode("utf-8") if isinstance(data, str) else data,
        )

        # Send response
        self.context.logger.info("Responding with: {}".format(http_response))
        self.context.outbox.put_message(message=http_response)

    def _send_bad_request_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Handle a HTTP bad request."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.BAD_REQUEST.value,
            HTTPStatus.BAD_REQUEST.phrase,
            content_type,
        )

    def _send_ok_response(
        self,
        http_msg: HttpMessage,
        http_dialogue: HttpDialogue,
        data: Union[str, Dict, List, bytes],
        content_type: Optional[str] = None,
    ) -> None:
        """Send an OK response with the provided data."""
        self._send_http_response(
            http_msg,
            http_dialogue,
            data,
            HTTPStatus.OK.value,
            "Success",
            content_type,
        )

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
        self.context.state.req_to_callback[nonce] = (callback, callback_kwargs or {})

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

    def _handle_get_agent_performance(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle GET /api/v1/agent/performance request."""
        try:
            # Parse query parameters
            url_parts = http_msg.url.split('?')
            window = "lifetime"  # Default
            currency = "USD"  # Default
            
            if len(url_parts) > 1:
                params = {}
                for param in url_parts[1].split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
                window = params.get('window', 'lifetime')
                currency = params.get('currency', 'USD')
            
            # Validate window parameter
            if window not in ["lifetime", "7d", "30d", "90d"]:
                self._send_bad_request_response(
                    http_msg, http_dialogue,
                    {"error": f"Invalid window parameter: {window}. Must be one of: lifetime, 7d, 30d, 90d"}
                )
                return
            
            safe_address = self.synchronized_data.safe_contract_address.lower()
            summary = self.shared_state.read_existing_performance_summary()
            performance = summary.agent_performance
            
            if not performance or not performance.metrics:
                self._send_internal_server_error_response(
                    http_msg, 
                    http_dialogue,
                    {"error": "Performance data not available. Data may not have been fetched yet or there was an error retrieving it."}
                )
                return
            
            # Convert dataclasses to dicts for response
            formatted_response = {
                "agent_id": safe_address,
                "window": window,
                "currency": currency,
                "metrics": asdict(performance.metrics),
                "stats": asdict(performance.stats)
            }
            
            self.context.logger.info(f"Sending performance data for agent: {safe_address}")
            self._send_ok_response(http_msg, http_dialogue, formatted_response)
            
        except Exception as e:
            self.context.logger.error(f"Error in performance endpoint: {str(e)}")
            self._send_internal_server_error_response(
                http_msg, http_dialogue,
                {"error": "Failed to fetch performance data"}
            )

    def _handle_get_predictions(
        self, http_msg: HttpMessage, http_dialogue: HttpDialogue
    ) -> None:
        """Handle GET /api/v1/agent/predictions request."""
        try:
            # Parse query parameters
            page, page_size, status_filter = self._parse_query_params(http_msg)
            
            # Validate status filter
            if status_filter and status_filter not in VALID_PREDICTION_STATUSES:
                self._send_bad_request_response(
                    http_msg, http_dialogue,
                    {"error": f"Invalid status parameter. Must be one of: {', '.join(VALID_PREDICTION_STATUSES)}"}
                )
                return
            
            safe_address = self.synchronized_data.safe_contract_address.lower()
            skip = (page - 1) * page_size
            
            # Check stored history first
            summary = self.shared_state.read_existing_performance_summary()
            history = summary.prediction_history
            
            if history and history.stored_count > 0 and skip < history.stored_count:
                # Serve from stored history
                self.context.logger.info(f"Serving predictions from stored history (page {page})")
                items = self._filter_and_paginate(history.items, status_filter, skip, page_size)
                
                response = {
                    "agent_id": safe_address,
                    "currency": "USD",
                    "page": page,
                    "page_size": page_size,
                    "total": history.total_predictions,
                    "items": items
                }
                self._send_ok_response(http_msg, http_dialogue, response)
                return
            
            # Fetch from subgraph
            self.context.logger.info(f"Querying subgraph (page {page})")
            fetcher = PredictionsFetcher(self.context, self.context.logger)
            result = fetcher.fetch_predictions(
                safe_address=safe_address,
                first=page_size,
                skip=skip,
                status_filter=status_filter if status_filter != PREDICTION_STATUS_ALL else None
            )
            
            response = {
                "agent_id": safe_address,
                "currency": "USD",
                "page": page,
                "page_size": page_size,
                "total": result["total_predictions"],
                "items": result["items"]
            }
            
            self.context.logger.info(f"Sending {len(result['items'])} predictions")
            self._send_ok_response(http_msg, http_dialogue, response)
            
        except Exception as e:
            self.context.logger.error(f"Error in predictions endpoint: {e}")
            self._send_internal_server_error_response(
                http_msg, http_dialogue,
                {"error": "Failed to fetch predictions"}
            )

    def _parse_query_params(self, http_msg: HttpMessage) -> tuple:
        """Parse page, page_size, and status_filter from query string."""
        page = 1
        page_size = DEFAULT_PAGE_SIZE
        status_filter = None
        
        url_parts = http_msg.url.split('?')
        if len(url_parts) > 1:
            params = {}
            for param in url_parts[1].split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value
            
            try:
                page = int(params.get('page', 1))
                page_size = min(int(params.get('page_size', DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
            except ValueError:
                pass
            
            status_filter = params.get('status')
        
        return page, page_size, status_filter

    def _filter_and_paginate(self, items: list, status_filter: Optional[str], skip: int, page_size: int) -> list:
        """Filter items by status and paginate."""
        if status_filter and status_filter != PREDICTION_STATUS_ALL:
            items = [item for item in items if item.get("status") == status_filter]
        
        return items[skip:skip + page_size]