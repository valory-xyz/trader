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
from typing import Any, Dict, List, Optional

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_PREDICTION_HISTORY_QUERY,
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
            
            # Format predictions (aggregated by market)
            items = self._format_predictions(bets, safe_address, status_filter)
            
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

    def _format_predictions(
        self, 
        bets: List[Dict],
        safe_address: str,
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
            
            # Format predictions (one per market)
            items = []
            for fpmm_id, market_bet_list in market_bets.items():
                # Get first bet for reference data
                first_bet = market_bet_list[0]
                fpmm = first_bet.get("fixedProductMarketMaker", {})
                
                # Get market participant data
                participants = fpmm.get("participants", [])
                market_participant = participants[0] if participants else None
                
                # Determine market-level status (use first bet as reference)
                prediction_status = self._get_prediction_status(first_bet)
                
                # Apply status filter if provided
                if status_filter and prediction_status != status_filter:
                    continue
                
                # Get prediction side (from first bet)
                outcome_index = int(first_bet.get("outcomeIndex", 0))
                outcomes = fpmm.get("outcomes", [])
                
                # Calculate aggregated values
                total_bet_amount = sum(
                    float(bet.get("amount", 0)) / WEI_TO_NATIVE 
                    for bet in market_bet_list
                )
                
                total_net_profit = self._calculate_market_net_profit(
                    market_bet_list, market_participant, safe_address
                )
                
                # Get earliest timestamp
                earliest_timestamp = min(
                    int(bet.get("timestamp", 0)) 
                    for bet in market_bet_list 
                    if bet.get("timestamp")
                )
                
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
                    "net_profit": round(total_net_profit, 4) if total_net_profit is not None else None,                    "created_at": self._format_timestamp(str(earliest_timestamp)),
                    "settled_at": self._format_timestamp(fpmm.get("answerFinalizedTimestamp")) if prediction_status != "pending" else None
                }
                items.append(prediction)
            
            return items
            
        except Exception as e:
            self.logger.error(f"Error formatting predictions: {str(e)}")
            return []

    def _calculate_market_net_profit(
        self, 
        market_bets: List[Dict],
        market_participant: Optional[Dict],
        safe_address: str
    ) -> Optional[float]:
        """
        Calculate net profit for all bets on a market.
        
        For multi-bet scenarios, uses MarketParticipant data with proportional distribution.
        """
        try:
            # Check if market is resolved
            first_bet = market_bets[0]
            fpmm = first_bet.get("fixedProductMarketMaker", {})
            current_answer = fpmm.get("currentAnswer")
            
            # Pending market
            if current_answer is None:
                return 0.0
            
            # Invalid market - all bets lost
            if current_answer == INVALID_ANSWER_HEX:
                return -sum(
                    float(bet.get("amount", 0)) / WEI_TO_NATIVE 
                    for bet in market_bets
                )
            
            correct_answer = int(current_answer, 0)
            
            # Separate winning and losing bets
            winning_bets = []
            losing_bets = []
            
            for bet in market_bets:
                outcome_index = int(bet.get("outcomeIndex", 0))
                if outcome_index == correct_answer:
                    winning_bets.append(bet)
                else:
                    losing_bets.append(bet)
            
            # Calculate loss from losing bets
            total_loss = sum(
                float(bet.get("amount", 0)) / WEI_TO_NATIVE 
                for bet in losing_bets
            )
            
            # If no winning bets, return total loss
            if not winning_bets:
                return -total_loss
            
            if not market_participant:
                return None
            
            # Get market participant data
            total_payout = float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
            total_traded = float(market_participant.get("totalTraded", 0)) / WEI_TO_NATIVE
            total_fees = float(market_participant.get("totalFees", 0)) / WEI_TO_NATIVE
            
            # Calculate profit from winning bets using proportional distribution
            total_winning_amount = sum(
                float(bet.get("amount", 0)) / WEI_TO_NATIVE 
                for bet in winning_bets
            )
            
            if total_winning_amount == 0:
                return -total_loss
            
            # Distribute payout proportionally among winning bets
            winning_profit = 0.0
            for bet in winning_bets:
                bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
                bet_proportion = bet_amount / total_winning_amount
                
                bet_payout = total_payout * bet_proportion
                bet_fees = total_fees * bet_proportion
                
                bet_profit = bet_payout - bet_amount - bet_fees
                winning_profit += bet_profit
            
            # Total profit = winning profit - losing bets
            return winning_profit - total_loss
            
        except Exception as e:
            self.logger.error(f"Error calculating market net profit: {e}")
            return 0.0

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