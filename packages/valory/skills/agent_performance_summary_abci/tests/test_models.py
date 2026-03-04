# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for agent_performance_summary_abci models."""

import json
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.agent_performance_summary_abci.models import (
    AGENT_PERFORMANCE_SUMMARY_FILE,
    Achievement,
    Achievements,
    AgentDetails,
    AgentPerformanceData,
    AgentPerformanceMetrics,
    AgentPerformanceSummary,
    AgentPerformanceSummaryParams,
    GnosisStakingSubgraph,
    OlasAgentsSubgraph,
    OlasMechSubgraph,
    OpenMarketsSubgraph,
    PerformanceMetricsData,
    PerformanceStatsData,
    PolygonMechSubgraph,
    PolygonStakingSubgraph,
    PolymarketAgentsSubgraph,
    PolymarketBetsSubgraph,
    PredictionHistory,
    ProfitDataPoint,
    ProfitOverTimeData,
    SharedState,
    Subgraph,
    TradesSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
)


class TestConstant:
    """Tests for module-level constants."""

    def test_agent_performance_summary_file(self) -> None:
        """AGENT_PERFORMANCE_SUMMARY_FILE has the expected value."""
        assert AGENT_PERFORMANCE_SUMMARY_FILE == "agent_performance.json"


class TestAgentPerformanceMetrics:
    """Tests for the AgentPerformanceMetrics dataclass."""

    def test_create_with_all_fields(self) -> None:
        """Create with all fields including description."""
        m = AgentPerformanceMetrics(
            name="accuracy",
            is_primary=True,
            value="75%",
            description="<b>Prediction</b> accuracy",
        )
        assert m.name == "accuracy"
        assert m.is_primary is True
        assert m.value == "75%"
        assert m.description == "<b>Prediction</b> accuracy"

    def test_description_defaults_to_none(self) -> None:
        """Description is optional and defaults to None."""
        m = AgentPerformanceMetrics(name="roi", is_primary=False, value="10%")
        assert m.description is None


class TestAgentDetails:
    """Tests for the AgentDetails dataclass."""

    def test_defaults_all_none(self) -> None:
        """Create with all defaults; all fields are None."""
        d = AgentDetails()
        assert d.id is None
        assert d.created_at is None
        assert d.last_active_at is None

    def test_create_with_values(self) -> None:
        """Create with explicit values."""
        d = AgentDetails(
            id="agent-001",
            created_at="2024-01-01T00:00:00Z",
            last_active_at="2024-06-01T12:00:00Z",
        )
        assert d.id == "agent-001"
        assert d.created_at == "2024-01-01T00:00:00Z"
        assert d.last_active_at == "2024-06-01T12:00:00Z"


class TestPerformanceMetricsData:
    """Tests for the PerformanceMetricsData dataclass."""

    def test_defaults_all_none(self) -> None:
        """Create with all defaults; all fields are None."""
        m = PerformanceMetricsData()
        assert m.all_time_funds_used is None
        assert m.all_time_profit is None
        assert m.funds_locked_in_markets is None
        assert m.available_funds is None
        assert m.roi is None
        assert m.settled_mech_request_count is None
        assert m.total_mech_request_count is None
        assert m.open_mech_request_count is None
        assert m.placed_mech_request_count is None
        assert m.unplaced_mech_request_count is None

    def test_create_with_values(self) -> None:
        """Create with explicit values."""
        m = PerformanceMetricsData(
            all_time_funds_used=100.5,
            all_time_profit=50.25,
            funds_locked_in_markets=30.0,
            available_funds=20.25,
            roi=0.5,
            settled_mech_request_count=10,
            total_mech_request_count=15,
            open_mech_request_count=3,
            placed_mech_request_count=8,
            unplaced_mech_request_count=2,
        )
        assert m.all_time_funds_used == 100.5
        assert m.all_time_profit == 50.25
        assert m.settled_mech_request_count == 10
        assert m.total_mech_request_count == 15
        assert m.placed_mech_request_count == 8
        assert m.unplaced_mech_request_count == 2


class TestPerformanceStatsData:
    """Tests for the PerformanceStatsData dataclass."""

    def test_defaults_all_none(self) -> None:
        """Create with all defaults; all fields are None."""
        s = PerformanceStatsData()
        assert s.predictions_made is None
        assert s.prediction_accuracy is None

    def test_create_with_values(self) -> None:
        """Create with explicit values."""
        s = PerformanceStatsData(predictions_made=100, prediction_accuracy=0.75)
        assert s.predictions_made == 100
        assert s.prediction_accuracy == 0.75


class TestAgentPerformanceData:
    """Tests for the AgentPerformanceData dataclass."""

    def test_defaults(self) -> None:
        """Create with defaults."""
        d = AgentPerformanceData()
        assert d.window == "lifetime"
        assert d.currency == "USD"
        assert d.metrics is None
        assert d.stats is None

    def test_post_init_converts_metrics_dict(self) -> None:
        """__post_init__ converts a metrics dict to PerformanceMetricsData."""
        d = AgentPerformanceData(
            metrics={"all_time_funds_used": 100.0, "roi": 0.5}  # type: ignore[arg-type]
        )
        assert isinstance(d.metrics, PerformanceMetricsData)
        assert d.metrics.all_time_funds_used == 100.0
        assert d.metrics.roi == 0.5

    def test_post_init_converts_stats_dict(self) -> None:
        """__post_init__ converts a stats dict to PerformanceStatsData."""
        d = AgentPerformanceData(
            stats={"predictions_made": 50, "prediction_accuracy": 0.8}  # type: ignore[arg-type]
        )
        assert isinstance(d.stats, PerformanceStatsData)
        assert d.stats.predictions_made == 50

    def test_post_init_with_instances_no_conversion(self) -> None:
        """When metrics/stats are already instances, no conversion occurs."""
        metrics = PerformanceMetricsData(roi=0.3)
        stats = PerformanceStatsData(predictions_made=20)
        d = AgentPerformanceData(metrics=metrics, stats=stats)
        assert d.metrics is metrics
        assert d.stats is stats


class TestPredictionHistory:
    """Tests for the PredictionHistory dataclass."""

    def test_defaults(self) -> None:
        """Create with defaults."""
        ph = PredictionHistory()
        assert ph.total_predictions == 0
        assert ph.stored_count == 0
        assert ph.last_updated is None
        assert ph.items == []

    def test_create_with_values(self) -> None:
        """Create with explicit values."""
        items = [{"id": "1", "result": True}]
        ph = PredictionHistory(
            total_predictions=10,
            stored_count=5,
            last_updated=1700000000,
            items=items,
        )
        assert ph.total_predictions == 10
        assert ph.stored_count == 5
        assert ph.last_updated == 1700000000
        assert ph.items == items


class TestProfitDataPoint:
    """Tests for the ProfitDataPoint dataclass."""

    def test_create_with_required_fields(self) -> None:
        """Create with all required fields; daily_profit_raw defaults to None."""
        p = ProfitDataPoint(
            date="2024-01-01",
            timestamp=1704067200,
            daily_profit=10.5,
            cumulative_profit=100.0,
        )
        assert p.date == "2024-01-01"
        assert p.timestamp == 1704067200
        assert p.daily_profit == 10.5
        assert p.cumulative_profit == 100.0
        assert p.daily_mech_requests == 0
        assert p.daily_profit_raw is None

    def test_create_with_optional_daily_profit_raw(self) -> None:
        """Create with daily_profit_raw set."""
        p = ProfitDataPoint(
            date="2024-01-01",
            timestamp=1704067200,
            daily_profit=10.5,
            cumulative_profit=100.0,
            daily_mech_requests=5,
            daily_profit_raw=12.0,
        )
        assert p.daily_profit_raw == 12.0
        assert p.daily_mech_requests == 5


class TestProfitOverTimeData:
    """Tests for the ProfitOverTimeData dataclass."""

    def test_post_init_converts_dicts_to_profit_data_points(self) -> None:
        """__post_init__ converts list of dicts to ProfitDataPoint instances."""
        data_points = [
            {
                "date": "2024-01-01",
                "timestamp": 1704067200,
                "daily_profit": 10.0,
                "cumulative_profit": 10.0,
            },
            {
                "date": "2024-01-02",
                "timestamp": 1704153600,
                "daily_profit": 5.0,
                "cumulative_profit": 15.0,
            },
        ]
        pot = ProfitOverTimeData(
            last_updated=1704153600,
            total_days=2,
            data_points=data_points,  # type: ignore[arg-type]
        )
        assert len(pot.data_points) == 2
        assert all(isinstance(dp, ProfitDataPoint) for dp in pot.data_points)
        assert pot.data_points[0].date == "2024-01-01"
        assert pot.data_points[1].daily_profit == 5.0

    def test_empty_data_points_no_conversion(self) -> None:
        """Empty data_points list requires no conversion."""
        pot = ProfitOverTimeData(last_updated=1704153600, total_days=0)
        assert pot.data_points == []

    def test_with_profit_data_point_instances(self) -> None:
        """When data_points are already ProfitDataPoint instances, no conversion occurs."""
        point = ProfitDataPoint(
            date="2024-01-01",
            timestamp=1704067200,
            daily_profit=10.0,
            cumulative_profit=10.0,
        )
        pot = ProfitOverTimeData(
            last_updated=1704067200,
            total_days=1,
            data_points=[point],
        )
        assert pot.data_points[0] is point

    def test_extra_fields_defaults(self) -> None:
        """Test extra fields have correct defaults."""
        pot = ProfitOverTimeData(last_updated=1704067200, total_days=0)
        assert pot.settled_mech_requests_count == 0
        assert pot.unplaced_mech_requests_count == 0
        assert pot.placed_mech_requests_count == 0
        assert pot.includes_unplaced_mech_fees is False


class TestAchievement:
    """Tests for the Achievement dataclass."""

    def test_create_with_all_fields(self) -> None:
        """Create with all required fields."""
        a = Achievement(
            achievement_id="first-bet",
            achievement_type="milestone",
            title="First Bet",
            description="Placed your first bet",
            timestamp=1700000000,
            data={"bet_id": "123"},
        )
        assert a.achievement_id == "first-bet"
        assert a.achievement_type == "milestone"
        assert a.title == "First Bet"
        assert a.description == "Placed your first bet"
        assert a.timestamp == 1700000000
        assert a.data == {"bet_id": "123"}


class TestAchievements:
    """Tests for the Achievements dataclass."""

    def test_empty_items_returns_early(self) -> None:
        """__post_init__ returns early when items is empty."""
        a = Achievements()
        assert a.items == {}

    def test_post_init_converts_dicts_to_achievement_instances(self) -> None:
        """__post_init__ converts dict values to Achievement instances."""
        items = {
            "first-bet": {
                "achievement_id": "first-bet",
                "achievement_type": "milestone",
                "title": "First Bet",
                "description": "Placed your first bet",
                "timestamp": 1700000000,
                "data": {"bet_id": "123"},
            },
            "ten-bets": {
                "achievement_id": "ten-bets",
                "achievement_type": "milestone",
                "title": "Ten Bets",
                "description": "Placed ten bets",
                "timestamp": 1700100000,
                "data": {},
            },
        }
        a = Achievements(items=items)  # type: ignore[arg-type]
        assert len(a.items) == 2
        assert all(isinstance(v, Achievement) for v in a.items.values())
        assert a.items["first-bet"].title == "First Bet"
        assert a.items["ten-bets"].timestamp == 1700100000

    def test_with_achievement_instances_no_conversion(self) -> None:
        """When items values are already Achievement instances, no conversion occurs."""
        ach = Achievement(
            achievement_id="first-bet",
            achievement_type="milestone",
            title="First Bet",
            description="Placed your first bet",
            timestamp=1700000000,
            data={},
        )
        a = Achievements(items={"first-bet": ach})
        assert a.items["first-bet"] is ach


class TestAgentPerformanceSummary:
    """Tests for the AgentPerformanceSummary dataclass."""

    def test_all_defaults(self) -> None:
        """Create with all defaults."""
        s = AgentPerformanceSummary()
        assert s.timestamp is None
        assert s.metrics == []
        assert s.agent_behavior is None
        assert s.agent_details is None
        assert s.agent_performance is None
        assert s.prediction_history is None
        assert s.profit_over_time is None
        assert s.achievements is None

    def test_post_init_converts_agent_details_dict(self) -> None:
        """__post_init__ converts agent_details dict to AgentDetails."""
        s = AgentPerformanceSummary(
            agent_details={"id": "agent-001", "created_at": "2024-01-01T00:00:00Z"}  # type: ignore[arg-type]
        )
        assert isinstance(s.agent_details, AgentDetails)
        assert s.agent_details.id == "agent-001"

    def test_post_init_converts_agent_performance_dict(self) -> None:
        """__post_init__ converts agent_performance dict to AgentPerformanceData."""
        s = AgentPerformanceSummary(
            agent_performance={"window": "7d", "currency": "EUR"}  # type: ignore[arg-type]
        )
        assert isinstance(s.agent_performance, AgentPerformanceData)
        assert s.agent_performance.window == "7d"
        assert s.agent_performance.currency == "EUR"

    def test_post_init_converts_prediction_history_dict(self) -> None:
        """__post_init__ converts prediction_history dict to PredictionHistory."""
        s = AgentPerformanceSummary(
            prediction_history={"total_predictions": 50, "stored_count": 10}  # type: ignore[arg-type]
        )
        assert isinstance(s.prediction_history, PredictionHistory)
        assert s.prediction_history.total_predictions == 50

    def test_post_init_converts_profit_over_time_dict(self) -> None:
        """__post_init__ converts profit_over_time dict to ProfitOverTimeData."""
        s = AgentPerformanceSummary(
            profit_over_time={"last_updated": 1704067200, "total_days": 3}  # type: ignore[arg-type]
        )
        assert isinstance(s.profit_over_time, ProfitOverTimeData)
        assert s.profit_over_time.last_updated == 1704067200

    def test_post_init_converts_achievements_dict(self) -> None:
        """__post_init__ converts achievements dict to Achievements."""
        s = AgentPerformanceSummary(
            achievements={"items": {}}  # type: ignore[arg-type]
        )
        assert isinstance(s.achievements, Achievements)
        assert s.achievements.items == {}

    def test_post_init_with_instances_no_conversion(self) -> None:
        """When fields are already instances, no conversion occurs."""
        details = AgentDetails(id="agent-001")
        perf = AgentPerformanceData()
        history = PredictionHistory()
        pot = ProfitOverTimeData(last_updated=0, total_days=0)
        achievements = Achievements()

        s = AgentPerformanceSummary(
            agent_details=details,
            agent_performance=perf,
            prediction_history=history,
            profit_over_time=pot,
            achievements=achievements,
        )
        assert s.agent_details is details
        assert s.agent_performance is perf
        assert s.prediction_history is history
        assert s.profit_over_time is pot
        assert s.achievements is achievements


# Default kwargs for AgentPerformanceSummaryParams init
DEFAULT_APS_KWARGS: Dict[str, Any] = {
    "coingecko_olas_in_usd_price_url": "https://api.coingecko.com/olas",
    "coingecko_pol_in_usd_price_url": "https://api.coingecko.com/pol",
    "is_agent_performance_summary_enabled": True,
    "is_achievement_checker_enabled": True,
    "is_running_on_polymarket": False,
}


class TestAgentPerformanceSummaryParams:
    """Tests for AgentPerformanceSummaryParams.__init__."""

    def test_init_sets_all_attributes(self, tmp_path: Path) -> None:
        """Init sets all required attributes from kwargs."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            params = AgentPerformanceSummaryParams(
                skill_context=mock_skill_context,
                store_path=str(tmp_path),
                **DEFAULT_APS_KWARGS,
            )
        assert (
            params.coingecko_olas_in_usd_price_url == "https://api.coingecko.com/olas"
        )
        assert params.coingecko_pol_in_usd_price_url == "https://api.coingecko.com/pol"
        assert params.store_path == tmp_path
        assert params.is_agent_performance_summary_enabled is True
        assert params.is_achievement_checker_enabled is True
        assert params.is_running_on_polymarket is False

    def test_init_calls_super(self, tmp_path: Path) -> None:
        """Init calls BaseParams.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None) as mock_super:
            AgentPerformanceSummaryParams(
                skill_context=mock_skill_context,
                store_path=str(tmp_path),
                **DEFAULT_APS_KWARGS,
            )
        mock_super.assert_called_once()

    def test_is_running_on_polymarket_already_set(self, tmp_path: Path) -> None:
        """When is_running_on_polymarket is already set (hasattr branch), keep it."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            # Pre-set the attribute before __init__ runs
            # We do this by creating the object without __init__, setting the attr,
            # then calling __init__
            params = object.__new__(AgentPerformanceSummaryParams)
            params.is_running_on_polymarket = True  # type: ignore[attr-defined]
            # Now call __init__ - the hasattr branch should fire
            params.__init__(  # type: ignore[misc]
                skill_context=mock_skill_context,
                store_path=str(tmp_path),
                coingecko_olas_in_usd_price_url="https://api.coingecko.com/olas",
                coingecko_pol_in_usd_price_url="https://api.coingecko.com/pol",
                is_agent_performance_summary_enabled=True,
                is_achievement_checker_enabled=True,
                is_running_on_polymarket=False,
            )
        # The pre-set value should remain (hasattr returned True, so it kept existing value)
        assert params.is_running_on_polymarket is True

    def test_is_running_on_polymarket_not_set(self, tmp_path: Path) -> None:
        """When is_running_on_polymarket is not set, set it from kwargs."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            params = AgentPerformanceSummaryParams(
                skill_context=mock_skill_context,
                store_path=str(tmp_path),
                coingecko_olas_in_usd_price_url="https://api.coingecko.com/olas",
                coingecko_pol_in_usd_price_url="https://api.coingecko.com/pol",
                is_agent_performance_summary_enabled=True,
                is_achievement_checker_enabled=True,
                is_running_on_polymarket=True,
            )
        assert params.is_running_on_polymarket is True


class TestGetStorePath:
    """Tests for AgentPerformanceSummaryParams.get_store_path."""

    def _make_params_object(self) -> AgentPerformanceSummaryParams:
        """Create a bare AgentPerformanceSummaryParams for testing get_store_path."""
        return object.__new__(AgentPerformanceSummaryParams)

    def test_valid_directory(self, tmp_path: Path) -> None:
        """Valid writable directory returns a Path object."""
        params = self._make_params_object()
        kwargs: Dict[str, Any] = {
            "skill_context": MagicMock(),
            "store_path": str(tmp_path),
        }
        result = params.get_store_path(kwargs)
        assert isinstance(result, Path)
        assert result == tmp_path

    def test_invalid_directory_raises(self) -> None:
        """Non-existent directory raises ValueError."""
        params = self._make_params_object()
        kwargs: Dict[str, Any] = {
            "skill_context": MagicMock(),
            "store_path": "/nonexistent/path/should/not/exist",
        }
        with pytest.raises(ValueError, match="is not a directory or is not writable"):
            params.get_store_path(kwargs)

    def test_non_writable_directory_raises(self, tmp_path: Path) -> None:
        """A directory without write permissions raises ValueError."""
        read_only_dir = tmp_path / "read_only"
        read_only_dir.mkdir()
        read_only_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            params = self._make_params_object()
            kwargs: Dict[str, Any] = {
                "skill_context": MagicMock(),
                "store_path": str(read_only_dir),
            }
            with pytest.raises(
                ValueError, match="is not a directory or is not writable"
            ):
                params.get_store_path(kwargs)
        finally:
            read_only_dir.chmod(stat.S_IRWXU)

    def test_non_readable_directory_raises(self, tmp_path: Path) -> None:
        """A directory without read permissions raises ValueError."""
        no_read_dir = tmp_path / "no_read"
        no_read_dir.mkdir()
        no_read_dir.chmod(stat.S_IWUSR | stat.S_IXUSR)
        try:
            params = self._make_params_object()
            kwargs: Dict[str, Any] = {
                "skill_context": MagicMock(),
                "store_path": str(no_read_dir),
            }
            with pytest.raises(
                ValueError, match="is not a directory or is not writable"
            ):
                params.get_store_path(kwargs)
        finally:
            no_read_dir.chmod(stat.S_IRWXU)

    def test_file_path_raises(self, tmp_path: Path) -> None:
        """A path that is a file (not a directory) raises ValueError."""
        file_path = tmp_path / "a_file.txt"
        file_path.write_text("content")
        params = self._make_params_object()
        kwargs: Dict[str, Any] = {
            "skill_context": MagicMock(),
            "store_path": str(file_path),
        }
        with pytest.raises(ValueError, match="is not a directory or is not writable"):
            params.get_store_path(kwargs)


class _TestableSharedState(SharedState):
    """Subclass that overrides the read-only context property for testing.

    Model.context is a property from the AEA framework; this subclass
    shadows it with a plain attribute so tests can inject a MagicMock.
    """

    context = None  # type: ignore[assignment]


class TestSharedState:
    """Tests for SharedState model."""

    def _make_state(self) -> _TestableSharedState:
        """Create a testable SharedState instance with mocked context."""
        state = object.__new__(_TestableSharedState)
        state.context = MagicMock()  # type: ignore[assignment]
        return state

    def test_abci_app_cls(self) -> None:
        """Test that SharedState points to AgentPerformanceSummaryAbciApp."""
        assert SharedState.abci_app_cls is AgentPerformanceSummaryAbciApp

    def test_params_property(self) -> None:
        """Params property returns context.params cast to AgentPerformanceSummaryParams."""
        state = self._make_state()
        mock_params = MagicMock(spec=AgentPerformanceSummaryParams)
        state.context.params = mock_params  # type: ignore[attr-defined]
        result = state.params
        assert result is mock_params

    def test_synced_timestamp_property(self) -> None:
        """synced_timestamp returns the int timestamp from round_sequence."""
        state = self._make_state()
        mock_ts = MagicMock()
        mock_ts.timestamp.return_value = 1700000000.5
        state.context.state.round_sequence.last_round_transition_timestamp = mock_ts  # type: ignore[attr-defined]
        result = state.synced_timestamp
        assert result == 1700000000
        assert isinstance(result, int)

    def test_read_existing_performance_summary_happy_path(self, tmp_path: Path) -> None:
        """read_existing_performance_summary reads and returns data from file."""
        state = self._make_state()

        mock_params = MagicMock()
        mock_params.store_path = tmp_path
        state.context.params = mock_params  # type: ignore[attr-defined]

        summary = AgentPerformanceSummary(
            timestamp=1700000000,
            agent_behavior="active",
        )
        file_path = tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE
        with open(file_path, "w") as f:
            json.dump(asdict(summary), f)

        result = state.read_existing_performance_summary()
        assert isinstance(result, AgentPerformanceSummary)
        assert result.timestamp == 1700000000
        assert result.agent_behavior == "active"

    def test_read_existing_performance_summary_file_not_found(
        self, tmp_path: Path
    ) -> None:
        """read_existing_performance_summary returns empty summary on FileNotFoundError."""
        state = self._make_state()

        mock_params = MagicMock()
        mock_params.store_path = tmp_path
        state.context.params = mock_params  # type: ignore[attr-defined]

        result = state.read_existing_performance_summary()
        assert isinstance(result, AgentPerformanceSummary)
        assert result.timestamp is None
        state.context.logger.warning.assert_called_once()  # type: ignore[attr-defined]

    def test_read_existing_performance_summary_json_decode_error(
        self, tmp_path: Path
    ) -> None:
        """read_existing_performance_summary returns empty summary on JSONDecodeError."""
        state = self._make_state()

        mock_params = MagicMock()
        mock_params.store_path = tmp_path
        state.context.params = mock_params  # type: ignore[attr-defined]

        file_path = tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE
        file_path.write_text("not valid json {{{")

        result = state.read_existing_performance_summary()
        assert isinstance(result, AgentPerformanceSummary)
        assert result.timestamp is None
        state.context.logger.warning.assert_called_once()  # type: ignore[attr-defined]

    def test_overwrite_performance_summary(self, tmp_path: Path) -> None:
        """overwrite_performance_summary writes JSON to file."""
        state = self._make_state()

        mock_params = MagicMock()
        mock_params.store_path = tmp_path
        state.context.params = mock_params  # type: ignore[attr-defined]

        summary = AgentPerformanceSummary(
            timestamp=1700000000,
            agent_behavior="observing",
        )
        state.overwrite_performance_summary(summary)

        file_path = tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE
        assert file_path.exists()
        with open(file_path, "r") as f:
            data = json.load(f)
        assert data["timestamp"] == 1700000000
        assert data["agent_behavior"] == "observing"

    def test_update_agent_behavior(self, tmp_path: Path) -> None:
        """update_agent_behavior reads, updates behavior and timestamp, then writes."""
        state = self._make_state()

        mock_params = MagicMock()
        mock_params.store_path = tmp_path
        state.context.params = mock_params  # type: ignore[attr-defined]

        # Set up synced_timestamp
        mock_ts = MagicMock()
        mock_ts.timestamp.return_value = 1700000100.0
        state.context.state.round_sequence.last_round_transition_timestamp = mock_ts  # type: ignore[attr-defined]

        # Write initial data
        initial = AgentPerformanceSummary(timestamp=1700000000, agent_behavior="idle")
        file_path = tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE
        with open(file_path, "w") as f:
            json.dump(asdict(initial), f)

        state.update_agent_behavior("active")

        with open(file_path, "r") as f:
            data = json.load(f)
        assert data["agent_behavior"] == "active"
        assert data["timestamp"] == 1700000100


class _TestableSubgraph(Subgraph):
    """Subclass that overrides the read-only context property for testing.

    Model.context is a property from the AEA framework; this subclass
    shadows it with a plain attribute so tests can inject a MagicMock.
    """

    context = None  # type: ignore[assignment]


class TestSubgraphProcessResponse:
    """Tests for Subgraph.process_response."""

    def _make_subgraph(self) -> _TestableSubgraph:
        """Create a testable Subgraph instance with mocked internals."""
        subgraph = object.__new__(_TestableSubgraph)
        subgraph.__dict__["_frozen"] = False
        subgraph.context = MagicMock()  # type: ignore[assignment]
        subgraph.response_info = MagicMock()  # type: ignore[assignment]
        subgraph.response_info.error_type = "dict"
        return subgraph

    def test_returns_result_when_super_returns_non_none(self) -> None:
        """When super().process_response returns non-None, return it directly."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()
        expected_result = {"data": {"agents": []}}  # type: ignore[var-annotated]

        with patch.object(ApiSpecs, "process_response", return_value=expected_result):
            result = subgraph.process_response(mock_response)

        assert result is expected_result

    def test_returns_none_and_logs_payment_required(self) -> None:
        """When super returns None and error_data matches payment required, log error."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        error_message_key = "message"
        payment_required_error = "payment required"
        subgraph.context.params.the_graph_error_message_key = error_message_key  # type: ignore[attr-defined]
        subgraph.context.params.the_graph_payment_required_error = (  # type: ignore[attr-defined]
            payment_required_error
        )
        subgraph.response_info.error_data = {
            "message": "402 payment required for this request"
        }
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            result = subgraph.process_response(mock_response)

        assert result is None
        subgraph.context.logger.error.assert_called_once_with(  # type: ignore[attr-defined]
            "Payment required for subsequent requests for the current 'The Graph' API key!"
        )

    def test_returns_none_no_payment_required_match(self) -> None:
        """When super returns None and error does not match payment required, no log."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        error_message_key = "message"
        payment_required_error = "payment required"
        subgraph.context.params.the_graph_error_message_key = error_message_key  # type: ignore[attr-defined]
        subgraph.context.params.the_graph_payment_required_error = (  # type: ignore[attr-defined]
            payment_required_error
        )
        subgraph.response_info.error_data = {"message": "some other error occurred"}
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            result = subgraph.process_response(mock_response)

        assert result is None
        subgraph.context.logger.error.assert_not_called()  # type: ignore[attr-defined]

    def test_returns_none_when_error_data_is_not_expected_type(self) -> None:
        """When error_data does not match expected_error_type, skip the check."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        subgraph.response_info.error_data = "a string error, not a dict"
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            result = subgraph.process_response(mock_response)

        assert result is None
        subgraph.context.logger.error.assert_not_called()  # type: ignore[attr-defined]

    def test_returns_none_when_error_message_key_missing(self) -> None:
        """When error_data is a dict but missing the error_message_key, return None."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        error_message_key = "message"
        payment_required_error = "payment required"
        subgraph.context.params.the_graph_error_message_key = error_message_key  # type: ignore[attr-defined]
        subgraph.context.params.the_graph_payment_required_error = (  # type: ignore[attr-defined]
            payment_required_error
        )
        subgraph.response_info.error_data = {"other_key": "some value"}
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            # error_data.get(error_message_key, None) returns None
            # "payment required" in None will raise TypeError
            with pytest.raises(TypeError):
                subgraph.process_response(mock_response)


class TestSubgraphSubclasses:
    """Tests that all subgraph subclasses inherit from Subgraph."""

    @pytest.mark.parametrize(
        "cls",
        [
            OlasAgentsSubgraph,
            OlasMechSubgraph,
            GnosisStakingSubgraph,
            PolygonStakingSubgraph,
            OpenMarketsSubgraph,
            TradesSubgraph,
            PolymarketAgentsSubgraph,
            PolymarketBetsSubgraph,
            PolygonMechSubgraph,
        ],
    )
    def test_is_subclass_of_subgraph(self, cls: type) -> None:
        """Each subgraph class is a subclass of Subgraph."""
        assert issubclass(cls, Subgraph)

    @pytest.mark.parametrize(
        "cls",
        [
            OlasAgentsSubgraph,
            OlasMechSubgraph,
            GnosisStakingSubgraph,
            PolygonStakingSubgraph,
            OpenMarketsSubgraph,
            TradesSubgraph,
            PolymarketAgentsSubgraph,
            PolymarketBetsSubgraph,
            PolygonMechSubgraph,
        ],
    )
    def test_is_subclass_of_api_specs(self, cls: type) -> None:
        """Each subgraph class is also a subclass of ApiSpecs."""
        assert issubclass(cls, ApiSpecs)
