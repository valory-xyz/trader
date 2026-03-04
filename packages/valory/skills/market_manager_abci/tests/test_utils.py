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
"""This module contains the tests for the utils of the MarketManager ABCI application."""

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    PredictionResponse,
    QueueStatus,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    INVALID_MARKET_ANSWER,
    MarketState,
    filter_claimed_conditions,
    get_bet_id_to_balance,
    get_condition_id_to_balances,
    get_position_balance,
    get_position_lifetime_value,
    next_status,
)


@pytest.mark.parametrize(
    "bets, expected",
    [
        (
            [
                Bet(
                    id="0x1ecd2fafee33e19cc4d5a150314c25aaeca95cea",
                    market="omen_subgraph",
                    title="Will the LTO Program publicly announce the commercial availability of an LTO-11 tape cartridge before or on August 1, 2025?",
                    collateralToken="0xe91d153e0b41518a2ce8dd3d7944fa863463a97d",  # nosec
                    creator="0x89c5cc945dd550bcffb72fe42bff002429f46fec",
                    fee=10000000000000000,
                    openingTimestamp=1754092800,
                    outcomeSlotCount=2,
                    outcomeTokenAmounts=[12821128072452298989, 3821816592354479467],
                    outcomeTokenMarginalPrices=[0.2296358408518959, 0.7703641591481041],
                    outcomes=["Yes", "No"],
                    scaledLiquidityMeasure=5.888381051174862,
                    prediction_response=PredictionResponse(
                        p_yes=0.5, p_no=0.5, confidence=0.5, info_utility=0.5
                    ),
                    position_liquidity=0,
                    potential_net_profit=0,
                    processed_timestamp=0,
                    queue_status=QueueStatus.TO_PROCESS,
                    investments={"Yes": [], "No": [49776971867373361]},
                ),
            ],
            '[{"id": "0x1ecd2fafee33e19cc4d5a150314c25aaeca95cea", "market": "omen_subgraph", "title": "Will the LTO Program publicly announce the commercial availability of an LTO-11 tape cartridge before or on August 1, 2025?", "collateralToken": "0xe91d153e0b41518a2ce8dd3d7944fa863463a97d", "creator": "0x89c5cc945dd550bcffb72fe42bff002429f46fec", "fee": 10000000000000000, "openingTimestamp": 1754092800, "outcomeSlotCount": 2, "outcomeTokenAmounts": [12821128072452298989, 3821816592354479467], "outcomeTokenMarginalPrices": [0.2296358408518959, 0.7703641591481041], "outcomes": ["Yes", "No"], "scaledLiquidityMeasure": 5.888381051174862, "prediction_response": {"p_yes": 0.5, "p_no": 0.5, "confidence": 0.5, "info_utility": 0.5}, "position_liquidity": 0, "potential_net_profit": 0, "processed_timestamp": 0, "queue_status": 1, "investments": {"Yes": [], "No": [49776971867373361]}, "outcome_token_ids": null, "condition_id": null, "category": null, "strategy": null}]',
        ),
    ],
)
def test_serialize_bets(bets: List[Bet], expected: str) -> None:
    """Test the serialize_bets function."""
    assert serialize_bets(bets) == expected


def test_get_position_lifetime_value_claimed() -> None:
    """Test the get_position_lifetime_value function."""

    condition_id = "0x1"
    user_positions = [
        {
            "position": {
                "conditionIds": [condition_id],
                "lifetimeValue": "36587407016997229890",
                "conditions": [
                    {
                        "id": condition_id,
                        "outcomes": ["Yes", "No"],
                    }
                ],
            },
            "totalBalance": "0",
        }
    ]

    assert get_position_lifetime_value(user_positions, condition_id) == 0


def test_get_position_lifetime_value_unclaimed() -> None:
    """Test the get_position_lifetime_value function."""

    condition_id = "0x1"
    user_positions = [
        {
            "position": {
                "conditionIds": [condition_id],
                "lifetimeValue": "25556977789032118615",
                "conditions": [
                    {
                        "id": condition_id,
                        "outcomes": ["Yes", "No"],
                    }
                ],
            },
            "totalBalance": "2238183507853351332",
        }
    ]
    assert (
        get_position_lifetime_value(user_positions, condition_id) == 2238183507853351332
    )


def test_get_condition_id_to_balances() -> None:
    """Test the get_condition_id_to_balances function."""

    condition_id = "0x1"
    trades = [
        {
            "outcomeIndex": 0,
            "fpmm": {
                "id": "0x1",
                "currentAnswer": "0x0",
                "answerFinalizedTimestamp": "1754092800",
                "isPendingArbitration": False,
                "condition": {
                    "id": condition_id,
                },
                "openingTimestamp": "1754092800",
            },
        }
    ]
    user_positions = [
        {
            "position": {
                "indexSets": ["0"],
                "conditionIds": [condition_id],
                "lifetimeValue": "2238183507853351332",
                "balance": "2238183507853351332",
                "conditions": [
                    {
                        "id": condition_id,
                        "outcomes": ["Yes", "No"],
                    }
                ],
            },
            "balance": "2238183507853351332",
            "totalBalance": "2238183507853351332",
        }
    ]

    condition_to_payout, condition_to_balance = get_condition_id_to_balances(
        trades, user_positions
    )

    # needs to be presented in both
    assert condition_to_payout[condition_id] == 2238183507853351332
    assert condition_to_balance[condition_id] == 2238183507853351332


# ---------------------------------------------------------------------------
# MarketState.__str__ coverage (line 43)
# ---------------------------------------------------------------------------


class TestMarketStateStr:
    """Tests for MarketState.__str__ method."""

    @pytest.mark.parametrize(
        "state, expected_str",
        [
            (MarketState.OPEN, "Open"),
            (MarketState.PENDING, "Pending"),
            (MarketState.FINALIZING, "Finalizing"),
            (MarketState.ARBITRATING, "Arbitrating"),
            (MarketState.CLOSED, "Closed"),
        ],
    )
    def test_str_returns_capitalized_name(
        self, state: MarketState, expected_str: str
    ) -> None:
        """Test that __str__ returns the capitalized name."""
        assert str(state) == expected_str


# ---------------------------------------------------------------------------
# get_position_balance coverage gaps (lines 58, 64, 68)
# ---------------------------------------------------------------------------


class TestGetPositionBalance:
    """Tests for the get_position_balance function."""

    def test_no_matching_condition_id(self) -> None:
        """Test that positions with non-matching condition_id are skipped."""
        user_positions = [
            {
                "position": {
                    "conditionIds": ["0xother"],
                    "conditions": [
                        {"id": "0xother", "outcomes": ["Yes", "No"]}
                    ],
                    "indexSets": ["1"],
                },
                "balance": "1000",
            }
        ]
        result = get_position_balance(user_positions, "0xmissing")
        assert result == {}

    def test_empty_conditions(self) -> None:
        """Test that positions with empty conditions list are skipped."""
        condition_id = "0xcond1"
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "conditions": [],
                    "indexSets": ["1"],
                },
                "balance": "1000",
            }
        ]
        result = get_position_balance(user_positions, condition_id)
        assert result == {}

    def test_empty_index_sets(self) -> None:
        """Test that positions with empty indexSets list are skipped."""
        condition_id = "0xcond1"
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "conditions": [
                        {"id": condition_id, "outcomes": ["Yes", "No"]}
                    ],
                    "indexSets": [],
                },
                "balance": "1000",
            }
        ]
        result = get_position_balance(user_positions, condition_id)
        assert result == {}

    def test_empty_outcomes(self) -> None:
        """Test that positions with empty outcomes are skipped."""
        condition_id = "0xcond1"
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "conditions": [
                        {"id": condition_id, "outcomes": []}
                    ],
                    "indexSets": ["1"],
                },
                "balance": "1000",
            }
        ]
        result = get_position_balance(user_positions, condition_id)
        assert result == {}

    def test_none_outcomes(self) -> None:
        """Test that positions with None outcomes are skipped."""
        condition_id = "0xcond1"
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "conditions": [
                        {"id": condition_id, "outcomes": None}
                    ],
                    "indexSets": ["1"],
                },
                "balance": "1000",
            }
        ]
        result = get_position_balance(user_positions, condition_id)
        assert result == {}

    def test_matching_position_balance(self) -> None:
        """Test that a matching position returns the correct balance."""
        condition_id = "0xcond1"
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "conditions": [
                        {"id": condition_id, "outcomes": ["Yes", "No"]}
                    ],
                    "indexSets": ["1"],
                },
                "balance": "5000",
            }
        ]
        result = get_position_balance(user_positions, condition_id)
        assert result == {"Yes": 5000}

    def test_empty_user_positions(self) -> None:
        """Test with an empty user positions list."""
        result = get_position_balance([], "0xcond1")
        assert result == {}


# ---------------------------------------------------------------------------
# next_status coverage (lines 95, 119-121, 124, 127)
# ---------------------------------------------------------------------------


class TestNextStatus:
    """Tests for the next_status function."""

    def test_open_status_no_answer_before_opening(self) -> None:
        """Test OPEN when currentAnswer is None and before opening timestamp."""
        fpmm: Dict[str, Any] = {"currentAnswer": None}
        # opening_timestamp far in the future
        result = next_status(
            fpmm,
            opening_timestamp=str(int(2e12)),
            answer_finalized_timestamp="0",
            is_pending_arbitration=False,
        )
        assert result == MarketState.OPEN

    def test_open_status_no_answer_no_opening_timestamp(self) -> None:
        """Test OPEN when currentAnswer is None and opening_timestamp is None."""
        fpmm: Dict[str, Any] = {"currentAnswer": None}
        result = next_status(
            fpmm,
            opening_timestamp=None,  # type: ignore
            answer_finalized_timestamp="0",
            is_pending_arbitration=False,
        )
        assert result == MarketState.OPEN

    def test_pending_status_no_answer_past_opening(self) -> None:
        """Test PENDING when currentAnswer is None and past opening timestamp."""
        fpmm: Dict[str, Any] = {"currentAnswer": None}
        # opening_timestamp far in the past
        result = next_status(
            fpmm,
            opening_timestamp="1000000000",
            answer_finalized_timestamp="0",
            is_pending_arbitration=False,
        )
        assert result == MarketState.PENDING

    def test_arbitrating_status(self) -> None:
        """Test ARBITRATING when is_pending_arbitration is True."""
        fpmm: Dict[str, Any] = {"currentAnswer": "0x1"}
        result = next_status(
            fpmm,
            opening_timestamp="1000000000",
            answer_finalized_timestamp="1000000000",
            is_pending_arbitration=True,
        )
        assert result == MarketState.ARBITRATING

    def test_finalizing_status(self) -> None:
        """Test FINALIZING when answer exists but not yet finalized."""
        fpmm: Dict[str, Any] = {"currentAnswer": "0x1"}
        # answer_finalized_timestamp far in the future
        result = next_status(
            fpmm,
            opening_timestamp="1000000000",
            answer_finalized_timestamp=str(int(2e12)),
            is_pending_arbitration=False,
        )
        assert result == MarketState.FINALIZING

    def test_closed_status(self) -> None:
        """Test CLOSED when answer exists and is finalized."""
        fpmm: Dict[str, Any] = {"currentAnswer": "0x1"}
        # answer_finalized_timestamp in the past
        result = next_status(
            fpmm,
            opening_timestamp="1000000000",
            answer_finalized_timestamp="1000000000",
            is_pending_arbitration=False,
        )
        assert result == MarketState.CLOSED


# ---------------------------------------------------------------------------
# get_condition_id_to_balances — invalid market answer (lines 119-121, 124, 127)
# ---------------------------------------------------------------------------


class TestGetConditionIdToBalancesInvalidAnswer:
    """Tests for get_condition_id_to_balances with invalid market answer."""

    def test_invalid_market_answer(self) -> None:
        """Test that invalid market answer triggers the payout path."""
        condition_id = "0xcond1"
        # INVALID_MARKET_ANSWER is 0xFF...FF (256 bits)
        invalid_answer_hex = hex(INVALID_MARKET_ANSWER)
        trades: List[Dict[str, Any]] = [
            {
                "outcomeIndex": 0,
                "fpmm": {
                    "id": "0xmarket1",
                    "currentAnswer": invalid_answer_hex,
                    "answerFinalizedTimestamp": "1000000000",
                    "isPendingArbitration": False,
                    "condition": {"id": condition_id},
                    "openingTimestamp": "1000000000",
                },
            }
        ]
        user_positions: List[Dict[str, Any]] = [
            {
                "position": {
                    "indexSets": ["1"],
                    "conditionIds": [condition_id],
                    "lifetimeValue": "5000",
                    "conditions": [
                        {"id": condition_id, "outcomes": ["Yes", "No"]}
                    ],
                },
                "balance": "0",
                "totalBalance": "5000",
            }
        ]
        condition_to_payout, condition_to_balance = get_condition_id_to_balances(
            trades, user_positions
        )
        # with invalid answer the condition should be included
        assert condition_id in condition_to_balance
        # payout should be set because balance is 0 but lifetime value > 0
        assert condition_id in condition_to_payout
        assert condition_to_payout[condition_id] == 5000
        assert condition_to_balance[condition_id] == 5000

    def test_non_closed_market_skipped(self) -> None:
        """Test that non-CLOSED markets are skipped in get_condition_id_to_balances."""
        condition_id = "0xcond1"
        # currentAnswer is None -> OPEN or PENDING, not CLOSED
        trades: List[Dict[str, Any]] = [
            {
                "outcomeIndex": 0,
                "fpmm": {
                    "id": "0xmarket1",
                    "currentAnswer": None,
                    "answerFinalizedTimestamp": "1000000000",
                    "isPendingArbitration": False,
                    "condition": {"id": condition_id},
                    "openingTimestamp": str(int(2e12)),
                },
            }
        ]
        user_positions: List[Dict[str, Any]] = [
            {
                "position": {
                    "indexSets": ["1"],
                    "conditionIds": [condition_id],
                    "lifetimeValue": "5000",
                    "conditions": [
                        {"id": condition_id, "outcomes": ["Yes", "No"]}
                    ],
                },
                "balance": "5000",
                "totalBalance": "5000",
            }
        ]
        condition_to_payout, condition_to_balance = get_condition_id_to_balances(
            trades, user_positions
        )
        assert condition_id not in condition_to_balance
        assert condition_id not in condition_to_payout

    def test_wrong_outcome_index_not_matching(self) -> None:
        """Test that a trade with non-matching outcome index is skipped."""
        condition_id = "0xcond1"
        trades: List[Dict[str, Any]] = [
            {
                "outcomeIndex": 1,
                "fpmm": {
                    "id": "0xmarket1",
                    "currentAnswer": "0x0",  # answer is 0, but we bet on 1
                    "answerFinalizedTimestamp": "1000000000",
                    "isPendingArbitration": False,
                    "condition": {"id": condition_id},
                    "openingTimestamp": "1000000000",
                },
            }
        ]
        user_positions: List[Dict[str, Any]] = []
        condition_to_payout, condition_to_balance = get_condition_id_to_balances(
            trades, user_positions
        )
        assert condition_id not in condition_to_balance

    def test_empty_trades(self) -> None:
        """Test with an empty trades list."""
        condition_to_payout, condition_to_balance = get_condition_id_to_balances(
            [], []
        )
        assert condition_to_payout == {}
        assert condition_to_balance == {}


# ---------------------------------------------------------------------------
# filter_claimed_conditions coverage (lines 137-144, 188-192)
# ---------------------------------------------------------------------------


class TestFilterClaimedConditions:
    """Tests for the filter_claimed_conditions function."""

    def test_no_claimed_conditions(self) -> None:
        """Test that no conditions are filtered when claimed list is empty."""
        payouts = {"0xcond1": 100, "0xcond2": 200}
        result = filter_claimed_conditions(payouts, [])
        assert result == {"0xcond1": 100, "0xcond2": 200}

    def test_filter_one_claimed(self) -> None:
        """Test filtering a single claimed condition."""
        payouts = {"0xcond1": 100, "0xcond2": 200}
        result = filter_claimed_conditions(payouts, ["0xcond1"])
        assert result == {"0xcond2": 200}

    def test_filter_all_claimed(self) -> None:
        """Test filtering when all conditions are claimed."""
        payouts = {"0xcond1": 100, "0xcond2": 200}
        result = filter_claimed_conditions(payouts, ["0xcond1", "0xcond2"])
        assert result == {}

    def test_case_insensitive_filtering(self) -> None:
        """Test that filtering is case insensitive."""
        payouts = {"0xAbCd": 100, "0xEfGh": 200}
        # claim with different case
        result = filter_claimed_conditions(payouts, ["0xabcd"])
        assert result == {"0xEfGh": 200}

    def test_case_insensitive_upper_in_claimed(self) -> None:
        """Test case insensitivity when claimed list has uppercase."""
        payouts = {"0xabcd": 100, "0xefgh": 200}
        result = filter_claimed_conditions(payouts, ["0xABCD", "0xEFGH"])
        assert result == {}

    def test_empty_payouts(self) -> None:
        """Test with empty payouts dict."""
        result = filter_claimed_conditions({}, ["0xcond1"])
        assert result == {}

    def test_non_matching_claimed_ids(self) -> None:
        """Test that non-matching claimed IDs do not filter anything."""
        payouts = {"0xcond1": 100, "0xcond2": 200}
        result = filter_claimed_conditions(payouts, ["0xother"])
        assert result == {"0xcond1": 100, "0xcond2": 200}


class TestGetBetIdToBalance:
    """Tests for the get_bet_id_to_balance function."""

    def test_basic(self) -> None:
        """Test basic mapping from trade fpmm id to position balance."""
        condition_id = "0xcond1"
        trades = [
            {
                "fpmm": {
                    "id": "0xbet1",
                    "condition": {"id": condition_id},
                },
            },
        ]
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "indexSets": ["1"],
                    "conditions": [{"id": condition_id, "outcomes": ["Yes", "No"]}],
                },
                "balance": "100",
            },
        ]
        result = get_bet_id_to_balance(trades, user_positions)
        assert "0xbet1" in result
        assert result["0xbet1"]["Yes"] == 100

    def test_empty_trades(self) -> None:
        """Test with empty trades returns empty dict."""
        result = get_bet_id_to_balance([], [])
        assert dict(result) == {}

    def test_multiple_trades(self) -> None:
        """Test with multiple trades maps each bet id."""
        trades = [
            {"fpmm": {"id": "bet_a", "condition": {"id": "c1"}}},
            {"fpmm": {"id": "bet_b", "condition": {"id": "c2"}}},
        ]
        result = get_bet_id_to_balance(trades, [])
        assert "bet_a" in result
        assert "bet_b" in result


class TestGetPositionLifetimeValueNonMatchingCondition:
    """Test get_position_lifetime_value when condition id does not match."""

    def test_non_matching_condition_continues(self) -> None:
        """Test that non-matching condition id continues to next position."""
        condition_id = "0x1"
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "lifetimeValue": "100",
                    "conditions": [
                        {"id": "0xOTHER", "outcomes": ["Yes", "No"]},
                        {"id": condition_id, "outcomes": ["Yes", "No"]},
                    ],
                },
                "totalBalance": "500",
            },
        ]
        result = get_position_lifetime_value(user_positions, condition_id)
        assert result == 500


class TestGetConditionIdToBalancesPayoutBranch:
    """Test the payout branch in get_condition_id_to_balances."""

    def test_payout_positive_balance_positive_skips_payout(self) -> None:
        """When payout > 0 and balance > 0, condition_id_to_payout is empty (line 176 False branch)."""
        condition_id = "0x1"
        trades = [
            {
                "outcomeIndex": 0,
                "fpmm": {
                    "id": "0x1",
                    "currentAnswer": "0x0",
                    "answerFinalizedTimestamp": "100",
                    "isPendingArbitration": False,
                    "condition": {"id": condition_id},
                    "openingTimestamp": "100",
                },
            },
        ]
        user_positions = [
            {
                "position": {
                    "conditionIds": [condition_id],
                    "lifetimeValue": "500",
                    "indexSets": ["1"],
                    "conditions": [{"id": condition_id, "outcomes": ["0", "1"]}],
                },
                "balance": "200",
                "totalBalance": "500",
            },
        ]
        with patch(
            "packages.valory.skills.market_manager_abci.graph_tooling.utils.time"
        ) as mock_time:
            mock_time.time.return_value = 999999.0
            payouts, balances = get_condition_id_to_balances(trades, user_positions)
        # payout > 0 but balance["0"] > 0 too, so condition should NOT be in payouts
        assert condition_id not in payouts
