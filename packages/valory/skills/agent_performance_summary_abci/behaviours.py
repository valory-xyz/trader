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

"""This module contains the behaviour of the skill which is responsible for agent performance summary file updation."""

import bisect
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import partial
from typing import Any, Dict, Generator, List, Optional, Set, Tuple, Type, cast
from urllib.parse import urlencode

import requests

from packages.valory.connections.polymarket_client.connection import (
    is_unclaimable_v2,
)
from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.contracts.erc20.contract import ERC20TokenContract as ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.achievements_checker.bet_payout_checker import (
    BetPayoutChecker,
)
from packages.valory.skills.agent_performance_summary_abci.feed import (
    EventType,
    field,
    format_amount,
    format_date,
    market_url,
    record_event,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher as BasePredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client import (
    build_requester_url,
    chain_id_for_platform,
    parse_requester_payload,
    rows_as_subgraph_mech_requests,
    uses_mech_analytics,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import (
    PolymarketPredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    BetStatus,
    PredictionsFetcher,
    compute_funds_locked_from_bets,
    now_ts,
    parse_current_answer,
    parse_timestamp,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.requests import (
    APTQueryingBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    Achievements,
    AgentDetails,
    AgentPerformanceData,
    AgentPerformanceMetrics,
    AgentPerformanceSummary,
    LEADERBOARD_CLOCK_SKEW_SECONDS,
    LEADERBOARD_DEFAULT_NOT_RANKED_REASON,
    LEADERBOARD_WINDOWS,
    LeaderboardAgentType,
    LeaderboardData,
    LeaderboardWindow,
    LeaderboardWindowRank,
    NotRankedReason,
    PROFIT_OVER_TIME_SCHEMA_VERSION,
    PerformanceMetricsData,
    PerformanceStatsData,
    PredictionHistory,
    ProfitDataPoint,
    ProfitOverTimeData,
    SharedState,
    flat_mech_fee_usd,
    get_leaderboard_agent_type,
    is_allowed_leaderboard_url,
    is_not_ranked_reason,
)
from packages.valory.skills.agent_performance_summary_abci.payloads import (
    FetchPerformanceDataPayload,
    UpdateAchievementsPayload,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
    FetchPerformanceDataRound,
    UpdateAchievementsRound,
)

RESOLVED_STATUSES = frozenset(
    {BetStatus.WON.value, BetStatus.LOST.value, BetStatus.INVALID.value}
)
QUESTION_DATA_SEPARATOR = "\u241f"
PREDICT_MARKET_DURATION_DAYS = 4
WXDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"  # wxDAI on Gnosis Chain
PUSD_ADDRESS = (
    "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"  # pUSD on Polygon (v2 collateral)
)
USDC_DECIMALS_DIVISOR = 10**6  # pUSD has 6 decimals, same as USDC.e
POLYGON_NATIVE_TOKEN_ADDRESS = (
    "0x0000000000000000000000000000000000001010"  # POL on Polygon  # nosec B105
)
POLYGON_CHAIN_ID = 137  # Polygon chain ID
LIFI_QUOTE_URL = "https://li.quest/v1/quote"  # LiFi API endpoint

# Rate limiting for LiFi API: 200 requests per 2 hours
LIFI_RATE_LIMIT_SECONDS = 7200  # 2 hours
# Use 1 POL as the base amount for rate calculation
RATE_CALC_BASE_AMOUNT = 10**18  # 1 POL in wei

INVALID_ANSWER_HEX = (
    "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)

PERCENTAGE_FACTOR = 100
WEI_IN_ETH = 10**18  # 1 ETH = 10^18 wei
SECONDS_PER_DAY = 86400
MECH_LOOKBACK_SECONDS = 2 * SECONDS_PER_DAY  # 48h lookback for mech watermark fallback
# mech-analytics serves a request only once scored, up to ~6 days late.
MECH_ANALYTICS_LOOKBACK_SECONDS = 7 * SECONDS_PER_DAY
NA = "N/A"
UPDATE_INTERVAL = 1800  # 30 mins
LEADERBOARD_REFRESH_INTERVAL = 3600
LEADERBOARD_REQUEST_TIMEOUT = 10.0
TX_HISTORY_DEPTH = 25  # match healthcheck slice length
POLYMARKET_ACHIEVEMENT_ROI_THRESHOLD = 1.5
POLYMARKET_ACHIEVEMENT_DESCRIPTION_TEMPLATE = """My Polystrat agent just made {roi}\u00d7 ROI on Polymarket! \U0001f680

Check it out\U0001f447
{{achievement_url}}"""
OMENSTRAT_ACHIEVEMENT_ROI_THRESHOLD = 1.5
OMENSTRAT_ACHIEVEMENT_DESCRIPTION_TEMPLATE = """My Omenstrat agent just made {roi}\u00d7 ROI on Omen Markets! \U0001f680

Check it out\U0001f447
{{achievement_url}}"""


MIN_TRADES_FOR_ROI_DISPLAY = 10
MORE_TRADES_NEEDED_TEXT = "More trades needed"

# Small gaps between the series and the KPI's settled count are expected (a
# mech landing between the two reads); anything larger triggers a rebuild.
_RESIDUAL_TOLERANCE = 5
# Days to wait before the next residual rebuild. Each rebuild that leaves
# the drift in place moves one step up, so an agent whose fetched requests
# and ``total`` genuinely disagree stops re-paginating its history daily.
_RESIDUAL_REBUILD_BACKOFF_DAYS = (1, 7, 30)


def _usd_amount(value: Any) -> Optional[Decimal]:
    """Return a non-negative USD amount from a decoded JSON value, or ``None``.

    Strings are parsed exactly (mech-analytics sends sub-cent charges as
    strings); numbers go through ``str`` so a float keeps its printed value.

    :param value: a value from a decoded JSON response
    :return: the amount, or ``None`` when absent, not a number, negative or
        not finite
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


def _cost_or_flat_fee(cost: Optional[Decimal], request_count: int) -> Decimal:
    """Return a known cost, or the flat fee for ``request_count`` requests.

    :param cost: the known USD cost, ``None`` when unknown
    :param request_count: the number of requests the cost belongs to
    :return: ``cost``, or ``flat_mech_fee_usd(request_count)`` without one
    """
    return flat_mech_fee_usd(request_count) if cost is None else cost


MechRequestCosts = Dict[Tuple[str, int], List[Decimal]]


def _take_cost(costs: MechRequestCosts, key: Tuple[str, int]) -> Decimal:
    """Remove and return the cost of one request with ``key``.

    :param costs: each request's cost by ``(title, timestamp)``; modified
    :param key: the request's ``(title, timestamp)``
    :return: its cost, or the flat fee when none is known
    """
    known = costs.get(key)
    return known.pop(0) if known else flat_mech_fee_usd(1)


def _parse_iso_timestamp(value: Any) -> Optional[int]:
    """Return an ISO 8601 timestamp (UTC if naive) as UNIX seconds, or ``None``.

    :param value: a value from a decoded JSON response, e.g. ``2026-01-01T00:00:00.000Z``
    :return: the UNIX timestamp in seconds, or ``None``
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def leaderboard_request_url(base: str, query: str) -> str:
    """Append ``query`` to the configured leaderboard URL.

    :param base: the configured ``olas_predict_leaderboard_url``
    :param query: the encoded query string
    :return: the request URL
    """
    if base.endswith(("?", "&")):
        return f"{base}{query}"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{query}"


def parse_leaderboard_window(  # pylint: disable=too-many-return-statements,too-many-arguments
    status_code: int,
    body: bytes,
    agent_type: LeaderboardAgentType,
    window: LeaderboardWindow,
    safe_address: str,
    now: int,
    api_url: str,
    logger: Any,
) -> Optional[LeaderboardWindowRank]:
    """Validate olas-predict's answer for one window.

    :param status_code: the HTTP status code
    :param body: the raw response body
    :param agent_type: ``omenstrat`` or ``polystrat``
    :param window: one of ``LEADERBOARD_WINDOWS``
    :param safe_address: the agent's lowercased Safe address
    :param now: the timestamp to stamp a successful answer with
    :param api_url: the configured ``olas_predict_leaderboard_url``
    :param logger: where to report a rejected answer
    :return: the window's rank, or ``None`` when the answer is unusable
    """
    if status_code != 200:
        logger.warning(
            f"Leaderboard {window} responded {status_code}; keeping the previous rank"
        )
        return None

    try:
        data = json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(f"Leaderboard {window} JSON parse failed: {exc}")
        return None

    def _reject(reason: str) -> None:
        logger.warning(
            f"Leaderboard {window} answer {reason}; keeping the previous rank"
        )

    if not isinstance(data, dict):
        _reject("is not an object")
        return None
    if data.get("window") != window or data.get("agentType") != agent_type:
        _reject(
            f"is for {data.get('agentType')!r}/{data.get('window')!r}, "
            f"not {agent_type}/{window}"
        )
        return None

    agents = data.get("agents")
    agent = agents[0] if isinstance(agents, list) and agents else None
    if not isinstance(agent, dict) or (
        str(agent.get("address", "")).lower() != safe_address
    ):
        _reject("has no entry for this agent")
        return None

    ranked = agent.get("ranked")
    if not isinstance(ranked, bool):
        _reject("has no ranked flag")
        return None

    rank_by_roi, rank_by_pnl = agent.get("rankByRoi"), agent.get("rankByPnl")
    reason: Optional[NotRankedReason] = None
    if not ranked:
        rank_by_roi = rank_by_pnl = None
        reason = agent.get("notRankedReason")
        if not is_not_ranked_reason(reason):
            logger.warning(
                f"Leaderboard {window} gave an unknown notRankedReason "
                f"{reason!r}; storing {LEADERBOARD_DEFAULT_NOT_RANKED_REASON}"
            )
            reason = LEADERBOARD_DEFAULT_NOT_RANKED_REASON

    url_value = agent.get("leaderboardUrl")
    if not is_allowed_leaderboard_url(url_value, api_url):
        if url_value is not None:
            logger.warning(
                f"Leaderboard {window} link {url_value!r} is not on the "
                "olas-predict leaderboard page; serving the bare page"
            )
        url_value = None

    updated_at = _parse_iso_timestamp(data.get("updatedAt"))
    if updated_at is not None and updated_at > now + LEADERBOARD_CLOCK_SKEW_SECONDS:
        logger.warning(
            f"Leaderboard {window} updatedAt is in the future; "
            "judging freshness by the fetch time"
        )
        updated_at = None

    try:
        return LeaderboardWindowRank(
            ranked=ranked,
            fetched_at=now,
            not_ranked_reason=reason,
            rank_by_roi=rank_by_roi,
            rank_by_pnl=rank_by_pnl,
            total_ranked=data.get("totalRanked"),
            leaderboard_url=url_value,
            updated_at=updated_at,
        )
    except ValueError:
        _reject("has invalid ranks or totalRanked")
        return None


def get_within_deadline(url: str, timeout: float) -> Tuple[int, bytes]:
    """GET ``url``, giving up once the whole request has taken ``timeout``.

    :param url: the request URL
    :param timeout: the limit for the whole request, in seconds
    :return: the status code and the body
    :raises Timeout: if the body is not complete within ``timeout``
    """
    deadline = time.monotonic() + timeout
    with requests.get(url, timeout=timeout, stream=True) as response:
        body = bytearray()
        # ``timeout`` above bounds each read, so read a byte at a time: a server
        # dripping bytes cannot then hold the worker past the deadline
        for chunk in response.iter_content(chunk_size=1):
            if time.monotonic() > deadline:
                raise requests.Timeout(f"no complete answer within {timeout}s")
            body += chunk
        return response.status_code, bytes(body)


def refresh_leaderboard(  # pylint: disable=too-many-arguments
    shared_state: SharedState,
    logger: Any,
    api_url: str,
    agent_type: LeaderboardAgentType,
    safe_address: str,
    now: int,
) -> None:
    """Fetch every window from olas-predict and store each usable answer; never raises.

    :param shared_state: the skill state the ranks are stored on
    :param logger: the skill logger (``logging`` is thread-safe)
    :param api_url: the configured ``olas_predict_leaderboard_url``
    :param agent_type: ``omenstrat`` or ``polystrat``
    :param safe_address: the agent's lowercased Safe address
    :param now: the timestamp to stamp successful answers with
    """
    for window in LEADERBOARD_WINDOWS:
        try:
            query = urlencode(
                {"agentType": agent_type, "window": window, "addresses": safe_address}
            )
            status_code, body = get_within_deadline(
                leaderboard_request_url(api_url, query), LEADERBOARD_REQUEST_TIMEOUT
            )
            entry = parse_leaderboard_window(
                status_code,
                body,
                agent_type,
                window,
                safe_address,
                now,
                api_url,
                logger,
            )
            if entry is not None:
                shared_state.update_leaderboard_window(window, entry)
        except requests.Timeout:
            # olas-predict is hanging: don't spend a timeout per window
            logger.warning(
                f"Leaderboard {window} timed out after "
                f"{LEADERBOARD_REQUEST_TIMEOUT}s; keeping the previous "
                "ranks until the next refresh"
            )
            return
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(
                f"Leaderboard {window} fetch failed: {e}; keeping the previous rank",
                exc_info=True,
            )


class FetchPerformanceSummaryBehaviour(
    APTQueryingBehaviour,
):
    """A behaviour to fetch and store the agent performance summary file."""

    matching_round = FetchPerformanceDataRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._agent_performance_summary: Optional[AgentPerformanceSummary] = None
        self._final_roi: Optional[float] = None
        self._partial_roi: Optional[float] = None
        self._total_mech_requests: Optional[int] = None
        self._open_market_requests: Optional[int] = None
        # ``(title, timestamp)`` of each request counted in
        # ``_open_market_requests``; ``None`` until that count is computed.
        self._open_market_request_keys: Optional[List[Tuple[str, int]]] = None
        # USD cost of the requests counted in ``_total_mech_requests``,
        # ``_open_market_requests`` and ``_settled_mech_requests_count``;
        # ``None`` alongside an unknown count.
        self._total_mech_cost_usd: Optional[Decimal] = None
        self._open_market_cost_usd: Optional[Decimal] = None
        self._settled_mech_cost_usd: Optional[Decimal] = None
        self._mech_request_lookup: Optional[dict] = None
        # Each fetched request's cost, keyed by ``(title, timestamp)``.
        self._request_costs: MechRequestCosts = {}
        self._fetched_mech_requests: List[dict] = []
        self._update_interval: int = UPDATE_INTERVAL
        self._last_update_timestamp: int = 0
        # ``None`` = "unknown this round" (fetch failure); ``0`` = "genuinely no
        # requests". The distinction is load-bearing: ``FetchPerformanceSummaryBehaviour``
        # is re-instantiated on every entry into its round, so there is no prior-round
        # ``self.`` state to fall back on. If this defaulted to ``0`` a fetch failure
        # would silently pass through ``calculate_roi`` as ``settled_mech_costs = 0``,
        # producing a real (undercounted) ROI float that would then overwrite the
        # previously-persisted Total ROI (the ``is_primary=True`` metric users see).
        # Keeping it ``None`` funnels the failure through ``calculate_roi`` →
        # ``final_roi=None`` → metric value = ``NA`` → NA-preservation triggers.
        self._settled_mech_requests_count: Optional[int] = None
        # ``None`` until a profit series exists to split settled requests into
        # placed and unplaced.
        self._placed_mech_requests_count: Optional[int] = None
        self._unplaced_mech_requests_count: Optional[int] = None
        # Cache for POL to USDC conversion rate
        self._pol_usdc_rate: Optional[float] = None  # Rate: 1 POL = X USDC
        self._pol_usdc_rate_timestamp: float = 0.0

    def _should_update(self) -> bool:
        """Check if we should update."""
        existing_summary = self.shared_state.read_existing_performance_summary()

        if not existing_summary or self.synchronized_data.period_count == 0:
            return True  # First run

        # Refresh immediately if post_tx_settlement_round observed since last update
        # which indicates a tx was executed last period meaning either a bet was placed, a bet was redeemed, or a mech request was placeed
        # in that case we update the metrics
        if self._post_tx_round_detected():
            return True

        time_since_last = self.shared_state.synced_timestamp - (
            existing_summary.timestamp or 0
        )
        return time_since_last >= self._update_interval

    def _post_tx_round_detected(self) -> bool:
        """Detect whether post_tx_settlement_round occurred since last update.

        :return: True if post_tx_settlement_round was detected in recent history
        """
        try:
            abci_app = self.context.state.round_sequence.abci_app  # type: ignore
            previous_rounds = getattr(abci_app, "_previous_rounds", [])
            for rnd in reversed(previous_rounds[-TX_HISTORY_DEPTH:]):
                rnd_id = getattr(rnd, "round_id", None)
                if rnd_id == "post_tx_settlement_round":
                    return True
            return False
        except Exception as e:
            self.context.logger.debug(
                f"post-tx detection via round history skipped: {e}"
            )
            return False

    def _fetch_polymarket_open_position_titles(
        self,
    ) -> Generator[None, None, Optional[Set[str]]]:
        """Fetch open position titles from Polymarket.

        Returns a set of position titles (market questions) for positions
        that are currently open (not redeemed). These are used to identify
        which mech requests should be counted as 'open' (not settled).

        :return: Set of position titles, or ``None`` when the fetch failed
        :yield: None
        """
        try:
            # Prepare payload - FETCH_ALL_POSITIONS with no redeemable filter
            payload = {
                "request_type": RequestType.FETCH_ALL_POSITIONS.value,
                "params": {},  # No redeemable param = returns all positions
            }

            positions = yield from self.send_polymarket_connection_request(payload)

            if not isinstance(positions, list):
                self.context.logger.warning(
                    f"Polymarket positions fetch failed: {positions}"
                )
                return None

            # Extract titles from positions. Unclaimable V2 rows aren't open.
            titles = {
                p.get("title", "")
                for p in positions
                if isinstance(p, dict)
                and p.get("title", "")
                and not is_unclaimable_v2(p)
            }

            self.context.logger.info(
                f"Fetched {len(positions)} positions from Polymarket, "
                f"extracted {len(titles)} unique titles"
            )
            return titles

        except Exception as e:
            self.context.logger.error(f"Error fetching Polymarket positions: {e}")
            return None

    @property
    def shared_state(self) -> SharedState:
        """Return the shared state."""
        return cast(SharedState, self.context.state)

    @property
    def market_open_timestamp(self) -> int:
        """Return the UTC timestamp for market open."""
        synced_dt = datetime.fromtimestamp(
            self.shared_state.synced_timestamp, tz=timezone.utc
        )

        utc_midnight_synced = datetime(
            year=synced_dt.year,
            month=synced_dt.month,
            day=synced_dt.day,
            tzinfo=timezone.utc,
        )

        timestamp = int(
            (
                utc_midnight_synced - timedelta(days=PREDICT_MARKET_DURATION_DAYS)
            ).timestamp()
        )
        return timestamp

    def _get_total_mech_requests(
        self, agent_safe_address: str
    ) -> Generator[None, None, Optional[int]]:
        """Get total number of mech requests (cached).

        :param agent_safe_address: The agent's safe address
        :return: Total number of mech requests, or ``None`` when the
            fetch failed and no cached value is available. Callers MUST
            distinguish ``None`` (unknown, cannot compute) from ``0``
            (genuinely no requests) - multiplying ``None`` into the
            mech cost inflates ROI silently.
        :yield: None
        """
        if self._total_mech_requests is not None:
            return self._total_mech_requests

        # Flag-on path: read the cumulative count from mech-analytics'
        # per-address usage endpoint. The subgraph counter this used to
        # read (``sender.totalMarketplaceRequests``) is only incremented
        # on the on-chain MarketplaceRequest event and freezes for
        # off-chain volume post-switch, so the pre-migration read
        # undercounts the mech cost as off-chain adoption grows.
        # ``/v1/metrics/requester/{chain_id}/{address}`` returns the
        # per-window rollups for this exact Safe on this exact chain
        # (Gnosis Safe proxies CREATE2 to the same address on every
        # chain, so ``chain_id`` scoping is required).
        if uses_mech_analytics(self.params):
            # Async GET via the framework's ``get_http_response`` — the
            # sync ``requests.get`` path would block the FSM round
            # (Tendermint heartbeats + ABCI message pumps stall while
            # the socket is waiting). ``mech_analytics_client`` still
            # exposes the URL builder and payload parser so the sync
            # (helper-side) and async (behaviour-side) call sites share
            # the same URL and validation rules.
            url = build_requester_url(
                base_url=self.params.mech_analytics_url,
                chain_id=chain_id_for_platform(self.params.is_running_on_polymarket),
                address=agent_safe_address,
            )
            response = yield from self.get_http_response(method="GET", url=url)
            usage = None
            if response.status_code == 200:
                try:
                    usage = parse_requester_payload(
                        json.loads(response.body.decode()), self.context.logger
                    )
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    self.context.logger.error(
                        f"mech-analytics /requester JSON parse failed: {exc}"
                    )
            else:
                self.context.logger.error(
                    f"mech-analytics /requester responded {response.status_code}"
                )
            # ``None`` = transport / schema failure. An unknown Safe
            # returns a zero-shaped body (not None), so a real 0 count
            # still caches correctly. Return ``None`` (not 0) so callers
            # short-circuit cost math this round instead of computing a
            # zero mech cost and reporting inflated ROI.
            if usage is None:
                self.context.logger.warning(
                    "mech-analytics /requester fetch failed; skipping "
                    "total_mech_requests for this round"
                )
                return None
            all_window = (usage.get("windows") or {}).get("all") or {}
            self._total_mech_requests = int(all_window.get("n_mech_requests") or 0)
            # ``mech_fee_usd`` is the real charges plus the flat fee for
            # requests without one; a deployment that predates the field
            # gets the flat fee for every request.
            raw_fee = all_window.get("mech_fee_usd")
            fee = _usd_amount(raw_fee)
            if fee is None and raw_fee is not None:
                self.context.logger.warning(
                    f"mech-analytics /requester served an unusable "
                    f"mech_fee_usd={raw_fee!r}; charging the flat fee per request"
                )
            self._total_mech_cost_usd = _cost_or_flat_fee(
                fee, self._total_mech_requests
            )
            self.context.logger.info(
                f"{self._total_mech_requests=}, {self._total_mech_cost_usd=}"
            )
            return self._total_mech_requests

        mech_sender = yield from self._fetch_mech_sender(
            agent_safe_address=agent_safe_address,
            timestamp_gt=self.market_open_timestamp,
        )

        if not mech_sender or mech_sender.get("totalMarketplaceRequests") is None:
            self._total_mech_requests = 0
            self._total_mech_cost_usd = Decimal(0)
            return 0

        self._total_mech_requests = int(mech_sender["totalMarketplaceRequests"])
        # The subgraph sees only on-chain requests, each at the flat fee.
        self._total_mech_cost_usd = flat_mech_fee_usd(self._total_mech_requests)
        self.context.logger.info(f"{self._total_mech_requests=}")
        return self._total_mech_requests

    def _get_open_market_requests(
        self, agent_safe_address: str
    ) -> Generator[None, None, Optional[int]]:
        """Get number of mech requests for open markets (cached).

        :param agent_safe_address: The agent's safe address
        :return: Number of open market requests, or ``None`` when any of
            its fetches failed and no cached value is available. Callers MUST
            distinguish ``None`` (unknown) from ``0`` (no open-market
            requests) — treating unknown as 0 in
            ``_calculate_settled_mech_requests`` would compute
            ``settled = total - 0 = total``, counting every open request
            as settled and over-inflating ``settled_mech_costs`` (the
            mirror silent-zero of the total-fetch failure that
            ``_get_total_mech_requests`` already handles).
        :yield: None
        """
        if self._open_market_requests is not None:
            return self._open_market_requests

        # Flag-on path: pull the per-Safe request list from
        # mech-analytics scored rows instead of the marketplace
        # subgraph's ``sender.requests`` (which stops seeing the
        # content of off-chain requests post-switch). Without this
        # branch, an on-chain ``total`` from mech-analytics minus an
        # ``open`` from the frozen subgraph over-states ``settled``.
        if uses_mech_analytics(self.params):
            since = datetime.fromtimestamp(self.market_open_timestamp, tz=timezone.utc)
            # Async paginate via the framework HTTP protocol (defined
            # on the parent ``APTQueryingBehaviour``) so the FSM round
            # doesn't block on synchronous ``requests.get``.
            rows = yield from self._page_mech_analytics_scored_rows(
                requester=agent_safe_address,
                since=since,
            )
            if rows is None:
                self.context.logger.warning(
                    "mech-analytics scored-rows fetch failed; skipping "
                    "open_market_requests for this round"
                )
                # ``None`` propagates through
                # ``_calculate_settled_mech_requests`` →
                # ``self._settled_mech_requests_count = None`` →
                # ``calculate_roi`` / ``_calculate_performance_metrics``
                # short-circuit → Total ROI metric = ``NA`` →
                # NA-preservation keeps the last persisted good value.
                return None
            last_four_days_requests = rows_as_subgraph_mech_requests(rows)
        else:
            # Fetch mech sender to get recent requests
            mech_sender = yield from self._fetch_mech_sender(
                agent_safe_address=agent_safe_address,
                timestamp_gt=self.market_open_timestamp,
            )

            if mech_sender is None:
                self.context.logger.warning(
                    "Mech sender fetch failed; skipping open_market_requests "
                    "for this round"
                )
                return None

            last_four_days_requests = mech_sender.get("requests", [])

        # A failed fetch must not read as "nothing open": that would release
        # every pending request from the profit series.
        if self.params.is_running_on_polymarket:
            # For Polymarket: get open positions from connection
            open_market_titles = (
                yield from self._fetch_polymarket_open_position_titles()
            )
            if open_market_titles is None:
                self.context.logger.warning(
                    "Polymarket open positions fetch failed; skipping "
                    "open_market_requests for this round"
                )
                return None
        else:
            # For Omen: get open markets from subgraph
            open_markets = yield from self._fetch_open_markets(
                timestamp_gt=self.market_open_timestamp,
            )

            if open_markets is None:
                self.context.logger.warning(
                    "Open markets fetch failed; skipping open_market_requests "
                    "for this round"
                )
                return None

            if not open_markets:
                self._open_market_requests = 0
                self._open_market_request_keys = []
                self._open_market_cost_usd = Decimal(0)
                return 0

            # Get titles of open markets
            open_market_titles = {
                q["question"].split(QUESTION_DATA_SEPARATOR, 4)[0]
                for q in open_markets
                if q.get("question")
            }

        # Keep the requests for still-open markets, not just their count, so
        # the profit series holds back exactly the requests counted here.
        open_requests: List[dict] = []
        open_request_keys: List[Tuple[str, int]] = []
        for request in last_four_days_requests:
            key = self._mech_request_key(request)
            if key[0] and key[0] in open_market_titles:
                open_requests.append(request)
                open_request_keys.append(key)
        self._open_market_request_keys = open_request_keys
        self._open_market_requests = len(open_request_keys)
        self._open_market_cost_usd = sum(
            (self._mech_request_cost_usd(request) for request in open_requests),
            Decimal(0),
        )
        self.context.logger.info(
            f"{self._open_market_requests=}, {self._open_market_cost_usd=}"
        )
        return self._open_market_requests

    def _calculate_settled_mech_requests(
        self, agent_safe_address: str
    ) -> Generator[None, None, Optional[int]]:
        """Calculate the number of settled mech requests (excludes open markets).

        :param agent_safe_address: The agent's safe address
        :return: Number of settled mech requests, or ``None`` when
            ``total_mech_requests`` could not be fetched. Callers MUST
            treat ``None`` as "unknown, skip cost math" rather than 0.
        :yield: None
        """
        # Get total mech requests (uses cache if available)
        total_mech_requests = yield from self._get_total_mech_requests(
            agent_safe_address
        )

        # ``None`` = fetch failure, propagate so callers short-circuit
        # cost math. ``0`` = genuinely no requests, return 0.
        if total_mech_requests is None:
            return None
        if total_mech_requests == 0:
            self._settled_mech_cost_usd = Decimal(0)
            return 0

        # Get open market requests (uses cache if available)
        open_market_requests = yield from self._get_open_market_requests(
            agent_safe_address
        )
        # ``None`` = fetch failure for the open-request side. Propagate
        # so ``self._settled_mech_requests_count`` stays ``None`` and
        # the ROI guards funnel the failure into ``NA`` (rather than
        # ``settled = total - 0 = total``, which would silently
        # over-inflate ``settled_mech_costs``).
        if open_market_requests is None:
            return None

        # where settled = Total - Open, for the count and for the cost
        self._settled_mech_cost_usd = max(
            _cost_or_flat_fee(self._total_mech_cost_usd, total_mech_requests)
            - _cost_or_flat_fee(self._open_market_cost_usd, open_market_requests),
            Decimal(0),
        )
        return total_mech_requests - open_market_requests

    def calculate_roi(
        self,
    ) -> Generator[None, None, Tuple[Optional[float], Optional[float]]]:
        """Calculate the ROI."""
        agent_safe_address = self.synchronized_data.safe_contract_address

        trader_agent = yield from self._fetch_trader_agent(
            agent_safe_address=agent_safe_address,
        )
        if (
            trader_agent is None
            or trader_agent.get("serviceId") is None
            or trader_agent.get("totalTraded") is None
            or trader_agent.get("totalExpectedPayout") is None
        ):
            self.context.logger.warning(
                f"Trader agent data not found or incomplete for {agent_safe_address} "
                f"(queried as {agent_safe_address.lower()}) and {trader_agent=}"
            )
            return None, None

        staking_service = yield from self._fetch_staking_service(
            service_id=trader_agent["serviceId"],
        )
        if staking_service is None:
            self.context.logger.warning(
                f"Staking service data not found for service id {trader_agent['serviceId']}"
            )
            return None, None

        olas_in_usd_price = yield from self._fetch_olas_in_usd_price()
        if olas_in_usd_price is None:
            self.context.logger.warning("Olas in USD price data not found")
            return None, None

        settled_mech_requests = self._settled_mech_requests_count
        if settled_mech_requests is None:
            # ``None`` means ``_calculate_settled_mech_requests`` failed
            # this round; propagate as ``(None, None)`` so the caller
            # sets the Total ROI metric to ``NA``, which lets
            # ``_save_agent_performance_summary``'s NA-preservation
            # fallback keep the previously-persisted good value instead
            # of overwriting with a cost-undercounted number.
            self.context.logger.warning(
                "Settled mech-request count unknown this round; "
                "skipping ROI computation to preserve the previously-"
                "persisted Total ROI."
            )
            return None, None

        # Use appropriate divisor based on platform
        # For Polymarket: USDC has 6 decimals; For Gnosis: xDAI has 18 decimals
        token_divisor = (
            USDC_DECIMALS_DIVISOR
            if self.params.is_running_on_polymarket
            else WEI_IN_ETH
        )

        self.context.logger.info(
            f"[ROI Calculation] Platform: {'Polymarket' if self.params.is_running_on_polymarket else 'Gnosis'}, "
            f"token_divisor: {token_divisor}"
        )

        # Get raw values from subgraph (in smallest units)
        total_traded_settled_raw = int(trader_agent.get("totalTradedSettled", 0))
        total_fees_settled_raw = int(trader_agent.get("totalFeesSettled", 0))
        total_market_payout_raw = int(trader_agent.get("totalExpectedPayout", 0))

        self.context.logger.info(
            f"[ROI Calculation] Raw values from subgraph: "
            f"totalTradedSettled={total_traded_settled_raw}, "
            f"totalFeesSettled={total_fees_settled_raw}, "
            f"totalExpectedPayout={total_market_payout_raw}"
        )

        # Convert market values to USD
        total_traded_settled_usd = total_traded_settled_raw / token_divisor
        total_fees_settled_usd = total_fees_settled_raw / token_divisor
        total_market_payout_usd = total_market_payout_raw / token_divisor

        self.context.logger.info(
            f"[ROI Calculation] Converted to USD: "
            f"total_traded_settled_usd={total_traded_settled_usd:.6f}, "
            f"total_fees_settled_usd={total_fees_settled_usd:.6f}, "
            f"total_market_payout_usd={total_market_payout_usd:.6f}"
        )

        settled_mech_costs_usd = float(
            _cost_or_flat_fee(self._settled_mech_cost_usd, settled_mech_requests)
        )

        self.context.logger.info(
            f"[ROI Calculation] Mech costs: "
            f"settled_mech_requests={settled_mech_requests}, "
            f"settled_mech_costs_usd={settled_mech_costs_usd:.6f}"
        )

        # Calculate total costs in USD
        total_costs_usd = (
            total_traded_settled_usd + total_fees_settled_usd + settled_mech_costs_usd
        )

        self.context.logger.info(
            f"[ROI Calculation] Total costs USD: {total_costs_usd:.6f}"
        )

        if total_costs_usd == 0:
            self.context.logger.warning(
                "[ROI Calculation] Total costs is zero, returning None"
            )
            return None, None

        # Convert OLAS rewards to USD
        olas_rewards_earned_raw = int(staking_service.get("olasRewardsEarned", 0))
        self.context.logger.info(
            f"[ROI Calculation] OLAS rewards: "
            f"olasRewardsEarned (raw)={olas_rewards_earned_raw}, "
            f"olas_in_usd_price={olas_in_usd_price}"
        )

        # olas_in_usd_price is already scaled to 18 decimals (wei), so we need to divide by WEI_IN_ETH twice
        # once to convert olasRewardsEarned from wei to OLAS, and once to convert the price from wei to USD
        total_olas_rewards_payout_in_usd = (
            olas_rewards_earned_raw * olas_in_usd_price
        ) / (WEI_IN_ETH * WEI_IN_ETH)

        self.context.logger.info(
            f"[ROI Calculation] OLAS rewards in USD: {total_olas_rewards_payout_in_usd:.6f}"
        )

        # Calculate ROI percentages
        partial_roi = (
            (total_market_payout_usd - total_costs_usd) * PERCENTAGE_FACTOR
        ) / total_costs_usd
        final_roi = (
            (
                total_market_payout_usd
                + total_olas_rewards_payout_in_usd
                - total_costs_usd
            )
            * PERCENTAGE_FACTOR
        ) / total_costs_usd

        self.context.logger.info(
            f"[ROI Calculation] ROI results: "
            f"partial_roi={partial_roi:.2f}%, "
            f"final_roi={final_roi:.2f}%"
        )

        self._final_roi = final_roi
        self._partial_roi = partial_roi

        return final_roi, partial_roi

    def _get_prediction_accuracy(self) -> Generator[None, None, Optional[float]]:
        """Get the prediction accuracy."""
        agent_safe_address = self.synchronized_data.safe_contract_address

        agent_bets_data = yield from self._fetch_trader_agent_bets(
            agent_safe_address=agent_safe_address,
        )
        if agent_bets_data is None:
            addresses = (
                f"for {agent_safe_address} (queried as {agent_safe_address.lower()})."
            )
            if self._call_failed:
                self.context.logger.error(f"Bets subgraph unavailable {addresses}")
            else:
                self.context.logger.info(f"No bets returned {addresses}")
            return None

        if len(agent_bets_data.get("bets", [])) == 0:
            return None

        # Platform-specific accuracy calculation
        if self.params.is_running_on_polymarket:
            return self._calculate_polymarket_accuracy(agent_bets_data)

        # ZD#919: enrich Omen bets with Reality.eth finalization data from
        # omen_subgraph before computing accuracy. The olas_agents subgraph
        # does not expose answerFinalizedTimestamp; without enrichment
        # every bet would be filtered out as unfinalized and accuracy
        # would silently disappear from the UI.
        fetcher = PredictionsFetcher(self.context, self.context.logger)
        fetcher._enrich_bets_with_finalization(agent_bets_data["bets"])
        return self._calculate_omen_accuracy(agent_bets_data)

    def _now(self) -> int:
        """Return the current wall-clock time as a Unix timestamp.

        Thin delegator to :func:`predictions_helper.now_ts` so this
        class shares a single time source with ``PredictionsFetcher``
        and the two cannot drift (e.g. one switching to milliseconds
        while the other stays on seconds). Kept as an instance method
        so tests can still ``patch.object(self, "_now", ...)``.

        :return: current Unix timestamp in seconds.
        """
        return now_ts()

    def _calculate_omen_accuracy(self, agent_bets_data: dict) -> Optional[float]:
        """Calculate prediction accuracy for Omen markets."""
        bets = agent_bets_data.get("bets", [])
        now = self._now()

        # Bug A (ZD#919): only finalized markets contribute to accuracy.
        # Reality.eth answers can flip during the dispute window, so a bet
        # whose market has currentAnswer set but answerFinalizedTimestamp
        # in the future is still provisional and must be excluded.
        # parse_timestamp treats None / "0" / malformed as unfinalized.
        bets_on_finalized_markets = []
        bets_with_answer = 0
        for bet in bets:
            fpmm = bet.get("fixedProductMarketMaker", {})
            if fpmm.get("currentAnswer") is None:
                continue
            bets_with_answer += 1
            # ZD#919: Kleros arbitration suspends the 24h clock; the answer
            # is provisional regardless of currentAnswer / finalization
            # timestamp. Exclude from accuracy until arbitration resolves.
            if fpmm.get("isPendingArbitration"):
                continue
            finalized_ts = parse_timestamp(fpmm.get("answerFinalizedTimestamp"))
            if finalized_ts is None or finalized_ts > now:
                continue
            bets_on_finalized_markets.append(bet)

        if not bets_on_finalized_markets:
            # Signal subgraph regressions (indexer lag, schema drift) so
            # accuracy silently disappearing from the UI is diagnosable.
            # Only warn if markets *have* a resolved answer but none are
            # finalized — all-unresolved is the normal state pre-resolution.
            if bets_with_answer > 0:
                self.context.logger.warning(
                    "Omen accuracy unavailable: %d resolved bets have no "
                    "valid answerFinalizedTimestamp (subgraph regression?).",
                    bets_with_answer,
                )
            return None

        won_bets = 0
        total_bets = 0

        for bet in bets_on_finalized_markets:
            market_answer = bet["fixedProductMarketMaker"]["currentAnswer"]
            bet_answer = bet.get("outcomeIndex")
            if bet_answer is None:
                continue
            correct = parse_current_answer(market_answer)
            if correct is None:
                # parse_current_answer returns None for the INVALID_ANSWER_HEX
                # sentinel and for malformed hex. Both must be excluded from
                # accuracy — invalid markets have no correct outcome, and
                # malformed data would crash int(...) further down.
                continue
            total_bets += 1
            if correct == int(bet_answer):
                won_bets += 1

        if total_bets == 0:
            return None

        win_rate = (won_bets / total_bets) * PERCENTAGE_FACTOR
        return win_rate

    def _calculate_polymarket_accuracy(self, agent_bets_data: dict) -> Optional[float]:
        """Calculate prediction accuracy for Polymarket markets."""
        bets = agent_bets_data.get("bets", [])
        # Filter for resolved markets only
        bets_on_resolved_markets = [
            bet
            for bet in bets
            if (bet.get("question") or {}).get("resolution") is not None
        ]

        if len(bets_on_resolved_markets) == 0:
            return None

        won_bets = 0
        total_bets = 0

        for bet in bets_on_resolved_markets:
            resolution = (bet.get("question") or {}).get("resolution", {})
            winning_index = resolution.get("winningIndex")
            outcome_index = bet.get("outcomeIndex")

            # Skip if either index is None
            if winning_index is None or outcome_index is None:
                continue
            # Skip invalid markets (winningIndex < 0)
            if int(winning_index) < 0:
                continue

            total_bets += 1

            # Compare outcomeIndex with winningIndex
            if int(outcome_index) == int(winning_index):
                won_bets += 1

        if total_bets == 0:
            return None

        win_rate = (won_bets / total_bets) * PERCENTAGE_FACTOR
        return win_rate

    def _format_timestamp(self, timestamp: Optional[str]) -> Optional[str]:
        """Format Unix timestamp to ISO 8601."""
        if not timestamp:
            return None
        try:
            unix_timestamp = int(timestamp)
            dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            self.context.logger.error(f"Error formatting timestamp {timestamp}: {e}")
            return None

    def _fetch_agent_details_data(
        self,
    ) -> Generator[None, None, Optional[AgentDetails]]:
        """Fetch agent details"""

        safe_address = self.synchronized_data.safe_contract_address.lower()

        agent_details_raw = yield from self._fetch_agent_details(safe_address)

        if not agent_details_raw:
            self.context.logger.warning(
                f"Could not fetch agent details for {safe_address}"
            )
            # Return empty structure instead of None
            return AgentDetails(
                id=None,
                created_at=None,
                last_active_at=None,
            )

        return AgentDetails(
            id=agent_details_raw.get("id", safe_address),
            created_at=self._format_timestamp(agent_details_raw.get("blockTimestamp")),
            last_active_at=self._format_timestamp(agent_details_raw.get("lastActive")),
        )

    def _fetch_agent_performance_data(
        self,
    ) -> Generator[None, None, Optional[AgentPerformanceData]]:
        """Fetch agent performance data"""

        safe_address = self.synchronized_data.safe_contract_address.lower()
        trader_agent = yield from self._fetch_trader_agent_performance(
            safe_address, first=200, skip=0
        )

        if not trader_agent:
            self.context.logger.warning(
                "Could not fetch trader agent for performance data"
            )
            # Return empty structure instead of None
            return AgentPerformanceData(
                metrics=PerformanceMetricsData(),
                stats=PerformanceStatsData(),
            )

        # Calculate metrics — returns None when mech-analytics fetch
        # fails and no cached total is available. In that case we render
        # an empty structure (same as trader_agent-fetch failure above)
        # rather than a partially-computed one that would misreport ROI.
        metrics = yield from self._calculate_performance_metrics(trader_agent)
        if metrics is None:
            return AgentPerformanceData(
                metrics=PerformanceMetricsData(),
                stats=PerformanceStatsData(),
            )
        stats = yield from self._calculate_performance_stats(trader_agent)

        return AgentPerformanceData(
            window="lifetime",
            currency="USD",
            metrics=metrics,
            stats=stats,
        )

    def _calculate_performance_metrics(
        self, trader_agent: dict
    ) -> Generator[None, None, Optional[PerformanceMetricsData]]:
        """Calculate performance metrics from trader agent data.

        Returns ``None`` when ``total_mech_requests`` could not be
        fetched (mech-analytics transport / schema failure). The caller
        renders an empty structure in that case rather than a
        partially-computed one that would misreport ROI.

        :param trader_agent: the raw trader-agent dict as returned by
            ``_fetch_trader_agent_performance``.
        :return: a populated ``PerformanceMetricsData`` on success, or
            ``None`` when the cost-affecting total-count fetch failed.
        :yield: framework yields for the mech-request-count fetches
            and (Omen only) the CT-balance lookup.
        """
        safe_address = self.synchronized_data.safe_contract_address.lower()

        total_traded = int(trader_agent.get("totalTraded", 0))
        total_fees = int(trader_agent.get("totalFees", 0))
        total_traded_settled = int(trader_agent.get("totalTradedSettled", 0))
        total_fees_settled = int(trader_agent.get("totalFeesSettled", 0))
        total_payout = int(trader_agent.get("totalExpectedPayout", 0))

        settled_mech_requests = self._settled_mech_requests_count
        # ``None`` = ``_calculate_settled_mech_requests`` fetch failed
        # this round; short-circuit rather than treat as 0 (which would
        # zero ``settled_mech_costs`` and inflate ``all_time_profit``).
        if settled_mech_requests is None:
            return None

        # Get mech request counts (uses caches populated earlier)
        total_mech_requests = yield from self._get_total_mech_requests(safe_address)
        # ``None`` = fetch failure — short-circuit ROI computation for
        # this round rather than treating it as 0 and inflating ROI.
        if total_mech_requests is None:
            return None
        open_mech_requests = self._open_market_requests or 0
        placed_mech_requests = self._placed_mech_requests_count
        # Without a placed count, every settled request would read as unplaced.
        unplaced_mech_requests = (
            None
            if placed_mech_requests is None
            else max(total_mech_requests - open_mech_requests - placed_mech_requests, 0)
        )

        all_mech_costs_usd = float(
            _cost_or_flat_fee(self._total_mech_cost_usd, total_mech_requests)
        )

        # Use appropriate divisor based on platform
        # For Polymarket: USDC has 6 decimals; For Gnosis: xDAI has 18 decimals
        token_divisor = (
            USDC_DECIMALS_DIVISOR
            if self.params.is_running_on_polymarket
            else WEI_IN_ETH
        )

        # All-time funds used: traded + fees + ALL mech costs
        all_time_funds_used = (
            total_traded + total_fees
        ) / token_divisor + all_mech_costs_usd

        # All-time profit: uses settled traded/fees and settled mech costs
        # Settled mech requests include both placed and unplaced mech calls (excluding open markets).
        settled_mech_costs_usd = float(
            _cost_or_flat_fee(self._settled_mech_cost_usd, settled_mech_requests)
        )
        all_time_profit = (
            total_payout - total_traded_settled - total_fees_settled
        ) / token_divisor - settled_mech_costs_usd

        # Calculate locked funds. Polymarket keeps its pre-existing
        # cash-flow-net formula (set up by #943). Omenstrat now uses a
        # per-position formula that survives sell-at-loss: sum the
        # FIFO-aware ``remaining_cost`` of every non-resolved-losing buy
        # in the agent's history. Spec §7.2 / §10.13.1 — fixes the
        # phantom-locked-funds bug where a sell-at-loss leaves cost
        # basis on the balance sheet until Realitio finalisation.
        if self.params.is_running_on_polymarket:
            funds_locked_in_markets = (
                total_traded - total_traded_settled
            ) / token_divisor
        else:
            funds_locked_in_markets = yield from self._compute_omen_funds_locked(
                trader_agent, safe_address
            )

        # Get available funds
        available_funds = yield from self._fetch_available_funds()

        # Convert from percentage (e.g., -56) to decimal (e.g., -0.56)
        roi_decimal = (
            round(self._partial_roi / 100, 2) if self._partial_roi is not None else None
        )

        return PerformanceMetricsData(
            all_time_funds_used=(
                round(all_time_funds_used, 2)
                if all_time_funds_used is not None
                else None
            ),
            all_time_profit=(
                round(all_time_profit, 2) if all_time_profit is not None else None
            ),
            funds_locked_in_markets=(
                round(funds_locked_in_markets, 2)
                if funds_locked_in_markets is not None
                else None
            ),
            available_funds=(
                round(available_funds, 2) if available_funds is not None else None
            ),
            roi=roi_decimal,
            # Settled mech requests cover placed + unplaced, excluding open markets.
            # Reads the narrowed local (int) rather than the instance
            # attribute (Optional[int]) so mypy sees the None-guard above.
            settled_mech_request_count=settled_mech_requests,
            total_mech_request_count=total_mech_requests,
            open_mech_request_count=open_mech_requests,
            placed_mech_request_count=placed_mech_requests,
            unplaced_mech_request_count=unplaced_mech_requests,
        )

    def _compute_omen_funds_locked(
        self, trader_agent: dict, safe_address: str
    ) -> Generator[None, None, float]:
        """Per-position funds-locked-in-markets for Omenstrat.

        Fetches the CT-balance "held" set first so already-redeemed
        positions drop out of the trade-history-FIFO sum. Shared with
        the post-withdrawal snapshot hook in
        ``decision_maker_abci.PostOmenWithdrawBehaviour`` so both
        writers produce the same scalar.

        :param trader_agent: the dict returned by
            ``_fetch_trader_agent_performance`` for Omenstrat.
        :param safe_address: the agent's safe address (used as the CT
            subgraph ``userPositions`` key).
        :yield: framework yields for the CT subgraph fetch.
        :return: wxDAI total of remaining cost on currently-held,
            non-LOSING positions.
        """
        bets = trader_agent.get("bets") or []
        held_keys = yield from self._fetch_ct_held_position_keys(safe_address)
        return compute_funds_locked_from_bets(
            bets,
            self.context,
            self.context.logger,
            held_keys=held_keys,
        )

    def _get_pol_to_usdc_rate(
        self,
    ) -> Generator[None, None, Optional[float]]:
        """
        Get the POL to USDC conversion rate (1 POL = X USDC), with caching.

        Only fetches from LiFi API if cache is stale (older than 2 hours).

        :return: Conversion rate (1 POL = X USDC), or None if failed
        :yield: None
        """

        current_time = self.shared_state.synced_timestamp

        # Check if cached rate is still valid
        if (
            self._pol_usdc_rate is not None
            and (current_time - self._pol_usdc_rate_timestamp) < LIFI_RATE_LIMIT_SECONDS
        ):
            self.context.logger.info(
                f"Using cached POL→USDC rate: 1 POL = {self._pol_usdc_rate} USDC "
                f"(cached {int(current_time - self._pol_usdc_rate_timestamp)}s ago)"
            )
            return self._pol_usdc_rate

        # Cache is stale or doesn't exist, fetch new rate
        try:
            safe_address = self.synchronized_data.safe_contract_address

            # Get quote for 1 POL to USDC to determine the rate
            self.context.logger.info(
                "Fetching fresh POL→USDC rate from LiFi API (cache expired or missing)"
            )

            # Build LiFi quote request URL for 1 POL
            params = {
                "fromChain": str(POLYGON_CHAIN_ID),
                "toChain": str(POLYGON_CHAIN_ID),
                "fromToken": POLYGON_NATIVE_TOKEN_ADDRESS,
                "toToken": PUSD_ADDRESS,
                "fromAmount": str(RATE_CALC_BASE_AMOUNT),  # 1 POL in wei
                "fromAddress": safe_address,
                "toAddress": safe_address,
            }

            # Construct URL with query parameters
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            url = f"{LIFI_QUOTE_URL}?{query_string}"

            # Make HTTP request to LiFi API
            response = yield from self.get_http_response(
                method="GET",
                url=url,
            )

            if response.status_code != 200:
                self.context.logger.warning(
                    f"LiFi API returned status {response.status_code}, using stale cache if available"
                )
                return self._pol_usdc_rate  # Return stale cache if available

            # Parse response
            response_data = json.loads(response.body.decode())

            # Extract USDC amount for 1 POL
            to_amount_wei = response_data.get("estimate", {}).get("toAmount")

            if not to_amount_wei:
                self.context.logger.error("No toAmount in LiFi quote response")
                return self._pol_usdc_rate  # Return stale cache if available

            # Calculate rate: 1 POL = X USDC
            # USDC has 6 decimals, POL has 18 decimals
            usdc_amount = int(to_amount_wei) / USDC_DECIMALS_DIVISOR
            rate = usdc_amount  # This is the USDC amount for 1 POL

            # Update cache
            self._pol_usdc_rate = rate
            self._pol_usdc_rate_timestamp = current_time

            self.context.logger.info(
                f"Updated POL→USDC rate cache: 1 POL = {rate} USDC"
            )

            return rate

        except Exception as e:
            self.context.logger.error(f"Error fetching POL→USDC rate: {str(e)}")
            return self._pol_usdc_rate  # Return stale cache if available

    def _get_usdc_equivalent_for_pol(
        self, pol_balance_wei: int
    ) -> Generator[None, None, Optional[float]]:
        """Convert POL balance to USDC equivalent using cached rate."""
        try:
            # Get the conversion rate (1 POL = X USDC)
            rate = yield from self._get_pol_to_usdc_rate()

            if rate is None or rate == 0:
                self.context.logger.error(
                    "No valid POL→USDC rate available, cannot calculate equivalent"
                )
                return None

            # Convert POL from wei to standard units
            pol_amount = pol_balance_wei / WEI_IN_ETH

            # Calculate USDC equivalent: USDC = POL * rate
            usdc_amount = pol_amount * rate

            self.context.logger.info(
                f"POL→USDC conversion: {pol_amount:.4f} POL ≈ {usdc_amount:.2f} USDC "
                f"(rate: 1 POL = {rate} USDC)"
            )

            return usdc_amount

        except Exception as e:
            self.context.logger.error(
                f"Error getting USDC equivalent for POL: {str(e)}"
            )
            return None

    def _fetch_available_funds(self) -> Generator[None, None, Optional[float]]:
        """Fetch available funds (token + native balance) - platform-aware."""
        safe_contract_address = self.synchronized_data.safe_contract_address

        # Use appropriate token address based on platform
        token_address = (
            PUSD_ADDRESS if self.params.is_running_on_polymarket else WXDAI_ADDRESS
        )

        self.context.logger.info(
            f"Fetching available funds: is_polymarket={self.params.is_running_on_polymarket}, "
            f"token_address={token_address}, chain_id={self.params.mech_chain_id}"
        )

        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=token_address,
            contract_id=str(ERC20.contract_id),
            contract_callable="check_balance",
            account=safe_contract_address,
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not calculate the balance of the safe: {response_msg}"
            )
            return None

        token = response_msg.raw_transaction.body.get("token", None)
        wallet = response_msg.raw_transaction.body.get("wallet", None)

        if token is None or wallet is None:
            self.context.logger.error(
                "Invalid balance response: token or wallet is None"
            )
            return None

        # Use appropriate divisor based on platform
        token_divisor = (
            USDC_DECIMALS_DIVISOR
            if self.params.is_running_on_polymarket
            else WEI_IN_ETH
        )
        token_balance = token / token_divisor

        # For Polymarket, convert POL to USDC equivalent; for Gnosis, xDAI is already ~$1
        if self.params.is_running_on_polymarket:
            # Convert POL (native token) to USDC equivalent
            pol_in_usdc = yield from self._get_usdc_equivalent_for_pol(wallet)
            if pol_in_usdc is None:
                self.context.logger.warning(
                    "Failed to convert POL to USDC. Using only USDC.e balance."
                )
                pol_in_usdc = 0.0
            available_funds = token_balance + pol_in_usdc
        else:
            # For Gnosis: both wxDAI and xDAI are ~$1, can add directly
            wallet_balance = wallet / WEI_IN_ETH
            available_funds = token_balance + wallet_balance

        self.context.logger.info(
            f"Calculated balances: token_balance={token_balance}, "
            f"native_balance_converted={pol_in_usdc if self.params.is_running_on_polymarket else wallet / WEI_IN_ETH}, "
            f"available_funds={available_funds}"
        )

        return available_funds

    def _calculate_performance_stats(
        self, trader_agent: dict
    ) -> Generator[None, None, PerformanceStatsData]:
        """Calculate performance statistics."""
        total_bets = int(trader_agent.get("totalBets", 0))
        accuracy = yield from self._get_prediction_accuracy()

        return PerformanceStatsData(
            predictions_made=total_bets,
            prediction_accuracy=(
                round(accuracy / 100, 2) if accuracy is not None else None
            ),
        )

    def _fetch_prediction_history(self) -> PredictionHistory:
        """Fetch latest 200 predictions."""
        safe_address = self.synchronized_data.safe_contract_address.lower()

        try:
            # Use platform-specific fetcher
            fetcher: BasePredictionsFetcher
            if self.params.is_running_on_polymarket:
                fetcher = PolymarketPredictionsFetcher(
                    self.context, self.context.logger
                )
            else:
                fetcher = PredictionsFetcher(self.context, self.context.logger)

            result = fetcher.fetch_predictions(
                safe_address=safe_address, first=200, skip=0, status_filter=None
            )

            return PredictionHistory(
                total_predictions=result["total_predictions"],
                stored_count=len(result["items"]),
                last_updated=self.shared_state.synced_timestamp,
                items=result["items"],
            )
        except Exception as e:
            self.context.logger.error(f"Error fetching prediction history: {e}")
            return PredictionHistory(
                total_predictions=0,
                stored_count=0,
                last_updated=self.shared_state.synced_timestamp,
                items=[],
            )

    @staticmethod
    def _extract_omen_question_title(question: str) -> str:
        """Extract the question title from an Omen question string (split by separator)."""
        return question.split(QUESTION_DATA_SEPARATOR)[0] if question else ""

    def _extract_title(self, participant: dict) -> str:
        """Extract question title from a profit participant, platform-aware.

        :param participant: A profit participant dict from daily stats
        :return: The extracted title string
        """
        if self.params.is_running_on_polymarket:
            metadata = participant.get("metadata", {})
            return metadata.get("title", "") if metadata else ""
        question = participant.get("question", "")
        return self._extract_omen_question_title(question)

    def _match_mech_requests_to_days(
        self,
        daily_stats: list,
        mech_request_lookup: Dict[str, List[int]],
        request_costs: MechRequestCosts,
    ) -> Tuple[Dict[int, int], int, int, Dict[int, Decimal]]:
        """Match mech requests to bet days using timestamps (last-before-bet via bisect).

        For each bet, consumes the last mech request with timestamp <= bet timestamp.
        When bet-level timestamps are available (via profitParticipants[].bets[]),
        matching is precise.  Falls back to day_ts when bets field is absent.
        Remaining unconsumed requests are unplaced and assigned to their own
        mech-request day.

        :param daily_stats: List of daily profit statistics
        :param mech_request_lookup: Dictionary mapping question titles to sorted timestamp lists
        :param request_costs: each request's cost by ``(title, timestamp)``;
            a request without one costs the flat fee
        :return: Tuple of (requests per day, placed_count, unplaced_count,
            USD cost per day)
        """
        # Deep-copy timestamps so we can pop without mutating the original lookup
        remaining: Dict[str, List[int]] = {
            title: list(timestamps) for title, timestamps in mech_request_lookup.items()
        }
        costs: MechRequestCosts = {
            key: list(values) for key, values in request_costs.items()
        }

        fees_by_day: Dict[int, int] = {}
        costs_by_day: Dict[int, Decimal] = {}
        placed_count = 0

        # Build (title, bet_ts, day_ts) triples from bet-level data when available
        bet_pairs: List[Tuple[str, int, int]] = []
        for stat in daily_stats:
            date_value = stat.get("date")
            if date_value is None:
                continue
            day_ts = int(date_value)
            for participant in stat.get("profitParticipants") or []:
                title = self._extract_title(participant)
                if not title:
                    continue
                bets = participant.get("bets") or []
                if bets:
                    for bet in bets:
                        bet_ts = int(
                            bet.get("timestamp") or bet.get("blockTimestamp") or 0
                        )
                        if bet_ts:
                            bet_pairs.append((title, bet_ts, day_ts))
                else:
                    # Fallback: no bet-level data, use day_ts as approximate
                    bet_pairs.append((title, day_ts, day_ts))

        bet_pairs.sort(key=lambda x: x[1])

        # Last-before-bet match via bisect
        for title, bet_ts, day_ts in bet_pairs:
            ts_list = remaining.get(title)
            if ts_list:
                idx = bisect.bisect_right(ts_list, bet_ts) - 1
                if idx >= 0:
                    mech_ts = ts_list.pop(idx)
                    fees_by_day[day_ts] = fees_by_day.get(day_ts, 0) + 1
                    costs_by_day[day_ts] = costs_by_day.get(
                        day_ts, Decimal(0)
                    ) + _take_cost(costs, (title, mech_ts))
                    placed_count += 1

        # Remaining unconsumed requests are unplaced — assign to mech request's own day
        unplaced_count = 0
        for title, ts_list in remaining.items():
            for mech_ts in ts_list:
                mech_day = (mech_ts // SECONDS_PER_DAY) * SECONDS_PER_DAY
                fees_by_day[mech_day] = fees_by_day.get(mech_day, 0) + 1
                costs_by_day[mech_day] = costs_by_day.get(
                    mech_day, Decimal(0)
                ) + _take_cost(costs, (title, mech_ts))
                unplaced_count += 1

        return fees_by_day, placed_count, unplaced_count, costs_by_day

    @staticmethod
    def _mech_request_key(request: dict) -> Tuple[str, int]:
        """Return a mech request's ``(question title, block timestamp)``.

        :param request: a subgraph-shaped mech request
        :return: the title (``""`` when the request has none) and timestamp
        """
        title = (request.get("parsedRequest") or {}).get("questionTitle") or ""
        return title, int(request.get("blockTimestamp") or 0)

    def _hold_back_open_requests(
        self, candidates: List[Tuple[str, int]]
    ) -> Tuple[Dict[str, List[int]], List[Tuple[str, int]]]:
        """Split uncharged requests into those to charge and those the KPI counts as open.

        Matching is by count, so duplicate ``(title, timestamp)`` pairs are
        each held back only as often as the KPI counted them.

        :param candidates: ``(title, timestamp)`` of every uncharged request
        :return: tuple of (title -> sorted timestamps to charge, held-back requests)
        """
        open_left = Counter(self._open_market_request_keys or [])
        chargeable: Dict[str, List[int]] = {}
        held_back: List[Tuple[str, int]] = []
        for key in candidates:
            if open_left[key] > 0:
                open_left[key] -= 1
                held_back.append(key)
            else:
                chargeable.setdefault(key[0], []).append(key[1])
        for timestamps in chargeable.values():
            timestamps.sort()
        return chargeable, held_back

    @staticmethod
    def _as_pending_mech_requests(
        held_back: List[Tuple[str, int]],
        request_costs: MechRequestCosts,
    ) -> List[Dict[str, Any]]:
        """Serialise held-back requests for ``ProfitOverTimeData.pending_mech_requests``.

        :param held_back: ``(title, timestamp)`` of each held-back request
        :param request_costs: each request's cost by ``(title, timestamp)``;
            the held-back requests' costs are removed from it
        :return: the persisted ``{"title", "timestamp", "cost_usd"}`` entries
        """
        return [
            {
                "title": title,
                "timestamp": ts,
                "cost_usd": str(_take_cost(request_costs, (title, ts))),
            }
            for title, ts in held_back
        ]

    def _costs_by_key(
        self,
        mech_requests: List[dict],
        pending: Optional[List[Dict[str, Any]]] = None,
    ) -> MechRequestCosts:
        """Return each request's cost keyed by ``(title, timestamp)``.

        :param mech_requests: subgraph-shaped mech requests
        :param pending: persisted held-back entries, charged at their stored
            ``cost_usd`` (the flat fee for entries stored without one)
        :return: costs in request order per key
        """
        costs: MechRequestCosts = {}
        for entry in pending or []:
            cost = _usd_amount(entry.get("cost_usd"))
            key = (entry["title"], int(entry["timestamp"]))
            costs.setdefault(key, []).append(_cost_or_flat_fee(cost, 1))
        for request in mech_requests:
            key = self._mech_request_key(request)
            if key[1]:
                costs.setdefault(key, []).append(self._mech_request_cost_usd(request))
        return costs

    def _mech_request_cost_usd(self, request: dict) -> Decimal:
        """Return what a subgraph-shaped mech request cost, in USD.

        :param request: a mech request; ``chargeUsd`` is the charge the mech
            reported, absent for on-chain and subgraph-sourced requests
        :return: the reported charge, or the flat fee without a usable one
        """
        raw_charge = request.get("chargeUsd")
        charge = _usd_amount(raw_charge)
        if charge is None and raw_charge is not None:
            self.context.logger.warning(
                f"Mech request {request.get('requestId')!r} has an unusable "
                f"chargeUsd={raw_charge!r}; charging the flat fee"
            )
        return _cost_or_flat_fee(charge, 1)

    def _recent_request_ids(
        self, requests: List[dict], watermark: int
    ) -> Optional[List[str]]:
        """Return the ids the next lookback fetch serves again, ``None`` off mech-analytics.

        :param requests: every request the lookback window returned
        :param watermark: the watermark after this round
        :return: sorted request ids inside the next window, or ``None``
        """
        if not uses_mech_analytics(self.params):
            return None
        cutoff = watermark - MECH_ANALYTICS_LOOKBACK_SECONDS
        return sorted(
            {
                request["requestId"]
                for request in requests
                if self._mech_request_key(request)[1] > cutoff
            }
        )

    def _apply_mech_fees(
        self,
        fees_by_day: Dict[int, int],
        date_timestamp: int,
        costs_by_day: Dict[int, Decimal],
    ) -> Tuple[float, int]:
        """Look up a day's pre-computed mech requests and their cost.

        :param fees_by_day: Pre-computed mapping of day timestamp to mech request count
        :param date_timestamp: The day timestamp to look up
        :param costs_by_day: Pre-computed USD cost per day
        :return: Tuple of (mech fees in USD, mech_request_count)
        """
        count = fees_by_day.get(date_timestamp, 0)
        return float(costs_by_day.get(date_timestamp, Decimal(0))), count

    def _build_mech_request_lookup(
        self, agent_safe_address: str
    ) -> Generator[None, None, Dict[str, List[int]]]:
        """Build a lookup map of question titles to sorted mech request timestamps.

        :param agent_safe_address: The agent's safe address
        :return: Dictionary mapping question titles to sorted timestamp lists
        :yield: None
        """
        # Fetch all mech requests for this agent
        if self._mech_request_lookup is not None:
            self.context.logger.info(
                f"Using cached mech request lookup with {len(self._mech_request_lookup)} unique questions"
            )
            return self._mech_request_lookup

        all_mech_requests = yield from self._fetch_all_mech_requests(agent_safe_address)

        # Distinguish fetch failure (``None``) from genuinely empty
        # (``[]``): the caller currently would treat both as an empty
        # lookup and blame the missing fee attribution on "no requests"
        # rather than surfacing that the request-list fetch dropped.
        if all_mech_requests is None:
            self.context.logger.warning(
                "mech request fetch failed; skipping lookup this round"
            )
            return {}
        if not all_mech_requests:
            self.context.logger.info("No mech requests found for agent")
            return {}

        # Build lookup map: question_title -> sorted timestamps. Untitled
        # requests key under ``""``, which no bet matches, so they are
        # charged as unplaced: the KPI's ``total`` counts them too.
        lookup: Dict[str, List[int]] = {}
        for request in all_mech_requests:
            title, ts = self._mech_request_key(request)
            if ts:
                lookup.setdefault(title, []).append(ts)

        for title in lookup:
            lookup[title].sort()

        total_requests = sum(len(v) for v in lookup.values())
        self.context.logger.info(
            f"Built mech request lookup with {len(lookup)} unique questions, {total_requests} total requests"
        )
        self._mech_request_lookup = lookup
        self._fetched_mech_requests = all_mech_requests
        self._request_costs = self._costs_by_key(all_mech_requests)
        return lookup

    def _build_profit_over_time_data(
        self,
    ) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """Build profit over time data with efficient backfill and incremental update strategy.

        :return: ProfitOverTimeData or None
        :yield: None
        """
        # Without this round's open set the series cannot hold back what
        # the KPI excludes, so keep the stored series rather than diverge.
        settled_reference = self._settled_mech_requests_count
        if settled_reference is None:
            self.context.logger.warning(
                "Settled mech request count unknown this round; "
                "keeping the stored profit over time data"
            )
            return None

        agent_safe_address = self.synchronized_data.safe_contract_address.lower()
        current_timestamp = self.shared_state.synced_timestamp

        # Check if we have existing profit data
        existing_summary = self.shared_state.read_existing_performance_summary()
        existing_profit_data = existing_summary.profit_over_time
        last_residual_rebuild_ts = (
            existing_profit_data.last_residual_rebuild_ts if existing_profit_data else 0
        )

        # Determine if this is initial backfill or incremental update
        # Rebuild if missing data, or when new fields (settled mech count / unplaced mech fees) are absent
        if not existing_profit_data or not existing_profit_data.data_points:
            # INITIAL BACKFILL - First time or no existing data
            self.context.logger.info("Performing initial profit over time backfill...")
            return (
                yield from self._perform_initial_backfill(
                    agent_safe_address, current_timestamp, last_residual_rebuild_ts
                )
            )
        elif (
            existing_summary.agent_performance
            and existing_summary.agent_performance.metrics
            and not getattr(
                existing_summary.agent_performance.metrics,
                "settled_mech_request_count",
                None,
            )
        ):
            # INITIAL BACKFILL - Missing settled_mech_request_count field (hotfix)
            self.context.logger.info(
                "Performing initial profit over time backfill due to missing settled_mech_request_count..."
            )
            return (
                yield from self._perform_initial_backfill(
                    agent_safe_address, current_timestamp, last_residual_rebuild_ts
                )
            )
        elif not getattr(existing_profit_data, "includes_unplaced_mech_fees", False):
            # INITIAL BACKFILL - Apply new non-placed mech fees logic and track counts
            self.context.logger.info(
                "Performing initial profit over time backfill to include unplaced mech fees and counts..."
            )
            return (
                yield from self._perform_initial_backfill(
                    agent_safe_address, current_timestamp, last_residual_rebuild_ts
                )
            )
        elif (
            getattr(existing_profit_data, "schema_version", 0)
            < PROFIT_OVER_TIME_SCHEMA_VERSION
        ):
            # INITIAL BACKFILL - Schema cutover (e.g. subgraph endpoint change).
            # Pre-cutover days were attributed under prior endpoint semantics and
            # don't reconcile with new days; full rebuild restores consistency.
            self.context.logger.info(
                "Performing initial profit over time backfill due to schema version "
                f"upgrade ({getattr(existing_profit_data, 'schema_version', 0)} -> "
                f"{PROFIT_OVER_TIME_SCHEMA_VERSION})..."
            )
            return (
                yield from self._perform_initial_backfill(
                    agent_safe_address, current_timestamp, last_residual_rebuild_ts
                )
            )
        else:
            # INCREMENTAL UPDATE - Check if we need to add new days
            self.context.logger.info(
                "Checking for incremental profit over time updates..."
            )
            updated = yield from self._perform_incremental_update(
                agent_safe_address, current_timestamp, existing_profit_data
            )
            if updated is None:
                return None
            return (
                yield from self._rebuild_on_residual(
                    updated, settled_reference, agent_safe_address, current_timestamp
                )
            )

    def _rebuild_on_residual(
        self,
        updated: ProfitOverTimeData,
        settled_reference: int,
        agent_safe_address: str,
        current_timestamp: int,
    ) -> Generator[None, None, ProfitOverTimeData]:
        """Rebuild the series when its settled count drifts from the KPI's.

        :param updated: the series after this round's incremental update
        :param settled_reference: the KPI's settled count this round
        :param agent_safe_address: the agent's safe address
        :param current_timestamp: the current timestamp
        :return: the rebuilt series, or ``updated`` when the rebuild was skipped
            or failed
        :yield: None
        """
        # Drift beyond tolerance means requests the watermark skipped; rebuild.
        residual = updated.settled_mech_requests_count - settled_reference
        if abs(residual) <= _RESIDUAL_TOLERANCE:
            return updated

        residual_log = (
            f"Settled mech count residual (series={updated.settled_mech_requests_count}, "
            f"snapshot={settled_reference}, residual={residual})"
        )
        backoff_days = updated.residual_rebuild_backoff_days
        if (
            current_timestamp - updated.last_residual_rebuild_ts
            < backoff_days * SECONDS_PER_DAY
        ):
            self.context.logger.warning(
                f"{residual_log}; already rebuilt within the last {backoff_days} "
                "day(s), keeping the incremental update."
            )
            return updated

        self.context.logger.warning(
            f"{residual_log}; rebuilding profit over time data."
        )
        rebuilt = yield from self._perform_initial_backfill(
            agent_safe_address,
            current_timestamp,
            last_residual_rebuild_ts=current_timestamp,
        )
        if rebuilt is None:
            self.context.logger.error(
                "Residual-triggered profit over time rebuild failed; keeping the "
                f"incremental update and retrying in {backoff_days} day(s)."
            )
            updated.last_residual_rebuild_ts = current_timestamp
            return updated

        rebuilt_residual = rebuilt.settled_mech_requests_count - settled_reference
        if abs(rebuilt_residual) > _RESIDUAL_TOLERANCE:
            # A fresh rebuild cannot close the gap: the request list and the
            # KPI's ``total`` disagree at the source, so retrying soon is waste.
            rebuilt.residual_rebuild_backoff_days = next(
                (
                    days
                    for days in _RESIDUAL_REBUILD_BACKOFF_DAYS
                    if days > backoff_days
                ),
                _RESIDUAL_REBUILD_BACKOFF_DAYS[-1],
            )
            self.context.logger.error(
                "Residual persists after a full rebuild (series="
                f"{rebuilt.settled_mech_requests_count}, snapshot={settled_reference}, "
                f"residual={rebuilt_residual}): the fetched mech requests and the "
                "KPI's total disagree at the source. Next rebuild in "
                f"{rebuilt.residual_rebuild_backoff_days} day(s)."
            )
        return rebuilt

    def _perform_initial_backfill(
        self,
        agent_safe_address: str,
        current_timestamp: int,
        last_residual_rebuild_ts: int = 0,
    ) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """Perform initial backfill of all profit data."""
        # Fetch ALL daily profit statistics from creation to now
        daily_stats = yield from self._fetch_daily_profit_statistics(
            agent_safe_address, 0
        )

        if daily_stats is None:
            self.context.logger.error("Failed to fetch daily profit statistics")
            return None

        if not daily_stats:
            self.context.logger.info(
                "No daily profit statistics found - agent may not have any trading activity yet"
            )
            return ProfitOverTimeData(
                last_updated=current_timestamp,
                total_days=0,
                data_points=[],
                settled_mech_requests_count=0,
                includes_unplaced_mech_fees=True,
                schema_version=PROFIT_OVER_TIME_SCHEMA_VERSION,
                last_residual_rebuild_ts=last_residual_rebuild_ts,
            )

        self.context.logger.info(
            f"Initial backfill: Found {len(daily_stats)} daily profit statistics"
        )

        # Build mech request lookup ONCE for all historical data.
        # Fail-closed (H6): every bet must have a mech request. Non-empty trading
        # stats with an empty mech lookup = unavailable subgraph data — suppress the
        # series (return None preserves stored data) rather than emit zero mech fees.
        all_mech_request_lookup = yield from self._build_mech_request_lookup(
            agent_safe_address
        )
        if not all_mech_request_lookup:
            self.context.logger.warning(
                "No mech requests found — preserving existing profit data"
            )
            return None
        mech_request_lookup, held_back = self._hold_back_open_requests(
            [
                (title, ts)
                for title, timestamps in all_mech_request_lookup.items()
                for ts in timestamps
            ]
        )

        request_costs: MechRequestCosts = {
            key: list(values) for key, values in self._request_costs.items()
        }
        pending_mech_requests = self._as_pending_mech_requests(held_back, request_costs)

        # Timestamp-based mech-to-bet attribution
        (
            fees_by_day,
            placed_count,
            unplaced_count,
            costs_by_day,
        ) = self._match_mech_requests_to_days(
            daily_stats, mech_request_lookup, request_costs
        )
        self._placed_mech_requests_count = placed_count

        # Process all daily statistics
        data_points = []
        cumulative_profit = 0.0

        # Determine divisor based on platform
        profit_divisor = (
            USDC_DECIMALS_DIVISOR
            if self.params.is_running_on_polymarket
            else WEI_IN_ETH
        )

        for stat in daily_stats:
            date_value = stat.get("date")
            if date_value is None:
                self.context.logger.warning(
                    "Skipping daily stat with missing 'date' key"
                )
                continue
            date_timestamp = int(date_value)
            date_str = datetime.fromtimestamp(date_timestamp, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            daily_profit_raw = float(stat.get("dailyProfit", 0)) / profit_divisor

            # Look up pre-computed mech fees for this day
            mech_fees, daily_mech_count = self._apply_mech_fees(
                fees_by_day, date_timestamp, costs_by_day
            )

            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net

            data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=date_timestamp,
                    daily_profit_raw=daily_profit_raw,
                    daily_profit=daily_profit_net,
                    cumulative_profit=round(cumulative_profit, 3),
                    daily_mech_requests=daily_mech_count,
                    daily_mech_cost=mech_fees,
                )
            )

        # R2: Emit data points for mech-only days (unplaced requests on days
        # with no bets).  These costs would otherwise be silently lost.
        visited_days = {int(stat["date"]) for stat in daily_stats if "date" in stat}
        for mech_day_ts in sorted(fees_by_day.keys() - visited_days):
            count = fees_by_day[mech_day_ts]
            date_str = datetime.fromtimestamp(mech_day_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            mech_fees = float(costs_by_day[mech_day_ts])
            data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=mech_day_ts,
                    daily_profit_raw=0.0,
                    daily_profit=-mech_fees,
                    cumulative_profit=0.0,  # recomputed below
                    daily_mech_requests=count,
                    daily_mech_cost=mech_fees,
                )
            )

        # Re-sort and recompute cumulative profit since mech-only days
        # may interleave with bet days
        data_points.sort(key=lambda dp: dp.timestamp)
        cumulative_profit = 0.0
        for dp in data_points:
            cumulative_profit += dp.daily_profit
            dp.cumulative_profit = round(cumulative_profit, 3)

        # Calculate total settled mech requests from all data points
        settled_mech_requests_count = sum(
            point.daily_mech_requests for point in data_points
        )
        self._unplaced_mech_requests_count = unplaced_count

        # Watermark: max timestamp across all fetched requests, held-back included
        last_mech_timestamp = max(
            (ts for ts_list in all_mech_request_lookup.values() for ts in ts_list),
            default=0,
        )

        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(data_points),
            data_points=data_points,
            settled_mech_requests_count=settled_mech_requests_count,
            unplaced_mech_requests_count=self._unplaced_mech_requests_count,
            placed_mech_requests_count=self._placed_mech_requests_count,
            includes_unplaced_mech_fees=True,
            last_mech_timestamp=last_mech_timestamp,
            schema_version=PROFIT_OVER_TIME_SCHEMA_VERSION,
            pending_mech_requests=pending_mech_requests,
            last_residual_rebuild_ts=last_residual_rebuild_ts,
            recent_mech_request_ids=self._recent_request_ids(
                self._fetched_mech_requests, last_mech_timestamp
            ),
        )

    def _perform_incremental_update(
        self,
        agent_safe_address: str,
        current_timestamp: int,
        existing_data: ProfitOverTimeData,
    ) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """Perform incremental update for new days only."""
        # Check if we're on a new day
        current_day = current_timestamp // SECONDS_PER_DAY
        last_updated_day = existing_data.last_updated // SECONDS_PER_DAY

        # Get the timestamp of the last data point
        last_data_timestamp = (
            existing_data.data_points[-1].timestamp if existing_data.data_points else 0
        )
        prev_last_point = (
            existing_data.data_points[-1] if existing_data.data_points else None
        )
        prev_len = len(existing_data.data_points) if existing_data.data_points else 0
        prev_settled_total = existing_data.settled_mech_requests_count

        # Same-day refresh: refetch today's stats and replace the last point; otherwise fetch only new days.
        replace_last = False
        # Always include last day in the query to detect updates
        start_ts = last_data_timestamp
        if current_day == last_updated_day:
            self.context.logger.info("Refreshing same-day profit statistics.")
            replace_last = True

        new_daily_stats = yield from self._fetch_daily_profit_statistics(
            agent_safe_address, start_ts
        )

        if new_daily_stats is None:
            self.context.logger.error("Failed to fetch new daily profit statistics")
            return None

        self.context.logger.info(
            f"Incremental update: Found {len(new_daily_stats)} new daily profit statistics"
        )

        # Keep stats on/after the last stored timestamp; same-day is allowed so
        # we can detect changes. An empty result still falls through: mech
        # requests made without trading are charged as mech-only days.
        filtered_daily_stats = [
            stat
            for stat in new_daily_stats
            if "date" in stat and int(stat["date"]) >= last_data_timestamp
        ]

        # Decide if we really should replace last point: only if incoming stats contain that same day
        last_point_day = (
            last_data_timestamp // SECONDS_PER_DAY if last_data_timestamp else None
        )
        incoming_days = {
            int(s["date"]) // SECONDS_PER_DAY for s in filtered_daily_stats
        }
        if last_point_day is not None and last_point_day in incoming_days:
            replace_last = True
        elif replace_last and (last_point_day not in incoming_days):
            replace_last = False

        # Every request past the watermark, traded or not, as the KPI's
        # ``total`` counts them all. mech-analytics can serve a request after
        # the watermark passed it, so that path refetches a window and dedupes.
        lookback = uses_mech_analytics(self.params)
        watermark = existing_data.last_mech_timestamp
        new_mech_requests = yield from self._fetch_all_mech_requests(
            agent_safe_address,
            block_timestamp_gt=(
                max(watermark - MECH_ANALYTICS_LOOKBACK_SECONDS, 0)
                if lookback
                else watermark
            ),
        )
        window_requests = new_mech_requests or []
        if lookback and new_mech_requests:
            seen = existing_data.recent_mech_request_ids
            new_mech_requests = [
                request
                for request in new_mech_requests
                if (
                    request["requestId"] not in seen
                    if seen is not None
                    else self._mech_request_key(request)[1] > watermark
                )
            ]

        # Retry only on a genuine failure (``None``); ``[]`` means nothing new
        # past the watermark. The lookback path refetches its window next round.
        if new_mech_requests is None:
            new_mech_requests = []
            if watermark > 0 and not lookback:
                lookback_ts = max(
                    existing_data.last_mech_timestamp - MECH_LOOKBACK_SECONDS, 0
                )
                self.context.logger.info(
                    f"Primary mech query failed; retrying with "
                    f"lookback window (watermark {existing_data.last_mech_timestamp} "
                    f"→ {lookback_ts})"
                )
                fallback_requests = yield from self._fetch_all_mech_requests(
                    agent_safe_address,
                    block_timestamp_gt=lookback_ts,
                )
                # Only entries strictly past the watermark are truly new;
                # anything at or below it was already attributed in a
                # previous tick.
                new_mech_requests = [
                    request
                    for request in fallback_requests or []
                    if self._mech_request_key(request)[1]
                    > existing_data.last_mech_timestamp
                ]

            if not new_mech_requests:
                self.context.logger.warning(
                    "Mech fetch failed and lookback did not recover — "
                    "preserving existing profit data"
                )
                return None

        fetched_keys = [
            key for key in map(self._mech_request_key, new_mech_requests) if key[1]
        ]
        previously_pending = [
            (request["title"], int(request["timestamp"]))
            for request in existing_data.pending_mech_requests
        ]
        mech_request_lookup, held_back = self._hold_back_open_requests(
            previously_pending + fetched_keys
        )
        self.context.logger.info(
            f"Incremental mech requests: fetched={len(fetched_keys)}, "
            f"previously_pending={len(previously_pending)}, "
            f"held_back={len(held_back)}, "
            f"to_charge={sum(len(v) for v in mech_request_lookup.values())}"
        )

        if not filtered_daily_stats and not fetched_keys and not mech_request_lookup:
            self.context.logger.info(
                "No new daily profit statistics or mech requests; "
                "skipping incremental update."
            )
            return existing_data

        request_costs = self._costs_by_key(
            new_mech_requests, existing_data.pending_mech_requests
        )
        pending_mech_requests = self._as_pending_mech_requests(held_back, request_costs)

        # Timestamp-based mech-to-bet attribution for new stats
        (
            fees_by_day,
            placed_delta,
            unplaced_delta,
            costs_by_day,
        ) = self._match_mech_requests_to_days(
            filtered_daily_stats, mech_request_lookup, request_costs
        )

        # Use persisted placed count as base (may be zero after restart)
        prev_placed = getattr(existing_data, "placed_mech_requests_count", 0)

        # Process new daily statistics
        new_data_points = list(existing_data.data_points)  # Copy existing points
        # Preserve the popped last day's mech attributions so that they
        # accumulate across ticks rather than being overwritten by the
        # single-slice ``fees_by_day`` produced by this run. Keyed by
        # day-index (``timestamp // SECONDS_PER_DAY``) so it lines up
        # with the ``incoming_days`` membership test above and with the
        # per-day pop below, whatever exact timestamps the two sides use.
        carry_by_day_idx: Dict[int, int] = {}
        carry_cost_by_day_idx: Dict[int, Decimal] = {}
        if replace_last and new_data_points:
            last_dp = new_data_points[-1]
            last_dp_day = last_dp.timestamp // SECONDS_PER_DAY
            if last_dp_day in incoming_days:  # pragma: no branch
                # False branch is unreachable: ``replace_last`` is only
                # set True when ``last_point_day in incoming_days``
                # earlier, and ``last_point_day == last_dp_day`` by
                # construction (both derived from the same last data
                # point's timestamp).
                carry_by_day_idx[last_dp_day] = last_dp.daily_mech_requests
                carry_cost_by_day_idx[last_dp_day] = last_dp.mech_cost_usd
                new_data_points.pop()
        cumulative_profit = (
            new_data_points[-1].cumulative_profit if new_data_points else 0.0
        )

        # Determine divisor based on platform
        profit_divisor = (
            USDC_DECIMALS_DIVISOR
            if self.params.is_running_on_polymarket
            else WEI_IN_ETH
        )

        new_mech_sum = 0
        for stat in filtered_daily_stats:
            date_timestamp = int(stat["date"])
            date_str = datetime.fromtimestamp(date_timestamp, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            daily_profit_raw = float(stat.get("dailyProfit", 0)) / profit_divisor

            # Combine this run's fresh attributions with the popped day's
            # stored count. Direct ``fees_by_day`` lookup avoids the
            # discarded ``mech_fees`` return from ``_apply_mech_fees``.
            fresh_count = fees_by_day.get(date_timestamp, 0)
            carried = carry_by_day_idx.pop(date_timestamp // SECONDS_PER_DAY, 0)
            daily_mech_count = fresh_count + carried
            carried_cost = carry_cost_by_day_idx.pop(
                date_timestamp // SECONDS_PER_DAY, Decimal(0)
            )
            mech_fees = float(
                costs_by_day.get(date_timestamp, Decimal(0)) + carried_cost
            )

            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net
            new_mech_sum += fresh_count

            new_data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=date_timestamp,
                    daily_profit_raw=daily_profit_raw,
                    daily_profit=daily_profit_net,
                    cumulative_profit=round(cumulative_profit, 3),
                    daily_mech_requests=daily_mech_count,
                    daily_mech_cost=mech_fees,
                )
            )

        # R2: Attribute mech-only days that fell outside the incremental
        # window. Days already present in ``new_data_points`` (carried over
        # from prior ticks) must be merged rather than duplicated, otherwise
        # the same day would appear twice in the sorted series and its fees
        # would be double-counted in the cumulative sum.
        visited_days = {int(s["date"]) for s in filtered_daily_stats if "date" in s}
        existing_by_ts = {int(dp.timestamp): dp for dp in new_data_points}
        for mech_day_ts in sorted(fees_by_day.keys() - visited_days):
            count = fees_by_day[mech_day_ts]
            date_str = datetime.fromtimestamp(mech_day_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            new_mech_sum += count
            existing_dp = existing_by_ts.get(mech_day_ts)
            if existing_dp is not None:
                old_count = existing_dp.daily_mech_requests
                old_cost = existing_dp.mech_cost_usd
                # Legacy points (persisted before ``daily_profit_raw`` was
                # added) leave the field ``None``. Reconstruct it from the
                # stored net so the merge does not silently zero the day's
                # gross profit.
                raw = existing_dp.daily_profit_raw
                if raw is None:
                    raw = existing_dp.daily_profit + float(old_cost)
                    existing_dp.daily_profit_raw = raw
                existing_dp.daily_mech_requests = old_count + count
                merged_fees = float(old_cost + costs_by_day[mech_day_ts])
                existing_dp.daily_mech_cost = merged_fees
                existing_dp.daily_profit = raw - merged_fees
                continue
            mech_fees = float(costs_by_day[mech_day_ts])
            new_data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=mech_day_ts,
                    daily_profit_raw=0.0,
                    daily_profit=-mech_fees,
                    cumulative_profit=0.0,  # recomputed below
                    daily_mech_requests=count,
                    daily_mech_cost=mech_fees,
                )
            )

        # Re-sort and recompute cumulative profit for the full series
        new_data_points.sort(key=lambda dp: dp.timestamp)
        cumulative_profit = 0.0
        for dp in new_data_points:
            cumulative_profit += dp.daily_profit
            dp.cumulative_profit = round(cumulative_profit, 3)

        # Tie the settled counter to the stored per-day data so the two
        # cannot drift. Any counter that is maintained separately from
        # ``data_points`` (via ``prev + delta`` arithmetic) is vulnerable
        # to the fallback re-fetch + replace_last interaction that has
        # inflated stored counters ~3x in production.
        settled_mech_requests_count = sum(
            dp.daily_mech_requests for dp in new_data_points
        )
        # ``placed_total`` still accumulates because we do not persist a
        # per-day placed-vs-unplaced split; clamp it to settled so it
        # cannot exceed the total attributed count under any drift.
        placed_pre_clamp = prev_placed + placed_delta
        placed_total = min(placed_pre_clamp, settled_mech_requests_count)
        if placed_pre_clamp > settled_mech_requests_count:
            self.context.logger.warning(
                f"placed_total clamped to settled: prev({prev_placed}) + "
                f"delta({placed_delta}) = {placed_pre_clamp} > "
                f"settled({settled_mech_requests_count})"
            )
        prev_unplaced = getattr(existing_data, "unplaced_mech_requests_count", 0)
        unplaced_mech_requests_count = min(
            prev_unplaced + unplaced_delta,
            max(settled_mech_requests_count - placed_total, 0),
        )
        # Legitimate downward moves happen (e.g. right after a rebuild).
        # Log so a stuck agent is visible rather than silently ratcheting
        # the KPI's mech-cost subtraction down.
        if settled_mech_requests_count < prev_settled_total:
            self.context.logger.warning(
                f"Settled count decreased: {prev_settled_total} -> "
                f"{settled_mech_requests_count}"
            )
        self._placed_mech_requests_count = placed_total
        self._unplaced_mech_requests_count = unplaced_mech_requests_count
        self.context.logger.info(
            f"Incremental totals => placed_total={placed_total}, "
            f"unplaced_total={unplaced_mech_requests_count}, "
            f"settled_total={settled_mech_requests_count}, "
            f"delta_new_attributions={new_mech_sum}"
        )
        self.context.logger.info(
            f"Incremental end snapshot: settled={settled_mech_requests_count}, "
            f"placed={placed_total}, unplaced={unplaced_mech_requests_count}, "
            f"days={len(new_data_points)}"
        )

        last_mech_timestamp = max(
            [existing_data.last_mech_timestamp] + [ts for _, ts in fetched_keys]
        )

        # If we only reprocessed the last day and nothing changed (profits AND mech counts), skip writing.
        if (
            new_mech_sum == 0
            and unplaced_delta == 0
            and placed_delta == 0
            and replace_last
            and prev_last_point
            and len(new_data_points) == prev_len
            and new_data_points
        ):
            new_last = new_data_points[-1]
            if (
                new_last.timestamp == prev_last_point.timestamp
                and round(new_last.daily_profit_raw or 0.0, 3)
                == round(getattr(prev_last_point, "daily_profit_raw", 0.0) or 0.0, 3)
                and new_last.daily_profit == prev_last_point.daily_profit
                and new_last.daily_mech_requests == prev_last_point.daily_mech_requests
                and settled_mech_requests_count == prev_settled_total
                and pending_mech_requests == existing_data.pending_mech_requests
                and last_mech_timestamp == existing_data.last_mech_timestamp
            ):
                self.context.logger.info(
                    "Last day unchanged (profit/mech/settled); skipping update."
                )
                return existing_data

        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(new_data_points),
            data_points=new_data_points,
            settled_mech_requests_count=settled_mech_requests_count,
            unplaced_mech_requests_count=unplaced_mech_requests_count,
            placed_mech_requests_count=self._placed_mech_requests_count,
            includes_unplaced_mech_fees=True,
            last_mech_timestamp=last_mech_timestamp,
            schema_version=PROFIT_OVER_TIME_SCHEMA_VERSION,
            pending_mech_requests=pending_mech_requests,
            last_residual_rebuild_ts=existing_data.last_residual_rebuild_ts,
            residual_rebuild_backoff_days=existing_data.residual_rebuild_backoff_days,
            recent_mech_request_ids=self._recent_request_ids(
                window_requests, last_mech_timestamp
            ),
        )

    def _update_profit_over_time_storage(self) -> Generator[None, None, None]:
        """Update profit over time data in storage."""

        # Check if we need to update (daily check)
        existing_summary = self.shared_state.read_existing_performance_summary()

        # Build new profit over time data
        self.context.logger.info("Updating profit over time data...")
        profit_data = yield from self._build_profit_over_time_data()

        if profit_data:
            # Update the summary with new profit data
            existing_summary.profit_over_time = profit_data
            self.shared_state.overwrite_performance_summary(existing_summary)
            self.context.logger.info(
                f"Updated profit over time data with {profit_data.total_days} days"
            )
        else:
            self.context.logger.warning("Failed to build profit over time data")

    def _fetch_agent_performance_summary(self) -> Generator[None, None, None]:
        """Fetch the agent performance summary"""

        agent_safe_address = self.synchronized_data.safe_contract_address
        # ``None`` from ``_calculate_settled_mech_requests`` means the
        # total-count fetch failed this round. Leave ``self.``'s init-time
        # ``None`` in place so downstream (``calculate_roi`` /
        # ``_build_performance_metrics``) can short-circuit to ``(None,
        # None)`` / ``None``. This behaviour is re-instantiated per round,
        # so there is no prior-round ``self._settled_mech_requests_count``
        # to fall back on — the propagation-to-NA route is the only one
        # that keeps the previously-persisted Total ROI intact via
        # ``_save_agent_performance_summary``'s NA-preservation fallback.
        settled = yield from self._calculate_settled_mech_requests(agent_safe_address)
        if settled is not None:
            self._settled_mech_requests_count = settled

        current_timestamp = self.shared_state.synced_timestamp
        profit_over_time = yield from self._build_profit_over_time_data()
        counts_source = (
            profit_over_time
            or self.shared_state.read_existing_performance_summary().profit_over_time
        )
        if counts_source is None:
            self._unplaced_mech_requests_count = None
            self._placed_mech_requests_count = None
        else:
            self._unplaced_mech_requests_count = (
                counts_source.unplaced_mech_requests_count
            )
            self._placed_mech_requests_count = getattr(
                counts_source, "placed_mech_requests_count", 0
            )

        final_roi, partial_roi = yield from self.calculate_roi()

        metrics = []

        accuracy = yield from self._get_prediction_accuracy()

        metrics.append(
            AgentPerformanceMetrics(
                name="Prediction accuracy",
                is_primary=False,
                description="Percentage of correct predictions",
                value=f"{round(accuracy)}%" if accuracy is not None else NA,
            )
        )

        agent_details = yield from self._fetch_agent_details_data()
        agent_performance = yield from self._fetch_agent_performance_data()
        prediction_history = self._fetch_prediction_history()

        # Filter by status, not total_payout: with sell-aware semantics,
        # fully-sold-at-loss bets carry non-zero total_payout (realized
        # proceeds) but should not satisfy the ROI display gate.
        winning_trades = [
            item
            for item in prediction_history.items
            if item.get("status") == BetStatus.WON.value
        ]
        if len(winning_trades) >= MIN_TRADES_FOR_ROI_DISPLAY:
            partial_roi_string = (
                f"{round(partial_roi)}%" if partial_roi is not None else NA
            )
            metrics.append(
                AgentPerformanceMetrics(
                    name="Total ROI",
                    is_primary=True,
                    description=f"Total return on investment including staking rewards. Partial ROI (Prediction market activity only): <b>{partial_roi_string}</b>",
                    value=f"{round(final_roi)}%" if final_roi is not None else NA,
                )
            )
        else:
            metrics.append(
                AgentPerformanceMetrics(
                    name="Total ROI",
                    is_primary=True,
                    description=f"Total return on investment including staking rewards. ROI is not shown until at least {MIN_TRADES_FOR_ROI_DISPLAY} winning trades have been made to ensure statistical significance.",
                    value=MORE_TRADES_NEEDED_TEXT,
                )
            )
        self._agent_performance_summary = AgentPerformanceSummary(
            timestamp=current_timestamp,
            metrics=metrics,
            agent_behavior=None,
            agent_details=agent_details,
            agent_performance=agent_performance,
            prediction_history=prediction_history,
            profit_over_time=profit_over_time,
        )

    def _save_agent_performance_summary(
        self, agent_performance_summary: AgentPerformanceSummary
    ) -> None:
        """Save the agent performance summary to a file, preserving existing data for failed sections."""
        existing_data = self.shared_state.read_existing_performance_summary()

        # Always preserve agent_behavior from existing data
        agent_performance_summary.agent_behavior = existing_data.agent_behavior

        # Achievements are written by ``UpdateAchievementsBehaviour``; losing
        # them here would reset the backlog-guard watermark. Re-read them
        # leniently, like ``offchain_deposits`` below, so a corrupt sibling
        # that degraded ``existing_data`` cannot wipe them.
        agent_performance_summary.achievements = (
            self.shared_state.read_achievements_from_disk()
        )
        # Written by the stop-trading check and the chat; the rebuild above
        # knows nothing of it.
        agent_performance_summary.activity_goal = (
            self.shared_state.read_activity_goal_from_disk()
        )

        # Keep a stored ``offchain_deposits`` (no longer updated): the rebuilt
        # summary omits it, so re-read it leniently from disk.
        disk_offchain = self.shared_state.read_offchain_deposits_from_disk()
        if disk_offchain is not None:
            agent_performance_summary.offchain_deposits = disk_offchain

        # Track whether any section fell back to existing data
        preserved = False

        # Preserve metrics where new value is NA but existing had real values
        if existing_data.metrics:
            existing_by_name = {m.name: m for m in existing_data.metrics}
            for i, metric in enumerate(agent_performance_summary.metrics):
                if metric.value == NA and metric.name in existing_by_name:
                    existing_metric = existing_by_name[metric.name]
                    if existing_metric.value != NA:
                        agent_performance_summary.metrics[i] = existing_metric
                        preserved = True

        # Preserve agent_details if new has all-None fields
        if (
            agent_performance_summary.agent_details is not None
            and agent_performance_summary.agent_details.id is None
            and agent_performance_summary.agent_details.created_at is None
            and agent_performance_summary.agent_details.last_active_at is None
            and existing_data.agent_details is not None
        ):
            agent_performance_summary.agent_details = existing_data.agent_details
            preserved = True

        # Preserve agent_performance if new has all-None key fields
        if (
            agent_performance_summary.agent_performance is not None
            and agent_performance_summary.agent_performance.metrics is not None
            and agent_performance_summary.agent_performance.metrics.all_time_funds_used
            is None
            and agent_performance_summary.agent_performance.metrics.all_time_profit
            is None
            and agent_performance_summary.agent_performance.metrics.roi is None
            and existing_data.agent_performance is not None
        ):
            agent_performance_summary.agent_performance = (
                existing_data.agent_performance
            )
            preserved = True

        # Preserve profit_over_time if new is None
        if (
            agent_performance_summary.profit_over_time is None
            and existing_data.profit_over_time is not None
        ):
            agent_performance_summary.profit_over_time = existing_data.profit_over_time
            preserved = True

        # Preserve prediction_history if new has 0 predictions and empty items
        if (
            agent_performance_summary.prediction_history is not None
            and agent_performance_summary.prediction_history.total_predictions == 0
            and not agent_performance_summary.prediction_history.items
            and existing_data.prediction_history is not None
            and existing_data.prediction_history.total_predictions > 0
        ):
            agent_performance_summary.prediction_history = (
                existing_data.prediction_history
            )
            preserved = True

        # If any section was preserved, keep the existing timestamp so the UI
        # can detect that the data is stale rather than freshly fetched.
        if preserved and existing_data.timestamp is not None:
            agent_performance_summary.timestamp = existing_data.timestamp

        self.shared_state.overwrite_performance_summary(agent_performance_summary)
        self._record_resolved_markets(
            existing_data.prediction_history,
            agent_performance_summary.prediction_history,
        )

    def _record_resolved_markets(
        self,
        previous: Optional[PredictionHistory],
        current: Optional[PredictionHistory],
    ) -> None:
        """Write a ``Market resolved`` card for each prediction that has left pending.

        :param previous: the history saved before this refresh.
        :param current: the history just saved.
        """
        if previous is None or current is None:
            return
        was_pending = {
            item.get("id")
            for item in previous.items
            if isinstance(item, dict) and item.get("status") == BetStatus.PENDING.value
        }
        resolved = [
            item
            for item in current.items
            if isinstance(item, dict)
            and item.get("id") in was_pending
            and item.get("status") in RESOLVED_STATUSES
        ]
        if not resolved:
            return
        is_polymarket = self.params.is_running_on_polymarket
        slugs = self._polymarket_slugs() if is_polymarket else {}
        for item in resolved:
            try:
                market = item["market"]
                opened_ts = _parse_iso_timestamp(item.get("created_at"))
                opened = format_date(opened_ts) if opened_ts is not None else "Unknown"
                url = (
                    market_url(True, None, slugs.get(market.get("condition_id")))
                    if is_polymarket
                    else market.get("external_url")
                )
                fields = [
                    field("Market", market["title"], url),
                    field("Result", item["status"].capitalize()),
                    field(
                        "Amount traded",
                        format_amount(float(item["bet_amount"]), is_polymarket),
                    ),
                    field("Opened", opened),
                ]
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                self.context.logger.warning(
                    f"Not writing a resolved market for malformed prediction "
                    f"{item.get('id')!r}: {e!r}"
                )
                continue
            record_event(
                self.params.store_path,
                EventType.MARKET_RESOLVED,
                fields,
                self.context.logger,
            )

    def _polymarket_slugs(self) -> Dict[str, str]:
        """Return the slug of each known Polymarket market by its condition id."""
        fetcher = PolymarketPredictionsFetcher(self.context, self.context.logger)
        return fetcher.load_market_slugs(str(self.params.store_path))

    @staticmethod
    def _is_leaderboard_refresh_due(last_attempt_at: Optional[int], now: int) -> bool:
        """Return whether a refresh is due; a future watermark counts as due.

        :param last_attempt_at: the persisted throttle watermark
        :param now: the current timestamp
        :return: whether a refresh is due
        """
        return (
            last_attempt_at is None
            or last_attempt_at > now + LEADERBOARD_CLOCK_SKEW_SECONDS
            or now - last_attempt_at >= LEADERBOARD_REFRESH_INTERVAL
        )

    def _update_leaderboard(self) -> None:
        """Start a refresh on a worker thread at most once per interval; never raises."""
        api_url = self.params.olas_predict_leaderboard_url
        if not api_url:
            return
        try:
            existing = self.shared_state.get_leaderboard() or LeaderboardData()
            now = self.shared_state.synced_timestamp
            if not self._is_leaderboard_refresh_due(existing.last_attempt_at, now):
                return
            if self.shared_state.is_leaderboard_refresh_running():
                self.context.logger.info(
                    "The previous leaderboard refresh is still running; skipping"
                )
                return

            # Persist the watermark first: a refresh cut short (restart) must
            # not make every following period retry.
            self.shared_state.update_leaderboard(
                LeaderboardData(windows=dict(existing.windows), last_attempt_at=now)
            )
            self.shared_state.start_leaderboard_refresh(
                partial(
                    refresh_leaderboard,
                    self.shared_state,
                    self.context.logger,
                    api_url,
                    get_leaderboard_agent_type(self.params.is_running_on_polymarket),
                    self.synchronized_data.safe_contract_address.lower(),
                    now,
                )
            )
        except Exception as e:  # pylint: disable=broad-except
            self.context.logger.warning(
                f"Could not start the leaderboard refresh: {e}", exc_info=True
            )

    def async_act(self) -> Generator:
        """Do the action."""
        if not self.params.is_agent_performance_summary_enabled:
            self.context.logger.info(
                "Agent performance summary is disabled. Skipping fetch and save."
            )
            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=True,
            )
            yield from self.finish_behaviour(payload)
            return

        if not self._should_update():
            self.context.logger.info("Skipping update - too soon")
            self._update_leaderboard()
            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=True,
            )
            yield from self.finish_behaviour(payload)
            return

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self._last_update_timestamp = self.shared_state.synced_timestamp
            yield from self._fetch_agent_performance_summary()

            if self._agent_performance_summary is not None:
                success = all(
                    metric.value != NA
                    for metric in self._agent_performance_summary.metrics
                )
                if not success:
                    self.context.logger.warning(
                        "Agent performance summary could not be fetched. Preserving existing values for failed metrics"
                    )
                self._save_agent_performance_summary(self._agent_performance_summary)
            else:
                success = False
                self.context.logger.error("Agent performance summary is None")

            self._update_leaderboard()

            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=success,
            )

        yield from self.finish_behaviour(payload)

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class UpdateAchievementsBehaviour(
    APTQueryingBehaviour,
):
    """A behaviour for updating the agent achievements database."""

    matching_round = UpdateAchievementsRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)

        if self.params.is_running_on_polymarket:
            self._bet_payout_checker = BetPayoutChecker(
                achievement_type="polystrat/payout",
                roi_threshold=POLYMARKET_ACHIEVEMENT_ROI_THRESHOLD,
                description_template=POLYMARKET_ACHIEVEMENT_DESCRIPTION_TEMPLATE,
            )
        else:
            self._bet_payout_checker = BetPayoutChecker(
                achievement_type="omenstrat/payout",
                roi_threshold=OMENSTRAT_ACHIEVEMENT_ROI_THRESHOLD,
                description_template=OMENSTRAT_ACHIEVEMENT_DESCRIPTION_TEMPLATE,
                skip_settled_before_enabled=True,
                require_remaining_shares=True,
            )

    def async_act(self) -> Generator:
        """Do the action."""

        if not self.params.is_achievement_checker_enabled:
            self.context.logger.info(
                "Achievement checker is disabled. Skipping achievements update."
            )
            payload = UpdateAchievementsPayload(
                sender=self.context.agent_address,
                vote=True,
            )
            yield from self.finish_behaviour(payload)
            return

        agent_performance_summary = (
            self.shared_state.read_existing_performance_summary()
        )

        achievements = agent_performance_summary.achievements
        if achievements is None:
            achievements = Achievements()
            agent_performance_summary.achievements = achievements

        achievements_updated = False
        achievements_updated = self._bet_payout_checker.update_achievements(
            achievements=agent_performance_summary.achievements,
            prediction_history=agent_performance_summary.prediction_history,
            now=self.shared_state.synced_timestamp,
            logger=self.context.logger,
        )

        if achievements_updated:
            self.context.logger.info("Agent achievements updated.")
            self.shared_state.overwrite_performance_summary(agent_performance_summary)
        else:
            self.context.logger.info("Agent achievements not updated.")

        success = True  # Left to handle error conditions on future achievement checkers
        payload = UpdateAchievementsPayload(
            sender=self.context.agent_address,
            vote=success,
        )

        yield from self.finish_behaviour(payload)
        return

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class AgentPerformanceSummaryRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the AgentPerformanceSummary behaviour."""

    initial_behaviour_cls = FetchPerformanceSummaryBehaviour
    abci_app_cls = AgentPerformanceSummaryAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {FetchPerformanceSummaryBehaviour, UpdateAchievementsBehaviour}  # type: ignore
