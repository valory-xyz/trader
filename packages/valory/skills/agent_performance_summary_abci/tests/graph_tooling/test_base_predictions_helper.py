# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains tests for the PredictionsFetcher abstract base class."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.base_predictions_helper import (
    PredictionsFetcher,
)


class ConcretePredictionsFetcher(PredictionsFetcher):
    """Concrete implementation of PredictionsFetcher for testing."""

    def fetch_predictions(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch and format predictions with pagination support."""
        return None

    def _fetch_trader_agent_bets(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch trader agent bets from subgraph."""
        return None

    def fetch_mech_tool_for_question(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch the prediction tool used for a specific question from the mech subgraph."""
        return None

    def _fetch_prediction_response_from_mech(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch prediction response from mech subgraph."""
        return None

    def fetch_position_details(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch complete position details for a specific market."""
        return None

    def _load_multi_bets_data(self, *args: Any, **kwargs: Any) -> Any:
        """Load data from multi_bets.json file."""
        return None

    def _load_agent_performance_data(self, *args: Any, **kwargs: Any) -> Any:
        """Load data from agent_performance.json file."""
        return None

    def _find_market_entry(self, *args: Any, **kwargs: Any) -> Any:
        """Find market information in multi_bets data by market ID."""
        return None

    def _find_bet(self, *args: Any, **kwargs: Any) -> Any:
        """Find bet for a specific bet ID in agent performance data."""
        return None

    def _format_bet_for_position(self, *args: Any, **kwargs: Any) -> Any:
        """Format bets into the required API format for position details."""
        return None

    def _fetch_bet_from_subgraph(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch bet for a specific market from the subgraph."""
        return None

    def _format_predictions(self, *args: Any, **kwargs: Any) -> Any:
        """Format raw bets into prediction objects."""
        return None

    def _build_market_context(self, *args: Any, **kwargs: Any) -> Any:
        """Precompute per-market aggregates."""
        return None

    def _format_single_bet(self, *args: Any, **kwargs: Any) -> Any:
        """Format a single bet into the public prediction object."""
        return None

    def _calculate_bet_net_profit(self, *args: Any, **kwargs: Any) -> Any:
        """Calculate net profit and actual payout for a single bet."""
        return None

    def _get_prediction_status(self, *args: Any, **kwargs: Any) -> Any:
        """Determine the status of a prediction."""
        return None

    def _get_prediction_side(self, *args: Any, **kwargs: Any) -> Any:
        """Get the prediction side from outcome index and outcomes array."""
        return None

    def _format_timestamp(self, *args: Any, **kwargs: Any) -> Any:
        """Format Unix timestamp to ISO 8601."""
        return None

    def _get_ui_trading_strategy(self, *args: Any, **kwargs: Any) -> Any:
        """Get the UI trading strategy."""
        return None


class TestPredictionsFetcherABC:
    """Tests for PredictionsFetcher abstract base class."""

    def test_cannot_instantiate_directly(self) -> None:
        """Test that PredictionsFetcher cannot be instantiated directly."""
        with pytest.raises(TypeError):
            PredictionsFetcher(context=MagicMock(), logger=MagicMock())  # type: ignore

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        """Test that a concrete subclass can be instantiated."""
        context = MagicMock()
        logger = MagicMock()
        fetcher = ConcretePredictionsFetcher(context=context, logger=logger)
        assert isinstance(fetcher, PredictionsFetcher)
        assert isinstance(fetcher, ConcretePredictionsFetcher)

    def test_init_sets_context(self) -> None:
        """Test that __init__ sets the context attribute."""
        context = MagicMock()
        logger = MagicMock()
        fetcher = ConcretePredictionsFetcher(context=context, logger=logger)
        assert fetcher.context is context

    def test_init_sets_logger(self) -> None:
        """Test that __init__ sets the logger attribute."""
        context = MagicMock()
        logger = MagicMock()
        fetcher = ConcretePredictionsFetcher(context=context, logger=logger)
        assert fetcher.logger is logger

    def test_abstract_methods_exist(self) -> None:
        """Test that all abstract methods are defined on the base class."""
        abstract_methods = PredictionsFetcher.__abstractmethods__
        expected_methods = {
            "fetch_predictions",
            "_fetch_trader_agent_bets",
            "fetch_mech_tool_for_question",
            "_fetch_prediction_response_from_mech",
            "fetch_position_details",
            "_load_multi_bets_data",
            "_load_agent_performance_data",
            "_find_market_entry",
            "_find_bet",
            "_format_bet_for_position",
            "_fetch_bet_from_subgraph",
            "_format_predictions",
            "_build_market_context",
            "_format_single_bet",
            "_calculate_bet_net_profit",
            "_get_prediction_status",
            "_get_prediction_side",
            "_format_timestamp",
            "_get_ui_trading_strategy",
        }
        assert abstract_methods == expected_methods

    def test_abstract_method_count(self) -> None:
        """Test that there are exactly 19 abstract methods."""
        assert len(PredictionsFetcher.__abstractmethods__) == 19
