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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, List, Optional, Set, Tuple, Type, cast

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
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher as BasePredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import (
    PolymarketPredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    PredictionsFetcher,
    _parse_current_answer,
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
    PerformanceMetricsData,
    PerformanceStatsData,
    PredictionHistory,
    ProfitDataPoint,
    ProfitOverTimeData,
    SharedState,
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

DEFAULT_MECH_FEE = 1e16  # Fixed fee per mech request, scaled to 18 decimals (0.01 when divided by 1e18)
QUESTION_DATA_SEPARATOR = "\u241f"
PREDICT_MARKET_DURATION_DAYS = 4
WXDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"  # wxDAI on Gnosis Chain
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon
USDC_DECIMALS_DIVISOR = 10**6  # USDC.e has 6 decimals
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
NA = "N/A"
UPDATE_INTERVAL = 1800  # 30 mins
TX_HISTORY_DEPTH = 25  # match healthcheck slice length
POLYMARKET_ACHIEVEMENT_ROI_THRESHOLD = 1.5
POLYMARKET_ACHIEVEMENT_DESCRIPTION_TEMPLATE = """My Polystrat agent just made {roi}\u00d7 ROI on Polymarket! \U0001f680

Check it out\U0001f447
{{achievement_url}}"""


MIN_TRADES_FOR_ROI_DISPLAY = 10
MORE_TRADES_NEEDED_TEXT = "More trades needed"


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
        self._mech_request_lookup: Optional[dict] = None
        self._update_interval: int = UPDATE_INTERVAL
        self._last_update_timestamp: int = 0
        self._settled_mech_requests_count: int = 0
        self._placed_mech_requests_count: int = 0
        self._unplaced_mech_requests_count: int = 0
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
    ) -> Generator[None, None, Set[str]]:
        """Fetch open position titles from Polymarket.

        Returns a set of position titles (market questions) for positions
        that are currently open (not redeemed). These are used to identify
        which mech requests should be counted as 'open' (not settled).

        :return: Set of position titles
        :yield: None
        """
        try:
            # Prepare payload - FETCH_ALL_POSITIONS with no redeemable filter
            payload = {
                "request_type": RequestType.FETCH_ALL_POSITIONS.value,
                "params": {},  # No redeemable param = returns all positions
            }

            positions = yield from self.send_polymarket_connection_request(payload)

            if not positions or not isinstance(positions, list):
                self.context.logger.warning(
                    f"No positions returned from Polymarket connection: {positions}"
                )
                return set()

            # Extract titles from positions
            titles = {
                p.get("title", "")
                for p in positions
                if isinstance(p, dict) and p.get("title", "")
            }

            self.context.logger.info(
                f"Fetched {len(positions)} positions from Polymarket, "
                f"extracted {len(titles)} unique titles"
            )
            return titles

        except Exception as e:
            self.context.logger.error(f"Error fetching Polymarket positions: {e}")
            return set()

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
    ) -> Generator[None, None, int]:
        """Get total number of mech requests (cached).

        :param agent_safe_address: The agent's safe address
        :return: Total number of mech requests
        :yield: None
        """
        if self._total_mech_requests is not None:
            return self._total_mech_requests

        mech_sender = yield from self._fetch_mech_sender(
            agent_safe_address=agent_safe_address,
            timestamp_gt=self.market_open_timestamp,
        )

        if not mech_sender or mech_sender.get("totalMarketplaceRequests") is None:
            self._total_mech_requests = 0
            return 0

        self._total_mech_requests = int(mech_sender["totalMarketplaceRequests"])
        self.context.logger.info(f"{self._total_mech_requests=}")
        return self._total_mech_requests

    def _get_open_market_requests(
        self, agent_safe_address: str
    ) -> Generator[None, None, int]:
        """Get number of mech requests for open markets (cached).

        :param agent_safe_address: The agent's safe address
        :return: Number of open market requests
        :yield: None
        """
        if self._open_market_requests is not None:
            return self._open_market_requests

        # Fetch mech sender to get recent requests
        mech_sender = yield from self._fetch_mech_sender(
            agent_safe_address=agent_safe_address,
            timestamp_gt=self.market_open_timestamp,
        )

        if not mech_sender:
            self._open_market_requests = 0
            return 0

        last_four_days_requests = mech_sender.get("requests", [])

        # Platform-specific: get open markets
        if self.params.is_running_on_polymarket:
            # For Polymarket: get open positions from connection
            open_market_titles = (
                yield from self._fetch_polymarket_open_position_titles()
            )
        else:
            # For Omen: get open markets from subgraph
            open_markets = yield from self._fetch_open_markets(
                timestamp_gt=self.market_open_timestamp,
            )

            if not open_markets:
                self._open_market_requests = 0
                return 0

            # Get titles of open markets
            open_market_titles = {
                q["question"].split(QUESTION_DATA_SEPARATOR, 4)[0]
                for q in open_markets
                if q.get("question")
            }

        # Count requests for still-open markets
        open_market_requests = sum(
            (r.get("parsedRequest", {}) or {}).get("questionTitle")
            in open_market_titles
            for r in last_four_days_requests
        )

        self._open_market_requests = open_market_requests
        self.context.logger.info(f"{self._open_market_requests=}")
        return self._open_market_requests

    def _calculate_settled_mech_requests(
        self, agent_safe_address: str
    ) -> Generator[None, None, int]:
        """Calculate the number of settled mech requests (excludes open markets).

        :param agent_safe_address: The agent's safe address
        :return: Number of settled mech requests
        :yield: None
        """
        # Get total mech requests (uses cache if available)
        total_mech_requests = yield from self._get_total_mech_requests(
            agent_safe_address
        )

        if not total_mech_requests:
            return 0

        # Get open market requests (uses cache if available)
        open_market_requests = yield from self._get_open_market_requests(
            agent_safe_address
        )

        # where settled = Total - Open
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
            or trader_agent.get("totalPayout") is None
        ):
            self.context.logger.warning(
                f"Trader agent data not found or incomplete for {agent_safe_address=} and {trader_agent=}"
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
        total_market_payout_raw = int(trader_agent.get("totalPayout", 0))

        self.context.logger.info(
            f"[ROI Calculation] Raw values from subgraph: "
            f"totalTradedSettled={total_traded_settled_raw}, "
            f"totalFeesSettled={total_fees_settled_raw}, "
            f"totalPayout={total_market_payout_raw}"
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

        # Convert mech costs from wei to native token, then treat as USD
        # Fixed 0.01 fee per request (DEFAULT_MECH_FEE is scaled to 18 decimals)
        settled_mech_costs_raw = settled_mech_requests * DEFAULT_MECH_FEE
        settled_mech_costs_usd = settled_mech_costs_raw / WEI_IN_ETH

        self.context.logger.info(
            f"[ROI Calculation] Mech costs: "
            f"settled_mech_requests={settled_mech_requests}, "
            f"settled_mech_costs_raw={settled_mech_costs_raw}, "
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
            self.context.logger.warning(
                f"Agent bets data not found for {agent_safe_address=}. Trader may be unstaked."
            )
            return None

        if len(agent_bets_data.get("bets", [])) == 0:
            return None

        # Platform-specific accuracy calculation
        if self.params.is_running_on_polymarket:
            return self._calculate_polymarket_accuracy(agent_bets_data)
        else:
            return self._calculate_omen_accuracy(agent_bets_data)

    def _now(self) -> int:
        """Return the current wall-clock time as a Unix timestamp.

        Indirected through a method so tests can patch it deterministically.

        :return: current Unix timestamp in seconds.
        """
        return int(time.time())

    def _calculate_omen_accuracy(self, agent_bets_data: dict) -> Optional[float]:
        """Calculate prediction accuracy for Omen markets."""
        bets = agent_bets_data.get("bets", [])
        now = self._now()

        # Bug A (ZD#919): only finalized markets contribute to accuracy.
        # Reality.eth answers can flip during the dispute window, so a bet
        # whose market has currentAnswer set but answerFinalizedTimestamp
        # in the future is still provisional and must be excluded.
        bets_on_finalized_markets = []
        for bet in bets:
            fpmm = bet.get("fixedProductMarketMaker", {})
            if fpmm.get("currentAnswer") is None:
                continue
            finalized_ts = fpmm.get("answerFinalizedTimestamp")
            if finalized_ts is None or int(finalized_ts) > now:
                continue
            bets_on_finalized_markets.append(bet)

        if not bets_on_finalized_markets:
            return None

        won_bets = 0
        total_bets = 0

        for bet in bets_on_finalized_markets:
            market_answer = bet["fixedProductMarketMaker"]["currentAnswer"]
            bet_answer = bet.get("outcomeIndex")
            if market_answer == INVALID_ANSWER_HEX or bet_answer is None:
                continue
            correct = _parse_current_answer(market_answer)
            if correct is None:
                # Malformed currentAnswer — skip rather than crash.
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

        # Calculate metrics
        metrics = yield from self._calculate_performance_metrics(trader_agent)
        stats = yield from self._calculate_performance_stats(trader_agent)

        return AgentPerformanceData(
            window="lifetime",
            currency="USD",
            metrics=metrics,
            stats=stats,
        )

    def _calculate_performance_metrics(
        self, trader_agent: dict
    ) -> Generator[None, None, PerformanceMetricsData]:
        """Calculate performance metrics from trader agent data."""
        safe_address = self.synchronized_data.safe_contract_address.lower()

        total_traded = int(trader_agent.get("totalTraded", 0))
        total_fees = int(trader_agent.get("totalFees", 0))
        total_traded_settled = int(trader_agent.get("totalTradedSettled", 0))
        total_fees_settled = int(trader_agent.get("totalFeesSettled", 0))
        total_payout = int(trader_agent.get("totalPayout", 0))

        settled_mech_requests = self._settled_mech_requests_count

        # Get mech request counts (uses caches populated earlier)
        total_mech_requests = yield from self._get_total_mech_requests(safe_address)
        open_mech_requests = self._open_market_requests or 0
        placed_mech_requests = self._placed_mech_requests_count
        unplaced_mech_requests = max(
            (total_mech_requests or 0) - open_mech_requests - placed_mech_requests,
            0,
        )

        all_mech_costs = total_mech_requests * DEFAULT_MECH_FEE

        # Use appropriate divisor based on platform
        # For Polymarket: USDC has 6 decimals; For Gnosis: xDAI has 18 decimals
        token_divisor = (
            USDC_DECIMALS_DIVISOR
            if self.params.is_running_on_polymarket
            else WEI_IN_ETH
        )

        # All-time funds used: traded + fees + ALL mech costs
        all_time_funds_used = (total_traded + total_fees) / token_divisor + (
            all_mech_costs / WEI_IN_ETH
        )

        # All-time profit: uses settled traded/fees and settled mech costs
        # Settled mech requests include both placed and unplaced mech calls (excluding open markets).
        settled_mech_costs = settled_mech_requests * DEFAULT_MECH_FEE
        all_time_profit = (
            total_payout - total_traded_settled - total_fees_settled
        ) / token_divisor - (settled_mech_costs / WEI_IN_ETH)

        # Calculate locked funds
        funds_locked_in_markets = (total_traded - total_traded_settled) / token_divisor

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
            settled_mech_request_count=self._settled_mech_requests_count,
            total_mech_request_count=total_mech_requests,
            open_mech_request_count=open_mech_requests,
            placed_mech_request_count=placed_mech_requests,
            unplaced_mech_request_count=unplaced_mech_requests,
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
                "toToken": USDC_E_ADDRESS,
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
            USDC_E_ADDRESS if self.params.is_running_on_polymarket else WXDAI_ADDRESS
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
    ) -> Tuple[Dict[int, int], int, int]:
        """Match mech requests to bet days using timestamps (last-before-bet via bisect).

        For each bet, consumes the last mech request with timestamp <= bet timestamp.
        When bet-level timestamps are available (via profitParticipants[].bets[]),
        matching is precise.  Falls back to day_ts when bets field is absent.
        Remaining unconsumed requests are unplaced and assigned to their own
        mech-request day.

        :param daily_stats: List of daily profit statistics
        :param mech_request_lookup: Dictionary mapping question titles to sorted timestamp lists
        :return: Tuple of (fees_by_day, placed_count, unplaced_count)
        """
        # Deep-copy timestamps so we can pop without mutating the original lookup
        remaining: Dict[str, List[int]] = {
            title: list(timestamps) for title, timestamps in mech_request_lookup.items()
        }

        fees_by_day: Dict[int, int] = {}
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
                    ts_list.pop(idx)
                    fees_by_day[day_ts] = fees_by_day.get(day_ts, 0) + 1
                    placed_count += 1

        # Remaining unconsumed requests are unplaced — assign to mech request's own day
        unplaced_count = 0
        for ts_list in remaining.values():
            for mech_ts in ts_list:
                mech_day = (mech_ts // SECONDS_PER_DAY) * SECONDS_PER_DAY
                fees_by_day[mech_day] = fees_by_day.get(mech_day, 0) + 1
                unplaced_count += 1

        return fees_by_day, placed_count, unplaced_count

    def _apply_mech_fees(
        self, fees_by_day: Dict[int, int], date_timestamp: int
    ) -> Tuple[float, int]:
        """Look up pre-computed mech fee count for a day.

        :param fees_by_day: Pre-computed mapping of day timestamp to mech request count
        :param date_timestamp: The day timestamp to look up
        :return: Tuple of (mech_fees_in_eth, mech_request_count)
        """
        count = fees_by_day.get(date_timestamp, 0)
        return count * (DEFAULT_MECH_FEE / WEI_IN_ETH), count

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

        if not all_mech_requests:
            self.context.logger.warning("No mech requests found for agent")
            return {}

        # Build lookup map: question_title -> sorted timestamps
        lookup: Dict[str, List[int]] = {}
        for request in all_mech_requests:
            title = (request.get("parsedRequest", {}) or {}).get("questionTitle", "")
            ts = int(request.get("blockTimestamp", 0))
            if title and ts:
                lookup.setdefault(title, []).append(ts)

        for title in lookup:
            lookup[title].sort()

        total_requests = sum(len(v) for v in lookup.values())
        self.context.logger.info(
            f"Built mech request lookup with {len(lookup)} unique questions, {total_requests} total requests"
        )
        self._mech_request_lookup = lookup
        return lookup

    def _build_profit_over_time_data(
        self,
    ) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """Build profit over time data with efficient backfill and incremental update strategy.

        :return: ProfitOverTimeData or None
        :yield: None
        """
        agent_safe_address = self.synchronized_data.safe_contract_address.lower()
        current_timestamp = self.shared_state.synced_timestamp

        # Check if we have existing profit data
        existing_summary = self.shared_state.read_existing_performance_summary()
        existing_profit_data = existing_summary.profit_over_time

        # Determine if this is initial backfill or incremental update
        # Rebuild if missing data, or when new fields (settled mech count / unplaced mech fees) are absent
        if not existing_profit_data or not existing_profit_data.data_points:
            # INITIAL BACKFILL - First time or no existing data
            self.context.logger.info("Performing initial profit over time backfill...")
            return (
                yield from self._perform_initial_backfill(
                    agent_safe_address, current_timestamp
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
                    agent_safe_address, current_timestamp
                )
            )
        elif not getattr(existing_profit_data, "includes_unplaced_mech_fees", False):
            # INITIAL BACKFILL - Apply new non-placed mech fees logic and track counts
            self.context.logger.info(
                "Performing initial profit over time backfill to include unplaced mech fees and counts..."
            )
            return (
                yield from self._perform_initial_backfill(
                    agent_safe_address, current_timestamp
                )
            )
        else:
            # INCREMENTAL UPDATE - Check if we need to add new days
            # M5: Log mismatch between series-attributed and snapshot counts as
            # diagnostic only.  These are produced by different models and benign
            # drift is expected; only rebuild on missing fields or storage migration.
            settled_reference = self._settled_mech_requests_count
            stored_settled = existing_profit_data.settled_mech_requests_count
            if (
                settled_reference is not None
                and stored_settled
                and stored_settled != settled_reference
            ):
                self.context.logger.warning(
                    f"Settled mech count drift (series={stored_settled}, "
                    f"snapshot={settled_reference}); diagnostic only, no rebuild."
                )
            self.context.logger.info(
                "Checking for incremental profit over time updates..."
            )
            return (
                yield from self._perform_incremental_update(
                    agent_safe_address, current_timestamp, existing_profit_data
                )
            )

    def _perform_initial_backfill(
        self, agent_safe_address: str, current_timestamp: int
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
            )

        self.context.logger.info(
            f"Initial backfill: Found {len(daily_stats)} daily profit statistics"
        )

        # Build mech request lookup ONCE for all historical data.
        # Fail-closed (H6): every bet must have a mech request. Non-empty trading
        # stats with an empty mech lookup = unavailable subgraph data — suppress the
        # series (return None preserves stored data) rather than emit zero mech fees.
        mech_request_lookup = yield from self._build_mech_request_lookup(
            agent_safe_address
        )
        if not mech_request_lookup:
            self.context.logger.warning(
                "No mech requests found — preserving existing profit data"
            )
            return None

        # Timestamp-based mech-to-bet attribution
        fees_by_day, placed_count, unplaced_count = self._match_mech_requests_to_days(
            daily_stats, mech_request_lookup
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
                fees_by_day, date_timestamp
            )

            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net

            data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=date_timestamp,
                    daily_profit_raw=round(daily_profit_raw, 3),
                    daily_profit=round(daily_profit_net, 3),
                    cumulative_profit=round(cumulative_profit, 3),
                    daily_mech_requests=daily_mech_count,
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
            mech_fees = count * (DEFAULT_MECH_FEE / WEI_IN_ETH)
            data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=mech_day_ts,
                    daily_profit_raw=0.0,
                    daily_profit=round(-mech_fees, 3),
                    cumulative_profit=0.0,  # recomputed below
                    daily_mech_requests=count,
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

        # Watermark: max mech request timestamp across all processed requests
        last_mech_timestamp = max(
            (ts for ts_list in mech_request_lookup.values() for ts in ts_list),
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
            return existing_data

        if not new_daily_stats:
            self.context.logger.info("No new daily profit statistics found")
            return existing_data

        self.context.logger.info(
            f"Incremental update: Found {len(new_daily_stats)} new daily profit statistics"
        )

        # Keep stats on/after the last stored timestamp; same-day is allowed so we can detect changes
        filtered_daily_stats = [
            stat
            for stat in new_daily_stats
            if "date" in stat and int(stat["date"]) >= last_data_timestamp
        ]
        if not filtered_daily_stats:
            self.context.logger.info(
                "No newer days or changes to the last stored day; skipping incremental append."
            )
            return existing_data

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

        # Build lookup ONLY for questions present in the new stats
        new_question_titles: Set[str] = set()
        for stat in filtered_daily_stats:
            for participant in stat.get("profitParticipants") or []:
                title = self._extract_title(participant)
                if title:
                    new_question_titles.add(title)

        mech_request_lookup: Dict[str, List[int]] = {}
        if new_question_titles:
            self.context.logger.info(
                f"Building mech request lookup for {len(new_question_titles)} questions in new daily stats"
            )
            new_mech_requests = yield from self._fetch_mech_requests_by_titles(
                agent_safe_address,
                list(new_question_titles),
                block_timestamp_gt=existing_data.last_mech_timestamp,
            )
            new_mech_requests = new_mech_requests if new_mech_requests else []
            for request in new_mech_requests:
                parsed = request.get("parsedRequest", {}) or {}
                title = parsed.get("questionTitle", "")
                ts = int(request.get("blockTimestamp", 0))
                if title and ts:
                    mech_request_lookup.setdefault(title, []).append(ts)
            for title in mech_request_lookup:
                mech_request_lookup[title].sort()
        total_requests_in_lookup = sum(len(v) for v in mech_request_lookup.values())
        self.context.logger.info(
            f"Incremental mech lookup size={len(mech_request_lookup)}, total_requests_in_lookup={total_requests_in_lookup}"
        )

        # Fail-closed (H6): new bets without mech data may indicate subgraph
        # indexing lag rather than true unavailability.  Retry with a lookback
        # window before giving up so that a slow mech subgraph does not
        # freeze the profit-over-time series.
        if new_question_titles and not mech_request_lookup:
            if existing_data.last_mech_timestamp > 0:
                lookback_ts = max(
                    existing_data.last_mech_timestamp - MECH_LOOKBACK_SECONDS, 0
                )
                self.context.logger.info(
                    f"Primary mech query returned no results; retrying with "
                    f"lookback window (watermark {existing_data.last_mech_timestamp} "
                    f"→ {lookback_ts})"
                )
                fallback_requests = yield from self._fetch_mech_requests_by_titles(
                    agent_safe_address,
                    list(new_question_titles),
                    block_timestamp_gt=lookback_ts,
                )
                for request in fallback_requests or []:
                    parsed = request.get("parsedRequest", {}) or {}
                    title = parsed.get("questionTitle", "")
                    ts = int(request.get("blockTimestamp", 0))
                    if title and ts:
                        mech_request_lookup.setdefault(title, []).append(ts)
                for title in mech_request_lookup:
                    mech_request_lookup[title].sort()

            if not mech_request_lookup:
                self.context.logger.warning(
                    "Mech data unavailable for new bets — preserving existing profit data"
                )
                return None

        # Timestamp-based mech-to-bet attribution for new stats
        fees_by_day, placed_delta, unplaced_delta = self._match_mech_requests_to_days(
            filtered_daily_stats, mech_request_lookup
        )

        # Use persisted placed count as base (may be zero after restart)
        prev_placed = getattr(existing_data, "placed_mech_requests_count", 0)

        # Process new daily statistics
        new_data_points = list(existing_data.data_points)  # Copy existing points
        prev_settled = existing_data.settled_mech_requests_count or sum(
            dp.daily_mech_requests for dp in new_data_points
        )
        if replace_last and new_data_points:
            last_dp = new_data_points[-1]
            last_dp_day = last_dp.timestamp // SECONDS_PER_DAY
            if (
                last_dp_day in incoming_days
            ):  # pragma: no cover  # defensive: replace_last guarantees membership
                new_data_points.pop()
                prev_settled -= last_dp.daily_mech_requests
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

            # Look up pre-computed mech fees for this day
            mech_fees, daily_mech_count = self._apply_mech_fees(
                fees_by_day, date_timestamp
            )

            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net
            new_mech_sum += daily_mech_count

            new_data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=date_timestamp,
                    daily_profit_raw=round(daily_profit_raw, 3),
                    daily_profit=round(daily_profit_net, 3),
                    cumulative_profit=round(cumulative_profit, 3),
                    daily_mech_requests=daily_mech_count,
                )
            )

        # R2: Emit data points for mech-only days in the incremental window
        visited_days = {int(s["date"]) for s in filtered_daily_stats if "date" in s}
        for mech_day_ts in sorted(fees_by_day.keys() - visited_days):
            count = fees_by_day[mech_day_ts]
            date_str = datetime.fromtimestamp(mech_day_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
            mech_fees = count * (DEFAULT_MECH_FEE / WEI_IN_ETH)
            new_mech_sum += count
            new_data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=mech_day_ts,
                    daily_profit_raw=0.0,
                    daily_profit=round(-mech_fees, 3),
                    cumulative_profit=0.0,  # recomputed below
                    daily_mech_requests=count,
                )
            )

        # Re-sort and recompute cumulative profit for the full series
        new_data_points.sort(key=lambda dp: dp.timestamp)
        cumulative_profit = 0.0
        for dp in new_data_points:
            cumulative_profit += dp.daily_profit
            dp.cumulative_profit = round(cumulative_profit, 3)

        # Calculate updated settled mech requests count incrementally (monotonic, bounded by total-open)
        settled_mech_requests_count = prev_settled + new_mech_sum
        total_mech_requests = (
            self._total_mech_requests
            if self._total_mech_requests is not None
            else (yield from self._get_total_mech_requests(agent_safe_address))
        )
        max_settled = (
            max((total_mech_requests or 0) - (self._open_market_requests or 0), 0)
            if total_mech_requests is not None
            else None
        )
        pre_bounds = settled_mech_requests_count
        if max_settled is not None:
            settled_mech_requests_count = min(settled_mech_requests_count, max_settled)
        settled_mech_requests_count = max(prev_settled, settled_mech_requests_count)
        self.context.logger.info(
            f"Incremental settled counts: prev={prev_settled}, delta={new_mech_sum}, pre_bounds={pre_bounds}, "
            f"bounded_settled={settled_mech_requests_count}, max_settled={max_settled}"
        )
        # Recompute placed/unplaced totals using persisted counts + deltas
        placed_total = prev_placed + placed_delta
        prev_unplaced = getattr(existing_data, "unplaced_mech_requests_count", 0)
        unplaced_mech_requests_count = prev_unplaced + unplaced_delta
        # Safety clamp to settled - placed if somehow over
        unplaced_mech_requests_count = min(
            unplaced_mech_requests_count,
            max(settled_mech_requests_count - placed_total, 0),
        )
        self._placed_mech_requests_count = placed_total
        self._unplaced_mech_requests_count = unplaced_mech_requests_count
        self.context.logger.info(
            f"Incremental totals => placed_total={placed_total}, unplaced_total={unplaced_mech_requests_count}, "
            f"settled_total={settled_mech_requests_count}"
        )
        self.context.logger.info(
            f"Incremental end snapshot: settled={settled_mech_requests_count}, placed={placed_total}, "
            f"unplaced={unplaced_mech_requests_count}, days={len(new_data_points)}"
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
            ):
                self.context.logger.info(
                    "Last day unchanged (profit/mech/settled); skipping update."
                )
                return existing_data

        # Update watermark
        new_max_ts = max(
            (ts for ts_list in mech_request_lookup.values() for ts in ts_list),
            default=0,
        )
        last_mech_timestamp = max(existing_data.last_mech_timestamp, new_max_ts)

        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(new_data_points),
            data_points=new_data_points,
            settled_mech_requests_count=settled_mech_requests_count,
            unplaced_mech_requests_count=unplaced_mech_requests_count,
            placed_mech_requests_count=self._placed_mech_requests_count,
            includes_unplaced_mech_fees=True,
            last_mech_timestamp=last_mech_timestamp,
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
        self._settled_mech_requests_count = (
            yield from self._calculate_settled_mech_requests(agent_safe_address)
        )

        current_timestamp = self.shared_state.synced_timestamp
        profit_over_time = yield from self._build_profit_over_time_data()
        self._unplaced_mech_requests_count = (
            profit_over_time.unplaced_mech_requests_count if profit_over_time else 0
        )
        self._placed_mech_requests_count = (
            profit_over_time.placed_mech_requests_count
            if profit_over_time
            and hasattr(profit_over_time, "placed_mech_requests_count")
            else 0
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

        winning_trades = [
            item for item in prediction_history.items if item.get("total_payout", 0) > 0
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

    def async_act(self) -> Generator:
        """Do the action."""
        if not self.params.is_agent_performance_summary_enabled:
            self.context.logger.info(
                "Agent performance summary is disabled. Skipping fetch and save."
            )
            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=False,
            )
            yield from self.finish_behaviour(payload)
            return

        if not self._should_update():
            self.context.logger.info("Skipping update - too soon")
            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=False,
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
            self._bet_payout_checker = BetPayoutChecker(achievement_type="omen/payout")

    def async_act(self) -> Generator:
        """Do the action."""

        if not self.params.is_achievement_checker_enabled:
            self.context.logger.info(
                "Achievement checker is disabled. Skipping achievements update."
            )
            payload = UpdateAchievementsPayload(
                sender=self.context.agent_address,
                vote=False,
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
