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

"""This module contains tests for the GraphQL query constants in queries.py."""

import pytest

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_ALL_MECH_REQUESTS_QUERY,
    GET_DAILY_PROFIT_STATISTICS_QUERY,
    GET_FPMM_PAYOUTS_QUERY,
    GET_MECH_REQUESTS_BY_TITLES_QUERY,
    GET_MECH_RESPONSE_QUERY,
    GET_MECH_SENDER_QUERY,
    GET_MECH_TOOL_FOR_QUESTION_QUERY,
    GET_OMEN_FINALIZATION_QUERY,
    GET_OPEN_MARKETS_QUERY,
    GET_PENDING_BETS_QUERY,
    GET_POLYMARKET_DAILY_PROFIT_STATISTICS_QUERY,
    GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
    GET_POLYMARKET_SPECIFIC_BET_QUERY,
    GET_POLYMARKET_TRADER_AGENT_BETS_QUERY,
    GET_POLYMARKET_TRADER_AGENT_DETAILS_QUERY,
    GET_POLYMARKET_TRADER_AGENT_PERFORMANCE_QUERY,
    GET_PREDICTION_HISTORY_QUERY,
    GET_RESOLVED_MARKETS_QUERY,
    GET_SPECIFIC_MARKET_BETS_QUERY,
    GET_STAKING_SERVICE_QUERY,
    GET_TRADER_AGENT_BETS_QUERY,
    GET_TRADER_AGENT_DETAILS_QUERY,
    GET_TRADER_AGENT_PERFORMANCE_QUERY,
    GET_TRADER_AGENT_QUERY,
)

# Map of constant name to expected GraphQL query operation name
QUERY_CONSTANTS = {
    "GET_TRADER_AGENT_QUERY": (GET_TRADER_AGENT_QUERY, "GetOlasTraderAgent"),
    "GET_MECH_SENDER_QUERY": (GET_MECH_SENDER_QUERY, "MechSender"),
    "GET_OPEN_MARKETS_QUERY": (GET_OPEN_MARKETS_QUERY, "Fpmms"),
    "GET_STAKING_SERVICE_QUERY": (GET_STAKING_SERVICE_QUERY, "StakingService"),
    "GET_TRADER_AGENT_BETS_QUERY": (
        GET_TRADER_AGENT_BETS_QUERY,
        "GetOlasTraderAgentBets",
    ),
    "GET_TRADER_AGENT_DETAILS_QUERY": (
        GET_TRADER_AGENT_DETAILS_QUERY,
        "GetTraderAgentDetails",
    ),
    "GET_TRADER_AGENT_PERFORMANCE_QUERY": (
        GET_TRADER_AGENT_PERFORMANCE_QUERY,
        "GetTraderAgentPerformance",
    ),
    "GET_PREDICTION_HISTORY_QUERY": (
        GET_PREDICTION_HISTORY_QUERY,
        "GetPredictionHistory",
    ),
    "GET_RESOLVED_MARKETS_QUERY": (
        GET_RESOLVED_MARKETS_QUERY,
        "GetResolvedMarkets",
    ),
    "GET_FPMM_PAYOUTS_QUERY": (GET_FPMM_PAYOUTS_QUERY, "GetFPMMPayouts"),
    "GET_PENDING_BETS_QUERY": (GET_PENDING_BETS_QUERY, "GetPendingBets"),
    "GET_DAILY_PROFIT_STATISTICS_QUERY": (
        GET_DAILY_PROFIT_STATISTICS_QUERY,
        "GetDailyProfitStatistics",
    ),
    "GET_ALL_MECH_REQUESTS_QUERY": (
        GET_ALL_MECH_REQUESTS_QUERY,
        "GetAllMechRequests",
    ),
    "GET_MECH_REQUESTS_BY_TITLES_QUERY": (
        GET_MECH_REQUESTS_BY_TITLES_QUERY,
        "GetMechRequestsByTitles",
    ),
    "GET_POLYMARKET_TRADER_AGENT_DETAILS_QUERY": (
        GET_POLYMARKET_TRADER_AGENT_DETAILS_QUERY,
        "GetPolymarketTraderAgentDetails",
    ),
    "GET_MECH_TOOL_FOR_QUESTION_QUERY": (
        GET_MECH_TOOL_FOR_QUESTION_QUERY,
        "GetMechToolForQuestion",
    ),
    "GET_POLYMARKET_TRADER_AGENT_PERFORMANCE_QUERY": (
        GET_POLYMARKET_TRADER_AGENT_PERFORMANCE_QUERY,
        "GetPolymarketTraderAgentPerformance",
    ),
    "GET_POLYMARKET_PREDICTION_HISTORY_QUERY": (
        GET_POLYMARKET_PREDICTION_HISTORY_QUERY,
        "GetPolymarketPredictionHistory",
    ),
    "GET_POLYMARKET_TRADER_AGENT_BETS_QUERY": (
        GET_POLYMARKET_TRADER_AGENT_BETS_QUERY,
        "GetPolymarketTraderAgentBets",
    ),
    "GET_MECH_RESPONSE_QUERY": (GET_MECH_RESPONSE_QUERY, "GetMechResponse"),
    "GET_SPECIFIC_MARKET_BETS_QUERY": (
        GET_SPECIFIC_MARKET_BETS_QUERY,
        "GetSpecificMarketBets",
    ),
    "GET_POLYMARKET_DAILY_PROFIT_STATISTICS_QUERY": (
        GET_POLYMARKET_DAILY_PROFIT_STATISTICS_QUERY,
        "GetPolymarketDailyProfitStatistics",
    ),
    "GET_POLYMARKET_SPECIFIC_BET_QUERY": (
        GET_POLYMARKET_SPECIFIC_BET_QUERY,
        "GetPolymarketSpecificBet",
    ),
    "GET_OMEN_FINALIZATION_QUERY": (
        GET_OMEN_FINALIZATION_QUERY,
        "GetOmenFinalization",
    ),
}


@pytest.mark.parametrize(
    "constant_name,query_value,expected_operation",
    [(name, value, op) for name, (value, op) in QUERY_CONSTANTS.items()],
)
def test_query_is_non_empty_string(
    constant_name: str, query_value: str, expected_operation: str
) -> None:
    """Test that each query constant is a non-empty string."""
    assert isinstance(query_value, str), f"{constant_name} is not a string"
    assert len(query_value.strip()) > 0, f"{constant_name} is empty"


@pytest.mark.parametrize(
    "constant_name,query_value,expected_operation",
    [(name, value, op) for name, (value, op) in QUERY_CONSTANTS.items()],
)
def test_query_contains_expected_operation_name(
    constant_name: str, query_value: str, expected_operation: str
) -> None:
    """Test that each query constant contains the expected GraphQL operation name."""
    assert (
        expected_operation in query_value
    ), f"{constant_name} does not contain expected operation name '{expected_operation}'"


@pytest.mark.parametrize(
    "constant_name,query_value,expected_operation",
    [(name, value, op) for name, (value, op) in QUERY_CONSTANTS.items()],
)
def test_query_contains_query_keyword(
    constant_name: str, query_value: str, expected_operation: str
) -> None:
    """Test that each query constant contains the 'query' keyword."""
    assert (
        "query" in query_value.lower()
    ), f"{constant_name} does not contain the 'query' keyword"


# Bug A (ZD#919): status helpers gate the "invalid" label on Reality.eth
# finalization. The olas_agents subgraph does not expose
# answerFinalizedTimestamp or isPendingArbitration, so we source both from
# omen_subgraph via a single dedicated finalization query. This test pins
# the schema of that query — the three olas queries no longer need the
# field (enrichment happens in _enrich_bets_with_finalization).
def test_omen_finalization_query_selects_required_fields() -> None:
    """GET_OMEN_FINALIZATION_QUERY must select both finalization fields."""
    assert "answerFinalizedTimestamp" in GET_OMEN_FINALIZATION_QUERY, (
        "GET_OMEN_FINALIZATION_QUERY must select answerFinalizedTimestamp "
        "to support the Bug A finalization gate"
    )
    assert "isPendingArbitration" in GET_OMEN_FINALIZATION_QUERY, (
        "GET_OMEN_FINALIZATION_QUERY must select isPendingArbitration to "
        "correctly classify markets under Kleros arbitration as pending"
    )
    assert "fixedProductMarketMakers" in GET_OMEN_FINALIZATION_QUERY, (
        "GET_OMEN_FINALIZATION_QUERY must target the "
        "fixedProductMarketMakers entity on omen_subgraph"
    )
    assert "id_in" in GET_OMEN_FINALIZATION_QUERY, (
        "GET_OMEN_FINALIZATION_QUERY must filter by id_in for batched "
        "enrichment keyed on fpmm ids"
    )
