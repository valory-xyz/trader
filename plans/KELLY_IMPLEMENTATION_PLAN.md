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
5. Supports configurable side evaluation (mech-side-only or independent both-sides)

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
MechResponse (p_yes, confidence)
    │
    ▼
DecisionReceiveBehaviour._is_profitable()
    │
    ├── [Poly only] _fetch_orderbook(token_id) ──► CLOB ask levels  ◄── NEW
    │
    ├── get_bet_amount() ──► strategy.run()
    │   │                        │
    │   │   NEW kwargs:          │
    │   │     market_type,       │   Strategy now does EVERYTHING:
    │   │     orderbook_asks,    │   - edge filtering
    │   │     market_price,      │   - grid search over bet sizes
    │   │     n_bets,            │   - execution simulation (CLOB or FPMM)
    │   │     min_edge,          │   - log-growth comparison vs no-trade
    │   │     grid_points, ...   │
    │   │                        │
    │   ◄── returns: {           │
    │         "bet_amount": int, ◄──────────────────────────────────────┘
    │         "expected_shares": int,
    │         "g_improvement": float,
    │       }
    │
    ├── [Kelly] If bet_amount > 0, trust the strategy  ◄── SIMPLIFIED
    │           (strategy already validated profitability via log-growth)
    │           Only apply: rebet check (position management, not sizing)
    │
    ├── [bet_amount_per_threshold] Keep existing logic unchanged
    │
    ▼
(is_profitable, bet_amount) returned
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
    "win_probability",   # float [0,1] — oracle's p for the predicted side
    "market_type",       # str — "clob" or "fpmm"
    "floor_balance",     # int (wei) — minimum balance to keep in wallet
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
    # DEFERRED: independent side evaluation (evaluate YES and NO independently
    # and pick the side with highest G_improvement, even if it disagrees with
    # the mech). Decision pending — not implemented in V1. When implemented,
    # will require fetching both orderbooks for CLOB markets.

    # FPMM-specific (used when market_type="fpmm")
    "selected_type_tokens_in_pool",  # int (wei) — x: selected outcome tokens
    "other_tokens_in_pool",          # int (wei) — y: other outcome tokens
    "bet_fee",                       # int (wei) — FPMM market fee

    # CLOB-specific (used when market_type="clob")
    "orderbook_asks",       # List[Dict[str, str]] — [{"price": "0.55", "size": "100"}, ...]

    # Market price (for edge calculation)
    "market_price",         # float — current market price for the predicted side

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
        Per-trade friction cost (native units).
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
        expected_shares : int (wei) — shares from execution model
        g_improvement : float — log-growth improvement over no-trade
        info : list of str — informational log messages
        error : list of str — error messages
    """
    info = []
    error = []

    # --- 1. Validate required fields ---
    missing = [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]
    if missing:
        return {"bet_amount": 0, "error": [f"Missing required fields: {missing}"]}

    # --- 2. Extract parameters ---
    bankroll = kwargs["bankroll"]            # int, wei
    win_probability = kwargs["win_probability"]  # float
    market_type = kwargs["market_type"]      # "clob" or "fpmm"
    floor_balance = kwargs["floor_balance"]  # int, wei

    token_decimals = kwargs.get("token_decimals", DEFAULT_TOKEN_DECIMALS)
    scale = 10 ** token_decimals

    # Determine defaults based on token
    default_max_bet = DEFAULT_MAX_BET_USDC if token_decimals == 6 else DEFAULT_MAX_BET_XDAI

    max_bet_wei = kwargs.get("max_bet", default_max_bet)
    min_bet_wei = kwargs.get("min_bet", DEFAULT_MIN_BET)
    n_bets = kwargs.get("n_bets", DEFAULT_N_BETS)
    min_edge = kwargs.get("min_edge", DEFAULT_MIN_EDGE)
    min_oracle_prob = kwargs.get("min_oracle_prob", DEFAULT_MIN_ORACLE_PROB)
    fee_per_trade = kwargs.get("fee_per_trade", DEFAULT_FEE_PER_TRADE)
    grid_points = kwargs.get("grid_points", DEFAULT_GRID_POINTS)
    # NOTE: independent side evaluation is deferred (decision pending).
    # V1 only evaluates the mech's predicted side.

    # Convert to native units for calculation
    max_bet = max_bet_wei / scale
    min_bet = min_bet_wei / scale
    W_total = bankroll / scale
    floor = floor_balance / scale

    token_name = "USDC" if token_decimals == 6 else "xDAI"
    info.append(f"Bankroll: {W_total} {token_name}, floor: {floor} {token_name}")
    info.append(f"max_bet: {max_bet}, n_bets: {n_bets}, min_edge: {min_edge}")
    info.append(f"market_type: {market_type}")

    # --- 3. Compute effective wealth ---
    W = W_total - floor
    if W <= 0:
        info.append(f"Bankroll ({W_total}) <= floor ({floor}). No bet.")
        return {"bet_amount": 0, "expected_shares": 0, "g_improvement": 0.0,
                "info": info, "error": error}

    W = min(W, max_bet)  # Can't bet more than max_bet from adjusted bankroll

    # Per-bet bankroll: W_bet = min(n_bets * max_bet, W_total - floor)
    W_bet = min(n_bets * max_bet, W_total - floor)
    info.append(f"W_bet (per-bet bankroll): {W_bet} {token_name}")

    # --- 4. Validate probability ---
    if not (0 < win_probability < 1):
        error.append(f"Invalid win_probability: {win_probability}")
        return {"bet_amount": 0, "expected_shares": 0, "g_improvement": 0.0,
                "info": info, "error": error}

    # --- 5. Get market price and compute edge ---
    market_price = kwargs.get("market_price", 0.0)
    if market_price <= 0 or market_price >= 1:
        error.append(f"Invalid market_price: {market_price}")
        return {"bet_amount": 0, "expected_shares": 0, "g_improvement": 0.0,
                "info": info, "error": error}

    # --- 6. Prepare side(s) to evaluate ---
    sides_to_evaluate = []

    # Primary side (matching mech's prediction)
    p_primary = win_probability
    edge_primary = p_primary - market_price
    sides_to_evaluate.append({
        "label": "predicted",
        "p": p_primary,
        "edge": edge_primary,
        "market_price": market_price,
    })

    # DEFERRED: independent side evaluation would add the opposite side here

    # --- 7. Evaluate each side ---
    best_result = None
    all_rejections = []

    for side_info in sides_to_evaluate:
        side_label = side_info["label"]
        p = side_info["p"]
        edge = side_info["edge"]

        # Filter: min_edge
        if edge < min_edge:
            msg = f"{side_label}: edge {edge:+.4f} < min_edge {min_edge}"
            info.append(msg)
            all_rejections.append(msg)
            continue

        # Filter: min_oracle_prob
        if min_oracle_prob > 0 and p < min_oracle_prob:
            msg = f"{side_label}: oracle prob {p:.3f} < min_oracle_prob {min_oracle_prob}"
            info.append(msg)
            all_rejections.append(msg)
            continue

        # Determine b_min for this side
        if market_type == "clob":
            asks = kwargs.get("orderbook_asks")
            if not asks:
                msg = f"{side_label}: no orderbook asks available"
                info.append(msg)
                all_rejections.append(msg)
                continue
            # b_min for CLOB: min_order_shares * best_ask_price
            sorted_asks = sorted(asks, key=lambda a: float(a["price"]))
            best_ask_price = float(sorted_asks[0]["price"])
            # Use min_bet if it's larger than the minimum executable
            b_min_side = max(min_bet, best_ask_price * 5.0)  # 5 shares minimum on Polymarket
        else:
            asks = None
            b_min_side = min_bet

        # Get FPMM parameters if needed
        x_native = kwargs.get("selected_type_tokens_in_pool", 0) / scale if market_type == "fpmm" else 0.0
        y_native = kwargs.get("other_tokens_in_pool", 0) / scale if market_type == "fpmm" else 0.0
        bet_fee_wei = kwargs.get("bet_fee", 0)
        alpha = 1.0 - (bet_fee_wei / scale) if market_type == "fpmm" else 1.0

        # Run grid search
        best_spend, best_shares, best_G, G_baseline = optimize_side(
            p=p,
            W_bet=W_bet,
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

        G_improvement = best_G - G_baseline

        info.append(
            f"{side_label}: spend={best_spend:.4f}, shares={best_shares:.4f}, "
            f"G_improvement={G_improvement:.6f}, edge={edge:+.4f}"
        )

        if best_spend > 0 and G_improvement > 0:
            if best_result is None or G_improvement > best_result["g_improvement"]:
                best_result = {
                    "spend": best_spend,
                    "shares": best_shares,
                    "g_improvement": G_improvement,
                    "side_label": side_label,
                    "edge": edge,
                }

    # --- 8. Return result ---
    if best_result is None:
        reason = "; ".join(all_rejections) if all_rejections else "no bet improves log-growth"
        info.append(f"No trade: {reason}")
        return {"bet_amount": 0, "expected_shares": 0, "g_improvement": 0.0,
                "info": info, "error": error}

    bet_amount_wei = int(best_result["spend"] * scale)
    expected_shares_wei = int(best_result["shares"] * scale)

    info.append(
        f"Selected {best_result['side_label']}: "
        f"bet={best_result['spend']:.4f} {token_name}, "
        f"shares={best_result['shares']:.4f}, "
        f"G_improvement={best_result['g_improvement']:.6f}"
    )

    return {
        "bet_amount": bet_amount_wei,
        "expected_shares": expected_shares_wei,
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
| `fee_per_trade` | float | 0.01 | Gas + mech cost in native units. Deducted in both win/lose states. |
| `grid_points` | int | 500 | Grid resolution for optimizer. 500 is production-grade. |
| *(deferred)* | | | Independent side evaluation — decision pending. Not in V1. |

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

**Before `get_bet_amount()` call — fetch orderbook for Polymarket:**

```python
# Existing code:
selected_type_tokens_in_pool, other_tokens_in_pool = self._get_bet_sample_info(
    bet, prediction_response.vote
)

# NEW: Determine market type and fetch orderbook if CLOB
market_type = "clob" if self.params.is_running_on_polymarket else "fpmm"
orderbook_asks = None
market_price = 0.0

if market_type == "clob":
    # Get market price for the predicted side
    predicted_vote_side = prediction_response.vote
    prices = bet.outcomeTokenMarginalPrices
    if prices is not None:
        market_price = prices[predicted_vote_side]

    # Fetch orderbook for the predicted side's token
    if bet.outcome_token_ids is not None:
        side_key = "Yes" if predicted_vote_side == 0 else "No"
        token_id = bet.outcome_token_ids.get(side_key)
        if token_id:
            orderbook_response = yield from self._fetch_orderbook(token_id)
            if orderbook_response is not None:
                orderbook_asks = orderbook_response.get("asks", [])
            else:
                self.context.logger.warning(
                    "Orderbook fetch failed. Kelly will receive empty orderbook."
                )
else:
    # FPMM: market_price from outcomeTokenMarginalPrices
    prices = bet.outcomeTokenMarginalPrices
    if prices is not None:
        market_price = prices[prediction_response.vote]
```

**Modify `get_bet_amount()` call:**

```python
bet_amount = yield from self.get_bet_amount(
    prediction_response.win_probability,
    prediction_response.confidence,
    selected_type_tokens_in_pool,
    other_tokens_in_pool,
    bet.fee,
    self.synchronized_data.weighted_accuracy,
    bet.collateralToken,
    market_type=market_type,
    orderbook_asks=orderbook_asks,
    market_price=market_price,
)
```

**After `get_bet_amount()` — simplified profitability for Kelly:**

```python
# If using Kelly strategy, the strategy itself determines profitability
# via log-growth optimization. If bet_amount > 0, the bet improves log-growth.
# No bet_threshold check — Kelly already handles minimum viable bets via
# min_bet and fee_per_trade. bet_threshold is redundant here.
if self.params.using_kelly:
    if bet_amount <= 0:
        return False, 0

    # Extract extra info from strategy result
    g_improvement = getattr(self, '_last_strategy_result', {}).get('g_improvement', 0.0)
    expected_shares = getattr(self, '_last_strategy_result', {}).get('expected_shares', 0)

    net_bet_amount = remove_fraction_wei(bet_amount, self.convert_to_native(bet.fee))
    potential_net_profit = expected_shares - net_bet_amount

    token_name = self.get_token_name()
    self.context.logger.info(
        f"Kelly bet: {self.convert_to_native(bet_amount)} {token_name}, "
        f"G_improvement: {g_improvement:.6f}, "
        f"expected_shares: {self.convert_to_native(expected_shares)} {token_name}"
    )

    # Only check rebet (position management — prevents re-entering same market
    # without sufficient liquidity/prediction change). Not a profitability check.
    is_profitable = self.rebet_allowed(prediction_response, potential_net_profit)

    return is_profitable, bet_amount

# For non-Kelly strategies (bet_amount_per_threshold), keep existing logic:
# ... existing Omenstrat / Polystrat profitability checks unchanged ...
```

#### 3.3.3 Changes to `base.py` — `get_bet_amount()`

**File:** `packages/valory/skills/decision_maker_abci/behaviours/base.py`

**Extend signature:**

```python
def get_bet_amount(
    self,
    win_probability: float,
    confidence: float,
    selected_type_tokens_in_pool: int,
    other_tokens_in_pool: int,
    bet_fee: int,
    weighted_accuracy: float,
    collateral_token: str,
    market_type: str = "fpmm",
    orderbook_asks: Optional[List[Dict[str, str]]] = None,
    market_price: float = 0.0,
) -> Generator[None, None, int]:
```

**Map old strategy name to new (backward compat):**

```python
# In the while loop, before executing:
if next_strategy == STRATEGY_KELLY_CRITERION_NO_CONF:
    next_strategy = STRATEGY_KELLY_CRITERION
```

**Add new kwargs before `execute_strategy()` call:**

```python
kwargs.update({
    "trading_strategy": next_strategy,
    "bankroll": bankroll,
    "win_probability": win_probability,
    "confidence": confidence,
    "selected_type_tokens_in_pool": selected_type_tokens_in_pool,
    "other_tokens_in_pool": other_tokens_in_pool,
    "bet_fee": bet_fee,
    "weighted_accuracy": weighted_accuracy,
    "market_type": market_type,          # NEW
    "orderbook_asks": orderbook_asks,    # NEW
    "market_price": market_price,        # NEW
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
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
```

Keep `KELLY_CRITERION_NO_CONF` in the enum for backward compatibility — users may have
this value persisted in `chatui_param_store.json` and historical bet records in the
subgraph will reference it.

Also update the prompt text that describes the strategy to reflect the new algorithm.

#### 3.4.2 `chatui_abci/handlers.py`

Update `_get_ui_trading_strategy()` to map **both** names to RISKY:
```python
if selected_value in (
    TradingStrategy.KELLY_CRITERION.value,
    TradingStrategy.KELLY_CRITERION_NO_CONF.value,
):
    return TradingStrategyUI.RISKY
```

#### 3.4.3 `trader_abci/handlers.py`

Same change — map both kelly names to RISKY.

#### 3.4.4 `agent_performance_summary_abci/graph_tooling/predictions_helper.py`

**New:**
```python
class TradingStrategy(enum.Enum):
    KELLY_CRITERION = "kelly_criterion"
    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"  # backward compat
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
```

Update `_get_ui_trading_strategy()` to map both kelly names to RISKY.

#### 3.4.5 `agent_performance_summary_abci/graph_tooling/polymarket_predictions_helper.py`

Same — update `strategy_map` to include both kelly names → RISKY:
```python
strategy_map = {
    TradingStrategy.KELLY_CRITERION.value: TradingStrategyUI.RISKY.value,
    TradingStrategy.KELLY_CRITERION_NO_CONF.value: TradingStrategyUI.RISKY.value,
    TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value: TradingStrategyUI.BALANCED.value,
}
```

#### 3.4.6 `decision_maker_abci/models.py`

`STRATEGY_KELLY_CRITERION = "kelly_criterion"` — already correct (line 71).

Add a constant for the old name and update `using_kelly` to match both:
```python
STRATEGY_KELLY_CRITERION = "kelly_criterion"
STRATEGY_KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"  # backward compat

@property
def using_kelly(self) -> bool:
    return self.trading_strategy in (
        STRATEGY_KELLY_CRITERION,
        STRATEGY_KELLY_CRITERION_NO_CONF,
    )
```

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
  n_bets: 1
  min_edge: 0.03
  min_oracle_prob: 0.5
  fee_per_trade: 0.01
  grid_points: 500
  absolute_min_bet_size: 10000000000000000
  bet_amount_per_threshold:
    0.0: 0
    ...
```

Remove `bet_kelly_fraction`. Add Kelly hyperparameters.

#### 3.5.2 Service/Agent YAML Files

Update these files to:
- Change `trading_strategy` default to `"kelly_criterion"`
- Update `strategies_kwargs` to match new params
- Update dependency hashes after package changes

**Files:**
- `packages/valory/services/trader/service.yaml`
- `packages/valory/services/trader_pearl/service.yaml`
- `packages/valory/services/polymarket_trader/service.yaml`
- `packages/valory/agents/trader/aea-config.yaml`
- `packages/valory/skills/trader_abci/skill.yaml`

### 3.6 Delete Old Strategies

**Delete entirely:**
- `packages/jhehemann/customs/kelly_criterion/` — legacy Kelly WITH confidence
- `packages/valory/customs/kelly_criterion_no_conf/` — Kelly WITHOUT confidence

**Update `packages/packages.json`:**
- Remove entries for both deleted packages
- Add entry for new `valory/customs/kelly_criterion`

**Update agent/service YAML files:**
- Remove dependencies on deleted packages
- Add dependency on new `valory/customs/kelly_criterion`

---

## 4. Test Plan (TDD)

### 4.1 New Strategy Tests

**File:** `packages/valory/customs/kelly_criterion/tests/test_kelly_criterion.py`

| Test | Description | Key Assertion |
|------|-------------|---------------|
| `test_missing_required_fields` | Call `run()` with missing bankroll | Returns `error` with missing fields list |
| `test_bankroll_below_floor` | bankroll < floor_balance | `bet_amount == 0` |
| `test_zero_bankroll` | bankroll = 0 | `bet_amount == 0` |
| `test_invalid_win_probability` | p = 1.5 or p = -0.1 | `bet_amount == 0`, error message |
| `test_invalid_market_price` | market_price = 0 or 1.5 | `bet_amount == 0` |
| `test_edge_below_min_edge` | p=0.53, market_price=0.52, min_edge=0.03 | `bet_amount == 0` |
| `test_oracle_prob_below_min` | p=0.4, min_oracle_prob=0.5 | `bet_amount == 0` |
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
| `test_only_predicted_side_evaluated` | Only mech's predicted side evaluated | Only one side in info logs |
| `test_full_integration_clob` | Realistic CLOB scenario | Non-zero bet with positive G_improvement |
| `test_full_integration_fpmm` | Realistic FPMM scenario | Non-zero bet with positive G_improvement |
| `test_unknown_kwargs_no_crash` | Pass extra unknown kwargs | No error, strategy ignores them |
| `test_return_format` | Any valid call | Dict has bet_amount, expected_shares, g_improvement, info, error |

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
| `test_is_profitable_clob_kelly_positive` | Kelly returns bet_amount > 0, g_improvement > 0 → is_profitable = True |
| `test_is_profitable_clob_kelly_zero` | Kelly returns bet_amount = 0 → is_profitable = False |
| `test_is_profitable_clob_rebet_rejected` | rebet_allowed returns False → is_profitable = False despite Kelly positive |
| `test_is_profitable_fpmm_kelly` | FPMM market, Kelly returns positive → is_profitable = True |
| `test_is_profitable_non_kelly_unchanged` | bet_amount_per_threshold strategy → existing logic unchanged |
| `test_orderbook_fetch_failure_fallback` | Orderbook fetch fails → Kelly gets empty asks, returns 0 |

### 4.4 Base Behaviour Tests

**File:** `packages/valory/skills/decision_maker_abci/tests/behaviours/test_base.py`

| Test | Description |
|------|-------------|
| `test_get_bet_amount_passes_market_type` | market_type kwarg reaches strategy |
| `test_get_bet_amount_passes_orderbook` | orderbook_asks kwarg reaches strategy |
| `test_get_bet_amount_passes_market_price` | market_price kwarg reaches strategy |
| `test_last_strategy_result_stored` | After execute_strategy, _last_strategy_result is set |
| `test_strategies_kwargs_no_bet_kelly_fraction` | STRATEGIES_KWARGS updated without bet_kelly_fraction |

### 4.5 Enum/Handler Tests

Update existing tests that reference `kelly_criterion_no_conf` to use `kelly_criterion` in:
- `chatui_abci/tests/test_handlers.py`
- `chatui_abci/tests/test_prompts.py`
- `chatui_abci/tests/test_models.py`
- `trader_abci/tests/test_handlers.py`
- `agent_performance_summary_abci/tests/graph_tooling/test_predictions_helper.py`
- `agent_performance_summary_abci/tests/graph_tooling/test_polymarket_predictions_helper.py`
- `decision_maker_abci/tests/test_models.py`

---

## 5. Verification Checklist

```bash
# 1. New strategy tests
poetry run pytest packages/valory/customs/kelly_criterion/tests/ -v

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

# 9. Verify no old references remain
grep -r "kelly_criterion_no_conf" packages/
grep -r "jhehemann.*kelly" packages/

# 10. Coverage (must not drop)
# Check tox coverage job output
```

---

## 6. Execution Order

```
1. Write strategy tests first (TDD)
2. Implement kelly_criterion.py to pass tests
3. Write connection tests
4. Implement FETCH_ORDER_BOOK in connection
5. Write decision_receive tests
6. Implement decision_receive integration
7. Update all enums and handler references (with tests)
8. Update YAML configurations
9. Delete old kelly strategies
10. Update packages.json and run autonomy packages lock
11. Run full test suite and linting
```

---

## 7. Risk Considerations

| Risk | Mitigation |
|------|------------|
| Strategy `exec()` sandbox doesn't have `math` | Strategy file imports `math` at top — `exec()` runs the full file which creates the import |
| Orderbook stale by execution time | Acceptable for sizing; actual execution uses fresh order at placement time |
| Operators have old `bet_kelly_fraction` in config | Config YAML is updated in this PR. Operators must update their overrides. |
| FPMM Kelly gives different results than old quadratic | Expected — grid search is more correct. Differences should be small for well-balanced pools. Document in PR. |
| Independent side evaluation | Deferred — V1 only evaluates mech's predicted side. Decision pending on whether to add this. |
