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

"""Shared helper for fetching and formatting predictions data."""
import enum
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher as BasePredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_MECH_RESPONSE_QUERY,
    GET_MECH_TOOL_FOR_QUESTION_QUERY,
    GET_PREDICTION_HISTORY_QUERY,
    GET_SPECIFIC_MARKET_BETS_QUERY,
)


# Constants
WEI_TO_NATIVE = 10**18
INVALID_ANSWER_HEX = (
    "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)
PREDICT_BASE_URL = "https://predict.olas.network/questions"
GRAPHQL_BATCH_SIZE = 1000
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_CURRENCY = "USD"


class BetStatus(enum.Enum):
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


class BetSide(enum.Enum):
    """Bet Side"""

    YES = "yes"
    NO = "no"


class PredictionsFetcher(BasePredictionsFetcher):
    """Shared logic for fetching and formatting predictions."""

    def __init__(self, context: Any, logger: Any) -> None:
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
        status_filter: Optional[str] = None,
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

        return {"total_predictions": total_bets, "items": items}

    def _fetch_trader_agent_bets(
        self, safe_address: str, first: int, skip: int
    ) -> Optional[Dict]:
        """Fetch trader agent bets from subgraph."""
        query_payload = {
            "query": GET_PREDICTION_HISTORY_QUERY,
            "variables": {"id": safe_address, "first": first, "skip": skip},
        }

        try:
            response = requests.post(
                self.predict_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch trader agent bets: {response.status_code}"
                )
                return None

            response_data = response.json()
            participants = response_data.get("data", {}).get("marketParticipants") or []
            if not participants:
                return None

            bets: List[Dict[str, Any]] = []
            for participant in participants:
                fpmm = participant.get("fixedProductMarketMaker") or {}
                participant_totals = {
                    "totalPayout": float(participant.get("totalPayout", 0))
                    / WEI_TO_NATIVE,
                    "totalTraded": float(participant.get("totalTraded", 0))
                    / WEI_TO_NATIVE,
                    "totalFees": float(participant.get("totalFees", 0)) / WEI_TO_NATIVE,
                    "totalBets": participant.get("totalBets", 0),
                }
                for bet in participant.get("bets", []) or []:
                    bet_copy = dict(bet)
                    bet_copy["fixedProductMarketMaker"] = {
                        **fpmm,
                        "participants": [participant_totals],
                    }
                    bets.append(bet_copy)

            return {
                "totalBets": sum(p.get("totalBets", 0) for p in participants),
                "bets": bets,
            }

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
                "questionTitle": question_title,
            },
        }

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

            deliveries = (requests_list[0] or {}).get("deliveries") or []
            if not deliveries:
                return None

            return deliveries[0].get("model")

            return None

        except Exception as e:
            self.logger.error(
                f"Error fetching mech tool for question '{question_title}': {str(e)}"
            )
            return None

    def _fetch_prediction_response_from_mech(
        self, question_title: str, sender_address: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch prediction response (p_yes, p_no, etc.) from mech subgraph"""
        if not question_title:
            return None

        query_payload = {
            "query": GET_MECH_RESPONSE_QUERY,
            "variables": {
                "sender": sender_address.lower(),
                "questionTitle": question_title,
            },
        }

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

    def fetch_position_details(
        self, bet_id: str, safe_address: str, store_path: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch complete position details for a specific market.

        :param bet_id: The bet ID to fetch details for
        :param safe_address: The agent's safe address
        :param store_path: Path to the data store directory
        :return: Complete position details or None if not found
        """
        try:
            # Load multi_bets.json to get market info and prediction response
            multi_bets_data = self._load_multi_bets_data(store_path)
            # Load agent_performance.json to get bet history
            agent_performance_data = self._load_agent_performance_data(store_path)
            bet = self._find_bet(agent_performance_data, bet_id)

            # If no bet found in agent_performance.json, fetch from subgraph
            if not bet:
                self.logger.info(
                    f"No bets found in agent_performance.json for bet {bet_id}, fetching from subgraph"
                )
                bet = self._fetch_bet_from_subgraph(bet_id, safe_address) or {}

            if not bet:
                # Market exists but no bet found
                return None

            market_id = bet.get("market", {}).get("id", "")
            market_info = self._find_market_entry(multi_bets_data, market_id)
            if not market_info:
                # Fall back to minimal market info from bet data
                market_info = bet.get("market", {}) or {}
                market_info.setdefault("id", market_id)

            bet_market_url = bet.get("market", {}).get("external_url")
            market_info["external_url"] = bet_market_url

            # Ensure prediction_response exists
            prediction_response = market_info.get("prediction_response")
            if not prediction_response:
                question_title = market_info.get("title") or bet.get("market", {}).get(
                    "title", ""
                )
                fetched_prediction_response = self._fetch_prediction_response_from_mech(
                    question_title,
                    safe_address,
                )
                if fetched_prediction_response:
                    prediction_response = fetched_prediction_response
                    market_info["prediction_response"] = prediction_response

            # Calculate totals and status
            total_bet = bet.get("bet_amount", 0)
            net_profit = bet.get("net_profit", 0)
            total_payout = bet.get("total_payout", 0)
            status = bet.get("status", 0)
            closing_timestamp = market_info.get("openingTimestamp", 0)
            current_timestamp = int(datetime.utcnow().timestamp())

            remaining_seconds = (
                (closing_timestamp - current_timestamp)
                if closing_timestamp > current_timestamp
                else 0
            )

            # Calculate to_win based on potential_net_profit
            potential_profit = market_info.get("potential_net_profit", 0)
            to_win = (
                total_bet + (potential_profit / WEI_TO_NATIVE)
                if potential_profit > 0
                else total_bet
            )

            if status == BetStatus.WON.value:
                to_win = total_payout
            elif status == BetStatus.LOST.value:
                to_win = 0

            # Get prediction tool from mech subgraph
            prediction_tool = self.fetch_mech_tool_for_question(
                market_info.get("title", ""), safe_address
            )

            # when creating prediction history, the agent assumes only one bet per market
            # we will need to add handling for multi-bets on same market
            bets = []
            bet = self._format_bet_for_position(bet, market_info, prediction_tool)
            bets.append(bet)

            # Build response
            return {
                "id": bet_id,
                "question": market_info.get("title", ""),
                "external_url": market_info.get("external_url", ""),
                "currency": DEFAULT_CURRENCY,
                "total_bet": round(total_bet, 3),
                "to_win": round(to_win, 3),
                "remaining_seconds": remaining_seconds,
                "status": status,
                "net_profit": round(net_profit, 3),
                "bets": bets,
            }

        except Exception as e:
            self.logger.error(
                f"Error fetching position details for bet {bet_id}: {str(e)}"
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
        self, multi_bets_data: List[Dict], market_id: str
    ) -> Optional[Dict]:
        """Find market information in multi_bets data by market ID."""
        for market in multi_bets_data:
            if market.get("id") == market_id:
                return market
        return None

    def _find_bet(self, agent_performance_data: Dict, bet_id: str) -> Dict:
        """Find bet for a specific bet ID in agent performance data."""
        prediction_history = agent_performance_data.get("prediction_history", {})
        items = prediction_history.get("items", [])

        for item in items:
            if item.get("id") == bet_id:
                return item

        return {}

    def _format_bet_for_position(
        self, bets: Dict, market_info: Dict, prediction_tool: Optional[str]
    ) -> Dict:
        """Format bets into the required API format for position details."""

        # Get prediction response from market_info
        prediction_response = market_info.get("prediction_response") or {}
        strategy = market_info.get("strategy")
        trading_strategy_ui = self._get_ui_trading_strategy(strategy)

        # Determine implied probability based on bet side
        bet_side = bets.get("prediction_side", "").lower()
        if bet_side == BetSide.YES.value:
            implied_probability = prediction_response.get("p_yes", 0) * 100
        else:
            implied_probability = prediction_response.get("p_no", 0) * 100

        formatted_bet = {
            "id": bets.get("id", ""),
            "bet": {
                "amount": round(bets.get("bet_amount", 0), 3),
                "side": bet_side,
                "placed_at": bets.get("created_at", ""),
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

    def _fetch_bet_from_subgraph(
        self, bet_id: str, safe_address: str
    ) -> Optional[Dict]:
        """
        Fetch bet for a specific market from the subgraph.

        :param bet_id: The bet ID to fetch
        :param safe_address: The agent's safe address
        :return: formatted bet
        """
        # Query to get all bets for this agent

        query_payload = {
            "query": GET_SPECIFIC_MARKET_BETS_QUERY,
            "variables": {"id": safe_address, "betId": bet_id},
        }

        try:
            response = requests.post(
                self.predict_url,
                json=query_payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )

            if response.status_code != 200:
                self.logger.error(
                    f"Failed to fetch specific market bets: {response.status_code}"
                )
                return None

            response_data = response.json()
            data = response_data.get("data", {}) or {}
            trader_agent = data.get("traderAgent")

            if not trader_agent or not trader_agent.get("bets"):
                return None

            # Convert subgraph format to agent_performance.json format
            bets = trader_agent["bets"]
            if not bets:
                return None

            # Pick the requested bet (fallback to first if not found)
            bet = next((b for b in bets if b.get("id") == bet_id), bets[0])
            fpmm = bet.get("fixedProductMarketMaker") or {}

            # Build per-market context from the returned bets (one item per bet)
            market_ctx_dict = self._build_market_context(bets)
            fpmm_id = fpmm.get("id")
            market_ctx = (
                market_ctx_dict.get(str(fpmm_id), {}) if fpmm_id is not None else {}
            )
            participant = market_ctx.get("participant") if market_ctx else None

            status = self._get_prediction_status(bet, participant)

            bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
            net_profit_val, payout_amount = self._calculate_bet_net_profit(
                bet, market_ctx, bet_amount
            )

            net_profit = (
                round(net_profit_val, 3) if net_profit_val is not None else None
            )
            payout_rounded = (
                round(payout_amount, 3) if payout_amount is not None else None
            )

            outcome_index = int(bet.get("outcomeIndex", 0))
            outcomes = fpmm.get("outcomes", [])
            prediction_side = self._get_prediction_side(outcome_index, outcomes)

            formatted_bet = {
                "id": bet.get("id"),
                "market": {
                    "id": fpmm.get("id"),
                    "title": fpmm.get("question", ""),
                    "external_url": f"{PREDICT_BASE_URL}/{fpmm.get('id')}",
                },
                "prediction_side": prediction_side,
                "bet_amount": round(bet_amount, 3),
                "status": status,
                "net_profit": net_profit,
                "total_payout": payout_rounded,
                "created_at": self._format_timestamp(bet.get("timestamp")),
                "settled_at": (
                    self._format_timestamp(fpmm.get("currentAnswerTimestamp"))
                    if status != "pending"
                    else None
                ),
            }

            return formatted_bet

        except Exception as e:
            self.logger.error(
                f"Error fetching specific market bets for {bet_id}: {str(e)}"
            )
            return None

    def _format_predictions(
        self, bets: List[Dict], safe_address: str, status_filter: Optional[str] = None
    ) -> List[Dict]:
        """Format raw bets into prediction objects with proportional payout distribution.

        :param bets: List of raw bet dictionaries
        :param safe_address: The safe address for filtering
        :param status_filter: Optional status filter
        :return: List of formatted prediction dictionaries
        """
        market_ctx = self._build_market_context(bets)

        items: List[Dict] = []
        for bet in bets:  # already ordered desc by timestamp in the query
            fpmm = bet.get("fixedProductMarketMaker", {}) or {}
            fpmm_id = fpmm.get("id")
            ctx = market_ctx.get(fpmm_id) if fpmm_id is not None else None
            prediction = self._format_single_bet(bet, fpmm, ctx, status_filter)
            if prediction:
                items.append(prediction)

        return items

    def _build_market_context(self, bets: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """Precompute per-market aggregates needed to distribute payouts per bet."""
        ctx: Dict[str, Dict[str, Any]] = {}

        for bet in bets:
            fpmm = bet.get("fixedProductMarketMaker", {}) or {}
            fpmm_id = fpmm.get("id")
            if not fpmm_id:
                continue

            entry = ctx.setdefault(
                fpmm_id,
                {
                    "current_answer": fpmm.get("currentAnswer"),
                    "current_answer_ts": fpmm.get("currentAnswerTimestamp"),
                    "outcomes": fpmm.get("outcomes") or [],
                    "participant": (fpmm.get("participants") or [None])[0],
                    "total_payout": None,
                    "total_traded": None,
                    "winning_total_amount": 0.0,
                },
            )

            participant = entry["participant"] or {}
            if entry["total_payout"] is None:
                entry["total_payout"] = float(participant.get("totalPayout", 0))
            if entry["total_traded"] is None:
                entry["total_traded"] = float(participant.get("totalTraded", 0))

            amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
            current_answer = entry["current_answer"]
            if current_answer not in (None, INVALID_ANSWER_HEX):
                correct = int(current_answer, 0)
                if int(bet.get("outcomeIndex", 0)) == correct:
                    entry["winning_total_amount"] += amount

        return ctx

    def _format_single_bet(
        self,
        bet: Dict,
        fpmm: Dict,
        market_ctx: Optional[Dict[str, Any]],
        status_filter: Optional[str],
    ) -> Optional[Dict]:
        """Format a single bet into the public prediction object."""
        participant = market_ctx.get("participant") if market_ctx else None
        prediction_status = self._get_prediction_status(bet, participant)

        if status_filter and prediction_status != status_filter:
            return None

        bet_amount = float(bet.get("amount", 0)) / WEI_TO_NATIVE
        net_profit, payout_amount = self._calculate_bet_net_profit(
            bet, market_ctx, bet_amount
        )

        outcome_index = int(bet.get("outcomeIndex", 0))
        outcomes = fpmm.get("outcomes", [])

        return {
            "id": bet.get("id"),
            "market": {
                "id": fpmm.get("id"),
                "title": fpmm.get("question", ""),
                "external_url": f"{PREDICT_BASE_URL}/{fpmm.get('id')}",
            },
            "prediction_side": self._get_prediction_side(outcome_index, outcomes),
            "bet_amount": round(bet_amount, 3),
            "status": prediction_status,
            "net_profit": round(net_profit, 3) if net_profit is not None else None,
            "total_payout": (
                round(payout_amount, 3) if payout_amount is not None else None
            ),
            "created_at": self._format_timestamp(bet.get("timestamp")),
            "settled_at": (
                self._format_timestamp(market_ctx.get("current_answer_ts"))
                if market_ctx and prediction_status != "pending"
                else None
            ),
        }

    def _calculate_bet_net_profit(
        self,
        bet: Dict,
        market_ctx: Optional[Dict[str, Any]],
        bet_amount: float,
    ) -> Tuple[Optional[float], Optional[float]]:
        """Calculate net profit and actual payout for a single bet using market-level payout data."""
        if not market_ctx:
            return 0.0, None

        current_answer = market_ctx.get("current_answer")
        total_payout = market_ctx.get("total_payout") or 0.0
        total_traded = market_ctx.get("total_traded") or 0.0
        winning_total = market_ctx.get("winning_total_amount") or 0.0
        outcome_index = int(bet.get("outcomeIndex", 0))

        # Unresolved market
        if current_answer is None:
            return 0.0, None

        # Invalid market refund path
        if current_answer == INVALID_ANSWER_HEX:
            if total_payout == 0 or total_traded == 0:
                return 0.0, None
            refund_share = total_payout * (bet_amount / total_traded)
            return refund_share - bet_amount, refund_share

        correct_answer = int(current_answer, 0)

        # Losing bet
        if outcome_index != correct_answer:
            return -bet_amount, 0.0

        # Winning bet
        if total_payout == 0 or winning_total == 0:
            # Won but not redeemed yet
            return 0.0, None

        payout_share = total_payout * (bet_amount / winning_total)
        return payout_share - bet_amount, payout_share

    def _get_prediction_status(
        self, bet: Dict, market_participant: Optional[Dict]
    ) -> str:
        """Determine the status of a prediction (pending, won, lost), treating unredeemed wins as pending.

        :param bet: The bet dictionary
        :param market_participant: Optional market participant data
        :return: Status string (pending, won, or lost)
        """
        fpmm = bet.get("fixedProductMarketMaker", {})
        current_answer = fpmm.get("currentAnswer")

        # Market not resolved
        if current_answer is None:
            return BetStatus.PENDING.value

        # Check for invalid market
        if current_answer == INVALID_ANSWER_HEX:
            return BetStatus.LOST.value

        outcome_index = int(bet.get("outcomeIndex", 0))
        correct_answer = int(current_answer, 0)

        # Check if won
        if outcome_index == correct_answer:
            # Check if winnings have been redeemed
            if market_participant:
                total_payout = (
                    float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
                )
                if total_payout == 0:
                    # Won but not redeemed yet - treat as pending
                    return BetStatus.PENDING.value
            return BetStatus.WON.value

        return BetStatus.LOST.value

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

    def _get_ui_trading_strategy(self, selected_value: Optional[str]) -> Optional[str]:
        """Get the UI trading strategy."""
        if selected_value is None:
            return None

        if selected_value == TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value:
            return TradingStrategyUI.BALANCED.value
        elif selected_value == TradingStrategy.KELLY_CRITERION_NO_CONF.value:
            return TradingStrategyUI.RISKY.value
        else:
            return None
