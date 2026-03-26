"""Replay Polymarket bets against the new Kelly sizing logic."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from packages.valory.customs.kelly_criterion.kelly_criterion import run as run_kelly
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_MECH_RESPONSE_QUERY,
    GET_MECH_TOOL_FOR_QUESTION_QUERY,
    GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
)

USDC_DECIMALS = 10**6
DEFAULT_POLYMARKET_AGENTS_SUBGRAPH = (
    "https://predict-polymarket-agents.subgraph.autonolas.tech/"
)
DEFAULT_POLYGON_MECH_SUBGRAPH = (
    "https://api.subgraph.autonolas.tech/api/proxy/marketplace-polygon"
)
DEFAULT_MECH_FEE_USDC = 0.01
DEFAULT_BANKROLL_USDC = 15.0
DEFAULT_MIN_BET_USDC = 1.0
DEFAULT_MAX_BET_USDC = 5.0
DEFAULT_MIN_EDGE = 0.01
DEFAULT_MIN_ORACLE_PROB = 0.4
DEFAULT_N_BETS = 3
DEFAULT_GRID_POINTS = 500
DEFAULT_SYNTHETIC_ORDERBOOK_SIZE = 10_000.0
DEFAULT_TIMEOUT_SECONDS = 30
TRADER_AGENTS_QUERY = """
query GetAllPolystratAgents($first: Int!, $skip: Int!) {
  traderAgents(first: $first, skip: $skip, orderBy: blockTimestamp, orderDirection: asc) {
    id
    blockTimestamp
    lastActive
    totalBets
    totalTraded
    totalPayout
  }
}
"""


@dataclass(frozen=True)
class ReplayConfig:
    """Replay configuration."""

    start_timestamp: int
    end_timestamp: int
    bankroll_usdc: float = DEFAULT_BANKROLL_USDC
    floor_balance_usdc: float = 0.0
    min_bet_usdc: float = DEFAULT_MIN_BET_USDC
    max_bet_usdc: float = DEFAULT_MAX_BET_USDC
    n_bets: int = DEFAULT_N_BETS
    min_edge: float = DEFAULT_MIN_EDGE
    min_oracle_prob: float = DEFAULT_MIN_ORACLE_PROB
    fee_per_trade_usdc: float = DEFAULT_MECH_FEE_USDC
    mech_fee_usdc: float = DEFAULT_MECH_FEE_USDC
    grid_points: int = DEFAULT_GRID_POINTS
    synthetic_orderbook_size: float = DEFAULT_SYNTHETIC_ORDERBOOK_SIZE


@dataclass(frozen=True)
class SnapshotMetadata:
    """Metadata for a replay snapshot."""

    start_timestamp: int
    end_timestamp: int
    start_iso: str
    end_iso: str
    agents_subgraph_url: str
    mech_subgraph_url: str
    agent_count: int
    closed_bet_count: int
    capture_version: str = "v1"


@dataclass(frozen=True)
class HistoricalBet:
    """A resolved Polymarket bet used for replay."""

    agent_safe: str
    bet_id: str
    market_id: str
    condition_id: str
    title: str
    placed_at: int
    settled_at: int
    outcome_index: int
    winning_index: int
    amount_usdc: float
    shares: float
    payout_usdc: float
    executed_price: float
    actual_side: str
    actual_net_profit_usdc: float
    mech_tool: Optional[str] = None
    p_yes: Optional[float] = None
    p_no: Optional[float] = None
    mech_model: Optional[str] = None


@dataclass(frozen=True)
class ReplayDecision:
    """Counterfactual decision for a resolved bet."""

    would_bet: bool
    vote: Optional[int]
    side: Optional[str]
    kelly_bet_usdc: float
    expected_profit_usdc: float
    counterfactual_payout_usdc: float
    counterfactual_net_profit_usdc: float
    g_improvement: float
    p_yes: Optional[float]
    executed_price: float
    info: List[str]
    error: List[str]


@dataclass(frozen=True)
class AgentReplaySummary:
    """Replay summary per agent."""

    agent_safe: str
    closed_bets_count: int
    actual_bets_count: int
    counterfactual_bets_count: int
    actual_traded_usdc: float
    counterfactual_traded_usdc: float
    actual_profit_usdc: float
    counterfactual_profit_usdc: float
    actual_roi: Optional[float]
    counterfactual_roi: Optional[float]
    roi_delta: Optional[float]


class GraphQLClient:
    """Minimal GraphQL client."""

    def __init__(self, url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        """Initialize the client."""
        self.url = url
        self.timeout = timeout

    def query(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a GraphQL query."""
        response = requests.post(
            self.url,
            json={"query": query, "variables": variables},
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        errors = payload.get("errors") or []
        if errors:
            raise ValueError(f"GraphQL query failed: {errors}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected GraphQL payload: {payload}")
        return data


def start_of_week_utc(reference: date) -> int:
    """Return the UTC timestamp for Monday 00:00:00 of the reference week."""
    monday = reference - timedelta(days=reference.weekday())
    return int(datetime.combine(monday, time.min, tzinfo=timezone.utc).timestamp())


def end_of_day_utc(reference: date) -> int:
    """Return the UTC timestamp for the end of a UTC day."""
    return int(datetime.combine(reference + timedelta(days=1), time.min, tzinfo=timezone.utc).timestamp()) - 1


def chunk_date_range(
    start_date: date,
    end_date: date,
    chunk_days: int,
) -> List[Tuple[date, date]]:
    """Split an inclusive UTC date range into smaller inclusive chunks."""
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive.")
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    ranges: List[Tuple[date, date]] = []
    current_start = start_date
    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
        ranges.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return ranges


def usdc_to_micro(amount_usdc: float) -> int:
    """Convert USDC to micro units."""
    return int(round(amount_usdc * USDC_DECIMALS))


def safe_div(numerator: float, denominator: float) -> Optional[float]:
    """Divide safely."""
    if denominator == 0:
        return None
    return numerator / denominator


def compute_current_net_profit(
    payout_usdc: float,
    bet_amount_usdc: float,
    mech_fee_usdc: float,
) -> float:
    """Return net profit using the current closed-market accounting."""
    return payout_usdc - bet_amount_usdc - mech_fee_usdc


def synthesize_clob_inputs(
    actual_side: str,
    executed_price: float,
    size: float,
) -> Tuple[float, float, List[Dict[str, str]], List[Dict[str, str]]]:
    """Build a synthetic binary orderbook from the realized fill price."""
    clamped_price = max(min(executed_price, 0.999999), 0.000001)
    yes_price = clamped_price if actual_side == "yes" else 1.0 - clamped_price
    no_price = 1.0 - yes_price
    asks_yes = [{"price": f"{yes_price:.6f}", "size": f"{size:.6f}"}]
    asks_no = [{"price": f"{no_price:.6f}", "size": f"{size:.6f}"}]
    return yes_price, no_price, asks_yes, asks_no


def estimate_counterfactual_payout(
    winning_index: int,
    counterfactual_vote: Optional[int],
    counterfactual_bet_usdc: float,
    executed_price: float,
) -> float:
    """Estimate payout with a constant-price execution proxy."""
    if counterfactual_vote is None or counterfactual_bet_usdc <= 0:
        return 0.0
    if counterfactual_vote != winning_index:
        return 0.0
    price = max(min(executed_price, 0.999999), 0.000001)
    return counterfactual_bet_usdc / price


def replay_bet_with_kelly(
    bet: HistoricalBet,
    config: ReplayConfig,
) -> ReplayDecision:
    """Replay one bet with the new Kelly sizing logic."""
    if bet.p_yes is None:
        return ReplayDecision(
            would_bet=False,
            vote=None,
            side=None,
            kelly_bet_usdc=0.0,
            expected_profit_usdc=0.0,
            counterfactual_payout_usdc=0.0,
            counterfactual_net_profit_usdc=0.0,
            g_improvement=0.0,
            p_yes=None,
            executed_price=bet.executed_price,
            info=["No mech response found before bet timestamp."],
            error=[],
        )

    price_yes, price_no, asks_yes, asks_no = synthesize_clob_inputs(
        actual_side=bet.actual_side,
        executed_price=bet.executed_price,
        size=max(config.synthetic_orderbook_size, bet.shares, 1.0),
    )
    result = run_kelly(
        bankroll=usdc_to_micro(config.bankroll_usdc),
        p_yes=bet.p_yes,
        market_type="clob",
        floor_balance=usdc_to_micro(config.floor_balance_usdc),
        price_yes=price_yes,
        price_no=price_no,
        max_bet=usdc_to_micro(config.max_bet_usdc),
        min_bet=usdc_to_micro(config.min_bet_usdc),
        n_bets=config.n_bets,
        min_edge=config.min_edge,
        min_oracle_prob=config.min_oracle_prob,
        fee_per_trade=usdc_to_micro(config.fee_per_trade_usdc),
        grid_points=config.grid_points,
        token_decimals=6,
        orderbook_asks_yes=asks_yes,
        orderbook_asks_no=asks_no,
        min_order_shares=0.0,
    )
    bet_amount_micro = int(result.get("bet_amount", 0) or 0)
    vote = result.get("vote")
    would_bet = bet_amount_micro > 0 and vote in (0, 1)
    kelly_bet_usdc = bet_amount_micro / USDC_DECIMALS
    estimated_payout = estimate_counterfactual_payout(
        winning_index=bet.winning_index,
        counterfactual_vote=vote if would_bet else None,
        counterfactual_bet_usdc=kelly_bet_usdc,
        executed_price=(price_yes if vote == 0 else price_no) if vote in (0, 1) else bet.executed_price,
    )
    estimated_profit = (
        compute_current_net_profit(
            payout_usdc=estimated_payout,
            bet_amount_usdc=kelly_bet_usdc,
            mech_fee_usdc=config.mech_fee_usdc,
        )
        if would_bet
        else 0.0
    )
    side = "yes" if vote == 0 else "no" if vote == 1 else None
    return ReplayDecision(
        would_bet=would_bet,
        vote=vote if would_bet else None,
        side=side,
        kelly_bet_usdc=round(kelly_bet_usdc, 6),
        expected_profit_usdc=round((result.get("expected_profit", 0) or 0) / USDC_DECIMALS, 6),
        counterfactual_payout_usdc=round(estimated_payout, 6),
        counterfactual_net_profit_usdc=round(estimated_profit, 6),
        g_improvement=float(result.get("g_improvement", 0.0) or 0.0),
        p_yes=bet.p_yes,
        executed_price=bet.executed_price,
        info=list(result.get("info", [])),
        error=list(result.get("error", [])),
    )


def summarize_agent(
    agent_safe: str,
    rows: Sequence[Tuple[HistoricalBet, ReplayDecision]],
) -> AgentReplaySummary:
    """Summarize one agent replay."""
    actual_traded = sum(bet.amount_usdc for bet, _ in rows)
    simulated_traded = sum(decision.kelly_bet_usdc for _, decision in rows if decision.would_bet)
    actual_profit = sum(bet.actual_net_profit_usdc for bet, _ in rows)
    simulated_profit = sum(decision.counterfactual_net_profit_usdc for _, decision in rows)
    actual_cost_base = sum(bet.amount_usdc + DEFAULT_MECH_FEE_USDC for bet, _ in rows)
    simulated_cost_base = sum(
        decision.kelly_bet_usdc + DEFAULT_MECH_FEE_USDC for _, decision in rows if decision.would_bet
    )
    actual_roi = safe_div(actual_profit, actual_cost_base)
    simulated_roi = safe_div(simulated_profit, simulated_cost_base)
    roi_delta = None
    if actual_roi is not None and simulated_roi is not None:
        roi_delta = simulated_roi - actual_roi
    return AgentReplaySummary(
        agent_safe=agent_safe,
        closed_bets_count=len(rows),
        actual_bets_count=len(rows),
        counterfactual_bets_count=sum(1 for _, decision in rows if decision.would_bet),
        actual_traded_usdc=round(actual_traded, 6),
        counterfactual_traded_usdc=round(simulated_traded, 6),
        actual_profit_usdc=round(actual_profit, 6),
        counterfactual_profit_usdc=round(simulated_profit, 6),
        actual_roi=round(actual_roi, 6) if actual_roi is not None else None,
        counterfactual_roi=round(simulated_roi, 6) if simulated_roi is not None else None,
        roi_delta=round(roi_delta, 6) if roi_delta is not None else None,
    )


def build_historical_bet(
    agent_safe: str,
    participant_total_payout_micro: int,
    bet: Dict[str, Any],
    mech_fee_usdc: float,
) -> Optional[HistoricalBet]:
    """Build a replay bet from a subgraph bet payload."""
    question = bet.get("question") or {}
    resolution = question.get("resolution") or {}
    if not resolution:
        return None

    winning_index = int(resolution.get("winningIndex", -1))
    amount_usdc = float(bet.get("amount", 0)) / USDC_DECIMALS
    shares = float(bet.get("shares", 0)) / USDC_DECIMALS
    executed_price = amount_usdc / shares if shares > 0 else 0.5
    outcome_index = int(bet.get("outcomeIndex", 0))

    if winning_index < 0:
        payout_usdc = participant_total_payout_micro / USDC_DECIMALS
    elif outcome_index == winning_index:
        payout_usdc = shares
    else:
        payout_usdc = 0.0

    actual_side = "yes" if outcome_index == 0 else "no"
    actual_profit = compute_current_net_profit(
        payout_usdc=payout_usdc,
        bet_amount_usdc=amount_usdc,
        mech_fee_usdc=mech_fee_usdc,
    )
    return HistoricalBet(
        agent_safe=agent_safe.lower(),
        bet_id=str(bet.get("id", "")),
        market_id=str((question.get("questionId") or "")),
        condition_id=str((question.get("id") or "")),
        title=str(((question.get("metadata") or {}).get("title") or "")),
        placed_at=int(bet.get("blockTimestamp", 0)),
        settled_at=int(resolution.get("blockTimestamp", 0)),
        outcome_index=outcome_index,
        winning_index=winning_index,
        amount_usdc=round(amount_usdc, 6),
        shares=round(shares, 6),
        payout_usdc=round(payout_usdc, 6),
        executed_price=round(executed_price, 6),
        actual_side=actual_side,
        actual_net_profit_usdc=round(actual_profit, 6),
    )


def attach_mech_data(
    mech_client: GraphQLClient,
    bet: HistoricalBet,
) -> HistoricalBet:
    """Attach mech response metadata to a bet."""
    response_data = mech_client.query(
        GET_MECH_RESPONSE_QUERY,
        {
            "sender": bet.agent_safe.lower(),
            "questionTitle": bet.title,
            "blockTimestamp_lte": str(bet.placed_at),
        },
    )
    requests_list = response_data.get("requests") or []
    p_yes = None
    p_no = None
    mech_model = None
    if requests_list:
        deliveries = (requests_list[0] or {}).get("deliveries") or []
        if deliveries:
            raw_response = deliveries[0].get("toolResponse")
            mech_model = deliveries[0].get("model")
            if raw_response:
                try:
                    parsed = json.loads(raw_response)
                    if isinstance(parsed, dict):
                        p_yes = parsed.get("p_yes")
                        p_no = parsed.get("p_no")
                except json.JSONDecodeError:
                    pass

    tool_name = None
    tool_data = mech_client.query(
        GET_MECH_TOOL_FOR_QUESTION_QUERY,
        {
            "sender": bet.agent_safe.lower(),
            "questionTitle": bet.title,
            "blockTimestamp_lte": str(bet.placed_at),
        },
    )
    sender_data = tool_data.get("sender") or {}
    tool_requests = sender_data.get("requests") or []
    if tool_requests:
        parsed_request = (tool_requests[0] or {}).get("parsedRequest") or {}
        tool_name = parsed_request.get("tool")

    return HistoricalBet(
        **{
            **asdict(bet),
            "mech_tool": tool_name,
            "p_yes": float(p_yes) if p_yes is not None else None,
            "p_no": float(p_no) if p_no is not None else None,
            "mech_model": mech_model,
        }
    )


def fetch_all_polystrat_agents(agent_client: GraphQLClient) -> List[str]:
    """Fetch all polystrat agent safes from the subgraph."""
    safes: List[str] = []
    skip = 0
    batch_size = 500
    while True:
        data = agent_client.query(
            TRADER_AGENTS_QUERY,
            {"first": batch_size, "skip": skip},
        )
        batch = data.get("traderAgents") or []
        if not batch:
            break
        safes.extend(str(agent["id"]).lower() for agent in batch if agent.get("id"))
        if len(batch) < batch_size:
            break
        skip += batch_size
    return safes


def fetch_active_polystrat_agents(
    agent_client: GraphQLClient,
    start_timestamp: int,
) -> List[str]:
    """Fetch polystrat agents that appear active for the replay window."""
    safes: List[str] = []
    skip = 0
    batch_size = 500
    while True:
        data = agent_client.query(
            TRADER_AGENTS_QUERY,
            {"first": batch_size, "skip": skip},
        )
        batch = data.get("traderAgents") or []
        if not batch:
            break
        for agent in batch:
            safe = str(agent.get("id") or "").lower()
            last_active = int(agent.get("lastActive") or 0)
            created_at = int(agent.get("blockTimestamp") or 0)
            total_bets = int(agent.get("totalBets") or 0)
            if not safe or total_bets <= 0:
                continue
            if last_active >= start_timestamp or created_at >= start_timestamp:
                safes.append(safe)
        if len(batch) < batch_size:
            break
        skip += batch_size
    return safes


def fetch_closed_bets_for_agent(
    agent_client: GraphQLClient,
    mech_client: GraphQLClient,
    agent_safe: str,
    config: ReplayConfig,
) -> List[HistoricalBet]:
    """Fetch resolved bets placed in the configured time window."""
    bets: List[HistoricalBet] = []
    skip = 0
    batch_size = 500
    while True:
        data = agent_client.query(
            GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
            {"id": agent_safe.lower(), "first": batch_size, "skip": skip},
        )
        participants = data.get("marketParticipants") or []
        if not participants:
            break
        for participant in participants:
            participant_total_payout = int(participant.get("totalPayout", 0) or 0)
            for raw_bet in participant.get("bets") or []:
                historical_bet = build_historical_bet(
                    agent_safe=agent_safe,
                    participant_total_payout_micro=participant_total_payout,
                    bet=raw_bet,
                    mech_fee_usdc=config.mech_fee_usdc,
                )
                if historical_bet is None:
                    continue
                if not (config.start_timestamp <= historical_bet.placed_at <= config.end_timestamp):
                    continue
                enriched_bet = attach_mech_data(mech_client, historical_bet)
                bets.append(enriched_bet)
        if len(participants) < batch_size:
            break
        skip += batch_size
    bets.sort(key=lambda item: item.placed_at)
    return bets


def replay_agents(
    agent_safes: Iterable[str],
    agent_client: GraphQLClient,
    mech_client: GraphQLClient,
    config: ReplayConfig,
) -> Dict[str, Any]:
    """Replay all requested agents."""
    rows_by_agent: Dict[str, List[Tuple[HistoricalBet, ReplayDecision]]] = {}
    detailed_rows: List[Dict[str, Any]] = []
    agent_safes_list = list(agent_safes)
    total_agents = len(agent_safes_list)
    for index, agent_safe in enumerate(agent_safes_list, start=1):
        print(
            f"[polystrat-replay] fetching agent {index}/{total_agents}: {agent_safe}",
            file=sys.stderr,
            flush=True,
        )
        bets = fetch_closed_bets_for_agent(agent_client, mech_client, agent_safe, config)
        rows: List[Tuple[HistoricalBet, ReplayDecision]] = []
        for bet in bets:
            decision = replay_bet_with_kelly(bet, config)
            rows.append((bet, decision))
            detailed_rows.append(
                {
                    "agent_safe": agent_safe.lower(),
                    "bet_id": bet.bet_id,
                    "market_title": bet.title,
                    "placed_at": bet.placed_at,
                    "settled_at": bet.settled_at,
                    "actual_side": bet.actual_side,
                    "actual_bet_usdc": bet.amount_usdc,
                    "actual_payout_usdc": bet.payout_usdc,
                    "actual_net_profit_usdc": bet.actual_net_profit_usdc,
                    "executed_price": bet.executed_price,
                    "winning_index": bet.winning_index,
                    "mech_tool": bet.mech_tool,
                    "p_yes": bet.p_yes,
                    "counterfactual_would_bet": decision.would_bet,
                    "counterfactual_side": decision.side,
                    "counterfactual_bet_usdc": decision.kelly_bet_usdc,
                    "counterfactual_payout_usdc": decision.counterfactual_payout_usdc,
                    "counterfactual_net_profit_usdc": decision.counterfactual_net_profit_usdc,
                    "roi_delta_vs_actual_trade_usdc": round(
                        decision.counterfactual_net_profit_usdc - bet.actual_net_profit_usdc, 6
                    ),
                    "g_improvement": round(decision.g_improvement, 8),
                    "info": decision.info,
                    "error": decision.error,
                }
            )
        rows_by_agent[agent_safe.lower()] = rows

    summaries = [
        summarize_agent(agent_safe, rows)
        for agent_safe, rows in rows_by_agent.items()
        if rows
    ]
    aggregate_summary = summarize_agent(
        agent_safe="all_polystrat_agents",
        rows=[row for rows in rows_by_agent.values() for row in rows],
    )
    return {
        "window": {
            "start_timestamp": config.start_timestamp,
            "end_timestamp": config.end_timestamp,
            "start_iso": datetime.fromtimestamp(config.start_timestamp, tz=timezone.utc).isoformat(),
            "end_iso": datetime.fromtimestamp(config.end_timestamp, tz=timezone.utc).isoformat(),
        },
        "assumptions": {
            "bankroll_usdc": config.bankroll_usdc,
            "floor_balance_usdc": config.floor_balance_usdc,
            "min_bet_usdc": config.min_bet_usdc,
            "max_bet_usdc": config.max_bet_usdc,
            "n_bets": config.n_bets,
            "min_edge": config.min_edge,
            "min_oracle_prob": config.min_oracle_prob,
            "fee_per_trade_usdc": config.fee_per_trade_usdc,
            "mech_fee_usdc": config.mech_fee_usdc,
            "historical_clob_proxy": "realized_execution_price_from_amount_div_shares",
        },
        "aggregate_summary": asdict(aggregate_summary),
        "agent_summaries": [asdict(summary) for summary in summaries],
        "closed_bet_replay": detailed_rows,
    }


def create_snapshot(
    agent_safes: Iterable[str],
    agent_client: GraphQLClient,
    mech_client: GraphQLClient,
    config: ReplayConfig,
    agents_subgraph_url: str,
    mech_subgraph_url: str,
) -> Dict[str, Any]:
    """Create a reusable local snapshot for a fixed replay window."""
    agent_safes_list = list(agent_safes)
    snapshot_rows: List[Dict[str, Any]] = []
    for index, agent_safe in enumerate(agent_safes_list, start=1):
        print(
            f"[polystrat-snapshot] fetching agent {index}/{len(agent_safes_list)}: {agent_safe}",
            file=sys.stderr,
            flush=True,
        )
        bets = fetch_closed_bets_for_agent(agent_client, mech_client, agent_safe, config)
        snapshot_rows.extend(asdict(bet) for bet in bets)

    metadata = SnapshotMetadata(
        start_timestamp=config.start_timestamp,
        end_timestamp=config.end_timestamp,
        start_iso=datetime.fromtimestamp(config.start_timestamp, tz=timezone.utc).isoformat(),
        end_iso=datetime.fromtimestamp(config.end_timestamp, tz=timezone.utc).isoformat(),
        agents_subgraph_url=agents_subgraph_url,
        mech_subgraph_url=mech_subgraph_url,
        agent_count=len(agent_safes_list),
        closed_bet_count=len(snapshot_rows),
    )
    return {
        "snapshot_metadata": asdict(metadata),
        "bets": snapshot_rows,
    }


def merge_snapshots(snapshots: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge multiple snapshot payloads into one deduplicated snapshot."""
    if not snapshots:
        raise ValueError("At least one snapshot is required for merge.")

    merged_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    start_timestamp: Optional[int] = None
    end_timestamp: Optional[int] = None
    start_iso: Optional[str] = None
    end_iso: Optional[str] = None
    agents_urls: List[str] = []
    mech_urls: List[str] = []
    agent_safes = set()

    for snapshot in snapshots:
        metadata = snapshot.get("snapshot_metadata", {})
        snapshot_rows = snapshot.get("bets", [])
        if not isinstance(snapshot_rows, list):
            raise ValueError("Snapshot bets must be a list.")

        current_start = metadata.get("start_timestamp")
        current_end = metadata.get("end_timestamp")
        if isinstance(current_start, int) and (start_timestamp is None or current_start < start_timestamp):
            start_timestamp = current_start
            start_iso = metadata.get("start_iso")
        if isinstance(current_end, int) and (end_timestamp is None or current_end > end_timestamp):
            end_timestamp = current_end
            end_iso = metadata.get("end_iso")

        agent_url = metadata.get("agents_subgraph_url")
        if isinstance(agent_url, str) and agent_url:
            agents_urls.append(agent_url)
        mech_url = metadata.get("mech_subgraph_url")
        if isinstance(mech_url, str) and mech_url:
            mech_urls.append(mech_url)

        for row in snapshot_rows:
            agent_safe = str(row.get("agent_safe", "")).lower()
            bet_id = str(row.get("bet_id", ""))
            if not bet_id:
                raise ValueError("Snapshot row missing bet_id.")
            key = (agent_safe, bet_id)
            merged_rows[key] = row
            if agent_safe:
                agent_safes.add(agent_safe)

    if start_timestamp is None or end_timestamp is None or start_iso is None or end_iso is None:
        raise ValueError("Snapshot metadata missing date bounds.")

    unique_agent_urls = sorted(set(agents_urls))
    unique_mech_urls = sorted(set(mech_urls))
    bets = sorted(
        merged_rows.values(),
        key=lambda row: (
            int(row.get("placed_at", 0)),
            int(row.get("settled_at", 0)),
            str(row.get("agent_safe", "")).lower(),
            str(row.get("bet_id", "")),
        ),
    )
    metadata = SnapshotMetadata(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        start_iso=start_iso,
        end_iso=end_iso,
        agents_subgraph_url=unique_agent_urls[0] if len(unique_agent_urls) == 1 else "multiple",
        mech_subgraph_url=unique_mech_urls[0] if len(unique_mech_urls) == 1 else "multiple",
        agent_count=len(agent_safes),
        closed_bet_count=len(bets),
        capture_version=f"v1-merged-{len(snapshots)}",
    )
    return {
        "snapshot_metadata": asdict(metadata),
        "bets": bets,
    }


def replay_from_snapshot(snapshot: Dict[str, Any], config: ReplayConfig) -> Dict[str, Any]:
    """Replay from a local snapshot with no network access."""
    raw_bets = snapshot.get("bets", [])
    if raw_bets:
        bets = [HistoricalBet(**row) for row in raw_bets]
    else:
        legacy_rows = snapshot.get("closed_bet_replay", [])
        bets = []
        for row in legacy_rows:
            actual_side = row.get("actual_side", "yes")
            p_yes = row.get("p_yes")
            bets.append(
                HistoricalBet(
                    agent_safe=str(row.get("agent_safe", "")),
                    bet_id=str(row.get("bet_id", "")),
                    market_id="",
                    condition_id="",
                    title=str(row.get("market_title", "")),
                    placed_at=int(row.get("placed_at", 0)),
                    settled_at=int(row.get("settled_at", 0)),
                    outcome_index=0 if actual_side == "yes" else 1,
                    winning_index=int(row.get("winning_index", -1)),
                    amount_usdc=float(row.get("actual_bet_usdc", 0.0)),
                    shares=safe_div(
                        float(row.get("actual_bet_usdc", 0.0)),
                        float(row.get("executed_price", 0.5)),
                    )
                    or 0.0,
                    payout_usdc=float(row.get("actual_payout_usdc", 0.0)),
                    executed_price=float(row.get("executed_price", 0.5)),
                    actual_side=str(actual_side),
                    actual_net_profit_usdc=float(row.get("actual_net_profit_usdc", 0.0)),
                    mech_tool=row.get("mech_tool"),
                    p_yes=float(p_yes) if p_yes is not None else None,
                    p_no=(1.0 - float(p_yes)) if p_yes is not None else None,
                    mech_model=None,
                )
            )
    rows_by_agent: Dict[str, List[Tuple[HistoricalBet, ReplayDecision]]] = {}
    detailed_rows: List[Dict[str, Any]] = []
    for bet in bets:
        decision = replay_bet_with_kelly(bet, config)
        rows_by_agent.setdefault(bet.agent_safe, []).append((bet, decision))
        detailed_rows.append(
            {
                "agent_safe": bet.agent_safe,
                "bet_id": bet.bet_id,
                "market_title": bet.title,
                "placed_at": bet.placed_at,
                "settled_at": bet.settled_at,
                "actual_side": bet.actual_side,
                "actual_bet_usdc": bet.amount_usdc,
                "actual_payout_usdc": bet.payout_usdc,
                "actual_net_profit_usdc": bet.actual_net_profit_usdc,
                "executed_price": bet.executed_price,
                "winning_index": bet.winning_index,
                "mech_tool": bet.mech_tool,
                "p_yes": bet.p_yes,
                "counterfactual_would_bet": decision.would_bet,
                "counterfactual_side": decision.side,
                "counterfactual_bet_usdc": decision.kelly_bet_usdc,
                "counterfactual_payout_usdc": decision.counterfactual_payout_usdc,
                "counterfactual_net_profit_usdc": decision.counterfactual_net_profit_usdc,
                "roi_delta_vs_actual_trade_usdc": round(
                    decision.counterfactual_net_profit_usdc - bet.actual_net_profit_usdc, 6
                ),
                "g_improvement": round(decision.g_improvement, 8),
                "info": decision.info,
                "error": decision.error,
            }
        )

    summaries = [
        summarize_agent(agent_safe, rows)
        for agent_safe, rows in rows_by_agent.items()
        if rows
    ]
    aggregate_summary = summarize_agent(
        agent_safe="all_polystrat_agents",
        rows=[row for rows in rows_by_agent.values() for row in rows],
    )
    window = snapshot.get("snapshot_metadata", {})
    return {
        "window": {
            "start_timestamp": window.get("start_timestamp", config.start_timestamp),
            "end_timestamp": window.get("end_timestamp", config.end_timestamp),
            "start_iso": window.get(
                "start_iso",
                datetime.fromtimestamp(config.start_timestamp, tz=timezone.utc).isoformat(),
            ),
            "end_iso": window.get(
                "end_iso",
                datetime.fromtimestamp(config.end_timestamp, tz=timezone.utc).isoformat(),
            ),
        },
        "snapshot_metadata": snapshot.get("snapshot_metadata", {}),
        "assumptions": {
            "bankroll_usdc": config.bankroll_usdc,
            "floor_balance_usdc": config.floor_balance_usdc,
            "min_bet_usdc": config.min_bet_usdc,
            "max_bet_usdc": config.max_bet_usdc,
            "n_bets": config.n_bets,
            "min_edge": config.min_edge,
            "min_oracle_prob": config.min_oracle_prob,
            "fee_per_trade_usdc": config.fee_per_trade_usdc,
            "mech_fee_usdc": config.mech_fee_usdc,
            "historical_clob_proxy": "realized_execution_price_from_amount_div_shares",
            "data_source": "local_snapshot",
        },
        "aggregate_summary": asdict(aggregate_summary),
        "agent_summaries": [asdict(summary) for summary in summaries],
        "closed_bet_replay": detailed_rows,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    today_utc = datetime.now(timezone.utc).date()
    parser = argparse.ArgumentParser(
        description="Replay this week's closed Polystrat bets against the new Kelly sizing logic."
    )
    parser.add_argument("--agent-safe", action="append", default=[], help="Polystrat agent safe to replay. Repeatable.")
    parser.add_argument("--all-agents", action="store_true", help="Discover all Polystrat agents from the subgraph.")
    parser.add_argument("--start-date", default=(today_utc - timedelta(days=today_utc.weekday())).isoformat(), help="UTC start date (YYYY-MM-DD). Defaults to Monday of the current UTC week.")
    parser.add_argument("--end-date", default=today_utc.isoformat(), help="UTC end date (YYYY-MM-DD). Defaults to today in UTC.")
    parser.add_argument("--agents-subgraph-url", default=DEFAULT_POLYMARKET_AGENTS_SUBGRAPH)
    parser.add_argument("--mech-subgraph-url", default=DEFAULT_POLYGON_MECH_SUBGRAPH)
    parser.add_argument("--bankroll-usdc", type=float, default=DEFAULT_BANKROLL_USDC)
    parser.add_argument("--floor-balance-usdc", type=float, default=0.0)
    parser.add_argument("--min-bet-usdc", type=float, default=DEFAULT_MIN_BET_USDC)
    parser.add_argument("--max-bet-usdc", type=float, default=DEFAULT_MAX_BET_USDC)
    parser.add_argument("--n-bets", type=int, default=DEFAULT_N_BETS)
    parser.add_argument("--min-edge", type=float, default=DEFAULT_MIN_EDGE)
    parser.add_argument("--min-oracle-prob", type=float, default=DEFAULT_MIN_ORACLE_PROB)
    parser.add_argument("--fee-per-trade-usdc", type=float, default=DEFAULT_MECH_FEE_USDC)
    parser.add_argument("--mech-fee-usdc", type=float, default=DEFAULT_MECH_FEE_USDC)
    parser.add_argument("--grid-points", type=int, default=DEFAULT_GRID_POINTS)
    parser.add_argument("--output", help="Optional JSON file path for the replay results.")
    parser.add_argument(
        "--snapshot-output",
        help="Optional path to save the enriched fixed-window dataset for later offline retuning.",
    )
    parser.add_argument(
        "--input-snapshot",
        help="Replay from a previously saved snapshot JSON instead of refetching live data.",
    )
    return parser.parse_args(argv)


def _parse_utc_date(raw: str) -> date:
    """Parse a UTC date argument."""
    return date.fromisoformat(raw)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the replay CLI."""
    args = parse_args(argv)
    start_date = _parse_utc_date(args.start_date)
    end_date = _parse_utc_date(args.end_date)
    config = ReplayConfig(
        start_timestamp=int(datetime.combine(start_date, time.min, tzinfo=timezone.utc).timestamp()),
        end_timestamp=end_of_day_utc(end_date),
        bankroll_usdc=args.bankroll_usdc,
        floor_balance_usdc=args.floor_balance_usdc,
        min_bet_usdc=args.min_bet_usdc,
        max_bet_usdc=args.max_bet_usdc,
        n_bets=args.n_bets,
        min_edge=args.min_edge,
        min_oracle_prob=args.min_oracle_prob,
        fee_per_trade_usdc=args.fee_per_trade_usdc,
        mech_fee_usdc=args.mech_fee_usdc,
        grid_points=args.grid_points,
    )
    if args.input_snapshot:
        snapshot = json.loads(Path(args.input_snapshot).read_text(encoding="utf-8"))
        results = replay_from_snapshot(snapshot, config)
    else:
        agent_client = GraphQLClient(args.agents_subgraph_url)
        mech_client = GraphQLClient(args.mech_subgraph_url)
        agent_safes = [safe.lower() for safe in args.agent_safe]
        if args.all_agents:
            discovered = fetch_active_polystrat_agents(agent_client, config.start_timestamp)
            merged = dict.fromkeys([*agent_safes, *discovered])
            agent_safes = list(merged.keys())
        if not agent_safes:
            raise SystemExit("Provide at least one --agent-safe or use --all-agents.")

        snapshot = None
        if args.snapshot_output:
            snapshot = create_snapshot(
                agent_safes=agent_safes,
                agent_client=agent_client,
                mech_client=mech_client,
                config=config,
                agents_subgraph_url=args.agents_subgraph_url,
                mech_subgraph_url=args.mech_subgraph_url,
            )
            Path(args.snapshot_output).write_text(
                json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(
                f"[polystrat-snapshot] wrote snapshot to {args.snapshot_output}",
                file=sys.stderr,
                flush=True,
            )
            results = replay_from_snapshot(snapshot, config)
        else:
            results = replay_agents(agent_safes, agent_client, mech_client, config)

    rendered = json.dumps(results, indent=2, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(rendered)
            output_file.write("\n")
    print(rendered)
    return 0
