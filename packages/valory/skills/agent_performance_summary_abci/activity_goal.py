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

"""Per-epoch activity goal: the trades ledger and the block Pearl reads."""

import json
from dataclasses import asdict
from logging import Logger
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.valory.skills.agent_performance_summary_abci.models import (
    ActivityGoal,
    read_activity_goal,
    write_json_atomically,
    write_performance_summary_key,
)

ACTIVITY_GOAL_KEY = "activity_goal"
ACTIVITY_GOAL_TRADES_FILE = "activity_goal_trades.json"
ACTIVITY_GOAL_UNIT = "trades"


def is_valid_activity_goal(value: Any) -> bool:
    """Return whether ``value`` can be used as a goal: a non-negative, non-bool int.

    :param value: the candidate goal.
    :return: whether it is valid.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def effective_activity_goal(stored_goal: Optional[int], default_goal: int) -> int:
    """Return the goal in force: the user's, else the default.

    :param stored_goal: the goal the user set, or ``None`` if unset.
    :param default_goal: the ``default_activity_goal`` param.
    :return: the effective goal.
    """
    return default_goal if stored_goal is None else stored_goal


def _is_trade_entry(entry: Any) -> bool:
    """Return whether a ledger entry carries a usable timestamp.

    :param entry: one item of the ledger list.
    :return: whether it can be counted.
    """
    if not isinstance(entry, dict):
        return False
    timestamp = entry.get("timestamp")
    return isinstance(timestamp, int) and not isinstance(timestamp, bool)


def read_trades(store_path: Path, logger: Logger) -> List[Dict[str, Any]]:
    """Return the ledger of placed trades.

    A missing or corrupt ledger reads as empty: under-counting keeps the agent
    trading, which is the safe direction.

    :param store_path: directory containing the ledger.
    :param logger: where to warn about an unusable ledger.
    :return: the ledger entries with a usable timestamp.
    """
    file_path = store_path / ACTIVITY_GOAL_TRADES_FILE
    try:
        with open(file_path, "r") as f:
            trades = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logger.warning(f"Unusable trades ledger {file_path}, reading it as empty: {e}")
        return []
    if not isinstance(trades, list):
        logger.warning(f"Trades ledger {file_path} is not a list, reading it as empty.")
        return []
    return [entry for entry in trades if _is_trade_entry(entry)]


def record_trade(store_path: Path, timestamp: int, bet_id: str, logger: Logger) -> None:
    """Append one placed trade to the ledger.

    :param store_path: directory containing the ledger.
    :param timestamp: when the trade was placed.
    :param bet_id: the id of the bet traded.
    :param logger: where to warn about an unusable ledger.
    """
    trades = read_trades(store_path, logger)
    trades.append({"timestamp": timestamp, "bet_id": bet_id})
    write_json_atomically(store_path / ACTIVITY_GOAL_TRADES_FILE, trades)


def count_trades_since(store_path: Path, period_start: int, logger: Logger) -> int:
    """Count the trades placed at or after ``period_start``, pruning older ones.

    :param store_path: directory containing the ledger.
    :param period_start: the start of the current staking epoch.
    :param logger: where to warn about an unusable ledger.
    :return: the number of trades in the current epoch.
    """
    trades = read_trades(store_path, logger)
    current = [entry for entry in trades if entry["timestamp"] >= period_start]
    if len(current) != len(trades):
        write_json_atomically(store_path / ACTIVITY_GOAL_TRADES_FILE, current)
    return len(current)


def build_activity_goal(
    target: int,
    progress: int,
    period_start: int,
    now: int,
    previous: Optional[ActivityGoal],
) -> ActivityGoal:
    """Build the block, stamping ``last_met_at`` when the goal becomes met in an epoch.

    :param target: the effective goal.
    :param progress: trades placed in the current epoch.
    :param period_start: the start of the current staking epoch.
    :param now: the current timestamp.
    :param previous: the block last written, if any.
    :return: the new block.
    """
    is_met = progress >= target
    was_met = (
        previous is not None
        and previous.is_met
        and previous.period_start == period_start
    )
    last_met_at = previous.last_met_at if previous is not None else None
    if is_met and not was_met:
        last_met_at = now
    return ActivityGoal(
        unit=ACTIVITY_GOAL_UNIT,
        target=target,
        progress=progress,
        is_met=is_met,
        period_start=period_start,
        updated_at=now,
        last_met_at=last_met_at,
    )


def update_activity_goal(
    store_path: Path, target: int, progress: int, period_start: int, now: int
) -> ActivityGoal:
    """Rebuild the block and merge it into the performance summary.

    :param store_path: directory containing the performance summary.
    :param target: the effective goal.
    :param progress: trades placed in the current epoch.
    :param period_start: the start of the current staking epoch.
    :param now: the current timestamp.
    :return: the block written.
    """
    goal = build_activity_goal(
        target, progress, period_start, now, read_activity_goal(store_path)
    )
    write_performance_summary_key(store_path, ACTIVITY_GOAL_KEY, asdict(goal))
    return goal


def retarget_activity_goal(
    store_path: Path, target: int, now: int
) -> Optional[ActivityGoal]:
    """Apply a new goal to the last written block, keeping its progress and epoch.

    Lets Pearl see a goal change at once; the next evaluation recomputes the
    block authoritatively.

    :param store_path: directory containing the performance summary.
    :param target: the new effective goal.
    :param now: the current timestamp.
    :return: the block written, or ``None`` when no block exists yet.
    """
    previous = read_activity_goal(store_path)
    if previous is None:
        return None
    goal = build_activity_goal(
        target, previous.progress, previous.period_start, now, previous
    )
    write_performance_summary_key(store_path, ACTIVITY_GOAL_KEY, asdict(goal))
    return goal
