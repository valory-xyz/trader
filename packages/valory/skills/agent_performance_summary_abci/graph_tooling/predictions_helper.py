#!/usr/bin/env python3
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

"""Shared helper for fetching and formatting predictions data."""

from datetime import datetime
from typing import Any, Dict, Generator, List, Optional

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_PREDICTION_HISTORY_QUERY,
    GET_FPMM_PAYOUTS_QUERY,
)


# Constants
WEI_TO_NATIVE = 10**18
INVALID_ANSWER_HEX = "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
PREDICT_BASE_URL = "https://predict.olas.network/questions"
GRAPHQL_BATCH_SIZE = 1000
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class PredictionsFetcher:
    """Shared logic for fetching and formatting predictions."""

    def __init__(self, context, logger):
        """
        Initialize the predictions fetcher.
        
        :param context: The behaviour/handler context
        :param logger: Logger instance
        """
        self.context = context
        self.logger = logger
        self.predict_url = context.params.olas_agents_subgraph_url
        self.trades_url = context.params.trades_subgraph_url

    def fetch_predictions(
        self,
        safe_address: str,
        first: int,
        skip: int = 0,
        status_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch and format predictions with pagination support.
        
        :param safe_address: The agent's safe address
        :param first: Number of items to fetch
        :param skip: Number of items to skip (for pagination)
        :param status_filter: Optional status filter ('pending', 'won', 'lost')
        :return: Dictionary with total_predictions and formatted items
        """
        try:
            # Fetch trader agent with bets
            trader_agent = self._fetch_trader_agent_bets(
                safe_address, first, skip
            )
            
            if not trader_agent:
                self.logger.warning(f"No trader agent found for {safe_address}")
                return {
                    "total_predictions": 0,
                    "items": []
                }
            
            total_bets = trader_agent.get("totalBets", 0)
            bets = trader_agent.get("bets", [])
            
            if not bets:
                return {
                    "total_predictions": total_bets,
                    "items": []
                }
            
            # Extract unique FPMM IDs
            fpmm_ids = list(set([
                bet["fixedProductMarketMaker"]["id"] 
                for bet in bets 
                if bet.get("fixedProductMarketMaker", {}).get("id")
            ]))
            
            # Fetch payouts for these markets
            payouts_map = self._fetch_fpmm_payouts(fpmm_ids)
            
            # Format predictions
            items = self._format_predictions(
                bets, payouts_map, status_filter
            )
            
            return {
                "total_predictions": total_bets,
                "items": items
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching predictions: {str(e)}")
            return {
                "total_predictions": 0,
                "items": []
            }

    def _fetch_trader_agent_bets(
        self, safe_address: str, first: int, skip: int
    ) -> Optional[Dict]:
        """Fetch trader agent bets from subgraph."""
        try:
            query_payload = {
                "query": GET_PREDICTION_HISTORY_QUERY,
                "variables": {
                    "id": safe_address,
                    "first": first,
                    "skip": skip
                }
            }
            
            response = requests.post(
                self.predict_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch trader agent bets: {response.status_code}"
                )
                return None
            
            response_data = response.json()
            trader_agent = response_data.get("data", {}).get("traderAgent")
            
            return trader_agent
            
        except Exception as e:
            self.logger.error(f"Error fetching trader agent bets: {str(e)}")
            return None

    def _fetch_fpmm_payouts(self, fpmm_ids: List[str]) -> Dict[str, List]:
        """Fetch FPMM payouts from trades subgraph."""
        try:
            if not fpmm_ids:
                return {}
            
            query_payload = {
                "query": GET_FPMM_PAYOUTS_QUERY,
                "variables": {"fpmmIds": fpmm_ids}
            }
            
            response = requests.post(
                self.trades_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.logger.error(
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
            self.logger.error(f"Error fetching FPMM payouts: {str(e)}")
            return {}

    def _format_predictions(
        self, 
        bets: List[Dict], 
        payouts_map: Dict[str, List],
        status_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Format raw bets into prediction objects.
        
        Groups bets by market and aggregates multiple bets on the same market.
        """
        try:
            # Group bets by FPMM (market)
            market_bets = {}
            for bet in bets:
                fpmm = bet.get("fixedProductMarketMaker", {})
                fpmm_id = fpmm.get("id")
                
                if not fpmm_id:
                    continue
                
                if fpmm_id not in market_bets:
                    market_bets[fpmm_id] = []
                market_bets[fpmm_id].append(bet)
            
            # Format predictions (aggregated by market)
            items = []
            for fpmm_id, market_bet_list in market_bets.items():
                # Get first bet for reference data
                first_bet = market_bet_list[0]
                fpmm = first_bet.get("fixedProductMarketMaker", {})
                outcome_index = int(first_bet.get("outcomeIndex", 0))
                outcomes = fpmm.get("outcomes", [])
                
                prediction_status = self._get_prediction_status(first_bet)
                
                # Apply status filter if provided
                if status_filter and prediction_status != status_filter:
                    continue
                
                # Aggregate bet amounts and profits across all bets for this market
                total_bet_amount = 0.0
                total_net_profit = 0.0
                earliest_timestamp = None
                
                for bet in market_bet_list:
                    bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
                    total_bet_amount += bet_amount
                    total_net_profit += self._calculate_net_profit(
                        bet, payouts_map
                    )
                    
                    # Track earliest timestamp
                    bet_timestamp = bet.get("timestamp")
                    if bet_timestamp:
                        if earliest_timestamp is None or int(bet_timestamp) < int(earliest_timestamp):
                            earliest_timestamp = bet_timestamp
                
                # Build prediction object
                prediction = {
                    "id": first_bet.get("id"),
                    "market": {
                        "id": fpmm.get("id"),
                        "title": fpmm.get("question", ""),
                        "external_url": f"{PREDICT_BASE_URL}/{fpmm.get('id')}"
                    },
                    "prediction_side": self._get_prediction_side(outcome_index, outcomes),
                    "bet_amount": round(total_bet_amount, 4),
                    "status": prediction_status,
                    "net_profit": round(total_net_profit, 4),
                    "created_at": self._format_timestamp(earliest_timestamp or first_bet.get("timestamp")),
                    "settled_at": self._format_timestamp(fpmm.get("answerFinalizedTimestamp")) if prediction_status != "pending" else None
                }
                items.append(prediction)
            
            return items
            
        except Exception as e:
            self.logger.error(f"Error formatting predictions: {str(e)}")
            return []

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
            self.logger.error(f"Error determining prediction status: {e}")
            return "pending"

    def _get_prediction_side(self, outcome_index: int, outcomes: List[str]) -> str:
        """Get the prediction side from outcome index and outcomes array."""
        try:
            if not outcomes or outcome_index >= len(outcomes):
                return "unknown"
            return outcomes[outcome_index]
        except (IndexError, TypeError) as e:
            self.logger.error(f"Error getting prediction side: {e}")
            return "unknown"

    def _calculate_net_profit(
        self, bet: Dict, payouts_map: Dict[str, List]
    ) -> float:
        """Calculate net profit for a single bet."""
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
            self.logger.error(f"Error calculating net profit: {e}")
            return 0.0

    def _format_timestamp(self, timestamp: Optional[str]) -> Optional[str]:
        """Format Unix timestamp to ISO 8601."""
        if not timestamp:
            return None
        try:
            unix_timestamp = int(timestamp)
            dt = datetime.utcfromtimestamp(unix_timestamp)
            return dt.strftime(ISO_TIMESTAMP_FORMAT)
        except Exception as e:
            self.logger.error(f"Error formatting timestamp {timestamp}: {e}")
            return None
