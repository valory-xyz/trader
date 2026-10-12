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

"""This module contains the models for the skill."""

import atexit
import builtins
import json
import os
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    cast,
    get_args,
)
from urllib.parse import urlsplit

from packages.valory.protocols.http import HttpMessage
from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import (
    ApiSpecs,
    BaseParams,
)
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
)

AGENT_PERFORMANCE_SUMMARY_FILE = "agent_performance.json"

# Serialises every read-modify-write of the summary file: the leaderboard
# refresh writes it from a worker thread. Module-level so that writers that
# only know the store path (e.g. ``activity_goal``) share it; reentrant so a
# writer can call another under it.
SUMMARY_FILE_LOCK = threading.RLock()

# Spelled as olas-predict's leaderboard API expects them
LeaderboardWindow = Literal["7d", "30d", "90d", "1y"]
LeaderboardAgentType = Literal["omenstrat", "polystrat"]
NotRankedReason = Literal[
    "not_ranked_yet", "not_enough_trades_in_window", "not_eligible"
]
LEADERBOARD_WINDOWS: Tuple[LeaderboardWindow, ...] = get_args(LeaderboardWindow)
LEADERBOARD_NOT_RANKED_REASONS: FrozenSet[NotRankedReason] = frozenset(
    get_args(NotRankedReason)
)
LEADERBOARD_DEFAULT_NOT_RANKED_REASON: NotRankedReason = "not_ranked_yet"
LEADERBOARD_CLOCK_SKEW_SECONDS = 300
# Path of olas-predict's leaderboard page; deep links must stay under it
LEADERBOARD_PAGE_PATH = "/leaderboard"

# Bump when on-disk profit_over_time must be rebuilt against the current
# subgraph endpoint/schema. Files with a lower version are rebuilt once on
# first run via _perform_initial_backfill.
PROFIT_OVER_TIME_SCHEMA_VERSION = 2


@dataclass
class AgentPerformanceMetrics:
    """Agent performance metrics."""

    name: str
    is_primary: bool
    value: str  # eg. "75%"
    description: Optional[str] = (
        None  # Can have HTML tags like <b>bold</b> or <i>italic</i>
    )


@dataclass
class AgentDetails:
    """Agent metadata for /api/v1/agent/details endpoint."""

    id: Optional[str] = None
    created_at: Optional[str] = None  # ISO 8601 format
    last_active_at: Optional[str] = None  # ISO 8601 format


@dataclass
class PerformanceMetricsData:
    """Performance metrics for /api/v1/agent/performance endpoint."""

    all_time_funds_used: Optional[float] = None
    all_time_profit: Optional[float] = None
    funds_locked_in_markets: Optional[float] = None
    available_funds: Optional[float] = None
    roi: Optional[float] = None
    settled_mech_request_count: Optional[int] = None
    total_mech_request_count: Optional[int] = None
    open_mech_request_count: Optional[int] = None
    placed_mech_request_count: Optional[int] = None
    unplaced_mech_request_count: Optional[int] = None


@dataclass
class PerformanceStatsData:
    """Performance stats for /api/v1/agent/performance endpoint."""

    predictions_made: Optional[int] = None
    prediction_accuracy: Optional[float] = None


@dataclass
class AgentPerformanceData:
    """Complete performance data for /api/v1/agent/performance endpoint."""

    window: str = "lifetime"
    currency: str = "USD"
    metrics: Optional[PerformanceMetricsData] = None
    stats: Optional[PerformanceStatsData] = None

    def __post_init__(self) -> None:
        """Convert nested dicts to dataclass instances."""
        if isinstance(self.metrics, dict):
            self.metrics = PerformanceMetricsData(**self.metrics)
        if isinstance(self.stats, dict):
            self.stats = PerformanceStatsData(**self.stats)


@dataclass
class PredictionHistory:
    """Prediction history stored for faster API responses."""

    total_predictions: int = 0
    stored_count: int = 0
    last_updated: Optional[int] = None
    items: List[Dict] = field(default_factory=list)


@dataclass
class ProfitDataPoint:
    """Single data point for profit over time chart."""

    date: str  # YYYY-MM-DD format
    timestamp: int  # Unix timestamp
    daily_profit: float  # Net daily profit (after mech fees)
    cumulative_profit: float  # Cumulative profit from start of window
    daily_mech_requests: int = 0  # Number of mech requests for this day
    daily_profit_raw: Optional[float] = (
        None  # Gross daily profit from subgraph (before fees)
    )


@dataclass
class ProfitOverTimeData:
    """Profit over time data stored in agent_performance.json."""

    last_updated: int  # Unix timestamp of last update
    total_days: int  # Total number of days with data
    data_points: List[ProfitDataPoint] = field(default_factory=list)
    settled_mech_requests_count: int = 0  # Total settled mech requests
    unplaced_mech_requests_count: int = 0  # Total mech requests with no bets placed
    placed_mech_requests_count: int = 0  # Total mech requests tied to placed bets
    includes_unplaced_mech_fees: bool = (
        False  # Whether unplaced mech fees logic was applied
    )
    last_mech_timestamp: int = (
        0  # Watermark: max blockTimestamp of processed mech requests
    )
    schema_version: int = 0  # Bumped to trigger one-shot rebuild on cutovers

    def __post_init__(self) -> None:
        """Convert dicts to dataclass instances."""
        if (
            self.data_points
            and self.data_points
            and isinstance(self.data_points[0], dict)
        ):
            self.data_points = [
                ProfitDataPoint(**point)
                for point in self.data_points
                if isinstance(point, dict)
            ]


@dataclass
class Achievement:
    """Achievement."""

    achievement_id: str
    achievement_type: str
    title: str
    description: str
    timestamp: int
    data: Dict


@dataclass
class Achievements:
    """Achievements dictionary."""

    items: Dict[str, Achievement] = field(default_factory=dict)
    # UNIX timestamp (seconds); wins settled earlier are never recorded by
    # checkers that opt into the backlog guard.
    eligible_since: Optional[int] = None

    def __post_init__(self) -> None:
        """Convert dicts to dataclass instances."""
        if not self.items:
            return

        first_value = next(iter(self.items.values()), None)
        if isinstance(first_value, dict):
            self.items = {
                key: Achievement(**value)
                for key, value in self.items.items()
                if isinstance(value, dict)
            }


@dataclass
class OffchainDepositState:
    """Cumulative on-chain BalanceTracker Deposit tracking for pre-deposit-as-loss ROI.

    Under the pre-deposit-as-loss decision, every top-up to a Safe's
    ``mapRequesterBalances`` on the BalanceTracker contract (the mech
    marketplace only routes requests; the balance mapping and the
    ``Deposit`` event live on the tracker) is booked as spent the moment
    it lands on chain — the tracker has no requester-withdraw path, so
    committed money is unrecoverable regardless of consumption.

    ``total_deposited_wei`` is the cumulative wei-scaled sum of Deposit
    event amounts. ``last_scanned_block`` is the highest block already
    counted; the next cycle scans only ``last_scanned_block + 1`` and
    above. ``last_scanned_block is None`` distinguishes "never scanned"
    from a legitimate genesis-block checkpoint (matters on devnet/Hardhat
    chains where block 0 is a real block).

    For any Safe that has never called ``depositFor`` (i.e. every
    production on-chain trader today), the state stays at its default
    (``None`` checkpoint) and contributes nothing to the ROI cost side.

    Enforced invariants at construction time:
    - ``total_deposited_wei`` must be a non-negative integer.
    - ``last_scanned_block`` must be ``None`` or a non-negative integer.
    """

    total_deposited_wei: int = 0
    last_scanned_block: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate the persisted checkpoint fields."""
        # Defensive: some future writer may round-trip the wei count
        # through JSON as a string; coerce transparently rather than
        # rejecting. Not driven by any real prior on-disk data — this
        # dataclass is new in this PR.
        if isinstance(self.total_deposited_wei, str):
            self.total_deposited_wei = int(self.total_deposited_wei)
        if not isinstance(self.total_deposited_wei, int):
            raise TypeError(
                f"total_deposited_wei must be int, got {type(self.total_deposited_wei).__name__}"
            )
        if self.total_deposited_wei < 0:
            raise ValueError(
                f"total_deposited_wei must be non-negative, got {self.total_deposited_wei}"
            )
        if self.last_scanned_block is not None:
            if not isinstance(self.last_scanned_block, int):
                raise TypeError(
                    "last_scanned_block must be int or None, "
                    f"got {type(self.last_scanned_block).__name__}"
                )
            if self.last_scanned_block < 0:
                raise ValueError(
                    "last_scanned_block must be non-negative, "
                    f"got {self.last_scanned_block}"
                )


@dataclass(frozen=True)
class ActivityGoal:
    """Per-epoch activity goal progress, read by Pearl."""

    unit: str
    target: int
    progress: int
    is_met: bool
    period_start: int
    updated_at: int
    last_met_at: Optional[int] = None

    def __post_init__(self) -> None:
        """Refuse a block that is ill-typed or contradicts its own counts."""
        if not _is_valid_activity_goal_block(self):
            raise ValueError(f"invalid ActivityGoal: {self!r}")


@dataclass
class LeaderboardWindowRank:
    """The last successful olas-predict leaderboard answer for one window."""

    ranked: bool
    fetched_at: int
    not_ranked_reason: Optional[NotRankedReason] = None
    rank_by_roi: Optional[int] = None
    rank_by_pnl: Optional[int] = None
    total_ranked: Optional[int] = None
    leaderboard_url: Optional[str] = None
    # olas-predict's ``updatedAt``
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        """Reject ranks that contradict ``ranked`` or lie outside ``total_ranked``."""
        total = self.total_ranked
        ranks = (self.rank_by_roi, self.rank_by_pnl)
        if total is not None and not (is_plain_int(total) and total >= 0):
            valid = False
        elif self.ranked:
            valid = total is not None and all(
                rank is not None and is_plain_int(rank) and 1 <= rank <= total
                for rank in ranks
            )
        else:
            valid = ranks == (None, None)
        if not valid:
            raise ValueError(f"invalid LeaderboardWindowRank: {self!r}")

    @property
    def as_of(self) -> int:
        """Return when the answer's data was computed, or else fetched.

        :return: a UNIX timestamp in seconds.
        """
        return self.updated_at if self.updated_at is not None else self.fetched_at

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["LeaderboardWindowRank"]:
        """Build an entry from persisted JSON, or ``None`` if it is unusable.

        :param raw: the persisted entry.
        :return: the entry, or ``None``.
        """
        if not isinstance(raw, dict):
            return None
        ranked, fetched_at = raw.get("ranked"), raw.get("fetched_at")
        if not isinstance(ranked, bool) or not is_plain_int(fetched_at):
            return None

        def _int(key: str) -> Optional[int]:
            value = raw.get(key)
            return value if is_plain_int(value) else None

        reason, url = raw.get("not_ranked_reason"), raw.get("leaderboard_url")
        try:
            return cls(
                ranked=ranked,
                fetched_at=cast(int, fetched_at),
                not_ranked_reason=reason if is_not_ranked_reason(reason) else None,
                rank_by_roi=_int("rank_by_roi"),
                rank_by_pnl=_int("rank_by_pnl"),
                total_ranked=_int("total_ranked"),
                leaderboard_url=url if isinstance(url, str) else None,
                updated_at=_int("updated_at"),
            )
        except ValueError:
            return None


@dataclass
class LeaderboardData:
    """This agent's leaderboard rank per window, fetched from olas-predict."""

    windows: Dict[LeaderboardWindow, LeaderboardWindowRank] = field(
        default_factory=dict
    )
    # Throttle watermark: when a refresh was last attempted, successful or not
    last_attempt_at: Optional[int] = None

    def __post_init__(self) -> None:
        """Convert dicts to dataclass instances, dropping anything unusable."""
        raw_windows: Any = self.windows
        windows: Dict[LeaderboardWindow, LeaderboardWindowRank] = {}
        if isinstance(raw_windows, dict):
            for window, raw_entry in raw_windows.items():
                if window not in LEADERBOARD_WINDOWS:
                    continue
                entry = (
                    raw_entry
                    if isinstance(raw_entry, LeaderboardWindowRank)
                    else LeaderboardWindowRank.from_dict(raw_entry)
                )
                if entry is not None:
                    windows[cast(LeaderboardWindow, window)] = entry
        self.windows = windows
        if not is_plain_int(self.last_attempt_at):
            self.last_attempt_at = None

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["LeaderboardData"]:
        """Build the section from persisted JSON, or ``None`` if it is not an object.

        :param raw: the persisted section.
        :return: the section, or ``None``.
        """
        if not isinstance(raw, dict):
            return None
        return cls(
            windows=cast(
                Dict[LeaderboardWindow, LeaderboardWindowRank], raw.get("windows")
            ),
            last_attempt_at=raw.get("last_attempt_at"),
        )


def is_not_ranked_reason(value: Any) -> bool:
    """Return whether ``value`` is a ``notRankedReason`` olas-predict documents.

    :param value: the candidate reason.
    :return: whether it is known.
    """
    return isinstance(value, str) and value in LEADERBOARD_NOT_RANKED_REASONS


def get_leaderboard_agent_type(is_running_on_polymarket: bool) -> LeaderboardAgentType:
    """Return the agent type olas-predict ranks this agent under.

    :param is_running_on_polymarket: whether the agent trades on Polymarket.
    :return: the agent type.
    """
    return "polystrat" if is_running_on_polymarket else "omenstrat"


def is_allowed_leaderboard_url(url: Any, api_url: str) -> bool:
    """Return whether ``url`` is an https link under the API host's leaderboard page.

    :param url: the candidate link.
    :param api_url: the configured ``olas_predict_leaderboard_url``.
    :return: whether the link may be served.
    """
    if not isinstance(url, str) or not api_url:
        return False
    if any(ch.isspace() or ord(ch) < 0x20 or ch == "\\" for ch in url):
        return False
    try:
        candidate, allowed = urlsplit(url), urlsplit(api_url)
        candidate_port, allowed_port = candidate.port, allowed.port
    except ValueError:
        return False
    return (
        candidate.scheme == "https"
        and allowed.scheme == "https"
        and candidate.username is None
        and candidate.password is None
        and candidate.hostname is not None
        and candidate.hostname == allowed.hostname
        and candidate_port == allowed_port
        and (
            candidate.path == LEADERBOARD_PAGE_PATH
            or candidate.path.startswith(f"{LEADERBOARD_PAGE_PATH}/")
        )
    )


@dataclass
class AgentPerformanceSummary:
    """
    Agent performance summary.

    - If the agent has any activity, fields will be filled.
    - Otherwise, initial state with nulls and empty arrays.
    """

    timestamp: Optional[int] = None  # UNIX timestamp (in seconds, UTC)
    metrics: List[AgentPerformanceMetrics] = field(default_factory=list)
    agent_behavior: Optional[str] = None
    agent_details: Optional[AgentDetails] = None
    agent_performance: Optional[AgentPerformanceData] = None
    prediction_history: Optional[PredictionHistory] = None
    profit_over_time: Optional[ProfitOverTimeData] = None
    achievements: Optional[Achievements] = None
    offchain_deposits: Optional[OffchainDepositState] = None
    leaderboard: Optional[LeaderboardData] = None
    activity_goal: Optional[ActivityGoal] = None

    def __post_init__(self) -> None:
        """Convert dicts to dataclass instances."""
        if self.metrics and isinstance(self.metrics[0], dict):
            self.metrics = [
                AgentPerformanceMetrics(**m)
                for m in self.metrics
                if isinstance(m, dict)
            ]

        if isinstance(self.agent_details, dict):
            self.agent_details = AgentDetails(**self.agent_details)

        # Similarly for other nested dataclasses
        if isinstance(self.agent_performance, dict):
            self.agent_performance = AgentPerformanceData(**self.agent_performance)

        if isinstance(self.prediction_history, dict):
            self.prediction_history = PredictionHistory(**self.prediction_history)

        if isinstance(self.profit_over_time, dict):
            self.profit_over_time = ProfitOverTimeData(**self.profit_over_time)

        if isinstance(self.achievements, dict):
            self.achievements = Achievements(**self.achievements)

        if isinstance(self.offchain_deposits, dict):
            self.offchain_deposits = OffchainDepositState(**self.offchain_deposits)

        if isinstance(self.leaderboard, dict):
            self.leaderboard = LeaderboardData.from_dict(self.leaderboard)
        elif not isinstance(self.leaderboard, LeaderboardData):
            # A refetchable cache, so a malformed value is dropped, not raised
            self.leaderboard = None

        if isinstance(self.activity_goal, dict):
            # Rebuilt from the ledger on every evaluation, so a bad block is
            # dropped rather than degrading the whole summary read.
            try:
                self.activity_goal = ActivityGoal(**self.activity_goal)
            except (TypeError, ValueError):
                self.activity_goal = None


def write_json_atomically(file_path: Path, data: Any) -> None:
    """Write JSON so that a crash mid-write never leaves a truncated file.

    :param file_path: the file to (over)write.
    :param data: the JSON-serialisable content.
    """
    # tempfile in the same directory so ``os.replace`` is atomic on
    # POSIX (both paths on one filesystem).
    fd, tmp_path = tempfile.mkstemp(
        prefix=file_path.name + ".", dir=str(file_path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_activity_goal(store_path: Path) -> Optional[ActivityGoal]:
    """Return the persisted ``activity_goal`` block, ignoring every sibling field.

    :param store_path: directory containing the performance summary file.
    :return: the block, or ``None`` if the file or the key is missing or invalid.
    """
    try:
        with open(store_path / AGENT_PERFORMANCE_SUMMARY_FILE, "r") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None

    sub = raw.get("activity_goal") if isinstance(raw, dict) else None
    if not isinstance(sub, dict):
        return None

    try:
        return ActivityGoal(**sub)
    except (TypeError, ValueError):
        return None


def is_plain_int(value: Any) -> bool:
    """Return whether ``value`` is an int and not a bool.

    :param value: the value to check.
    :return: whether it is a plain int.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _is_valid_activity_goal_block(goal: ActivityGoal) -> bool:
    """Return whether a block is well-typed and self-consistent.

    :param goal: the block to check.
    :return: whether it is safe to compute with.
    """
    counters = (goal.target, goal.progress, goal.period_start, goal.updated_at)
    return (
        isinstance(goal.unit, str)
        and isinstance(goal.is_met, bool)
        and all(is_plain_int(value) and value >= 0 for value in counters)
        and (goal.last_met_at is None or is_plain_int(goal.last_met_at))
        and goal.is_met == (goal.progress >= goal.target)
    )


def write_performance_summary_key(store_path: Path, key: str, value: Any) -> None:
    """Atomically replace one top-level key of the summary file, keeping the others.

    Edits raw JSON so a degraded typed read cannot wipe sibling keys.

    :param store_path: directory containing the performance summary file.
    :param key: the top-level key to replace.
    :param value: the JSON-serialisable value to store under ``key``.
    """
    file_path = store_path / AGENT_PERFORMANCE_SUMMARY_FILE

    with SUMMARY_FILE_LOCK:
        try:
            with open(file_path, "r") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
        except (FileNotFoundError, ValueError):
            raw = {}

        raw[key] = value
        write_json_atomically(file_path, raw)


class AgentPerformanceSummaryParams(BaseParams):
    """Agent Performance Summary's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.coingecko_olas_in_usd_price_url: str = self._ensure(
            "coingecko_olas_in_usd_price_url", kwargs, str
        )
        self.coingecko_pol_in_usd_price_url: str = self._ensure(
            "coingecko_pol_in_usd_price_url", kwargs, str
        )
        self.store_path: Path = self.get_store_path(kwargs)
        self.is_agent_performance_summary_enabled: bool = self._ensure(
            "is_agent_performance_summary_enabled", kwargs, bool
        )
        self.is_achievement_checker_enabled: bool = self._ensure(
            "is_achievement_checker_enabled", kwargs, bool
        )
        # BalanceTracker contract address for pre-deposit-as-loss ROI
        # accounting. Empty or the zero address disables the Deposit-event
        # scan; the helper falls back to the cached total (see
        # ``_fetch_offchain_prepaid_wei``). Kept as a trader-local skill
        # param on purpose — this is an ROI-accounting concern, not a
        # mech-routing concern, so it does not belong on
        # ``mech_marketplace_config``.
        self.balance_tracker_address: str = self._ensure(
            "balance_tracker_address", kwargs, str
        )
        # Mech-analytics migration: base URL of the read-only mech-analytics
        # API and a feature flag gating whether the trader reads request
        # data from that API instead of the marketplace subgraph. Empty URL
        # disables the flag-on path defensively (throws in the client rather
        # than silently returning zero rows and inflating ROI). Both default
        # to the safe pre-migration behaviour: flag off, subgraph read
        # unchanged. See docs (consumer migration §7 in mech-analytics repo).
        # The env-var template grammar has no empty default, so unset arrives as None.
        self.mech_analytics_url: str = (
            self._ensure("mech_analytics_url", kwargs, Optional[str]) or ""
        )
        self.use_mech_analytics: bool = self._ensure("use_mech_analytics", kwargs, bool)
        # Enforce the pairing at startup — fail loudly rather than
        # silently no-op'ing back to the subgraph path when an operator
        # enables the flag but forgets the URL.
        if self.use_mech_analytics and not self.mech_analytics_url:
            raise ValueError(
                "use_mech_analytics is true but mech_analytics_url is empty; "
                "set MECH_ANALYTICS_URL or turn USE_MECH_ANALYTICS off"
            )
        # ``None`` (a ``null`` override) disables the leaderboard fetch
        self.olas_predict_leaderboard_url: str = (
            self._ensure("olas_predict_leaderboard_url", kwargs, Optional[str]) or ""
        )
        # Handle is_running_on_polymarket which may be shared with MarketManagerParams
        # If already set by a parent class (MarketManagerParams), use that value
        # Otherwise, pop it from kwargs ourselves
        if hasattr(self, "is_running_on_polymarket"):
            # Already set by MarketManagerParams in the inheritance chain
            pass
        else:
            # Standalone usage or not yet set - pop it from kwargs
            self.is_running_on_polymarket: bool = self._ensure(
                "is_running_on_polymarket", kwargs, bool
            )
        super().__init__(*args, **kwargs)

    def get_store_path(self, kwargs: Dict) -> Path:
        """Get the path of the store."""
        path = self._ensure("store_path", kwargs, str)
        # check if path exists, and we can write to it
        if (
            not os.path.isdir(path)
            or not os.access(path, os.W_OK)
            or not os.access(path, os.R_OK)
        ):
            raise ValueError(
                f"Policy store path {path!r} is not a directory or is not writable."
            )
        return Path(path)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls: Type[AbciApp] = AgentPerformanceSummaryAbciApp

    # Class-level defaults rather than ``__init__`` so a state built without
    # it (e.g. ``object.__new__`` in tests) still works; assignments shadow them.
    # The leaderboard section, loaded from disk once and kept in sync on writes
    _leaderboard_cache: Optional[LeaderboardData] = None
    _leaderboard_cache_loaded: bool = False
    # Runs the leaderboard refresh off the FSM; created on first use
    _leaderboard_executor: Optional[ThreadPoolExecutor] = None
    _leaderboard_future: Optional[Future] = None

    @property
    def params(self) -> AgentPerformanceSummaryParams:
        """Return the params."""
        return cast(AgentPerformanceSummaryParams, self.context.params)

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        try:
            return int(
                self.context.state.round_sequence.last_round_transition_timestamp.timestamp()
            )
        except ValueError as e:
            self.context.logger.warning(
                "No round transition has completed yet, e.g. after a Tendermint "
                f"period reset: {e}. Falling back to the local clock."
            )
            return int(datetime.now(timezone.utc).timestamp())

    def read_existing_performance_summary(self) -> AgentPerformanceSummary:
        """Read the existing agent performance summary from a file."""
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        try:
            with open(file_path, "r") as f:
                existing_data = AgentPerformanceSummary(**json.load(f))
            return existing_data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.context.logger.warning(
                f"Could not read existing agent performance summary: {e}"
            )
            return AgentPerformanceSummary()
        except (TypeError, ValueError) as e:
            # A nested ``__post_init__`` (e.g. ``OffchainDepositState``)
            # rejected a persisted value. Previously no field could raise
            # from the reader; now that we persist typed state, one bad
            # entry could brick every read. Degrade to a fresh summary
            # rather than propagate — same behaviour as an unreadable
            # file. Callers that persist irreversible state
            # (``offchain_deposits.total_deposited_wei``) MUST NOT use the
            # degraded return value to derive an on-disk write for that
            # state — see ``read_offchain_deposits_from_disk`` for the
            # sibling-agnostic re-read used in the cycle-end save path.
            self.context.logger.warning(
                f"Persisted agent performance summary failed validation ({e}); "
                "starting from a fresh summary."
            )
            return AgentPerformanceSummary()

    def read_offchain_deposits_from_disk(self) -> Optional["OffchainDepositState"]:
        """Return the persisted ``offchain_deposits`` sub-field with lenient parsing.

        Bypasses ``AgentPerformanceSummary.__post_init__`` so a corrupt
        sibling field (e.g. a bad ``Achievements`` or ``PredictionHistory``
        entry that would otherwise degrade
        ``read_existing_performance_summary`` to a fresh summary) can't
        cascade into wiping this specific irreversible field.
        ``_save_agent_performance_summary`` calls this before overwriting
        so the mid-cycle write from ``_fetch_offchain_prepaid_wei``
        survives the cycle-end save under any sibling-corruption path.

        :return: the persisted ``OffchainDepositState`` if the file has a
            valid entry, ``None`` if the file is missing, unreadable,
            has no ``offchain_deposits`` key, or the field itself fails
            validation. The final case is logged; the others are silent
            (they overlap with the legitimate first-boot / never-scanned
            path).
        """
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        try:
            with open(file_path, "r") as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

        sub = raw.get("offchain_deposits") if isinstance(raw, dict) else None
        if not isinstance(sub, dict):
            return None

        try:
            return OffchainDepositState(**sub)
        except (TypeError, ValueError) as e:
            self.context.logger.warning(
                f"Persisted offchain_deposits failed validation ({e}); "
                "leaving it unpreserved on this save."
            )
            return None

    def read_achievements_from_disk(self) -> Optional[Achievements]:
        """Return the persisted ``achievements`` sub-field with lenient parsing.

        Sibling-agnostic like ``read_offchain_deposits_from_disk``: a corrupt
        sibling field must not drop the backlog-guard watermark on save.

        :return: the persisted ``Achievements``, or ``None`` if the file is
            missing, unreadable, has no ``achievements`` key, or the field
            itself fails validation (logged).
        """
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        try:
            with open(file_path, "r") as f:
                raw = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

        sub = raw.get("achievements") if isinstance(raw, dict) else None
        if not isinstance(sub, dict):
            return None

        try:
            return Achievements(**sub)
        except (AttributeError, TypeError, ValueError) as e:
            self.context.logger.warning(
                f"Persisted achievements failed validation ({e}); "
                "leaving them unpreserved on this save."
            )
            return None

    def read_leaderboard_from_disk(self) -> Optional[LeaderboardData]:
        """Return the persisted ``leaderboard`` section, ignoring sibling fields.

        :return: the section, or ``None`` if missing or unreadable.
        """
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        try:
            with open(file_path, "r") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return None

        sub = raw.get("leaderboard") if isinstance(raw, dict) else None
        return LeaderboardData.from_dict(sub)

    def read_activity_goal_from_disk(self) -> Optional[ActivityGoal]:
        """Return the persisted ``activity_goal`` block with lenient parsing.

        :return: the persisted ``ActivityGoal``, or ``None`` if unavailable.
        """
        return read_activity_goal(self.params.store_path)

    def write_offchain_deposits_to_disk(self, state: "OffchainDepositState") -> None:
        """Atomic-write ``offchain_deposits`` to disk, preserving sibling fields.

        Mirrors ``read_offchain_deposits_from_disk`` on the write side.
        Reads the raw JSON dict (bypassing every dataclass
        ``__post_init__``), updates only the ``offchain_deposits`` key,
        writes back atomically via tempfile + ``os.replace``.
        ``_fetch_offchain_prepaid_wei`` uses this instead of
        ``overwrite_performance_summary(summary)`` because the summary
        read it would otherwise pair with can silently degrade to a
        fresh dataclass on any nested-field ``__post_init__`` raise,
        which would then wipe every sibling field on disk (metrics,
        agent_details, prediction_history, ...) during the mid-cycle
        checkpoint write. Split-write keeps our checkpoint safe without
        depending on other fields' validation state.

        If the file is missing or unreadable, writes a minimal
        ``{"offchain_deposits": ...}`` — the operator has explicitly
        opted in to off-chain accounting at this point, so keeping the
        checkpoint alive is more important than refusing to write over
        a corrupt file. The next cycle-end
        ``_save_agent_performance_summary`` will re-populate the sibling
        fields from live data.

        :param state: the ``OffchainDepositState`` to persist.
        """
        write_performance_summary_key(
            self.params.store_path, "offchain_deposits", asdict(state)
        )

    def overwrite_performance_summary(self, summary: AgentPerformanceSummary) -> None:
        """Write the agent performance summary to a file atomically.

        Uses a same-directory temp file + ``os.replace`` so a mid-write
        crash (docker stop -t 0, OOM, disk full) can't leave the file
        truncated. Matters more than for the previous callers of this
        method: this PR is the first to persist irreversible state
        (``offchain_deposits.total_deposited_wei``) that cannot be
        re-derived from the subgraph.

        The ``leaderboard`` section is owned by the leaderboard refresh, which
        may have written it from its worker thread since the caller read the
        summary: the current section is re-applied under the file lock, so a
        full-summary write never rolls it back.

        :param summary: fully-populated summary to overwrite the persisted
            copy with.
        """
        data = asdict(summary)
        with SUMMARY_FILE_LOCK:
            leaderboard = self.get_leaderboard()
            data["leaderboard"] = None if leaderboard is None else asdict(leaderboard)
            write_json_atomically(
                self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE, data
            )

    def update_agent_behavior(self, behavior: str) -> None:
        """Update the agent behavior in agent performance template file."""
        existing_data = self.read_existing_performance_summary()
        existing_data.agent_behavior = behavior
        existing_data.timestamp = self.synced_timestamp
        self.overwrite_performance_summary(existing_data)

    def update_funds_locked_in_markets(self, value: float) -> None:
        """Update only the ``funds_locked_in_markets`` field in the summary.

        Lets external skills (e.g. the withdrawal behaviour at sweep
        end) bridge the cache-staleness gap between an event that
        changes on-chain locked value and the next normal performance
        summary round. The field is overwritten on the next normal
        round; this is an interim refresh.

        Lazily builds the nested ``AgentPerformanceData`` →
        ``PerformanceMetricsData`` chain when the file doesn't exist
        yet (first-ever run) or has only partially-populated nested
        fields.

        :param value: USD-equivalent value of currently locked positions.
        """
        existing = self.read_existing_performance_summary()
        if existing.agent_performance is None:
            existing.agent_performance = AgentPerformanceData(
                metrics=PerformanceMetricsData()
            )
        if existing.agent_performance.metrics is None:
            existing.agent_performance.metrics = PerformanceMetricsData()
        existing.agent_performance.metrics.funds_locked_in_markets = value
        existing.timestamp = self.synced_timestamp
        self.overwrite_performance_summary(existing)

    def get_leaderboard(self) -> Optional[LeaderboardData]:
        """Return the ``leaderboard`` section, reading the file only the first time.

        :return: the section, or ``None`` if there is none.
        """
        if not self._leaderboard_cache_loaded:
            with SUMMARY_FILE_LOCK:
                if not self._leaderboard_cache_loaded:
                    self._leaderboard_cache = self.read_leaderboard_from_disk()
                    self._leaderboard_cache_loaded = True
        return self._leaderboard_cache

    def update_leaderboard(self, leaderboard: LeaderboardData) -> None:
        """Store the ``leaderboard`` section, leaving sibling fields untouched.

        The in-memory copy is always updated. The file is not written when it
        exists but is not a JSON object: replacing it would wipe every other
        section (``offchain_deposits``, ``achievements``, ...); the next full
        summary save rewrites it, including this section.

        :param leaderboard: the leaderboard section to persist.
        """
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE
        with SUMMARY_FILE_LOCK:
            self._leaderboard_cache = leaderboard
            self._leaderboard_cache_loaded = True
            try:
                with open(file_path, "r") as f:
                    raw: Any = json.load(f)
            except FileNotFoundError:
                raw = {}
            except (OSError, ValueError) as e:
                raw = e
            if not isinstance(raw, dict):
                problem = (
                    raw
                    if isinstance(raw, Exception)
                    else f"a JSON {type(raw).__name__}"
                )
                self.context.logger.warning(
                    f"{file_path} is not a readable JSON object ({problem}); "
                    "not writing the leaderboard section to it"
                )
                return
            raw["leaderboard"] = asdict(leaderboard)
            write_json_atomically(file_path, raw)

    def update_leaderboard_window(
        self, window: LeaderboardWindow, entry: LeaderboardWindowRank
    ) -> None:
        """Store one window's rank, keeping the other windows and the watermark.

        :param window: the window the rank is for.
        :param entry: the rank.
        """
        with SUMMARY_FILE_LOCK:
            current = self.get_leaderboard() or LeaderboardData()
            windows = dict(current.windows)
            windows[window] = entry
            self.update_leaderboard(
                LeaderboardData(
                    windows=windows, last_attempt_at=current.last_attempt_at
                )
            )

    def is_leaderboard_refresh_running(self) -> bool:
        """Return whether a submitted leaderboard refresh has not finished yet.

        :return: whether a refresh is running or queued.
        """
        future = self._leaderboard_future
        return future is not None and not future.done()

    def submit_leaderboard_refresh(self, job: Callable[[], None]) -> bool:
        """Run ``job`` on the leaderboard worker thread unless one is running.

        :param job: the refresh; it must not touch the FSM state.
        :return: whether the job was submitted.
        """
        if self.is_leaderboard_refresh_running():
            return False
        if self._leaderboard_executor is None:
            self._leaderboard_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="leaderboard"
            )
            atexit.register(self.shutdown_leaderboard_executor)
        self._leaderboard_future = self._leaderboard_executor.submit(job)
        return True

    def shutdown_leaderboard_executor(self) -> None:
        """Shut the leaderboard worker down without waiting for a running job."""
        executor, self._leaderboard_executor = self._leaderboard_executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def teardown(self) -> None:
        """Tear down the state."""
        super().teardown()
        self.shutdown_leaderboard_executor()


class Subgraph(ApiSpecs):
    """Specifies `ApiSpecs` with common functionality for subgraphs."""

    def process_response(self, response: HttpMessage) -> Any:
        """Process the response."""
        res = super().process_response(response)
        if res is not None:
            return res

        error_data = self.response_info.error_data
        expected_error_type = getattr(builtins, self.response_info.error_type)
        if isinstance(error_data, expected_error_type):
            error_message_key = self.context.params.the_graph_error_message_key
            error_message = error_data.get(error_message_key, None)
            if (
                error_message is not None
                and self.context.params.the_graph_payment_required_error
                in error_message
            ):
                err = "Payment required for subsequent requests for the current 'The Graph' API key!"
                self.context.logger.error(err)
        return None


class OlasAgentsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Olas Agent's subgraph specifications for trades."""


class OlasMechSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Olas Mech's subgraph specifications."""


class OmenSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Omen xDai subgraph.

    Used to enrich bets from the olas_agents subgraph with Reality.eth
    finalization data (answerFinalizedTimestamp, isPendingArbitration),
    which is not exposed by the olas_agents subgraph's
    FixedProductMarketMakerCreation entity.
    """


class GnosisStakingSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Gnosis Staking's subgraph specifications."""


class PolygonStakingSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Polygon Staking's subgraph specifications."""


class OpenMarketsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Open Markets subgraph specifications."""


class TradesSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the OMEN's subgraph specifications for trades."""


class PolymarketAgentsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Polymarket Agent's subgraph specifications."""


class PolymarketBetsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Polymarket bets subgraph specifications."""


class PolymarketQuestionsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Polymarket questions subgraph."""


class PolygonMechSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Polygon Mech's subgraph specifications."""
