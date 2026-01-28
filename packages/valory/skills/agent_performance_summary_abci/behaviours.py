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

from datetime import datetime, timedelta, timezone
from typing import Any, Generator, List, Optional, Set, Type, cast

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.requests import (
    APTQueryingBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    Achievements,
    AgentPerformanceMetrics,
    AgentPerformanceSummary,
    AgentDetails,
    AgentPerformanceData,
    PredictionHistory,
    PerformanceMetricsData,
    PerformanceStatsData,
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
from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import PredictionsFetcher
from packages.valory.skills.agent_performance_summary_abci.achievements_checker.bet_payout_checker import BetPayoutChecker


DEFAULT_MECH_FEE = 1e16  # 0.01 ETH
QUESTION_DATA_SEPARATOR = "\u241f"
PREDICT_MARKET_DURATION_DAYS = 4
WXDAI_ADDRESS = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"  # wxDAI on Gnosis Chain

INVALID_ANSWER_HEX = (
    "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)

PERCENTAGE_FACTOR = 100
WEI_IN_ETH = 10**18  # 1 ETH = 10^18 wei
SECONDS_PER_DAY = 86400
NA = "N/A"
UPDATE_INTERVAL = 1800 #30 mins


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
    
    def _should_update(self) -> bool:
        """Check if we should update."""
        if self._last_update_timestamp == 0:
            return True  # First run
        
        time_since_last = self.shared_state.synced_timestamp - self._last_update_timestamp
        return time_since_last >= self._update_interval

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

    def _get_total_mech_requests(self, agent_safe_address: str) -> Generator[None, None, int]:
        """
        Get total number of mech requests (cached).
        
        :param agent_safe_address: The agent's safe address
        :return: Total number of mech requests
        """
        if self._total_mech_requests is not None:
            return self._total_mech_requests
        
        mech_sender = yield from self._fetch_mech_sender(
            agent_safe_address=agent_safe_address,
            timestamp_gt=self.market_open_timestamp,
        )
        
        if not mech_sender or mech_sender.get("totalRequests") is None:
            self._total_mech_requests = 0
            return 0
        
        self._total_mech_requests = int(mech_sender["totalRequests"])
        self.context.logger.info(f"{self._total_mech_requests=}")
        return self._total_mech_requests

    def _get_open_market_requests(self, agent_safe_address: str) -> Generator[None, None, int]:
        """
        Get number of mech requests for open markets (cached).
        
        :param agent_safe_address: The agent's safe address
        :return: Number of open market requests
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
        
        # Get open markets to count pending mech requests
        open_markets = yield from self._fetch_open_markets(
            timestamp_gt=self.market_open_timestamp,
        )
        
        if not open_markets:
            self._open_market_requests = 0
            return 0
        
        # Get titles of open markets
        open_market_titles = {
            q["question"].split(QUESTION_DATA_SEPARATOR, 4)[0] for q in open_markets
        }
        
        # Count requests for still-open markets
        open_market_requests = sum(
            r.get("questionTitle", None) in open_market_titles
            for r in last_four_days_requests
        )
        
        self._open_market_requests = open_market_requests
        self.context.logger.info(f"{self._open_market_requests=}")
        return self._open_market_requests

    def _calculate_settled_mech_requests(self, agent_safe_address: str) -> Generator[None, None, int]:
        """
        Calculate the number of settled mech requests.
        Excludes mech requests for markets that are still open.
        
        :param agent_safe_address: The agent's safe address
        :return: Number of settled mech requests
        """
        # Get total mech requests (uses cache if available)
        total_mech_requests = yield from self._get_total_mech_requests(agent_safe_address)
        
        if not total_mech_requests:
            return 0
        
        # Get open market requests (uses cache if available)
        open_market_requests = yield from self._get_open_market_requests(agent_safe_address)
        
        # Settled = Total - Open
        return total_mech_requests - open_market_requests

    def calculate_roi(self):
        """Calculate the ROI."""
        agent_safe_address = self.synchronized_data.safe_contract_address

        trader_agent = yield from self._fetch_trader_agent(
            agent_safe_address=agent_safe_address,
        )
        if (
            trader_agent is None
            or trader_agent.get("serviceId") is None
            or trader_agent.get("totalTraded") is None
            or trader_agent.get("totalFees") is None
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

        total_costs = (
            int(trader_agent["totalTraded"])
            + int(trader_agent["totalFees"])
            + settled_mech_requests * DEFAULT_MECH_FEE
        )

        if total_costs == 0:
            return None, None

        total_market_payout = int(trader_agent["totalPayout"])
        total_olas_rewards_payout_in_usd = (
            int(staking_service.get("olasRewardsEarned", 0)) * olas_in_usd_price
        ) / WEI_IN_ETH

        partial_roi = (
            (total_market_payout - total_costs) * PERCENTAGE_FACTOR
        ) / total_costs
        final_roi = (
            (total_market_payout + total_olas_rewards_payout_in_usd - total_costs)
            * PERCENTAGE_FACTOR
        ) / total_costs
        self._final_roi = final_roi
        self._partial_roi = partial_roi

        return final_roi, partial_roi

    def _get_prediction_accuracy(self):
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

        bets_on_closed_markets = [
            bet
            for bet in agent_bets_data["bets"]
            if bet.get("fixedProductMarketMaker", {}).get("currentAnswer") is not None
        ]
        total_bets = len(bets_on_closed_markets)
        won_bets = 0

        if total_bets == 0:
            return None
        for bet in bets_on_closed_markets:
            market_answer = bet["fixedProductMarketMaker"]["currentAnswer"]
            bet_answer = bet.get("outcomeIndex")
            if market_answer == INVALID_ANSWER_HEX or bet_answer is None:
                continue
            if int(market_answer, 0) == int(bet_answer):
                won_bets += 1

        win_rate = (won_bets / total_bets) * PERCENTAGE_FACTOR

        return win_rate

    def _format_timestamp(self, timestamp: Optional[str]) -> Optional[str]:
        """Format Unix timestamp to ISO 8601."""
        if not timestamp:
            return None
        try:
            unix_timestamp = int(timestamp)
            dt = datetime.utcfromtimestamp(unix_timestamp)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            self.context.logger.error(f"Error formatting timestamp {timestamp}: {e}")
            return None

    def _fetch_agent_details_data(self) -> Generator:
        """Fetch agent details"""
        
        safe_address = self.synchronized_data.safe_contract_address.lower()
        
        agent_details_raw = yield from self._fetch_agent_details(safe_address)
        
        if not agent_details_raw:
            self.context.logger.warning(f"Could not fetch agent details for {safe_address}")
            return None
        
        return AgentDetails(
            id=agent_details_raw.get("id", safe_address),
            created_at=self._format_timestamp(agent_details_raw.get("blockTimestamp")),
            last_active_at=self._format_timestamp(agent_details_raw.get("lastActive")),
        )

    def _fetch_agent_performance_data(self) -> Generator:
        """Fetch agent performance data"""
        
        safe_address = self.synchronized_data.safe_contract_address.lower()
        trader_agent = yield from self._fetch_trader_agent_performance(safe_address, first=200, skip=0)
        
        if not trader_agent:
            self.context.logger.warning(f"Could not fetch trader agent for performance data")
            return None
        
        # Calculate metrics
        metrics = yield from self._calculate_performance_metrics(trader_agent)
        stats = yield from self._calculate_performance_stats(trader_agent)
        
        return AgentPerformanceData(
            window="lifetime",
            currency="USD",
            metrics=metrics,
            stats=stats,
        )

    def _calculate_performance_metrics(self, trader_agent: dict) -> Generator:
        """Calculate performance metrics from trader agent data."""
        safe_address = self.synchronized_data.safe_contract_address.lower()
        
        total_traded = int(trader_agent.get("totalTraded", 0))
        total_fees = int(trader_agent.get("totalFees", 0))
        total_payout = int(trader_agent.get("totalPayout", 0))
        total_bets = int(trader_agent.get("totalBets", 0))
        
        settled_mech_requests = self._settled_mech_requests_count
        
        # Get total mech requests for funds_used calculation (uses cache)
        total_mech_requests = yield from self._get_total_mech_requests(safe_address)
        
        # Get pending bets to calculate locked amounts
        pending_bets_data = yield from self._fetch_pending_bets(safe_address)
        pending_bets = pending_bets_data.get("bets", []) if pending_bets_data else []
        
        # Calculate pending bet amounts
        pending_bet_amounts = sum(int(bet.get("amount", 0)) for bet in pending_bets)
        
        # Calculate ALL mech costs (for all requests, not just settled)
        all_mech_costs = total_mech_requests * DEFAULT_MECH_FEE
        
        # All-time funds used: traded + fees + ALL mech costs + locked funds
        all_time_funds_used = (
            total_traded + total_fees + all_mech_costs + pending_bet_amounts
        ) / WEI_IN_ETH
        
        # All-time profit: uses only SETTLED mech costs
        settled_mech_costs = settled_mech_requests * DEFAULT_MECH_FEE
        all_time_profit = (
            total_payout - total_traded - total_fees - settled_mech_costs
        ) / WEI_IN_ETH
        
        # Calculate locked funds
        funds_locked_in_markets = pending_bet_amounts / WEI_IN_ETH
        
        # Get available funds
        available_funds = yield from self._fetch_available_funds()
        
        # Convert from percentage (e.g., -56) to decimal (e.g., -0.56)
        roi_decimal = round(self._partial_roi / 100, 2) if self._partial_roi is not None else None
        
        return PerformanceMetricsData(
            all_time_funds_used=round(all_time_funds_used, 2) if all_time_funds_used else None,
            all_time_profit=round(all_time_profit, 2) if all_time_profit else None,
            funds_locked_in_markets=round(funds_locked_in_markets, 2) if funds_locked_in_markets else None,
            available_funds=round(available_funds, 2) if available_funds else None,
            roi=roi_decimal,
            settled_mech_request_count=self._settled_mech_requests_count
        )


    def _fetch_available_funds(self) -> Generator[None, None, Optional[float]]:
        """Fetch available funds (wxDAI + xDAI balance)."""
        safe_contract_address = self.synchronized_data.safe_contract_address
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=WXDAI_ADDRESS,
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
            self.context.logger.error("Invalid balance response: token or wallet is None")
            return None
            
        token_balance = token / WEI_IN_ETH
        wallet_balance = wallet / WEI_IN_ETH
        available_funds = token_balance + wallet_balance
        return available_funds

    def _calculate_performance_stats(self, trader_agent: dict) -> Generator:
        """Calculate performance statistics."""
        total_bets = int(trader_agent.get("totalBets", 0))
        accuracy = yield from self._get_prediction_accuracy()
        
        return PerformanceStatsData(
            predictions_made=total_bets,
            prediction_accuracy=round(accuracy / 100, 2) if accuracy is not None else None,
        )

    def _fetch_prediction_history(self):
        """Fetch latest 200 predictions - platform-aware."""
        safe_address = self.synchronized_data.safe_contract_address.lower()
        
        try:
            # Use platform-specific fetcher
            if self.params.is_running_on_polymarket:
                from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import PolymarketPredictionsFetcher
                fetcher = PolymarketPredictionsFetcher(self.context, self.context.logger)
            else:
                fetcher = PredictionsFetcher(self.context, self.context.logger)
            
            result = fetcher.fetch_predictions(
                safe_address=safe_address,
                first=200,
                skip=0,
                status_filter=None
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


    def _calculate_mech_fees_for_day(self, profit_participants: list, mech_request_lookup: dict) -> tuple[float, int]:
        """
        Calculate mech fees for a specific day based on profit participants using cached lookup.
        
        :param profit_participants: List of profit participants for the day
        :param mech_request_lookup: Cached lookup map of question_title -> count
        :return: Tuple of (total_mech_fees, mech_request_count)
        """
        if not profit_participants:
            return 0.0, 0
        
        # Extract question titles from profit participants and count mech requests
        mech_fee_count = 0
        for participant in profit_participants:
            question = participant.get("question", "")
            if question:
                # Split by separator and take the first part (question title)
                title = question.split(QUESTION_DATA_SEPARATOR)[0]
                if title:
                    # Use cached lookup instead of querying
                    mech_fee_count += mech_request_lookup.get(title, 0)
        
        # Calculate fees: 0.01 xDAI per request
        total_mech_fees = mech_fee_count * (DEFAULT_MECH_FEE / WEI_IN_ETH)
        
        return total_mech_fees, mech_fee_count

    def _build_mech_request_lookup(self, agent_safe_address: str) -> Generator[None, None, dict]:
        """
        Build a lookup map of question titles to mech request counts.
        
        :param agent_safe_address: The agent's safe address
        :return: Dictionary mapping question titles to request counts
        """
        # Fetch all mech requests for this agent
        if self._mech_request_lookup is not None:
            self.context.logger.info(f"Using cached mech request lookup with {len(self._mech_request_lookup)} unique questions")
            return self._mech_request_lookup
        
        all_mech_requests = yield from self._fetch_all_mech_requests(agent_safe_address)
        
        if not all_mech_requests:
            self.context.logger.warning("No mech requests found for agent")
            return None
        
        # Build lookup map: question_title -> count
        lookup = {}
        for request in all_mech_requests:
            title = request.get("questionTitle", "")
            if title:
                lookup[title] = lookup.get(title, 0) + 1
        
        self.context.logger.info(f"Built mech request lookup with {len(lookup)} unique questions, {len(all_mech_requests)} total requests")
        self._mech_request_lookup = lookup
        return lookup

    def _build_profit_over_time_data(self) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """
        Build profit over time data with efficient backfill and incremental update strategy.
        
        :return: ProfitOverTimeData or None
        """
        agent_safe_address = self.synchronized_data.safe_contract_address.lower()
        current_timestamp = self.shared_state.synced_timestamp
        
        # Check if we have existing profit data
        existing_summary = self.shared_state.read_existing_performance_summary()
        existing_profit_data = existing_summary.profit_over_time
        
        # Determine if this is initial backfill or incremental update
        # We need to build the profit over time chart again after the hotfix so we check for settled_mech_request_count field in agent performance metrics, as it was newly added in the hotfix
        if not existing_profit_data or not existing_profit_data.data_points:
            # INITIAL BACKFILL - First time or no existing data
            self.context.logger.info("Performing initial profit over time backfill...")
            return (yield from self._perform_initial_backfill(agent_safe_address, current_timestamp))
        elif (existing_summary.agent_performance and 
              existing_summary.agent_performance.metrics and 
              not getattr(existing_summary.agent_performance.metrics, 'settled_mech_request_count', None)):
            # INITIAL BACKFILL - Missing settled_mech_request_count field (hotfix)
            self.context.logger.info("Performing initial profit over time backfill due to missing settled_mech_request_count...")
            return (yield from self._perform_initial_backfill(agent_safe_address, current_timestamp))
        else:
            # INCREMENTAL UPDATE - Check if we need to add new days
            self.context.logger.info("Checking for incremental profit over time updates...")
            return (yield from self._perform_incremental_update(agent_safe_address, current_timestamp, existing_profit_data))

    def _perform_initial_backfill(self, agent_safe_address: str, current_timestamp: int) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """Perform initial backfill of all profit data."""
        # Fetch ALL daily profit statistics from creation to now
        daily_stats = yield from self._fetch_daily_profit_statistics(
            agent_safe_address, 0
        )
        
        if daily_stats is None:
            self.context.logger.error("Failed to fetch daily profit statistics")
            return None
        
        if not daily_stats:
            self.context.logger.info("No daily profit statistics found - agent may not have any trading activity yet")
            return ProfitOverTimeData(
                last_updated=current_timestamp,
                total_days=0,
                data_points=[],
                settled_mech_requests_count=0
            )
        
        self.context.logger.info(f"Initial backfill: Found {len(daily_stats)} daily profit statistics")
        
        # Build mech request lookup ONCE for all historical data
        mech_request_lookup = yield from self._build_mech_request_lookup(agent_safe_address)
        if not mech_request_lookup:
            self.context.logger.warning("No mech requests found")
            return ProfitOverTimeData(
                last_updated=current_timestamp,
                total_days=0,
                data_points=[],
                settled_mech_requests_count=0
            )
        
        # Process all daily statistics
        data_points = []
        cumulative_profit = 0.0
        
        for stat in daily_stats:
            date_timestamp = int(stat["date"])
            date_str = datetime.utcfromtimestamp(date_timestamp).strftime("%Y-%m-%d")
            daily_profit_raw = float(stat.get("dailyProfit", 0)) / WEI_IN_ETH
            
            # Calculate mech fees using cached lookup
            profit_participants = stat.get("profitParticipants", [])
            mech_fees, daily_mech_count = self._calculate_mech_fees_for_day(profit_participants, mech_request_lookup)
            
            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net
            
            data_points.append(ProfitDataPoint(
                date=date_str,
                timestamp=date_timestamp,
                daily_profit=round(daily_profit_net, 3),
                cumulative_profit=round(cumulative_profit, 3),
                daily_mech_requests=daily_mech_count
            ))
        
        # Calculate total settled mech requests from all data points
        settled_mech_requests_count = sum(point.daily_mech_requests for point in data_points)
        
        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(data_points),
            data_points=data_points,
            settled_mech_requests_count=settled_mech_requests_count
        )

    def _perform_incremental_update(self, agent_safe_address: str, current_timestamp: int, existing_data: ProfitOverTimeData) -> Generator[None, None, Optional[ProfitOverTimeData]]:
        """Perform incremental update for new days only."""
        # Check if we're on a new day
        current_day = current_timestamp // SECONDS_PER_DAY
        last_updated_day = existing_data.last_updated // SECONDS_PER_DAY
        
        if current_day == last_updated_day:
            # Same day, no update needed
            self.context.logger.info("Profit over time data is up to date (same day)")
            return existing_data
        
        # Get the timestamp of the last data point to fetch only new data
        last_data_timestamp = existing_data.data_points[-1].timestamp if existing_data.data_points else 0
        
        # Fetch only NEW daily profit statistics (after last timestamp)
        new_daily_stats = yield from self._fetch_daily_profit_statistics(
            agent_safe_address, last_data_timestamp + 1
        )
        
        if new_daily_stats is None:
            self.context.logger.error("Failed to fetch new daily profit statistics")
            return existing_data
        
        if not new_daily_stats:
            self.context.logger.info("No new daily profit statistics found")
            return existing_data 
        
        self.context.logger.info(f"Incremental update: Found {len(new_daily_stats)} new daily profit statistics")
        
        # Build lookup ONLY for questions in NEW daily stats
        new_question_titles = set()
        for stat in new_daily_stats:
            for participant in stat.get("profitParticipants", []):
                question = participant.get("question", "")
                if question:
                    title = question.split(QUESTION_DATA_SEPARATOR)[0]
                    if title:
                        new_question_titles.add(title)
        
        if not new_question_titles:
            self.context.logger.info("No new questions in incremental update")
            # Update timestamp but keep existing data
            existing_data.last_updated = current_timestamp
            return existing_data
        
        self.context.logger.info(f"Building mech request lookup for {len(new_question_titles)} questions in new daily stats")
        new_mech_requests = yield from self._fetch_mech_requests_by_titles(agent_safe_address, list(new_question_titles))
        
        mech_request_lookup = {}
        if new_mech_requests:
            for request in new_mech_requests:
                title = request.get("questionTitle", "")
                if title:
                    mech_request_lookup[title] = mech_request_lookup.get(title, 0) + 1
        
        # Process new daily statistics
        new_data_points = list(existing_data.data_points)  # Copy existing points
        cumulative_profit = existing_data.data_points[-1].cumulative_profit if existing_data.data_points else 0.0
        
        for stat in new_daily_stats:
            date_timestamp = int(stat["date"])
            date_str = datetime.utcfromtimestamp(date_timestamp).strftime("%Y-%m-%d")
            daily_profit_raw = float(stat.get("dailyProfit", 0)) / WEI_IN_ETH
            
            # Calculate mech fees using lookup for this day only
            profit_participants = stat.get("profitParticipants", [])
            mech_fees, daily_mech_count = self._calculate_mech_fees_for_day(profit_participants, mech_request_lookup)
            
            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net
            
            new_data_points.append(ProfitDataPoint(
                date=date_str,
                timestamp=date_timestamp,
                daily_profit=round(daily_profit_net, 3),
                cumulative_profit=round(cumulative_profit, 3),
                daily_mech_requests=daily_mech_count
            ))
        
        # Calculate updated settled mech requests count from all data points
        settled_mech_requests_count = sum(point.daily_mech_requests for point in new_data_points)
        
        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(new_data_points),
            data_points=new_data_points,
            settled_mech_requests_count=settled_mech_requests_count
        )

    def _update_profit_over_time_storage(self) -> Generator[None, None, None]:
        """Update profit over time data in storage."""
        
        # Check if we need to update (daily check)
        existing_summary = self.shared_state.read_existing_performance_summary()
        current_timestamp = self.shared_state.synced_timestamp
        
        # Check if profit_over_time exists and is up to date
        if existing_summary.profit_over_time:
            last_updated = existing_summary.profit_over_time.last_updated
            current_day = current_timestamp // 86400  # Convert to days
            last_updated_day = last_updated // 86400
            
            if current_day == last_updated_day:
                # Same day, no update needed
                self.context.logger.info("Profit over time data is up to date")
                return
        
        # Build new profit over time data
        self.context.logger.info("Updating profit over time data...")
        profit_data = yield from self._build_profit_over_time_data()
        
        if profit_data:
            # Update the summary with new profit data
            existing_summary.profit_over_time = profit_data
            self.shared_state.overwrite_performance_summary(existing_summary)
            self.context.logger.info(f"Updated profit over time data with {profit_data.total_days} days")
        else:
            self.context.logger.warning("Failed to build profit over time data")

    def _fetch_agent_performance_summary(self) -> Generator:
        """Fetch the agent performance summary"""
        self._total_mech_requests = None
        self._open_market_requests = None
        self._mech_request_lookup = None
        
        agent_safe_address = self.synchronized_data.safe_contract_address
        self._settled_mech_requests_count = yield from self._calculate_settled_mech_requests(agent_safe_address)
        
        current_timestamp = self.shared_state.synced_timestamp
        
        final_roi, partial_roi = yield from self.calculate_roi()

        metrics = []

        partial_roi_string = f"{round(partial_roi)}%" if partial_roi is not None else NA
        metrics.append(
            AgentPerformanceMetrics(
                name="Total ROI",
                is_primary=True,
                description=f"Total return on investment including staking rewards. Partial ROI (Prediction market activity only): <b>{partial_roi_string}</b>",
                value=f"{round(final_roi)}%" if final_roi is not None else NA,
            )
        )

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
        profit_over_time = yield from self._build_profit_over_time_data()

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
        """Save the agent performance summary to a file."""
        existing_data = self.shared_state.read_existing_performance_summary()
        agent_performance_summary.agent_behavior = existing_data.agent_behavior
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

            success = all(
                metric.value != NA for metric in self._agent_performance_summary.metrics
            )
            if not success:
                self.context.logger.warning(
                    "Agent performance summary could not be fetched. Saving default values"
                )
            self._save_agent_performance_summary(self._agent_performance_summary)

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
            self._bet_payout_checker = BetPayoutChecker(achievement_type="polystrat/payout")
        else:
            self._bet_payout_checker = BetPayoutChecker(achievement_type="omen/payout")

    def async_act(self) -> Generator:
        """Do the action."""

        agent_performance_summary = self.shared_state.read_existing_performance_summary()

        achievements = agent_performance_summary.achievements
        if achievements is None:
            achievements = Achievements()
            agent_performance_summary.achievements = achievements

        achievements_updated = False
        achievements_updated = self._bet_payout_checker.update_achievements(
            achievements=agent_performance_summary.achievements,
            prediction_history=agent_performance_summary.prediction_history
        )

        if achievements_updated:
            self.context.logger.info(
                "Agent achievements updated."
            )
            self.shared_state.overwrite_performance_summary(agent_performance_summary)
        else:
            self.context.logger.info(
                "Agent achievements not updated."
            )

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
