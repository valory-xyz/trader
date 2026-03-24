# Unified Kelly Algorithm Spec

## Purpose

This document is the normative algorithm specification for the unified Kelly
strategy used by trader.

It exists to define:

- the optimization objective
- the venue-specific execution models
- the parameter contract and units
- the output contract
- the known approximations and accepted limitations

This is distinct from the implementation plan:

- `plans/KELLY_IMPLEMENTATION_PLAN.md` explains rollout and integration work
- this document defines the algorithm itself

---

## Scope

The unified Kelly strategy applies to binary markets on:

- Polymarket, modeled as a CLOB
- Omen, modeled as an FPMM

The strategy:

- evaluates both YES and NO independently
- compares all admissible bets against a no-trade baseline
- returns the side and size with the highest positive log-growth improvement

If no candidate improves the objective over no trade, the strategy returns no bet.

---

## Definitions

Let:

- `p_yes` be the oracle probability for YES
- `p_no = 1 - p_yes`
- `vote = 0` denote YES
- `vote = 1` denote NO
- `W_total` be current bankroll
- `floor_balance` be the reserve not available for betting
- `W = W_total - floor_balance`
- `max_bet` be the hard per-trade cap
- `n_bets` be the bankroll-depth parameter
- `W_bet = min(n_bets * max_bet, W)`

The strategy evaluates one side at a time. For a given side:

- `p` is the probability of that side winning
- `cost(b)` is the modeled spend for candidate bet `b`
- `shares(b)` is the number of payout-1 shares obtained by executing `b`
- `fee_per_trade` is external friction only

External friction means:

- mech costs today
- optionally gas in future

It does not include venue/market trading fees.

---

## Objective

For each candidate bet `b`, the strategy evaluates expected log wealth:

```text
G(b) = p * log(W_bet - cost(b) + shares(b) - fee_per_trade)
     + (1 - p) * log(W_bet - cost(b) - fee_per_trade)
```

The no-trade baseline is:

```text
G_0 = log(W_bet)
```

The optimizer selects the admissible bet with maximum `G(b)`.

The strategy only returns a trade if:

```text
G(b*) > G_0
```

where `b*` is the best candidate for the evaluated side.

The final selected trade is the side/size pair with the highest positive:

```text
G_improvement = G(b*) - G_0
```

---

## Side Evaluation

The strategy evaluates both sides independently:

- YES side:
  - `vote = 0`
  - `p = p_yes`
- NO side:
  - `vote = 1`
  - `p = p_no`

For each side:

1. apply side-level admissibility filters
2. construct venue-specific execution inputs
3. optimize over candidate bet sizes
4. compare best side result against no trade

The strategy then returns the side with the largest positive `G_improvement`.

If neither side beats no trade, return no bet.

---

## Admissibility Filters

For each side, define:

- `price` = current market price for that side
- `edge = p - price`

The side is rejected before optimization if either:

```text
edge < min_edge
```

or:

```text
p < min_oracle_prob
```

These are policy/risk filters, not part of the Kelly objective itself.

---

## Candidate Grid

For an admissible side, candidate bet sizes are evaluated on a grid over:

```text
b in [b_lower_side, b_max]
```

where:

- `b_max = max_bet`
- `b_lower_side = max(min_bet, venue_min_side)`
- `venue_min_side` is venue-specific

If `grid_points < 2`, use `2`.

The grid is:

```text
step = (b_max - b_lower_side) / (grid_points - 1)
b_i = b_lower_side + i * step
```

for `i = 0, ..., grid_points - 1`.

---

## Venue Execution Models

### Polymarket (CLOB)

Inputs:

- `orderbook_asks_yes`
- `orderbook_asks_no`
- `min_order_shares`

Each ask level has:

- `price`
- `size`

For a given side, execution is modeled by walking the ask book from lowest to
highest price until the spend budget is exhausted.

For candidate spend `b`:

- `cost(b)` is the actual spend consumed by the walk
- `shares(b)` is the total shares filled by the walk

This is a market-buy execution model.

#### CLOB Minimum Spend

For Polymarket, the venue-side minimum spend should be computed from the actual
cost of acquiring `min_order_shares` from the ask book.

```text
venue_min_side = cost_to_buy(min_order_shares, ask_book_side)
b_lower_side = max(min_bet, venue_min_side)
```

This means:

- walk the selected side's ask book from best price upward
- accumulate fills until `min_order_shares` is reached
- sum the actual spend required for those fills
- use that spend as `venue_min_side`

Equivalently:

```text
venue_min_side = vwap_min_fill * min_order_shares
```

where `vwap_min_fill` is the VWAP of the first executable `min_order_shares`.

This must not be approximated as `min_order_shares * best_ask_price`, because
top-of-book depth may be smaller than `min_order_shares`.

If the orderbook cannot supply `min_order_shares`, then the side is not
executable and should be rejected before optimization.

### Omen (FPMM)

Inputs:

- `tokens_yes`
- `tokens_no`
- `bet_fee`

For the selected side:

- if buying YES:
  - `x = tokens_yes`
  - `y = tokens_no`
- if buying NO:
  - `x = tokens_no`
  - `y = tokens_yes`

Define:

```text
alpha = 1 - bet_fee
```

with `bet_fee` represented in normalized native units.

Execution model:

```text
cost(b) = b
shares(b) = alpha * b + x - (x * y) / (y + alpha * b)
```

This is the FPMM execution model used for Omen.

For Omen, if no venue-imposed minimum executable spend is modeled, then:

```text
venue_min_side = 0
b_lower_side = min_bet
```

---

## Fee Accounting

Fee handling must be explicit and non-overlapping.

### Venue Fee

Venue fee is part of venue execution.

For Omen:

- venue fee is represented by `bet_fee`
- venue fee is incorporated into `shares(b)` via `alpha`
- it must not be subtracted again downstream

For Polymarket:

- venue trading fee is currently treated as `0` in trader

### External Friction

`fee_per_trade` is separate from venue fee and includes only:

- mech cost now
- optionally gas later

This term appears directly in the Kelly objective and in `expected_profit`.

### Rule

Venue fee and external friction must never be counted twice.

---

## Expected Profit

The strategy returns `expected_profit` for the selected side using the exact same
accounting model as the optimizer.

For the chosen side:

```text
expected_profit = p_selected * shares(b_opt) - cost(b_opt) - fee_per_trade
```

where:

- `p_selected = p_yes` if `vote = 0`
- `p_selected = p_no` if `vote = 1`
- `shares(b_opt)` comes from the venue-specific execution model
- `cost(b_opt)` is the modeled gross spend

This value must not be recomputed downstream using a different price model.

---

## Bankroll and Risk Parameters

### `floor_balance`

Reserve not available for betting.

```text
W = W_total - floor_balance
```

If `W <= 0`, the strategy returns no bet.

### `max_bet`

Hard cap per trade.

This is the primary operational risk cap.

### `n_bets`

Bankroll-depth parameter:

```text
W_bet = min(n_bets * max_bet, W)
```

This changes how aggressively the optimizer sizes within the hard cap.

### `min_bet`

Policy minimum spend.

This is distinct from venue minimum execution constraints.

---

## Parameter Contract

### Common Inputs

| Parameter | Type | Meaning | Unit / Scale | Applies to |
|---|---|---|---|---|
| `bankroll` | int | wallet balance | token native units | both |
| `p_yes` | float | oracle YES probability | `[0,1]` | both |
| `floor_balance` | int | reserved bankroll floor | token native units | both |
| `price_yes` | float | current YES market price | `[0,1]` | both |
| `price_no` | float | current NO market price | `[0,1]` | both |
| `max_bet` | int | hard cap per trade | token native units | both |
| `min_bet` | int | policy minimum spend | token native units | both |
| `n_bets` | int | bankroll-depth parameter | dimensionless | both |
| `min_edge` | float | minimum `p - price` | probability units | both |
| `min_oracle_prob` | float | minimum side probability | probability units | both |
| `fee_per_trade` | float | external friction only | native token units | both |
| `grid_points` | int | optimization grid resolution | dimensionless | both |
| `token_decimals` | int | token scale metadata | decimals | both |

### Polymarket-Specific Inputs

| Parameter | Type | Meaning | Unit / Scale |
|---|---|---|---|
| `orderbook_asks_yes` | list | YES ask levels | price/share strings |
| `orderbook_asks_no` | list | NO ask levels | price/share strings |
| `min_order_shares` | float | venue minimum order size | shares |

### Omen-Specific Inputs

| Parameter | Type | Meaning | Unit / Scale |
|---|---|---|---|
| `tokens_yes` | int | YES pool tokens | native token units |
| `tokens_no` | int | NO pool tokens | native token units |
| `bet_fee` | int or float | venue fee input to `alpha` | normalized native units |

---

## Output Contract

The strategy returns:

| Field | Type | Meaning |
|---|---|---|
| `bet_amount` | int | selected spend in native units; `0` means no trade |
| `vote` | int or `None` | `0 = YES`, `1 = NO`, `None = no trade` |
| `expected_profit` | int | expected profit in native units using optimizer-consistent accounting |
| `g_improvement` | float | log-growth improvement over no trade |
| `info` | list[str] | informational messages |
| `error` | list[str] | validation or execution errors |

---

## No-Trade Conditions

The strategy returns no trade if any of the following holds:

- required inputs are missing
- `W <= 0`
- `p_yes` is invalid
- both sides fail admissibility filters
- venue execution inputs are missing for both sides
- no candidate bet produces positive `G_improvement`

---

## Known Approximations and Open Choices

### Accepted Approximation

Polymarket minimum executable spend may be approximated using:

```text
min_order_shares * best_ask_price
```

This is not exact on thin books and should be treated as an explicit approximation,
not as a fully execution-accurate minimum-fill model.

### Open Parameter-Contract Question

For Polymarket-compatible config values such as `default_max_bet_size` and
`absolute_max_bet_size`, trader must define whether the authoritative
representation is:

- native 6-decimal USDC units
- or a normalized 18-decimal internal scale

This must be resolved in implementation/config docs.

### Execution-Time Validation

This algorithm spec covers sizing, not final placement safety.

If trader wants protection against quote-to-execution drift, execution-time checks
must be defined separately, for example:

- fresh-orderbook validation on Polymarket
- stale-pool / stale-price validation on Omen
- slippage tolerance checks before placement

---

## Relationship to Reference Work

This spec is informed by the Kelly reference work in `kelly_poly` PR #5, but it
is intended to be self-contained and reviewable inside `trader`.

Where trader intentionally matches the reference, this document should say so
directly.

Where trader intentionally differs, this document or the implementation plan
should state the deviation explicitly.
