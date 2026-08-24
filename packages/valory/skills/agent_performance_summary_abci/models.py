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

import builtins
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

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
        self.mech_analytics_url: str = self._ensure("mech_analytics_url", kwargs, str)
        self.use_mech_analytics: bool = self._ensure("use_mech_analytics", kwargs, bool)
        # Enforce the pairing at startup — fail loudly rather than
        # silently no-op'ing back to the subgraph path when an operator
        # enables the flag but forgets the URL.
        if self.use_mech_analytics and not self.mech_analytics_url:
            raise ValueError(
                "use_mech_analytics is true but mech_analytics_url is empty; "
                "set MECH_ANALYTICS_URL or turn USE_MECH_ANALYTICS off"
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

    @property
    def params(self) -> AgentPerformanceSummaryParams:
        """Return the params."""
        return cast(AgentPerformanceSummaryParams, self.context.params)

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(
            self.context.state.round_sequence.last_round_transition_timestamp.timestamp()
        )

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
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        try:
            with open(file_path, "r") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
        except (FileNotFoundError, json.JSONDecodeError):
            raw = {}

        raw["offchain_deposits"] = asdict(state)

        # tempfile in the same directory so ``os.replace`` is atomic on
        # POSIX (both paths on one filesystem).
        fd, tmp_path = tempfile.mkstemp(
            prefix=file_path.name + ".", dir=str(file_path.parent)
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(raw, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def overwrite_performance_summary(self, summary: AgentPerformanceSummary) -> None:
        """Write the agent performance summary to a file atomically.

        Uses a same-directory temp file + ``os.replace`` so a mid-write
        crash (docker stop -t 0, OOM, disk full) can't leave the file
        truncated. Matters more than for the previous callers of this
        method: this PR is the first to persist irreversible state
        (``offchain_deposits.total_deposited_wei``) that cannot be
        re-derived from the subgraph.

        :param summary: fully-populated summary to overwrite the persisted
            copy with.
        """
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        # tempfile in the same directory so ``os.replace`` is atomic on
        # POSIX (both paths on one filesystem).
        fd, tmp_path = tempfile.mkstemp(
            prefix=file_path.name + ".", dir=str(file_path.parent)
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(summary), f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
        except Exception:
            # Best-effort cleanup of the stale temp file.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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
