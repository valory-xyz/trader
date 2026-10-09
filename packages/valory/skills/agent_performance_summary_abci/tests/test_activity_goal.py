# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for the activity goal ledger and block helpers."""

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.activity_goal import (
    ACTIVITY_GOAL_TRADES_FILE,
    build_activity_goal,
    count_trades_since,
    effective_activity_goal,
    is_valid_activity_goal,
    read_trades,
    record_trade,
    retarget_activity_goal,
    update_activity_goal,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AGENT_PERFORMANCE_SUMMARY_FILE,
    ActivityGoal,
)

PERIOD_START = 1_791_331_200


def _goal(**overrides: Any) -> ActivityGoal:
    """Build a block with sensible defaults."""
    values = dict(
        unit="trades",
        target=8,
        progress=3,
        is_met=False,
        period_start=PERIOD_START,
        updated_at=PERIOD_START + 100,
        last_met_at=None,
    )
    values.update(overrides)
    return ActivityGoal(**values)  # type: ignore[arg-type]


def _read_summary(store_path: Path) -> Any:
    """Return the raw summary file content."""
    with open(store_path / AGENT_PERFORMANCE_SUMMARY_FILE, "r") as f:
        return json.load(f)


class TestIsValidActivityGoal:
    """Tests for is_valid_activity_goal."""

    @pytest.mark.parametrize("value", [0, 1, 8, 500])
    def test_accepts_non_negative_ints(self, value: int) -> None:
        """Zero and any positive int are goals; there is no upper bound."""
        assert is_valid_activity_goal(value)

    @pytest.mark.parametrize("value", [True, False, -1, 8.0, 2.5, "8", None, [8]])
    def test_rejects_everything_else(self, value: Any) -> None:
        """Bools, negatives, floats and non-numbers are not goals."""
        assert not is_valid_activity_goal(value)


class TestEffectiveActivityGoal:
    """Tests for effective_activity_goal."""

    @pytest.mark.parametrize(
        "stored_goal, expected", [(None, 8), (0, 0), (20, 20)], ids=["unset", "0", "20"]
    )
    def test_stored_goal_else_default(
        self, stored_goal: Optional[int], expected: int
    ) -> None:
        """The user's goal wins, including 0; unset falls back to the default."""
        assert effective_activity_goal(stored_goal, 8) == expected


class TestTradesLedger:
    """Tests for the trades ledger."""

    def test_append_count_and_prune_across_period_start(self, tmp_path: Path) -> None:
        """Trades before the epoch start are not counted and are pruned."""
        record_trade(tmp_path, PERIOD_START - 1, "old")
        record_trade(tmp_path, PERIOD_START, "at_start")
        record_trade(tmp_path, PERIOD_START + 60, "later")

        assert count_trades_since(tmp_path, PERIOD_START, MagicMock()) == 2
        assert read_trades(tmp_path) == [
            {"timestamp": PERIOD_START, "bet_id": "at_start"},
            {"timestamp": PERIOD_START + 60, "bet_id": "later"},
        ]

    def test_count_does_not_rewrite_when_nothing_to_prune(self, tmp_path: Path) -> None:
        """A ledger holding only current trades is left as it is."""
        record_trade(tmp_path, PERIOD_START, "a")
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.activity_goal.write_json_atomically"
        ) as write:
            assert count_trades_since(tmp_path, PERIOD_START, MagicMock()) == 1
        write.assert_not_called()

    def test_missing_ledger_reads_as_empty_without_warning(
        self, tmp_path: Path
    ) -> None:
        """No ledger yet is the normal first-run state."""
        logger = MagicMock()

        assert read_trades(tmp_path) == []
        assert count_trades_since(tmp_path, 0, logger) == 0
        logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        "content",
        [b"{not json", b"\xff\xfe", json.dumps({"timestamp": PERIOD_START}).encode()],
        ids=["corrupt", "not_utf8", "not_a_list"],
    )
    def test_unusable_ledger_raises(self, tmp_path: Path, content: bytes) -> None:
        """A ledger that exists but cannot be used is an error, not an empty ledger."""
        (tmp_path / ACTIVITY_GOAL_TRADES_FILE).write_bytes(content)

        with pytest.raises(ValueError):
            read_trades(tmp_path)
        with pytest.raises(ValueError):
            count_trades_since(tmp_path, PERIOD_START, MagicMock())

    def test_entries_without_a_timestamp_are_ignored(self, tmp_path: Path) -> None:
        """Malformed entries are skipped rather than failing the count."""
        (tmp_path / ACTIVITY_GOAL_TRADES_FILE).write_text(
            json.dumps(
                [
                    "junk",
                    {"bet_id": "no_ts"},
                    {"timestamp": True},
                    {"timestamp": "1"},
                    {"timestamp": PERIOD_START, "bet_id": "ok"},
                ]
            )
        )

        assert read_trades(tmp_path) == [{"timestamp": PERIOD_START, "bet_id": "ok"}]

    @pytest.mark.parametrize(
        "content",
        [b"{not json", b"\xff\xfe", json.dumps({"timestamp": PERIOD_START}).encode()],
        ids=["corrupt", "not_utf8", "not_a_list"],
    )
    def test_unusable_ledger_is_not_overwritten_by_next_trade(
        self, tmp_path: Path, content: bytes
    ) -> None:
        """Recording a trade over an unusable ledger fails and leaves it intact."""
        (tmp_path / ACTIVITY_GOAL_TRADES_FILE).write_bytes(content)

        with pytest.raises(ValueError):
            record_trade(tmp_path, PERIOD_START, "a")

        assert (tmp_path / ACTIVITY_GOAL_TRADES_FILE).read_bytes() == content

    def test_repeated_trade_is_recorded_once(self, tmp_path: Path) -> None:
        """A retried write of the same placement does not count twice."""
        record_trade(tmp_path, PERIOD_START, "a")
        record_trade(tmp_path, PERIOD_START, "a")
        record_trade(tmp_path, PERIOD_START, "b")
        record_trade(tmp_path, PERIOD_START + 1, "a")

        assert count_trades_since(tmp_path, PERIOD_START, MagicMock()) == 3

    def test_failed_prune_still_counts(self, tmp_path: Path) -> None:
        """A prune that cannot be written is reported and the count still stands."""
        record_trade(tmp_path, PERIOD_START - 1, "old")
        record_trade(tmp_path, PERIOD_START, "a")
        logger = MagicMock()

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.activity_goal.write_json_atomically",
            side_effect=OSError("disk full"),
        ):
            assert count_trades_since(tmp_path, PERIOD_START, logger) == 1

        logger.warning.assert_called_once()
        assert len(read_trades(tmp_path)) == 2


class TestBuildActivityGoal:
    """Tests for build_activity_goal."""

    def test_met_when_progress_equals_target(self) -> None:
        """Reaching the target exactly meets the goal."""
        goal = build_activity_goal(8, 8, PERIOD_START, PERIOD_START + 5, None)
        assert goal.is_met is True
        assert goal.unit == "trades"
        assert goal.updated_at == PERIOD_START + 5

    def test_not_met_below_target(self) -> None:
        """One trade short is not met and stamps nothing."""
        goal = build_activity_goal(8, 7, PERIOD_START, PERIOD_START + 5, None)
        assert goal.is_met is False
        assert goal.last_met_at is None

    def test_zero_target_is_met_at_once(self) -> None:
        """A goal of zero is met before any trade."""
        goal = build_activity_goal(0, 0, PERIOD_START, PERIOD_START + 5, None)
        assert goal.is_met is True
        assert goal.last_met_at == PERIOD_START + 5

    def test_last_met_at_stamped_on_transition(self) -> None:
        """False to true within the epoch stamps the current time."""
        previous = _goal(is_met=False, last_met_at=PERIOD_START - 10)
        goal = build_activity_goal(8, 8, PERIOD_START, PERIOD_START + 50, previous)
        assert goal.last_met_at == PERIOD_START + 50

    def test_last_met_at_carried_while_met(self) -> None:
        """Staying met keeps the first stamp."""
        previous = _goal(progress=8, is_met=True, last_met_at=PERIOD_START + 50)
        goal = build_activity_goal(8, 9, PERIOD_START, PERIOD_START + 90, previous)
        assert goal.last_met_at == PERIOD_START + 50

    def test_last_met_at_carried_when_not_met(self) -> None:
        """Dropping to not met keeps the previous stamp."""
        previous = _goal(progress=8, is_met=True, last_met_at=PERIOD_START + 50)
        goal = build_activity_goal(10, 8, PERIOD_START, PERIOD_START + 90, previous)
        assert goal.is_met is False
        assert goal.last_met_at == PERIOD_START + 50

    def test_met_in_new_epoch_is_a_transition(self) -> None:
        """Being met in the previous epoch does not count for the new one."""
        new_period = PERIOD_START + 86_400
        previous = _goal(progress=8, is_met=True, last_met_at=PERIOD_START + 50)
        goal = build_activity_goal(0, 0, new_period, new_period + 5, previous)
        assert goal.last_met_at == new_period + 5


class TestUpdateActivityGoal:
    """Tests for the merge-writers."""

    def test_preserves_every_sibling_key(self, tmp_path: Path) -> None:
        """Only the ``activity_goal`` key is replaced."""
        siblings = {
            "timestamp": 1,
            "agent_behavior": "observing",
            "achievements": {"items": {}, "eligible_since": 5},
            "offchain_deposits": {"total_deposited_wei": 7, "last_scanned_block": 9},
            "future_key": [1, 2, 3],
        }
        (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).write_text(json.dumps(siblings))

        update_activity_goal(
            tmp_path, 8, 3, PERIOD_START, PERIOD_START + 5, MagicMock()
        )

        data = _read_summary(tmp_path)
        assert {k: v for k, v in data.items() if k != "activity_goal"} == siblings
        assert data["activity_goal"] == {
            "unit": "trades",
            "target": 8,
            "progress": 3,
            "is_met": False,
            "period_start": PERIOD_START,
            "updated_at": PERIOD_START + 5,
            "last_met_at": None,
        }

    @pytest.mark.parametrize(
        "content",
        [None, b"{not json", b"\xff\xfe", b"[]"],
        ids=["missing", "corrupt", "not_utf8", "list"],
    )
    def test_writes_minimal_file(
        self, tmp_path: Path, content: Optional[bytes]
    ) -> None:
        """A missing or unusable summary is replaced by one holding the block."""
        if content is not None:
            (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).write_bytes(content)

        update_activity_goal(
            tmp_path, 1, 1, PERIOD_START, PERIOD_START + 5, MagicMock()
        )

        data = _read_summary(tmp_path)
        assert list(data) == ["activity_goal"]
        assert data["activity_goal"]["is_met"] is True
        assert data["activity_goal"]["last_met_at"] == PERIOD_START + 5

    def test_uses_previous_block_for_last_met_at(self, tmp_path: Path) -> None:
        """The stamp is carried from the block on disk."""
        update_activity_goal(
            tmp_path, 1, 1, PERIOD_START, PERIOD_START + 5, MagicMock()
        )
        update_activity_goal(
            tmp_path, 1, 2, PERIOD_START, PERIOD_START + 9, MagicMock()
        )

        block = _read_summary(tmp_path)["activity_goal"]
        assert block["last_met_at"] == PERIOD_START + 5
        assert block["updated_at"] == PERIOD_START + 9

    def test_failed_publish_is_logged_and_returns_the_block(
        self, tmp_path: Path
    ) -> None:
        """A write failure does not change the block the vote is computed from."""
        logger = MagicMock()

        with patch(
            "packages.valory.skills.agent_performance_summary_abci.activity_goal.write_performance_summary_key",
            side_effect=OSError("disk full"),
        ):
            goal = update_activity_goal(
                tmp_path, 1, 1, PERIOD_START, PERIOD_START + 5, logger
            )

        assert goal.is_met is True
        logger.error.assert_called_once()
        assert not (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).exists()

    def test_retarget_keeps_progress_and_epoch(self, tmp_path: Path) -> None:
        """A goal change reuses the last progress and recomputes ``is_met``."""
        update_activity_goal(
            tmp_path, 8, 3, PERIOD_START, PERIOD_START + 5, MagicMock()
        )

        goal = retarget_activity_goal(tmp_path, 3, PERIOD_START + 20)

        assert goal is not None
        block = _read_summary(tmp_path)["activity_goal"]
        assert block["target"] == 3
        assert block["progress"] == 3
        assert block["period_start"] == PERIOD_START
        assert block["is_met"] is True
        assert block["last_met_at"] == PERIOD_START + 20
        assert block["updated_at"] == PERIOD_START + 20

    def test_retarget_without_block_writes_nothing(self, tmp_path: Path) -> None:
        """Without an epoch on record there is nothing to retarget."""
        assert retarget_activity_goal(tmp_path, 3, PERIOD_START) is None
        assert not (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).exists()
