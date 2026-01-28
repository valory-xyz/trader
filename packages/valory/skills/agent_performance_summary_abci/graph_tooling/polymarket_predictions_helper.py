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

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
)


# Constants
WEI_TO_NATIVE = 10**18
POLYMARKET_BASE_URL = "https://polymarket.com"
GRAPHQL_BATCH_SIZE = 1000
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class PolymarketPredictionsFetcher(
    PredictionsFetcher,
):
    """Shared logic for fetching and formatting Polymarket predictions."""

    def __init__(self, context: Any, logger: Any):
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
        status_filter: Optional[str] = None,
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

        # Extract all bets from all market participants with their associated question
        all_bets_with_questions = []
        for participant in market_participants:
            question = participant.get("question", {})
            bets = participant.get("bets", [])
            # Attach the question to each bet for processing
            for bet in bets:
                bet_with_question = {**bet, "question": question}
                all_bets_with_questions.append(bet_with_question)

        if not all_bets_with_questions:
            return {"total_predictions": 0, "items": []}

        # Format individual bets (not grouped by market)
        items = self._format_predictions(
            all_bets_with_questions, safe_address, status_filter
        )

        return {"total_predictions": len(all_bets_with_questions), "items": items}

    def _fetch_market_participants(
        self, safe_address: str, first: int, skip: int
    ) -> Optional[List[Dict]]:
        """Fetch market participants from Polymarket subgraph."""
        query_payload = {
            "query": GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
            "variables": {"id": safe_address, "first": first, "skip": skip},
        }

        try:
            response = requests.post(
                self.polymarket_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch market participants: {response.status_code}"
                )
                return None

            response_data = response.json()
            return response_data.get("data", {}).get("marketParticipants", [])

        except Exception as e:
            self.logger.error(f"Error fetching market participants: {str(e)}")
            return None

    def _format_predictions(
        self, bets: List[Dict], safe_address: str, status_filter: Optional[str] = None
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
        self, bet: Dict, safe_address: str, status_filter: Optional[str]
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

        # Get IDs
        bet_id = bet.get("id", "")
        question_id = question.get("questionId", "")
        market_title = metadata.get("title", "")
        transaction_hash = bet.get("transactionHash", "")

        # Get timestamps
        bet_timestamp = bet.get("blockTimestamp")
        resolution_timestamp = resolution.get("timestamp") if resolution else None

        return {
            "id": bet_id,
            "market": {
                "id": question_id,
                "title": market_title,
                "external_url": (
                    f"{POLYMARKET_BASE_URL}/event/{question_id}"
                    if question_id
                    else f"{POLYMARKET_BASE_URL}/"
                ),
            },
            "prediction_side": prediction_side,
            "bet_amount": round(bet_amount, 3),
            "status": prediction_status,
            "net_profit": round(net_profit, 3) if net_profit is not None else None,
            "created_at": (
                self._format_timestamp(str(bet_timestamp)) if bet_timestamp else None
            ),
            "settled_at": (
                self._format_timestamp(str(resolution_timestamp))
                if resolution_timestamp
                else None
            ),
            "transaction_hash": transaction_hash,
        }

    def _calculate_bet_profit(self, bet: Dict) -> Optional[float]:
        """Calculate profit for a single Polymarket bet."""
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
        """Determine the status of a Polymarket prediction."""
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

    # Stub implementations for abstract methods not used in Polymarket
    # TODO: Move relevant methods to base class if shared
    def _fetch_trader_agent_bets(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def fetch_mech_tool_for_question(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _fetch_prediction_response_from_mech(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def fetch_position_details(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _load_multi_bets_data(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _load_agent_performance_data(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _find_market_entry(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _find_bet(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _format_bet_for_position(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _fetch_bet_from_subgraph(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _build_market_context(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _calculate_bet_net_profit(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _get_ui_trading_strategy(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")
