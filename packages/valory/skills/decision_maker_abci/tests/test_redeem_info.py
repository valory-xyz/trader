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

"""Tests for the redeem_info module of decision_maker_abci."""

import pytest
from hexbytes import HexBytes

from packages.valory.skills.decision_maker_abci.redeem_info import (
    INVALID_MARKET_ANSWER,
    Condition,
    FPMM,
    Question,
    Trade,
)


class TestCondition:
    """Tests for the Condition dataclass."""

    def test_condition_creation(self) -> None:
        """Test creating a Condition instance."""
        condition = Condition(id=HexBytes(b"\x01" * 32), outcomeSlotCount=2)
        assert isinstance(condition.id, HexBytes)
        assert condition.outcomeSlotCount == 2

    def test_condition_string_id_converted_to_hexbytes(self) -> None:
        """Test that a string id is converted to HexBytes."""
        hex_str = "0x" + "01" * 32
        condition = Condition(id=hex_str, outcomeSlotCount=2)  # type: ignore[arg-type]
        assert isinstance(condition.id, HexBytes)

    def test_condition_outcome_slot_count_converted_to_int(self) -> None:
        """Test that outcomeSlotCount is converted to int."""
        condition = Condition(id=HexBytes(b"\x01" * 32), outcomeSlotCount="3")  # type: ignore[arg-type]
        assert condition.outcomeSlotCount == 3
        assert isinstance(condition.outcomeSlotCount, int)

    def test_condition_index_sets(self) -> None:
        """Test the index_sets property."""
        condition = Condition(id=HexBytes(b"\x01" * 32), outcomeSlotCount=3)
        assert condition.index_sets == [1, 2, 3]

    def test_condition_index_sets_two_outcomes(self) -> None:
        """Test the index_sets property with two outcomes."""
        condition = Condition(id=HexBytes(b"\x01" * 32), outcomeSlotCount=2)
        assert condition.index_sets == [1, 2]


class TestQuestion:
    """Tests for the Question dataclass."""

    def test_question_creation(self) -> None:
        """Test creating a Question instance."""
        question = Question(id=b"\x01" * 32, data="What is the answer?")
        assert question.id == b"\x01" * 32
        assert question.data == "What is the answer?"

    def test_question_string_id_converted_to_bytes(self) -> None:
        """Test that a string id is converted to bytes."""
        hex_str = "0x" + "ab" * 32
        question = Question(id=hex_str, data="test")  # type: ignore[arg-type]
        assert isinstance(question.id, bytes)
        assert question.id == bytes.fromhex("ab" * 32)


class TestFPMM:
    """Tests for the FPMM dataclass."""

    @staticmethod
    def _make_fpmm(**overrides: object) -> FPMM:
        """Create a FPMM instance with default values."""
        defaults = dict(
            answerFinalizedTimestamp=1000,
            collateralToken="0xtoken",
            condition=Condition(id=HexBytes(b"\x01" * 32), outcomeSlotCount=2),
            creator="0xcreator",
            creationTimestamp=900,
            currentAnswer="0x0000000000000000000000000000000000000000000000000000000000000001",
            question=Question(id=b"\x01" * 32, data="Will it rain?"),
            templateId=2,
        )
        defaults.update(overrides)
        return FPMM(**defaults)  # type: ignore[arg-type]

    def test_fpmm_creation(self) -> None:
        """Test creating an FPMM instance."""
        fpmm = self._make_fpmm()
        assert isinstance(fpmm.answerFinalizedTimestamp, int)
        assert isinstance(fpmm.creationTimestamp, int)
        assert isinstance(fpmm.templateId, int)

    def test_fpmm_post_init_converts_types(self) -> None:
        """Test that __post_init__ converts string values to int."""
        fpmm = self._make_fpmm(
            answerFinalizedTimestamp="2000",  # type: ignore[arg-type]
            creationTimestamp="1500",  # type: ignore[arg-type]
            templateId="5",  # type: ignore[arg-type]
        )
        assert fpmm.answerFinalizedTimestamp == 2000
        assert fpmm.creationTimestamp == 1500
        assert fpmm.templateId == 5

    def test_fpmm_dict_condition_converted(self) -> None:
        """Test that a dict condition is converted to Condition."""
        condition_dict = {"id": "0x" + "01" * 32, "outcomeSlotCount": 2}
        fpmm = self._make_fpmm(condition=condition_dict)
        assert isinstance(fpmm.condition, Condition)

    def test_fpmm_dict_question_converted(self) -> None:
        """Test that a dict question is converted to Question."""
        question_dict = {"id": "0x" + "01" * 32, "data": "test question"}
        fpmm = self._make_fpmm(question=question_dict)
        assert isinstance(fpmm.question, Question)

    def test_fpmm_current_answer_index(self) -> None:
        """Test the current_answer_index property."""
        fpmm = self._make_fpmm(
            currentAnswer="0x0000000000000000000000000000000000000000000000000000000000000001"
        )
        assert fpmm.current_answer_index == 1

    def test_fpmm_current_answer_index_zero(self) -> None:
        """Test the current_answer_index property for answer 0."""
        fpmm = self._make_fpmm(
            currentAnswer="0x0000000000000000000000000000000000000000000000000000000000000000"
        )
        assert fpmm.current_answer_index == 0


class TestTrade:
    """Tests for the Trade dataclass."""

    @staticmethod
    def _make_fpmm(
        current_answer: str = "0x0000000000000000000000000000000000000000000000000000000000000001",
        condition_id: bytes = b"\x01" * 32,
        question_id: bytes = b"\x02" * 32,
    ) -> FPMM:
        """Create a helper FPMM instance."""
        return FPMM(
            answerFinalizedTimestamp=1000,
            collateralToken="0xtoken",
            condition=Condition(id=HexBytes(condition_id), outcomeSlotCount=2),
            creator="0xcreator",
            creationTimestamp=900,
            currentAnswer=current_answer,
            question=Question(id=question_id, data="Will it rain?"),
            templateId=2,
        )

    def _make_trade(
        self,
        outcome_index: int = 1,
        current_answer: str = "0x0000000000000000000000000000000000000000000000000000000000000001",
        tokens_traded: int = 100,
        condition_id: bytes = b"\x01" * 32,
        question_id: bytes = b"\x02" * 32,
    ) -> Trade:
        """Create a helper Trade instance."""
        fpmm = self._make_fpmm(
            current_answer=current_answer,
            condition_id=condition_id,
            question_id=question_id,
        )
        return Trade(
            fpmm=fpmm,
            outcomeIndex=outcome_index,
            outcomeTokenMarginalPrice=0.5,
            outcomeTokensTraded=tokens_traded,
            transactionHash="0xtxhash",
        )

    def test_trade_creation(self) -> None:
        """Test creating a Trade instance."""
        trade = self._make_trade()
        assert isinstance(trade.outcomeIndex, int)
        assert isinstance(trade.outcomeTokenMarginalPrice, float)
        assert isinstance(trade.outcomeTokensTraded, int)

    def test_trade_post_init_converts_types(self) -> None:
        """Test that __post_init__ converts types correctly."""
        fpmm = self._make_fpmm()
        trade = Trade(
            fpmm=fpmm,
            outcomeIndex="0",  # type: ignore[arg-type]
            outcomeTokenMarginalPrice="0.75",  # type: ignore[arg-type]
            outcomeTokensTraded="200",  # type: ignore[arg-type]
            transactionHash="0xtxhash",
        )
        assert trade.outcomeIndex == 0
        assert trade.outcomeTokenMarginalPrice == 0.75
        assert trade.outcomeTokensTraded == 200

    def test_trade_dict_fpmm_converted(self) -> None:
        """Test that a dict fpmm is converted to FPMM."""
        fpmm_dict = {
            "answerFinalizedTimestamp": 1000,
            "collateralToken": "0xtoken",
            "condition": {"id": "0x" + "01" * 32, "outcomeSlotCount": 2},
            "creator": "0xcreator",
            "creationTimestamp": 900,
            "currentAnswer": "0x" + "00" * 31 + "01",
            "question": {"id": "0x" + "02" * 32, "data": "test"},
            "templateId": 2,
        }
        trade = Trade(
            fpmm=fpmm_dict,  # type: ignore[arg-type]
            outcomeIndex=1,
            outcomeTokenMarginalPrice=0.5,
            outcomeTokensTraded=100,
            transactionHash="0xtxhash",
        )
        assert isinstance(trade.fpmm, FPMM)

    def test_trade_is_winning_true(self) -> None:
        """Test is_winning when our answer matches the correct answer."""
        trade = self._make_trade(
            outcome_index=1,
            current_answer="0x0000000000000000000000000000000000000000000000000000000000000001",
        )
        assert trade.is_winning is True

    def test_trade_is_winning_false(self) -> None:
        """Test is_winning when our answer does not match the correct answer."""
        trade = self._make_trade(
            outcome_index=0,
            current_answer="0x0000000000000000000000000000000000000000000000000000000000000001",
        )
        assert trade.is_winning is False

    def test_trade_is_winning_invalid_market_answer(self) -> None:
        """Test is_winning when the market answer is invalid (always winning)."""
        invalid_hex = hex(INVALID_MARKET_ANSWER)
        trade = self._make_trade(outcome_index=0, current_answer=invalid_hex)
        assert trade.is_winning is True

    def test_trade_claimable_amount_winning(self) -> None:
        """Test claimable_amount when the trade is winning."""
        trade = self._make_trade(
            outcome_index=1,
            current_answer="0x0000000000000000000000000000000000000000000000000000000000000001",
            tokens_traded=500,
        )
        assert trade.claimable_amount == 500

    def test_trade_claimable_amount_losing(self) -> None:
        """Test claimable_amount when the trade is losing."""
        trade = self._make_trade(
            outcome_index=0,
            current_answer="0x0000000000000000000000000000000000000000000000000000000000000001",
            tokens_traded=500,
        )
        assert trade.claimable_amount == -500

    def test_trade_equality_same_condition(self) -> None:
        """Test trade equality by condition id."""
        trade1 = self._make_trade(condition_id=b"\x01" * 32, question_id=b"\x02" * 32)
        trade2 = self._make_trade(condition_id=b"\x01" * 32, question_id=b"\x03" * 32)
        assert trade1 == trade2

    def test_trade_equality_same_question(self) -> None:
        """Test trade equality by question id."""
        trade1 = self._make_trade(condition_id=b"\x01" * 32, question_id=b"\x02" * 32)
        trade2 = self._make_trade(condition_id=b"\x03" * 32, question_id=b"\x02" * 32)
        assert trade1 == trade2

    def test_trade_inequality(self) -> None:
        """Test trade inequality when neither condition nor question matches."""
        trade1 = self._make_trade(condition_id=b"\x01" * 32, question_id=b"\x02" * 32)
        trade2 = self._make_trade(condition_id=b"\x03" * 32, question_id=b"\x04" * 32)
        assert trade1 != trade2

    def test_trade_equality_with_non_trade(self) -> None:
        """Test trade equality with a non-Trade object."""
        trade = self._make_trade()
        assert trade != "not a trade"

    def test_trade_hash(self) -> None:
        """Test trade hash function."""
        trade = self._make_trade()
        h = hash(trade)
        assert isinstance(h, int)

    def test_trade_hash_consistency(self) -> None:
        """Test that equal trades have the same hash (when condition IDs match)."""
        trade1 = self._make_trade(condition_id=b"\x01" * 32, question_id=b"\x02" * 32)
        trade2 = self._make_trade(condition_id=b"\x01" * 32, question_id=b"\x02" * 32)
        assert hash(trade1) == hash(trade2)
