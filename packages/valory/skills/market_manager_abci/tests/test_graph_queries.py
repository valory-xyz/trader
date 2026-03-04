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

"""Tests for GraphQL query templates in the graph_tooling subpackage."""

from string import Template

from packages.valory.skills.market_manager_abci.graph_tooling.queries.conditional_tokens import (
    user_positions,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.network import (
    block_number,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.omen import (
    questions,
    trades as omen_trades,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.realitio import (
    answers,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.trades import (
    trades as trades_trades,
)


class TestConditionalTokensQueries:
    """Tests for the conditional_tokens query templates."""

    def test_user_positions_is_template(self) -> None:
        """Test that user_positions is a Template instance."""
        assert isinstance(user_positions, Template)

    def test_user_positions_substitution(self) -> None:
        """Test that user_positions can be substituted with expected variables."""
        result = user_positions.substitute(
            id="0xabc123",
            first=100,
            userPositions_id_gt="0xdef456",
        )
        assert "0xabc123" in result
        assert "100" in result
        assert "0xdef456" in result

    def test_user_positions_contains_expected_fields(self) -> None:
        """Test that the user_positions template contains expected GraphQL fields."""
        result = user_positions.substitute(
            id="test_id",
            first=10,
            userPositions_id_gt="gt_id",
        )
        assert "balance" in result
        assert "conditionIds" in result
        assert "lifetimeValue" in result
        assert "indexSets" in result
        assert "conditions" in result
        assert "outcomes" in result
        assert "totalBalance" in result
        assert "wrappedBalance" in result


class TestNetworkQueries:
    """Tests for the network query templates."""

    def test_block_number_is_template(self) -> None:
        """Test that block_number is a Template instance."""
        assert isinstance(block_number, Template)

    def test_block_number_substitution(self) -> None:
        """Test that block_number can be substituted with expected variables."""
        result = block_number.substitute(
            timestamp_from="1700000000",
            timestamp_to="1700001000",
        )
        assert "1700000000" in result
        assert "1700001000" in result

    def test_block_number_contains_expected_fields(self) -> None:
        """Test that the block_number template contains expected GraphQL fields."""
        result = block_number.substitute(
            timestamp_from="0",
            timestamp_to="1",
        )
        assert "blocks" in result
        assert "timestamp_gte" in result
        assert "timestamp_lte" in result


class TestOmenQueries:
    """Tests for the omen query templates."""

    def test_questions_is_template(self) -> None:
        """Test that questions is a Template instance."""
        assert isinstance(questions, Template)

    def test_questions_substitution(self) -> None:
        """Test that questions can be substituted with expected variables."""
        result = questions.substitute(
            creators='["0xabc", "0xdef"]',
            slot_count=2,
            opening_threshold=1700000000,
            languages='["en"]',
        )
        assert '["0xabc", "0xdef"]' in result
        assert "2" in result
        assert "1700000000" in result
        assert '["en"]' in result

    def test_questions_contains_expected_fields(self) -> None:
        """Test that the questions template contains expected GraphQL fields."""
        result = questions.substitute(
            creators="[]",
            slot_count=2,
            opening_threshold=0,
            languages="[]",
        )
        assert "fixedProductMarketMakers" in result
        assert "title" in result
        assert "collateralToken" in result
        assert "outcomeSlotCount" in result
        assert "outcomeTokenAmounts" in result
        assert "outcomeTokenMarginalPrices" in result
        assert "outcomes" in result
        assert "scaledLiquidityMeasure" in result

    def test_omen_trades_is_template(self) -> None:
        """Test that omen trades is a Template instance."""
        assert isinstance(omen_trades, Template)

    def test_omen_trades_substitution(self) -> None:
        """Test that omen trades can be substituted with expected variables."""
        result = omen_trades.substitute(
            creator="0xabc123",
            first=1000,
            creationTimestamp_gt="1700000000",
        )
        assert "0xabc123" in result
        assert "1000" in result
        assert "1700000000" in result

    def test_omen_trades_contains_expected_fields(self) -> None:
        """Test that the omen trades template contains expected GraphQL fields."""
        result = omen_trades.substitute(
            creator="0x0",
            first=1,
            creationTimestamp_gt="0",
        )
        assert "fpmmTrades" in result
        assert "answerFinalizedTimestamp" in result
        assert "collateralToken" in result
        assert "condition" in result
        assert "outcomeIndex" in result
        assert "outcomeTokensTraded" in result
        assert "transactionHash" in result


class TestRealitioQueries:
    """Tests for the realitio query templates."""

    def test_answers_is_template(self) -> None:
        """Test that answers is a Template instance."""
        assert isinstance(answers, Template)

    def test_answers_substitution(self) -> None:
        """Test that answers can be substituted with expected variables."""
        result = answers.substitute(
            question_id="0xquestion123",
        )
        assert "0xquestion123" in result

    def test_answers_contains_expected_fields(self) -> None:
        """Test that the answers template contains expected GraphQL fields."""
        result = answers.substitute(question_id="test")
        assert "answer" in result
        assert "question" in result
        assert "historyHash" in result
        assert "bondAggregate" in result
        assert "lastBond" in result
        assert "timestamp" in result


class TestTradesQueries:
    """Tests for the trades query templates."""

    def test_trades_is_template(self) -> None:
        """Test that trades is a Template instance."""
        assert isinstance(trades_trades, Template)

    def test_trades_substitution(self) -> None:
        """Test that trades can be substituted with expected variables."""
        result = trades_trades.substitute(
            creator="0xabc123",
            creationTimestamp_gte="1700000000",
            creationTimestamp_lte="1700100000",
            first=1000,
            creationTimestamp_gt="0",
        )
        assert "0xabc123" in result
        assert "1700000000" in result
        assert "1700100000" in result
        assert "1000" in result

    def test_trades_contains_expected_fields(self) -> None:
        """Test that the trades template contains expected GraphQL fields."""
        result = trades_trades.substitute(
            creator="0x0",
            creationTimestamp_gte="0",
            creationTimestamp_lte="1",
            first=1,
            creationTimestamp_gt="0",
        )
        assert "fpmmTrades" in result
        assert "collateralToken" in result
        assert "outcomeTokenMarginalPrice" in result
        assert "oldOutcomeTokenMarginalPrice" in result
        assert "collateralAmount" in result
        assert "collateralAmountUSD" in result
        assert "feeAmount" in result
        assert "outcomeIndex" in result
        assert "outcomeTokensTraded" in result
        assert "transactionHash" in result
        assert "answerFinalizedTimestamp" in result
        assert "currentAnswer" in result
        assert "isPendingArbitration" in result
        assert "arbitrationOccurred" in result
