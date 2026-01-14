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

import json
import enum
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_PREDICTION_HISTORY_QUERY,
    GET_MECH_TOOL_FOR_QUESTION_QUERY,
    GET_SPECIFIC_MARKET_BETS_QUERY
)


# Constants
WEI_TO_NATIVE = 10**18
INVALID_ANSWER_HEX = "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
PREDICT_BASE_URL = "https://predict.olas.network/questions"
GRAPHQL_BATCH_SIZE = 1000
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

class BET_STATUS(enum.Enum):
    """BetStatus"""
    WON = "won"
    LOST = "lost"
    PENDING = "pending"

class TradingStrategy(enum.Enum):
    """TradingStrategy"""

    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"

class TradingStrategyUI(enum.Enum):
    """Trading strategy for the Agent's UI."""

    RISKY = "risky"
    BALANCED = "balanced"

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
        self.mech_url = context.olas_mech_subgraph.url

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

    def fetch_mech_tool_for_question(
        self, question_title: str, sender_address: str
    ) -> Optional[str]:
        """
        Fetch the prediction tool used for a specific question from the mech subgraph.
        
        :param question_title: The question title to search for
        :param sender_address: The sender address
        :return: The tool name or None if not found
        """
        query_payload = {
            "query": GET_MECH_TOOL_FOR_QUESTION_QUERY,
            "variables": {
                "sender": sender_address.lower(),
                "questionTitle": question_title
            }
        }
        
        try:
            response = requests.post(
                self.mech_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch mech tool: {response.status_code}")
                return None
            
            response_data = response.json()
            sender_data = response_data.get("data", {}).get("sender")
            
            if sender_data and sender_data.get("requests"):
                requests_list = sender_data["requests"]
                if requests_list and len(requests_list) > 0:
                    return requests_list[0].get("tool")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error fetching mech tool for question '{question_title}': {str(e)}")
            return None

    def fetch_position_details(
        self, market_id: str, safe_address: str, store_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch complete position details for a specific market.
        
        :param market_id: The market ID to fetch details for
        :param safe_address: The agent's safe address
        :param store_path: Path to the data store directory
        :return: Complete position details or None if not found
        """
        try:
            # Load multi_bets.json to get market info and prediction response
            multi_bets_data = self._load_multi_bets_data(store_path)
            market_info = self._find_market_in_multi_bets(multi_bets_data, market_id)
            
            if not market_info:
                return None
            
            # Load agent_performance.json to get bet history
            agent_performance_data = self._load_agent_performance_data(store_path)
            bet = self._find_bet_for_market(agent_performance_data, market_id)
            
            # If no bet found in agent_performance.json, fetch from subgraph
            if not bet:
                self.logger.info(f"No bets found in agent_performance.json for market {market_id}, fetching from subgraph")
                bet = self._fetch_specific_market_bet_from_subgraph(market_id, safe_address)
            
            if not bet:
                # Market exists but no bet found
                return {
                    "id": market_id,
                    "question": market_info.get("title", ""),
                    "currency": "USD",
                    "total_bet": 0.0,
                    "to_win": 0.0,
                    "status": "pending",
                    "net_profit": 0.0,
                    "bets": []
                }
            
            # Calculate totals and status
            total_bet = bet.get("bet_amount", 0)
            net_profit = bet.get("net_profit", 0)
            total_payout = bet.get("total_payout", 0)
            status = bet.get("status", 0)
            closing_timestamp = market_info.get("openingTimestamp", 0)
            current_timestamp =  int(datetime.utcnow().timestamp())

            remaining_seconds = (closing_timestamp - current_timestamp) if closing_timestamp>current_timestamp else 0 
            
            # Calculate to_win based on potential_net_profit
            potential_profit = market_info.get("potential_net_profit", 0)
            to_win = total_bet + (potential_profit / WEI_TO_NATIVE) if potential_profit > 0 else total_bet
            
            if status == BET_STATUS.WON.value:
                to_win = total_payout
            elif status in [BET_STATUS.PENDING.value, BET_STATUS.LOST.value] :
                to_win = 0

            # Get prediction tool from mech subgraph
            prediction_tool = self.fetch_mech_tool_for_question(
                market_info.get("title", ""), safe_address
            )

            #when creating prediction history, the agent assumes only one bet per market
            #we will need to add handling for multi-bets on same market
            bets = []
            bet = self._format_bet_for_position(bet, market_info, prediction_tool)
            bets.append(bet)
            
            # Build response
            return {
                "id": market_id,
                "question": market_info.get("title", ""),
                "currency": "USD",
                "total_bet": round(total_bet, 3),
                "to_win": round(to_win, 3),
                "remaining_seconds": remaining_seconds,
                "status": status,
                "net_profit": round(net_profit, 3),
                "bets": bets
            }
            
        except Exception as e:
            self.logger.error(f"Error fetching position details for market {market_id}: {str(e)}")
            return None

    def _load_multi_bets_data(self, store_path: str) -> List[Dict]:
        """Load data from multi_bets.json file."""
        try:
            import os
            multi_bets_path = os.path.join(store_path, "multi_bets.json")
            with open(multi_bets_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading multi_bets.json: {e}")
            return []

    def _load_agent_performance_data(self, store_path: str) -> Dict:
        """Load data from agent_performance.json file."""
        try:
            import os
            agent_performance_path = os.path.join(store_path, "agent_performance.json")
            with open(agent_performance_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading agent_performance.json: {e}")
            return {}

    def _find_market_in_multi_bets(self, multi_bets_data: List[Dict], market_id: str) -> Optional[Dict]:
        """Find market information in multi_bets data by market ID."""
        for market in multi_bets_data:
            if market.get("id") == market_id:
                return market
        return None

    def _find_bet_for_market(self, agent_performance_data: Dict, market_id: str) -> Optional[Dict]:
        """Find bet for a specific market ID in agent performance data."""
        prediction_history = agent_performance_data.get("prediction_history", {})
        items = prediction_history.get("items", [])
        
        for item in items:
            market = item.get("market", {})
            if market.get("id") == market_id:
                return item
        
        return {}
        

    def _format_bet_for_position(self, bets: Dict, market_info: Dict, prediction_tool: Optional[str]) -> Dict:
        """Format bets into the required API format for position details."""
        
        # Get prediction response from market_info
        prediction_response = market_info.get("prediction_response", {})
        strategy = market_info.get("strategy")
        trading_strategy_ui = self._get_ui_trading_strategy(strategy)

        
        # Determine implied probability based on bet side
        bet_side = bets.get("prediction_side", "").lower()
        if bet_side == "yes":
            implied_probability = prediction_response.get("p_yes",0) * 100
        else:
            implied_probability = prediction_response.get("p_no",0) * 100

        formatted_bet = {
            "id": bets.get("id", ""),
            "bet": {
                "amount": round(bets.get("bet_amount", 0), 3),
                "side": bet_side,
                "external_url": bets.get("market", {}).get("external_url", ""),
                "placed_at": bets.get("created_at", "")
            },
            "intelligence": {
                "prediction_tool": prediction_tool,
                "implied_probability": round(implied_probability, 1),
                "confidence_score": round(prediction_response.get("confidence",0) * 100, 1),
                "utility_score": round(prediction_response.get("info_utility",0) * 100, 1)
            },
            "strategy": trading_strategy_ui
        }
        
        return formatted_bet

    def _fetch_specific_market_bet_from_subgraph(
        self, market_id: str, safe_address: str
    ) -> Optional[Dict]:
        """
        Fetch bet for a specific market from the subgraph.
        
        :param market_id: The market ID to fetch bets for
        :param safe_address: The agent's safe address
        :return: formatted bet
        """
        # Query to get all bets for this agent and filter for specific market
        
        query_payload = {
            "query": GET_SPECIFIC_MARKET_BETS_QUERY,
            "variables": {
                "id": safe_address,
                "marketId": market_id
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
                self.logger.error(f"Failed to fetch specific market bets: {response.status_code}")
                return []
            
            response_data = response.json()
            trader_agent = response_data.get("data", {}).get("traderAgent")
            
            if not trader_agent or not trader_agent.get("bets"):
                return []
            
            # Convert subgraph format to agent_performance.json format
            bets = trader_agent["bets"]
            if not bets:
                return {}
            
            bet = bets[0]
            fpmm = bet.get("fixedProductMarketMaker", {})
            participants = fpmm.get("participants", [])
            market_participant = participants[0] if participants else None
            
            # Calculate net profit for this specific bet
            net_profit = self._calculate_market_net_profit(bets, market_participant)
            
            # Determine status
            status = self._get_prediction_status(bet, market_participant)
            
            # Get prediction side
            outcome_index = int(bet.get("outcomeIndex", 0))
            outcomes = fpmm.get("outcomes", [])
            prediction_side = self._get_prediction_side(outcome_index, outcomes)
            
            formatted_bet = {
                "id": bet.get("id"),
                "market": {
                    "id": fpmm.get("id"),
                    "title": fpmm.get("question", ""),
                    "external_url": f"{PREDICT_BASE_URL}/{fpmm.get('id')}"
                },
                "prediction_side": prediction_side,
                "bet_amount": round(float(bet.get("amount", 0)) / WEI_TO_NATIVE, 3),
                "status": status,
                "net_profit": round(net_profit, 3) if net_profit is not None else 0.0,
                "total_payout": float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE,
                "created_at": self._format_timestamp(bet.get("timestamp")),
                "settled_at": self._format_timestamp(fpmm.get("currentAnswerTimestamp")) if status != "pending" else None
            }
            
            return formatted_bet
            
        except Exception as e:
            self.logger.error(f"Error fetching specific market bets for {market_id}: {str(e)}")
            return {}

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
        
        # Get market participant data
        participants = fpmm.get("participants", [])
        market_participant = participants[0] if participants else None
        
        # Get basic prediction info
        prediction_status = self._get_prediction_status(first_bet, market_participant)
        
        # Apply status filter
        if status_filter and prediction_status != status_filter:
            return None
        
        # Calculate aggregated values
        total_bet_amount = self._calculate_total_bet_amount(market_bet_list)
        total_net_profit = self._calculate_market_net_profit(
            market_bet_list, market_participant
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
            "settled_at": self._format_timestamp(fpmm.get("currentAnswerTimestamp")) if prediction_status != "pending" else None,
            "total_payout": float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
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
        market_participant: Optional[Dict]
    ) -> Optional[float]:
        """
        Calculate net profit for all bets on a market.
        Net profit = payout - bet amount (no fees included)
        
        For multi-bet scenarios, uses MarketParticipant data with proportional distribution.
        """
        first_bet = market_bets[0]
        fpmm = first_bet.get("fixedProductMarketMaker", {})
        current_answer = fpmm.get("currentAnswer")
        
        # Pending market
        if current_answer is None:
            return 0.0
        
        # No market participant data available
        if not market_participant:
            return 0.0
        
        total_payout = float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
        
        # Invalid market - participants get refunds (use payout data)
        if current_answer == INVALID_ANSWER_HEX:
            # Only calculate if payout is actually received
            if total_payout == 0:
                return 0.0
            total_bet_amount = self._calculate_total_loss(market_bets)
            # Net profit = refund - original bet
            return total_payout - total_bet_amount
        
        # Parse correct answer
        correct_answer = int(current_answer, 0)
        
        # Separate winning and losing bets
        winning_bets, losing_bets = self._separate_winning_losing_bets(
            market_bets, correct_answer
        )
        
        # Check if payout is redeemed
        # If there are winning bets but payout is 0, treat as unredeemed (pending)
        if winning_bets and total_payout == 0:
            return 0.0
        
        total_loss = self._calculate_total_loss(losing_bets)
        
        # If no winning bets, return total loss
        if not winning_bets:
            return -total_loss
        
        # Calculate winning profit (payout - bet amount)
        winning_profit = self._calculate_winning_profit(
            winning_bets, market_participant
        )
        
        if winning_profit is None:
            return None
        
        # Subtract losses from winning profit
        return winning_profit - total_loss
        
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

    def _calculate_winning_profit(
        self,
        winning_bets: List[Dict],
        market_participant: Optional[Dict]
    ) -> Optional[float]:
        """Calculate profit from winning bets using proportional distribution (payout - bet amount only)."""
        if not market_participant:
            return None
        
        total_payout = float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
        
        total_winning_amount = sum(
            float(bet.get("amount", 0)) / WEI_TO_NATIVE 
            for bet in winning_bets
        )
        
        if total_winning_amount == 0:
            return 0.0
        
        # Distribute payout proportionally among winning bets
        # Profit = payout - bet amount
        winning_profit = 0.0
        for bet in winning_bets:
            bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
            bet_proportion = bet_amount / total_winning_amount
            
            bet_payout = total_payout * bet_proportion
            bet_profit = bet_payout - bet_amount
            winning_profit += bet_profit
        
        return winning_profit

    def _get_prediction_status(self, bet: Dict, market_participant: Optional[Dict]) -> str:
        """
        Determine the status of a prediction (pending, won, lost).
        If won but no payout (unredeemed), treat as pending.
        """
        fpmm = bet.get("fixedProductMarketMaker", {})
        current_answer = fpmm.get("currentAnswer")
        
        # Market not resolved
        if current_answer is None:
            return BET_STATUS.PENDING.value
        
        # Check for invalid market
        if current_answer == INVALID_ANSWER_HEX:
            return BET_STATUS.LOST.value
        
        outcome_index = int(bet.get("outcomeIndex", 0))
        correct_answer = int(current_answer, 0)
        
        # Check if won
        if outcome_index == correct_answer:
            # Check if winnings have been redeemed
            if market_participant:
                total_payout = float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
                if total_payout == 0:
                    # Won but not redeemed yet - treat as pending
                    return BET_STATUS.PENDING.value
            return BET_STATUS.WON.value
        
        return BET_STATUS.LOST.value

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
        
    def _get_ui_trading_strategy(
        self, selected_value: Optional[str]
    ) -> str:
        """Get the UI trading strategy."""
        if selected_value is None:
            return TradingStrategyUI.BALANCED.value

        if selected_value == TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value:
            return TradingStrategyUI.BALANCED.value
        elif selected_value == TradingStrategy.KELLY_CRITERION_NO_CONF.value:
            return TradingStrategyUI.RISKY.value
        else:
            return TradingStrategyUI.RISKY.value
