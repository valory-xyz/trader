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

"""Tests for redeem info of decision_maker skill."""

import pytest
from hexbytes import HexBytes

from packages.valory.skills.decision_maker_abci.redeem_info import (
    Condition,
    FPMM,
    Question,
    Trade,
)


class TestCondition:
    """Test condition."""

    def test_initialization(self) -> None:
        """Test initialization."""
        condition = Condition(
            id="0x00000000000000001234567890abcdef", outcomeSlotCount=2
        )
        condition.__post_init__()

        assert condition.outcomeSlotCount == 2
        assert condition.id == HexBytes("0x00000000000000001234567890abcdef")
        assert condition.index_sets == [1, 2]


class TestQuestion:
    """Test Question."""

    @pytest.mark.parametrize(
        "name, id",
        [
            [
                "id as bytes",
                b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            ],
            ["id as string", "0x00000000000000001234567890abcdef"],
        ],
    )
    def test_initialization(self, name: str, id: bytes) -> None:
        """Test initialization."""
        question = Question(id=id, data="dummy_data")

        question.__post_init__()


class TestFPMM:
    """Test FPMM."""

    def test_initialization(self) -> None:
        """Test initialization"""
        fpmm = FPMM(
            answerFinalizedTimestamp=1,
            collateralToken="dummy_collateral_token",
            condition={
                "id": HexBytes("0x00000000000000001234567890abcdef"),
                "outcomeSlotCount": 2,
            },
            creator="dummy_creator",
            creationTimestamp=1,
            currentAnswer="0x1A2B3C",
            question={
                "id": b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                "data": "dummy_data",
            },
            templateId=1,
        )
        fpmm.__post_init__()

        assert (
            fpmm.answerFinalizedTimestamp == 1
            and fpmm.collateralToken == "dummy_collateral_token"
            and fpmm.condition
            == Condition(
                id=HexBytes("0x00000000000000001234567890abcdef"), outcomeSlotCount=2
            )
            and fpmm.creator == "dummy_creator"
            and fpmm.creationTimestamp == 1
            and fpmm.currentAnswer == "0x1A2B3C"
            and fpmm.question
            == Question(
                id=b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                data="dummy_data",
            )
            and fpmm.templateId == 1
            and fpmm.current_answer_index == 1715004
        )


class TestTrade:
    """Test Trade."""

    @pytest.mark.parametrize("outcomeIndex", [1, 2])
    def test_initialization(self, outcomeIndex: int) -> None:
        """Test initialization."""
        trade = Trade(
            fpmm=dict(
                answerFinalizedTimestamp=1,
                collateralToken="dummy_collateral_token",
                condition=Condition(
                    id=HexBytes("0x00000000000000001234567890abcdef"),
                    outcomeSlotCount=2,
                ),
                creator="dummy_creator",
                creationTimestamp=1,
                currentAnswer="0x2",
                question=Question(
                    id=b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                    data="dummy_data",
                ),
                templateId=1,
            ),
            outcomeIndex=outcomeIndex,
            outcomeTokenMarginalPrice=1.00,
            outcomeTokensTraded=1,
            transactionHash="0x5b6a3f8eaa6c8a5c3b123d456e7890abcdef1234567890abcdef1234567890ab",
        )

        trade.__post_init__()
        assert (
            trade.fpmm
            == FPMM(
                answerFinalizedTimestamp=1,
                collateralToken="dummy_collateral_token",
                condition=Condition(
                    id=HexBytes("0x00000000000000001234567890abcdef"),
                    outcomeSlotCount=2,
                ),
                creator="dummy_creator",
                creationTimestamp=1,
                currentAnswer="0x2",
                question=Question(
                    id=b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
                    data="dummy_data",
                ),
                templateId=1,
            )
            and trade.outcomeTokensTraded == 1
            and trade.outcomeTokenMarginalPrice == 1.00
            and trade.outcomeTokensTraded == 1
            and trade.transactionHash == "0x5b6a3f8eaa6c8a5c3b123d456e7890abcdef1234567890abcdef1234567890ab"
        )

        if trade.outcomeIndex == 1:
            assert not trade.is_winning, trade.claimable_amount == -1
        else:
            assert trade.is_winning, trade.claimable_amount == 2
