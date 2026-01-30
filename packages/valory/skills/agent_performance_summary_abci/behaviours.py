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

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Generator, Optional, Set, Tuple, Type, cast

from packages.valory.contracts.erc20.contract import ERC20
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


DEFAULT_MECH_FEE = 1e16  # 0.01 ETH
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

INVALID_ANSWER_HEX = (
    "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)

PERCENTAGE_FACTOR = 100
WEI_IN_ETH = 10**18  # 1 ETH = 10^18 wei
SECONDS_PER_DAY = 86400
NA = "N/A"
UPDATE_INTERVAL = 1800  # 30 mins
TX_HISTORY_DEPTH = 25  # match healthcheck slice length
POLYMARKET_ACHIEVEMENT_ROI_THRESHOLD = 1.7
POLYMARKET_ACHIEVEMENT_DESCRIPTION_TEMPLATE = (
    "My Polystrat agent just closed a Polymarket trade at {roi}\u00d7 ROI. Pretty impressive! \U0001f680\n"
    "Curious to see how around-the-clock, autonomous trading with Polystrat on Pearl works and spin up an agent yourself?\n"
    "Check it out\U0001f447\n"
    "{{achievement_url}}\n"
    "#PolystratOnPearl"
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
        self._mech_request_lookup: Optional[dict] = None
        self._update_interval: int = UPDATE_INTERVAL
        self._last_update_timestamp: int = 0
        self._settled_mech_requests_count: int = 0
        self._unplaced_mech_requests_count: int = 0
        self._placed_titles: Set[str] = set()

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

        total_traded_settled = int(trader_agent.get("totalTradedSettled", 0))
        total_fees_settled = int(trader_agent.get("totalFeesSettled", 0))

        settled_mech_costs = settled_mech_requests * DEFAULT_MECH_FEE
        total_costs = total_traded_settled + total_fees_settled + settled_mech_costs

        if total_costs == 0:
            return None, None

        total_market_payout = int(trader_agent.get("totalPayout", 0))
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
        placed_mech_requests = sum(
            (self._mech_request_lookup or {}).get(title, 0)
            for title in self._placed_titles
        )
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
                round(all_time_funds_used, 2) if all_time_funds_used else None
            ),
            all_time_profit=round(all_time_profit, 2) if all_time_profit else None,
            funds_locked_in_markets=(
                round(funds_locked_in_markets, 2) if funds_locked_in_markets else None
            ),
            available_funds=round(available_funds, 2) if available_funds else None,
            roi=roi_decimal,
            # Settled mech requests cover placed + unplaced, excluding open markets.
            settled_mech_request_count=self._settled_mech_requests_count,
            total_mech_request_count=total_mech_requests,
            open_mech_request_count=open_mech_requests,
            placed_mech_request_count=placed_mech_requests,
            unplaced_mech_request_count=unplaced_mech_requests,
        )

    def _get_usdc_equivalent_for_pol(
        self, pol_balance_wei: int
    ) -> Generator[None, None, Optional[float]]:
        """Convert POL balance to USDC equivalent using LiFi quote."""
        try:
            safe_address = self.synchronized_data.safe_contract_address

            # Build LiFi quote request URL
            params = {
                "fromChain": str(POLYGON_CHAIN_ID),
                "toChain": str(POLYGON_CHAIN_ID),
                "fromToken": POLYGON_NATIVE_TOKEN_ADDRESS,
                "toToken": USDC_E_ADDRESS,
                "fromAmount": str(pol_balance_wei),
                "fromAddress": safe_address,
                "toAddress": safe_address,
            }

            # Construct URL with query parameters
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            url = f"{LIFI_QUOTE_URL}?{query_string}"

            self.context.logger.info("Fetching LiFi quote for POL→USDC conversion")

            # Make HTTP request to LiFi API
            response = yield from self.get_http_response(
                method="GET",
                url=url,
            )

            if response.status_code != 200:
                self.context.logger.error(
                    f"LiFi API returned status {response.status_code}"
                )
                return None

            # Parse response
            response_data = json.loads(response.body.decode())

            # Extract USDC amount from quote
            to_amount_wei = response_data.get("estimate", {}).get("toAmount")

            if not to_amount_wei:
                self.context.logger.error("No toAmount in LiFi quote response")
                return None

            # Convert USDC wei to standard units (6 decimals)
            usdc_amount = int(to_amount_wei) / USDC_DECIMALS_DIVISOR

            self.context.logger.info(
                f"POL→USDC conversion: {pol_balance_wei / WEI_IN_ETH:.4f} POL ≈ {usdc_amount:.2f} USDC"
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

    def _calculate_mech_fees_for_day(
        self, profit_participants: list, mech_request_lookup: dict
    ) -> tuple[float, int]:
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

    def _collect_placed_titles(self, daily_stats: list) -> Set[str]:
        """Collect all question titles that have bets (profit participants) in given stats."""
        placed_titles: Set[str] = set()
        for stat in daily_stats:
            for participant in stat.get("profitParticipants", []):
                question = participant.get("question", "")
                if question:
                    title = question.split(QUESTION_DATA_SEPARATOR)[0]
                    if title:
                        placed_titles.add(title)
        return placed_titles

    def _apply_mech_fees(
        self,
        profit_participants: list,
        mech_request_lookup: Dict[str, int],
        extra_fees_by_day: Dict[int, int],
        date_timestamp: int,
    ) -> Tuple[float, int]:
        """Calculate mech fees for a day: lookup-based fees plus any precomputed extra buckets."""
        mech_fees, mech_count = self._calculate_mech_fees_for_day(
            profit_participants, mech_request_lookup
        )

        extra_count = extra_fees_by_day.get(date_timestamp, 0)
        if extra_count:
            mech_fees += extra_count * (DEFAULT_MECH_FEE / WEI_IN_ETH)
            mech_count += extra_count
        return mech_fees, mech_count

    def _evenly_distribute_requests(
        self, total_requests: int, days: list[int]
    ) -> Dict[int, int]:
        """Evenly distribute request count across given day timestamps."""
        if total_requests <= 0 or not days:
            return {}
        per_day = total_requests // len(days)
        remainder = total_requests % len(days)
        buckets: Dict[int, int] = {}
        for idx, day_ts in enumerate(sorted(days)):
            alloc = per_day + (1 if idx < remainder else 0)
            if alloc:
                buckets[day_ts] = alloc
        return buckets

    def _build_multi_bet_allocations(
        self, daily_stats: list, mech_request_lookup: Dict[str, int]
    ) -> Tuple[Dict[int, int], Set[str]]:
        """For markets appearing on multiple days, split mech requests evenly across those days.

        :param daily_stats: List of daily statistics
        :param mech_request_lookup: Dictionary mapping question titles to request counts
        :return: Tuple of (allocations_by_day, titles_allocated)
        """
        title_days: Dict[str, list] = {}
        for stat in daily_stats:
            day_ts = int(stat["date"])
            titles = {
                participant.get("question", "").split(QUESTION_DATA_SEPARATOR)[0]
                for participant in stat.get("profitParticipants", [])
                if participant.get("question", "")
            }
            for title in titles:
                if title:
                    title_days.setdefault(title, []).append(day_ts)

        allocations: Dict[int, int] = {}
        titles_allocated: Set[str] = set()

        for title, days in title_days.items():
            if len(days) <= 1:
                continue
            total_requests = mech_request_lookup.get(title, 0)
            if total_requests <= 0:
                continue
            titles_allocated.add(title)
            allocations_for_title = self._evenly_distribute_requests(
                total_requests, days
            )
            for day_ts, count in allocations_for_title.items():
                allocations[day_ts] = allocations.get(day_ts, 0) + count

        return allocations, titles_allocated

    def _compute_mech_fee_buckets(
        self,
        daily_stats: list,
        mech_request_lookup: Dict[str, int],
        placed_titles: Set[str],
        existing_unplaced_count: int,
    ) -> Tuple[Dict[int, int], Dict[str, int], int]:
        """Build per-day mech fee buckets for unplaced requests and multi-bet markets.

        :param daily_stats: List of daily statistics
        :param mech_request_lookup: Dictionary mapping question titles to request counts
        :param placed_titles: Set of titles that have been placed
        :param existing_unplaced_count: Count of existing unplaced requests
        :return: Tuple of (extra_fees_by_day, filtered_lookup, unplaced_allocated)
        """
        # Unplaced requests (no bets)
        total_mech_requests = self._total_mech_requests or sum(
            (mech_request_lookup or {}).values()
        )
        open_requests = self._open_market_requests or 0
        placed_requests_count = sum(
            (mech_request_lookup or {}).get(t, 0) for t in placed_titles
        )
        remaining_unplaced = max(
            total_mech_requests
            - open_requests
            - placed_requests_count
            - existing_unplaced_count,
            0,
        )

        extra_fees_by_day: Dict[int, int] = {}
        unplaced_buckets: Dict[int, int] = {}
        if daily_stats and remaining_unplaced > 0:
            days = [int(stat["date"]) for stat in daily_stats]
            unplaced_buckets = self._evenly_distribute_requests(
                remaining_unplaced, days
            )
            extra_fees_by_day.update(unplaced_buckets)

        # Multi-bet allocations (split across days) and exclude from lookup to avoid double count
        multi_allocations, allocated_titles = self._build_multi_bet_allocations(
            daily_stats, mech_request_lookup
        )
        for day_ts, count in multi_allocations.items():
            extra_fees_by_day[day_ts] = extra_fees_by_day.get(day_ts, 0) + count

        filtered_lookup = {
            k: v
            for k, v in (mech_request_lookup or {}).items()
            if k not in allocated_titles
        }
        unplaced_allocated = sum(unplaced_buckets.values())
        return extra_fees_by_day, filtered_lookup, unplaced_allocated

    def _build_mech_request_lookup(
        self, agent_safe_address: str
    ) -> Generator[None, None, dict]:
        """Build a lookup map of question titles to mech request counts.

        :param agent_safe_address: The agent's safe address
        :return: Dictionary mapping question titles to request counts
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

        # Build lookup map: question_title -> count
        lookup: Dict[str, int] = {}
        for request in all_mech_requests:
            title = (request.get("parsedRequest", {}) or {}).get("questionTitle", "")
            if title:
                lookup[title] = lookup.get(title, 0) + 1

        self.context.logger.info(
            f"Built mech request lookup with {len(lookup)} unique questions, {len(all_mech_requests)} total requests"
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

        # Build mech request lookup ONCE for all historical data
        mech_request_lookup = yield from self._build_mech_request_lookup(
            agent_safe_address
        )
        if not mech_request_lookup:
            self.context.logger.warning("No mech requests found")
            return ProfitOverTimeData(
                last_updated=current_timestamp,
                total_days=0,
                data_points=[],
                settled_mech_requests_count=0,
                includes_unplaced_mech_fees=True,
            )

        # Build mech fee buckets (unplaced + multi-bet) and filtered lookup
        placed_titles = self._collect_placed_titles(daily_stats)
        self._placed_titles = set(placed_titles)
        merged_extra_fees_by_day, filtered_lookup, unplaced_count = (
            self._compute_mech_fee_buckets(
                daily_stats,
                mech_request_lookup,
                placed_titles,
                existing_unplaced_count=0,
            )
        )

        # Process all daily statistics
        data_points = []
        cumulative_profit = 0.0

        for stat in daily_stats:
            date_timestamp = int(stat["date"])
            date_str = datetime.utcfromtimestamp(date_timestamp).strftime("%Y-%m-%d")
            daily_profit_raw = float(stat.get("dailyProfit", 0)) / WEI_IN_ETH

            # Calculate mech fees (placed + unplaced) using cached lookup
            profit_participants = stat.get("profitParticipants", [])
            mech_fees, daily_mech_count = self._apply_mech_fees(
                profit_participants,
                filtered_lookup,
                merged_extra_fees_by_day,
                date_timestamp,
            )

            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net

            data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=date_timestamp,
                    daily_profit=round(daily_profit_net, 3),
                    cumulative_profit=round(cumulative_profit, 3),
                    daily_mech_requests=daily_mech_count,
                )
            )

        # Calculate total settled mech requests from all data points
        settled_mech_requests_count = sum(
            point.daily_mech_requests for point in data_points
        )
        unplaced_mech_requests_count = unplaced_count

        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(data_points),
            data_points=data_points,
            settled_mech_requests_count=settled_mech_requests_count,
            unplaced_mech_requests_count=unplaced_mech_requests_count,
            includes_unplaced_mech_fees=True,
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

        if current_day == last_updated_day:
            # Same day, no update needed
            self.context.logger.info("Profit over time data is up to date (same day)")
            return existing_data

        # Get the timestamp of the last data point to fetch only new data
        last_data_timestamp = (
            existing_data.data_points[-1].timestamp if existing_data.data_points else 0
        )

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

        self.context.logger.info(
            f"Incremental update: Found {len(new_daily_stats)} new daily profit statistics"
        )

        placed_titles = self._collect_placed_titles(new_daily_stats)
        # Track all titles that have had bets so metrics can report placed mech requests.
        self._placed_titles.update(placed_titles)

        # Mech requests lookup (use cached full lookup if available, else fetch all)
        if self._mech_request_lookup is None:
            self.context.logger.info("Building mech request lookup (incremental, full)")
            self._mech_request_lookup = yield from self._build_mech_request_lookup(
                agent_safe_address
            )
        mech_request_lookup = self._mech_request_lookup or {}

        already_counted = (
            existing_data.unplaced_mech_requests_count
            if hasattr(existing_data, "unplaced_mech_requests_count")
            else 0
        )
        combined_extra_fees_by_day, filtered_lookup, unplaced_count = (
            self._compute_mech_fee_buckets(
                new_daily_stats,
                mech_request_lookup,
                placed_titles,
                existing_unplaced_count=already_counted,
            )
        )

        # Process new daily statistics
        new_data_points = list(existing_data.data_points)  # Copy existing points
        cumulative_profit = (
            existing_data.data_points[-1].cumulative_profit
            if existing_data.data_points
            else 0.0
        )

        for stat in new_daily_stats:
            date_timestamp = int(stat["date"])
            date_str = datetime.utcfromtimestamp(date_timestamp).strftime("%Y-%m-%d")
            daily_profit_raw = float(stat.get("dailyProfit", 0)) / WEI_IN_ETH

            # Calculate mech fees using lookup for this day only
            profit_participants = stat.get("profitParticipants", [])
            mech_fees, daily_mech_count = self._apply_mech_fees(
                profit_participants,
                filtered_lookup,
                combined_extra_fees_by_day,
                date_timestamp,
            )

            daily_profit_net = daily_profit_raw - mech_fees
            cumulative_profit += daily_profit_net

            new_data_points.append(
                ProfitDataPoint(
                    date=date_str,
                    timestamp=date_timestamp,
                    daily_profit=round(daily_profit_net, 3),
                    cumulative_profit=round(cumulative_profit, 3),
                    daily_mech_requests=daily_mech_count,
                )
            )

        # Calculate updated settled mech requests count from all data points
        settled_mech_requests_count = sum(
            point.daily_mech_requests for point in new_data_points
        )
        unplaced_mech_requests_count = unplaced_count + (
            existing_data.unplaced_mech_requests_count
            if hasattr(existing_data, "unplaced_mech_requests_count")
            else 0
        )

        return ProfitOverTimeData(
            last_updated=current_timestamp,
            total_days=len(new_data_points),
            data_points=new_data_points,
            settled_mech_requests_count=settled_mech_requests_count,
            unplaced_mech_requests_count=unplaced_mech_requests_count,
            includes_unplaced_mech_fees=True,
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
            self.context.logger.info(
                f"Updated profit over time data with {profit_data.total_days} days"
            )
        else:
            self.context.logger.warning("Failed to build profit over time data")

    def _fetch_agent_performance_summary(self) -> Generator[None, None, None]:
        """Fetch the agent performance summary"""
        self._total_mech_requests = None
        self._open_market_requests = None
        self._mech_request_lookup = None
        self._placed_titles = set()

        agent_safe_address = self.synchronized_data.safe_contract_address
        self._settled_mech_requests_count = (
            yield from self._calculate_settled_mech_requests(agent_safe_address)
        )

        current_timestamp = self.shared_state.synced_timestamp
        profit_over_time = yield from self._build_profit_over_time_data()
        if profit_over_time and hasattr(
            profit_over_time, "unplaced_mech_requests_count"
        ):
            self._unplaced_mech_requests_count = (
                profit_over_time.unplaced_mech_requests_count
            )
        else:
            self._unplaced_mech_requests_count = 0

        if self._unplaced_mech_requests_count == 0:
            existing_summary = self.shared_state.read_existing_performance_summary()
            if (
                existing_summary
                and existing_summary.profit_over_time
                and hasattr(
                    existing_summary.profit_over_time, "unplaced_mech_requests_count"
                )
            ):
                self._unplaced_mech_requests_count = (
                    existing_summary.profit_over_time.unplaced_mech_requests_count or 0
                )

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

            if self._agent_performance_summary is not None:
                success = all(
                    metric.value != NA
                    for metric in self._agent_performance_summary.metrics
                )
                if not success:
                    self.context.logger.warning(
                        "Agent performance summary could not be fetched. Saving default values"
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
