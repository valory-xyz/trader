"""Segment a polystrat replay output by negRisk market type.

Usage:
    python scripts/segment_replay_by_neg_risk.py \
        --replay reports/.../replay_mop_01.json \
        --enriched-snapshot reports/.../snapshot_enriched.json \
        --output reports/.../segmented_mop_01.json
"""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_MECH_FEE = 0.01


def safe_div(num: float, den: float) -> Optional[float]:
    """Divide safely."""
    return num / den if den != 0 else None


def compute_segment_stats(
    label: str,
    rows: Sequence[Dict[str, Any]],
    mech_fee: float = DEFAULT_MECH_FEE,
) -> Dict[str, Any]:
    """Compute aggregate statistics for a segment of replay rows."""
    n = len(rows)
    n_cf = sum(1 for r in rows if r.get("counterfactual_would_bet"))
    n_yes = sum(
        1 for r in rows
        if r.get("counterfactual_would_bet") and r.get("counterfactual_side") == "yes"
    )
    n_no = sum(
        1 for r in rows
        if r.get("counterfactual_would_bet") and r.get("counterfactual_side") == "no"
    )
    n_switch = sum(
        1 for r in rows
        if r.get("counterfactual_would_bet")
        and r.get("counterfactual_side") != r.get("actual_side")
    )

    act_traded = sum(r["actual_bet_usdc"] for r in rows)
    act_profit = sum(r["actual_net_profit_usdc"] for r in rows)
    cf_traded = sum(
        r["counterfactual_bet_usdc"] for r in rows if r.get("counterfactual_would_bet")
    )
    cf_profit = sum(
        r["counterfactual_net_profit_usdc"]
        for r in rows
        if r.get("counterfactual_would_bet")
    )

    act_cost = sum(r["actual_bet_usdc"] + mech_fee for r in rows)
    cf_cost = sum(
        r["counterfactual_bet_usdc"] + mech_fee
        for r in rows
        if r.get("counterfactual_would_bet")
    )
    act_roi = safe_div(act_profit, act_cost)
    cf_roi = safe_div(cf_profit, cf_cost)

    return {
        "segment": label,
        "bets": n,
        "cf_bets": n_cf,
        "yes": n_yes,
        "no": n_no,
        "side_switch": n_switch,
        "actual_traded_usdc": round(act_traded, 2),
        "actual_profit_usdc": round(act_profit, 2),
        "actual_roi_pct": round(act_roi * 100, 2) if act_roi is not None else None,
        "cf_traded_usdc": round(cf_traded, 2),
        "cf_profit_usdc": round(cf_profit, 2),
        "cf_roi_pct": round(cf_roi * 100, 2) if cf_roi is not None else None,
        "roi_delta_pp": (
            round((cf_roi - act_roi) * 100, 2)
            if cf_roi is not None and act_roi is not None
            else None
        ),
    }


def segment_replay(
    replay: Dict[str, Any],
    neg_risk_lookup: Dict[str, Optional[bool]],
) -> Dict[str, Any]:
    """Segment replay rows by negRisk and compute per-segment statistics."""
    rows = replay.get("closed_bet_replay", [])

    neg_rows: List[Dict[str, Any]] = []
    non_neg_rows: List[Dict[str, Any]] = []

    for row in rows:
        key = (row["agent_safe"].lower(), row["bet_id"])
        is_neg = neg_risk_lookup.get(key)
        row["is_neg_risk"] = is_neg
        if is_neg is True:
            neg_rows.append(row)
        elif is_neg is False:
            non_neg_rows.append(row)

    mop = replay.get("assumptions", {}).get("min_oracle_prob", "?")
    return {
        "min_oracle_prob": mop,
        "segments": {
            "all": compute_segment_stats("all", rows),
            "neg_risk": compute_segment_stats("negRisk", neg_rows),
            "non_neg_risk": compute_segment_stats("non-negRisk", non_neg_rows),
        },
    }


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Segment replay by negRisk market type."
    )
    parser.add_argument("--replay", required=True, help="Replay JSON file.")
    parser.add_argument(
        "--enriched-snapshot", required=True, help="Enriched snapshot with is_neg_risk."
    )
    parser.add_argument("--output", required=True, help="Output segmented JSON.")
    args = parser.parse_args()

    with open(args.replay) as f:
        replay = json.load(f)
    with open(args.enriched_snapshot) as f:
        snap = json.load(f)

    # Build lookup: (agent_safe, bet_id) -> is_neg_risk
    lookup = {}
    for b in snap.get("bets", []):
        key = (b["agent_safe"].lower(), b["bet_id"])
        lookup[key] = b.get("is_neg_risk")

    result = segment_replay(replay, lookup)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)

    # Print summary
    for seg_name, stats in result["segments"].items():
        print(
            f"[{seg_name}] bets={stats['bets']}, cf={stats['cf_bets']}, "
            f"Y={stats['yes']}/N={stats['no']}, sw={stats['side_switch']}, "
            f"act_roi={stats['actual_roi_pct']}%, cf_roi={stats['cf_roi_pct']}%, "
            f"delta={stats['roi_delta_pp']}pp",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
