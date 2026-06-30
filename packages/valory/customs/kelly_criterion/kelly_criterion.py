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

"""Execution-aware Kelly criterion bet sizing for CLOB and FPMM markets."""

import math
from typing import Any, Dict, List, Optional, Tuple, cast

# --- Required / optional field contracts ---

REQUIRED_FIELDS = frozenset(
    {
        "bankroll",
        "p_yes",
        "market_type",
        "floor_balance",
        "price_yes",
        "price_no",
    }
)

OPTIONAL_FIELDS = frozenset(
    {
        "max_bet",
        "min_bet",
        "n_bets",
        "min_edge",
        "max_edge",
        "min_oracle_prob",
        "fee_per_trade",
        "grid_points",
        "token_decimals",
        "tokens_yes",
        "tokens_no",
        "bet_fee",
        "orderbook_asks_yes",
        "orderbook_asks_no",
        # accepted but NOT consulted in the CLOB sizing path post-PR #971
        # (FOK takers are not share-count-constrained); still populated by
        # decision_receive.py — kept here to avoid breaking those callers.
        "min_order_shares",
    }
)

# --- Defaults ---

DEFAULT_MAX_BET_XDAI = int(8e17)  # 0.8 xDAI
DEFAULT_MAX_BET_USDC = int(5e6)  # 5 USDC
DEFAULT_MIN_BET = 1
DEFAULT_N_BETS = 1
DEFAULT_MIN_EDGE = 0.03
# Optional CLOB-only upper bound on edge. edge = p_oracle - best_ask is
# always <= 1.0, so 1.0 widens the band to the full range = no-op.
DEFAULT_MAX_EDGE = 1.0
DEFAULT_MIN_ORACLE_PROB = 0.5
DEFAULT_FEE_PER_TRADE_XDAI = int(1e16)  # 0.01 xDAI
DEFAULT_FEE_PER_TRADE_USDC = int(1e4)  # 0.01 USDC
DEFAULT_GRID_POINTS = 500
DEFAULT_TOKEN_DECIMALS = 18


# --- Execution models ---


def walk_book(asks: List[Dict[str, str]], spend: float) -> Tuple[float, float]:
    """Walk CLOB ask-side orderbook to simulate a market buy.

    :param asks: ask levels from CLOB, each {"price": str, "size": str}.
    :param spend: maximum amount to spend in native units.
    :return: (cost, shares) tuple.
    """
    if spend <= 0 or not asks:
        return 0.0, 0.0

    remaining = float(spend)
    cost = 0.0
    shares = 0.0

    for level in sorted(asks, key=lambda a: float(a["price"])):
        price = float(level["price"])
        size = float(level["size"])
        if price <= 0 or size <= 0:
            continue

        level_cost = price * size
        if level_cost <= remaining:
            cost += level_cost
            shares += size
            remaining -= level_cost
        else:
            fill_shares = remaining / price
            cost += remaining
            shares += fill_shares
            remaining = 0.0
            break

    return cost, shares


def fpmm_execution(b: float, x: float, y: float, alpha: float) -> Tuple[float, float]:
    """FPMM constant-product AMM execution model.

    cost(b) = b
    shares(b) = alpha * b + x - x * y / (y + alpha * b)

    :param b: bet amount in native units.
    :param x: reserve of the outcome token being bought.
    :param y: reserve of the opposite outcome token.
    :param alpha: fee fraction (1 - venue_fee_rate).
    :return: (cost, shares) tuple.
    """
    if b <= 0 or y <= 0:
        return 0.0, 0.0
    cost = b
    denominator = y + alpha * b
    if denominator <= 0:
        return 0.0, 0.0
    shares = alpha * b + x - x * y / denominator
    return cost, max(shares, 0.0)


# --- Grid search optimizer ---


def optimize_side(  # pylint: disable=too-many-arguments,too-many-locals
    p: float,
    w_bet: float,
    b_min: float,
    b_max: float,
    fee: float,
    grid_points: int,
    market_type: str,
    asks: Optional[List[Dict[str, str]]] = None,
    x: float = 0.0,
    y: float = 0.0,
    alpha: float = 1.0,
) -> Tuple[float, float, float, float]:
    """Grid-search for the spend that maximizes log-growth on one side.

    :param p: oracle probability for this side winning.
    :param w_bet: per-bet bankroll in native units.
    :param b_min: minimum executable spend.
    :param b_max: maximum admissible spend.
    :param fee: per-trade external friction cost.
    :param grid_points: number of candidate points.
    :param market_type: "clob" or "fpmm".
    :param asks: CLOB ask levels (required if market_type="clob").
    :param x: FPMM selected token reserve.
    :param y: FPMM other token reserve.
    :param alpha: FPMM fee fraction.
    :return: (best_spend, best_shares, best_G, G_baseline).
    """
    g_baseline = math.log(w_bet) if w_bet > 0 else -math.inf

    if b_max <= 0 or w_bet <= 0:
        return 0.0, 0.0, g_baseline, g_baseline

    b_min = min(b_min, b_max)
    if grid_points < 2:
        grid_points = 2

    best_spend = 0.0
    best_shares = 0.0
    best_g = g_baseline

    step = (b_max - b_min) / (grid_points - 1)

    for i in range(grid_points):
        b = b_min + i * step

        if market_type == "clob":
            cost, n_shares = walk_book(asks or [], b)
        else:
            cost, n_shares = fpmm_execution(b, x, y, alpha)

        if cost <= 0 or n_shares <= 0:
            continue

        w_win = w_bet - cost + n_shares - fee
        w_lose = w_bet - cost - fee

        if w_win <= 0 or w_lose <= 0:
            continue

        g = p * math.log(w_win) + (1 - p) * math.log(w_lose)

        if g > best_g:
            best_g = g
            best_spend = cost
            best_shares = n_shares

    return best_spend, best_shares, best_g, g_baseline


# --- No-trade result helper ---


def _no_trade(
    info: List[str],
    error: List[str],
    reason: str = "",
) -> Dict[str, Any]:
    """Return a no-trade result."""
    if reason:
        info.append(f"No trade: {reason}")
    return {
        "bet_amount": 0,
        "vote": None,
        "expected_profit": 0,
        "g_improvement": 0.0,
        "info": info,
        "error": error,
    }


# --- Main entry point ---


def run(**kwargs: Any) -> Dict[str, Any]:  # pylint: disable=too-many-locals
    """Run the Kelly criterion strategy.

    :param kwargs: strategy parameters (see REQUIRED_FIELDS / OPTIONAL_FIELDS).
    :return: dict with bet_amount, vote, expected_profit, g_improvement, info, error.
    """
    info: List[str] = []
    error: List[str] = []

    # 1. Validate required fields
    missing = [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]
    if missing:
        return {
            "bet_amount": 0,
            "vote": None,
            "error": [f"Missing required fields: {missing}"],
        }

    # 2. Extract parameters
    bankroll: int = kwargs["bankroll"]
    p_yes: float = kwargs["p_yes"]
    p_no: float = 1.0 - p_yes
    market_type: str = kwargs["market_type"]
    floor_balance: int = kwargs["floor_balance"]
    price_yes: float = kwargs["price_yes"]
    price_no: float = kwargs["price_no"]

    token_decimals: int = kwargs.get("token_decimals", DEFAULT_TOKEN_DECIMALS)
    scale = 10**token_decimals

    default_max_bet = (
        DEFAULT_MAX_BET_USDC if token_decimals == 6 else DEFAULT_MAX_BET_XDAI
    )

    default_fee = (
        DEFAULT_FEE_PER_TRADE_USDC
        if token_decimals == 6
        else DEFAULT_FEE_PER_TRADE_XDAI
    )

    max_bet_wei: int = kwargs.get("max_bet", default_max_bet)
    min_bet_wei: int = kwargs.get("min_bet", DEFAULT_MIN_BET)
    fee_per_trade_wei: int = kwargs.get("fee_per_trade", default_fee)
    n_bets: int = kwargs.get("n_bets", DEFAULT_N_BETS)
    min_edge: float = kwargs.get("min_edge", DEFAULT_MIN_EDGE)
    max_edge: float = kwargs.get("max_edge", DEFAULT_MAX_EDGE)
    min_oracle_prob: float = kwargs.get("min_oracle_prob", DEFAULT_MIN_ORACLE_PROB)
    grid_points: int = kwargs.get("grid_points", DEFAULT_GRID_POINTS)

    # Convert to native units
    max_bet = max_bet_wei / scale
    min_bet = min_bet_wei / scale
    fee_per_trade = fee_per_trade_wei / scale
    w_total = bankroll / scale
    floor = floor_balance / scale

    token_name = "USDC" if token_decimals == 6 else "xDAI"
    info.append(f"Bankroll: {w_total} {token_name}, floor: {floor} {token_name}")
    info.append(
        f"max_bet: {max_bet}, n_bets: {n_bets}, "
        f"min_edge: {min_edge}, max_edge: {max_edge}"
    )
    info.append(f"market_type: {market_type}, p_yes: {p_yes}")

    # Reject an inverted edge band up front: min_edge > max_edge makes the
    # CLOB pre-filter unsatisfiable, which would silently skip every bet.
    if min_edge > max_edge:
        error.append(
            f"min_edge ({min_edge}) > max_edge ({max_edge}): no valid edge band"
        )
        return _no_trade(info, error)

    # 3. Compute effective wealth
    w = w_total - floor
    if w <= 0:
        return _no_trade(info, error, f"Bankroll ({w_total}) <= floor ({floor})")

    # Per-bet bankroll
    w_bet = min(n_bets * max_bet, w)
    info.append(f"W_bet (per-bet bankroll): {w_bet} {token_name}")

    # 4. Validate inputs
    if not (0 < p_yes < 1):
        error.append(f"Invalid p_yes: {p_yes}")
        return _no_trade(info, error)

    # 5. Evaluate BOTH sides independently
    sides = [
        {"label": "yes", "vote": 0, "p": p_yes, "price": price_yes},
        {"label": "no", "vote": 1, "p": p_no, "price": price_no},
    ]

    best_result: Optional[Dict[str, Any]] = None
    all_rejections: List[str] = []
    bet_fee_wei: int = kwargs.get("bet_fee", 0)
    alpha = 1.0 - (bet_fee_wei / scale) if market_type == "fpmm" else 1.0

    for side in sides:
        label = side["label"]
        # Side dict mixes value types; cast at access site for arithmetic.
        p = cast(float, side["p"])
        price = cast(float, side["price"])

        # Filter on min_oracle_prob — skip sides whose oracle prob is below the threshold.
        if min_oracle_prob > 0 and p < min_oracle_prob:
            msg = f"{label}: oracle prob {p:.3f} < min_oracle_prob {min_oracle_prob}"
            info.append(msg)
            all_rejections.append(msg)
            continue

        # Determine execution model inputs for this side
        if market_type == "clob":
            asks_key = (
                "orderbook_asks_yes" if side["vote"] == 0 else "orderbook_asks_no"
            )
            asks = kwargs.get(asks_key)
            if not asks:
                msg = f"{label}: no orderbook asks available ({asks_key})"
                info.append(msg)
                all_rejections.append(msg)
                continue

            sorted_asks = sorted(asks, key=lambda a: float(a["price"]))
            best_ask_price = float(sorted_asks[0]["price"])

            # No venue-minimum floor for CLOB: ``min_order_size`` (~5 shares)
            # is a maker/limit constraint, not enforced on the FOK *taker*
            # orders Trader places (USD depth checked only). See PR #971.
            b_min_side = min_bet
            x_native, y_native = 0.0, 0.0

            # CLOB pre-filter: quick edge check against best ask. Edge must
            # fall inside the [min_edge, max_edge] band; defaults
            # (DEFAULT_MIN_EDGE, DEFAULT_MAX_EDGE) reduce to the original
            # floor-only check.
            edge_best_ask = p - best_ask_price
            if not min_edge <= edge_best_ask <= max_edge:
                if edge_best_ask < min_edge:
                    msg = (
                        f"{label}: edge vs best_ask "
                        f"{edge_best_ask:+.4f} < min_edge {min_edge}"
                    )
                else:
                    msg = (
                        f"{label}: edge vs best_ask "
                        f"{edge_best_ask:+.4f} > max_edge {max_edge}"
                    )
                info.append(msg)
                all_rejections.append(msg)
                continue

        else:  # fpmm
            asks = None
            b_min_side = min_bet
            tokens_yes = kwargs.get("tokens_yes", 0) / scale
            tokens_no = kwargs.get("tokens_no", 0) / scale
            if side["vote"] == 0:
                x_native, y_native = tokens_yes, tokens_no
            else:
                x_native, y_native = tokens_no, tokens_yes

            # FPMM edge filter: use market price
            edge = p - price
            if edge < min_edge:
                msg = f"{label}: edge {edge:+.4f} < min_edge {min_edge}"
                info.append(msg)
                all_rejections.append(msg)
                continue

        # Run grid search
        best_spend, best_shares, best_g, g_baseline = optimize_side(
            p=p,
            w_bet=w_bet,
            b_min=b_min_side,
            b_max=max_bet,
            fee=fee_per_trade,
            grid_points=grid_points,
            market_type=market_type,
            asks=asks,
            x=x_native,
            y=y_native,
            alpha=alpha,
        )

        # True edge: oracle probability minus actual execution price (VWAP)
        if market_type == "clob" and best_shares > 0:
            vwap = best_spend / best_shares
            edge = p - vwap
        else:
            vwap = price
            edge = p - price

        g_improvement = best_g - g_baseline
        info.append(
            f"{label}: spend={best_spend:.4f}, shares={best_shares:.4f}, "
            f"vwap={vwap:.4f}, edge={edge:+.4f}, "
            f"G_improvement={g_improvement:.6f}"
        )

        if market_type == "clob":
            # The book genuinely cannot fill (empty / all zero-price /
            # invalid): keep an explicit signal so a no-bet on a high-edge
            # market is not mistaken for a legitimately unprofitable one.
            _, depth_shares = walk_book(sorted_asks, max_bet)
            if depth_shares <= 0:
                msg = (
                    f"{label}: book filled to 0 at all grid points "
                    f"(thin or invalid)"
                )
                info.append(msg)
                all_rejections.append(msg)
                continue

            # ``b_min_side`` only sets the requested grid point; ``walk_book``
            # caps the actual fill cost to available depth, so a book thinner
            # than ``min_bet`` would otherwise leak a sub-floor order through.
            if 0 < best_spend < b_min_side:
                msg = (
                    f"{label}: fill cost {best_spend:.4f} < min_bet "
                    f"{b_min_side:.4f} (insufficient book depth)"
                )
                info.append(msg)
                all_rejections.append(msg)
                continue

        if best_spend > 0 and g_improvement > 0:
            if (  # pragma: no branch — first side always sets best_result
                best_result is None or g_improvement > best_result["g_improvement"]
            ):
                best_result = {
                    "spend": best_spend,
                    "shares": best_shares,
                    "g_improvement": g_improvement,
                    "vote": side["vote"],
                    "label": label,
                    "edge": edge,
                    "vwap": vwap,
                    "p": p,
                }

    # 6. Return result
    if best_result is None:
        reason = (
            "; ".join(all_rejections)
            if all_rejections
            else "no bet improves log-growth"
        )
        return _no_trade(info, error, reason)

    bet_amount_wei = int(best_result["spend"] * scale)
    expected_profit = (
        best_result["p"] * best_result["shares"] - best_result["spend"] - fee_per_trade
    )
    expected_profit_wei = int(expected_profit * scale)

    info.append(
        f"Selected {best_result['label']}: "
        f"bet={best_result['spend']:.4f} {token_name}, "
        f"shares={best_result['shares']:.4f}, "
        f"expected_profit={expected_profit:.6f} {token_name}, "
        f"G_improvement={best_result['g_improvement']:.6f}"
    )

    return {
        "bet_amount": bet_amount_wei,
        "vote": best_result["vote"],
        "expected_profit": expected_profit_wei,
        "g_improvement": best_result["g_improvement"],
        "info": info,
        "error": error,
    }
