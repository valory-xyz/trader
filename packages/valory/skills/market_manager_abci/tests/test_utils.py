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
