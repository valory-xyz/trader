"""Fetch chunked Polystrat snapshots and merge them into one replayable dataset."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.valory.skills.agent_performance_summary_abci.replay.polystrat_kelly import (
    DEFAULT_BANKROLL_USDC,
    DEFAULT_GRID_POINTS,
    DEFAULT_MAX_BET_USDC,
    DEFAULT_MECH_FEE_USDC,
    DEFAULT_MIN_BET_USDC,
    DEFAULT_MIN_EDGE,
    DEFAULT_MIN_ORACLE_PROB,
    DEFAULT_N_BETS,
    DEFAULT_POLYGON_MECH_SUBGRAPH,
    DEFAULT_POLYMARKET_AGENTS_SUBGRAPH,
    GraphQLClient,
    ReplayConfig,
    SnapshotMetadata,
    chunk_date_range,
    end_of_day_utc,
    fetch_active_polystrat_agents,
    fetch_closed_bets_for_agent,
    merge_snapshots,
    replay_from_snapshot,
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Fetch Polystrat snapshots in chunks, merge them, and optionally replay offline."
    )
    parser.add_argument("--agent-safe", action="append", default=[], help="Polystrat agent safe to include. Repeatable.")
    parser.add_argument("--all-agents", action="store_true", help="Discover active Polystrat agents for the overall window.")
    parser.add_argument(
        "--rediscover-per-chunk",
        action="store_true",
        help="Rediscover active agents for each chunk instead of reusing one overall active list.",
    )
    parser.add_argument("--start-date", required=True, help="UTC start date (YYYY-MM-DD).")
    parser.add_argument("--end-date", required=True, help="UTC end date (YYYY-MM-DD).")
    parser.add_argument("--chunk-days", type=int, default=7, help="Chunk size in days. Defaults to 7.")
    parser.add_argument("--agents-subgraph-url", default=DEFAULT_POLYMARKET_AGENTS_SUBGRAPH)
    parser.add_argument("--mech-subgraph-url", default=DEFAULT_POLYGON_MECH_SUBGRAPH)
    parser.add_argument("--output-snapshot", required=True, help="Path for the merged snapshot JSON.")
    parser.add_argument("--output", help="Optional path for offline replay results from the merged snapshot.")
    parser.add_argument("--chunks-dir", help="Optional directory for the per-chunk snapshot JSON files.")
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
    return parser.parse_args()


def _parse_utc_date(raw: str) -> date:
    """Parse a UTC date argument."""
    return date.fromisoformat(raw)


def _chunk_path(chunks_dir: str, index: int, chunk_start: date, chunk_end: date) -> Path:
    """Build the checkpoint path for a chunk."""
    return Path(chunks_dir) / f"chunk_{index:02d}_{chunk_start.isoformat()}_{chunk_end.isoformat()}.json"


def _initialize_chunk_payload(
    *,
    agent_safes: List[str],
    config: ReplayConfig,
    agents_subgraph_url: str,
    mech_subgraph_url: str,
) -> Dict[str, Any]:
    """Build an empty resumable chunk payload."""
    metadata = SnapshotMetadata(
        start_timestamp=config.start_timestamp,
        end_timestamp=config.end_timestamp,
        start_iso=datetime.fromtimestamp(config.start_timestamp, tz=timezone.utc).isoformat(),
        end_iso=datetime.fromtimestamp(config.end_timestamp, tz=timezone.utc).isoformat(),
        agents_subgraph_url=agents_subgraph_url,
        mech_subgraph_url=mech_subgraph_url,
        agent_count=len(agent_safes),
        closed_bet_count=0,
        capture_version="v1-resumable-chunk",
    )
    return {
        "snapshot_metadata": asdict(metadata),
        "chunk_progress": {
            "agent_safes": agent_safes,
            "completed_agents": [],
        },
        "bets": [],
    }


def _load_or_initialize_chunk_payload(
    *,
    chunk_path: Path,
    agent_safes: List[str],
    config: ReplayConfig,
    agents_subgraph_url: str,
    mech_subgraph_url: str,
) -> Dict[str, Any]:
    """Load a chunk checkpoint if present, otherwise initialize a new one."""
    if chunk_path.exists():
        payload = json.loads(chunk_path.read_text(encoding="utf-8"))
        progress = payload.setdefault("chunk_progress", {})
        progress.setdefault("agent_safes", agent_safes)
        progress.setdefault("completed_agents", [])
        payload.setdefault("bets", [])
        return payload
    return _initialize_chunk_payload(
        agent_safes=agent_safes,
        config=config,
        agents_subgraph_url=agents_subgraph_url,
        mech_subgraph_url=mech_subgraph_url,
    )


def _write_chunk_payload(chunk_path: Path, payload: Dict[str, Any]) -> None:
    """Persist the current chunk payload to disk."""
    payload["snapshot_metadata"]["closed_bet_count"] = len(payload.get("bets", []))
    chunk_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    """Run the chunked snapshot workflow."""
    args = parse_args()
    start_date = _parse_utc_date(args.start_date)
    end_date = _parse_utc_date(args.end_date)
    ranges = chunk_date_range(start_date, end_date, args.chunk_days)
    if args.chunks_dir:
        Path(args.chunks_dir).mkdir(parents=True, exist_ok=True)

    agent_client = GraphQLClient(args.agents_subgraph_url)
    mech_client = GraphQLClient(args.mech_subgraph_url)
    snapshots = []
    base_agent_safes = [safe.lower() for safe in args.agent_safe]

    if args.all_agents and not args.rediscover_per_chunk:
        overall_config = ReplayConfig(
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
        discovered = fetch_active_polystrat_agents(agent_client, overall_config.start_timestamp)
        merged = dict.fromkeys([*base_agent_safes, *discovered])
        base_agent_safes = list(merged.keys())
        print(
            f"[polystrat-chunked] discovered {len(base_agent_safes)} active agents for the overall window",
            file=sys.stderr,
            flush=True,
        )

    for index, (chunk_start, chunk_end) in enumerate(ranges, start=1):
        config = ReplayConfig(
            start_timestamp=int(datetime.combine(chunk_start, time.min, tzinfo=timezone.utc).timestamp()),
            end_timestamp=end_of_day_utc(chunk_end),
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
        agent_safes = list(base_agent_safes)
        if args.all_agents and args.rediscover_per_chunk:
            discovered = fetch_active_polystrat_agents(agent_client, config.start_timestamp)
            merged = dict.fromkeys([*agent_safes, *discovered])
            agent_safes = list(merged.keys())
        if not agent_safes:
            raise SystemExit("Provide at least one --agent-safe or use --all-agents.")

        print(
            f"[polystrat-chunked] chunk {index}/{len(ranges)}: {chunk_start.isoformat()} -> {chunk_end.isoformat()} ({len(agent_safes)} agents)",
            file=sys.stderr,
            flush=True,
        )
        chunk_path = (
            _chunk_path(args.chunks_dir, index, chunk_start, chunk_end)
            if args.chunks_dir
            else None
        )
        chunk_payload = (
            _load_or_initialize_chunk_payload(
                chunk_path=chunk_path,
                agent_safes=agent_safes,
                config=config,
                agents_subgraph_url=args.agents_subgraph_url,
                mech_subgraph_url=args.mech_subgraph_url,
            )
            if chunk_path is not None
            else _initialize_chunk_payload(
                agent_safes=agent_safes,
                config=config,
                agents_subgraph_url=args.agents_subgraph_url,
                mech_subgraph_url=args.mech_subgraph_url,
            )
        )
        completed_agents = {
            safe.lower()
            for safe in chunk_payload.get("chunk_progress", {}).get("completed_agents", [])
        }
        chunk_bets = list(chunk_payload.get("bets", []))

        if completed_agents:
            print(
                f"[polystrat-chunked] resuming chunk {index} with {len(completed_agents)} completed agents and {len(chunk_bets)} bets",
                file=sys.stderr,
                flush=True,
            )

        for agent_position, agent_safe in enumerate(agent_safes, start=1):
            if agent_safe in completed_agents:
                continue
            print(
                f"[polystrat-snapshot] fetching agent {agent_position}/{len(agent_safes)}: {agent_safe}",
                file=sys.stderr,
                flush=True,
            )
            bets = fetch_closed_bets_for_agent(agent_client, mech_client, agent_safe, config)
            chunk_bets.extend(asdict(bet) for bet in bets)
            completed_agents.add(agent_safe)
            chunk_payload["bets"] = chunk_bets
            chunk_payload["chunk_progress"]["completed_agents"] = sorted(completed_agents)
            if chunk_path is not None:
                _write_chunk_payload(chunk_path, chunk_payload)

        snapshots.append(
            {
                "snapshot_metadata": chunk_payload["snapshot_metadata"],
                "bets": chunk_bets,
            }
        )
        if chunk_path is not None:
            print(f"[polystrat-chunked] wrote {chunk_path}", file=sys.stderr, flush=True)

    merged_snapshot = merge_snapshots(snapshots)
    output_snapshot = Path(args.output_snapshot)
    output_snapshot.parent.mkdir(parents=True, exist_ok=True)
    output_snapshot.write_text(
        json.dumps(merged_snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[polystrat-chunked] wrote merged snapshot to {output_snapshot}", file=sys.stderr, flush=True)

    if args.output:
        replay_config = ReplayConfig(
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
        results = replay_from_snapshot(merged_snapshot, replay_config)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[polystrat-chunked] wrote replay results to {output_path}", file=sys.stderr, flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
