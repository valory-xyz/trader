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

import requests
from web3 import Web3

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
            unix_timestamp = int(timestamp)
            # Convert to datetime and format as ISO 8601
            dt = datetime.utcfromtimestamp(unix_timestamp)
            return dt.strftime(ISO_TIMESTAMP_FORMAT)
        except Exception as e:
            self.context.logger.error(f"Error formatting timestamp {timestamp}: {e}")
            return ""

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

    def _get_web3_instance(self, chain: str) -> Optional[Web3]:
        """Get Web3 instance for the specified chain."""
        try:
            rpc_url = self.params.gnosis_ledger_rpc

            if not rpc_url:
                self.context.logger.warning(f"No RPC URL for {chain}")
                return None

            # Commented for future debugging purposes:
            # Note that you should create only one HTTPProvider with the same provider URL per python process,
            # as the HTTPProvider recycles underlying TCP/IP network connections, for better performance.
            # Multiple HTTPProviders with different URLs will work as expected.
            return Web3(Web3.HTTPProvider(rpc_url))
        except Exception as e:
            self.context.logger.error(f"Error creating Web3 instance: {str(e)}")
            return None

    def _fetch_all_bets_paginated(self, safe_address: str, subgraph_url: str) -> Optional[Dict]:
        """
        Fetch all bets for an agent with pagination support.
        
        :param safe_address: The agent's safe address
        :param subgraph_url: The subgraph URL
        :return: Trader agent data with all bets, or None if error
        """
        all_bets = []
        skip = 0
        trader_agent_base = None
        
        while True:
            query_payload = {
                "query": GET_TRADER_AGENT_PERFORMANCE_QUERY,
                "variables": {
                    "id": safe_address,
                    "first": GRAPHQL_BATCH_SIZE,
                    "skip": skip
                }
            }
            
            try:
                response = requests.post(
                    subgraph_url,
                    json=query_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=30
                )
                
                if response.status_code != 200:
                    self.context.logger.error(
                        f"Failed to fetch bets batch at skip={skip}: {response.status_code}"
                    )
                    return None
                
                response_data = response.json()
                trader_agent = response_data.get("data", {}).get("traderAgent")
                
                if not trader_agent:
                    if skip == 0:
                        # No trader agent found at all
                        return None
                    # No more bets to fetch
                    break
                
                # Store base data on first iteration
                if trader_agent_base is None:
                    trader_agent_base = trader_agent.copy()
                
                bets_batch = trader_agent.get("bets", [])
                if not bets_batch:
                    # No more bets
                    break
                
                all_bets.extend(bets_batch)
                
                # If we got less than GRAPHQL_BATCH_SIZE bets, we've reached the end
                if len(bets_batch) < GRAPHQL_BATCH_SIZE:
                    break
                
                skip += GRAPHQL_BATCH_SIZE
                
            except Exception as e:
                self.context.logger.error(f"Error fetching bets batch at skip={skip}: {str(e)}")
                return None
        
        # Merge all bets into the base trader agent data
        if trader_agent_base:
            trader_agent_base["bets"] = all_bets
            self.context.logger.info(
                f"Fetched {len(all_bets)} total bets for agent {safe_address} using pagination"
            )
        
        return trader_agent_base

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

    def _calculate_performance_metrics(self, trader_agent: Dict, safe_address: str) -> Dict:
        """Calculate performance metrics from trader agent data."""
        try:
            # Extract base data
            total_traded = int(trader_agent.get("totalTraded", 0))
            total_fees = int(trader_agent.get("totalFees", 0))
            total_payout = int(trader_agent.get("totalPayout", 0))
            bets = trader_agent.get("bets", [])
            
            # For now, use a simple mech cost estimation
            # TODO: Replace with actual mech subgraph query when available
            total_bets_count = int(trader_agent.get("totalBets", 0))
            estimated_mech_costs = total_bets_count * DEFAULT_MECH_FEE
            
            # Calculate all_time_funds_used
            all_time_funds_used = (total_traded + total_fees + estimated_mech_costs) / WEI_TO_NATIVE
            
            # Calculate all_time_profit
            total_costs = total_traded + total_fees + estimated_mech_costs
            all_time_profit = (total_payout - total_costs) / WEI_TO_NATIVE
            
            # Calculate funds_locked_in_markets
            funds_locked = 0
            for bet in bets:
                current_answer = bet.get("fixedProductMarketMaker", {}).get("currentAnswer")
                if current_answer is None:  # Market not resolved
                    bet_amount = int(bet.get("amount", 0))
                    funds_locked += bet_amount
            funds_locked_in_markets = funds_locked / WEI_TO_NATIVE
            
            # Get available funds (balance query)
            available_funds = self._get_available_balance(safe_address)
            
            return {
                "all_time_funds_used": round(all_time_funds_used, 4),
                "all_time_profit": round(all_time_profit, 4),
                "funds_locked_in_markets": round(funds_locked_in_markets, 4),
                "available_funds": round(available_funds, 4)
            }
            
        except Exception as e:
            self.context.logger.error(f"Error calculating performance metrics: {str(e)}")
            return {
                "all_time_funds_used": 0.0,
                "all_time_profit": 0.0,
                "funds_locked_in_markets": 0.0,
                "available_funds": 0.0
            }

    def _calculate_performance_stats(self, trader_agent: Dict) -> Dict:
        """Calculate performance statistics from trader agent data."""
        try:
            # Extract data
            total_bets = int(trader_agent.get("totalBets", 0))
            bets = trader_agent.get("bets", [])
            
            # Calculate prediction accuracy
            closed_bets = []
            won_bets = 0
            
            for bet in bets:
                fpmm = bet.get("fixedProductMarketMaker", {})
                current_answer = fpmm.get("currentAnswer")
                
                # Only count closed markets (where currentAnswer is not None)
                if current_answer is not None:
                    closed_bets.append(bet)
                    outcome_index = bet.get("outcomeIndex")
                    
                    if outcome_index is not None:
                        try:
                            # Convert hex answer to int and compare with outcome index
                            answer_int = int(current_answer, 0)
                            if answer_int == int(outcome_index):
                                won_bets += 1
                        except (ValueError, TypeError):
                            continue
            
            # Calculate accuracy
            prediction_accuracy = 0.0
            if len(closed_bets) > 0:
                prediction_accuracy = won_bets / len(closed_bets)
            
            return {
                "predictions_made": total_bets,
                "prediction_accuracy": round(prediction_accuracy, 4)
            }
            
        except Exception as e:
            self.context.logger.error(f"Error calculating performance stats: {str(e)}")
            return {
                "predictions_made": 0,
                "prediction_accuracy": 0.0
            }

    def _get_available_balance(self, safe_address: str) -> float:
        """Query xDAI and wxDAI balance using Web3."""
        try:
            w3 = self._get_web3_instance("gnosis")
            if not w3:
                self.context.logger.error("Failed to get Web3 instance for Gnosis Chain")
                return 0.0
            
            # ERC20 ABI for balanceOf
            erc20_abi = [{
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            }]
            
            # Get wxDAI balance
            wxdai_contract = w3.eth.contract(
                address=Web3.to_checksum_address(WXDAI_ADDRESS),
                abi=erc20_abi
            )
            wxdai_balance = wxdai_contract.functions.balanceOf(
                Web3.to_checksum_address(safe_address)
            ).call()
            
            # Get native xDAI balance
            xdai_balance = w3.eth.get_balance(Web3.to_checksum_address(safe_address))
            
            # Convert from wei to native token
            total_balance = (wxdai_balance + xdai_balance) / WEI_TO_NATIVE
            return total_balance
            
        except Exception as e:
            self.context.logger.error(f"Error fetching balance: {str(e)}")
            # Return 0 on error instead of failing the entire request
            return 0.0

    def _get_prediction_side(self, outcome_index: int, outcomes: List[str]) -> str:
        """Get the prediction side from outcome index and outcomes array."""
        try:
            if not outcomes or outcome_index >= len(outcomes):
                return "unknown"
            return outcomes[outcome_index]
        except (IndexError, TypeError) as e:
            self.context.logger.error(f"Error getting prediction side: {e}")
            return "unknown"

    def _get_prediction_status(self, bet: Dict) -> str:
        """Determine the status of a prediction (pending, won, lost)."""
        try:
            fpmm = bet.get("fixedProductMarketMaker", {})
            current_answer = fpmm.get("currentAnswer")
            
            # Market not resolved
            if current_answer is None:
                return "pending"
            
            # Check for invalid market
            if current_answer == INVALID_ANSWER_HEX:
                return "lost"
            
            # Compare outcome
            outcome_index = int(bet.get("outcomeIndex", 0))
            correct_answer = int(current_answer, 0)
            
            return "won" if outcome_index == correct_answer else "lost"
        except (ValueError, TypeError, KeyError) as e:
            self.context.logger.error(f"Error determining prediction status: {e}")
            return "pending"

    def _calculate_net_profit_for_prediction(
        self, bet: Dict, payouts_map: Dict[str, List]
    ) -> float:
        """Calculate net profit for a single prediction."""
        try:
            bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
            status = self._get_prediction_status(bet)
            
            if status == "pending":
                return 0.0
            
            if status == "lost":
                return -bet_amount
            
            # Won - calculate payout
            fpmm_id = bet.get("fixedProductMarketMaker", {}).get("id")
            payouts = payouts_map.get(fpmm_id, [])
            outcome_index = int(bet.get("outcomeIndex", 0))
            
            if payouts and len(payouts) > outcome_index:
                payout_amount = float(payouts[outcome_index]) / WEI_TO_NATIVE
                return payout_amount - bet_amount
            
            # Fallback if payouts not available
            return 0.0
            
        except Exception as e:
            self.context.logger.error(f"Error calculating net profit: {e}")
            return 0.0

    def _fetch_fpmm_payouts(self, fpmm_ids: List[str], omen_url: str) -> Dict[str, List]:
        """Fetch FPMM payouts from Omen subgraph."""
        try:
            query_payload = {
                "query": GET_FPMM_PAYOUTS_QUERY,
                "variables": {"fpmmIds": fpmm_ids}
            }
            
            response = requests.post(
                omen_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.context.logger.error(
                    f"Failed to fetch FPMM payouts: {response.status_code}"
                )
                return {}
            
            response_data = response.json()
            fpmms = response_data.get("data", {}).get("fixedProductMarketMakers", [])
            
            # Build map: fpmm_id -> payouts
            payouts_map = {}
            for fpmm in fpmms:
                fpmm_id = fpmm.get("id")
                payouts = fpmm.get("payouts", [])
                if fpmm_id and payouts:
                    payouts_map[fpmm_id] = payouts
            
            return payouts_map
            
        except Exception as e:
            self.context.logger.error(f"Error fetching FPMM payouts: {e}")
            return {}

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