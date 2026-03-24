# Unified Kelly Criterion Implementation Plan

## 1. Problem Statement

### 1.1 What's Wrong Today

The trader has two Kelly criterion strategies, both using an **FPMM-derived quadratic formula** that assumes constant-product AMM pool mechanics. This is correct for Omen (an FPMM-based market) but fundamentally wrong for Polymarket (a CLOB-based market).

**The FPMM Kelly formula** (`kelly_criterion_no_conf.py` line 84-118):
```python
numerator = (
    -4 * x**2 * y
    + b * y**2 * p * f
    + 2 * b * x * y * p * f
    + b * x**2 * p * f
    - 2 * b * y**2 * f
    - 2 * b * x * y * f
    + (...)** (1 / 2)
)
denominator = 2 * (x**2 * f - y**2 * f)
kelly_bet_amount = numerator / denominator
```

This formula takes `x` (selected tokens in pool) and `y` (other tokens in pool) as inputs. For Polymarket CLOB markets, these pool reserves don't exist — they are fabricated from `liquidity * price * 1e6`, producing:

- **Negative fractions** on 73% of Polymarket markets (all with price < 0.48) — the agent refuses to bet
- **Wrong sizing** on the remaining 27% — underbets by 5-95%
- **Validated example**: real trader bet $1.43 where correct CLOB Kelly recommends $2.50 (43% underbetting)

**The profitability check** (`decision_receive.py` line 521-580) for Polymarket uses mid-price to estimate shares:
```python
num_shares_predicted_vote = net_bet_amount / market_probability_for_selected_vote
```
This ignores orderbook depth — a $5 market buy doesn't execute at mid-price; it walks multiple ask levels with increasing slippage.

### 1.2 What We're Building

A single, unified Kelly strategy that:
1. Uses **numerical grid-search** over log-utility instead of a closed-form quadratic
2. Is **execution-aware**: walks the real CLOB orderbook for Polymarket, uses constant-product AMM formula for Omen
3. Has **no-trade always admissible**: if no executable bet beats `log(W_bet)`, skip
4. Controls risk via `n_bets` (bankroll depth) instead of post-hoc `bet_kelly_fraction` multipliers
5. **Strategy decides the side**: receives `p_yes` and evaluates both YES and NO independently, returning the optimal side. The current hardcoded side selection (`PredictionResponse.vote = int(p_no > p_yes)`) is removed from the decision path.

Also:
- Replace `bet_amount_per_threshold` with a simple **fixed bet sizing** strategy
- Remove dead side-selection code from `PredictionResponse` and all downstream consumers

### 1.3 Sources of Truth

| Source | What it provides |
|--------|-----------------|
| [`kelly_poly` PR #5](https://github.com/jmoreira-valory/kelly_poly/pull/5) | Reference algorithm (`final_kelly.py`) and spec (`FINAL_KELLY.md`) |
| [trader PR #879](https://github.com/valory-xyz/trader/pull/879) | VWAP/orderbook fetching pattern for polymarket_client connection |

---

## 2. Architecture Overview

### 2.1 Current Data Flow

```
MechResponse (p_yes, confidence)
    │
    ▼
DecisionReceiveBehaviour._is_profitable()
    │
    ├── _get_bet_sample_info() ──► pool token amounts (x, y)
    │
    ├── get_bet_amount() ──► downloads strategy, passes kwargs ──► strategy.run()
    │   │                                                              │
    │   │   kwargs: bankroll, win_probability, confidence,             │
    │   │           selected_type_tokens_in_pool (x),                  │
    │   │           other_tokens_in_pool (y), bet_fee,                 │
    │   │           weighted_accuracy, bet_kelly_fraction               │
    │   │                                                              │
    │   ◄── returns: {"bet_amount": int} ◄─────────────────────────────┘
    │
    ├── [Omen]  _calc_binary_shares() ──► shares from constant-product
    │           potential_net_profit = shares - bet - threshold
    │
    ├── [Poly]  shares = bet / mid_price  ◄── WRONG: ignores orderbook depth
    │           expected_profit = p * shares - bet - mech_costs
    │
    ▼
(is_profitable, bet_amount) returned
```

### 2.2 New Data Flow

```
MechResponse (p_yes, p_no, confidence)
    │
    │   NOTE: p_yes/p_no passed directly to strategy.
    │   PredictionResponse.vote is NO LONGER used for side selection.
    │   The strategy decides the side.
    │
    ▼
DecisionReceiveBehaviour._is_profitable()
    │
    │   ┌─── Venue-specific data gathering ───────────────────────────┐
    │   │                                                             │
    │   │ [Polymarket (CLOB)]:                                        │
    │   │   market_type = "clob"                                      │
    │   │   _fetch_orderbook(yes_token_id) ──► orderbook_asks_yes     │
    │   │   _fetch_orderbook(no_token_id)  ──► orderbook_asks_no      │
    │   │   price_yes = bet.outcomeTokenMarginalPrices[0]             │
    │   │   price_no  = bet.outcomeTokenMarginalPrices[1]             │
    │   │   min_order_shares = bet.min_order_shares                   │
    │   │                                                             │
    │   │ [Omen (FPMM)]:                                              │
    │   │   market_type = "fpmm"                                      │
    │   │   tokens_yes = bet.outcomeTokenAmounts[0]                   │
    │   │   tokens_no  = bet.outcomeTokenAmounts[1]                   │
    │   │   price_yes  = bet.outcomeTokenMarginalPrices[0]            │
    │   │   price_no   = bet.outcomeTokenMarginalPrices[1]            │
    │   │   bet_fee    = bet.fee (venue fee → alpha in FPMM model)    │
    │   │                                                             │
    │   └─────────────────────────────────────────────────────────────┘
    │
    ├── get_bet_amount() ──► strategy.run()
    │   │                        │
    │   │   Common kwargs:       │   Strategy now does EVERYTHING:
    │   │     p_yes,             │   - evaluates BOTH sides independently
    │   │     market_type,       │   - edge filtering per side
    │   │     price_yes,         │   - grid search over bet sizes
    │   │     price_no,          │   - execution simulation (CLOB or FPMM)
    │   │     n_bets, ...        │   - log-growth comparison vs no-trade
    │   │                        │   - picks side with highest G_improvement
    │   │   CLOB-only:           │
    │   │     orderbook_asks_yes,│
    │   │     orderbook_asks_no, │
    │   │     min_order_shares,  │
    │   │                        │
    │   │   FPMM-only:           │
    │   │     tokens_yes,        │
    │   │     tokens_no,         │
    │   │     bet_fee,           │
    │   │                        │
    │   ◄── returns: {           │
    │         "bet_amount": int, ◄──────────────────────────────────────┘
    │         "vote": int,            ◄── 0=YES, 1=NO (strategy decides!)
    │         "expected_profit": int,
    │         "g_improvement": float,
    │       }
    │
    ├── [Kelly] If bet_amount > 0, trust the strategy
    │           vote from strategy overrides into DecisionReceivePayload
    │           Only apply: rebet check (position management)
    │
    ├── [fixed_bet] Returns configured amount + vote (higher-prob side)
    │
    ▼
(is_profitable, bet_amount, vote) returned
    │
    ▼
DecisionReceivePayload(vote=strategy_vote)
    │
    ▼
synchronized_data.vote ──► outcome_index ──► bet placement
```

### 2.3 Inheritance Chain (relevant for orderbook fetching)

```
DecisionReceiveBehaviour
    └── StorageManagerBehaviour
        └── DecisionMakerBaseBehaviour  (defines get_bet_amount, execute_strategy)
            └── BetsManagerBehaviour    (defines send_polymarket_connection_request)
                └── BaseBehaviour
```

`send_polymarket_connection_request` is available to `DecisionReceiveBehaviour` through this chain.

---

## 3. Detailed Implementation

### 3.1 New Strategy Package: `packages/valory/customs/kelly_criterion/`

#### 3.1.1 Package Structure

```
packages/valory/customs/kelly_criterion/
├── __init__.py                    # Copyright header + docstring
├── component.yaml                 # entry_point: kelly_criterion.py, callable: run
├── kelly_criterion.py             # Main strategy implementation
└── tests/
    ├── __init__.py
    └── test_kelly_criterion.py    # Comprehensive unit tests
```

#### 3.1.2 `component.yaml`

```yaml
name: kelly_criterion
author: valory
version: 0.1.0
type: custom
description: Execution-aware Kelly criterion bet sizing for CLOB and FPMM markets
license: Apache-2.0
entry_point: kelly_criterion.py
callable: run
```

#### 3.1.3 `kelly_criterion.py` — Full Design

**Field definitions:**

```python
REQUIRED_FIELDS = frozenset({
    "bankroll",          # int (wei) — current wallet balance
    "p_yes",             # float [0,1] — oracle's probability for YES
    "market_type",       # str — "clob" or "fpmm"
    "floor_balance",     # int (wei) — minimum balance to keep in wallet
    "price_yes",         # float — current market price for YES (FPMM edge filter; CLOB uses best_ask instead)
    "price_no",          # float — current market price for NO (FPMM edge filter; CLOB uses best_ask instead)
})

OPTIONAL_FIELDS = frozenset({
    # Kelly hyperparameters (have defaults)
    "max_bet",              # int (wei) — hard cap per trade. Default: 5e6 (5 USDC) or 8e17 (0.8 xDAI)
    "min_bet",              # int (wei) — minimum executable bet. Default: 1
    "n_bets",               # int — bankroll depth parameter. Default: 1
    "min_edge",             # float — minimum p - market_price to bet. Default: 0.03
    "min_oracle_prob",      # float — minimum oracle prob for side. Default: 0.5
    "fee_per_trade",        # float (native units) — gas + mech cost. Default: 0.01
    "grid_points",          # int — grid search resolution. Default: 500
    "token_decimals",       # int — 6 for USDC, 18 for xDAI. Default: 18

    # FPMM-specific (used when market_type="fpmm")
    # For FPMM the strategy receives BOTH pool sides so it can evaluate both directions.
    # outcomeTokenAmounts[0] = YES tokens, outcomeTokenAmounts[1] = NO tokens.
    "tokens_yes",           # int (wei) — YES outcome tokens in pool
    "tokens_no",            # int (wei) — NO outcome tokens in pool
    "bet_fee",              # int (wei) — FPMM market fee

    # CLOB-specific (used when market_type="clob")
    # Strategy receives BOTH orderbooks so it can evaluate both sides independently.
    "orderbook_asks_yes",   # List[Dict[str, str]] — ask levels for YES token
    "orderbook_asks_no",    # List[Dict[str, str]] — ask levels for NO token
    "min_order_shares",     # float — venue-provided min order size in shares
})
```

**Core algorithm (pseudocode with line-by-line detail):**

```python
import math
from typing import Any, Dict, List, Optional, Tuple, Union

# --- Constants ---
DEFAULT_MAX_BET_XDAI = int(8e17)   # 0.8 xDAI
DEFAULT_MAX_BET_USDC = int(5e6)    # 5 USDC
DEFAULT_MIN_BET = 1
DEFAULT_N_BETS = 1
DEFAULT_MIN_EDGE = 0.03
DEFAULT_MIN_ORACLE_PROB = 0.5
DEFAULT_FEE_PER_TRADE = 0.01
DEFAULT_GRID_POINTS = 500
DEFAULT_TOKEN_DECIMALS = 18

# --- Execution models ---

def walk_book(asks: List[Dict[str, str]], spend: float) -> Tuple[float, float]:
    """Walk CLOB ask-side orderbook to simulate a market buy.

    Parameters
    ----------
    asks : list of {"price": str, "size": str}
        Ask levels from CLOB. Must be sorted by price ascending.
    spend : float
        Maximum USDC to spend (in native units, e.g., 5.0).

    Returns
    -------
    (cost, shares) : tuple of float
        cost: actual USDC spent
        shares: total shares received
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


def fpmm_execution(
    b: float, x: float, y: float, alpha: float
) -> Tuple[float, float]:
    """FPMM constant-product AMM execution model.

    From FINAL_KELLY.md:
        cost(b) = b
        shares(b) = alpha * b + x - x*y / (y + alpha*b)

    Parameters
    ----------
    b : float
        Bet amount in native units.
    x : float
        Current reserve of the outcome token being bought (native units).
    y : float
        Current reserve of the opposite outcome token (native units).
    alpha : float
        Fee fraction: 1 - (bet_fee / 1e{decimals}). E.g., if bet_fee is 2%,
        alpha = 0.98.
        This is the venue/market fee term for Omen and is part of the execution
        model itself. It must not be counted again via `fee_per_trade`.

    Returns
    -------
    (cost, shares) : tuple of float
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

def optimize_side(
    p: float,
    W_bet: float,
    b_min: float,
    b_max: float,
    fee: float,
    grid_points: int,
    market_type: str,
    # CLOB args
    asks: Optional[List[Dict[str, str]]] = None,
    # FPMM args
    x: float = 0.0,
    y: float = 0.0,
    alpha: float = 1.0,
) -> Tuple[float, float, float, float]:
    """Grid-search for the spend that maximizes log-growth on one side.

    Implements:
        max(log(W_bet),  max over b_min <= b <= b_max of
            p * log(W_bet - cost(b) + shares(b) - fee)
            + (1 - p) * log(W_bet - cost(b) - fee))

    Parameters
    ----------
    p : float
        Oracle probability for this side winning.
    W_bet : float
        Per-bet bankroll (native units). Formed as min(n_bets * max_bet, W).
    b_min : float
        Minimum executable spend (native units).
    b_max : float
        Maximum admissible spend (native units).
    fee : float
        Per-trade external friction cost (native units), e.g. mech costs and,
        in future, gas costs. This is separate from venue/market fees:
        - Omen market fee is already modeled in `shares(b)` via `alpha`
        - Polymarket market fee is currently 0 in trader
        Therefore `fee` / `fee_per_trade` must not include the venue fee again.
    grid_points : int
        Number of candidate points in the grid.
    market_type : str
        "clob" or "fpmm".
    asks : list, optional
        CLOB ask levels (required if market_type="clob").
    x, y, alpha : float
        FPMM pool parameters (required if market_type="fpmm").

    Returns
    -------
    (best_spend, best_shares, best_G, G_baseline) : tuple of float
    """
    G_baseline = math.log(W_bet) if W_bet > 0 else -math.inf

    if b_max <= 0 or W_bet <= 0:
        return 0.0, 0.0, G_baseline, G_baseline

    b_min = min(b_min, b_max)
    if grid_points < 2:
        grid_points = 2

    best_spend = 0.0
    best_shares = 0.0
    best_G = G_baseline

    step = (b_max - b_min) / (grid_points - 1)

    for i in range(grid_points):
        b = b_min + i * step

        if market_type == "clob":
            cost, n_shares = walk_book(asks or [], b)
        else:  # fpmm
            cost, n_shares = fpmm_execution(b, x, y, alpha)

        if cost <= 0 or n_shares <= 0:
            continue

        W_win = W_bet - cost + n_shares - fee
        W_lose = W_bet - cost - fee

        if W_win <= 0 or W_lose <= 0:
            continue

        G = p * math.log(W_win) + (1 - p) * math.log(W_lose)

        if G > best_G:
            best_G = G
            best_spend = cost
            best_shares = n_shares

    return best_spend, best_shares, best_G, G_baseline


# --- Main entry point ---

def run(**kwargs) -> Dict[str, Any]:
    """Run the Kelly criterion strategy.

    This is the callable invoked by the decision maker via exec().

    Returns
    -------
    dict with keys:
        bet_amount : int (wei) — 0 means no trade
        expected_profit : int (wei) — expected profit computed with the exact
            same `shares(b)` and `fee` model used inside the Kelly objective.
            Venue/market fees must already be reflected in `shares(b)` where
            applicable; `fee_per_trade` is for external friction only.
        g_improvement : float — log-growth improvement over no-trade
        info : list of str — informational log messages
        error : list of str — error messages
    """
    info = []
    error = []

    # --- 1. Validate required fields ---
    missing = [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]
    if missing:
        return {"bet_amount": 0, "vote": None, "error": [f"Missing required fields: {missing}"]}

    # --- 2. Extract parameters ---
    bankroll = kwargs["bankroll"]            # int, wei
    p_yes = kwargs["p_yes"]                  # float [0,1]
    p_no = 1.0 - p_yes
    market_type = kwargs["market_type"]      # "clob" or "fpmm"
    floor_balance = kwargs["floor_balance"]  # int, wei
    price_yes = kwargs["price_yes"]          # float
    price_no = kwargs["price_no"]            # float

    token_decimals = kwargs.get("token_decimals", DEFAULT_TOKEN_DECIMALS)
    scale = 10 ** token_decimals

    default_max_bet = DEFAULT_MAX_BET_USDC if token_decimals == 6 else DEFAULT_MAX_BET_XDAI

    max_bet_wei = kwargs.get("max_bet", default_max_bet)
    min_bet_wei = kwargs.get("min_bet", DEFAULT_MIN_BET)
    n_bets = kwargs.get("n_bets", DEFAULT_N_BETS)
    min_edge = kwargs.get("min_edge", DEFAULT_MIN_EDGE)
    min_oracle_prob = kwargs.get("min_oracle_prob", DEFAULT_MIN_ORACLE_PROB)
    fee_per_trade = kwargs.get("fee_per_trade", DEFAULT_FEE_PER_TRADE)
    grid_points = kwargs.get("grid_points", DEFAULT_GRID_POINTS)

    # Convert to native units
    max_bet = max_bet_wei / scale
    min_bet = min_bet_wei / scale
    W_total = bankroll / scale
    floor = floor_balance / scale

    token_name = "USDC" if token_decimals == 6 else "xDAI"
    info.append(f"Bankroll: {W_total} {token_name}, floor: {floor} {token_name}")
    info.append(f"max_bet: {max_bet}, n_bets: {n_bets}, min_edge: {min_edge}")
    info.append(f"market_type: {market_type}, p_yes: {p_yes}")

    # --- 3. Compute effective wealth ---
    W = W_total - floor
    if W <= 0:
        info.append(f"Bankroll ({W_total}) <= floor ({floor}). No bet.")
        return {"bet_amount": 0, "vote": None, "expected_profit": 0,
                "g_improvement": 0.0, "info": info, "error": error}

    # Per-bet bankroll: W_bet = min(n_bets * max_bet, W_total - floor)
    W_bet = min(n_bets * max_bet, W_total - floor)
    info.append(f"W_bet (per-bet bankroll): {W_bet} {token_name}")

    # --- 4. Validate inputs ---
    if not (0 < p_yes < 1):
        error.append(f"Invalid p_yes: {p_yes}")
        return {"bet_amount": 0, "vote": None, "expected_profit": 0,
                "g_improvement": 0.0, "info": info, "error": error}

    # --- 5. Evaluate BOTH sides independently ---
    # The strategy decides the side — not the mech's vote.
    # vote=0 means YES, vote=1 means NO.
    sides = [
        {"label": "yes", "vote": 0, "p": p_yes, "price": price_yes},
        {"label": "no",  "vote": 1, "p": p_no,  "price": price_no},
    ]

    best_result = None
    all_rejections = []
    bet_fee_wei = kwargs.get("bet_fee", 0)
    alpha = 1.0 - (bet_fee_wei / scale) if market_type == "fpmm" else 1.0

    for side in sides:
        label = side["label"]
        p = side["p"]
        price = side["price"]

        # Filter: min_oracle_prob (applied before venue-specific logic)
        if min_oracle_prob > 0 and p < min_oracle_prob:
            msg = f"{label}: oracle prob {p:.3f} < min_oracle_prob {min_oracle_prob}"
            info.append(msg)
            all_rejections.append(msg)
            continue

        # Determine execution model inputs for this side
        if market_type == "clob":
            asks_key = "orderbook_asks_yes" if side["vote"] == 0 else "orderbook_asks_no"
            asks = kwargs.get(asks_key)
            if not asks:
                msg = f"{label}: no orderbook asks available ({asks_key})"
                info.append(msg)
                all_rejections.append(msg)
                continue

            sorted_asks = sorted(asks, key=lambda a: float(a["price"]))
            best_ask_price = float(sorted_asks[0]["price"])
            min_order_shares = float(kwargs.get("min_order_shares", 5.0))
            best_ask_size = float(sorted_asks[0]["size"])
            if best_ask_size >= min_order_shares:
                venue_min_side = min_order_shares * best_ask_price
            else:
                remaining_shares = min_order_shares
                venue_min_side = 0.0
                for level in sorted_asks:
                    price = float(level["price"])
                    size = float(level["size"])
                    if price <= 0 or size <= 0:
                        continue
                    fill = min(size, remaining_shares)
                    venue_min_side += fill * price
                    remaining_shares -= fill
                    if remaining_shares <= 0:
                        break
                if remaining_shares > 0:
                    msg = (
                        f"{label}: insufficient book depth to fill "
                        f"min_order_shares={min_order_shares}"
                    )
                    info.append(msg)
                    all_rejections.append(msg)
                    continue

            b_min_side = max(min_bet, venue_min_side)
            x_native, y_native = 0.0, 0.0

            # CLOB pre-filter: quick edge check against best ask (cheapest level).
            # The real edge (against VWAP) will be <= this, so if this fails
            # the real edge would also fail. Matches final_kelly.py.
            edge_best_ask = p - best_ask_price
            if edge_best_ask < min_edge:
                msg = f"{label}: edge vs best_ask {edge_best_ask:+.4f} < min_edge {min_edge}"
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

            # FPMM edge filter: use market price (no orderbook)
            edge = p - price
            if edge < min_edge:
                msg = f"{label}: edge {edge:+.4f} < min_edge {min_edge}"
                info.append(msg)
                all_rejections.append(msg)
                continue

        # Run grid search
        best_spend, best_shares, best_G, G_baseline = optimize_side(
            p=p, W_bet=W_bet, b_min=b_min_side, b_max=max_bet,
            fee=fee_per_trade, grid_points=grid_points,
            market_type=market_type, asks=asks,
            x=x_native, y=y_native, alpha=alpha,
        )

        # True edge: oracle probability minus actual execution price (VWAP)
        # For CLOB this replaces the best-ask pre-filter with the real number.
        # For FPMM this is p - price (same as pre-filter, since no orderbook).
        if market_type == "clob" and best_shares > 0:
            vwap = best_spend / best_shares
            edge = p - vwap
        else:
            vwap = price
            edge = p - price

        G_improvement = best_G - G_baseline
        info.append(
            f"{label}: spend={best_spend:.4f}, shares={best_shares:.4f}, "
            f"vwap={vwap:.4f}, edge={edge:+.4f}, "
            f"G_improvement={G_improvement:.6f}"
        )

        if best_spend > 0 and G_improvement > 0:
            if best_result is None or G_improvement > best_result["g_improvement"]:
                best_result = {
                    "spend": best_spend,
                    "shares": best_shares,
                    "g_improvement": G_improvement,
                    "vote": side["vote"],
                    "label": label,
                    "edge": edge,
                    "vwap": vwap,
                    "p": p,
                }

    # --- 6. Return result ---
    if best_result is None:
        reason = "; ".join(all_rejections) if all_rejections else "no bet improves log-growth"
        info.append(f"No trade: {reason}")
        return {"bet_amount": 0, "vote": None, "expected_profit": 0,
                "g_improvement": 0.0, "info": info, "error": error}

    bet_amount_wei = int(best_result["spend"] * scale)
    # Expected profit must use the same accounting as the Kelly objective:
    #   expected_profit = p * shares(b_opt) - b_opt - fee_per_trade
    #
    # where:
    # - `shares(b_opt)` already includes venue-specific execution and venue fees
    #   (for Omen, via alpha in the FPMM execution model)
    # - `b_opt` / `best_result["spend"]` is the modeled gross spend
    # - `fee_per_trade` is external friction only (mech costs today, gas later),
    #   and must not include venue/market fees again
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
        "vote": best_result["vote"],       # 0=YES, 1=NO — strategy decides!
        "expected_profit": expected_profit_wei,
        "g_improvement": best_result["g_improvement"],
        "info": info,
        "error": error,
    }
```

#### 3.1.4 Hyperparameter Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_bet` | int (wei) | 5e6 USDC / 8e17 xDAI | Hard cap per trade. Primary risk control. |
| `n_bets` | int | 1 | Bankroll depth: `W_bet = min(n_bets * max_bet, W)`. Higher = more willing to use full `max_bet`. |
| `min_edge` | float | 0.03 | Minimum `p - market_price` to consider betting. Protects against oracle noise. |
| `min_oracle_prob` | float | 0.5 | Minimum oracle prob for a side. Rejects "edge-only" bets where oracle still thinks side is unlikely. |
| `fee_per_trade` | float | 0.01 | External friction only in native units: mech costs today, optionally gas later. Deducted in both win/lose states. Do not include venue/market fee here. |
| `grid_points` | int | 500 | Grid resolution for optimizer. 500 is production-grade. |
| `min_order_shares` | float | 5.0 is the documented Polymarket example/common value, not a guaranteed invariant | Venue-provided minimum order size in shares. Read it from market/orderbook data instead of hardcoding it. |

### 3.2 Polymarket Connection: Orderbook Fetching

#### 3.2.1 `request_types.py`

**File:** `packages/valory/connections/polymarket_client/request_types.py`

**Change:** Add one enum value:

```python
class RequestType(Enum):
    """Enum for supported Polymarket request types."""

    PLACE_BET = "place_bet"
    FETCH_MARKETS = "fetch_markets"
    FETCH_MARKET = "fetch_market"
    GET_POSITIONS = "get_positions"
    FETCH_ALL_POSITIONS = "fetch_all_positions"
    GET_TRADES = "get_trades"
    FETCH_ALL_TRADES = "fetch_all_trades"
    REDEEM_POSITIONS = "redeem_positions"
    SET_APPROVAL = "set_approval"
    CHECK_APPROVAL = "check_approval"
    FETCH_ORDER_BOOK = "fetch_order_book"  # <-- NEW
```

#### 3.2.2 `connection.py`

**File:** `packages/valory/connections/polymarket_client/connection.py`

**Add handler method** (follow existing patterns like `_fetch_market`):

```python
def _fetch_order_book(self, token_id: str) -> Tuple[Any, Optional[str]]:
    """Fetch the order book for a given token from the CLOB.

    :param token_id: The CLOB token ID for the outcome.
    :return: Tuple of (order_book_dict, error_string).
    """
    try:
        order_book = self.client.get_order_book(token_id)
        asks = [
            {"price": str(a.price), "size": str(a.size)}
            for a in (order_book.asks or [])
        ]
        bids = [
            {"price": str(b.price), "size": str(b.size)}
            for b in (order_book.bids or [])
        ]
        return {"asks": asks, "bids": bids}, None
    except Exception as e:  # pylint: disable=broad-except
        return None, str(e)
```

**Register in `_route_request()`** — add to the request function mapping dict:

```python
RequestType.FETCH_ORDER_BOOK: self._fetch_order_book,
```

**Connection handler dispatch** — the existing `_route_request` method dispatches based on `request_type` string. The handler receives `params` dict. For `FETCH_ORDER_BOOK`, params must include `{"token_id": "<clob_token_id>"}`.

#### 3.2.3 Market metadata plumbing

To avoid hardcoding venue execution constraints inside the strategy, also extend the
Polymarket market ingestion path so `Bet` stores:

- `min_order_shares: Optional[float]`

Populate it from Gamma/CLOB market metadata when `Bet` objects are built, alongside
`outcome_token_ids`. The Kelly strategy should consume this value through
`get_bet_amount(..., min_order_shares=...)`.

### 3.3 Decision Receive Integration

#### 3.3.1 New method: `_fetch_orderbook()`

**File:** `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py`

Add a new generator method to `DecisionReceiveBehaviour`:

```python
def _fetch_orderbook(
    self, token_id: str
) -> Generator[None, None, Optional[Dict[str, Any]]]:
    """Fetch the orderbook for a CLOB token.

    :param token_id: The CLOB token ID.
    :return: Dict with "asks" and "bids" keys, or None on failure.
    """
    payload = {
        "request_type": RequestType.FETCH_ORDER_BOOK.value,
        "params": {"token_id": token_id},
    }
    response = yield from self.send_polymarket_connection_request(payload)
    if response is None:
        self.context.logger.warning("Failed to fetch orderbook: no response")
        return None
    if isinstance(response, dict) and response.get("error"):
        self.context.logger.warning(
            f"Failed to fetch orderbook: {response['error']}"
        )
        return None
    return response
```

**Import needed:** Add `RequestType` import from `packages.valory.connections.polymarket_client.request_types`.

#### 3.3.2 Changes to `_is_profitable()`

**Key change**: `_is_profitable()` no longer uses `prediction_response.vote` for side selection.
The strategy decides the side. `prediction_response.vote` and `prediction_response.win_probability`
are dead code — see Phase 3.7 for removal.

**Before `get_bet_amount()` call — gather market data for BOTH sides:**

```python
market_type = "clob" if self.params.is_running_on_polymarket else "fpmm"
orderbook_asks_yes = None
orderbook_asks_no = None
min_order_shares = 0.0

prices = bet.outcomeTokenMarginalPrices
price_yes = prices[0] if prices else 0.0
price_no = prices[1] if prices else 0.0

if market_type == "clob":
    # Fetch orderbooks for BOTH sides
    if bet.outcome_token_ids is not None:
        yes_token_id = bet.outcome_token_ids.get("Yes")
        no_token_id = bet.outcome_token_ids.get("No")
        if yes_token_id:
            ob_yes = yield from self._fetch_orderbook(yes_token_id)
            if ob_yes is not None:
                orderbook_asks_yes = ob_yes.get("asks", [])
        if no_token_id:
            ob_no = yield from self._fetch_orderbook(no_token_id)
            if ob_no is not None:
                orderbook_asks_no = ob_no.get("asks", [])

    # This must be populated by polymarket_fetch_market when Bet objects are built.
    min_order_shares = bet.min_order_shares or 5.0
```

**Modify `get_bet_amount()` call — pass `p_yes` and both sides' data:**

```python
bet_amount = yield from self.get_bet_amount(
    prediction_response.p_yes,       # pass p_yes, not win_probability
    prediction_response.confidence,
    bet.outcomeTokenAmounts,         # both sides' pool tokens
    bet.fee,
    bet.collateralToken,
    market_type=market_type,
    price_yes=price_yes,
    price_no=price_no,
    orderbook_asks_yes=orderbook_asks_yes,
    orderbook_asks_no=orderbook_asks_no,
    min_order_shares=min_order_shares,
)
```

**After `get_bet_amount()` — simplified: strategy owns profitability:**

All profitability logic is now inside the strategy itself. The caller only checks
whether the strategy approved a bet (`bet_amount > 0, vote != None`) and runs
position management (`rebet_allowed`).

```python
strategy_result = getattr(self, '_last_strategy_result', {})
strategy_vote = strategy_result.get('vote')  # 0=YES, 1=NO

# Strategy returned no bet — it determined the trade is not profitable.
if bet_amount <= 0 or strategy_vote is None:
    return False, 0, None

# Strategy approved a bet. Only check position management (rebet guard).
# expected_profit computed by strategy: p * shares(b_opt) - b_opt - fee_per_trade
# Venue fees already in shares via alpha; fee_per_trade is external friction only.
expected_profit = strategy_result.get('expected_profit', 0)

token_name = self.get_token_name()
side_name = "YES" if strategy_vote == 0 else "NO"
self.context.logger.info(
    f"Strategy approved bet: {self.convert_to_native(bet_amount)} {token_name} "
    f"on {side_name}"
)

# rebet_allowed() is not called — rebetting is not currently supported,
# and it accesses bet.prediction_response.vote which is being removed.
# When rebetting is re-enabled, it must be updated to work without .vote.

return True, bet_amount, strategy_vote
```

**No per-strategy branching** — the same code handles Kelly, fixed_bet, and any
future strategy. The old Omenstrat/Polystrat profitability checks (`_calc_binary_shares`,
`_compute_new_tokens_distribution`, mid-price shares estimation, `SLIPPAGE`,
`DEFAULT_MECH_COSTS`) are all removed.

**`_is_profitable()` return type changes** from `Tuple[bool, int]` to
`Tuple[bool, int, Optional[int]]` — the third element is the vote (side).

**Changes to `async_act()` (decision_receive.py lines 669-764):**

The current code uses `prediction_response.vote` for the payload. After the
change, `_is_profitable()` returns `strategy_vote` and `async_act()` uses that:

```python
# Current (line 685):
#   if prediction_response is not None and prediction_response.vote is not None:
# New: prediction_response.vote is removed. Check prediction_response is not None.
# The strategy handles ties via vote=None.

if prediction_response is not None:
    if not should_be_sold and not self.review_bets_for_selling_mode:
        is_profitable, bet_amount, strategy_vote = yield from self._is_profitable(
            prediction_response
        )
        decision_received_timestamp = self.synced_timestamp
        if is_profitable:
            self.store_bets()
            bets_hash = self.hash_stored_bets()

# Current (line 743):
#   vote = prediction_response.vote if prediction_response else None
# New: use strategy_vote from _is_profitable() return
vote = strategy_vote if (is_profitable and strategy_vote is not None) else None
confidence = prediction_response.confidence if prediction_response else None

payload = DecisionReceivePayload(
    self.context.agent_address,
    bets_hash,
    is_profitable,
    vote,           # now comes from strategy, not prediction_response
    confidence,
    bet_amount,
    next_mock_data_row,
    policy,
    decision_received_timestamp,
    should_be_sold,
)
```

Note: selling flow (`should_be_sold`) is not currently supported. When re-enabled,
it will need its own vote logic using inline `int(p_no > p_yes)`.

#### 3.3.3 Changes to `base.py` — `get_bet_amount()`

**File:** `packages/valory/skills/decision_maker_abci/behaviours/base.py`

**Extend signature:**

```python
def get_bet_amount(
    self,
    p_yes: float,
    confidence: float,
    outcome_token_amounts: List[int],
    bet_fee: int,
    collateral_token: str,
    market_type: str = "fpmm",
    price_yes: float = 0.0,
    price_no: float = 0.0,
    orderbook_asks_yes: Optional[List[Dict[str, str]]] = None,
    orderbook_asks_no: Optional[List[Dict[str, str]]] = None,
    min_order_shares: float = 0.0,
) -> Generator[None, None, int]:
```

**Normalize legacy strategy names — two places:**

Name normalization must happen in both places to prevent startup crashes and
ensure correct strategy execution.

**1. In `SharedState.setup()` (`models.py` line 316-327) — before startup validation:**

```python
selected_strategy = params.trading_strategy
# Normalize legacy names before validation
if selected_strategy == STRATEGY_KELLY_CRITERION_NO_CONF:
    selected_strategy = STRATEGY_KELLY_CRITERION
if selected_strategy == "bet_amount_per_threshold":
    selected_strategy = "fixed_bet"
strategy_exec = self.strategy_to_filehash.keys()
if selected_strategy not in strategy_exec:
    raise ValueError(...)
```

Without this, operators with `TRADING_STRATEGY=kelly_criterion_no_conf` in their env
would crash at startup because `file_hash_to_strategies` only has the new names.

**2. In `get_bet_amount()` (`base.py`) — before strategy execution:**

```python
# In the while loop, before executing:
if next_strategy == STRATEGY_KELLY_CRITERION_NO_CONF:
    next_strategy = STRATEGY_KELLY_CRITERION
if next_strategy == "bet_amount_per_threshold":
    next_strategy = "fixed_bet"
```

**`file_hash_to_strategies` YAML only needs new names:**

```yaml
file_hash_to_strategies:
  <kelly_criterion_hash>:
    - kelly_criterion
  <fixed_bet_hash>:
    - fixed_bet
```

No need to list old names here — normalization at startup handles it.

**Add new kwargs before `execute_strategy()` call:**

```python
kwargs.update({
    "trading_strategy": next_strategy,
    "bankroll": bankroll,
    "p_yes": p_yes,
    "confidence": confidence,
    "tokens_yes": outcome_token_amounts[0] if outcome_token_amounts else 0,
    "tokens_no": outcome_token_amounts[1] if len(outcome_token_amounts) > 1 else 0,
    "bet_fee": bet_fee,
    "market_type": market_type,
    "price_yes": price_yes,
    "price_no": price_no,
    "orderbook_asks_yes": orderbook_asks_yes,
    "orderbook_asks_no": orderbook_asks_no,
    "min_order_shares": min_order_shares,
})
```

**Store full result for downstream use:**

```python
results = self.execute_strategy(**kwargs)
self._last_strategy_result = results  # NEW: store for _is_profitable() to read
```

**Add `_last_strategy_result` initialization in `__init__`:**

```python
def __init__(self, **kwargs: Any) -> None:
    super().__init__(**kwargs)
    self._last_strategy_result: Dict[str, Any] = {}  # NEW
```

**Update `_update_with_values_from_chatui()` (`base.py` lines 503-521):**

This method maps ChatUI user config to strategy kwargs. ChatUI stores values in
**wei** (converted from native units via `int(value * 10**decimals)` in the HTTP
handler). The strategies receive these wei values directly.

Current mapping:
```python
# Kelly: chatui_config.max_bet_size → strategies_kwargs["max_bet"]
# Threshold: chatui_config.fixed_bet_size → overwrites all bet_amount_per_threshold entries
```

New mapping:
```python
def _update_with_values_from_chatui(self, strategies_kwargs):
    strategies_kwargs = deepcopy(strategies_kwargs)
    chatui_config = self.shared_state.chatui_config

    # For Kelly strategy: max_bet_size caps the hard per-trade limit
    if chatui_config.max_bet_size is not None:
        strategies_kwargs["max_bet"] = chatui_config.max_bet_size

    # For fixed_bet strategy: fixed_bet_size sets the bet amount
    if chatui_config.fixed_bet_size is not None:
        strategies_kwargs["bet_amount"] = chatui_config.fixed_bet_size

    # Keep backward compat: also update bet_amount_per_threshold dict
    # in case a legacy strategy is still active during migration
    if chatui_config.fixed_bet_size is not None:
        if "bet_amount_per_threshold" in strategies_kwargs:
            for key in strategies_kwargs["bet_amount_per_threshold"]:
                strategies_kwargs["bet_amount_per_threshold"][key] = (
                    chatui_config.fixed_bet_size
                )

    return strategies_kwargs
```

All values flow in wei. The Kelly strategy converts to native internally via
`token_decimals`. The fixed_bet strategy operates in wei directly (only does
`min()` comparisons, no floating point math).

### 3.4 Update Strategy References

#### 3.4.1 `chatui_abci/prompts.py`

**Current:**
```python
class TradingStrategy(enum.Enum):
    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
```

**New:**
```python
class TradingStrategy(enum.Enum):
    KELLY_CRITERION = "kelly_criterion"
    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"  # backward compat alias
    FIXED_BET = "fixed_bet"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"  # backward compat alias
```

Keep `KELLY_CRITERION_NO_CONF` and `BET_AMOUNT_PER_THRESHOLD` in the enum for backward
compatibility — users may have these values persisted in `chatui_param_store.json` and
historical bet records in the subgraph will reference them.

Also update the prompt text that describes the strategies to reflect the new ones.

#### 3.4.2 `chatui_abci/handlers.py`

Update `_get_ui_trading_strategy()` to map all names:
```python
if selected_value in (
    TradingStrategy.KELLY_CRITERION.value,
    TradingStrategy.KELLY_CRITERION_NO_CONF.value,
):
    return TradingStrategyUI.RISKY
if selected_value in (
    TradingStrategy.FIXED_BET.value,
    TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value,
):
    return TradingStrategyUI.BALANCED
```

#### 3.4.3 `trader_abci/handlers.py`

Same change — map all strategy names to UI names.

#### 3.4.4 `agent_performance_summary_abci/graph_tooling/predictions_helper.py`

**New:**
```python
class TradingStrategy(enum.Enum):
    KELLY_CRITERION = "kelly_criterion"
    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"  # backward compat
    FIXED_BET = "fixed_bet"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"  # backward compat
```

Update `_get_ui_trading_strategy()` to map all names (same pattern as chatui/trader handlers).

#### 3.4.5 `agent_performance_summary_abci/graph_tooling/polymarket_predictions_helper.py`

Same — update `strategy_map` to include all names:
```python
strategy_map = {
    TradingStrategy.KELLY_CRITERION.value: TradingStrategyUI.RISKY.value,
    TradingStrategy.KELLY_CRITERION_NO_CONF.value: TradingStrategyUI.RISKY.value,
    TradingStrategy.FIXED_BET.value: TradingStrategyUI.BALANCED.value,
    TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value: TradingStrategyUI.BALANCED.value,
}
```

#### 3.4.6 `decision_maker_abci/models.py`

`STRATEGY_KELLY_CRITERION = "kelly_criterion"` — already correct (line 71).

Add a constant for the old name (used in `get_bet_amount` name mapping):
```python
STRATEGY_KELLY_CRITERION = "kelly_criterion"
STRATEGY_KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"  # backward compat
```

Remove `using_kelly` property — no per-strategy branching in the caller anymore.
All strategies have the same contract (`bet_amount` + `vote`).

Remove `bet_kelly_fraction` from any default strategies_kwargs.

### 3.5 Configuration Updates

#### 3.5.1 `decision_maker_abci/skill.yaml`

**Current:**
```yaml
strategies_kwargs:
  bet_kelly_fraction: 1.0
  floor_balance: 500000000000000000
  bet_amount_per_threshold:
    0.0: 0
    ...
```

**New:**
```yaml
strategies_kwargs:
  floor_balance: 500000000000000000
  default_max_bet_size: 5000000
  absolute_max_bet_size: 5000000
  n_bets: 1
  min_edge: 0.03
  min_oracle_prob: 0.5
  fee_per_trade: 0.01
  grid_points: 500
  absolute_min_bet_size: 10000000000000000
  # Keep bet_amount_per_threshold for migration — agents with this strategy
  # configured will have it mapped to fixed_bet at runtime via name normalization.
  bet_amount_per_threshold:
    0.0: 0
    ...
```

Remove `bet_kelly_fraction`. Add Kelly hyperparameters.

Keep `default_max_bet_size` and `absolute_max_bet_size` for ChatUI compatibility.
The current ChatUI code still uses these fields to hydrate and validate `max_bet_size`.

**Decimal/unit contract (resolved):** Config values are in venue-native wei — each
service YAML already uses the correct scale for its venue. The strategy receives
`token_decimals` and converts via `value / 10^token_decimals`. No normalization layer.

- **polymarket_trader** (USDC, 6 decimals): `floor_balance: 1000000` (1 USDC),
  `default_max_bet_size: 2500000` (2.5 USDC), `absolute_max_bet_size: 5000000` (5 USDC),
  `absolute_min_bet_size: 1000000` (1 USDC)
- **trader_pearl** (xDAI, 18 decimals): `floor_balance: 500000000000000000` (0.5 xDAI),
  `default_max_bet_size: 2000000000000000000` (2 xDAI), `absolute_max_bet_size: 2000000000000000000` (2 xDAI),
  `absolute_min_bet_size: 25000000000000000` (0.025 xDAI)

#### 3.5.2 Service/Agent YAML Files

Update these files to:
- Change `trading_strategy` default to `"kelly_criterion"`
- Update `strategies_kwargs` to match new params while keeping ChatUI compatibility keys
- Allow both `kelly_criterion` and `kelly_criterion_no_conf` in config migration paths during backward-compat handling
- Update dependency hashes after package changes

**Files:**
- `packages/valory/services/trader/service.yaml`
- `packages/valory/services/trader_pearl/service.yaml`
- `packages/valory/services/polymarket_trader/service.yaml`
- `packages/valory/agents/trader/aea-config.yaml`
- `packages/valory/skills/trader_abci/skill.yaml`

### 3.6 New Fixed Bet Strategy — `packages/valory/customs/fixed_bet/`

Simple replacement for `bet_amount_per_threshold`. Returns a configured fixed amount.

**Files to create:**
- `packages/valory/customs/fixed_bet/__init__.py`
- `packages/valory/customs/fixed_bet/component.yaml`
- `packages/valory/customs/fixed_bet/fixed_bet.py`
- `packages/valory/customs/fixed_bet/tests/__init__.py`
- `packages/valory/customs/fixed_bet/tests/test_fixed_bet.py`

**`fixed_bet.py`:**
```python
REQUIRED_FIELDS = frozenset({"bankroll", "floor_balance", "p_yes"})
OPTIONAL_FIELDS = frozenset({"bet_amount", "min_bet", "max_bet", "token_decimals"})

def run(**kwargs):
    """Return a fixed bet amount. Side = higher-probability side."""
    missing = [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]
    if missing:
        return {"bet_amount": 0, "vote": None, "error": [f"Missing: {missing}"]}

    bankroll = kwargs["bankroll"]
    floor_balance = kwargs["floor_balance"]
    p_yes = kwargs["p_yes"]
    bet_amount = kwargs.get("bet_amount", kwargs.get("min_bet", 0))

    # Side selection: pick the higher-probability side
    p_no = 1.0 - p_yes
    if p_yes == p_no:
        return {"bet_amount": 0, "vote": None, "info": ["Tie — no bet"]}
    vote = int(p_no > p_yes)  # 0=YES, 1=NO

    if bankroll <= floor_balance:
        return {"bet_amount": 0, "vote": vote, "info": ["Bankroll below floor"]}
    if bet_amount <= 0:
        return {"bet_amount": 0, "vote": vote, "info": ["No bet_amount configured"]}

    max_bet = kwargs.get("max_bet", bet_amount)
    bet_amount = min(bet_amount, max_bet, bankroll - floor_balance)

    return {"bet_amount": int(bet_amount), "vote": vote, "info": [f"Fixed bet: {bet_amount}"]}
```

**Strategy contract**: every strategy must return `vote` (0=YES, 1=NO, or None=no trade).
No fallback logic in the caller — the strategy is the single source of truth for side selection.

### 3.7 Delete Old Strategies

**Delete entirely:**
- `packages/jhehemann/customs/kelly_criterion/` — legacy Kelly WITH confidence
- `packages/valory/customs/kelly_criterion_no_conf/` — Kelly WITHOUT confidence
- `packages/valory/customs/bet_amount_per_threshold/` — replaced by `fixed_bet`

**Update `packages/packages.json`:**
- Remove entries for all three deleted packages
- Add entries for `valory/customs/kelly_criterion` and `valory/customs/fixed_bet`

**Update agent/service YAML files:**
- Remove dependencies on deleted packages
- Add dependencies on new packages

### 3.8 Remove Dead Code

Two categories of dead code to remove:

**A) Side-selection code** — `PredictionResponse.vote` and `win_probability` are dead
now that strategies decide the side.

**B) Profitability-check code** — the Omenstrat/Polystrat branching in `_is_profitable()`
is dead now that strategies own profitability. Remove from `decision_receive.py`:
- `_calc_binary_shares()` method
- `_compute_new_tokens_distribution()` method
- `_get_bet_sample_info()` method (pool tokens now passed directly)
- The entire `if not self.params.is_running_on_polymarket: # Omenstrat` block (lines 484-520)
- The entire `else: # Polystrat` block (lines 521-585)
- `SLIPPAGE` constant (line 58)
- `DEFAULT_MECH_COSTS` constant (line 62)
- `bet_threshold` usage (strategy handles min viable bets)
- The `using_kelly` branching (all strategies now have the same caller contract)

**`packages/valory/skills/market_manager_abci/bets.py`:**

Remove from `PredictionResponse`:
```python
# DELETE these properties:
@property
def vote(self) -> Optional[int]:
    """Return the vote. `0` represents "yes" and `1` represents "no"."""
    if self.p_no != self.p_yes:
        return int(self.p_no > self.p_yes)
    return None

@property
def win_probability(self) -> float:
    """Return the probability estimation for winning with vote."""
    return max(self.p_no, self.p_yes)
```

**Impact — all consumers of `prediction_response.vote` must be updated:**

| File | Line | Current usage | New behavior |
|------|------|---------------|-------------|
| `decision_receive.py:444` | `if prediction_response.vote is None` | Check `p_yes == p_no` directly, or remove (let strategy handle ties) |
| `decision_receive.py:456` | `_get_bet_sample_info(bet, prediction_response.vote)` | No longer needed for Kelly (strategy gets both sides). For fixed_bet, use `int(prediction_response.p_no > prediction_response.p_yes)` inline |
| `decision_receive.py:460` | `prediction_response.win_probability` | Pass `prediction_response.p_yes` directly |
| `decision_receive.py:486` | `_calc_binary_shares(bet, net_bet_amount, prediction_response.vote)` | Removed — Kelly handles this internally |
| `decision_receive.py:522` | `predicted_vote_side = prediction_response.vote` | Removed — Kelly handles this internally |
| `decision_receive.py:591` | `_update_liquidity_info(net_bet_amount, prediction_response.vote)` | Use `strategy_vote` from strategy result |
| `decision_receive.py:637` | `prediction_response.vote is None` (sell check) | Keep for selling logic — use inline `int(p_no > p_yes)` |
| `decision_receive.py:640` | `get_vote_amount(prediction_response.vote)` | Same — inline calculation |
| `decision_receive.py:685` | `prediction_response.vote is not None` | Check `prediction_response is not None` only |
| `decision_receive.py:743` | `vote = prediction_response.vote` | Use `strategy_vote` from `_is_profitable()` return |
| `base.py:148` | `outcome_index` property | Unchanged — reads from `synchronized_data.vote` which now comes from strategy |

**Also update:**
- `decision_receive.py:428`: `bet.prediction_response.vote` in `rebet_allowed()` — keep, but use inline vote calc
- Any tests that mock `prediction_response.vote` or `prediction_response.win_probability`

**Note**: The selling flow (`should_sell_outcome_tokens`, `review_bets_for_selling_mode`) still
needs a vote to know which side's tokens to sell. For selling, use inline
`int(prediction_response.p_no > prediction_response.p_yes)` — selling is about
evaluating existing positions against new mech data, not about new side selection.

Legacy name normalization in `SharedState.setup()` and `get_bet_amount()` (see section 3.3.3)
ensures operators with old names don't crash — no need to list old names in `file_hash_to_strategies`.

### 3.9 Unsupported Code Paths

The following code paths exist in the current `decision_receive.py` but are
**not currently supported** in production. During implementation, these must be
guarded so they cannot be traversed, or removed entirely.

**A) Benchmarking mode** (`decision_receive.py` lines 447-450, 587-606)

`_is_profitable()` has benchmarking logic that calls:
- `_update_liquidity_info(net_bet_amount, prediction_response.vote)`
- `_write_benchmark_results(prediction_response, bet_amount, liquidity_info)`
- `_update_selected_bet(prediction_response)`

These use `prediction_response.vote` (which is being removed) and
`_compute_new_tokens_distribution()` (which is dead code). Since benchmarking
is not supported, either:
- remove this code entirely, or
- gate it behind `if self.benchmarking_mode.enabled:` with a clear error/skip

**B) `rebet_allowed()` (`decision_receive.py` lines 418-438)

This method internally accesses `bet.prediction_response.vote` (line 428):
```python
vote = bet.prediction_response.vote
bet.position_liquidity = bet.outcomeTokenAmounts[vote] if vote else 0
```

Since rebetting is not currently supported, this path won't execute. But if
rebetting is re-enabled, `rebet_allowed()` must be updated to work without
`PredictionResponse.vote` — use `strategy_vote` from the strategy result
or inline `int(p_no > p_yes)` instead.

**C) Selling flow** (`should_sell_outcome_tokens`, lines 630-651)

Uses `prediction_response.vote` to determine which side's tokens to sell.
Not currently supported. When re-enabled, use inline
`int(prediction_response.p_no > prediction_response.p_yes)`.

**D) `fixed_bet` does not return `expected_profit`**

The `fixed_bet` strategy returns `bet_amount` and `vote` but not
`expected_profit`. The caller reads `strategy_result.get('expected_profit', 0)`,
so it defaults to 0. This value currently flows to `rebet_allowed()` which is
not supported. When rebetting is re-enabled, `fixed_bet` must either:
- compute `expected_profit` (requires market data it currently doesn't use), or
- the caller must handle the 0 case explicitly

---

## 4. Test Plan (TDD)

### 4.1 New Strategy Tests

**File:** `packages/valory/customs/kelly_criterion/tests/test_kelly_criterion.py`

| Test | Description | Key Assertion |
|------|-------------|---------------|
| `test_missing_required_fields` | Call `run()` with missing bankroll | Returns `error` with missing fields list |
| `test_bankroll_below_floor` | bankroll < floor_balance | `bet_amount == 0` |
| `test_zero_bankroll` | bankroll = 0 | `bet_amount == 0` |
| `test_invalid_p_yes` | p_yes = 1.5 or p_yes = -0.1 | `bet_amount == 0`, error message |
| `test_edge_below_min_edge` | p_yes=0.53, price_yes=0.52, min_edge=0.03 | `bet_amount == 0` |
| `test_oracle_prob_below_min` | p_yes=0.4, min_oracle_prob=0.5 | `bet_amount == 0` for YES side |
| `test_clob_walk_book_single_level` | One ask level, enough to fill | Correct (cost, shares) |
| `test_clob_walk_book_multi_level` | Three ask levels, walks all | Shares accumulated correctly across levels |
| `test_clob_walk_book_partial_fill` | Budget exhausts mid-level | Partial fill at correct price |
| `test_clob_walk_book_empty` | Empty asks list | `bet_amount == 0` |
| `test_clob_walk_book_zero_price` | Level with price=0 | Skipped, no crash |
| `test_fpmm_execution_basic` | Known x, y, alpha, b | shares = alpha*b + x - x*y/(y + alpha*b) |
| `test_fpmm_execution_zero_bet` | b = 0 | shares = 0 |
| `test_fpmm_execution_equal_pools` | x = y (50/50 market) | Correct shares |
| `test_grid_search_finds_optimum_clob` | Orderbook with known optimal | bet_amount matches manual calculation |
| `test_grid_search_finds_optimum_fpmm` | Pool state with known optimal | bet_amount matches manual calculation |
| `test_no_trade_baseline` | Very small edge, fee > edge | `bet_amount == 0` (no-trade wins) |
| `test_min_bet_constraint` | min_bet larger than some levels | Grid starts at min_bet |
| `test_max_bet_constraint` | max_bet < optimal | Capped at max_bet |
| `test_n_bets_effect` | n_bets=1 vs n_bets=5, same market | Different bet sizes (n_bets=5 more aggressive) |
| `test_both_sides_evaluated` | Both YES and NO evaluated | Both sides in info logs, best G_improvement wins |
| `test_vote_returned` | Strategy returns correct vote | `vote == 0` when YES wins, `vote == 1` when NO wins |
| `test_strategy_picks_no_over_yes` | NO side has better G | `vote == 1` even though `p_yes > 0.5` |
| `test_full_integration_clob` | Realistic CLOB scenario | Non-zero bet with positive G_improvement |
| `test_full_integration_fpmm` | Realistic FPMM scenario | Non-zero bet with positive G_improvement |
| `test_unknown_kwargs_no_crash` | Pass extra unknown kwargs | No error, strategy ignores them |
| `test_return_format` | Any valid call | Dict has bet_amount, vote, expected_profit, g_improvement, info, error |

### 4.2 Connection Tests

**File:** `packages/valory/connections/polymarket_client/tests/test_connection.py`

| Test | Description |
|------|-------------|
| `test_fetch_order_book_success` | Mock `client.get_order_book` returns book → asks/bids serialized |
| `test_fetch_order_book_empty` | Empty asks/bids → `{"asks": [], "bids": []}` |
| `test_fetch_order_book_none_asks` | None asks/bids → `{"asks": [], "bids": []}` |
| `test_fetch_order_book_exception` | Client raises → `(None, error_msg)` |

### 4.3 Decision Receive Tests

**File:** `packages/valory/skills/decision_maker_abci/tests/behaviours/test_decision_receive.py`

| Test | Description |
|------|-------------|
| `test_fetch_orderbook_success` | Mock connection returns orderbook → parsed correctly |
| `test_fetch_orderbook_failure` | Connection returns None → returns None, warning logged |
| `test_fetch_orderbook_error_response` | Response has error key → returns None |
| `test_is_profitable_passes_min_order_shares` | Polymarket bet carries `min_order_shares` → strategy receives it |
| `test_fetch_both_orderbooks` | Both YES and NO orderbooks fetched for CLOB | Two connection requests sent |
| `test_strategy_positive_bet` | Strategy returns bet_amount > 0, vote=0 → is_profitable = True, vote propagated |
| `test_strategy_vote_propagated_to_payload` | Strategy returns vote=1 (NO) → DecisionReceivePayload gets vote=1 |
| `test_strategy_returns_zero` | Strategy returns bet_amount = 0 → is_profitable = False |
| `test_strategy_returns_none_vote` | Strategy returns vote=None → is_profitable = False |
| `test_rebet_rejected` | rebet_allowed returns False → is_profitable = False despite strategy positive |
| `test_orderbook_fetch_failure` | Orderbook fetch fails → strategy gets empty asks, returns 0 |
| `test_no_omenstrat_polystrat_branching` | No `is_running_on_polymarket` branching in profitability (removed) |

### 4.4 Base Behaviour Tests

**File:** `packages/valory/skills/decision_maker_abci/tests/behaviours/test_base.py`

| Test | Description |
|------|-------------|
| `test_get_bet_amount_passes_p_yes` | p_yes kwarg reaches strategy |
| `test_get_bet_amount_passes_both_orderbooks` | orderbook_asks_yes and _no reach strategy |
| `test_get_bet_amount_passes_both_prices` | price_yes and price_no reach strategy |
| `test_get_bet_amount_passes_min_order_shares` | min_order_shares kwarg reaches strategy |
| `test_last_strategy_result_stored` | After execute_strategy, _last_strategy_result is set |
| `test_kelly_no_conf_mapped_to_kelly` | `kelly_criterion_no_conf` strategy name mapped to `kelly_criterion` |

### 4.5 Fixed Bet Strategy Tests

**File:** `packages/valory/customs/fixed_bet/tests/test_fixed_bet.py`

| Test | Description |
|------|-------------|
| `test_missing_required_fields` | Missing bankroll → error |
| `test_bankroll_below_floor` | bankroll < floor_balance → bet_amount=0 |
| `test_returns_configured_amount` | bet_amount=1000 → returns 1000 |
| `test_capped_at_max_bet` | bet_amount=1000, max_bet=500 → returns 500 |
| `test_capped_at_available_balance` | bet_amount=1000, bankroll-floor=300 → returns 300 |
| `test_vote_picks_higher_prob` | p_yes=0.7 → vote=0 (YES); p_yes=0.3 → vote=1 (NO) |
| `test_tie_returns_no_trade` | p_yes=0.5 → vote=None, bet_amount=0 |

### 4.6 Enum/Handler Tests

Update existing tests that reference `kelly_criterion_no_conf` to use `kelly_criterion` in:
- `chatui_abci/tests/test_handlers.py`
- `chatui_abci/tests/test_prompts.py`
- `chatui_abci/tests/test_models.py`
- `trader_abci/tests/test_handlers.py`
- `agent_performance_summary_abci/tests/graph_tooling/test_predictions_helper.py`
- `agent_performance_summary_abci/tests/graph_tooling/test_polymarket_predictions_helper.py`
- `decision_maker_abci/tests/test_models.py`

### 4.7 Migration Tests (exhaustive)

Legacy names can enter the system through 8 surfaces. Each needs a test proving
the old name doesn't crash and resolves correctly.

**Surface 1: `SharedState.setup()` startup validation**
(`decision_maker_abci/tests/test_models.py`)

| Test | Description |
|------|-------------|
| `test_setup_kelly_criterion_no_conf_normalized` | `params.trading_strategy="kelly_criterion_no_conf"`, `file_hash_to_strategies` only has `kelly_criterion` → setup succeeds, no ValueError |
| `test_setup_bet_amount_per_threshold_normalized` | `params.trading_strategy="bet_amount_per_threshold"`, `file_hash_to_strategies` only has `fixed_bet` → setup succeeds |
| `test_setup_new_names_work` | `params.trading_strategy="kelly_criterion"` with matching hash → setup succeeds (sanity) |

**Surface 2: ChatUI config persistence — `trading_strategy`**
(`chatui_abci/tests/test_models.py`)

| Test | Description |
|------|-------------|
| `test_chatui_store_loads_legacy_kelly_name` | `chatui_param_store.json` has `"trading_strategy": "kelly_criterion_no_conf"` → `ChatuiConfig.trading_strategy` loads without error |
| `test_chatui_store_loads_legacy_threshold_name` | `chatui_param_store.json` has `"trading_strategy": "bet_amount_per_threshold"` → loads without error |

**Surface 3: ChatUI config persistence — `initial_trading_strategy`**
(`chatui_abci/tests/test_models.py`)

| Test | Description |
|------|-------------|
| `test_chatui_initial_strategy_mismatch_resets` | YAML default is `"kelly_criterion"`, stored `initial_trading_strategy` is `"kelly_criterion_no_conf"` → detects mismatch, resets to YAML default |

**Surface 4: ChatUI HTTP handler — `AVAILABLE_TRADING_STRATEGIES` validation**
(`chatui_abci/tests/test_handlers.py`)

| Test | Description |
|------|-------------|
| `test_legacy_kelly_name_in_available_strategies` | `"kelly_criterion_no_conf"` is in `AVAILABLE_TRADING_STRATEGIES` → HTTP request with old name accepted |
| `test_legacy_threshold_name_in_available_strategies` | `"bet_amount_per_threshold"` is in `AVAILABLE_TRADING_STRATEGIES` → accepted |
| `test_new_kelly_name_in_available_strategies` | `"kelly_criterion"` accepted |
| `test_new_fixed_bet_name_in_available_strategies` | `"fixed_bet"` accepted |

**Surface 5: `file_hash_to_strategies` → `strategy_to_filehash` mapping**
(`decision_maker_abci/tests/test_models.py`)

| Test | Description |
|------|-------------|
| `test_legacy_name_resolves_after_normalization` | `file_hash_to_strategies={"hash1": ["kelly_criterion"]}`, `trading_strategy="kelly_criterion_no_conf"` → normalized to `kelly_criterion`, found in map |

**Surface 6: `get_bet_amount()` runtime name mapping**
(`decision_maker_abci/tests/behaviours/test_base.py`)

| Test | Description |
|------|-------------|
| `test_kelly_no_conf_executes_kelly_package` | `next_strategy="kelly_criterion_no_conf"` → mapped to `"kelly_criterion"`, correct strategy executable found and run |
| `test_bet_amount_per_threshold_executes_fixed_bet` | `next_strategy="bet_amount_per_threshold"` → mapped to `"fixed_bet"`, correct executable run |

**Surface 7: Historical bet records — `_get_ui_trading_strategy()`**
(`agent_performance_summary_abci/tests/graph_tooling/test_predictions_helper.py`)
(`agent_performance_summary_abci/tests/graph_tooling/test_polymarket_predictions_helper.py`)

| Test | Description |
|------|-------------|
| `test_legacy_kelly_maps_to_risky` | `_get_ui_trading_strategy("kelly_criterion_no_conf")` → `"risky"` |
| `test_new_kelly_maps_to_risky` | `_get_ui_trading_strategy("kelly_criterion")` → `"risky"` |
| `test_legacy_threshold_maps_to_balanced` | `_get_ui_trading_strategy("bet_amount_per_threshold")` → `"balanced"` |
| `test_new_fixed_bet_maps_to_balanced` | `_get_ui_trading_strategy("fixed_bet")` → `"balanced"` |

**Surface 8: UI display — chatui/trader handler `_get_ui_trading_strategy()`**
(`chatui_abci/tests/test_handlers.py`, `trader_abci/tests/test_handlers.py`)

| Test | Description |
|------|-------------|
| `test_ui_kelly_no_conf_returns_risky` | Handler maps `"kelly_criterion_no_conf"` → `RISKY` |
| `test_ui_kelly_returns_risky` | Handler maps `"kelly_criterion"` → `RISKY` |
| `test_ui_threshold_returns_balanced` | Handler maps `"bet_amount_per_threshold"` → `BALANCED` |
| `test_ui_fixed_bet_returns_balanced` | Handler maps `"fixed_bet"` → `BALANCED` |

**ChatUI config key compatibility**
(`chatui_abci/tests/test_models.py`)

| Test | Description |
|------|-------------|
| `test_default_max_bet_size_present` | `strategies_kwargs` still has `default_max_bet_size` key |
| `test_absolute_max_bet_size_present` | `strategies_kwargs` still has `absolute_max_bet_size` key |

---

## 5. Verification Checklist

```bash
# 1. New strategy tests
poetry run pytest packages/valory/customs/kelly_criterion/tests/ -v
poetry run pytest packages/valory/customs/fixed_bet/tests/ -v

# 2. Connection tests
poetry run pytest packages/valory/connections/polymarket_client/tests/ -v

# 3. Decision maker tests
poetry run pytest packages/valory/skills/decision_maker_abci/tests/ -v

# 4. ChatUI tests
poetry run pytest packages/valory/skills/chatui_abci/tests/ -v

# 5. Trader ABCI tests
poetry run pytest packages/valory/skills/trader_abci/tests/ -v

# 6. Performance summary tests
poetry run pytest packages/valory/skills/agent_performance_summary_abci/tests/ -v

# 7. Full test suite
tox -e py3.10-linux

# 8. Linting
tomte check-code

# 9. Verify old strategy code is gone (only backward-compat enum references should remain)
grep -r "kelly_criterion_no_conf" packages/ --include="*.py" | grep -v "test_\|enum\|Enum\|backward"
grep -r "jhehemann.*kelly" packages/
grep -r "bet_amount_per_threshold" packages/ --include="*.py" | grep -v "test_\|enum\|Enum\|backward"

# 10. Verify PredictionResponse.vote and .win_probability are removed
grep -rn "prediction_response\.vote\|\.win_probability" packages/ --include="*.py"

# 11. Coverage (must not drop)
# Check tox coverage job output
```

---

## 6. Execution Order

```
1.  Write kelly_criterion strategy tests (TDD)
2.  Implement kelly_criterion.py to pass tests
3.  Write fixed_bet strategy tests (TDD)
4.  Implement fixed_bet.py to pass tests
5.  Write connection tests for FETCH_ORDER_BOOK
6.  Implement FETCH_ORDER_BOOK in polymarket connection
7.  Write decision_receive tests (side selection from strategy, both orderbooks)
8.  Implement decision_receive integration
9.  Write base.py tests (new get_bet_amount signature)
10. Implement base.py changes
11. Remove PredictionResponse.vote and .win_probability, update all consumers
12. Update all enums and handler references (with tests)
13. Update YAML configurations
14. Delete old strategies (kelly_criterion_no_conf, kelly_criterion jhehemann, bet_amount_per_threshold)
15. Update packages.json and run autonomy packages lock
16. Run full test suite and linting
```

---

## 7. API-Call Budget

Per-market request changes in the decision receive cycle:

**Polymarket (CLOB):**

| Call | Before | After |
|------|--------|-------|
| Orderbook fetch (YES) | 0 | 1 (new) |
| Orderbook fetch (NO) | 0 | 1 (new) |
| Mid-price profitability calc | 1 (in-memory, no API) | 0 (removed) |
| Strategy execution | 1 (exec) | 1 (exec) |

Net change: +2 API calls per market (both orderbook fetches). The old mid-price
profitability check was purely in-memory math on already-fetched `outcomeTokenMarginalPrices`,
not an API call — so nothing is removed on the API side.

**Omen (FPMM):**

| Call | Before | After |
|------|--------|-------|
| Pool data / prices | already fetched in market sampling | same |
| Binary shares calc | 1 (in-memory) | 0 (moved into strategy) |
| Strategy execution | 1 (exec) | 1 (exec) |

Net change: 0 API calls. FPMM path uses data already available on `Bet` object.

**Execution-time validation:** Out of scope for the sizing algorithm (see
`plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md` section "Execution-Time Validation").
If needed, define separately as a pre-placement guard.

---

## 8. Risk Considerations

| Risk | Mitigation |
|------|------------|
| Strategy `exec()` sandbox doesn't have `math` | Strategy file imports `math` at top — `exec()` runs the full file which creates the import |
| Orderbook stale by execution time | Acceptable for sizing; actual execution uses fresh order at placement time |
| ChatUI/config regression from removed max-bet keys | Keep `default_max_bet_size` and `absolute_max_bet_size` in `strategies_kwargs` until ChatUI is refactored |
| Operators have old `kelly_criterion_no_conf` in config | Normalize at startup in `SharedState.setup()` and at runtime in `get_bet_amount()` — see section 3.3.3 |
| Operators have old `bet_kelly_fraction` in config | Config YAML is updated in this PR. Operators must update their overrides. |
| FPMM Kelly gives different results than old quadratic | Expected — grid search is more correct. Differences should be small for well-balanced pools. Document in PR. |
| Venue minimum order changes or differs across markets | Pipe `min_order_shares` from market metadata instead of hardcoding 5 shares inside the strategy |
| Strategy picks different side than mech | This is intentional — Kelly evaluates both sides by G_improvement. The mech provides `p_yes`; Kelly uses it to evaluate both YES (p_yes) and NO (1-p_yes) sides. |
| Selling flow needs a vote | Selling still uses inline `int(p_no > p_yes)` since it's about which existing position to sell, not about new side selection. |
| Users have `bet_amount_per_threshold` or `kelly_criterion_no_conf` in chatui_param_store | Backward compat aliases in enums + `get_bet_amount()` name mapping handle this. |
| Two orderbook fetches per market (CLOB) | Adds one extra API call. Acceptable latency tradeoff for correct side selection. |
