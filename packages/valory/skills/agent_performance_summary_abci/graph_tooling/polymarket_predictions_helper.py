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

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    BetStatus,
    TradingStrategy,
    TradingStrategyUI,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_MECH_RESPONSE_QUERY,
    GET_MECH_TOOL_FOR_QUESTION_QUERY,
    GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
    GET_POLYMARKET_SPECIFIC_BET_QUERY,
)

# Constants
USDC_DECIMALS_DIVISOR = 10**6  # USDC has 6 decimals on Polymarket
POLYMARKET_MARKET_BASE_URL = "https://polymarket.com/market"
GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"
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
        self.agents_url = context.polymarket_agents_subgraph.url
        self.mech_url = context.polygon_mech_subgraph.url

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

        # Extract all bets from all market participants
        # Now each bet already has its own question object, and we need to attach totalPayout from participant
        all_bets_with_questions = []
        for participant in market_participants:
            total_payout = participant.get("totalPayout", 0)
            bets = participant.get("bets", [])
            # Attach the totalPayout to each bet for processing
            for bet in bets:
                bet_with_payout = {**bet, "totalPayout": total_payout}
                all_bets_with_questions.append(bet_with_payout)

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

        # TODO: Switch to using the framework methods for calling subgraphs
        try:
            response = requests.post(
                self.context.polymarket_agents_subgraph.url,
                json=query_payload,
                timeout=30,
            )

            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch market participants: {response.status_code}"
                )
                return None

            response_data = response.json()
            return (response_data.get("data") or {}).get("marketParticipants", [])

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
        question = bet.get("question") or {}
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
        bet_amount = float(bet.get("amount", 0)) / USDC_DECIMALS_DIVISOR

        # Get prediction side
        outcome_index = int(bet.get("outcomeIndex", 0))
        outcomes = metadata.get("outcomes", [])
        prediction_side = self._get_prediction_side(outcome_index, outcomes)

        # Get IDs
        bet_id = bet.get("id", "")
        question_id = question.get("questionId", "")
        condition_id = question.get("id", "")
        market_title = metadata.get("title", "")
        transaction_hash = bet.get("transactionHash", "")

        # Get timestamps
        bet_timestamp = bet.get("blockTimestamp")
        resolution_timestamp = resolution.get("blockTimestamp") if resolution else None
        # Per-bet payout: shares for winning bets, 0 otherwise
        bet_shares = float(bet.get("shares", 0)) / USDC_DECIMALS_DIVISOR
        total_payout = bet_shares if prediction_status == BetStatus.WON.value else 0.0
        return {
            "id": bet_id,
            "market": {
                "id": question_id,
                "condition_id": condition_id,
                "title": market_title,
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
            "total_payout": (
                round(total_payout, 3) if total_payout is not None else None
            ),
        }

    def _calculate_bet_profit(self, bet: Dict) -> Optional[float]:
        """Calculate profit for a single Polymarket bet.

        Uses per-bet shares (not participant-level totalPayout) for accurate
        multi-bet payout attribution. On Polymarket, a winning bet's payout
        equals its shares value.

        :param bet: The bet dict (must include shares, amount, question with resolution)
        :return: Net profit or None
        """
        question = bet.get("question") or {}
        resolution = question.get("resolution")

        # Pending if no resolution
        if not resolution:
            return 0.0

        bet_amount = float(bet.get("amount", 0)) / USDC_DECIMALS_DIVISOR
        bet_shares = float(bet.get("shares", 0)) / USDC_DECIMALS_DIVISOR

        winning_index = resolution.get("winningIndex")
        # Invalid market: winningIndex < 0 (e.g. cancelled).
        # Use participant-level totalPayout pro-rated by bet amount.
        if winning_index is not None and int(winning_index) < 0:
            total_payout = float(bet.get("totalPayout", 0)) / USDC_DECIMALS_DIVISOR
            return total_payout - bet_amount

        outcome_index = bet.get("outcomeIndex")

        if outcome_index is not None and winning_index is not None:
            if int(outcome_index) == int(winning_index):
                # Winning bet — payout = shares
                if bet_shares > 0:
                    return bet_shares - bet_amount
                else:
                    # Won but not redeemed yet
                    return 0.0
            else:
                return -bet_amount
        else:
            # Fallback: use shares to determine
            if bet_shares > 0:
                return bet_shares - bet_amount
            else:
                return -bet_amount

    def _get_prediction_status(self, bet: Dict) -> str:
        """Determine the status of a Polymarket prediction, treating unredeemed wins as pending."""
        question = bet.get("question") or {}
        resolution = question.get("resolution")

        # Market not resolved - resolution object is null
        if not resolution:
            return BetStatus.PENDING.value

        # Market is resolved, determine win/loss by comparing outcomeIndex with winningIndex
        outcome_index = bet.get("outcomeIndex")
        winning_index = resolution.get("winningIndex")

        # Invalid market: winningIndex < 0 (e.g. cancelled)
        if winning_index is not None and int(winning_index) < 0:
            return BetStatus.INVALID.value

        # Compare outcomeIndex with winningIndex
        if outcome_index is not None and winning_index is not None:
            if int(outcome_index) == int(winning_index):
                # Check if winnings have been redeemed
                # totalPayout is only updated when the agent redeems (from subgraph)
                total_payout = float(bet.get("totalPayout", 0))
                if total_payout == 0:
                    # Won but not redeemed yet - treat as pending
                    return BetStatus.PENDING.value
                return BetStatus.WON.value
            else:
                return BetStatus.LOST.value
        else:
            # Fallback: if indices are missing, use totalPayout as backup
            total_payout = float(bet.get("totalPayout", 0))
            if total_payout > 0:
                return BetStatus.WON.value
            else:
                return BetStatus.LOST.value

    def _get_prediction_side(self, outcome_index: int, outcomes: List[str]) -> str:
        """Get the prediction side from outcome index and outcomes array."""
        # TODO: Hardcoded as outcomes onchain are not in proper order.
        # outcomes = metadata.get("outcomes", [])  # noqa: E800
        outcomes = ["Yes", "No"]
        if not outcomes or outcome_index >= len(outcomes):
            return "unknown"
        return outcomes[outcome_index].lower()

    def _format_timestamp(self, timestamp: Optional[str]) -> Optional[str]:
        """Format Unix timestamp to ISO 8601."""
        if not timestamp:
            return None

        try:
            unix_timestamp = int(timestamp)
            dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
            return dt.strftime(ISO_TIMESTAMP_FORMAT)
        except Exception as e:
            self.logger.error(f"Error formatting timestamp {timestamp}: {str(e)}")
            return None

    def fetch_mech_tool_for_question(
        self, question_title: str, sender_address: str, bet_timestamp: int = 0
    ) -> Optional[str]:
        """
        Fetch the prediction tool used for a specific question from the polygon mech subgraph.

        :param question_title: The question title to search for
        :param sender_address: The sender address
        :param bet_timestamp: Unix timestamp of the bet (0 = use current time)
        :return: The tool name or None if not found
        """
        ts = bet_timestamp or int(datetime.now(timezone.utc).timestamp())
        query_payload = {
            "query": GET_MECH_TOOL_FOR_QUESTION_QUERY,
            "variables": {
                "sender": sender_address.lower(),
                "questionTitle": question_title,
                "blockTimestamp_lte": str(ts),
            },
        }

        # TODO: Switch to using the framework methods for calling subgraphs
        try:
            response = requests.post(
                self.mech_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch mech tool: {response.status_code}")
                return None

            response_data = response.json()
            sender_data = (response_data.get("data", {}) or {}).get("sender") or {}

            requests_list = sender_data.get("requests") or []
            if not requests_list:
                return None

            parsed_request = (requests_list[0] or {}).get("parsedRequest") or {}
            if not parsed_request:
                return None

            return parsed_request.get("tool")

        except Exception as e:
            self.logger.error(
                f"Error fetching mech tool for question '{question_title}': {str(e)}"
            )
            return None

    def _fetch_prediction_response_from_mech(
        self, question_title: str, sender_address: str, bet_timestamp: int = 0
    ) -> Optional[Dict[str, Any]]:
        """Fetch prediction response (p_yes, p_no, etc.) from polygon mech subgraph.

        :param question_title: The question title to search for
        :param sender_address: The sender address
        :param bet_timestamp: Unix timestamp of the bet (0 = use current time)
        :return: Parsed prediction response dict or None
        """
        if not question_title:
            return None

        ts = bet_timestamp or int(datetime.now(timezone.utc).timestamp())
        query_payload = {
            "query": GET_MECH_RESPONSE_QUERY,
            "variables": {
                "sender": sender_address.lower(),
                "questionTitle": question_title,
                "blockTimestamp_lte": str(ts),
            },
        }

        # TODO: Switch to using the framework methods for calling subgraphs
        try:
            response = requests.post(
                self.mech_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch mech market data: {response.status_code}"
                )
                return None

            response_data = response.json()
            requests_list = (response_data.get("data", {}) or {}).get(
                "requests", []
            ) or []
            if not requests_list:
                return None

            deliveries = requests_list[0].get("deliveries", []) or []
            if not deliveries:
                return None

            tool_response_raw = deliveries[0].get("toolResponse")
            if not tool_response_raw:
                return None

            try:
                return json.loads(tool_response_raw)
            except json.JSONDecodeError:
                self.logger.error("Unable to parse mech toolResponse JSON")
                return None

        except Exception as e:
            self.logger.error(
                f"Error fetching prediction response from mech for '{question_title}': {str(e)}"
            )
            return None

    def _load_multi_bets_data(self, store_path: str) -> List[Dict]:
        """Load data from multi_bets.json file."""
        try:
            import os

            multi_bets_path = os.path.join(store_path, "multi_bets.json")
            with open(multi_bets_path, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading multi_bets.json: {e}")
            return []

    def _load_agent_performance_data(self, store_path: str) -> Dict:
        """Load data from agent_performance.json file."""
        try:
            import os

            agent_performance_path = os.path.join(store_path, "agent_performance.json")
            with open(agent_performance_path, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading agent_performance.json: {e}")
            return {}

    def _find_market_entry(
        self, multi_bets_data: List[Dict], market_id: str, condition_id: str = ""
    ) -> Optional[Dict]:
        """Find market information in multi_bets data by market ID (questionId)."""
        for market in multi_bets_data:
            # Primary: match by condition_id (most reliable cross-reference)
            if condition_id and market.get("condition_id") == condition_id:
                return market
            # Fallback: match by id or market field
            if market_id and (
                market.get("id") == market_id or market.get("market") == market_id
            ):
                return market
        return None

    def _find_bet(self, agent_performance_data: Dict, bet_id: str) -> Optional[Dict]:
        """Find bet for a specific bet ID in agent performance data."""
        prediction_history = agent_performance_data.get("prediction_history", {})
        items = prediction_history.get("items", [])

        for item in items:
            if item.get("id") == bet_id:
                return item

        return None

    def _fetch_bet_from_subgraph(
        self, bet_id: str, safe_address: str
    ) -> Optional[Dict]:
        """
        Fetch bet for a specific market from the Polymarket subgraph.

        :param bet_id: The bet ID to fetch
        :param safe_address: The agent's safe address
        :return: formatted bet
        """
        query_payload = {
            "query": GET_POLYMARKET_SPECIFIC_BET_QUERY,
            "variables": {"id": safe_address, "betId": bet_id},
        }

        # TODO: Switch to using the framework methods for calling subgraphs
        try:
            response = requests.post(
                self.agents_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch specific bet: {response.status_code}"
                )
                return None

            response_data = response.json()
            data = response_data.get("data", {}) or {}
            market_participants = data.get("marketParticipants", [])

            if not market_participants:
                return None

            # Find the bet across all market participants
            for participant in market_participants:
                bets = participant.get("bets", [])
                for bet in bets:
                    if bet.get("id") == bet_id:
                        # Format the bet to match agent_performance.json structure
                        question = bet.get("question") or {}
                        metadata = question.get("metadata", {})
                        resolution = question.get("resolution")

                        bet_amount = float(bet.get("amount", 0)) / USDC_DECIMALS_DIVISOR
                        bet_shares = float(bet.get("shares", 0)) / USDC_DECIMALS_DIVISOR

                        # Determine status (needs participant-level totalPayout for redemption check)
                        status = self._get_prediction_status(
                            {**bet, "totalPayout": participant.get("totalPayout", 0)}
                        )

                        # Calculate per-bet payout and net profit using shares
                        if not resolution:
                            bet_payout = 0.0
                            net_profit = 0.0
                        else:
                            winning_index = resolution.get("winningIndex")
                            if winning_index is not None and int(winning_index) < 0:
                                # Invalid market — pro-rate refund
                                total_traded_p = (
                                    float(participant.get("totalTraded", 0))
                                    / USDC_DECIMALS_DIVISOR
                                )
                                total_payout_p = (
                                    float(participant.get("totalPayout", 0))
                                    / USDC_DECIMALS_DIVISOR
                                )
                                bet_payout = (
                                    total_payout_p * (bet_amount / total_traded_p)
                                    if total_traded_p
                                    else 0.0
                                )
                                net_profit = bet_payout - bet_amount
                            elif str(bet.get("outcomeIndex")) == str(winning_index):
                                # Winning bet — payout = shares
                                bet_payout = bet_shares
                                net_profit = bet_payout - bet_amount
                            else:
                                bet_payout = 0.0
                                net_profit = -bet_amount

                        # Get prediction side
                        outcome_index = int(bet.get("outcomeIndex", 0))
                        outcomes = metadata.get("outcomes", [])
                        prediction_side = self._get_prediction_side(
                            outcome_index, outcomes
                        )

                        return {
                            "id": bet.get("id"),
                            "market": {
                                "id": question.get("questionId", ""),
                                "condition_id": question.get("id", ""),
                                "title": metadata.get("title", ""),
                            },
                            "prediction_side": prediction_side,
                            "bet_amount": round(bet_amount, 3),
                            "status": status,
                            "net_profit": round(net_profit, 3),
                            "total_payout": round(bet_payout, 3),
                            "created_at": (
                                self._format_timestamp(str(bet.get("blockTimestamp")))
                                if bet.get("blockTimestamp")
                                else None
                            ),
                            "settled_at": (
                                self._format_timestamp(
                                    str(resolution.get("blockTimestamp"))
                                )
                                if resolution and resolution.get("blockTimestamp")
                                else None
                            ),
                            "transaction_hash": bet.get("transactionHash", ""),
                        }

            return None

        except Exception as e:
            self.logger.error(f"Error fetching specific bet for {bet_id}: {str(e)}")
            return None

    def _fetch_market_slug(self, market_id: str) -> str:
        """Fetch the market slug from the Polymarket Gamma API.

        :param market_id: The numeric market ID (e.g. '1333587')
        :return: The market slug string, or empty string on failure
        """
        if not market_id:
            return ""
        try:
            # TODO: Switch to using the polymarket client connection for calling the Gamma API
            url = f"{GAMMA_API_BASE_URL}/markets/{market_id}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json().get("slug", "")
        except Exception as e:
            self.logger.warning(f"Failed to fetch slug for market {market_id}: {e}")
            return ""

    def _get_ui_trading_strategy(self, strategy: Optional[str]) -> Optional[str]:
        """Get the UI trading strategy representation."""
        if not strategy:
            return None

        strategy_map = {
            TradingStrategy.KELLY_CRITERION_NO_CONF.value: TradingStrategyUI.RISKY.value,
            TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value: TradingStrategyUI.BALANCED.value,
        }
        return strategy_map.get(strategy)

    def fetch_position_details(
        self, bet_id: str, safe_address: str, store_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch complete position details for a specific Polymarket bet.

        :param bet_id: The bet ID to fetch details for
        :param safe_address: The agent's safe address
        :param store_path: Path to the data store directory
        :return: Complete position details or None if not found
        """
        try:
            # Load from agent_performance.json first
            agent_performance_data = self._load_agent_performance_data(store_path)
            bet = self._find_bet(agent_performance_data, bet_id)

            # Fallback to subgraph if not found
            if not bet:
                self.logger.info(
                    f"No bet found in agent_performance.json for bet {bet_id}, fetching from subgraph"
                )
                bet = self._fetch_bet_from_subgraph(bet_id, safe_address)

            if not bet:
                return None

            # Parse bet timestamp for mech query filtering
            bet_timestamp = 0
            created_at = bet.get("created_at", "")
            if created_at:
                try:
                    dt = datetime.strptime(created_at, ISO_TIMESTAMP_FORMAT)
                    bet_timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
                except ValueError:
                    bet_timestamp = 0

            # Load market metadata from multi_bets.json
            multi_bets_data = self._load_multi_bets_data(store_path)
            market_id = bet.get("market", {}).get("id", "")
            condition_id = bet.get("market", {}).get("condition_id", "")
            market_info = self._find_market_entry(
                multi_bets_data, market_id, condition_id
            )

            if not market_info:
                # Use minimal market info from bet data
                market_info = bet.get("market", {}) or {}

            # Fetch prediction response from mech if not in multi_bets
            if market_info and not market_info.get("prediction_response"):
                question_title = market_info.get("title") or bet.get("market", {}).get(
                    "title", ""
                )
                if question_title:
                    prediction_response = self._fetch_prediction_response_from_mech(
                        question_title,
                        safe_address,
                        bet_timestamp=bet_timestamp,
                    )
                    if prediction_response:
                        market_info["prediction_response"] = prediction_response

            # Calculate financials
            total_bet = bet.get("bet_amount", 0)
            net_profit = bet.get("net_profit", 0)
            total_payout = bet.get("total_payout", 0)
            status = bet.get("status", "pending")

            # Calculate remaining time and potential payout
            closing_timestamp = (
                market_info.get("openingTimestamp", 0) if market_info else 0
            )
            current_timestamp = int(datetime.now(timezone.utc).timestamp())
            remaining_seconds = (
                (closing_timestamp - current_timestamp)
                if closing_timestamp > current_timestamp
                else 0
            )

            # Calculate to_win based on status and potential profit
            potential_profit = (
                market_info.get("potential_net_profit", 0) if market_info else 0
            )
            if status == "won" or status == "invalid":
                to_win = total_payout
            elif status == "lost":
                to_win = 0
            else:
                # Pending - use potential profit
                to_win = (
                    total_bet + (potential_profit / USDC_DECIMALS_DIVISOR)
                    if potential_profit > 0
                    else total_bet
                )

            # Get prediction tool from mech subgraph
            prediction_tool = None
            if market_info:
                question_title = market_info.get("title", "")
                if question_title:
                    prediction_tool = self.fetch_mech_tool_for_question(
                        question_title,
                        safe_address,
                        bet_timestamp=bet_timestamp,
                    )

            # Format bet details
            formatted_bet = self._format_bet_for_position(
                bet, market_info, prediction_tool
            )

            # Fetch slug from Gamma API to build the external URL
            numeric_market_id = str(market_info.get("id", "")) if market_info else ""
            slug = self._fetch_market_slug(numeric_market_id)
            external_url = f"{POLYMARKET_MARKET_BASE_URL}/{slug}" if slug else ""

            return {
                "id": bet_id,
                "question": bet.get("market", {}).get("title", ""),
                "external_url": external_url,
                "currency": "USDC",
                "total_bet": round(total_bet, 3),
                "payout": round(to_win, 3),
                "remaining_seconds": remaining_seconds,
                "status": status,
                "net_profit": round(net_profit, 3),
                "bets": [formatted_bet],
            }

        except Exception as e:
            self.logger.error(
                f"Error fetching position details for bet {bet_id}: {str(e)}"
            )
            return None

    def _format_bet_for_position(
        self, bet: Dict, market_info: Optional[Dict], prediction_tool: Optional[str]
    ) -> Dict:
        """Format bet into the required API format for position details."""

        # Get prediction response from market_info
        prediction_response = (market_info or {}).get("prediction_response") or {}
        strategy = (market_info or {}).get("strategy")
        trading_strategy_ui = self._get_ui_trading_strategy(strategy)

        # Determine implied probability based on bet side
        bet_side = bet.get("prediction_side", "").lower()
        if bet_side == "yes":
            implied_probability = prediction_response.get("p_yes", 0) * 100
        else:
            implied_probability = prediction_response.get("p_no", 0) * 100

        formatted_bet = {
            "id": bet.get("id", ""),
            "bet": {
                "amount": round(bet.get("bet_amount", 0), 3),
                "side": bet_side,
                "placed_at": bet.get("created_at", ""),
            },
            "intelligence": {
                "prediction_tool": prediction_tool,
                "implied_probability": round(implied_probability, 1),
                "confidence_score": round(
                    prediction_response.get("confidence", 0) * 100, 1
                ),
                "utility_score": round(
                    prediction_response.get("info_utility", 0) * 100, 1
                ),
            },
            "strategy": trading_strategy_ui,
        }

        return formatted_bet

    # Stub implementations for abstract methods not used in Polymarket
    def _fetch_trader_agent_bets(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _build_market_context(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")

    def _calculate_bet_net_profit(self, *args: Any, **kwargs: Any) -> Any:
        """Not used for Polymarket."""
        raise NotImplementedError("Not used for Polymarket")
