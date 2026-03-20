# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""VWAP (Volume-Weighted Average Price) computation for CLOB order books."""

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class VWAPResult:
    """Result of a VWAP simulation against an order book."""

    vwap: float
    total_shares: float
    budget_spent: float
    fully_filled: bool


def compute_vwap(asks: List[Tuple[float, float]], budget: float) -> VWAPResult:
    """Simulate a marketable BUY against the ask book and compute the VWAP.

    :param asks: list of (price, size) tuples representing ask levels.
    :param budget: total USDC budget to spend.
    :return: VWAPResult with the average fill price and fill details.
    """
    if budget <= 0:
        return VWAPResult(
            vwap=0.0, total_shares=0.0, budget_spent=0.0, fully_filled=True
        )

    sorted_asks = sorted(asks, key=lambda x: x[0])

    remaining = budget
    total_spent = 0.0
    total_shares = 0.0

    for price, size in sorted_asks:
        if price <= 0 or size <= 0:
            continue

        notional = price * size
        spend = min(remaining, notional)
        shares = spend / price

        total_spent += spend
        total_shares += shares
        remaining -= spend

        if remaining <= 0:
            break

    if total_shares == 0:
        return VWAPResult(
            vwap=0.0, total_shares=0.0, budget_spent=0.0, fully_filled=False
        )

    vwap = total_spent / total_shares
    fully_filled = remaining <= 0

    return VWAPResult(
        vwap=vwap,
        total_shares=total_shares,
        budget_spent=total_spent,
        fully_filled=fully_filled,
    )
