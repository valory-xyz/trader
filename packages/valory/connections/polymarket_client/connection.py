#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, cast

import requests
from aea.configurations.base import PublicId
from aea.connections.base import BaseSyncConnection
from aea.mail.base import Envelope
from aea.protocols.base import Address, Message
from aea.protocols.dialogue.base import Dialogue
from eth_abi import encode
from eth_utils import keccak, to_checksum_address
from py_builder_relayer_client.client import RelayClient
from py_builder_relayer_client.models import OperationType, SafeTransaction
from py_builder_signing_sdk.config import BuilderConfig, RemoteBuilderConfig
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.exceptions import PolyApiException
from py_clob_client.order_builder.constants import BUY
from web3 import Web3
from web3.middleware.proof_of_authority import ExtraDataToPOAMiddleware

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.protocols.srr.dialogues import SrrDialogue
from packages.valory.protocols.srr.dialogues import SrrDialogues as BaseSrrDialogues
from packages.valory.protocols.srr.message import SrrMessage


PUBLIC_ID = PublicId.from_str("valory/polymarket_client:0.1.0")
DATA_API_BASE_URL = "https://data-api.polymarket.com"
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
RELAYER_URL = "https://relayer-v2.polymarket.com/"
CONDITIONAL_TOKENS_CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
PARENT_COLLECTION_ID = bytes.fromhex("00" * 32)
CHAIN_ID = 137  # Polygon
MAX_UINT256 = (
    115792089237316195423570985008687907853269984665640564039457584007913129639935
)
POLYGON_RPC_URL = "https://polygon-rpc.com"
POLYMARKET_CATEGORY_TAGS = [
    "business",
    "politics",
    "science",
    "technology",
    "health",
    "travel",
    "entertainment",
    "weather",
    "finance",
    "international",
]
MARKETS_LIMIT = 300
MARKETS_TIME_WINDOW_DAYS = 4
API_REQUEST_TIMEOUT = 10
MAX_API_RETRIES = 3
RETRY_DELAY = 10
# Subgraph indexes markets created after this date; exclude older markets
MARKETS_MIN_CREATED_AT = "2025-12-15T19:20:11Z"


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
        builder_program_enabled = self.configuration.config.get(
            "polymarket_builder_program_enabled", True
        )

        self.dialogues = SrrDialogues(connection_id=PUBLIC_ID)

        # Initialize relay client if builder program is enabled
        self.relayer_client = None
        self.builder_config = None
        if builder_program_enabled:
            remote_builder_url = self.configuration.config.get("remote_builder_url")
            self.logger.info(
                f"Builder program enabled. Initializing RelayClient with remote builder URL: {remote_builder_url}"
            )
            remote_builder_config = RemoteBuilderConfig(url=remote_builder_url)
            self.builder_config = BuilderConfig(
                remote_builder_config=remote_builder_config
            )

        self.relayer_client = RelayClient(
            relayer_url=RELAYER_URL,
            chain_id=chain_id,
            private_key=self.connection_private_key,
            builder_config=self.builder_config,
        )
        self.client = ClobClient(
            host,
            key=self.connection_private_key,
            chain_id=chain_id,
            signature_type=2,
            funder=self.safe_address,
            builder_config=self.builder_config,
        )
        self.client.set_api_creds(self.client.create_or_derive_api_creds())

        # Load contract addresses for set approval
        self.usdc_address = to_checksum_address(
            self.configuration.config.get("usdc_address")
        )
        self.ctf_address = to_checksum_address(
            self.configuration.config.get("ctf_address")
        )
        self.ctf_exchange = to_checksum_address(
            self.configuration.config.get("ctf_exchange")
        )
        self.neg_risk_ctf_exchange = to_checksum_address(
            self.configuration.config.get("neg_risk_ctf_exchange")
        )
        self.neg_risk_adapter = to_checksum_address(
            self.configuration.config.get("neg_risk_adapter")
        )

        # Initialize Web3 for approval checking
        self.w3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

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

        payload, error_message = self._route_request(
            payload=json.loads(srr_message.payload),
        )

        response_message = cast(
            SrrMessage,
            dialogue.reply(  # type: ignore
                performative=SrrMessage.Performative.RESPONSE,
                target_message=srr_message,
                payload=json.dumps(payload),
                error=bool(error_message),
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
            RequestType.FETCH_MARKET: self._fetch_market_by_slug,
            RequestType.GET_POSITIONS: self._get_positions,
            RequestType.FETCH_ALL_POSITIONS: self._fetch_all_positions,
            RequestType.GET_TRADES: self._get_trades,
            RequestType.FETCH_ALL_TRADES: self._fetch_all_trades,
            RequestType.REDEEM_POSITIONS: self._redeem_positions,
            RequestType.SET_APPROVAL: self._set_approval,
            RequestType.CHECK_APPROVAL: self._check_approval,
        }

        self.logger.info(f"Routing request of type: {request_type.value}")

        try:
            params = payload.get("params", {})
            response, error_msg = request_function_map[request_type](**params)
            return response, str(error_msg) if error_msg else ""
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

    def _place_bet(self, token_id: str, amount: float) -> Tuple[Any, Any]:
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
            error_msg = (
                e.error_msg.get("error")
                if isinstance(e.error_msg, dict) and e.error_msg.get("error")
                else f"Error placing bet: {e}"
            )
            self.logger.error(error_msg)
            return None, error_msg

    def _load_cache_file(self, cache_file_path: str) -> Dict:
        """Load the cache file from disk.

        :param cache_file_path: Path to the cache file
        :return: Cache data dictionary
        """
        try:
            with open(cache_file_path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.warning(f"Could not load cache file: {e}. Using empty cache.")
            return {"allowances_set": False, "tag_id_cache": {}}

    def _save_cache_file(self, cache_file_path: str, cache_data: Dict) -> None:
        """Save the cache file to disk.

        :param cache_file_path: Path to the cache file
        :param cache_data: Cache data dictionary to save
        """
        try:
            # Ensure directory exists
            cache_path = Path(cache_file_path)
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            with open(cache_file_path, "w") as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Could not save cache file: {e}")

    def _request_with_retries(
        self, url: str, params: Dict = None, max_retries: int = MAX_API_RETRIES
    ) -> Tuple[Any, str]:
        """Make an API request with retry logic.

        :param url: The URL to request
        :param params: Optional query parameters
        :param max_retries: Maximum number of retry attempts
        :return: Tuple of (response_data, error_message)
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params=params, timeout=API_REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.json(), None
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    self.logger.warning(
                        f"API request failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying..."
                    )
                    time.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                else:
                    self.logger.error(
                        f"API request failed after {max_retries} attempts: {e}"
                    )

        return None, last_error

    def _fetch_tag_id(
        self,
        category: str,
        tag_id_cache: Dict[str, str],
        cache_file_path: str = None,
        cache_data: Dict = None,
    ) -> Tuple[str, str]:
        """Fetch tag ID for a category slug.

        :param category: The category name
        :param tag_id_cache: In-memory cache dictionary for tag IDs
        :param cache_file_path: Optional path to persistent cache file
        :param cache_data: Optional cache data dict to update
        :return: Tuple of (tag_id, error_message)
        """
        tag_slug = category.lower()

        # Check in-memory cache first
        if tag_slug in tag_id_cache:
            self.logger.info(f"  Using cached tag_id: {tag_id_cache[tag_slug]}")
            return tag_id_cache[tag_slug], None

        # Fetch from API
        tag_url = f"{GAMMA_API_BASE_URL}/tags/slug/{tag_slug}"
        tag_data, error = self._request_with_retries(tag_url)

        if error:
            return None, f"Error fetching tag for '{category}': {error}"

        tag_id = tag_data.get("id")
        if not tag_id:
            return None, f"No tag ID found for slug '{tag_slug}'"

        # Update in-memory cache
        tag_id_cache[tag_slug] = tag_id

        # Update persistent cache if provided
        if cache_file_path and cache_data is not None:
            # Ensure tag_id_cache dict exists
            if "tag_id_cache" not in cache_data or not isinstance(
                cache_data["tag_id_cache"], dict
            ):
                cache_data["tag_id_cache"] = {}
            cache_data["tag_id_cache"][tag_slug] = tag_id
            self._save_cache_file(cache_file_path, cache_data)

        self.logger.info(f"  Found tag_id: {tag_id}")
        return tag_id, None

    def _fetch_markets_by_tag(
        self, tag_id: str, end_date_min: str, end_date_max: str
    ) -> Tuple[list, str]:
        """Fetch all markets for a given tag ID with pagination.

        :param tag_id: The tag ID to filter markets by
        :param end_date_min: Minimum end date filter
        :param end_date_max: Maximum end date filter
        :return: Tuple of (markets_list, error_message)
        """
        offset = 0
        all_markets = []

        while True:
            params = {
                "tag_id": tag_id,
                "end_date_max": end_date_max,
                "end_date_min": end_date_min,
                "closed": "false",
                "limit": MARKETS_LIMIT,
                "offset": offset,
            }

            markets_data, error = self._request_with_retries(
                f"{GAMMA_API_BASE_URL}/markets", params=params
            )

            if error:
                return None, error

            if not markets_data:
                break

            all_markets.extend(markets_data)
            self.logger.info(
                f"  Fetched {len(markets_data)} markets (total: {len(all_markets)})"
            )

            if len(markets_data) < MARKETS_LIMIT:
                break

            offset += len(markets_data)

        return all_markets, None

    def _filter_markets_by_created_at(self, markets: list) -> list:
        """Filter markets to only include those created after MARKETS_MIN_CREATED_AT.

        Subgraph indexes markets created after this date.

        :param markets: List of market dictionaries
        :return: Filtered list of markets with createdAt > MARKETS_MIN_CREATED_AT
        """
        return [
            m for m in markets if (m.get("createdAt") or "") > MARKETS_MIN_CREATED_AT
        ]

    def _filter_yes_no_markets(self, markets: list) -> list:
        """Filter markets to only include those with Yes/No outcomes.

        :param markets: List of market dictionaries
        :return: Filtered list of markets with Yes/No outcomes
        """
        yes_no_markets = []
        for market in markets:
            outcomes_str = market.get("outcomes")
            if not outcomes_str:
                continue

            try:
                outcomes = json.loads(outcomes_str)
                if isinstance(outcomes, list) and len(outcomes) == 2:
                    outcomes_lower = [str(o).lower() for o in outcomes]
                    if set(outcomes_lower) == {"yes", "no"}:
                        yes_no_markets.append(market)
            except (json.JSONDecodeError, TypeError):
                continue

        return yes_no_markets

    def _remove_duplicate_markets(self, markets: list) -> list:
        """Remove duplicate markets based on market ID.

        :param markets: List of market dictionaries
        :return: List of unique markets
        """
        seen_ids = set()
        unique_markets = []

        for market in markets:
            market_id = market.get("id")
            if market_id and market_id not in seen_ids:
                seen_ids.add(market_id)
                unique_markets.append(market)

        return unique_markets

    def _fetch_markets(self, cache_file_path: str = None) -> Tuple[Any, Any]:
        """Fetch current markets from Polymarket with category-based filtering.

        Fetches markets from multiple categories and filters for Yes/No outcomes.
        Resolved/over markets (extreme outcome prices) are blacklisted in the
        PolymarketFetchMarketBehaviour._blacklist_expired_bets logic.

        :param cache_file_path: Optional path to persistent cache file for tag IDs
        :return: Tuple of (filtered_markets_dict, error_message)
        """
        try:
            # Calculate time window
            end_date_min = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_date_max = (
                datetime.now(timezone.utc) + timedelta(days=MARKETS_TIME_WINDOW_DAYS)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            filtered_markets_by_category = {}

            # Load persistent cache if path provided
            cache_data = None
            if cache_file_path:
                cache_data = self._load_cache_file(cache_file_path)
                # Handle case where tag_id_cache key is missing or None
                tag_id_cache = cache_data.get("tag_id_cache") or {}
                # Ensure tag_id_cache exists in cache_data for saving later
                if (
                    "tag_id_cache" not in cache_data
                    or cache_data["tag_id_cache"] is None
                ):
                    cache_data["tag_id_cache"] = {}
                self.logger.info(f"Loaded {len(tag_id_cache)} cached tag IDs")
            else:
                tag_id_cache = {}

            self.logger.info(
                f"Fetching markets for {len(POLYMARKET_CATEGORY_TAGS)} categories"
            )
            self.logger.info(f"Time window: {end_date_min} to {end_date_max}")

            for category in POLYMARKET_CATEGORY_TAGS:
                self.logger.info(f"Processing category: {category}")

                # Step 1: Fetch tag ID
                tag_id, error = self._fetch_tag_id(
                    category, tag_id_cache, cache_file_path, cache_data
                )
                if error:
                    self.logger.warning(f"  {error}. Skipping.")
                    continue

                # Step 2: Fetch markets with pagination
                category_markets, error = self._fetch_markets_by_tag(
                    tag_id, end_date_min, end_date_max
                )
                if error:
                    self.logger.error(
                        f"  Error fetching markets for '{category}': {error}"
                    )
                    continue

                # Step 3: Filter by createdAt (subgraph indexes markets after MARKETS_MIN_CREATED_AT),
                # then filter for Yes/No outcomes only
                markets_after_cutoff = self._filter_markets_by_created_at(
                    category_markets
                )
                self.logger.info(
                    f"  Filtered to {len(markets_after_cutoff)} markets with createdAt > {MARKETS_MIN_CREATED_AT}"
                )
                yes_no_markets = self._filter_yes_no_markets(markets_after_cutoff)
                self.logger.info(f"  Filtered to {len(yes_no_markets)} Yes/No markets")

                filtered_markets_by_category[category] = yes_no_markets
                self.logger.info(
                    f"  Found {len(yes_no_markets)} markets for '{category}'"
                )

            # Return all filtered markets by category (with potential duplicates)
            total_markets = sum(
                len(markets) for markets in filtered_markets_by_category.values()
            )
            self.logger.info(
                f"Fetched {total_markets} Yes/No markets across {len(filtered_markets_by_category)} categories"
            )

            return filtered_markets_by_category, None

        except Exception as e:
            error_msg = f"Unexpected error fetching markets: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _fetch_market_by_slug(self, slug: str) -> Tuple[Any, Any]:
        """Fetch a specific market from Polymarket by slug.

        :param slug: The market slug (e.g., 'cs2-vit-vp-2026-01-14')
        :return: Tuple of (market_data, error_message)
        """
        try:
            url = f"{GAMMA_API_BASE_URL}/markets/slug/{slug}"

            response = requests.get(url, timeout=API_REQUEST_TIMEOUT)
            response.raise_for_status()

            market = response.json()
            self.logger.info(f"Fetched market with slug: {slug}")
            return market, None

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching market by slug '{slug}': {str(e)}"
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error fetching market by slug '{slug}': {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _get_positions(
        self,
        size_threshold: int = 1,
        limit: int = 100,
        sort_by: str = "TOKENS",
        sort_direction: str = "DESC",
        redeemable: Optional[bool] = None,
        offset: int = 0,
    ) -> Tuple[Any, Any]:
        """Get positions from Polymarket for the safe address.

        :param size_threshold: Minimum position size threshold
        :param limit: Maximum number of positions to return
        :param sort_by: Field to sort by (e.g., TOKENS)
        :param sort_direction: Sort direction (ASC or DESC)
        :param redeemable: Filter for redeemable positions only. If None, returns all positions.
        :param offset: Pagination offset (default: 0)
        :return: Tuple of (positions_data, error_message)
        """
        try:
            url = f"{DATA_API_BASE_URL}/positions"
            params = {
                "sizeThreshold": size_threshold,
                "limit": limit,
                "sortBy": sort_by,
                "sortDirection": sort_direction,
                "offset": offset,
                "user": self.safe_address,
            }
            # Only include redeemable parameter if explicitly provided
            if redeemable is not None:
                params["redeemable"] = redeemable

            response = requests.get(url, params=params, timeout=API_REQUEST_TIMEOUT)
            response.raise_for_status()

            positions = response.json()
            self.logger.info(
                f"Fetched {len(positions)} positions for {self.safe_address}"
            )
            return positions, None

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching positions: {str(e)}"
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error fetching positions: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _fetch_all_positions(
        self,
        size_threshold: int = 1,
        sort_by: str = "TOKENS",
        sort_direction: str = "DESC",
        redeemable: Optional[bool] = None,
    ) -> Tuple[Any, Any]:
        """Fetch all positions from Polymarket by paginating through all results for the safe address.

        :param size_threshold: Minimum position size threshold
        :param sort_by: Field to sort by (e.g., TOKENS)
        :param sort_direction: Sort direction (ASC or DESC)
        :param redeemable: Filter for redeemable positions only. If None, returns all positions.
        :return: Tuple of (all_positions_data, error_message)
        """
        all_positions = []
        limit = 100  # Max limit per request
        offset = 0

        try:
            while True:
                positions, error = self._get_positions(
                    size_threshold=size_threshold,
                    limit=limit,
                    sort_by=sort_by,
                    sort_direction=sort_direction,
                    redeemable=redeemable,
                    offset=offset,
                )

                if error:
                    return None, error

                if not positions or len(positions) == 0:
                    break

                all_positions.extend(positions)

                # If we got fewer results than the limit, we've reached the end
                if len(positions) < limit:
                    break

                # Increment offset for next page
                offset += limit

            self.logger.info(
                f"Fetched total of {len(all_positions)} positions for {self.safe_address}"
            )
            return all_positions, None

        except Exception as e:
            error_msg = f"Unexpected error fetching all positions: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _get_trades(
        self,
        limit: int = 100,
        offset: int = 0,
        taker_only: bool = True,
    ) -> Tuple[Any, Any]:
        """Get trades from Polymarket for the safe address.

        :param limit: Maximum number of trades to return (default: 100)
        :param offset: Pagination offset (default: 0)
        :param taker_only: Only show trades where user was taker (default: True)
        :return: Tuple of (trades_data, error_message)
        """
        try:
            url = f"{DATA_API_BASE_URL}/trades"
            params = {
                "limit": limit,
                "offset": offset,
                "takerOnly": taker_only,
                "user": self.safe_address,
            }

            request_url = f"{url}?{'&'.join([f'{k}={v}' for k, v in params.items()])}"
            self.logger.info(
                f"Fetching trades from: {request_url}"
            )

            response = requests.get(url, params=params, timeout=API_REQUEST_TIMEOUT)
            response.raise_for_status()

            trades = response.json()
            self.logger.info(
                f"Fetched {len(trades)} trades for {self.safe_address} "
                f"(offset={offset}, limit={limit}, takerOnly={taker_only})"
            )
            return trades, None

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching trades: {str(e)}"
            self.logger.error(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error fetching trades: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _fetch_all_trades(
        self,
        taker_only: bool = True,
    ) -> Tuple[Any, Any]:
        """Fetch all trades from Polymarket by paginating through all results for the safe address.

        :param taker_only: Only show trades where user was taker (default: True)
        :return: Tuple of (all_trades_data, error_message)
        """
        all_trades = []
        limit = 100  # Max limit per request
        offset = 0

        try:
            self.logger.info(
                f"Starting to fetch all trades (takerOnly={taker_only}, limit={limit})"
            )

            while True:
                trades, error = self._get_trades(
                    limit=limit,
                    offset=offset,
                    taker_only=taker_only,
                )

                if error:
                    return None, error

                if not trades or len(trades) == 0:
                    break

                all_trades.extend(trades)

                self.logger.info(
                    f"Paginating: fetched {len(trades)} trades, "
                    f"total so far: {len(all_trades)}, next offset: {offset + limit}"
                )

                # If we got fewer results than the limit, we've reached the end
                if len(trades) < limit:
                    break

                # Increment offset for next page
                offset += limit

            pages_fetched = (len(all_trades) + limit - 1) // limit if all_trades else 0
            if pages_fetched == 0 and len(all_trades) > 0:
                pages_fetched = 1  # At least one page was fetched

            self.logger.info(
                f"Fetched total of {len(all_trades)} trades for {self.safe_address} "
                f"(completed pagination with {pages_fetched} page(s))"
            )
            if all_trades:
                self.logger.debug(
                    f"Trades fetched: {[(t.get('conditionId'), t.get('side'), t.get('outcomeIndex')) for t in all_trades[:10]]}"
                )
            return all_trades, None

        except Exception as e:
            error_msg = f"Unexpected error fetching all trades: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _redeem_positions(
        self, condition_id: str, index_sets: list[int], collateral_token: str
    ) -> Tuple[Any, Any]:
        """Redeem positions on Polymarket.

        :param condition_id: The condition ID (hex string with or without 0x prefix)
        :param index_sets: List of index sets to redeem (uint256[])
        :param collateral_token: The collateral token address
        :return: Tuple of (transaction_result, error_message)
        """
        try:
            # Check if relayer client is initialized
            if self.relayer_client is None:
                error_msg = "Relayer client not initialized. Enable polymarket_builder_program_enabled in config."
                self.logger.error(error_msg)
                return None, error_msg

            # Convert condition_id to bytes
            condition_id_clean = condition_id.removeprefix("0x")
            condition_id_bytes = bytes.fromhex(condition_id_clean)

            # Encode redeemPositions function call
            selector = bytes.fromhex(
                "01b7037c"
            )  # redeemPositions(address,bytes32,bytes32,uint256[])
            encoded_args = encode(
                ["address", "bytes32", "bytes32", "uint256[]"],
                [
                    collateral_token,
                    PARENT_COLLECTION_ID,
                    condition_id_bytes,
                    index_sets,
                ],
            )
            calldata = selector + encoded_args

            # Create SafeTransaction
            tx = SafeTransaction(
                to=CONDITIONAL_TOKENS_CONTRACT,
                operation=OperationType.Call,
                data="0x" + calldata.hex(),
                value="0",
            )

            # Execute transaction
            result = self.relayer_client.execute(
                transactions=[tx], metadata="Redeem conditional tokens"
            )

            transaction_data = result.get_transaction()
            self.logger.info(
                f"Redeemed positions for condition {condition_id}: {transaction_data}"
            )
            return transaction_data, None

        except Exception as e:
            error_msg = f"Error redeeming positions: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _encode_approve(self, spender: str, amount: int) -> str:
        """Encode ERC20 approve function call.

        :param spender: The address to approve
        :param amount: The amount to approve
        :return: Encoded calldata as hex string
        """
        selector = keccak(text="approve(address,uint256)")[:4]
        encoded_args = encode(["address", "uint256"], [spender, amount])
        return "0x" + (selector + encoded_args).hex()

    def _encode_set_approval_for_all(self, operator: str, approved: bool) -> str:
        """Encode ERC1155 setApprovalForAll function call.

        :param operator: The operator address
        :param approved: Whether to approve or revoke
        :return: Encoded calldata as hex string
        """
        selector = keccak(text="setApprovalForAll(address,bool)")[:4]
        encoded_args = encode(["address", "bool"], [operator, approved])
        return "0x" + (selector + encoded_args).hex()

    def _set_approval(self) -> Tuple[Any, Any]:
        """Set all required approvals for Polymarket trading.

        Sets approvals for:
        - USDC for CTF Exchange
        - CTF for CTF Exchange
        - USDC for Neg Risk CTF Exchange
        - CTF for Neg Risk CTF Exchange
        - USDC for Neg Risk Adapter
        - CTF for Neg Risk Adapter

        :return: Tuple of (transaction_result, error_message)
        """
        try:
            # Check if relayer client is initialized
            if self.relayer_client is None:
                error_msg = "Relayer client not initialized. Enable polymarket_builder_program_enabled in config."
                self.logger.error(error_msg)
                return None, error_msg

            self.logger.info(
                "Creating approval transactions for Polymarket contracts..."
            )

            # Create approval transactions for CTF Exchange
            usdc_approve_ctf = SafeTransaction(
                to=self.usdc_address,
                operation=OperationType.Call,
                data=self._encode_approve(self.ctf_exchange, MAX_UINT256),
                value="0",
            )

            ctf_approve_ctf_exchange = SafeTransaction(
                to=self.ctf_address,
                operation=OperationType.Call,
                data=self._encode_set_approval_for_all(self.ctf_exchange, True),
                value="0",
            )

            # Create approval transactions for Neg Risk CTF Exchange
            usdc_approve_neg_risk = SafeTransaction(
                to=self.usdc_address,
                operation=OperationType.Call,
                data=self._encode_approve(self.neg_risk_ctf_exchange, MAX_UINT256),
                value="0",
            )

            ctf_approve_neg_risk = SafeTransaction(
                to=self.ctf_address,
                operation=OperationType.Call,
                data=self._encode_set_approval_for_all(
                    self.neg_risk_ctf_exchange, True
                ),
                value="0",
            )

            # Create approval transactions for Neg Risk Adapter
            usdc_approve_adapter = SafeTransaction(
                to=self.usdc_address,
                operation=OperationType.Call,
                data=self._encode_approve(self.neg_risk_adapter, MAX_UINT256),
                value="0",
            )

            ctf_approve_adapter = SafeTransaction(
                to=self.ctf_address,
                operation=OperationType.Call,
                data=self._encode_set_approval_for_all(self.neg_risk_adapter, True),
                value="0",
            )

            # Execute all approval transactions together
            transactions = [
                usdc_approve_ctf,
                ctf_approve_ctf_exchange,
                usdc_approve_neg_risk,
                ctf_approve_neg_risk,
                usdc_approve_adapter,
                ctf_approve_adapter,
            ]

            self.logger.info("Executing all approval transactions...")
            result = self.relayer_client.execute(
                transactions=transactions,
                metadata="Set all Polymarket approvals for Safe",
            )

            transaction_data = result.get_transaction()
            self.logger.info(
                f"All approvals set successfully! Transaction: {transaction_data}"
            )
            return transaction_data, None

        except Exception as e:
            error_msg = f"Error setting approvals: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _check_erc20_allowance(
        self, token_address: str, owner: str, spender: str
    ) -> int:
        """Check ERC20 allowance.

        :param token_address: The ERC20 token address
        :param owner: The owner address
        :param spender: The spender address
        :return: The allowance amount
        """
        allowance_sig = self.w3.keccak(text="allowance(address,address)")[:4].hex()
        data = allowance_sig + encode(["address", "address"], [owner, spender]).hex()
        result = self.w3.eth.call(
            {"to": self.w3.to_checksum_address(token_address), "data": data}
        )
        allowance = int.from_bytes(result, byteorder="big")
        return allowance

    def _check_erc1155_approval(
        self, token_address: str, owner: str, operator: str
    ) -> bool:
        """Check ERC1155 approval.

        :param token_address: The ERC1155 token address
        :param owner: The owner address
        :param operator: The operator address
        :return: True if approved, False otherwise
        """
        is_approved_sig = self.w3.keccak(text="isApprovedForAll(address,address)")[
            :4
        ].hex()
        data = is_approved_sig + encode(["address", "address"], [owner, operator]).hex()
        result = self.w3.eth.call(
            {"to": self.w3.to_checksum_address(token_address), "data": data}
        )
        is_approved = int.from_bytes(result, byteorder="big") == 1
        return is_approved

    def _check_approval(self) -> Tuple[Any, Any]:
        """Check all required approvals for Polymarket trading.

        Checks:
        - USDC allowances for CTF Exchange, Neg Risk CTF Exchange, Neg Risk Adapter
        - CTF approvals for CTF Exchange, Neg Risk CTF Exchange, Neg Risk Adapter

        :return: Tuple of (approval_status_dict, error_message)
        """
        try:
            self.logger.info(
                f"Checking approvals for Safe: {self.safe_address} on Polygon..."
            )

            # Check USDC allowances
            usdc_ctf_exchange_allowance = self._check_erc20_allowance(
                self.usdc_address, self.safe_address, self.ctf_exchange
            )
            usdc_neg_risk_allowance = self._check_erc20_allowance(
                self.usdc_address, self.safe_address, self.neg_risk_ctf_exchange
            )
            usdc_adapter_allowance = self._check_erc20_allowance(
                self.usdc_address, self.safe_address, self.neg_risk_adapter
            )

            # Check CTF approvals
            ctf_ctf_exchange_approved = self._check_erc1155_approval(
                self.ctf_address, self.safe_address, self.ctf_exchange
            )
            ctf_neg_risk_approved = self._check_erc1155_approval(
                self.ctf_address, self.safe_address, self.neg_risk_ctf_exchange
            )
            ctf_adapter_approved = self._check_erc1155_approval(
                self.ctf_address, self.safe_address, self.neg_risk_adapter
            )

            # Build response
            approval_status = {
                "safe_address": self.safe_address,
                "usdc_allowances": {
                    "ctf_exchange": usdc_ctf_exchange_allowance,
                    "neg_risk_ctf_exchange": usdc_neg_risk_allowance,
                    "neg_risk_adapter": usdc_adapter_allowance,
                },
                "ctf_approvals": {
                    "ctf_exchange": ctf_ctf_exchange_approved,
                    "neg_risk_ctf_exchange": ctf_neg_risk_approved,
                    "neg_risk_adapter": ctf_adapter_approved,
                },
                "all_approvals_set": all(
                    [
                        usdc_ctf_exchange_allowance > 0,
                        usdc_neg_risk_allowance > 0,
                        usdc_adapter_allowance > 0,
                        ctf_ctf_exchange_approved,
                        ctf_neg_risk_approved,
                        ctf_adapter_approved,
                    ]
                ),
            }

            self.logger.info(f"Approval check results: {approval_status}")
            return approval_status, None

        except Exception as e:
            error_msg = f"Error checking approvals: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg
