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
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

from packages.valory.protocols.http import HttpMessage
from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
)


AGENT_PERFORMANCE_SUMMARY_FILE = "agent_performance.json"


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


@dataclass
class ProfitOverTimeData:
    """Profit over time data stored in agent_performance.json."""

    last_updated: int  # Unix timestamp of last update
    total_days: int  # Total number of days with data
    data_points: List[ProfitDataPoint] = field(default_factory=list)
    settled_mech_requests_count: int = 0  # Total settled mech requests
    unplaced_mech_requests_count: int = 0  # Total mech requests with no bets placed
    includes_unplaced_mech_fees: bool = (
        False  # Whether unplaced mech fees logic was applied
    )

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

    def __post_init__(self) -> None:
        """Convert dicts to dataclass instances."""
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


class AgentPerformanceSummaryParams(BaseParams):
    """Agent Performance Summary's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.coingecko_olas_in_usd_price_url: str = self._ensure(
            "coingecko_olas_in_usd_price_url", kwargs, str
        )
        self.store_path: Path = self.get_store_path(kwargs)
        self.is_agent_performance_summary_enabled: bool = self._ensure(
            "is_agent_performance_summary_enabled", kwargs, bool
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

    def overwrite_performance_summary(self, summary: AgentPerformanceSummary) -> None:
        """Write the agent performance summary to a file."""
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        with open(file_path, "w") as f:
            json.dump(asdict(summary), f, indent=4)

    def update_agent_behavior(self, behavior: str) -> None:
        """Update the agent behavior in agent performance template file."""
        existing_data = self.read_existing_performance_summary()
        existing_data.agent_behavior = behavior
        existing_data.timestamp = self.synced_timestamp
        self.overwrite_performance_summary(existing_data)


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
            if self.context.params.the_graph_payment_required_error in error_message:
                err = "Payment required for subsequent requests for the current 'The Graph' API key!"
                self.context.logger.error(err)
        return None


class OlasAgentsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Olas Agent's subgraph specifications for trades."""


class OlasMechSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Olas Mech's subgraph specifications."""


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


class PolygonMechSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Polygon Mech's subgraph specifications."""
