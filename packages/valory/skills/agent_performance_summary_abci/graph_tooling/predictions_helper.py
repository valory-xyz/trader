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
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher as BasePredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_MECH_RESPONSE_QUERY,
    GET_MECH_TOOL_FOR_QUESTION_QUERY,
    GET_OMEN_FINALIZATION_QUERY,
    GET_PREDICTION_HISTORY_QUERY,
    GET_SPECIFIC_MARKET_BETS_QUERY,
)

# Constants
WEI_TO_NATIVE = 10**18
# The Graph's `id_in` filter caps at 1000 entries per call. Batched
# finalization enrichment chunks at this limit to avoid silent truncation
# for agents with large histories.
OMEN_ID_IN_CHUNK = 1000
INVALID_ANSWER_HEX = (
    "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
)
PREDICT_BASE_URL = "https://predict.olas.network/questions"
GRAPHQL_BATCH_SIZE = 1000
ISO_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_CURRENCY = "USD"
# Treat sub-cent share residuals as fully sold for the hybrid-status rule.
# Shares are 18-decimal-scaled; 1 share of a winning Omen outcome redeems
# for at most 1 wxDAI (binary FPMMs, payout fraction 1.0), so 1e16 base
# units (= 0.01 share, ~1 wxDAI cent on a fully-priced winner) is the
# practical "this is dust" threshold. Mirrors Polystrat's SHARES_EPSILON
# at 1e-6 scale; same semantic, different decimals.
SHARES_EPSILON_OMEN = 10**16


def now_ts() -> int:
    """Return current wall-clock time as a Unix timestamp (seconds).

    Single module-level time source. ``PredictionsFetcher._now`` and
    ``FetchPerformanceSummaryBehaviour._now`` both delegate here so the
    two classes cannot drift (e.g. one switching to milliseconds while
    the other stays on seconds). Tests can patch this symbol to freeze
    time, or patch the instance method for per-instance control.

    :return: current Unix timestamp in seconds.
    """
    return int(time.time())


def parse_current_answer(value: Optional[str]) -> Optional[int]:
    """Parse a Reality.eth currentAnswer hex string into an outcome index.

    Returns ``None`` for any value that cannot be interpreted as a valid
    outcome index (None, the invalid sentinel, malformed hex, empty,
    garbage). Callers treat ``None`` as "cannot classify — fall back to
    pending / skip". Centralising the cast prevents subgraph data quality
    issues from crashing the status pipeline.

    :param value: the raw currentAnswer string from the subgraph, or None.
    :return: parsed outcome index, or None if unparseable.
    """
    if value is None or value == INVALID_ANSWER_HEX:
        return None
    try:
        return int(value, 0)
    except (ValueError, TypeError):
        return None


def parse_timestamp(value: Any) -> Optional[int]:
    """Parse a subgraph Unix-seconds timestamp into a positive int.

    Returns ``None`` for any value that must not pass a finalization
    gate: ``None``, the ``"0"`` / ``0`` sentinel some Omen subgraph
    indexers emit for unset fields, negative values, malformed strings,
    and non-numeric garbage. Callers treat ``None`` as "unfinalized →
    pending", mirroring :func:`parse_current_answer` for currentAnswer.

    Added in response to PR #903 review (comment #1): the original gate
    ``int(ts) > now`` (a) crashed on malformed input and (b) let the
    ``"0"`` sentinel slip through as terminal.

    :param value: the raw timestamp value from the subgraph.
    :return: positive Unix-seconds int, or None if unparseable/unset.
    """
    if value is None:
        return None
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        return None
    if parsed <= 0:
        return None
    return parsed


def compute_funds_locked_from_bets(
    bets: List[Dict[str, Any]],
    context: Any,
    logger: Any,
    held_keys: Optional["set[tuple[str, int]]"] = None,
) -> float:
    """Per-position ``funds_locked_in_markets`` for Omenstrat (spec §7.2).

    FIFO-allocates the bet history, drops buys on resolved-and-losing
    markets (shares are worthless) and — when ``held_keys`` is provided
    — also drops buys whose CT shares have already been burned by
    ``redeemPositions``. Sums the remaining cost basis in wxDAI on
    what's left.

    Shared between the normal perf-summary round (which sees the
    agent's bet history end-to-end) and the post-withdrawal snapshot
    hook in ``decision_maker_abci.PostOmenWithdrawBehaviour`` (which
    uses the same data path to bridge the indexer-lag gap between
    settlement and the next normal perf-summary refresh — spec §7.3 /
    §10.13.3).

    The ``held_keys`` gate is the critical correction over the initial
    Phase 3B release: trade-history FIFO alone counts a redeemed
    winning position as locked (the bet row is immutable, and FIFO
    doesn't see the CT.balanceOf burn from ``CT.redeemPositions``).
    Discovered on PR #952's first live run: a safe with 0 actual
    recoverable value reported ~110 wxDAI locked. With the gate,
    redeemed positions correctly drop out.

    Per spec §7.2, requires the bet's ``fixedProductMarketMaker`` to
    carry ``conditionIds`` so we can key the gate by
    ``(conditionId, outcomeIndex)`` — the same key shape the CT
    subgraph's ``userPositions`` exposes.

    :param bets: subgraph ``bets`` array — must carry at least
        ``amount``, ``outcomeTokenAmount``, ``blockTimestamp``,
        ``outcomeIndex`` and ``fixedProductMarketMaker.{id,
        currentAnswer, conditionIds}``.
    :param context: skill ``Context`` (passed through to
        ``PredictionsFetcher`` for subgraph and logging dependencies).
    :param logger: logger to attach to the fetcher.
    :param held_keys: optional set of ``(condition_id_lower,
        outcome_index)`` tuples representing positions the safe still
        holds on-chain (``CT.balanceOf > 0``). When provided, bets
        whose position is NOT in this set are excluded. When ``None``
        (legacy callers / fallback on subgraph error), no gate is
        applied — same behaviour as the initial release.
    :return: wxDAI total of remaining cost on currently-held,
        non-LOSING positions; 0.0 for an empty bet list.
    """
    if not bets:
        return 0.0

    fetcher = PredictionsFetcher(context, logger)
    enriched_buys = fetcher._allocate_fifo(bets)

    total_remaining_wei = 0.0
    for buy in enriched_buys:
        fpmm = buy.get("fixedProductMarketMaker") or {}
        current_answer = fpmm.get("currentAnswer")
        if current_answer is not None:
            correct = parse_current_answer(current_answer)
            outcome_index = buy.get("outcomeIndex")
            if (
                correct is not None
                and outcome_index is not None
                and int(outcome_index) != correct
            ):
                # Resolved-and-losing — shares are worthless.
                continue

        if held_keys is not None:
            condition_ids = fpmm.get("conditionIds") or []
            if len(condition_ids) != 1:
                # Compound or missing — can't key the gate; skip
                # conservatively (better to under-report than count an
                # already-redeemed position as locked).
                continue
            outcome_index = buy.get("outcomeIndex")
            if outcome_index is None:
                continue
            key = (str(condition_ids[0]).lower(), int(outcome_index))
            if key not in held_keys:
                # Position already redeemed / transferred / never held.
                continue

        remaining = float(buy.get("original_cost", 0.0)) - float(
            buy.get("allocated_cost", 0.0)
        )
        if remaining > 0:
            total_remaining_wei += remaining

    return total_remaining_wei / WEI_TO_NATIVE


class BetStatus(enum.Enum):
    """BetStatus"""

    WON = "won"
    LOST = "lost"
    PENDING = "pending"
    INVALID = "invalid"


class TradingStrategy(enum.Enum):
    """TradingStrategy"""

    KELLY_CRITERION = "kelly_criterion"
    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"  # backward compat alias
    FIXED_BET = "fixed_bet"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"  # backward compat alias


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
        self.omen_url = context.omen_subgraph.url

    def _now(self) -> int:
        """Return the current wall-clock time as a Unix timestamp.

        Thin delegator to the module-level :func:`now_ts` so the two
        classes that need a time source share one implementation and
        cannot drift. Kept as an instance method so existing tests can
        still ``patch.object(fetcher, "_now", return_value=...)``.

        :return: current Unix timestamp in seconds.
        """
        return now_ts()

    def _fetch_finalization_by_fpmm_ids(
        self, fpmm_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch Reality.eth finalization data from omen_subgraph by id.

        Chunks at :data:`OMEN_ID_IN_CHUNK` because The Graph's ``id_in``
        filter caps at 1000 entries per call. Failures (network, non-200,
        malformed JSON) degrade silently to an empty result for the
        affected chunk; callers downstream treat missing enrichment as
        "not finalized" and the bet stays pending — same defensive shape
        as the existing subgraph paths.

        :param fpmm_ids: List of FPMM contract addresses (lowercased hex).
        :return: ``{fpmm_id: {answerFinalizedTimestamp, isPendingArbitration, ...}}``.
        """
        if not fpmm_ids:
            return {}

        merged: Dict[str, Dict[str, Any]] = {}
        for i in range(0, len(fpmm_ids), OMEN_ID_IN_CHUNK):
            batch = fpmm_ids[i : i + OMEN_ID_IN_CHUNK]
            try:
                response = requests.post(
                    self.omen_url,
                    json={
                        "query": GET_OMEN_FINALIZATION_QUERY,
                        "variables": {"ids": batch},
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=30,
                )
            except Exception as exc:  # noqa: BLE001 - degrade on any error
                self.logger.warning(f"Omen finalization fetch errored: {exc}")
                continue

            if response.status_code != 200:
                self.logger.warning(
                    f"Omen finalization fetch failed with status "
                    f"{response.status_code}; chunk skipped"
                )
                continue

            try:
                payload = response.json() or {}
            except ValueError as exc:
                self.logger.warning(f"Omen finalization response not JSON: {exc}")
                continue

            data = payload.get("data") or {}
            for row in data.get("fixedProductMarketMakers") or []:
                fpmm_id = row.get("id")
                if fpmm_id is not None:
                    merged[fpmm_id] = row

        return merged

    def _enrich_bets_with_finalization(self, bets: List[Dict]) -> None:
        """Mutate each bet's fpmm dict in place with omen finalization fields.

        Bets whose ``fixedProductMarketMaker`` is missing or has no ``id``
        are left untouched. Bets whose id is not returned by the omen
        query (e.g. indexer skew) get safe defaults
        (``answerFinalizedTimestamp = None``,
        ``isPendingArbitration = False``) which downstream gate logic
        treats as "not finalized" → bet stays pending.

        :param bets: List of bet dicts as returned by the olas_agents
            queries; each must have a ``fixedProductMarketMaker`` key.
        """
        ids = list(
            {
                fpmm_id
                for fpmm_id in (
                    (bet.get("fixedProductMarketMaker") or {}).get("id") for bet in bets
                )
                if fpmm_id
            }
        )
        if not ids:
            return

        enrichment = self._fetch_finalization_by_fpmm_ids(ids)
        for bet in bets:
            fpmm = bet.get("fixedProductMarketMaker")
            if not fpmm:
                continue
            row = enrichment.get(fpmm.get("id"), {})
            fpmm["answerFinalizedTimestamp"] = row.get("answerFinalizedTimestamp")
            fpmm["isPendingArbitration"] = bool(row.get("isPendingArbitration", False))

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

        # ZD#919: enrich each bet's fpmm dict with finalization fields from
        # omen_subgraph BEFORE classification helpers run. The olas_agents
        # subgraph does not expose answerFinalizedTimestamp; without this
        # call every bet would be silently classified as pending.
        self._enrich_bets_with_finalization(bets)

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
            participants = (response_data.get("data") or {}).get(
                "marketParticipants"
            ) or []
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
        self, question_title: str, sender_address: str, bet_timestamp: int = 0
    ) -> Optional[str]:
        """
        Fetch the prediction tool used for a specific question from the mech subgraph.

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
        """Fetch prediction response (p_yes, p_no, etc.) from mech subgraph.

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

            # Parse bet timestamp for mech query filtering
            bet_timestamp = 0
            created_at = bet.get("created_at", "")
            if created_at:
                try:
                    dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ")
                    bet_timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
                except ValueError:
                    bet_timestamp = 0

            # Ensure prediction_response exists
            prediction_response = market_info.get("prediction_response")
            if not prediction_response:
                question_title = market_info.get("title") or bet.get("market", {}).get(
                    "title", ""
                )
                fetched_prediction_response = self._fetch_prediction_response_from_mech(
                    question_title,
                    safe_address,
                    bet_timestamp=bet_timestamp,
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
            current_timestamp = int(datetime.now(timezone.utc).timestamp())

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

            if status in (BetStatus.WON.value, BetStatus.INVALID.value):
                to_win = total_payout
            elif status == BetStatus.LOST.value:
                to_win = 0

            # Get prediction tool from mech subgraph
            prediction_tool = self.fetch_mech_tool_for_question(
                market_info.get("title", ""),
                safe_address,
                bet_timestamp=bet_timestamp,
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
                "payout": round(to_win, 3),
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

            # ZD#919: enrich with finalization fields from omen_subgraph
            # before any status helper runs. Single-bet path always
            # produces a one-element id list (deduplicated by the helper).
            self._enrich_bets_with_finalization(bets)

            # Pick the requested bet
            bet = next((b for b in bets if b.get("id") == bet_id), None)
            if bet is None:
                self.logger.warning(f"Bet {bet_id} not found in subgraph response")
                return None
            fpmm = bet.get("fixedProductMarketMaker") or {}

            # Build per-market context from ALL bets on this market (via participant.bets)
            # so that winning_total_amount is computed correctly for proportional payout
            participant_data = (fpmm.get("participants") or [{}])[0]
            all_market_bets = participant_data.get("bets", [])
            if all_market_bets:
                all_bets_with_fpmm = [
                    {**b, "fixedProductMarketMaker": fpmm} for b in all_market_bets
                ]
            else:
                # Fallback: use just the single bet (old behavior)
                all_bets_with_fpmm = bets
            # FIFO-allocate before building the market context so the
            # winning-total denominator + per-bet payout share use the
            # FIFO-aware remaining cost basis. The target ``bet`` is
            # re-resolved from the enriched output so this single-bet
            # endpoint emits the same FIFO state the bulk endpoint does.
            enriched_buys = self._allocate_fifo(all_bets_with_fpmm)
            market_ctx_dict = self._build_market_context(enriched_buys)
            enriched_bet = next(
                (b for b in enriched_buys if b.get("id") == bet_id),
                bet,
            )
            fpmm_id = fpmm.get("id")
            market_ctx = (
                market_ctx_dict.get(str(fpmm_id), {}) if fpmm_id is not None else {}
            )
            participant = market_ctx.get("participant") if market_ctx else None

            status = self._get_prediction_status(enriched_bet, participant)

            fifo = self._fifo_state(enriched_bet)
            bet_amount = fifo["original_cost"] / WEI_TO_NATIVE
            net_profit_val, payout_amount = self._calculate_bet_net_profit(
                enriched_bet, market_ctx, bet_amount
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

        Runs the sell-aware FIFO allocator before formatting so each output
        row represents a single original buy enriched with its
        FIFO-consumed sells. Sells are folded into their parent buys and
        therefore do not appear as standalone rows. See
        :meth:`_allocate_fifo` for the per-group allocation semantics.

        :param bets: List of raw bet dictionaries
        :param safe_address: The safe address for filtering
        :param status_filter: Optional status filter
        :return: List of formatted prediction dictionaries
        """
        enriched_buys = self._allocate_fifo(bets)
        market_ctx = self._build_market_context(enriched_buys)

        items: List[Dict] = []
        for bet in enriched_buys:  # ordered chronologically by FIFO output
            fpmm = bet.get("fixedProductMarketMaker", {}) or {}
            fpmm_id = fpmm.get("id")
            ctx = market_ctx.get(fpmm_id) if fpmm_id is not None else None
            prediction = self._format_single_bet(bet, fpmm, ctx, status_filter)
            if prediction:
                items.append(prediction)

        return items

    def _allocate_fifo(self, bets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """FIFO-allocate sells against prior buys per ``(fpmm.id, outcomeIndex)``.

        Returns one enriched buy dict per original buy row, with FIFO state
        fields attached:

        - ``original_shares`` / ``original_cost`` — the buy as posted.
        - ``remaining_shares`` — shares still held after sells (≥ 0).
        - ``allocated_proceeds`` — wxDAI realised from sells of this buy.
        - ``allocated_cost`` — cost-basis portion already exited via sells.
        - ``participant_remaining_cost`` — sum of all buys' remaining cost
          across the participant, used to pro-rate invalid-market refunds
          (multi-buy attribution from PR #948 review round 2).

        Sells are detected by ``amount < 0`` (predict-omen handler convention,
        confirmed empirically in spec §13.3) and folded into their parent buys
        — they do NOT appear in the output. Orphan sells (no matching prior
        buy within the same ``(fpmm, outcomeIndex)`` group) are logged and
        dropped. Bets with a None ``fpmm.id`` or ``outcomeIndex`` are skipped
        because they have no group key.

        :param bets: raw bet dicts from the subgraph (mix of buys and sells,
            ordered descending by timestamp from the query).
        :return: enriched buy dicts in chronological order within each group;
            inter-group order matches the input.
        """
        groups: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
        bet_to_participant: Dict[str, Dict[str, Any]] = {}
        for bet in bets:
            fpmm = bet.get("fixedProductMarketMaker") or {}
            fpmm_id = fpmm.get("id")
            outcome_index = bet.get("outcomeIndex")
            if fpmm_id is None or outcome_index is None:
                self.logger.warning(
                    "FIFO: skipping bet id=%s; fpmm_id or outcomeIndex missing",
                    bet.get("id"),
                )
                continue
            participant = (fpmm.get("participants") or [None])[0]
            bet_to_participant[bet.get("id", "")] = participant or {}
            groups[(fpmm_id, int(outcome_index))].append(bet)

        output: List[Dict[str, Any]] = []
        for (fpmm_id, outcome_index), group_bets in groups.items():
            # Sort chronologically. blockTimestamp is the canonical FIFO key;
            # `id` (subgraph's {txHash}-{logIndex} form) is a deterministic
            # tiebreaker for same-block rows.
            group_bets.sort(
                key=lambda b: (
                    int(b.get("blockTimestamp", b.get("timestamp", 0)) or 0),
                    b.get("id", ""),
                )
            )
            buys_in_group: List[Dict[str, Any]] = []
            open_buys: "deque[Dict[str, Any]]" = deque()

            for row in group_bets:
                row_amount = float(row.get("amount", 0) or 0)
                row_shares = float(row.get("outcomeTokenAmount", 0) or 0)

                # Defensive cross-check (spec §8.2): amount and shares
                # carry the same sign on a well-formed row. Disagreement is
                # a data-quality signal — warn and skip rather than feed
                # garbage through FIFO.
                if row_amount != 0 and row_shares != 0:
                    if (row_amount > 0) != (row_shares > 0):
                        self.logger.warning(
                            "FIFO: bet id=%s on (fpmm=%s, outcomeIndex=%s) has "
                            "amount/outcomeTokenAmount sign disagreement "
                            "(amount=%s, shares=%s); skipping",
                            row.get("id"),
                            fpmm_id,
                            outcome_index,
                            row_amount,
                            row_shares,
                        )
                        continue

                is_buy = row_amount > 0
                if is_buy:
                    enriched = {
                        **row,
                        "original_shares": row_shares,
                        "original_cost": row_amount,
                        "remaining_shares": row_shares,
                        "allocated_proceeds": 0.0,
                        "allocated_cost": 0.0,
                    }
                    buys_in_group.append(enriched)
                    if row_shares > 0:
                        open_buys.append(enriched)
                else:
                    proceeds_total = -row_amount  # positive wxDAI received
                    shares_consumed = -row_shares  # positive shares sold

                    while shares_consumed > 0 and open_buys:
                        head = open_buys[0]
                        take = min(shares_consumed, head["remaining_shares"])
                        if take <= 0:
                            open_buys.popleft()
                            continue
                        share_ratio = take / (-row_shares)
                        cost_ratio = take / head["original_shares"]
                        head["allocated_proceeds"] += proceeds_total * share_ratio
                        head["allocated_cost"] += head["original_cost"] * cost_ratio
                        head["remaining_shares"] -= take
                        shares_consumed -= take
                        if head["remaining_shares"] <= 0:
                            open_buys.popleft()

                    if shares_consumed > 0:
                        unattributed_wxdai = (
                            proceeds_total * (shares_consumed / (-row_shares))
                            / WEI_TO_NATIVE
                        )
                        self.logger.warning(
                            "FIFO: orphan sell %s on (fpmm=%s, outcomeIndex=%s): "
                            "%s shares unmatched, %.6f wxDAI unattributed",
                            row.get("id"),
                            fpmm_id,
                            outcome_index,
                            shares_consumed,
                            unattributed_wxdai,
                        )

            output.extend(buys_in_group)

        # participant_remaining_cost — sum across all enriched buys for the
        # invalid-market refund pro-rate. Stored in base units (wei) to
        # match the rest of the FIFO state.
        participant_remaining_cost = sum(
            max(b["original_cost"] - b["allocated_cost"], 0.0) for b in output
        )
        for b in output:
            b["participant_remaining_cost"] = participant_remaining_cost

        return output

    def _fifo_state(self, bet: Dict[str, Any]) -> Dict[str, float]:
        """Return FIFO state for a buy with safe defaults for legacy callers.

        Callers that haven't been routed through :meth:`_allocate_fifo`
        pass raw subgraph rows; treat those as "never sold" so the old
        formula paths remain bit-identical until they migrate. New
        sell-aware paths read from the enriched fields (``remaining_cost``
        etc.) and get the correct values.

        :param bet: bet dict, optionally enriched with FIFO state fields.
        :return: dict with float-typed FIFO state values, all in base units.
        """
        raw_amount = float(bet.get("amount", 0) or 0)
        raw_shares = float(bet.get("outcomeTokenAmount", 0) or 0)
        original_cost = float(bet.get("original_cost", raw_amount))
        allocated_cost = float(bet.get("allocated_cost", 0.0))
        return {
            "original_shares": float(bet.get("original_shares", raw_shares)),
            "original_cost": original_cost,
            "remaining_shares": float(bet.get("remaining_shares", raw_shares)),
            "allocated_proceeds": float(bet.get("allocated_proceeds", 0.0)),
            "allocated_cost": allocated_cost,
            "remaining_cost": max(original_cost - allocated_cost, 0.0),
            "participant_remaining_cost": float(
                bet.get(
                    "participant_remaining_cost",
                    max(original_cost - allocated_cost, 0.0),
                )
            ),
        }

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
                    # ZD#919: finalization & arbitration flags are populated
                    # via _enrich_bets_with_finalization (omen_subgraph) before
                    # this method runs. Both feed the gates in
                    # _calculate_bet_net_profit and _get_prediction_status.
                    "answer_finalized_ts": fpmm.get("answerFinalizedTimestamp"),
                    "is_pending_arbitration": bool(fpmm.get("isPendingArbitration")),
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

            # Use the FIFO ``remaining_cost`` instead of the raw signed
            # ``amount``: prior to FIFO this summed any sell row's negative
            # amount into the winning-total denominator (spec §8.1 bug
            # site at line 867), under-counting and skewing every winning
            # bet's payout share. After FIFO, sells have been folded into
            # the originating buys' ``allocated_cost`` — so the unsold
            # remaining cost basis is the right contribution.
            fifo = self._fifo_state(bet)
            remaining_cost = fifo["remaining_cost"] / WEI_TO_NATIVE
            correct = parse_current_answer(entry["current_answer"])
            if correct is not None:
                if int(bet.get("outcomeIndex", 0)) == correct:
                    entry["winning_total_amount"] += remaining_cost

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

        # Display the original buy size — the post-FIFO ``original_cost``
        # for enriched rows; the raw ``amount`` for legacy callers (the
        # FIFO state helper's defaults make this transparent).
        fifo = self._fifo_state(bet)
        bet_amount = fifo["original_cost"] / WEI_TO_NATIVE
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
                round(payout_amount, 3) if payout_amount is not None else 0
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
        """Calculate sell-aware net profit and payout for a single bet.

        Net profit = realized PnL on sold shares (allocated_proceeds −
        allocated_cost) + redemption PnL on the unsold remainder. For
        losing outcomes the remainder is worthless; for winners it is
        ``payout_share − remaining_cost``; for invalid-markets the
        participant refund is pro-rated by this buy's share of the
        participant's total remaining cost. Legacy callers that pass a raw
        subgraph row (no FIFO fields) get treated as "never sold" via
        :meth:`_fifo_state`'s defaults, preserving the pre-rewrite formula.

        ``bet_amount`` is kept in the signature for backward compatibility
        but no longer used — all cost-basis math now flows through the
        FIFO state.

        Spec §8.1 calls out three prior bug sites this method now fixes:
          - Line 954 invalid-market refund used the signed raw amount as
            the numerator; sells made the ratio negative.
          - Line 971 booked ``-bet_amount`` as the loss; for a sell row
            (negative amount) this surfaced as a positive profit.
          - Line 978 winning payout share used the raw amount; sells
            shrank it and skewed the winning-total denominator.
        """
        if not market_ctx:
            return 0.0, None

        current_answer = market_ctx.get("current_answer")
        answer_finalized_ts = market_ctx.get("answer_finalized_ts")
        total_payout = market_ctx.get("total_payout") or 0.0
        total_traded = market_ctx.get("total_traded") or 0.0
        winning_total = market_ctx.get("winning_total_amount") or 0.0
        outcome_index = int(bet.get("outcomeIndex", 0))

        fifo = self._fifo_state(bet)
        original_cost = fifo["original_cost"] / WEI_TO_NATIVE
        allocated_proceeds = fifo["allocated_proceeds"] / WEI_TO_NATIVE
        allocated_cost = fifo["allocated_cost"] / WEI_TO_NATIVE
        remaining_cost = fifo["remaining_cost"] / WEI_TO_NATIVE
        participant_remaining_cost = (
            fifo["participant_remaining_cost"] / WEI_TO_NATIVE
        )
        realized_pnl = allocated_proceeds - allocated_cost

        # Unresolved market — only realised PnL is settled at this point.
        if current_answer is None:
            return realized_pnl, allocated_proceeds if allocated_proceeds > 0 else None

        # ZD#919: pending arbitration is provisional regardless of the
        # on-chain currentAnswer; treat as unresolved for the unsold leg.
        if market_ctx.get("is_pending_arbitration"):
            return realized_pnl, allocated_proceeds if allocated_proceeds > 0 else None

        # Reality.eth answers can flip during the dispute window — wait
        # for finalization before booking the unsold leg.
        finalized_ts = parse_timestamp(answer_finalized_ts)
        if finalized_ts is None or finalized_ts > self._now():
            return realized_pnl, allocated_proceeds if allocated_proceeds > 0 else None

        # Invalid-market refund path. Pro-rate by THIS buy's remaining
        # cost share of the participant's total remaining cost, not the
        # signed raw amount (which sells made negative — spec §8.1 line
        # 954 bug).
        if current_answer == INVALID_ANSWER_HEX:
            if total_payout == 0 or participant_remaining_cost <= 0:
                return realized_pnl, allocated_proceeds if allocated_proceeds > 0 else None
            refund_share = total_payout * (
                remaining_cost / participant_remaining_cost
            )
            payout = allocated_proceeds + refund_share
            return realized_pnl + (refund_share - remaining_cost), payout

        correct_answer = parse_current_answer(current_answer)
        if correct_answer is None:
            self.logger.warning(
                f"Malformed currentAnswer for bet {bet.get('id')!r}: "
                f"{current_answer!r}"
            )
            return realized_pnl, allocated_proceeds if allocated_proceeds > 0 else None

        # Losing bet — the unsold remainder is worthless; the realized
        # leg is whatever was already exited via sells. Spec §8.1 line 971
        # used ``-bet_amount``; for a sell that was a positive number,
        # mis-booking the loss as profit.
        if outcome_index != correct_answer:
            payout = allocated_proceeds if allocated_proceeds > 0 else None
            return realized_pnl - remaining_cost, payout

        # Winning bet. Until the participant has been credited a payout
        # the unsold winning side is still pending — book only the
        # realised leg.
        if total_payout == 0 or winning_total == 0:
            return realized_pnl, allocated_proceeds if allocated_proceeds > 0 else None

        # Use remaining_cost (the unsold winning cost basis) as the
        # numerator. winning_total is now the FIFO-aware denominator
        # (per the §8.1 line 867 fix above), so this stays consistent.
        payout_share = total_payout * (remaining_cost / winning_total)
        payout = allocated_proceeds + payout_share
        return realized_pnl + (payout_share - remaining_cost), payout

    def _get_prediction_status(
        self, bet: Dict, market_participant: Optional[Dict]
    ) -> str:
        """Hybrid status rule (spec §8.2 — mirror of Polystrat's helper).

        Tier 1 — Invalid market wins outright. The participant-level
        refund mechanism in Realitio compensates regardless of when the
        agent exited, so an invalid resolution classifies any buy as
        INVALID even if it was already fully sold.

        Tier 2 — A buy fully exited via sells (``remaining_shares <=
        SHARES_EPSILON_OMEN``) classifies by realized PnL sign:
        ``allocated_proceeds - allocated_cost > 0`` is WON,
        ``< 0`` is LOST, exact break-even is PENDING. The market's
        resolution state is irrelevant — the agent has no remaining
        position, their P&L is fully determined. This is the key shape
        difference from the pre-Phase-3 resolution-only logic: a sell-
        at-profit on a market that later resolves against the bet is
        now correctly tagged WON, not LOST.

        Tier 3 — Not fully exited: fall back to the resolution-based
        logic (unresolved / arbitration / unfinalized → PENDING; won-
        but-unredeemed → PENDING; won-and-redeemed → WON; otherwise
        LOST).

        Legacy callers passing a raw subgraph bet without FIFO state
        get ``original_shares == 0`` from :meth:`_fifo_state`'s
        defaults; tier 2's gate (``original_shares > 0``) trivially
        skips for them and the pre-rewrite behaviour is preserved.

        :param bet: bet dict, optionally enriched with FIFO state fields
        :param market_participant: optional market participant data (used
            by tier 3 to detect won-but-unredeemed → PENDING)
        :return: one of the ``BetStatus`` string values
        """
        fpmm = bet.get("fixedProductMarketMaker", {})
        current_answer = fpmm.get("currentAnswer")

        # Tier 1 — invalid market beats fully-exited, but only once the
        # answer is terminal: must be finalized AND not under arbitration
        # (a Kleros arbitrator can override an invalid sentinel; ZD#919).
        if current_answer == INVALID_ANSWER_HEX and not fpmm.get(
            "isPendingArbitration"
        ):
            answer_finalized_ts = parse_timestamp(
                fpmm.get("answerFinalizedTimestamp")
            )
            if (
                answer_finalized_ts is not None
                and answer_finalized_ts <= self._now()
            ):
                return BetStatus.INVALID.value
            # else: fall through (provisional sentinel, still in dispute window).

        # Tier 2 — fully exited via sells: realized PnL is the status.
        fifo = self._fifo_state(bet)
        if (
            fifo["original_shares"] > 0
            and fifo["remaining_shares"] <= SHARES_EPSILON_OMEN
        ):
            realized_pnl = fifo["allocated_proceeds"] - fifo["allocated_cost"]
            if realized_pnl > 0:
                return BetStatus.WON.value
            if realized_pnl < 0:
                return BetStatus.LOST.value
            return BetStatus.PENDING.value

        # Tier 3 — resolution-based fallback for not-fully-exited buys.

        # Market not resolved.
        if current_answer is None:
            return BetStatus.PENDING.value

        # ZD#919: a Kleros arbitration request suspends the 24h finalization
        # clock and nulls answerFinalizedTimestamp on the omen subgraph
        # (handleArbitrationRequest in Protofire's mapping). Treat the
        # market as pending regardless of currentAnswer for as long as
        # arbitration is active — which can be days or weeks.
        if fpmm.get("isPendingArbitration"):
            return BetStatus.PENDING.value

        # Bug A (ZD#919): Reality.eth currentAnswer can flip during the
        # 24h dispute window. Any answer (including the invalid sentinel)
        # is provisional until answerFinalizedTimestamp passes.
        # Note: this only checks Reality.eth finalization. The on-chain
        # ConditionalTokens payoutDenominator/payoutNumerators may not yet
        # reflect the final state — there is a brief window between
        # Reality finalization and RealitioProxy.resolve() being called
        # in which the displayed status may be terminal here but the CT
        # condition is still unresolved. The user-visible delta is small
        # (one trader cycle) and an RPC fallback is intentionally out of
        # scope; the subgraph is treated as the source of truth.
        answer_finalized_ts = parse_timestamp(fpmm.get("answerFinalizedTimestamp"))
        if answer_finalized_ts is None or answer_finalized_ts > self._now():
            return BetStatus.PENDING.value

        # Invalid sentinel was already handled in tier 1; any other
        # malformed answer reaches the int(...) below and degrades to
        # pending.
        correct_answer = parse_current_answer(current_answer)
        if correct_answer is None:
            self.logger.warning(
                f"Malformed currentAnswer for bet {bet.get('id')!r}: "
                f"{current_answer!r}"
            )
            return BetStatus.PENDING.value

        outcome_index = int(bet.get("outcomeIndex", 0))

        # Won — gate on participant-level totalPayout to flag the
        # brief won-but-unredeemed window as PENDING.
        if outcome_index == correct_answer:
            if market_participant:
                total_payout = (
                    float(market_participant.get("totalPayout", 0)) / WEI_TO_NATIVE
                )
                if total_payout == 0:
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
            dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
            return dt.strftime(ISO_TIMESTAMP_FORMAT)
        except Exception as e:
            self.logger.error(f"Error formatting timestamp {timestamp}: {str(e)}")
            return None

    def _get_ui_trading_strategy(self, selected_value: Optional[str]) -> Optional[str]:
        """Get the UI trading strategy."""
        if selected_value is None:
            return None

        if selected_value in (
            TradingStrategy.KELLY_CRITERION.value,
            TradingStrategy.KELLY_CRITERION_NO_CONF.value,
        ):
            return TradingStrategyUI.RISKY.value
        if selected_value in (
            TradingStrategy.FIXED_BET.value,
            TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value,
        ):
            return TradingStrategyUI.BALANCED.value
        return None
