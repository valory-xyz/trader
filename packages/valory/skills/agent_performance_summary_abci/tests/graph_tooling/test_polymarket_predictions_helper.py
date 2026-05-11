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

"""Tests for the graph_tooling.polymarket_predictions_helper module."""

import json
import os
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import (
    GAMMA_API_BASE_URL,
    GRAPHQL_BATCH_SIZE,
    ISO_TIMESTAMP_FORMAT,
    POLYMARKET_MARKET_BASE_URL,
    PolymarketPredictionsFetcher,
    USDC_DECIMALS_DIVISOR,
)

# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_usdc_decimals_divisor(self) -> None:
        """Test USDC_DECIMALS_DIVISOR constant."""
        assert USDC_DECIMALS_DIVISOR == 10**6

    def test_polymarket_market_base_url(self) -> None:
        """Test POLYMARKET_MARKET_BASE_URL constant."""
        assert POLYMARKET_MARKET_BASE_URL == "https://polymarket.com/market"

    def test_gamma_api_base_url(self) -> None:
        """Test GAMMA_API_BASE_URL constant."""
        assert GAMMA_API_BASE_URL == "https://gamma-api.polymarket.com"

    def test_graphql_batch_size(self) -> None:
        """Test GRAPHQL_BATCH_SIZE constant."""
        assert GRAPHQL_BATCH_SIZE == 1000

    def test_iso_timestamp_format(self) -> None:
        """Test ISO_TIMESTAMP_FORMAT constant."""
        assert ISO_TIMESTAMP_FORMAT == "%Y-%m-%dT%H:%M:%SZ"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fetcher() -> PolymarketPredictionsFetcher:  # type: ignore[no-untyped-def]
    """Create a PolymarketPredictionsFetcher instance with mocked context and logger."""
    context = MagicMock()
    context.polymarket_agents_subgraph.url = "https://subgraph.test/polymarket"
    context.polygon_mech_subgraph.url = "https://subgraph.test/polygon_mech"
    logger = MagicMock()
    fetcher = PolymarketPredictionsFetcher(context, logger)
    return fetcher


def _make_polymarket_bet(  # type: ignore[no-untyped-def]
    bet_id: str = "bet_1",
    amount: str = str(1 * USDC_DECIMALS_DIVISOR),  # noqa: B008
    shares: str = "0",
    outcome_index: int = 0,
    block_timestamp: int = 1700000000,
    question_id: str = "q_1",
    condition_id: str = "c_1",
    title: str = "Will it rain?",
    outcomes: Optional[List[str]] = None,
    resolution: Optional[str] = None,
    total_payout: int = 0,
    transaction_hash: str = "0xtxhash",
) -> Dict[str, Any]:
    """Create a mock Polymarket bet dict for testing."""
    if outcomes is None:
        outcomes = ["Yes", "No"]

    bet = {
        "id": bet_id,
        "amount": amount,
        "shares": shares,
        "outcomeIndex": outcome_index,
        "blockTimestamp": block_timestamp,
        "transactionHash": transaction_hash,
        "totalPayout": total_payout,
        "question": {
            "id": condition_id,
            "questionId": question_id,
            "metadata": {
                "title": title,
                "outcomes": outcomes,
            },
            "resolution": resolution,
        },
    }
    return bet


# ---------------------------------------------------------------------------
# PolymarketPredictionsFetcher.__init__ tests
# ---------------------------------------------------------------------------


class TestPolymarketPredictionsFetcherInit:
    """Tests for PolymarketPredictionsFetcher initialization."""

    def test_init(self) -> None:
        """Test that init sets context and logger."""
        fetcher = _make_fetcher()
        assert fetcher.agents_url == "https://subgraph.test/polymarket"
        assert fetcher.mech_url == "https://subgraph.test/polygon_mech"


# ---------------------------------------------------------------------------
# fetch_predictions tests
# ---------------------------------------------------------------------------


class TestFetchPredictions:
    """Tests for fetch_predictions."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of predictions."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(2 * USDC_DECIMALS_DIVISOR),
                        "bets": [
                            _make_polymarket_bet(
                                resolution={  # type: ignore[arg-type]
                                    "blockTimestamp": 1700001000,
                                    "winningIndex": 0,
                                },
                                total_payout=str(2 * USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
                            )
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result["total_predictions"] == 1
        assert len(result["items"]) == 1

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_market_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when no market participants found."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": []}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result == {"total_predictions": 0, "items": []}

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_market_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when market participants is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": None}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result == {"total_predictions": 0, "items": []}

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_bets_in_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when participants have no bets."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"marketParticipants": [{"totalPayout": "0", "bets": []}]}
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result == {"total_predictions": 0, "items": []}

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_with_status_filter(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test filtering predictions by status."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "bets": [
                            _make_polymarket_bet(resolution=None),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        # Filter for "won" should exclude pending bets
        result = fetcher.fetch_predictions("0xsafe", first=10, status_filter="won")

        assert result["total_predictions"] == 1
        assert result["items"] == []

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_multiple_participants_bets_combined(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that bets from multiple participants are combined."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "bets": [_make_polymarket_bet(bet_id="b1")],
                    },
                    {
                        "totalPayout": str(USDC_DECIMALS_DIVISOR),
                        "bets": [_make_polymarket_bet(bet_id="b2")],
                    },
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result["total_predictions"] == 2


# ---------------------------------------------------------------------------
# _fetch_market_participants tests
# ---------------------------------------------------------------------------


class TestFetchMarketParticipants:
    """Tests for _fetch_market_participants."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 HTTP response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher._fetch_market_participants("0xsafe", 10, 0)

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Connection error")

        result = fetcher._fetch_market_participants("0xsafe", 10, 0)

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_successful_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"marketParticipants": [{"id": "p1"}]}
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_market_participants("0xsafe", 10, 0)

        assert result == [{"id": "p1"}]


# ---------------------------------------------------------------------------
# _format_predictions tests
# ---------------------------------------------------------------------------


class TestFormatPredictions:
    """Tests for _format_predictions."""

    def test_basic_formatting(self) -> None:
        """Test basic formatting of bets into predictions."""
        fetcher = _make_fetcher()
        bets = [_make_polymarket_bet()]

        result = fetcher._format_predictions(bets, "0xsafe")

        assert len(result) == 1
        assert result[0]["id"] == "bet_1"

    def test_status_filter_excludes(self) -> None:
        """Test status filter excludes non-matching bets."""
        fetcher = _make_fetcher()
        bets = [_make_polymarket_bet(resolution=None)]

        result = fetcher._format_predictions(bets, "0xsafe", status_filter="won")

        assert result == []

    def test_status_filter_includes(self) -> None:
        """Test status filter includes matching bets."""
        fetcher = _make_fetcher()
        bets = [_make_polymarket_bet(resolution=None)]

        result = fetcher._format_predictions(bets, "0xsafe", status_filter="pending")

        assert len(result) == 1


# ---------------------------------------------------------------------------
# _format_single_bet tests
# ---------------------------------------------------------------------------


class TestFormatSingleBet:
    """Tests for _format_single_bet."""

    def test_basic_formatting(self) -> None:
        """Test basic bet formatting."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet()

        result = fetcher._format_single_bet(bet, "0xsafe", None)

        assert result is not None
        assert result["id"] == "bet_1"
        assert result["market"]["id"] == "q_1"
        assert result["market"]["condition_id"] == "c_1"
        assert result["bet_amount"] == 1.0
        assert result["transaction_hash"] == "0xtxhash"

    def test_with_resolution(self) -> None:
        """Test formatting with resolution data."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"blockTimestamp": 1700001000, "winningIndex": 0},  # type: ignore[arg-type]
            total_payout=str(2 * USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
        )

        result = fetcher._format_single_bet(bet, "0xsafe", None)

        assert result is not None
        assert result["status"] == "won"
        assert result["settled_at"] is not None

    def test_status_filter_match(self) -> None:
        """Test status filter matches."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(resolution=None)

        result = fetcher._format_single_bet(bet, "0xsafe", "pending")

        assert result is not None

    def test_status_filter_no_match(self) -> None:
        """Test status filter does not match."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(resolution=None)

        result = fetcher._format_single_bet(bet, "0xsafe", "won")

        assert result is None

    def test_no_question(self) -> None:
        """Test bet with no question."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b1",
            "amount": str(USDC_DECIMALS_DIVISOR),
            "outcomeIndex": 0,
            "question": None,
            "totalPayout": 0,
        }

        result = fetcher._format_single_bet(bet, "0xsafe", None)

        assert result is not None
        assert result["market"]["title"] == ""

    def test_no_resolution_timestamp(self) -> None:
        """Test that settled_at is None when resolution has no timestamp."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 0, "blockTimestamp": None},  # type: ignore[arg-type]
            total_payout=str(2 * USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
        )

        result = fetcher._format_single_bet(bet, "0xsafe", None)

        assert result is not None
        assert result["settled_at"] is None

    def test_no_block_timestamp(self) -> None:
        """Test bet with no blockTimestamp."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(block_timestamp=None)  # type: ignore[arg-type]

        result = fetcher._format_single_bet(bet, "0xsafe", None)

        assert result is not None
        assert result["created_at"] is None


# ---------------------------------------------------------------------------
# _calculate_bet_profit tests
# ---------------------------------------------------------------------------


class TestCalculateBetProfit:
    """Tests for _calculate_bet_profit."""

    def test_pending_no_resolution(self) -> None:
        """Test pending bet (no resolution)."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(resolution=None)

        result = fetcher._calculate_bet_profit(bet)

        assert result == 0.0

    def test_winning_bet_redeemed(self) -> None:
        """Test winning bet that has been redeemed."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 0, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
            amount=str(USDC_DECIMALS_DIVISOR),
            shares=str(2 * USDC_DECIMALS_DIVISOR),
            total_payout=str(2 * USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
        )

        result = fetcher._calculate_bet_profit(bet)

        # profit = shares(2.0) - amount(1.0) = 1.0
        assert result == 1.0

    def test_winning_bet_not_redeemed(self) -> None:
        """Test winning bet not yet redeemed."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 0, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
            total_payout=0,
        )

        result = fetcher._calculate_bet_profit(bet)

        assert result == 0.0

    def test_losing_bet(self) -> None:
        """Test losing bet."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 1, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
            amount=str(USDC_DECIMALS_DIVISOR),
        )

        result = fetcher._calculate_bet_profit(bet)

        assert result == -1.0

    def test_invalid_market_negative_winning_index(self) -> None:
        """Test invalid market (negative winningIndex)."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": -1, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            total_payout=str(int(0.5 * USDC_DECIMALS_DIVISOR)),  # type: ignore[arg-type]
        )

        result = fetcher._calculate_bet_profit(bet)

        # net_profit = 0.5 - 1.0 = -0.5
        assert result == -0.5

    def test_fallback_with_payout(self) -> None:
        """Test fallback logic when outcomeIndex is None but shares > 0."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": None, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            shares=str(2 * USDC_DECIMALS_DIVISOR),
            total_payout=str(2 * USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
        )
        bet["outcomeIndex"] = None

        result = fetcher._calculate_bet_profit(bet)

        # Fallback: shares > 0 -> profit = shares(2.0) - amount(1.0) = 1.0
        assert result == 1.0

    def test_fallback_without_payout(self) -> None:
        """Test fallback logic when outcomeIndex is None and no payout."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": None, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            total_payout=0,
        )
        bet["outcomeIndex"] = None

        result = fetcher._calculate_bet_profit(bet)

        # Fallback: total_payout == 0 -> treated as loss
        assert result == -1.0

    def test_no_question(self) -> None:
        """Test when question is None."""
        fetcher = _make_fetcher()
        bet = {
            "amount": str(USDC_DECIMALS_DIVISOR),
            "question": None,
            "totalPayout": 0,
            "outcomeIndex": 0,
        }

        result = fetcher._calculate_bet_profit(bet)

        # No resolution -> pending
        assert result == 0.0

    def test_winning_index_none_outcome_index_present(self) -> None:
        """Test when winningIndex is None but outcomeIndex is present."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": None, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
            total_payout=0,
        )

        result = fetcher._calculate_bet_profit(bet)

        # Fallback: total_payout == 0 -> treated as loss
        assert result == -1.0


# ---------------------------------------------------------------------------
# _get_prediction_status tests
# ---------------------------------------------------------------------------


class TestGetPredictionStatus:
    """Tests for _get_prediction_status."""

    def test_pending_no_resolution(self) -> None:
        """Test pending when no resolution."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(resolution=None)

        result = fetcher._get_prediction_status(bet)

        assert result == "pending"

    def test_invalid_negative_winning_index(self) -> None:
        """Test invalid when winningIndex is negative."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": -1, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
        )

        result = fetcher._get_prediction_status(bet)

        assert result == "invalid"

    def test_won_redeemed(self) -> None:
        """Test won when bet matches winningIndex and payout > 0."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 0, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
            total_payout=str(2 * USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
        )

        result = fetcher._get_prediction_status(bet)

        assert result == "won"

    def test_won_not_redeemed_treated_as_pending(self) -> None:
        """Test won but not redeemed treated as pending."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 0, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
            total_payout=0,
        )

        result = fetcher._get_prediction_status(bet)

        assert result == "pending"

    def test_lost(self) -> None:
        """Test lost when outcomeIndex != winningIndex."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": 1, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            outcome_index=0,
        )

        result = fetcher._get_prediction_status(bet)

        assert result == "lost"

    def test_fallback_with_payout(self) -> None:
        """Test fallback when indices are missing but payout > 0."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": None, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            total_payout=str(USDC_DECIMALS_DIVISOR),  # type: ignore[arg-type]
        )
        bet["outcomeIndex"] = None

        result = fetcher._get_prediction_status(bet)

        assert result == "won"

    def test_fallback_without_payout(self) -> None:
        """Test fallback when indices are missing and payout == 0."""
        fetcher = _make_fetcher()
        bet = _make_polymarket_bet(
            resolution={"winningIndex": None, "blockTimestamp": 1700001000},  # type: ignore[arg-type]
            total_payout=0,
        )
        bet["outcomeIndex"] = None

        result = fetcher._get_prediction_status(bet)

        assert result == "lost"

    def test_no_question(self) -> None:
        """Test when question is None."""
        fetcher = _make_fetcher()
        bet = {"question": None, "outcomeIndex": 0, "totalPayout": 0}

        result = fetcher._get_prediction_status(bet)

        assert result == "pending"


# ---------------------------------------------------------------------------
# _get_prediction_side tests
# ---------------------------------------------------------------------------


class TestGetPredictionSide:
    """Tests for _get_prediction_side."""

    def test_yes_side(self) -> None:
        """Test outcome index 0 returns yes."""
        fetcher = _make_fetcher()

        result = fetcher._get_prediction_side(0, ["Yes", "No"])

        assert result == "yes"

    def test_no_side(self) -> None:
        """Test outcome index 1 returns no."""
        fetcher = _make_fetcher()

        result = fetcher._get_prediction_side(1, ["Yes", "No"])

        assert result == "no"

    def test_index_out_of_range(self) -> None:
        """Test index out of range returns unknown."""
        fetcher = _make_fetcher()

        # hardcoded outcomes ["Yes", "No"] in the method
        result = fetcher._get_prediction_side(5, ["Yes", "No"])

        assert result == "unknown"

    def test_empty_outcomes_ignored(self) -> None:
        """Test that empty input outcomes are ignored (hardcoded list used)."""
        fetcher = _make_fetcher()

        # The method hardcodes outcomes = ["Yes", "No"], so empty input is overridden
        result = fetcher._get_prediction_side(0, [])

        assert result == "yes"


# ---------------------------------------------------------------------------
# _format_timestamp tests
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    """Tests for _format_timestamp."""

    def test_valid_timestamp(self) -> None:
        """Test formatting a valid Unix timestamp."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp("1700000000")

        assert result is not None
        assert "T" in result
        assert result.endswith("Z")

    def test_none_timestamp(self) -> None:
        """Test None timestamp."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp(None)

        assert result is None

    def test_empty_timestamp(self) -> None:
        """Test empty string timestamp."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp("")

        assert result is None

    def test_invalid_timestamp(self) -> None:
        """Test invalid timestamp string."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp("not-a-number")

        assert result is None


# ---------------------------------------------------------------------------
# fetch_mech_tool_for_question tests
# ---------------------------------------------------------------------------


class TestFetchMechToolForQuestion:
    """Tests for fetch_mech_tool_for_question."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of mech tool."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "sender": {
                    "requests": [{"parsedRequest": {"tool": "poly-prediction-tool"}}]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Will it rain?", "0xsender")

        assert result == "poly-prediction-tool"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 HTTP response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_empty_requests_list(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": {"requests": []}}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_parsed_request(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when parsedRequest is missing."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"sender": {"requests": [{"parsedRequest": None}]}}
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Network error")

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_sender_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when sender data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": None}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_requests_list(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": {"requests": None}}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_first_request(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when first request is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": {"requests": [None]}}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_bet_timestamp_passed_in_query(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that blockTimestamp_lte is passed in query variables."""
        fetcher = _make_fetcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "sender": {
                    "requests": [{"parsedRequest": {"tool": "prediction-online"}}]
                }
            }
        }
        mock_post.return_value = mock_response

        fetcher.fetch_mech_tool_for_question("Q?", "0xsender", bet_timestamp=1700000000)

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["variables"]["blockTimestamp_lte"] == "1700000000"


# ---------------------------------------------------------------------------
# _fetch_prediction_response_from_mech tests
# ---------------------------------------------------------------------------


class TestFetchPredictionResponseFromMech:
    """Tests for _fetch_prediction_response_from_mech."""

    def test_empty_question_title(self) -> None:
        """Test that empty question title returns None."""
        fetcher = _make_fetcher()

        result = fetcher._fetch_prediction_response_from_mech("", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of prediction response."""
        fetcher = _make_fetcher()

        prediction_data = {"p_yes": 0.8, "p_no": 0.2, "confidence": 0.9}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "requests": [
                    {"deliveries": [{"toolResponse": json.dumps(prediction_data)}]}
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result == prediction_data

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_empty_requests(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": []}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_empty_deliveries(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when deliveries is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": [{"deliveries": []}]}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_tool_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when toolResponse is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"requests": [{"deliveries": [{"toolResponse": None}]}]}
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_invalid_json_in_tool_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when toolResponse has invalid JSON."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"requests": [{"deliveries": [{"toolResponse": "not-valid-json"}]}]}
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Network error")

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_requests_list(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": None}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_deliveries(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when deliveries is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": [{"deliveries": None}]}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_bet_timestamp_passed_in_query(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that blockTimestamp_lte is passed in query variables."""
        fetcher = _make_fetcher()
        prediction_data = {"p_yes": 0.7, "p_no": 0.3, "confidence": 0.8}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "requests": [
                    {"deliveries": [{"toolResponse": json.dumps(prediction_data)}]}
                ]
            }
        }
        mock_post.return_value = mock_response

        fetcher._fetch_prediction_response_from_mech(
            "Q?", "0xsender", bet_timestamp=1700000000
        )

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["variables"]["blockTimestamp_lte"] == "1700000000"


# ---------------------------------------------------------------------------
# _load_multi_bets_data tests
# ---------------------------------------------------------------------------


class TestLoadMultiBetsData:
    """Tests for _load_multi_bets_data."""

    def test_successful_load(self) -> None:
        """Test successful loading of multi_bets.json."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            data = [{"id": "m1"}, {"id": "m2"}]
            filepath = os.path.join(tmpdir, "multi_bets.json")
            with open(filepath, "w") as f:
                json.dump(data, f)

            result = fetcher._load_multi_bets_data(tmpdir)

            assert result == data

    def test_file_not_found(self) -> None:
        """Test handling of missing file."""
        fetcher = _make_fetcher()

        result = fetcher._load_multi_bets_data("/nonexistent/path")

        assert result == []


# ---------------------------------------------------------------------------
# _load_agent_performance_data tests
# ---------------------------------------------------------------------------


class TestLoadAgentPerformanceData:
    """Tests for _load_agent_performance_data."""

    def test_successful_load(self) -> None:
        """Test successful loading of agent_performance.json."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"prediction_history": {"items": []}}  # type: ignore[var-annotated]
            filepath = os.path.join(tmpdir, "agent_performance.json")
            with open(filepath, "w") as f:
                json.dump(data, f)

            result = fetcher._load_agent_performance_data(tmpdir)

            assert result == data

    def test_file_not_found(self) -> None:
        """Test handling of missing file."""
        fetcher = _make_fetcher()

        result = fetcher._load_agent_performance_data("/nonexistent/path")

        assert result == {}


# ---------------------------------------------------------------------------
# _find_market_entry tests
# ---------------------------------------------------------------------------


class TestFindMarketEntry:
    """Tests for _find_market_entry."""

    def test_found_by_condition_id(self) -> None:
        """Test finding a market by condition_id."""
        fetcher = _make_fetcher()
        multi_bets = [
            {"id": "m1", "condition_id": "c1"},
            {"id": "m2", "condition_id": "c2"},
        ]

        result = fetcher._find_market_entry(multi_bets, "m1", "c1")

        assert result == {"id": "m1", "condition_id": "c1"}

    def test_found_by_market_id(self) -> None:
        """Test finding a market by id."""
        fetcher = _make_fetcher()
        multi_bets = [{"id": "m1"}, {"id": "m2"}]

        result = fetcher._find_market_entry(multi_bets, "m2")

        assert result == {"id": "m2"}

    def test_found_by_market_field(self) -> None:
        """Test finding a market by market field."""
        fetcher = _make_fetcher()
        multi_bets = [{"id": "other", "market": "m1"}]

        result = fetcher._find_market_entry(multi_bets, "m1")

        assert result == {"id": "other", "market": "m1"}

    def test_not_found(self) -> None:
        """Test when market is not found."""
        fetcher = _make_fetcher()
        multi_bets = [{"id": "m1"}]

        result = fetcher._find_market_entry(multi_bets, "m99")

        assert result is None

    def test_empty_list(self) -> None:
        """Test with empty multi_bets list."""
        fetcher = _make_fetcher()

        result = fetcher._find_market_entry([], "m1")

        assert result is None

    def test_condition_id_takes_priority(self) -> None:
        """Test that condition_id matching takes priority."""
        fetcher = _make_fetcher()
        multi_bets = [
            {"id": "other_id", "condition_id": "c1"},
            {"id": "m1"},
        ]

        result = fetcher._find_market_entry(multi_bets, "m1", "c1")

        assert result == {"id": "other_id", "condition_id": "c1"}

    def test_empty_market_id_and_condition_id(self) -> None:
        """Test with empty market_id and condition_id."""
        fetcher = _make_fetcher()
        multi_bets = [{"id": "m1"}]

        result = fetcher._find_market_entry(multi_bets, "", "")

        assert result is None


# ---------------------------------------------------------------------------
# _find_bet tests
# ---------------------------------------------------------------------------


class TestFindBet:
    """Tests for _find_bet."""

    def test_found(self) -> None:
        """Test finding a bet by ID."""
        fetcher = _make_fetcher()
        data = {
            "prediction_history": {
                "items": [
                    {"id": "b1", "status": "won"},
                    {"id": "b2", "status": "lost"},
                ]
            }
        }

        result = fetcher._find_bet(data, "b1")

        assert result == {"id": "b1", "status": "won"}

    def test_not_found(self) -> None:
        """Test when bet is not found."""
        fetcher = _make_fetcher()
        data = {"prediction_history": {"items": [{"id": "b1"}]}}

        result = fetcher._find_bet(data, "b99")

        assert result is None

    def test_empty_data(self) -> None:
        """Test with empty data."""
        fetcher = _make_fetcher()

        result = fetcher._find_bet({}, "b1")

        assert result is None


# ---------------------------------------------------------------------------
# _fetch_bet_from_subgraph tests
# ---------------------------------------------------------------------------


class TestFetchBetFromSubgraph:
    """Tests for _fetch_bet_from_subgraph."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of bet from subgraph."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(2 * USDC_DECIMALS_DIVISOR),
                        "bets": [
                            _make_polymarket_bet(
                                bet_id="bet_1",
                                resolution={  # type: ignore[arg-type]
                                    "winningIndex": 0,
                                    "blockTimestamp": 1700001000,
                                },
                            ),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        assert result["id"] == "bet_1"
        assert result["market"]["id"] == "q_1"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_market_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when no market participants."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": []}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_bet_not_found(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when bet ID not found in any participant."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "bets": [_make_polymarket_bet(bet_id="other_bet")],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("nonexistent_bet", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Network error")

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_null_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_resolution_net_profit_zero(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that no resolution results in net_profit = 0."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "bets": [_make_polymarket_bet(bet_id="bet_1", resolution=None)],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        assert result["net_profit"] == 0.0
        assert result["settled_at"] is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_invalid_market_negative_winning_index(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test invalid market with negative winningIndex."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(int(0.5 * USDC_DECIMALS_DIVISOR)),
                        "totalTraded": str(USDC_DECIMALS_DIVISOR),
                        "bets": [
                            _make_polymarket_bet(
                                bet_id="bet_1",
                                resolution={  # type: ignore[arg-type]
                                    "winningIndex": -1,
                                    "blockTimestamp": 1700001000,
                                },
                            ),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        # pro-rated: bet_payout = 0.5 * (1.0 / 1.0) = 0.5, net = 0.5 - 1.0 = -0.5
        assert result["net_profit"] == -0.5

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_winning_bet_outcome_matches(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test winning bet where outcomeIndex matches winningIndex."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(2 * USDC_DECIMALS_DIVISOR),
                        "bets": [
                            _make_polymarket_bet(
                                bet_id="bet_1",
                                outcome_index=0,
                                shares=str(2 * USDC_DECIMALS_DIVISOR),
                                resolution={  # type: ignore[arg-type]
                                    "winningIndex": "0",
                                    "blockTimestamp": 1700001000,
                                },
                            ),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        # net_profit = shares(2.0) - amount(1.0) = 1.0
        assert result["net_profit"] == 1.0

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_losing_bet_net_profit(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test losing bet net_profit calculation."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "bets": [
                            _make_polymarket_bet(
                                bet_id="bet_1",
                                outcome_index=0,
                                resolution={  # type: ignore[arg-type]
                                    "winningIndex": 1,
                                    "blockTimestamp": 1700001000,
                                },
                            ),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_settled_at_from_resolution(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that settled_at is set from resolution blockTimestamp."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(2 * USDC_DECIMALS_DIVISOR),
                        "bets": [
                            _make_polymarket_bet(
                                bet_id="bet_1",
                                resolution={  # type: ignore[arg-type]
                                    "winningIndex": 0,
                                    "blockTimestamp": 1700001000,
                                },
                            ),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        assert result["settled_at"] is not None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_block_timestamp_in_bet(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test bet with no blockTimestamp."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        bet = _make_polymarket_bet(bet_id="bet_1", block_timestamp=None)  # type: ignore[arg-type]
        mock_response.json.return_value = {
            "data": {"marketParticipants": [{"totalPayout": "0", "bets": [bet]}]}
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        assert result["created_at"] is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_resolution_block_timestamp(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test resolution without blockTimestamp."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        bet = _make_polymarket_bet(
            bet_id="bet_1",
            resolution={"winningIndex": 0, "blockTimestamp": None},  # type: ignore[arg-type]
        )
        bet["totalPayout"] = str(2 * USDC_DECIMALS_DIVISOR)
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {"totalPayout": str(2 * USDC_DECIMALS_DIVISOR), "bets": [bet]}
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        assert result["settled_at"] is None


# ---------------------------------------------------------------------------
# _fetch_market_slug tests
# ---------------------------------------------------------------------------


class TestFetchMarketSlug:
    """Tests for _fetch_market_slug."""

    def test_empty_market_id(self) -> None:
        """Test with empty market ID."""
        fetcher = _make_fetcher()

        result = fetcher._fetch_market_slug("")

        assert result == ""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    def test_successful_fetch(self, mock_get: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful slug fetch."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.json.return_value = {"slug": "will-it-rain"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = fetcher._fetch_market_slug("12345")

        assert result == "will-it-rain"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    def test_exception_handling(self, mock_get: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_get.side_effect = Exception("Network error")

        result = fetcher._fetch_market_slug("12345")

        assert result == ""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    def test_no_slug_in_response(self, mock_get: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when slug is not in response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.json.return_value = {"other": "data"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = fetcher._fetch_market_slug("12345")

        assert result == ""


# ---------------------------------------------------------------------------
# _get_ui_trading_strategy tests
# ---------------------------------------------------------------------------


class TestGetUiTradingStrategy:
    """Tests for _get_ui_trading_strategy."""

    def test_none_input(self) -> None:
        """Test None input."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy(None)

        assert result is None

    def test_empty_string(self) -> None:
        """Test empty string input."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("")

        assert result is None

    def test_balanced_strategy(self) -> None:
        """Test bet_amount_per_threshold maps to balanced."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("bet_amount_per_threshold")

        assert result == "balanced"

    def test_risky_strategy(self) -> None:
        """Test kelly_criterion_no_conf maps to risky."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("kelly_criterion_no_conf")

        assert result == "risky"

    def test_unknown_strategy(self) -> None:
        """Test unknown strategy returns None."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("unknown_strategy")

        assert result is None


# ---------------------------------------------------------------------------
# _format_bet_for_position tests
# ---------------------------------------------------------------------------


class TestFormatBetForPosition:
    """Tests for _format_bet_for_position."""

    def test_yes_side(self) -> None:
        """Test formatting bet with yes side."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b1",
            "bet_amount": 1.0,
            "prediction_side": "yes",
            "created_at": "2024-01-01T00:00:00Z",
        }
        market_info = {
            "prediction_response": {
                "p_yes": 0.8,
                "p_no": 0.2,
                "confidence": 0.9,
                "info_utility": 0.7,
            },
            "strategy": "kelly_criterion_no_conf",
        }

        result = fetcher._format_bet_for_position(bet, market_info, "tool_1")

        assert result["id"] == "b1"
        assert result["bet"]["amount"] == 1.0
        assert result["bet"]["side"] == "yes"
        assert result["intelligence"]["prediction_tool"] == "tool_1"
        assert result["intelligence"]["implied_probability"] == 80.0
        assert result["intelligence"]["confidence_score"] == 90.0
        assert result["intelligence"]["utility_score"] == 70.0
        assert result["strategy"] == "risky"

    def test_no_side(self) -> None:
        """Test formatting bet with no side."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b2",
            "bet_amount": 0.5,
            "prediction_side": "no",
            "created_at": "",
        }
        market_info = {
            "prediction_response": {
                "p_yes": 0.3,
                "p_no": 0.7,
                "confidence": 0.8,
                "info_utility": 0.6,
            },
            "strategy": "bet_amount_per_threshold",
        }

        result = fetcher._format_bet_for_position(bet, market_info, None)

        assert result["intelligence"]["implied_probability"] == 70.0
        assert result["strategy"] == "balanced"

    def test_none_market_info(self) -> None:
        """Test when market_info is None."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b3",
            "bet_amount": 1.0,
            "prediction_side": "yes",
            "created_at": "",
        }

        result = fetcher._format_bet_for_position(bet, None, None)

        assert result["intelligence"]["implied_probability"] == 0.0
        assert result["intelligence"]["confidence_score"] == 0.0
        assert result["strategy"] is None

    def test_no_prediction_response(self) -> None:
        """Test when prediction_response is missing from market_info."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b4",
            "bet_amount": 1.0,
            "prediction_side": "yes",
            "created_at": "",
        }
        market_info = {"strategy": None}

        result = fetcher._format_bet_for_position(bet, market_info, None)

        assert result["intelligence"]["implied_probability"] == 0.0
        assert result["strategy"] is None


# ---------------------------------------------------------------------------
# fetch_position_details tests
# ---------------------------------------------------------------------------


class TestFetchPositionDetails:
    """Tests for fetch_position_details."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock, mock_get: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful position details fetch."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets = [
                {
                    "id": "m_numeric_id",
                    "condition_id": "c_1",
                    "title": "Will it rain?",
                    "openingTimestamp": 0,
                    "prediction_response": {
                        "p_yes": 0.8,
                        "p_no": 0.2,
                        "confidence": 0.9,
                        "info_utility": 0.7,
                    },
                    "potential_net_profit": 0,
                    "strategy": "kelly_criterion_no_conf",
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "q_1",
                                "condition_id": "c_1",
                                "title": "Will it rain?",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0.5,
                            "total_payout": 1.5,
                            "status": "won",
                            "created_at": "2024-01-01T00:00:00Z",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            # Mock mech tool fetch
            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {
                    "sender": {"requests": [{"parsedRequest": {"tool": "tool_1"}}]}
                }
            }
            mock_post.return_value = mock_response_post

            # Mock slug fetch
            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {"slug": "will-it-rain"}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["id"] == "bet_1"
            assert result["status"] == "won"
            assert result["payout"] == 1.5
            assert result["currency"] == "USDC"
            assert result["external_url"].startswith("https://polymarket.com/")

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_bet_not_found(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when bet is not found anywhere."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump({}, f)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"marketParticipants": []}}
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is None

    def test_exception_handling(self) -> None:
        """Test exception handling."""
        fetcher = _make_fetcher()

        with patch.object(
            fetcher, "_load_agent_performance_data", side_effect=Exception("Error")
        ):
            result = fetcher.fetch_position_details(
                "bet_1", "0xsafe", "/tmp/test"  # nosec B108
            )

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_lost_status_payout_zero(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test lost status results in payout = 0."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "q_1",
                                "condition_id": "c_1",
                                "title": "Q?",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": -1.0,
                            "total_payout": 0,
                            "status": "lost",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {"slug": ""}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["payout"] == 0

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"  # type: ignore[no-untyped-def]
    )
    def test_invalid_status_payout(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test invalid status results in payout = total_payout."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_1", "title": "Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": -0.1,
                            "total_payout": 0.9,
                            "status": "invalid",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["payout"] == 0.9

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )  # type: ignore[no-untyped-def]
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_pending_with_potential_profit(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test pending status with potential profit."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets = [
                {
                    "id": "q_1",
                    "title": "Q?",
                    "openingTimestamp": 0,
                    "potential_net_profit": int(0.5 * USDC_DECIMALS_DIVISOR),
                    "strategy": None,
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_1", "title": "Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {"slug": "q-slug"}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            # payout = 1.0 + (500000 / 1000000) = 1.5
            assert result["payout"] == 1.5

    @patch(  # type: ignore[no-untyped-def]
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_market_info_uses_bet_market(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test when market not found in multi_bets, uses bet's market data."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_unknown", "title": "Unknown Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["question"] == "Unknown Q?"  # type: ignore[no-untyped-def]

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_fetches_prediction_response_when_missing(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test that prediction response is fetched from mech when missing."""
        fetcher = _make_fetcher()

        call_count = [0]

        def mock_post_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if call_count[0] == 1:
                # Prediction response fetch
                mock_resp.json.return_value = {
                    "data": {
                        "requests": [
                            {
                                "deliveries": [
                                    {
                                        "toolResponse": json.dumps(
                                            {
                                                "p_yes": 0.8,
                                                "p_no": 0.2,
                                                "confidence": 0.9,
                                                "info_utility": 0.5,
                                            }
                                        )
                                    }
                                ]
                            }
                        ]
                    }
                }
            else:
                # Mech tool fetch
                mock_resp.json.return_value = {
                    "data": {
                        "sender": {"requests": [{"parsedRequest": {"tool": "tool_x"}}]}
                    }
                }
            return mock_resp

        mock_post.side_effect = mock_post_side_effect

        mock_response_get = MagicMock()
        mock_response_get.json.return_value = {"slug": "slug"}
        mock_response_get.raise_for_status.return_value = None
        mock_get.return_value = mock_response_get

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets = [
                {
                    "id": "q_1",
                    "title": "Q?",
                    "openingTimestamp": 0,
                    "potential_net_profit": 0,
                    "strategy": None,
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_1", "title": "Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None  # type: ignore[no-untyped-def]

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_slug_results_in_empty_external_url(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test that empty slug results in empty external_url."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_1", "title": "Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            # Empty slug
            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)
            # type: ignore[no-untyped-def]
            assert result is not None
            assert result["external_url"] == ""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_market_info_is_empty_dict(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test when market_info is empty dict (falsy), skipping prediction tool fetch.

        This covers the branch 710->718 where market_info is falsy.

        :param mock_post: patched requests.post.
        :param mock_get: patched requests.get.
        """
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {},  # empty dict -> market_info will be {} (falsy)
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {}
            mock_response_get.raise_for_status.return_value = None  # type: ignore[no-untyped-def]
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            # market_info is {} (falsy) so prediction_tool should be None
            assert result["bets"][0]["intelligence"]["prediction_tool"] is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_no_prediction_response_no_title(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """Test when prediction response is missing and title is empty."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets = [
                {
                    "id": "q_1",
                    "openingTimestamp": 0,
                    "potential_net_profit": 0,
                    "strategy": None,
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_1", "title": ""},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {"sender": {"requests": []}}
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.get"
    )
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_invalid_created_at_falls_back(self, mock_post: MagicMock, mock_get: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Invalid created_at format does not crash, falls back to current time."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "q_1", "title": "Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "not-a-valid-timestamp",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response_post = MagicMock()
            mock_response_post.status_code = 200
            mock_response_post.json.return_value = {
                "data": {
                    "sender": {"requests": [{"parsedRequest": {"tool": "tool_1"}}]}
                }
            }
            mock_post.return_value = mock_response_post

            mock_response_get = MagicMock()
            mock_response_get.json.return_value = {}
            mock_response_get.raise_for_status.return_value = None
            mock_get.return_value = mock_response_get

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["id"] == "bet_1"


# ---------------------------------------------------------------------------
# Stub abstract methods tests
# ---------------------------------------------------------------------------


class TestStubAbstractMethods:
    """Tests for the stub abstract method implementations."""

    def test_fetch_trader_agent_bets_raises(self) -> None:
        """Test that _fetch_trader_agent_bets raises NotImplementedError."""
        fetcher = _make_fetcher()

        with pytest.raises(NotImplementedError):
            fetcher._fetch_trader_agent_bets()

    def test_build_market_context_raises(self) -> None:
        """Test that _build_market_context raises NotImplementedError."""
        fetcher = _make_fetcher()

        with pytest.raises(NotImplementedError):
            fetcher._build_market_context()

    def test_calculate_bet_net_profit_raises(self) -> None:
        """Test that _calculate_bet_net_profit raises NotImplementedError."""
        fetcher = _make_fetcher()

        with pytest.raises(NotImplementedError):
            fetcher._calculate_bet_net_profit()


# ---------------------------------------------------------------------------
# Resilience audit: BUG 26 -- {"data": null} AttributeError
# ---------------------------------------------------------------------------


class TestFetchMarketParticipantsDataNull:
    """BUG 26: _fetch_market_participants crashes on {"data": null}.

    `response_data.get("data", {}).get("marketParticipants", [])` fails when
    `.get("data", {})` returns None (not {}) because the value is explicitly
    null. The `.get("marketParticipants", [])` call raises AttributeError.
    Caught by broad except, so no crash, but the `or {}` guard is missing.
    """

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_data_null_returns_none_without_attribute_error(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock
    ) -> None:
        """Verify {"data": null} returns empty list cleanly, not via AttributeError.

        :param mock_post: patched requests.post
        """
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        # Returns empty list (no AttributeError -- the `or {}` guard handles null data)
        result = fetcher._fetch_market_participants("0xsafe", 10, 0)
        assert result == []


# ---------------------------------------------------------------------------
# Sell-aware perf summary: FIFO allocation, hybrid status, profit/payout
# (WITHDRAWAL_PERFORMANCE_SUMMARY_SPEC.md test plan §1-21)
# ---------------------------------------------------------------------------


def _raw_bet(  # type: ignore[no-untyped-def]
    bet_id: str = "b",
    is_buy: bool = True,
    amount_usdc: float = 1.0,
    shares: float = 2.0,
    outcome_index: int = 0,
    block_timestamp: int = 1700000000,
    question_id: str = "c_1",
    resolution: Optional[Dict[str, Any]] = None,
    transaction_hash: str = "0xhash",
) -> Dict[str, Any]:
    """Build a raw subgraph-shape bet dict (signed amount/shares for sells).

    :param bet_id: bet id
    :param is_buy: True for buy, False for sell
    :param amount_usdc: USDC amount (signed convention: buys positive, sells negative)
    :param shares: share count (signed convention: buys positive, sells negative)
    :param outcome_index: outcome index 0 or 1
    :param block_timestamp: block timestamp
    :param question_id: condition id used as group key
    :param resolution: resolution dict or None
    :param transaction_hash: tx hash
    :return: raw bet dict matching subgraph shape
    """
    sign = 1 if is_buy else -1
    return {
        "id": bet_id,
        "isBuy": is_buy,
        "amount": str(int(sign * amount_usdc * USDC_DECIMALS_DIVISOR)),
        "shares": str(int(sign * shares * USDC_DECIMALS_DIVISOR)),
        "outcomeIndex": outcome_index,
        "blockTimestamp": block_timestamp,
        "transactionHash": transaction_hash,
        "countedInTotal": resolution is not None,
        "question": {
            "id": question_id,
            "questionId": f"qid_{question_id}",
            "metadata": {"title": "T", "outcomes": ["Yes", "No"]},
            "resolution": resolution,
        },
    }


class TestAllocateFifo:
    """FIFO allocation of sells against buys per (question, outcomeIndex)."""

    def test_single_buy_no_sells_yields_buy_with_full_remaining(self) -> None:
        """A buy with no matching sell has remaining_shares == original_shares."""
        fetcher = _make_fetcher()
        bets = [_raw_bet("b1", is_buy=True, amount_usdc=1.0, shares=2.0)]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert len(buys) == 1
        assert buys[0]["id"] == "b1"
        assert buys[0]["original_shares"] == 2 * USDC_DECIMALS_DIVISOR
        assert buys[0]["original_cost"] == 1 * USDC_DECIMALS_DIVISOR
        assert buys[0]["remaining_shares"] == 2 * USDC_DECIMALS_DIVISOR
        assert buys[0]["allocated_proceeds"] == 0
        assert buys[0]["allocated_cost"] == 0

    def test_full_sell_against_single_buy_zeros_remaining(self) -> None:
        """A sell consuming all shares of one buy leaves remaining_shares ≈ 0."""
        fetcher = _make_fetcher()
        bets = [
            _raw_bet("b1", is_buy=True, amount_usdc=1.0, shares=2.0, block_timestamp=1),
            _raw_bet(
                "s1",
                is_buy=False,
                amount_usdc=1.5,
                shares=2.0,
                block_timestamp=2,
            ),
        ]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert len(buys) == 1
        buy = buys[0]
        assert buy["remaining_shares"] == 0
        assert buy["allocated_proceeds"] == int(1.5 * USDC_DECIMALS_DIVISOR)
        assert buy["allocated_cost"] == 1 * USDC_DECIMALS_DIVISOR

    def test_partial_sell_against_single_buy_leaves_remainder(self) -> None:
        """A sell consuming half the shares leaves half remaining; cost half-allocated."""
        fetcher = _make_fetcher()
        bets = [
            _raw_bet("b1", is_buy=True, amount_usdc=1.0, shares=2.0, block_timestamp=1),
            _raw_bet(
                "s1",
                is_buy=False,
                amount_usdc=0.6,
                shares=1.0,
                block_timestamp=2,
            ),
        ]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert len(buys) == 1
        buy = buys[0]
        # half consumed
        assert buy["remaining_shares"] == 1 * USDC_DECIMALS_DIVISOR
        assert abs(buy["allocated_proceeds"] - 0.6 * USDC_DECIMALS_DIVISOR) < 1
        assert buy["allocated_cost"] == int(0.5 * USDC_DECIMALS_DIVISOR)

    def test_sell_spanning_two_buys_fifo_order(self) -> None:
        """A sell consuming all of buy1 + part of buy2 splits proceeds proportionally."""
        fetcher = _make_fetcher()
        bets = [
            _raw_bet("b1", is_buy=True, amount_usdc=1.0, shares=2.0, block_timestamp=1),
            _raw_bet("b2", is_buy=True, amount_usdc=2.0, shares=4.0, block_timestamp=2),
            _raw_bet(
                "s1",
                is_buy=False,
                amount_usdc=3.0,
                shares=4.0,
                block_timestamp=3,
            ),
        ]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert len(buys) == 2
        buy1 = next(b for b in buys if b["id"] == "b1")
        buy2 = next(b for b in buys if b["id"] == "b2")
        # b1 fully consumed: 2 of 4 sold shares (50% of sell) → 1.5 USD of 3.0 proceeds.
        assert buy1["remaining_shares"] == 0
        assert abs(buy1["allocated_proceeds"] - 1.5 * USDC_DECIMALS_DIVISOR) < 1
        assert buy1["allocated_cost"] == 1 * USDC_DECIMALS_DIVISOR
        # b2 partially consumed: 2 of 4 shares (50% of buy2). proceeds = 50% of 3.0 = 1.5.
        # cost allocated = 50% of 2.0 = 1.0.
        assert buy2["remaining_shares"] == 2 * USDC_DECIMALS_DIVISOR
        assert abs(buy2["allocated_proceeds"] - 1.5 * USDC_DECIMALS_DIVISOR) < 1
        assert buy2["allocated_cost"] == int(1.0 * USDC_DECIMALS_DIVISOR)

    def test_two_sells_against_same_buy(self) -> None:
        """Two separate sells consume the same buy in chronological order."""
        fetcher = _make_fetcher()
        bets = [
            _raw_bet("b1", is_buy=True, amount_usdc=1.0, shares=4.0, block_timestamp=1),
            _raw_bet(
                "s1",
                is_buy=False,
                amount_usdc=0.5,
                shares=2.0,
                block_timestamp=2,
            ),
            _raw_bet(
                "s2",
                is_buy=False,
                amount_usdc=0.6,
                shares=2.0,
                block_timestamp=3,
            ),
        ]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert len(buys) == 1
        buy = buys[0]
        assert buy["remaining_shares"] == 0
        # Total proceeds from both sells: 0.5 + 0.6 = 1.1
        assert abs(buy["allocated_proceeds"] - 1.1 * USDC_DECIMALS_DIVISOR) < 1
        # All original cost consumed: 1.0
        assert buy["allocated_cost"] == 1 * USDC_DECIMALS_DIVISOR

    def test_orphan_sell_logs_warning_and_emits_no_buy(self) -> None:
        """A sell with no matching buy is logged and dropped from the output."""
        fetcher = _make_fetcher()
        bets = [
            _raw_bet(
                "s_orphan",
                is_buy=False,
                amount_usdc=0.5,
                shares=1.0,
                block_timestamp=1,
            )
        ]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert buys == []
        # Logger.warning called at least once
        fetcher.logger.warning.assert_called()

    def test_groups_by_outcome_index(self) -> None:
        """Buys on outcome 0 are not consumed by sells on outcome 1."""
        fetcher = _make_fetcher()
        bets = [
            _raw_bet(
                "b_yes",
                is_buy=True,
                amount_usdc=1.0,
                shares=2.0,
                outcome_index=0,
                block_timestamp=1,
            ),
            _raw_bet(
                "b_no",
                is_buy=True,
                amount_usdc=1.0,
                shares=2.0,
                outcome_index=1,
                block_timestamp=2,
            ),
            _raw_bet(
                "s_no",
                is_buy=False,
                amount_usdc=1.2,
                shares=2.0,
                outcome_index=1,
                block_timestamp=3,
            ),
        ]

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert len(buys) == 2
        b_yes = next(b for b in buys if b["id"] == "b_yes")
        b_no = next(b for b in buys if b["id"] == "b_no")
        # b_yes untouched
        assert b_yes["remaining_shares"] == 2 * USDC_DECIMALS_DIVISOR
        assert b_yes["allocated_proceeds"] == 0
        # b_no fully consumed by the same-outcome sell
        assert b_no["remaining_shares"] == 0
        assert abs(b_no["allocated_proceeds"] - 1.2 * USDC_DECIMALS_DIVISOR) < 1

    def test_drops_bet_with_null_question(self) -> None:
        """Bets with question=None have no group key; FIFO drops them silently."""
        fetcher = _make_fetcher()
        bets = [_raw_bet("b1", is_buy=True, amount_usdc=1.0, shares=2.0)]
        bets[0]["question"] = None

        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)

        assert buys == []

    def test_dust_remainder_treated_as_fully_sold(self) -> None:
        """Sub-cent dust after a sell counts as fully exited (epsilon)."""
        fetcher = _make_fetcher()
        # Buy 5.2625 shares (5_262_500 base units), sell 5.26 shares (5_260_000).
        # Remaining = 2_500 base units < SHARES_EPSILON (10_000); treated as dust.
        bets = [
            {
                "id": "b1",
                "isBuy": True,
                "amount": "1000000",
                "shares": "5262500",
                "outcomeIndex": 0,
                "blockTimestamp": 1,
                "transactionHash": "0xa",
                "question": {
                    "id": "c1",
                    "questionId": "q1",
                    "metadata": {"title": "T", "outcomes": ["Yes", "No"]},
                    "resolution": None,
                },
            },
            {
                "id": "s1",
                "isBuy": False,
                "amount": "-900000",
                "shares": "-5260000",
                "outcomeIndex": 0,
                "blockTimestamp": 2,
                "transactionHash": "0xb",
                "question": {
                    "id": "c1",
                    "questionId": "q1",
                    "metadata": {"title": "T", "outcomes": ["Yes", "No"]},
                    "resolution": None,
                },
            },
        ]
        buys = fetcher._allocate_fifo(bets, participant_total_payout=0)
        assert len(buys) == 1
        # Verify dust threshold treats this as fully exited.
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import (
            SHARES_EPSILON,
        )

        assert buys[0]["remaining_shares"] <= SHARES_EPSILON


class TestHybridStatus:
    """Hybrid status rule per Design §4."""

    def _enriched(
        self,
        original_shares: float,
        remaining_shares: float,
        allocated_proceeds: float,
        allocated_cost: float,
        original_cost: float,
        outcome_index: Optional[int] = 0,
        winning_index: Optional[int] = None,
        total_payout: int = 0,
    ) -> Dict[str, Any]:
        """Build a FIFO-enriched buy dict for status testing."""
        resolution = None
        if winning_index is not None:
            resolution = {"winningIndex": winning_index, "blockTimestamp": 1700001000}
        return {
            "id": "b1",
            "isBuy": True,
            "outcomeIndex": outcome_index,
            "amount": str(int(original_cost * USDC_DECIMALS_DIVISOR)),
            "shares": str(int(original_shares * USDC_DECIMALS_DIVISOR)),
            "original_shares": original_shares * USDC_DECIMALS_DIVISOR,
            "original_cost": original_cost * USDC_DECIMALS_DIVISOR,
            "remaining_shares": remaining_shares * USDC_DECIMALS_DIVISOR,
            "allocated_proceeds": allocated_proceeds * USDC_DECIMALS_DIVISOR,
            "allocated_cost": allocated_cost * USDC_DECIMALS_DIVISOR,
            "totalPayout": total_payout,
            "question": {
                "id": "c1",
                "questionId": "q1",
                "metadata": {"title": "T", "outcomes": ["Yes", "No"]},
                "resolution": resolution,
            },
        }

    def test_full_sell_unresolved_profit_positive_is_won(self) -> None:
        """Fully sold, no resolution yet, realized PnL > 0 → WON."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=1.5,
            allocated_cost=1.0,
            original_cost=1.0,
        )
        assert fetcher._get_prediction_status(bet) == "won"

    def test_full_sell_unresolved_profit_negative_is_lost(self) -> None:
        """Fully sold, no resolution, realized PnL < 0 → LOST."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=0.8,
            allocated_cost=1.0,
            original_cost=1.0,
        )
        assert fetcher._get_prediction_status(bet) == "lost"

    def test_full_sell_resolved_winning_but_sold_below_cost_is_lost(self) -> None:
        """Fully sold pre-resolution at a loss; later resolves in agent's favor.

        Realized PnL sign wins: LOST.
        """
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=0.8,
            allocated_cost=1.0,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
        )
        assert fetcher._get_prediction_status(bet) == "lost"

    def test_full_sell_break_even_is_pending(self) -> None:
        """Fully sold with realized PnL exactly 0 → PENDING fallback."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=1.0,
            allocated_cost=1.0,
            original_cost=1.0,
        )
        assert fetcher._get_prediction_status(bet) == "pending"

    def test_partial_sell_unresolved_is_pending(self) -> None:
        """Partial sell, market unresolved → PENDING (treated as still not sold)."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
        )
        assert fetcher._get_prediction_status(bet) == "pending"

    def test_partial_sell_resolved_won_redeemed_is_won(self) -> None:
        """Partial sell, resolved + agent won + redeemed → WON."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
            total_payout=int(1.0 * USDC_DECIMALS_DIVISOR),
        )
        assert fetcher._get_prediction_status(bet) == "won"

    def test_partial_sell_resolved_won_not_redeemed_is_pending(self) -> None:
        """Partial sell, resolved + agent won + NOT redeemed → PENDING (carve-out)."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
            total_payout=0,
        )
        assert fetcher._get_prediction_status(bet) == "pending"

    def test_partial_sell_resolved_lost_is_lost(self) -> None:
        """Partial sell, resolved + agent lost → LOST."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.4,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=1,
        )
        assert fetcher._get_prediction_status(bet) == "lost"

    def test_invalid_market_overrides_fully_sold(self) -> None:
        """Invalid market → INVALID regardless of remaining shares or profit."""
        fetcher = _make_fetcher()
        bet = self._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=1.5,
            allocated_cost=1.0,
            original_cost=1.0,
            outcome_index=0,
            winning_index=-1,
        )
        assert fetcher._get_prediction_status(bet) == "invalid"


class TestSellAwareProfit:
    """Profit calculations under sells per Design §5."""

    def test_full_sell_unresolved_returns_realized_pnl(self) -> None:
        """Fully sold, no resolution → profit = proceeds - allocated cost."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=1.5,
            allocated_cost=1.0,
            original_cost=1.0,
        )
        assert fetcher._calculate_bet_profit(bet) == 0.5

    def test_full_sell_resolved_loss_returns_realized_pnl(self) -> None:
        """Fully sold pre-resolution at a loss; profit = realized loss."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=0.8,
            allocated_cost=1.0,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
        )
        # Realized = 0.8 - 1.0 = -0.2; remaining=0 so no redemption.
        result = fetcher._calculate_bet_profit(bet)
        assert result is not None
        assert abs(result + 0.2) < 1e-6

    def test_partial_sell_won_redeemed_includes_realized_and_redemption(self) -> None:
        """Partial sell + won + redeemed: realized + redemption on remainder."""
        fetcher = _make_fetcher()
        # Sold 1 of 2 shares for 0.6 (cost basis 0.5).
        # Remainder 1 share redeems at 1 USDC (cost basis 0.5).
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
            total_payout=int(1.0 * USDC_DECIMALS_DIVISOR),
        )
        # realized = 0.1; redemption = 1.0 - 0.5 = 0.5; total = 0.6.
        result = fetcher._calculate_bet_profit(bet)
        assert result is not None
        assert abs(result - 0.6) < 1e-6

    def test_partial_sell_lost_returns_realized_minus_remaining_cost(self) -> None:
        """Partial sell + lost: realized - cost_remaining."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.4,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=1,
        )
        # realized = -0.1; remaining cost 0.5 worthless. total = -0.6.
        result = fetcher._calculate_bet_profit(bet)
        assert result is not None
        assert abs(result + 0.6) < 1e-6

    def test_partial_sell_won_not_redeemed_returns_realized_only(self) -> None:
        """Partial sell + won + not yet redeemed: profit = realized only."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
            total_payout=0,
        )
        # realized = 0.1; redemption deferred.
        result = fetcher._calculate_bet_profit(bet)
        assert result is not None
        assert abs(result - 0.1) < 1e-6


class TestSellAwareTotalPayout:
    """total_payout field semantics per Design §6."""

    def test_full_sell_total_payout_equals_realized_proceeds(self) -> None:
        """Fully sold unresolved: total_payout = realized proceeds."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=0.0,
            allocated_proceeds=1.5,
            allocated_cost=1.0,
            original_cost=1.0,
        )
        result = fetcher._format_single_bet(bet, "0xsafe", None)
        assert result is not None
        assert result["total_payout"] == 1.5

    def test_partial_sell_pending_total_payout_is_realized(self) -> None:
        """Partial-sell PENDING bet: total_payout reflects realized proceeds."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
        )
        result = fetcher._format_single_bet(bet, "0xsafe", None)
        assert result is not None
        assert result["status"] == "pending"
        assert result["total_payout"] == 0.6

    def test_partial_sell_won_redeemed_total_payout_is_realized_plus_redemption(
        self,
    ) -> None:
        """Partial-sell WON+redeemed: total_payout = realized + redemption value."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=1.0,
            allocated_proceeds=0.6,
            allocated_cost=0.5,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
            total_payout=int(1.0 * USDC_DECIMALS_DIVISOR),
        )
        result = fetcher._format_single_bet(bet, "0xsafe", None)
        assert result is not None
        assert result["status"] == "won"
        # realized 0.6 + redemption value 1.0 = 1.6.
        assert result["total_payout"] == 1.6


class TestRedemptionValueBranches:
    """Cover the rarer branches inside _redemption_value.

    Won-unredeemed, lost, legacy fallback.
    """

    def test_won_unredeemed_returns_zero(self) -> None:
        """Won but participant.totalPayout == 0 → no redemption yet."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=2.0,
            allocated_proceeds=0.0,
            allocated_cost=0.0,
            original_cost=1.0,
            outcome_index=0,
            winning_index=0,
            total_payout=0,
        )
        fifo = fetcher._fifo_state(bet)
        assert fetcher._redemption_value(bet, fifo) == 0.0

    def test_losing_outcome_returns_zero(self) -> None:
        """Losing outcome → remainder worthless."""
        fetcher = _make_fetcher()
        bet = TestHybridStatus()._enriched(
            original_shares=2.0,
            remaining_shares=2.0,
            allocated_proceeds=0.0,
            allocated_cost=0.0,
            original_cost=1.0,
            outcome_index=0,
            winning_index=1,
        )
        fifo = fetcher._fifo_state(bet)
        assert fetcher._redemption_value(bet, fifo) == 0.0

    def test_legacy_fallback_with_shares_returns_share_value(self) -> None:
        """Missing indices + shares > 0 → fall back to share-as-redemption signal."""
        fetcher = _make_fetcher()
        # Build a legacy-shaped bet: shares present, but outcomeIndex/winningIndex
        # are missing.
        bet = {
            "id": "b",
            "amount": str(USDC_DECIMALS_DIVISOR),
            "shares": str(2 * USDC_DECIMALS_DIVISOR),
            "totalPayout": 0,
            "question": {
                "id": "c",
                "questionId": "q",
                "metadata": {"title": "T", "outcomes": ["Yes", "No"]},
                "resolution": {"winningIndex": None, "blockTimestamp": 1700001000},
            },
        }
        fifo = fetcher._fifo_state(bet)
        # shares=2 → redemption value 2.0.
        assert fetcher._redemption_value(bet, fifo) == 2.0


class TestFetchBetFromSubgraphSellLookup:
    """Single-bet fetch when bet_id matches a sell row (not a buy)."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post"
    )
    def test_sell_id_returns_none(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """A bet_id matching a sell row yields None — sells are folded into buys.

        :param mock_post: patched requests.post
        """
        fetcher = _make_fetcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "bets": [
                            _raw_bet(
                                "b1",
                                is_buy=True,
                                amount_usdc=1.0,
                                shares=2.0,
                                block_timestamp=1,
                            ),
                            _raw_bet(
                                "s1",
                                is_buy=False,
                                amount_usdc=0.8,
                                shares=2.0,
                                block_timestamp=2,
                            ),
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("s1", "0xsafe")
        assert result is None
