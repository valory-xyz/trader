#!/usr/bin/env python3
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

"""Helper for fetching and formatting predictions data."""

from abc import ABC, abstractmethod
from typing import Any


class PredictionsFetcher(ABC):
    """Abstract base class for fetching and formatting predictions."""

    def __init__(self, context: Any, logger: Any) -> None:
        """
        Initialize the predictions fetcher.

        :param context: The behaviour/handler context
        :param logger: Logger instance
        """
        self.context = context
        self.logger = logger

    @abstractmethod
    def fetch_predictions(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch and format predictions with pagination support."""

    @abstractmethod
    def _fetch_trader_agent_bets(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch trader agent bets from subgraph."""

    @abstractmethod
    def fetch_mech_tool_for_question(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch the prediction tool used for a specific question from the mech subgraph."""

    @abstractmethod
    def _fetch_prediction_response_from_mech(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch prediction response (p_yes, p_no, etc.) from mech subgraph."""

    @abstractmethod
    def fetch_position_details(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch complete position details for a specific market."""

    @abstractmethod
    def _load_multi_bets_data(self, *args: Any, **kwargs: Any) -> Any:
        """Load data from multi_bets.json file."""

    @abstractmethod
    def _load_agent_performance_data(self, *args: Any, **kwargs: Any) -> Any:
        """Load data from agent_performance.json file."""

    @abstractmethod
    def _find_market_entry(self, *args: Any, **kwargs: Any) -> Any:
        """Find market information in multi_bets data by market ID."""

    @abstractmethod
    def _find_bet(self, *args: Any, **kwargs: Any) -> Any:
        """Find bet for a specific bet ID in agent performance data."""

    @abstractmethod
    def _format_bet_for_position(self, *args: Any, **kwargs: Any) -> Any:
        """Format bets into the required API format for position details."""

    @abstractmethod
    def _fetch_bet_from_subgraph(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch bet for a specific market from the subgraph."""

    @abstractmethod
    def _format_predictions(self, *args: Any, **kwargs: Any) -> Any:
        """Format raw bets into prediction objects with proportional payout distribution."""

    @abstractmethod
    def _build_market_context(self, *args: Any, **kwargs: Any) -> Any:
        """Precompute per-market aggregates needed to distribute payouts per bet."""

    @abstractmethod
    def _format_single_bet(self, *args: Any, **kwargs: Any) -> Any:
        """Format a single bet into the public prediction object."""

    @abstractmethod
    def _calculate_bet_net_profit(self, *args: Any, **kwargs: Any) -> Any:
        """Calculate net profit and actual payout for a single bet using market-level payout data."""

    @abstractmethod
    def _get_prediction_status(self, *args: Any, **kwargs: Any) -> Any:
        """Determine the status of a prediction (pending, won, lost), treating unredeemed wins as pending."""

    @abstractmethod
    def _get_prediction_side(self, *args: Any, **kwargs: Any) -> Any:
        """Get the prediction side from outcome index and outcomes array."""

    @abstractmethod
    def _format_timestamp(self, *args: Any, **kwargs: Any) -> Any:
        """Format Unix timestamp to ISO 8601."""

    @abstractmethod
    def _get_ui_trading_strategy(self, *args: Any, **kwargs: Any) -> Any:
        """Get the UI trading strategy."""
