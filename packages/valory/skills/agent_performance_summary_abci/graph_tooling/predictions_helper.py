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
from typing import Any, Dict, List, Optional, Tuple

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
MECH_FEE_PER_BET = 0.01  # 0.01 ETH mech fee per bet


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
        self.predict_url = context.olas_agents_subgraph.url

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
        trader_agent = self._fetch_trader_agent_bets(safe_address, first, skip)
        
        if not trader_agent:
            self.logger.warning(f"No trader agent found for {safe_address}")
            return {"total_predictions": 0, "items": []}
        
        total_bets = trader_agent.get("totalBets", 0)
        bets = trader_agent.get("bets", [])
        
        if not bets:
            return {"total_predictions": total_bets, "items": []}
        
        items = self._format_predictions(bets, safe_address, status_filter)
        
        return {
            "total_predictions": total_bets,
            "items": items
        }

    def _fetch_trader_agent_bets(
        self, safe_address: str, first: int, skip: int
    ) -> Optional[Dict]:
        """Fetch trader agent bets from subgraph."""
        query_payload = {
            "query": GET_PREDICTION_HISTORY_QUERY,
            "variables": {
                "id": safe_address,
                "first": first,
                "skip": skip
            }
        }
        
        try:
            response = requests.post(
                self.predict_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch trader agent bets: {response.status_code}")
                return None
            
            response_data = response.json()
            return response_data.get("data", {}).get("traderAgent")
            
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
        market_bets = self._group_bets_by_market(bets)
        
        items = []
        for fpmm_id, market_bet_list in market_bets.items():
            prediction = self._format_single_prediction(
                market_bet_list, safe_address, status_filter
            )
            if prediction:
                items.append(prediction)
        
        return items

    def _group_bets_by_market(self, bets: List[Dict]) -> Dict[str, List[Dict]]:
        """Group bets by market (FPMM) ID."""
        market_bets = {}
        
        for bet in bets:
            fpmm = bet.get("fixedProductMarketMaker", {})
            fpmm_id = fpmm.get("id")
            
            if not fpmm_id:
                continue
            
            if fpmm_id not in market_bets:
                market_bets[fpmm_id] = []
            market_bets[fpmm_id].append(bet)
        
        return market_bets

    def _format_single_prediction(
        self,
        market_bet_list: List[Dict],
        safe_address: str,
        status_filter: Optional[str]
    ) -> Optional[Dict]:
        """Format a single prediction (aggregated from potentially multiple bets on same market)."""
        first_bet = market_bet_list[0]
        fpmm = first_bet.get("fixedProductMarketMaker", {})
        
        # Get basic prediction info
        prediction_status = self._get_prediction_status(first_bet)
        
        # Apply status filter
        if status_filter and prediction_status != status_filter:
            return None
        
        # Get market participant data
        participants = fpmm.get("participants", [])
        market_participant = participants[0] if participants else None
        
        # Calculate aggregated values
        total_bet_amount = self._calculate_total_bet_amount(market_bet_list)
        total_net_profit = self._calculate_market_net_profit(
            market_bet_list, market_participant, safe_address
        )
        earliest_timestamp = self._get_earliest_timestamp(market_bet_list)
        
        # Get prediction side
        outcome_index = int(first_bet.get("outcomeIndex", 0))
        outcomes = fpmm.get("outcomes", [])
        
        return {
            "id": first_bet.get("id"),
            "market": {
                "id": fpmm.get("id"),
                "title": fpmm.get("question", ""),
                "external_url": f"{PREDICT_BASE_URL}/{fpmm.get('id')}"
            },
            "prediction_side": self._get_prediction_side(outcome_index, outcomes),
            "bet_amount": round(total_bet_amount, 3),
            "status": prediction_status,
            "net_profit": round(total_net_profit, 3) if total_net_profit is not None else None,
            "created_at": self._format_timestamp(str(earliest_timestamp)),
            "settled_at": self._format_timestamp(fpmm.get("currentAnswerTimestamp")) if prediction_status != "pending" else None
        }

    def _calculate_total_bet_amount(self, market_bet_list: List[Dict]) -> float:
        """Calculate total bet amount across all bets on a market."""
        return sum(
            float(bet.get("amount", 0)) / WEI_TO_NATIVE 
            for bet in market_bet_list
        )

    def _get_earliest_timestamp(self, market_bet_list: List[Dict]) -> int:
        """Get the earliest timestamp from a list of bets."""
        timestamps = [
            int(bet.get("timestamp", 0)) 
            for bet in market_bet_list 
            if bet.get("timestamp")
        ]
        return min(timestamps) if timestamps else 0

    def _calculate_market_net_profit(
        self, 
        market_bets: List[Dict],
        market_participant: Optional[Dict],
        safe_address: str
    ) -> Optional[float]:
        """
        Calculate net profit for all bets on a market, including mech and market fees.
        
        For multi-bet scenarios, uses MarketParticipant data with proportional distribution.
        """
        first_bet = market_bets[0]
        fpmm = first_bet.get("fixedProductMarketMaker", {})
        current_answer = fpmm.get("currentAnswer")
        
        # Calculate total fees for all bets on this market
        total_market_fees = self._calculate_total_market_fees(market_bets)
        total_mech_fees = len(market_bets) * MECH_FEE_PER_BET
        total_fees = total_market_fees + total_mech_fees
        
        # Pending market
        if current_answer is None:
            return 0.0
        
        # Invalid market - participants get refunds (use payout data)
        if current_answer == INVALID_ANSWER_HEX:
            if not market_participant:
                return 0.0
            
            total_payout = float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
            total_bet_amount = self._calculate_total_loss(market_bets)
            
            # Net profit = refund - original bet - fees
            return total_payout - total_bet_amount - total_fees
        
        # Parse correct answer
        correct_answer = int(current_answer, 0)
        
        # Separate winning and losing bets
        winning_bets, losing_bets = self._separate_winning_losing_bets(
            market_bets, correct_answer
        )
        
        total_loss = self._calculate_total_loss(losing_bets)
        
        # If no winning bets, return total loss including fees
        if not winning_bets:
            return -total_loss - total_fees
        
        # Calculate winning profit
        winning_profit = self._calculate_winning_profit(
            winning_bets, market_participant
        )
        
        if winning_profit is None:
            return None
        
        # Subtract losses and all fees from winning profit
        return winning_profit - total_loss - total_fees

    def _separate_winning_losing_bets(
        self, 
        market_bets: List[Dict], 
        correct_answer: int
    ) -> Tuple[List[Dict], List[Dict]]:
        """Separate bets into winning and losing based on outcome."""
        winning_bets = []
        losing_bets = []
        
        for bet in market_bets:
            outcome_index = int(bet.get("outcomeIndex", 0))
            if outcome_index == correct_answer:
                winning_bets.append(bet)
            else:
                losing_bets.append(bet)
        
        return winning_bets, losing_bets

    def _calculate_total_loss(self, losing_bets: List[Dict]) -> float:
        """Calculate total loss from losing bets."""
        return sum(
            float(bet.get("amount", 0)) / WEI_TO_NATIVE 
            for bet in losing_bets
        )
    
    def _calculate_total_market_fees(self, market_bets: List[Dict]) -> float:
        """Calculate total market fees from all bets on a market."""
        return sum(
            float(bet.get("feeAmount", 0)) / WEI_TO_NATIVE 
            for bet in market_bets
        )

    def _calculate_winning_profit(
        self,
        winning_bets: List[Dict],
        market_participant: Optional[Dict]
    ) -> Optional[float]:
        """Calculate profit from winning bets using proportional distribution."""
        if not market_participant:
            return None
        
        total_payout = float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
        
        total_winning_amount = sum(
            float(bet.get("amount", 0)) / WEI_TO_NATIVE 
            for bet in winning_bets
        )
        
        if total_winning_amount == 0:
            return 0.0
        
        # If payout is 0, the winnings haven't been redeemed yet
        # Show 0 profit (unclaimed winnings scenario)
        if total_payout == 0:
            return 0.0
        
        # Distribute payout proportionally among winning bets
        winning_profit = 0.0
        for bet in winning_bets:
            bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
            bet_proportion = bet_amount / total_winning_amount
            
            bet_payout = total_payout * bet_proportion
            bet_profit = bet_payout - bet_amount
            winning_profit += bet_profit
        
        return winning_profit

    def _get_prediction_status(self, bet: Dict) -> str:
        """Determine the status of a prediction (pending, won, lost)."""
        fpmm = bet.get("fixedProductMarketMaker", {})
        current_answer = fpmm.get("currentAnswer")
        
        # Market not resolved
        if current_answer is None:
            return "pending"
        
        # Check for invalid market
        if current_answer == INVALID_ANSWER_HEX:
            return "lost"
        
        outcome_index = int(bet.get("outcomeIndex", 0))
        correct_answer = int(current_answer, 0)
        return "won" if outcome_index == correct_answer else "lost"

    def _get_prediction_side(self, outcome_index: int, outcomes: List[str]) -> str:
        """Get the prediction side from outcome index and outcomes array."""
        if not outcomes or outcome_index >= len(outcomes):
            return "unknown"
        return outcomes[outcome_index].lower()

    def _format_timestamp(self, timestamp: Optional[str]) -> Optional[str]:
        """Format Unix timestamp to ISO 8601."""
        if not timestamp:
            return None
        
        try:
            unix_timestamp = int(timestamp)
            dt = datetime.utcfromtimestamp(unix_timestamp)
            return dt.strftime(ISO_TIMESTAMP_FORMAT)
        except Exception as e:
            self.logger.error(f"Error formatting timestamp {timestamp}: {str(e)}")
            return None