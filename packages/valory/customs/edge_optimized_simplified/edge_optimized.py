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

"""Edge-optimized betting strategy that sizes bets based on the divergence between predicted probability and market-implied price."""


from typing import Dict, List, Union


# ── required fields ──────────────────────────────────────────────────────
REQUIRED_FIELDS = frozenset(
    {
        "win_probability",
        "selected_type_tokens_in_pool",
        "other_tokens_in_pool",
        "min_bet",
        "max_bet",
    }
)

DEFAULT_MIN_EDGE = 0.05  # 5% edge required to act
DEFAULT_MAX_EDGE = 0.25  # edge at which we bet max_bet


def _market_implied_price(
    selected_type_tokens_in_pool: int, other_tokens_in_pool: int
) -> float:
    total = selected_type_tokens_in_pool + other_tokens_in_pool
    if total == 0:
        return 0.5
    return other_tokens_in_pool / total


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(x, hi))


def get_bet_amount_edge_only(
    win_probability: float,
    selected_type_tokens_in_pool: int,
    other_tokens_in_pool: int,
    min_bet: int,
    max_bet: int,
    min_edge: float = DEFAULT_MIN_EDGE,
    max_edge: float = DEFAULT_MAX_EDGE,
) -> Dict[str, Union[int, List[str]]]:
    """
    Edge-only betting strategy.

    - Ignores bankroll entirely
    - Ignores confidence and accuracy
    - Sizes bets only from min_bet → max_bet based on edge
    """

    # Flipping tokens as we're getting wrong values from the pool info. This is a temporary fix until we can investigate the root cause.
    selected_type_tokens_in_pool, other_tokens_in_pool = (
        other_tokens_in_pool,
        selected_type_tokens_in_pool,
    )

    info: List[str] = []
    error: List[str] = []

    # ── market price ───────────────────────────────────────────────
    market_price = _market_implied_price(
        selected_type_tokens_in_pool,
        other_tokens_in_pool,
    )

    edge = win_probability - market_price

    info.append(f"Market price: {market_price:.4f}")
    info.append(f"Model p_yes:  {win_probability:.4f}")
    info.append(f"Edge:         {edge:+.4f}")

    # ── edge gate ──────────────────────────────────────────────────
    if edge < min_edge:
        info.append(f"Edge {edge:.4f} < min_edge {min_edge:.4f}. No bet.")
        return {"bet_amount": 0, "info": info, "error": error}

    # ── linear sizing ──────────────────────────────────────────────
    edge_scaled = clamp(
        (edge - min_edge) / (max_edge - min_edge),
        0.0,
        1.0,
    )

    bet_amount = int(min_bet + edge_scaled * (max_bet - min_bet))

    info.append(f"Edge scaled:  {edge_scaled:.2f}")
    info.append(f"Bet amount:  {bet_amount}")

    return {
        "bet_amount": bet_amount,
        "info": info,
        "error": error,
    }


def run(*_args, **kwargs) -> Dict[str, Union[int, List[str]]]:
    missing = [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]
    if missing:
        return {"error": [f"Missing required fields: {missing}"]}

    return get_bet_amount_edge_only(**kwargs)
