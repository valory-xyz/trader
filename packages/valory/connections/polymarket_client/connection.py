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

import dataclasses
import json
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
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
from py_clob_client_v2 import BuilderConfig, ClobClient, MarketOrderArgs, OrderType
from py_clob_client_v2.exceptions import PolyApiException
from py_clob_client_v2.order_builder.constants import BUY
from py_clob_client_v2.order_utils.model.order_data_v2 import Side, SignedOrderV2
from py_clob_client_v2.order_utils.model.signature_type_v2 import SignatureTypeV2
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
PARENT_COLLECTION_ID = bytes.fromhex("00" * 32)
CHAIN_ID = 137  # Polygon
MAX_UINT256 = (
    115792089237316195423570985008687907853269984665640564039457584007913129639935
)
POLYMARKET_CATEGORY_TAGS = [
    "business",
    "politics",
    "science",
    "technology",
    "health",
    # "travel",
    "entertainment",
    "weather",
    "finance",
    "international",
]
MARKETS_LIMIT = 300
EVENTS_LIMIT = 200
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


def _validate_builder_code(code: Optional[str], logger: Any) -> str:
    """Validate the operator-supplied builder_code shape.

    The SDK may silently accept a malformed code and produce orders with
    wrong / zero builder attribution — so a misconfigured operator env
    would route revenue share to the wrong (or no) account. Accept only
    ``0x``-prefixed 64-hex-char bytes32 (leading/trailing whitespace is
    stripped for copy-paste tolerance). Blank out and log a WARNING
    otherwise; an empty/None input is the documented "disabled" case and
    is tolerated silently.

    :param code: the raw value from the connection config.
    :param logger: logger to emit the warning through.
    :return: a validated builder_code, or ``""`` if invalid / absent.
    """
    if not code:
        return ""
    code = code.strip()
    if code.startswith("0x") and len(code) == 66:
        try:
            bytes.fromhex(code[2:])
        except ValueError:
            pass
        else:
            return code
    logger.warning(
        f"POLYMARKET_BUILDER_CODE has unexpected shape (len={len(code)}, "
        f"starts_with_0x={code.startswith('0x')}); orders will be "
        "posted without attribution."
    )
    return ""


def _serialize_signed_order_v2(signed: SignedOrderV2) -> Dict[str, Any]:
    """Serialize a v2 signed order to a JSON-safe dict.

    v2 SDK's SignedOrderV2 is a plain dataclass (no `.dict()` method) and
    carries `side` and `signatureType` as IntEnums, which json.dumps refuses.
    We convert enums to their int values here and include the ``clob_version``
    marker so the cache-invalidation check in W5 can distinguish v1 entries.
    """
    data = dataclasses.asdict(signed)
    for key, value in list(data.items()):
        if isinstance(value, Enum):
            data[key] = int(value)
    data["clob_version"] = "v2"
    return data


def _deserialize_signed_order_v2(payload: Dict[str, Any]) -> SignedOrderV2:
    """Rehydrate a v2 signed order from a cached JSON dict.

    The ``clob_version`` marker, if present, is ignored here; cache-invalidation
    logic is expected to reject entries without the v2 marker before calling
    this.
    """
    payload = {k: v for k, v in payload.items() if k != "clob_version"}
    if "side" in payload and not isinstance(payload["side"], Side):
        payload["side"] = Side(payload["side"])
    if "signatureType" in payload and not isinstance(
        payload["signatureType"], SignatureTypeV2
    ):
        payload["signatureType"] = SignatureTypeV2(payload["signatureType"])
    return SignedOrderV2(**payload)


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
        if not self.configuration.config.get("is_running_on_polymarket", False):
            self.logger.warning(
                "Not running on Polymarket environment. PolymarketClientConnection will not initialize."
            )
            return
        self.connection_private_key = self.crypto_store.private_keys.get("ethereum")

        host = self.configuration.config.get("host")
        chain_id = self.configuration.config.get("chain_id")
        builder_program_enabled = self.configuration.config.get(
            "polymarket_builder_program_enabled", True
        )
        builder_code = _validate_builder_code(
            self.configuration.config.get("builder_code"), self.logger
        )

        self.dialogues = SrrDialogues(connection_id=PUBLIC_ID)

        # Build the v2 BuilderConfig. Only the builder_code field matters for
        # attribution; builder_address is optional. When the builder program is
        # disabled or no code is provided, pass None so the SDK defaults to the
        # zero bytes32 (no attribution).
        self.builder_config: Optional[BuilderConfig] = None
        if builder_program_enabled and builder_code:
            self.logger.info(
                f"Builder program enabled. Using builder_code={builder_code[:10]}..."
            )
            self.builder_config = BuilderConfig(builder_code=builder_code)
        elif builder_program_enabled:
            self.logger.info(
                "Builder program enabled but builder_code is empty; "
                "orders will be posted without attribution."
            )

        # Relayer client is kept for Safe execTransaction gas relay (approvals,
        # redemptions, bet placements). v2 only deprecates the builder-signing
        # relay, not the tx-execution relay.
        self.relayer_client = RelayClient(
            relayer_url=RELAYER_URL,
            chain_id=chain_id,
            private_key=self.connection_private_key,
            builder_config=None,
        )
        self.client = ClobClient(
            host,
            chain_id=chain_id,
            key=self.connection_private_key,
            signature_type=2,
            funder=self.safe_address,
            builder_config=self.builder_config,
        )
        self.client.set_api_creds(self.client.create_or_derive_api_key())

        # Load contract addresses. In v2 the collateral token is pUSD; USDC.e
        # is kept only as a wrap-source. The onramp contract exposes
        # wrap()/unwrap() to convert between the two.
        # Future-proof scaffold: env chain (CLOB_VERSION → service.yaml →
        # aea-config.yaml → here) plumbed so the next CLOB migration only
        # wires new reads. The ``"v2"`` stamps elsewhere (signed-order tag,
        # cache-key prefix, allowances-file stamp) are code-shape tags tied
        # to the SDK / file formats, not runtime-switchable.
        self.clob_version = self.configuration.config.get("clob_version", "v2")
        self.collateral_address = to_checksum_address(
            self.configuration.config.get("collateral_address")
        )
        self.usdc_e_address = to_checksum_address(
            self.configuration.config.get("usdc_e_address")
        )
        self.collateral_onramp_address = to_checksum_address(
            self.configuration.config.get("collateral_onramp_address")
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
        self.ctf_collateral_adapter = to_checksum_address(
            self.configuration.config.get("ctf_collateral_adapter_address")
        )
        self.neg_risk_ctf_collateral_adapter = to_checksum_address(
            self.configuration.config.get("neg_risk_ctf_collateral_adapter_address")
        )

        # Initialize Web3 for approval checking
        rpc_url = self.configuration.config.get("polygon_ledger_rpc")
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
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

        try:
            decoded_payload = json.loads(srr_message.payload)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to decode SRR payload: {e}")
            decoded_payload = {}
            payload = None
            error_message = f"Invalid JSON payload: {e}"
        else:
            payload, error_message = self._route_request(
                payload=decoded_payload,
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
            RequestType.FETCH_ORDER_BOOK: self._fetch_order_book,
        }

        self.logger.info(f"Routing request of type: {request_type.value}")

        try:
            params = payload.get("params", {})
            response, error_msg = request_function_map[request_type](**params)
            if error_msg:
                error_msg = str(error_msg)
                # Preserve any extra keys the handler set on its response dict
                # (e.g. ``_place_bet`` attaches ``signed_order_json`` so the
                # caller can cache and retry without re-signing).
                if not isinstance(response, dict):
                    response = {"error": error_msg}
                else:
                    response.setdefault("error", error_msg)
                return response, error_msg

            error_msg = ""
            return response, error_msg

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

    def _place_bet(
        self, token_id: str, amount: float, cached_signed_order_json: str = None
    ) -> Tuple[Any, Any]:
        """Place a bet on Polymarket."""
        signed_order_json = None

        try:
            # Use cached order or create new one. A cached entry is trusted
            # only if it carries the v2 marker added by
            # ``_serialize_signed_order_v2``; v1 entries (missing the marker
            # or with a different shape) are silently dropped and a fresh
            # order is signed.
            signed = None
            if cached_signed_order_json:
                try:
                    signed_dict = json.loads(cached_signed_order_json)
                    if (
                        signed_dict.get("clob_version") == "v2"
                        and "timestamp" in signed_dict
                    ):
                        signed = _deserialize_signed_order_v2(signed_dict)
                        signed_order_json = cached_signed_order_json
                    else:
                        self.logger.warning(
                            "Dropping stale (non-v2) cached signed order; resigning."
                        )
                except (ValueError, TypeError) as e:
                    self.logger.warning(
                        f"Cached signed order could not be parsed ({e}); resigning."
                    )

            if signed is None:
                mo = MarketOrderArgs(
                    token_id=token_id,
                    amount=amount,
                    side=BUY,
                    order_type=OrderType.FOK,
                )
                signed = self.client.create_market_order(mo)
                signed_order_json = json.dumps(_serialize_signed_order_v2(signed))

            # Post order
            resp: Dict = self.client.post_order(signed, OrderType.FOK)

            # Add signed order to response
            if resp:
                resp["signed_order_json"] = signed_order_json

            return resp, None

        except PolyApiException as e:
            error_msg = (
                e.error_msg.get("error")
                if isinstance(e.error_msg, dict) and e.error_msg.get("error")
                else f"Error placing bet: {e}"
            )
            self.logger.error(error_msg)
            # Return error with signed order for retry
            response = {"error": error_msg, "signed_order_json": signed_order_json}
            return response, error_msg

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
            except (requests.exceptions.RequestException, ValueError) as e:
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

    def _fetch_markets_by_tag_slug(
        self, tag_slug: str, end_date_min: str, end_date_max: str
    ) -> Tuple[list, str]:
        """Fetch markets for a tag slug via /events, flattened with per-market tags.

        Hits `/events?tag_slug=X` (paginated), flattens each event's child markets,
        and attaches the event's tag slugs to every market as `_poly_tags`. The
        events endpoint returns markets with the same field shape as `/markets`
        but additionally carries the tag taxonomy required for filtering.

        :param tag_slug: The tag slug to filter events by
        :param end_date_min: Minimum end date filter
        :param end_date_max: Maximum end date filter
        :return: Tuple of (markets_list, error_message)
        """
        offset = 0
        all_markets: list = []

        while True:
            params = {
                "tag_slug": tag_slug,
                "end_date_max": end_date_max,
                "end_date_min": end_date_min,
                "limit": EVENTS_LIMIT,
                "offset": offset,
            }

            events_data, error = self._request_with_retries(
                f"{GAMMA_API_BASE_URL}/events", params=params
            )

            if error:
                return None, error

            if not events_data:
                break

            markets_this_page = 0
            for event in events_data:
                tag_slugs = [
                    t.get("slug") for t in (event.get("tags") or []) if t.get("slug")
                ]
                for market in event.get("markets") or []:
                    market["_poly_tags"] = tag_slugs
                    all_markets.append(market)
                    markets_this_page += 1

            self.logger.info(
                f"  Fetched {len(events_data)} events "
                f"→ {markets_this_page} markets (total: {len(all_markets)})"
            )

            if len(events_data) < EVENTS_LIMIT:
                break

            offset += len(events_data)

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

    def _filter_tradeable_markets(self, markets: list) -> list:
        """Filter to markets that are active and have populated price + CLOB tokens.

        The /events endpoint can surface nested markets that are yes/no-shaped
        but not yet (or no longer) tradeable — empty outcomePrices/clobTokenIds
        or active=False. The old /markets?tag_id=X endpoint filtered these
        server-side. This filter matches that behaviour client-side.

        :param markets: List of market dictionaries
        :return: Markets with non-empty outcomePrices and clobTokenIds, active=True
        """
        tradeable = []
        for market in markets:
            if not market.get("active"):
                continue
            try:
                outcome_prices = json.loads(market.get("outcomePrices") or "[]")
                clob_token_ids = json.loads(market.get("clobTokenIds") or "[]")
            except (json.JSONDecodeError, TypeError) as e:
                self.logger.debug(
                    f"Dropped market {market.get('id')}: "
                    f"malformed JSON in price/token fields ({e})"
                )
                continue
            if outcome_prices and clob_token_ids:
                tradeable.append(market)
        return tradeable

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

    def _fetch_markets(self) -> Tuple[Any, Any]:
        """Fetch current markets from Polymarket with category-based filtering.

        Fetches events per category from /events?tag_slug=X, flattens to markets
        with per-market _poly_tags attached, and filters for Yes/No outcomes +
        tradeable status. The disabled-tags policy filter runs downstream in
        decision_maker_abci's sampling behaviour so legacy bets get a chance
        to refresh their poly_tags via update_market_info before the filter
        runs. Resolved markets (extreme outcome prices) are blacklisted
        downstream by PolymarketFetchMarketBehaviour._blacklist_expired_bets.

        :return: Tuple of (filtered_markets_dict, error_message)
        """
        try:
            end_date_min = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_date_max = (
                datetime.now(timezone.utc) + timedelta(days=MARKETS_TIME_WINDOW_DAYS)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

            filtered_markets_by_category: Dict[str, list] = {}

            self.logger.info(
                f"Fetching markets for {len(POLYMARKET_CATEGORY_TAGS)} categories"
            )
            self.logger.info(f"Time window: {end_date_min} to {end_date_max}")

            for category in POLYMARKET_CATEGORY_TAGS:
                self.logger.info(f"Processing category: {category}")

                category_markets, error = self._fetch_markets_by_tag_slug(
                    category, end_date_min, end_date_max
                )
                if error:
                    self.logger.error(
                        f"  Error fetching markets for '{category}': {error}"
                    )
                    continue

                markets_after_cutoff = self._filter_markets_by_created_at(
                    category_markets
                )
                self.logger.info(
                    f"  Filtered to {len(markets_after_cutoff)} markets with createdAt > {MARKETS_MIN_CREATED_AT}"
                )
                yes_no_markets = self._filter_yes_no_markets(markets_after_cutoff)
                self.logger.info(f"  Filtered to {len(yes_no_markets)} Yes/No markets")

                tradeable_markets = self._filter_tradeable_markets(yes_no_markets)
                self.logger.info(
                    f"  Filtered to {len(tradeable_markets)} tradeable markets "
                    f"(dropped {len(yes_no_markets) - len(tradeable_markets)} "
                    f"inactive / unpriced)"
                )
                if yes_no_markets and not tradeable_markets:
                    self.logger.warning(
                        f"Tradeable filter dropped 100% of "
                        f"{len(yes_no_markets)} markets for category "
                        f"'{category}' — possible upstream schema change"
                    )

                filtered_markets_by_category[category] = tradeable_markets
                self.logger.info(
                    f"  Found {len(tradeable_markets)} markets for '{category}'"
                )

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

        except (requests.exceptions.RequestException, ValueError) as e:
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
            self.logger.info(f"Fetching trades from: {request_url}")

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
        self,
        condition_id: str,
        index_sets: list[int],
        collateral_token: str,
        is_neg_risk: bool = False,
        size: float = 0,
    ) -> Tuple[Any, Any]:
        """Redeem positions on Polymarket.

        :param condition_id: The condition ID (hex string with or without 0x prefix)
        :param index_sets: List of index sets to redeem (uint256[])
        :param collateral_token: The collateral token address
        :param is_neg_risk: Whether this is a negative risk market
        :param size: The size of the position to redeem (for neg risk markets)
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

            # Build transaction based on market type
            if is_neg_risk:
                # For negative risk markets, use neg risk adapter
                # redeemPositions(bytes32,uint256[])
                selector = bytes.fromhex(
                    "dbeccb23"
                )  # redeemPositions(bytes32,uint256[])

                # For neg risk, index_sets contains bit-shifted outcome_index (1 << outcome_index)
                # We need to build redeem_amounts array [yes_amount, no_amount]
                # The size parameter tells us the amount to redeem
                redeem_amounts = [0, 0]
                if index_sets:
                    # Extract outcome_index from bit-shifted value
                    # index_sets[0] = 1 << outcome_index # noqa: E800
                    # So: 1 (0b01) -> outcome_index = 0, 2 (0b10) -> outcome_index = 1
                    index_set = index_sets[0]
                    outcome_index = 0
                    while index_set > 1:
                        index_set >>= 1
                        outcome_index += 1
                    redeem_amounts[outcome_index] = int(size)

                encoded_args = encode(
                    ["bytes32", "uint256[]"],
                    [condition_id_bytes, redeem_amounts],
                )
                calldata = selector + encoded_args
                target_address = self.neg_risk_ctf_collateral_adapter
                market_type = "negative risk (via NegRiskCtfCollateralAdapter)"
            else:
                # Standard markets are redeemed via CtfCollateralAdapter so the
                # USDC.e payout is unwrapped to pUSD before reaching the Safe.
                # The adapter exposes the same redeemPositions selector as the
                # raw CTF, so the calldata shape is unchanged.
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
                target_address = self.ctf_collateral_adapter
                market_type = "standard (via CtfCollateralAdapter)"

            # Create SafeTransaction
            tx = SafeTransaction(
                to=target_address,
                operation=OperationType.Call,
                data="0x" + calldata.hex(),
                value="0",
            )

            # Execute transaction
            result = self.relayer_client.execute(
                transactions=[tx], metadata=f"Redeem {market_type} conditional tokens"
            )

            transaction_data = result.get_transaction()
            self.logger.info(
                f"Redeemed {market_type} positions for condition {condition_id}: {transaction_data}"
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
        - CTF for CtfCollateralAdapter (redeem)
        - CTF for NegRiskCtfCollateralAdapter (redeem)

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
                to=self.collateral_address,
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
                to=self.collateral_address,
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
                to=self.collateral_address,
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

            # Approvals for CtfCollateralAdapter / NegRiskCtfCollateralAdapter.
            # These adapters route redemption through the CTF while unwrapping
            # USDC.e → pUSD on the Safe's behalf. The redeem path receives
            # USDC.e from CTF and pushes pUSD to the Safe — it never pulls any
            # ERC20 from the Safe — so only ERC1155 operator rights on CTF
            # positions are needed.
            ctf_approve_collateral_adapter = SafeTransaction(
                to=self.ctf_address,
                operation=OperationType.Call,
                data=self._encode_set_approval_for_all(
                    self.ctf_collateral_adapter, True
                ),
                value="0",
            )

            ctf_approve_neg_risk_collateral_adapter = SafeTransaction(
                to=self.ctf_address,
                operation=OperationType.Call,
                data=self._encode_set_approval_for_all(
                    self.neg_risk_ctf_collateral_adapter, True
                ),
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
                ctf_approve_collateral_adapter,
                ctf_approve_neg_risk_collateral_adapter,
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
        - CTF approvals for CTF Exchange, Neg Risk CTF Exchange, Neg Risk Adapter,
          CtfCollateralAdapter, NegRiskCtfCollateralAdapter

        :return: Tuple of (approval_status_dict, error_message)
        """
        try:
            self.logger.info(
                f"Checking approvals for Safe: {self.safe_address} on Polygon..."
            )

            # Check USDC allowances
            usdc_ctf_exchange_allowance = self._check_erc20_allowance(
                self.collateral_address, self.safe_address, self.ctf_exchange
            )
            usdc_neg_risk_allowance = self._check_erc20_allowance(
                self.collateral_address, self.safe_address, self.neg_risk_ctf_exchange
            )
            usdc_adapter_allowance = self._check_erc20_allowance(
                self.collateral_address, self.safe_address, self.neg_risk_adapter
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
            ctf_collateral_adapter_approved = self._check_erc1155_approval(
                self.ctf_address, self.safe_address, self.ctf_collateral_adapter
            )
            ctf_neg_risk_collateral_adapter_approved = self._check_erc1155_approval(
                self.ctf_address,
                self.safe_address,
                self.neg_risk_ctf_collateral_adapter,
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
                    "ctf_collateral_adapter": ctf_collateral_adapter_approved,
                    "neg_risk_ctf_collateral_adapter": (
                        ctf_neg_risk_collateral_adapter_approved
                    ),
                },
                "all_approvals_set": all(
                    [
                        usdc_ctf_exchange_allowance > 0,
                        usdc_neg_risk_allowance > 0,
                        usdc_adapter_allowance > 0,
                        ctf_ctf_exchange_approved,
                        ctf_neg_risk_approved,
                        ctf_adapter_approved,
                        ctf_collateral_adapter_approved,
                        ctf_neg_risk_collateral_adapter_approved,
                    ]
                ),
            }

            self.logger.info(f"Approval check results: {approval_status}")
            return approval_status, None

        except Exception as e:
            error_msg = f"Error checking approvals: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg

    def _fetch_order_book(self, token_id: str) -> Tuple[Any, Any]:
        """Fetch the order book for a given token from the CLOB.

        v2 ``get_order_book`` returns the raw CLOB response as a plain dict
        (v1 wrapped it in an ``OrderBookSummary`` object); each level is a
        ``{"price": "...", "size": "..."}`` dict.

        :param token_id: The CLOB token ID for the outcome.
        :return: Tuple of (order_book_dict, error_string).
        """
        try:
            raw = self.client.get_order_book(token_id)
            raw_asks = (raw.get("asks") if isinstance(raw, dict) else raw.asks) or []
            raw_bids = (raw.get("bids") if isinstance(raw, dict) else raw.bids) or []
            min_order_size = (
                raw.get("min_order_size")
                if isinstance(raw, dict)
                else raw.min_order_size
            )

            def _level_to_dict(level: Any) -> Dict[str, str]:
                if isinstance(level, dict):
                    return {
                        "price": str(level.get("price")),
                        "size": str(level.get("size")),
                    }
                return {"price": str(level.price), "size": str(level.size)}

            return {
                "asks": [_level_to_dict(a) for a in raw_asks],
                "bids": [_level_to_dict(b) for b in raw_bids],
                "min_order_size": (
                    str(min_order_size) if min_order_size is not None else None
                ),
            }, None
        except Exception as e:
            error_msg = f"Error fetching order book for token {token_id}: {str(e)}"
            self.logger.exception(error_msg)
            return None, error_msg
