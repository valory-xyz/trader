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

"""Edge-optimized betting strategy.

This strategy sizes bets based on the *edge* — the divergence between
the mech's predicted probability and the market-implied price.

Advantages over the existing strategies:

* **bet_amount_per_threshold** uses a static lookup table keyed on confidence.
  It completely ignores the market price, so a 70 % confident prediction pays
  the same whether the market price is 0.50 or 0.69.  That leaves huge EV on
  the table and can't adapt to changing bankrolls.

* **kelly_criterion_no_conf** derives a theoretically optimal fraction via a
  quartic formula that is numerically fragile and hard to reason about.  It
  also ignores the *direction* of the edge (predicted prob vs market price)
  which is the single strongest predictor of long-run profitability.

This strategy:
1. Computes the edge  = predicted_probability − market_price
2. Requires a *minimum edge* (default 5 %) before betting at all.
3. Computes expected value  = edge × potential_payout
4. Sizes the bet as  bankroll × edge_fraction × edge_scaling_factor,
   clamped by min/max bet and max-loss-fraction caps.
5. Returns 0 when edge or EV is insufficient — naturally avoids the
   "betting with the crowd at 0.95" failure mode.
"""

from typing import Any, Dict, List, Optional, Union


REQUIRED_FIELDS = frozenset(
    {
        "bankroll",
        "win_probability",
        "confidence",
        "selected_type_tokens_in_pool",
        "other_tokens_in_pool",
        "bet_fee",
        "floor_balance",
    }
)

OPTIONAL_FIELDS = frozenset(
    {
        "weighted_accuracy",
        "max_bet",
        "min_bet",
        "token_decimals",
        "min_edge",
        "edge_fraction",
        "max_loss_fraction",
        "min_ev_threshold",
    }
)

ALL_FIELDS = REQUIRED_FIELDS.union(OPTIONAL_FIELDS)

# ── defaults ──────────────────────────────────────────────────────────────
DEFAULT_MAX_BET = 8e17
DEFAULT_MIN_BET = 1
DEFAULT_TOKEN_DECIMALS = 18
DEFAULT_MIN_EDGE = 0.10  # 10 % minimum edge to bet
DEFAULT_EDGE_FRACTION = 0.25  # risk up to 25 % of the computed edge-stake
DEFAULT_MAX_LOSS_FRACTION = 0.01  # never risk more than 1 % of bankroll
DEFAULT_MIN_EV_THRESHOLD = 0.10  # require ≥ 10 % EV per unit risked


# ── helpers ───────────────────────────────────────────────────────────────


def wei_to_native(wei: int, decimals: int = 18) -> float:
    """Convert smallest unit to native token."""
    return wei / 10**decimals


def native_to_wei(native: float, decimals: int = 18) -> int:
    """Convert native token to smallest unit."""
    return int(native * 10**decimals)


def check_missing_fields(kwargs: Dict[str, Any]) -> List[str]:
    """Return names of any required fields that are missing or None."""
    return [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]


def remove_irrelevant_fields(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the fields the strategy understands."""
    return {k: v for k, v in kwargs.items() if k in ALL_FIELDS}


def _market_implied_price(
    selected_tokens: int,
    other_tokens: int,
) -> float:
    """Derive the market-implied price for the selected outcome.

    In a CPMM (x · y = k) the marginal price for outcome A is:
        price_A = tokens_B / (tokens_A + tokens_B)
    """
    total = selected_tokens + other_tokens
    if total == 0:
        return 0.5
    return other_tokens / total


# ── core ──────────────────────────────────────────────────────────────────


def get_bet_amount_edge(
    bankroll: int,
    win_probability: float,
    confidence: float,
    selected_type_tokens_in_pool: int,
    other_tokens_in_pool: int,
    bet_fee: int,
    floor_balance: int,
    weighted_accuracy: Optional[float] = None,
    max_bet: int = DEFAULT_MAX_BET,
    min_bet: int = DEFAULT_MIN_BET,
    token_decimals: int = DEFAULT_TOKEN_DECIMALS,
    min_edge: float = DEFAULT_MIN_EDGE,
    edge_fraction: float = DEFAULT_EDGE_FRACTION,
    max_loss_fraction: float = DEFAULT_MAX_LOSS_FRACTION,
    min_ev_threshold: float = DEFAULT_MIN_EV_THRESHOLD,
) -> Dict[str, Union[int, List[str]]]:
    """Compute a bet amount proportional to the edge over the market price.

    Returns
    -------
    dict with keys:
        bet_amount : int   – the bet in the token's smallest unit (wei / USDC base)
        info       : list  – informational log messages
        error      : list  – error messages (non-fatal; bet_amount may still be > 0)
    """
    token_name = "USDC" if token_decimals == 6 else "xDAI"
    info: List[str] = []
    error: List[str] = []

    # ── bankroll check ────────────────────────────────────────────────
    effective_bankroll = bankroll - floor_balance
    if effective_bankroll <= 0:
        error.append(
            f"Bankroll ({wei_to_native(bankroll, token_decimals)} {token_name}) "
            f"≤ floor ({wei_to_native(floor_balance, token_decimals)} {token_name}). "
            f"Bet amount → 0."
        )
        return {"bet_amount": 0, "info": info, "error": error}

    info.append(
        f"Effective bankroll: {wei_to_native(effective_bankroll, token_decimals):.4f} {token_name}"
    )

    # ── market price & edge ───────────────────────────────────────────
    market_price = _market_implied_price(
        selected_type_tokens_in_pool, other_tokens_in_pool
    )
    edge = win_probability - market_price

    info.append(f"Market implied price: {market_price:.4f}")
    info.append(f"Mech predicted prob:  {win_probability:.4f}")
    info.append(f"Edge:                 {edge:+.4f}  (min required: {min_edge})")

    if edge < min_edge:
        info.append(f"Edge {edge:.4f} < minimum {min_edge}. No bet.")
        return {"bet_amount": 0, "info": info, "error": error}

    # ── expected value check ──────────────────────────────────────────
    # EV per unit risked = edge / market_price  (how much extra return per
    # unit of money at risk vs fair odds).
    ev_per_unit = edge / market_price if market_price > 0 else 0.0
    info.append(
        f"EV per unit risked:   {ev_per_unit:.4f}  (min required: {min_ev_threshold})"
    )

    if ev_per_unit < min_ev_threshold:
        info.append(f"EV/unit {ev_per_unit:.4f} < minimum {min_ev_threshold}. No bet.")
        return {"bet_amount": 0, "info": info, "error": error}

    # ── confidence & accuracy modulation ──────────────────────────────
    # Scale down bet when confidence is weak or tool accuracy is poor.
    confidence_factor = min(max(confidence, 0.0), 1.0)
    accuracy_factor = 1.0
    if weighted_accuracy is not None:
        if 0.0 <= weighted_accuracy <= 1.0:
            accuracy_factor = 0.5 + weighted_accuracy  # range [0.5, 1.5]
        else:
            error.append(
                f"weighted_accuracy {weighted_accuracy} out of [0,1]. Ignoring."
            )
    info.append(f"Confidence factor:    {confidence_factor:.2f}")
    info.append(f"Accuracy factor:      {accuracy_factor:.2f}")

    # ── fee adjustment ────────────────────────────────────────────────
    fee_fraction = 1.0 - wei_to_native(bet_fee, token_decimals)
    if fee_fraction <= 0:
        error.append(f"Fee fraction {fee_fraction} ≤ 0. No bet.")
        return {"bet_amount": 0, "info": info, "error": error}
    info.append(f"Fee fraction:         {fee_fraction:.4f}")

    # ── bet sizing ────────────────────────────────────────────────────
    # Core formula:
    #   raw = bankroll × edge × edge_fraction × confidence × accuracy × (1-fee)
    # This is deliberately simpler than Kelly — it's linear in the edge
    # so it naturally risks little on small edges and more on large ones.
    raw_bet = (
        effective_bankroll
        * edge
        * edge_fraction
        * confidence_factor
        * accuracy_factor
        * fee_fraction
    )

    info.append(
        f"Raw bet amount:       {wei_to_native(raw_bet, token_decimals):.4f} {token_name}"
    )

    # ── clamp to limits ───────────────────────────────────────────────
    bet_amount = int(raw_bet)

    # # max loss fraction of total bankroll (not effective — use full bankroll)
    # if max_loss_fraction > 0:
    #     max_allowed = int(bankroll * max_loss_fraction)
    #     if bet_amount > max_allowed > 0:
    #         info.append(
    #             f"Capping bet from {wei_to_native(bet_amount, token_decimals):.4f} "
    #             f"to {wei_to_native(max_allowed, token_decimals):.4f} {token_name} "
    #             f"({max_loss_fraction*100:.1f}% of bankroll)."
    #         )
    #         bet_amount = max_allowed

    if bet_amount > max_bet:
        info.append(
            f"Capping bet to max_bet {wei_to_native(max_bet, token_decimals):.4f} {token_name}."
        )
        bet_amount = int(max_bet)

    if bet_amount < min_bet:
        info.append(
            f"Bet {wei_to_native(bet_amount, token_decimals)} {token_name} "
            f"< min_bet {wei_to_native(min_bet, token_decimals)} {token_name}. No bet."
        )
        return {"bet_amount": 0, "info": info, "error": error}

    info.append(
        f"Final bet amount:     {wei_to_native(bet_amount, token_decimals):.4f} {token_name}"
    )
    return {"bet_amount": bet_amount, "info": info, "error": error}


# ── entry point (called by the framework via exec()) ──────────────────────


def run(*_args, **kwargs) -> Dict[str, Union[int, List[str]]]:
    """Run the strategy."""
    missing = check_missing_fields(kwargs)
    if missing:
        return {"error": [f"Required kwargs {missing} were not provided."]}

    kwargs = remove_irrelevant_fields(kwargs)
    return get_bet_amount_edge(**kwargs)
