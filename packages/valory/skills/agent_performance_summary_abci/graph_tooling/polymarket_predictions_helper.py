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

"""Helper for fetching and formatting Polymarket predictions data."""

from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
)


# Constants
WEI_TO_NATIVE = 10**18
POLYMARKET_BASE_URL = "https://polymarket.com"
GRAPHQL_BATCH_SIZE = 1000
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class PolymarketPredictionsFetcher:
    """Shared logic for fetching and formatting Polymarket predictions."""

    def __init__(self, context, logger):
        """
        Initialize the Polymarket predictions fetcher.
        
        :param context: The behaviour/handler context
        :param logger: Logger instance
        """
        self.context = context
        self.logger = logger
        self.polymarket_url = context.polymarket_agents_subgraph.url

    def fetch_predictions(
        self,
        safe_address: str,
        first: int,
        skip: int = 0,
        status_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch and format Polymarket predictions with pagination support.
        
        :param safe_address: The agent's safe address
        :param first: Number of items to fetch
        :param skip: Number of items to skip (for pagination)
        :param status_filter: Optional status filter ('pending', 'won', 'lost')
        :return: Dictionary with total_predictions and formatted items
        """
        market_participants = self._fetch_market_participants(safe_address, first, skip)
        
        if not market_participants:
            self.logger.warning(f"No market participants found for {safe_address}")
            return {"total_predictions": 0, "items": []}
        
        # Extract all bets from all market participants
        all_bets = []
        for participant in market_participants:
            trader_agent = participant.get("traderAgent", {})
            bets = trader_agent.get("bets", [])
            all_bets.extend(bets)
        
        if not all_bets:
            return {"total_predictions": 0, "items": []}
        
        # Format individual bets (not grouped by market)
        items = self._format_predictions(all_bets, safe_address, status_filter)
        
        return {
            "total_predictions": len(all_bets),
            "items": items
        }

    def _fetch_market_participants(
        self, safe_address: str, first: int, skip: int
    ) -> Optional[List[Dict]]:
        """Fetch market participants from Polymarket subgraph."""
        query_payload = {
            "query": GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
            "variables": {
                "id": safe_address,
                "first": first,
                "skip": skip
            }
        }
        
        try:
            response = requests.post(
                self.polymarket_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch market participants: {response.status_code}")
                return None
            
            response_data = response.json()
            return response_data.get("data", {}).get("marketParticipants", [])
            
        except Exception as e:
            self.logger.error(f"Error fetching market participants: {str(e)}")
            return None

    def _format_predictions(
        self, 
        bets: List[Dict],
        safe_address: str,
        status_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Format raw bets into prediction objects (individual bets, not grouped).
        
        :param bets: List of bet objects
        :param safe_address: The agent's safe address
        :param status_filter: Optional status filter
        :return: List of formatted prediction objects
        """
        items = []
        for bet in bets:
            prediction = self._format_single_bet(bet, safe_address, status_filter)
            if prediction:
                items.append(prediction)
        
        return items

    def _format_single_bet(
        self,
        bet: Dict,
        safe_address: str,
        status_filter: Optional[str]
    ) -> Optional[Dict]:
        """Format a single Polymarket bet into a prediction object."""
        question = bet.get("question", {})
        metadata = question.get("metadata", {})
        resolution = question.get("resolution")
        
        # Get prediction status
        prediction_status = self._get_prediction_status(bet)
        
        # Apply status filter
        if status_filter and prediction_status != status_filter:
            return None
        
        # Calculate profit
        net_profit = self._calculate_bet_profit(bet)
        
        # Get bet amount
        bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
        
        # Get prediction side
        outcome_index = int(bet.get("outcomeIndex", 0))
        outcomes = metadata.get("outcomes", [])
        prediction_side = self._get_prediction_side(outcome_index, outcomes)
        
        # Get timestamps
        settled_timestamp = None
        if resolution:
            settled_timestamp = resolution.get("timestamp")
        
        return {
            "id": f"{question.get('questionId', '')}_{outcome_index}",
            "market": {
                "id": question.get("questionId", ""),
                "title": metadata.get("title", ""),
                "external_url": f"{POLYMARKET_BASE_URL}/event/{question.get('questionId', '')}"
            },
            "prediction_side": prediction_side,
            "bet_amount": round(bet_amount, 3),
            "status": prediction_status,
            "net_profit": round(net_profit, 3) if net_profit is not None else None,
            "created_at": None,  # Not available in Polymarket query
            "settled_at": self._format_timestamp(str(settled_timestamp)) if settled_timestamp else None
        }

    def _calculate_bet_profit(self, bet: Dict) -> Optional[float]:
        """
        Calculate profit for a single Polymarket bet.
        Profit = (shares * settled_price) - bet_amount for winning bets
        Profit = -bet_amount for losing bets
        Profit = 0 for pending bets
        """
        question = bet.get("question", {})
        resolution = question.get("resolution")
        
        # Pending if no resolution
        if not resolution:
            return 0.0
        
        winning_index = resolution.get("winningIndex")
        if winning_index is None or winning_index == "":
            # No winner yet
            return 0.0
        
        winning_index = int(winning_index)
        outcome_index = int(bet.get("outcomeIndex", 0))
        bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
        
        # Lost bet
        if outcome_index != winning_index:
            return -bet_amount
        
        # Won bet: profit = (shares * settled_price) - bet_amount
        shares = float(bet.get("shares", 0)) / WEI_TO_NATIVE
        settled_price = float(resolution.get("settledPrice", 0)) / WEI_TO_NATIVE
        
        return (shares * settled_price) - bet_amount

    def _get_prediction_status(self, bet: Dict) -> str:
        """
        Determine the status of a Polymarket prediction.
        Returns 'pending', 'won', or 'lost'.
        """
        question = bet.get("question", {})
        resolution = question.get("resolution")
        
        # Market not resolved
        if not resolution:
            return "pending"
        
        winning_index = resolution.get("winningIndex")
        if winning_index is None or winning_index == "":
            return "pending"
        
        winning_index = int(winning_index)
        outcome_index = int(bet.get("outcomeIndex", 0))
        
        if outcome_index == winning_index:
            return "won"
        
        return "lost"

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
