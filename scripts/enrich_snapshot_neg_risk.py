"""Enrich a polystrat replay snapshot with negRisk tags from the Polymarket CLOB API.

Usage:
    python scripts/enrich_snapshot_neg_risk.py \
        --input reports/polystrat_kelly_replay_2026-03-12_2026-03-26/snapshot.json \
        --output reports/polystrat_kelly_replay_v2_2026-03-12_2026-03-26/snapshot_enriched.json
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, Optional

import requests

CLOB_BASE_URL = "https://clob.polymarket.com"
DEFAULT_TIMEOUT = 10
RATE_LIMIT_DELAY = 0.05


def fetch_neg_risk(condition_id: str, timeout: int = DEFAULT_TIMEOUT) -> Optional[bool]:
    """Fetch the neg_risk field for a market from the Polymarket CLOB API."""
    try:
        resp = requests.get(
            f"{CLOB_BASE_URL}/markets/{condition_id}",
            timeout=timeout,
        )
        if resp.status_code == 200:
            return bool(resp.json().get("neg_risk", False))
    except (requests.RequestException, ValueError):
        pass
    return None


def enrich_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Tag each bet in the snapshot with is_neg_risk from the CLOB API."""
    bets = snapshot.get("bets", [])

    # Collect unique condition_ids
    unique_cids = sorted(
        set(b["condition_id"] for b in bets if b.get("condition_id"))
    )
    print(
        f"[enrich] {len(bets)} bets, {len(unique_cids)} unique condition_ids",
        file=sys.stderr,
    )

    # Fetch negRisk for each
    cid_to_neg_risk: Dict[str, Optional[bool]] = {}
    for i, cid in enumerate(unique_cids):
        if i % 50 == 0:
            print(f"[enrich] fetching {i}/{len(unique_cids)}...", file=sys.stderr, flush=True)
        cid_to_neg_risk[cid] = fetch_neg_risk(cid)
        time.sleep(RATE_LIMIT_DELAY)

    # Tag bets
    for b in bets:
        cid = b.get("condition_id", "")
        b["is_neg_risk"] = cid_to_neg_risk.get(cid)

    # Stats
    neg_count = sum(1 for b in bets if b.get("is_neg_risk") is True)
    non_neg = sum(1 for b in bets if b.get("is_neg_risk") is False)
    unknown = sum(1 for b in bets if b.get("is_neg_risk") is None)
    print(
        f"[enrich] negRisk=True: {neg_count}, False: {non_neg}, Unknown: {unknown}",
        file=sys.stderr,
    )

    # Update metadata
    metadata = dict(snapshot.get("snapshot_metadata", {}))
    metadata["enrichment"] = "negRisk tags from Polymarket CLOB API"
    metadata["neg_risk_true"] = neg_count
    metadata["neg_risk_false"] = non_neg
    metadata["neg_risk_unknown"] = unknown

    return {"snapshot_metadata": metadata, "bets": bets}


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Enrich snapshot with negRisk tags.")
    parser.add_argument("--input", required=True, help="Path to input snapshot JSON.")
    parser.add_argument("--output", required=True, help="Path to output enriched snapshot JSON.")
    args = parser.parse_args()

    with open(args.input) as f:
        snapshot = json.load(f)

    enriched = enrich_snapshot(snapshot)

    with open(args.output, "w") as f:
        json.dump(enriched, f, indent=2)

    print(f"[enrich] saved to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
