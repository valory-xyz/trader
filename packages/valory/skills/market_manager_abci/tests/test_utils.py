# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

from typing import List

import pytest

from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    PredictionResponse,
    QueueStatus,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    get_condition_id_to_balances,
    get_position_lifetime_value,
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
            '[{"id": "0x1ecd2fafee33e19cc4d5a150314c25aaeca95cea", "market": "omen_subgraph", "title": "Will the LTO Program publicly announce the commercial availability of an LTO-11 tape cartridge before or on August 1, 2025?", "collateralToken": "0xe91d153e0b41518a2ce8dd3d7944fa863463a97d", "creator": "0x89c5cc945dd550bcffb72fe42bff002429f46fec", "fee": 10000000000000000, "openingTimestamp": 1754092800, "outcomeSlotCount": 2, "outcomeTokenAmounts": [12821128072452298989, 3821816592354479467], "outcomeTokenMarginalPrices": [0.2296358408518959, 0.7703641591481041], "outcomes": ["Yes", "No"], "scaledLiquidityMeasure": 5.888381051174862, "prediction_response": {"p_yes": 0.5, "p_no": 0.5, "confidence": 0.5, "info_utility": 0.5}, "position_liquidity": 0, "potential_net_profit": 0, "processed_timestamp": 0, "queue_status": 1, "investments": {"Yes": [], "No": [49776971867373361]}}]',
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
