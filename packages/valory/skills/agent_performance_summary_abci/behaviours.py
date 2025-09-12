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

"""This module contains the behaviour of the skill which is responsible for agent performance summary file updation."""

from datetime import datetime, timedelta, timezone
from typing import Any, Generator, Optional, Set, Type, cast

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.requests import (
    APTQueryingBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AgentPerformanceSummary,
    SharedState,
)
from packages.valory.skills.agent_performance_summary_abci.payloads import (
    FetchPerformanceDataPayload,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
    FetchPerformanceDataRound,
)


DEFAULT_MECH_FEE = 1e16  # 0.01 ETH
QUESTION_DATA_SEPARATOR = "\u241f"
PREDICT_MARKET_DURATION_DAYS = 4

INVALID_ANSWER_HEX = (
    "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)

PERCENTAGE_FACTOR = 100
WEI_IN_ETH = 10**18  # 1 ETH = 10^18 wei


class FetchPerformanceSummaryBehaviour(
    APTQueryingBehaviour,
):
    """A behaviour to fetch and store the agent performance summary file."""

    matching_round = FetchPerformanceDataRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._agent_performance_summary: Optional[AgentPerformanceSummary] = None

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

    def calculate_roi(self):
        """Calculate the ROI."""
        agent_id = self.context.agent_address.lower()

        mech_sender = yield from self._fetch_mech_sender(
            agent_id=agent_id,
            timestamp_gt=self.market_open_timestamp,
        )
        if mech_sender and (
            mech_sender.get("totalRequests") is None
            or mech_sender.get("requests") is None
        ):
            self.context.logger.warning(
                f"Mech sender data not found or incomplete for {agent_id=} and {mech_sender=}"
            )
            return None, None

        trader_agent = yield from self._fetch_trader_agent(
            agent_id=agent_id,
        )
        if (
            trader_agent is None
            or trader_agent.get("serviceId") is None
            or trader_agent.get("totalTraded") is None
            or trader_agent.get("totalFees") is None
            or trader_agent.get("totalPayout") is None
        ):
            self.context.logger.warning(
                f"Trader agent data not found or incomplete for {agent_id=} and {trader_agent=}"
            )
            return None, None

        open_markets = yield from self._fetch_open_markets(
            timestamp_gt=self.market_open_timestamp,
        )
        if open_markets is None:
            self.context.logger.warning("Open markets data not found")
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

        total_mech_requests = int(mech_sender["totalRequests"]) if mech_sender else 0

        last_four_days_requests = mech_sender["requests"] if mech_sender else []

        open_market_titles = {
            q["question"].split(QUESTION_DATA_SEPARATOR, 4)[0] for q in open_markets
        }

        # Subtract requests for still-open markets
        requests_to_subtract = sum(
            r.get("questionTitle", None) in open_market_titles
            for r in last_four_days_requests
        )

        total_costs = (
            int(trader_agent["totalTraded"])
            + int(trader_agent["totalFees"])
            + (total_mech_requests - requests_to_subtract) * DEFAULT_MECH_FEE
        )

        if total_costs == 0:
            return None, None

        total_market_payout = int(trader_agent["totalPayout"])
        total_olas_rewards_payout_in_usd = (
            int(staking_service.get("olasRewardsEarned", 0)) * olas_in_usd_price
        ) // WEI_IN_ETH

        partial_roi = (
            (total_market_payout - total_costs) * PERCENTAGE_FACTOR
        ) // total_costs
        final_roi = (
            (total_market_payout + total_olas_rewards_payout_in_usd - total_costs)
            * PERCENTAGE_FACTOR
        ) // total_costs

        return final_roi, partial_roi

    def _get_prediction_accuracy(self):
        """Get the prediction accuracy."""

        agent_id = self.context.agent_address.lower()
        agent_bets_data = yield from self._fetch_trader_agent_bets(
            agent_id=agent_id,
        )
        if agent_bets_data is None or len(agent_bets_data["bets"]) == 0:
            return None

        bets_on_closed_markets = [
            bet
            for bet in agent_bets_data["bets"]
            if bet["fixedProductMarketMaker"]["currentAnswer"] is not None
        ]
        total_bets = len(bets_on_closed_markets)
        won_bets = 0

        for bet in bets_on_closed_markets:
            market_answer = bet["fixedProductMarketMaker"]["currentAnswer"]
            bet_answer = bet["outcomeIndex"]
            if market_answer == INVALID_ANSWER_HEX:
                continue
            if int(market_answer, 0) == int(bet_answer):
                won_bets += 1

        win_rate = (won_bets / total_bets) * 100

        return win_rate

    def _fetch_agent_performance_summary(self) -> Generator:
        """Fetch the agent performance summary"""
        current_timestamp = self.shared_state.synced_timestamp

        final_roi, partial_roi = yield from self.calculate_roi() or (None, None)

        metrics = []
        if final_roi is not None:
            metrics.append(
                {
                    "name": "Total ROI",
                    "is_primary": True,
                    "description": "With staking rewards included",
                    "value": f"{final_roi}%",
                }
            )
        if partial_roi is not None:
            metrics.append(
                {
                    "name": "Partial ROI",
                    "is_primary": False,
                    "description": "Clean ROI without staking rewards",
                    "value": f"{partial_roi}%",
                }
            )

        accuracy = yield from self._get_prediction_accuracy()

        if accuracy is not None:
            metrics.append(
                {
                    "name": "Prediction accuracy",
                    "is_primary": False,
                    "description": "Percentage of correct predictions",
                    "value": f"{accuracy:.0f}%",
                }
            )

        self._agent_performance_summary = AgentPerformanceSummary(
            timestamp=current_timestamp, metrics=metrics, agent_behavior=None
        )

    def _save_agent_performance_summary(
        self, agent_performance_summary: AgentPerformanceSummary
    ) -> None:
        """Save the agent performance summary to a file."""
        existing_data = self.shared_state._read_existing_performance_summary()
        agent_performance_summary.agent_behavior = existing_data.agent_behavior
        self.shared_state._overwrite_performance_summary(agent_performance_summary)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            yield from self._fetch_agent_performance_summary()

            if self._agent_performance_summary is None:
                self.context.logger.warning(
                    "Agent performance summary could not be fetched. Saving default values"
                )
                self._agent_performance_summary = AgentPerformanceSummary()

            self._save_agent_performance_summary(self._agent_performance_summary)

            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=True,
            )

        yield from self.finish_behaviour(payload)

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
    behaviours: Set[Type[BaseBehaviour]] = {FetchPerformanceSummaryBehaviour}  # type: ignore
