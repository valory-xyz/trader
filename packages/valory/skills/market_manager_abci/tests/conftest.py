# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""Shared fixtures for the MarketManager ABCI tests."""

from typing import Any, Dict


def raw_bet(bet_id: str, **overrides: Any) -> Dict[str, Any]:
    """Build a raw bet payload accepted by ``_process_chunk``.

    :param bet_id: the id to give the raw bet.
    :param **overrides: fields overriding the defaults.
    :return: the raw bet dict.
    """
    payload: Dict[str, Any] = dict(
        id=bet_id,
        title="Q?",
        collateralToken="0x",
        creator="0x",
        fee=0,
        openingTimestamp=9999999999,
        outcomeSlotCount=2,
        outcomeTokenAmounts=[100, 200],
        outcomeTokenMarginalPrices=[0.5, 0.5],
        outcomes=["Yes", "No"],
        scaledLiquidityMeasure=10.0,
    )
    payload.update(overrides)
    return payload
