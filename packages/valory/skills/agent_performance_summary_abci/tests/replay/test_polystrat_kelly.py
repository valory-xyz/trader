# -*- coding: utf-8 -*-
"""Tests for the Polystrat Kelly replay helpers."""

from datetime import date

from packages.valory.skills.agent_performance_summary_abci.replay.polystrat_kelly import (
    HistoricalBet,
    ReplayConfig,
    chunk_date_range,
    compute_current_net_profit,
    estimate_counterfactual_payout,
    merge_snapshots,
    replay_bet_with_kelly,
    summarize_agent,
)


def _bet(**overrides: object) -> HistoricalBet:
    """Build a replay bet."""
    defaults = {
        "agent_safe": "0xabc",
        "bet_id": "bet-1",
        "market_id": "market-1",
        "condition_id": "condition-1",
        "title": "Will test pass?",
        "placed_at": 1_710_000_000,
        "settled_at": 1_710_086_400,
        "outcome_index": 0,
        "winning_index": 0,
        "amount_usdc": 2.0,
        "shares": 4.0,
        "payout_usdc": 4.0,
        "executed_price": 0.5,
        "actual_side": "yes",
        "actual_net_profit_usdc": 1.99,
        "mech_tool": "tool-1",
        "p_yes": 0.7,
        "p_no": 0.3,
        "mech_model": "model-1",
    }
    defaults.update(overrides)
    return HistoricalBet(**defaults)


def test_compute_current_net_profit_includes_mech_fee() -> None:
    """Current profit should subtract bet amount and mech fee."""
    assert compute_current_net_profit(4.0, 2.0, 0.01) == 1.99


def test_estimate_counterfactual_payout_zero_when_side_loses() -> None:
    """Counterfactual payout should be zero on the losing side."""
    assert estimate_counterfactual_payout(1, 0, 2.5, 0.5) == 0.0


def test_replay_bet_with_kelly_takes_positive_edge_bet() -> None:
    """Kelly replay should place a bet on a clear edge."""
    bet = _bet()
    decision = replay_bet_with_kelly(bet, ReplayConfig(start_timestamp=0, end_timestamp=10))
    assert decision.would_bet is True
    assert decision.vote == 0
    assert decision.kelly_bet_usdc > 0
    assert decision.counterfactual_net_profit_usdc > 0


def test_replay_bet_with_kelly_skips_when_mech_missing() -> None:
    """Missing mech data should produce a no-trade decision."""
    bet = _bet(p_yes=None, p_no=None, mech_tool=None, mech_model=None)
    decision = replay_bet_with_kelly(bet, ReplayConfig(start_timestamp=0, end_timestamp=10))
    assert decision.would_bet is False
    assert decision.kelly_bet_usdc == 0.0


def test_summarize_agent_computes_roi_delta() -> None:
    """Agent summary should compare actual and simulated ROI."""
    bet = _bet()
    decision = replay_bet_with_kelly(bet, ReplayConfig(start_timestamp=0, end_timestamp=10))
    summary = summarize_agent("0xabc", [(bet, decision)])
    assert summary.closed_bets_count == 1
    assert summary.actual_roi is not None
    assert summary.counterfactual_roi is not None


def test_chunk_date_range_splits_inclusive_window() -> None:
    """Chunked date ranges should cover the full inclusive window."""
    chunks = chunk_date_range(date(2026, 2, 26), date(2026, 3, 26), 7)
    assert chunks == [
        (date(2026, 2, 26), date(2026, 3, 4)),
        (date(2026, 3, 5), date(2026, 3, 11)),
        (date(2026, 3, 12), date(2026, 3, 18)),
        (date(2026, 3, 19), date(2026, 3, 25)),
        (date(2026, 3, 26), date(2026, 3, 26)),
    ]


def test_merge_snapshots_deduplicates_bets_and_extends_bounds() -> None:
    """Merged snapshots should deduplicate rows and widen the window bounds."""
    first = {
        "snapshot_metadata": {
            "start_timestamp": 100,
            "end_timestamp": 199,
            "start_iso": "1970-01-01T00:01:40+00:00",
            "end_iso": "1970-01-01T00:03:19+00:00",
            "agents_subgraph_url": "agents",
            "mech_subgraph_url": "mech",
            "agent_count": 1,
            "closed_bet_count": 1,
            "capture_version": "v1",
        },
        "bets": [dict(_bet().__dict__)],
    }
    second_bet = _bet(bet_id="bet-2", placed_at=300, settled_at=400, agent_safe="0xdef")
    second = {
        "snapshot_metadata": {
            "start_timestamp": 150,
            "end_timestamp": 499,
            "start_iso": "1970-01-01T00:02:30+00:00",
            "end_iso": "1970-01-01T00:08:19+00:00",
            "agents_subgraph_url": "agents",
            "mech_subgraph_url": "mech",
            "agent_count": 2,
            "closed_bet_count": 2,
            "capture_version": "v1",
        },
        "bets": [dict(_bet().__dict__), dict(second_bet.__dict__)],
    }

    merged = merge_snapshots([first, second])

    assert merged["snapshot_metadata"]["start_timestamp"] == 100
    assert merged["snapshot_metadata"]["end_timestamp"] == 499
    assert merged["snapshot_metadata"]["agent_count"] == 2
    assert merged["snapshot_metadata"]["closed_bet_count"] == 2
    assert merged["snapshot_metadata"]["capture_version"] == "v1-merged-2"
    assert [row["bet_id"] for row in merged["bets"]] == ["bet-2", "bet-1"]
