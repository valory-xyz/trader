# -*- coding: utf-8 -*-
"""Tests for resumable Polystrat chunked snapshots."""

from datetime import datetime, timezone
import json

from packages.valory.skills.agent_performance_summary_abci.replay.polystrat_kelly import ReplayConfig
from scripts.polystrat_kelly_chunked_snapshot import (
    _chunk_path,
    _initialize_chunk_payload,
    _load_or_initialize_chunk_payload,
    _write_chunk_payload,
)


def test_chunk_path_is_stable() -> None:
    """Chunk file names should be predictable."""
    path = _chunk_path("/tmp/chunks", 2, datetime(2026, 3, 20).date(), datetime(2026, 3, 26).date())
    assert str(path).endswith("/tmp/chunks/chunk_02_2026-03-20_2026-03-26.json")


def test_initialize_chunk_payload_starts_empty() -> None:
    """New chunk payloads should start with no completed agents or bets."""
    config = ReplayConfig(
        start_timestamp=int(datetime(2026, 3, 20, tzinfo=timezone.utc).timestamp()),
        end_timestamp=int(datetime(2026, 3, 26, 23, 59, 59, tzinfo=timezone.utc).timestamp()),
    )
    payload = _initialize_chunk_payload(
        agent_safes=["0xabc", "0xdef"],
        config=config,
        agents_subgraph_url="agents",
        mech_subgraph_url="mech",
    )
    assert payload["snapshot_metadata"]["closed_bet_count"] == 0
    assert payload["chunk_progress"]["agent_safes"] == ["0xabc", "0xdef"]
    assert payload["chunk_progress"]["completed_agents"] == []
    assert payload["bets"] == []


def test_load_or_initialize_chunk_payload_resumes_existing_file(tmp_path) -> None:
    """Existing chunk payloads should be loaded instead of overwritten."""
    chunk_path = tmp_path / "chunk.json"
    chunk_path.write_text(
        json.dumps(
            {
                "snapshot_metadata": {"closed_bet_count": 1},
                "chunk_progress": {
                    "agent_safes": ["0xabc"],
                    "completed_agents": ["0xabc"],
                },
                "bets": [{"bet_id": "bet-1"}],
            }
        ),
        encoding="utf-8",
    )
    config = ReplayConfig(start_timestamp=1, end_timestamp=2)
    payload = _load_or_initialize_chunk_payload(
        chunk_path=chunk_path,
        agent_safes=["0xabc"],
        config=config,
        agents_subgraph_url="agents",
        mech_subgraph_url="mech",
    )
    assert payload["chunk_progress"]["completed_agents"] == ["0xabc"]
    assert payload["bets"] == [{"bet_id": "bet-1"}]


def test_write_chunk_payload_updates_closed_bet_count(tmp_path) -> None:
    """Chunk writes should refresh the stored bet count."""
    chunk_path = tmp_path / "chunk.json"
    payload = {
        "snapshot_metadata": {"closed_bet_count": 0},
        "chunk_progress": {"agent_safes": ["0xabc"], "completed_agents": ["0xabc"]},
        "bets": [{"bet_id": "bet-1"}, {"bet_id": "bet-2"}],
    }
    _write_chunk_payload(chunk_path, payload)
    written = json.loads(chunk_path.read_text(encoding="utf-8"))
    assert written["snapshot_metadata"]["closed_bet_count"] == 2
