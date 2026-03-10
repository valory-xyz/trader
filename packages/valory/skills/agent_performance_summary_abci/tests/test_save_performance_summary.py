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

"""Tests for _save_agent_performance_summary preserving data on API failures."""

from typing import Any, List
from unittest.mock import MagicMock

from packages.valory.skills.agent_performance_summary_abci.behaviours import (
    FetchPerformanceSummaryBehaviour,
    NA,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AgentDetails,
    AgentPerformanceData,
    AgentPerformanceMetrics,
    AgentPerformanceSummary,
    PerformanceMetricsData,
    PerformanceStatsData,
    PredictionHistory,
    ProfitDataPoint,
    ProfitOverTimeData,
)


class _TestableBehaviour(FetchPerformanceSummaryBehaviour):
    """Shadows read-only AEA properties with plain instance attributes."""

    context: Any = None
    shared_state: Any = None
    synchronized_data: Any = None
    params: Any = None


def _make_behaviour(
    existing_summary: AgentPerformanceSummary,
) -> _TestableBehaviour:
    """Return a _TestableBehaviour wired with mocked dependencies."""
    behaviour = object.__new__(_TestableBehaviour)  # type: ignore[type-abstract]

    shared_state = MagicMock()
    shared_state.read_existing_performance_summary.return_value = existing_summary
    shared_state.overwrite_performance_summary = MagicMock()

    behaviour.shared_state = shared_state
    behaviour.context = MagicMock()
    return behaviour


def _good_metrics() -> List[AgentPerformanceMetrics]:
    """Return a list of metrics with real values."""
    return [
        AgentPerformanceMetrics(name="Total ROI", is_primary=True, value="12.5%"),
        AgentPerformanceMetrics(
            name="Prediction accuracy", is_primary=False, value="75%"
        ),
        AgentPerformanceMetrics(
            name="Total staking rewards", is_primary=False, value="3.2 OLAS"
        ),
    ]


def _na_metrics() -> List[AgentPerformanceMetrics]:
    """Return a list of metrics with NA values (API failure)."""
    return [
        AgentPerformanceMetrics(name="Total ROI", is_primary=True, value=NA),
        AgentPerformanceMetrics(name="Prediction accuracy", is_primary=False, value=NA),
        AgentPerformanceMetrics(
            name="Total staking rewards", is_primary=False, value=NA
        ),
    ]


def _good_agent_details() -> AgentDetails:
    """Return agent details with real values."""
    return AgentDetails(
        id="0xabc123",
        created_at="2025-01-01T00:00:00Z",
        last_active_at="2025-06-15T12:00:00Z",
    )


def _none_agent_details() -> AgentDetails:
    """Return agent details with all-None fields (API failure)."""
    return AgentDetails(id=None, created_at=None, last_active_at=None)


def _good_agent_performance() -> AgentPerformanceData:
    """Return agent performance data with real values."""
    return AgentPerformanceData(
        metrics=PerformanceMetricsData(
            all_time_funds_used=100.0,
            all_time_profit=12.5,
            roi=0.125,
        ),
        stats=PerformanceStatsData(
            predictions_made=50,
            prediction_accuracy=0.75,
        ),
    )


def _none_agent_performance() -> AgentPerformanceData:
    """Return agent performance data with all-None key fields (API failure)."""
    return AgentPerformanceData(
        metrics=PerformanceMetricsData(
            all_time_funds_used=None,
            all_time_profit=None,
            roi=None,
        ),
    )


def _good_profit_over_time() -> ProfitOverTimeData:
    """Return profit over time with real data."""
    return ProfitOverTimeData(
        last_updated=1700000000,
        total_days=30,
        data_points=[
            ProfitDataPoint(
                date="2025-06-01",
                timestamp=1700000000,
                daily_profit=1.5,
                cumulative_profit=10.0,
            )
        ],
    )


def _good_prediction_history() -> PredictionHistory:
    """Return prediction history with real data."""
    return PredictionHistory(
        total_predictions=50,
        stored_count=25,
        last_updated=1700000000,
        items=[{"id": "1", "outcome": "win"}],
    )


def _empty_prediction_history() -> PredictionHistory:
    """Return prediction history with 0 predictions (API failure)."""
    return PredictionHistory(
        total_predictions=0,
        stored_count=0,
        last_updated=None,
        items=[],
    )


def _good_existing_summary() -> AgentPerformanceSummary:
    """Return a fully populated existing summary."""
    return AgentPerformanceSummary(
        timestamp=1700000000,
        metrics=_good_metrics(),
        agent_behavior="some_behavior",
        agent_details=_good_agent_details(),
        agent_performance=_good_agent_performance(),
        prediction_history=_good_prediction_history(),
        profit_over_time=_good_profit_over_time(),
    )


class TestSaveAgentPerformanceSummary:
    """Tests for _save_agent_performance_summary merge logic."""

    def test_save_overwrites_with_good_data(self) -> None:
        """When all new data is valid, it should fully replace existing data."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_metrics = [
            AgentPerformanceMetrics(name="Total ROI", is_primary=True, value="20%"),
            AgentPerformanceMetrics(
                name="Prediction accuracy", is_primary=False, value="80%"
            ),
        ]
        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=new_metrics,
            agent_details=AgentDetails(
                id="0xdef456",
                created_at="2025-02-01T00:00:00Z",
                last_active_at="2025-06-20T12:00:00Z",
            ),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.metrics[0].value == "20%"
        assert saved.metrics[1].value == "80%"
        assert saved.agent_details.id == "0xdef456"
        assert saved.agent_performance.metrics.roi == 0.125
        assert saved.timestamp == 1700001000
        # agent_behavior should always come from existing
        assert saved.agent_behavior == "some_behavior"

    def test_save_preserves_metrics_on_na(self) -> None:
        """When new metrics have NA values but existing had real values, preserve existing."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_na_metrics(),
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        # NA metrics should be replaced with existing values
        assert saved.metrics[0].value == "12.5%"
        assert saved.metrics[1].value == "75%"
        assert saved.metrics[2].value == "3.2 OLAS"

    def test_save_preserves_agent_details_on_failure(self) -> None:
        """When new agent_details has all-None fields, preserve existing."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_good_metrics(),
            agent_details=_none_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.agent_details.id == "0xabc123"
        assert saved.agent_details.created_at == "2025-01-01T00:00:00Z"
        assert saved.agent_details.last_active_at == "2025-06-15T12:00:00Z"

    def test_save_preserves_agent_performance_on_failure(self) -> None:
        """When new agent_performance has all-None key fields, preserve existing."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_good_metrics(),
            agent_details=_good_agent_details(),
            agent_performance=_none_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.agent_performance.metrics.all_time_funds_used == 100.0
        assert saved.agent_performance.metrics.all_time_profit == 12.5
        assert saved.agent_performance.metrics.roi == 0.125

    def test_save_preserves_profit_over_time_on_none(self) -> None:
        """When new profit_over_time is None, preserve existing."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_good_metrics(),
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=None,
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.profit_over_time is not None
        assert saved.profit_over_time.total_days == 30
        assert len(saved.profit_over_time.data_points) == 1

    def test_save_preserves_prediction_history_on_empty(self) -> None:
        """When new prediction_history has 0 predictions/empty items, preserve existing."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_good_metrics(),
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_empty_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.prediction_history.total_predictions == 50
        assert saved.prediction_history.stored_count == 25
        assert len(saved.prediction_history.items) == 1

    def test_save_preserves_agent_behavior(self) -> None:
        """agent_behavior from existing data is always preserved."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_good_metrics(),
            agent_behavior="should_be_overridden",
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.agent_behavior == "some_behavior"

    def test_save_partial_failure_preserves_failed_sections_only(self) -> None:
        """Mixed case: some sections succeed, others fail (preserve existing)."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        # Metrics fail (NA), agent_details succeed (new values),
        # agent_performance fails (None keys), profit_over_time succeeds,
        # prediction_history fails (empty)
        new_profit = ProfitOverTimeData(
            last_updated=1700002000,
            total_days=35,
            data_points=[
                ProfitDataPoint(
                    date="2025-06-05",
                    timestamp=1700002000,
                    daily_profit=2.0,
                    cumulative_profit=15.0,
                )
            ],
        )
        new_details = AgentDetails(
            id="0xnew999",
            created_at="2025-03-01T00:00:00Z",
            last_active_at="2025-07-01T12:00:00Z",
        )

        new_summary = AgentPerformanceSummary(
            timestamp=1700002000,
            metrics=_na_metrics(),
            agent_details=new_details,
            agent_performance=_none_agent_performance(),
            prediction_history=_empty_prediction_history(),
            profit_over_time=new_profit,
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        # Metrics: preserved from existing (NA -> keep old)
        assert saved.metrics[0].value == "12.5%"
        assert saved.metrics[1].value == "75%"

        # Agent details: updated (new had real values)
        assert saved.agent_details.id == "0xnew999"

        # Agent performance: preserved from existing (None key fields)
        assert saved.agent_performance.metrics.roi == 0.125

        # Profit over time: updated (new had real data)
        assert saved.profit_over_time.total_days == 35

        # Prediction history: preserved from existing (empty -> keep old)
        assert saved.prediction_history.total_predictions == 50

        # Behavior always preserved
        assert saved.agent_behavior == "some_behavior"

    def test_save_preserves_timestamp_on_failure(self) -> None:
        """When data is preserved (failure), saved timestamp should be existing."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_na_metrics(),  # failure -> preserved
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        # Timestamp should be the existing one since data was preserved
        assert saved.timestamp == 1700000000

    def test_post_init_converts_metric_dicts_to_dataclasses(self) -> None:
        """Construct AgentPerformanceSummary with metrics as raw dicts.

        Assert they become AgentPerformanceMetrics instances.
        """
        raw_metrics = [
            {"name": "Total ROI", "is_primary": True, "value": "12.5%"},
            {"name": "Prediction accuracy", "is_primary": False, "value": "75%"},
        ]
        summary = AgentPerformanceSummary(
            metrics=raw_metrics,  # type: ignore[arg-type]
        )
        assert all(isinstance(m, AgentPerformanceMetrics) for m in summary.metrics)
        assert summary.metrics[0].name == "Total ROI"
        assert summary.metrics[0].value == "12.5%"
        assert summary.metrics[1].name == "Prediction accuracy"
        assert summary.metrics[1].value == "75%"

    def test_save_preserves_metrics_when_existing_loaded_from_json(self) -> None:
        """Preserve existing values when existing summary has metrics as raw dicts.

        Simulates JSON load where _save_agent_performance_summary with NA
        metrics should preserve existing values.
        """
        # Simulate what read_existing_performance_summary returns from JSON:
        # metrics are raw dicts, not AgentPerformanceMetrics instances
        existing = AgentPerformanceSummary(
            timestamp=1700000000,
            metrics=[
                {"name": "Total ROI", "is_primary": True, "value": "12.5%"},  # type: ignore[list-item]
                {"name": "Prediction accuracy", "is_primary": False, "value": "75%"},  # type: ignore[list-item]
                {  # type: ignore[list-item]
                    "name": "Total staking rewards",
                    "is_primary": False,
                    "value": "3.2 OLAS",
                },
            ],
            agent_behavior="some_behavior",
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_na_metrics(),
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.metrics[0].value == "12.5%"
        assert saved.metrics[1].value == "75%"
        assert saved.metrics[2].value == "3.2 OLAS"

    def test_save_uses_new_timestamp_on_full_success(self) -> None:
        """When all data is valid, the new timestamp should be used."""
        existing = _good_existing_summary()
        behaviour = _make_behaviour(existing)

        new_summary = AgentPerformanceSummary(
            timestamp=1700001000,
            metrics=_good_metrics(),
            agent_details=_good_agent_details(),
            agent_performance=_good_agent_performance(),
            prediction_history=_good_prediction_history(),
            profit_over_time=_good_profit_over_time(),
        )

        behaviour._save_agent_performance_summary(new_summary)

        saved = behaviour.shared_state.overwrite_performance_summary.call_args[0][0]
        assert saved.timestamp == 1700001000
