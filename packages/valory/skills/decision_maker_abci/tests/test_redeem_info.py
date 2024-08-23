import pytest
from hexbytes import HexBytes

from packages.valory.skills.decision_maker_abci.redeem_info import Condition, Question, FPMM, Trade


class TestCondition:

    def test_initialization(self) -> None:
        condition = Condition(id="0x00000000000000001234567890abcdef",
                              outcomeSlotCount=2)
        condition.__post_init__()

        assert condition.outcomeSlotCount == 2
        assert condition.id == HexBytes("0x00000000000000001234567890abcdef")
        assert condition.index_sets == [1, 2]


class TestQuestion:

    @pytest.mark.parametrize(
        "name, id",
        [
            [
                "id as bytes",
                b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            ],
            [
                "id as string",
                "0x00000000000000001234567890abcdef"
            ]
        ]
    )
    def test_initialization(self, name, id) -> None:
        question = Question(id=id,
                            data="dummy_data")

        question.__post_init__()


class TestFPMM:

    def test_initialization(self) -> None:
        fpmm = FPMM(
            answerFinalizedTimestamp=1,
            collateralToken="dummy_collateral_token",
            condition={"id":HexBytes("0x00000000000000001234567890abcdef"),
                       "outcomeSlotCount":2},
            creator="dummy_creator",
            creationTimestamp=1,
            currentAnswer="0x1A2B3C",
            question={"id":b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                      "data":"dummy_data"},
            templateId=1
        )
        fpmm.__post_init__()

        assert (
            fpmm.answerFinalizedTimestamp==1,
            fpmm.collateralToken=="dummy_collateral_token",
            fpmm.condition==Condition(id=HexBytes("0x00000000000000001234567890abcdef"),
                              outcomeSlotCount=2),
            fpmm.creator=="dummy_creator",
            fpmm.creationTimestamp==1,
            fpmm.currentAnswer=="0x1A2B3C",
            fpmm.question==Question(id=b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                              data="dummy_data"),
            fpmm.templateId==1,
            fpmm.current_answer_index==1715004
        )


class TestTrade:

    @pytest.mark.parametrize(
        "outcomeIndex",
        [
            1,
            2
        ]
    )
    def test_initialization(self, outcomeIndex) -> None:
        trade = Trade(
            fpmm=dict(
                answerFinalizedTimestamp=1,
                collateralToken="dummy_collateral_token",
                condition=Condition(id=HexBytes("0x00000000000000001234567890abcdef"),
                                  outcomeSlotCount=2),
                creator="dummy_creator",
                creationTimestamp=1,
                currentAnswer="0x2",
                question=Question(id=b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                                  data="dummy_data"),
                templateId=1
                ),
            outcomeIndex=outcomeIndex,
            outcomeTokenMarginalPrice=1.00,
            outcomeTokensTraded=1,
            transactionHash="0x5b6a3f8eaa6c8a5c3b123d456e7890abcdef1234567890abcdef1234567890ab"
        )

        trade.__post_init__()
        assert (
            trade.fpmm==FPMM(
                answerFinalizedTimestamp=1,
                collateralToken="dummy_collateral_token",
                condition=Condition(id=HexBytes("0x00000000000000001234567890abcdef"),
                                  outcomeSlotCount=2),
                creator="dummy_creator",
                creationTimestamp=1,
                currentAnswer="0x2",
                question=Question(id=b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                                  data="dummy_data"),
                templateId=1
            ),
            trade.outcomeTokensTraded==1,
            trade.outcomeTokenMarginalPrice==1.00,
            trade.outcomeTokensTraded==1,
            trade.transactionHash=="0x5b6a3f8eaa6c8a5c3b123d456e7890abcdef1234567890abcdef1234567890ab",
        )
        if trade.outcomeIndex==1:
            assert (not trade.is_winning,
                    trade.claimable_amount==-1)
        else:
            assert (trade.is_winning,
                    trade.claimable_amount==2)

