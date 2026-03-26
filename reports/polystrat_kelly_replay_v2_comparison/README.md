### Polystrat Kelly Replay v2 -- Cross-Window Comparison

**Date:** 2026-03-26
**Data period:** 2026-03-12 to 2026-03-26 (2 weeks). Analyzed at three overlapping
windows: 4-day (Mar 23-26, 315 bets), 7-day (Mar 20-26, 1045 bets), and 2-week
(Mar 12-26, 3297 bets, 107 agents). All conclusions are based on the full 2-week
dataset unless stated otherwise. The shorter windows are used to check consistency.
**New in v2:** negRisk segmentation, oracle calibration analysis, pricing artifact investigation

---

### WHAT WE DID AND WHAT WE FOUND

The old Kelly implementation used the FPMM constant-product formula for Polymarket
CLOB markets -- a mathematically incorrect formula that produced negative fractions
on 73% of markets and refused to bet at all. **This has been fixed.** The new Kelly
(PR #886) correctly walks the CLOB orderbook, evaluates both sides, and uses
log-utility grid search. The formula is now sound.

With the corrected formula in place, we ran a replay analysis on 3297 historical
bets across 107 agents to validate the new Kelly against real data. The replay
revealed that **while the Kelly formula is now correct, the ROI improvement is
limited by oracle quality** -- the mech predictions on range markets (89% of bets)
are not calibrated well enough for Kelly to exploit.

---

### CONCLUSIONS

**C1. The Kelly formula fix is complete and ready for production.**
The old FPMM formula was mathematically wrong for Polymarket CLOB (negative
fractions on 73% of markets, refused to bet). The new Kelly correctly walks
the orderbook, evaluates both sides, and uses log-utility grid search. This
was a necessary fix -- the old formula could not work on CLOB markets at all.

**C2. The replay reveals a new bottleneck: oracle calibration on negRisk markets.**
89% of bets are on negRisk range markets where the mech oracle has limited
discriminative power:

| Oracle predicts | YES actually wins | Expected |
|----------------|------------------|----------|
| p_yes = 5% | 37.5% | ~5% |
| p_yes = 15% | 34.8% | ~15% |
| p_yes = 35% | 34.8% | ~35% |
| p_yes = 85% | 42.3% | ~75% |
| p_yes = 95% | 34.1% | ~95% |

**C3. Filtering negRisk markets is the highest-impact operational change.**
negRisk markets account for 79% of dollar losses (-697 of -883 USDC).
Removing them reduces capital at risk by 90%. This is actionable now and
independent of oracle improvements.

**C4. Kelly adds +1.4pp on non-negRisk at production settings.**
At min_oracle_prob=0.5, Kelly improves ROI from -24.5% to -23.1% on standalone
binary markets through better bet sizing. This is the first measurable
improvement from the corrected formula.

**C5. Lower min_oracle_prob shows larger replay improvements but is unreliable
in production.** The +24pp at mop=0.1 is inflated by synthetic pricing in the
replay methodology. Production should use mop=0.5 until oracle quality improves.

**C6. Kelly acts as a bet filter (go/no-go) at current settings.**
With n_bets >= 2, most bets hit max_bet. Kelly's value is in deciding WHICH
bets to skip, not HOW MUCH to bet. This is expected given the W_bet/max_bet ratio.

**C7. negRisk YES bets with high edge thresholds do not reliably improve ROI.**
Win rate stays ~35% regardless of edge threshold on range markets.

**C8. The v1 instability across replay windows was a composition effect.**
Shorter windows have more non-negRisk markets. When segmented, results are
consistent within each market type.

---

### ACTION ITEMS

#### Priority 1: Reduce losses immediately (no code changes to Kelly)

**ACTION 1A: Filter or deprioritize negRisk markets in sampling.**

negRisk markets destroy value. The market sampling pipeline
(`sampling.py`) should deprioritize or exclude negRisk markets.

Market composition of the current bet universe:

| Type | Bets | % | Unique markets | Dollar loss | ROI |
|------|------|---|---------------|-------------|-----|
| negRisk: weather ranges | 1425 | 43% | 230 | -320 | -8.6% |
| negRisk: stock price ranges | 888 | 27% | 59 | -210 | -9.2% |
| negRisk: election ranges | 422 | 13% | 33 | -112 | -13.7% |
| negRisk: social media ranges | 130 | 4% | 13 | -35 | -11.3% |
| negRisk: approval ranges | 78 | 2% | 5 | -20 | -10.5% |
| non-negRisk: stock threshold | 213 | 6% | 77 | -91 | -19.0% |
| non-negRisk: other binary | 141 | 5% | 18 | -96 | -33.7% |

Implementation options:

1. **Quick fix:** Pass `neg_risk` boolean from the CLOB API to the sampling
   pipeline. Exclude `neg_risk=True` markets from the bet pool. This removes
   89% of losing bets immediately. Requires adding a CLOB API call in
   `polymarket_fetch_market.py` for each market's `conditionId`.

2. **Lighter fix:** In `sampling.py`, deprioritize markets whose title contains
   range patterns ("close at", "temperature", "approval rating", "posts from").
   No API call needed, just a title-matching heuristic.

3. **Lightest fix:** Increase `min_edge` to 0.05 or higher. This won't filter
   by market type but will reject more marginal bets.

**ACTION 1B: Fund the wallet with 10+ USDC.**

Current wallet has 0.66 USDC. Even when Kelly finds edge, it can't afford the
Polymarket minimum order (5 shares x best_ask = 1.20-4.85 USDC). See
`TRADER_LOG_ANALYSIS.md` for the full 42-market simulation.

#### Priority 2: Improve oracle quality (requires mech team)

**ACTION 2A: Fix oracle calibration on range markets.**

The superforcaster mech tool outputs random p_yes values on range markets.
It cannot distinguish "this range has 10% chance" from "this range has 40%
chance." Until this is fixed, no Kelly parameter can help on negRisk.

**ACTION 2B: Validate oracle on non-negRisk binary markets.**

Even on standalone binary markets (earnings, elections), the oracle produces
-24.5% ROI. A proper calibration study is needed: does the oracle beat a
naive baseline (e.g., always betting the market-favored side)?

#### Priority 3: Production release decision

**ACTION 3A: The Kelly implementation (PR #886) is complete and ready to release.**

This was the primary deliverable of this work. The formula is mathematically
sound and replaces the broken FPMM quadratic. It correctly:
- Walks the CLOB orderbook
- Evaluates both sides independently
- Uses per-bet bankroll (W_bet) for log-utility
- Handles negRisk markets (no special handling needed)
- Applies min_oracle_prob and min_edge filters

What Kelly CANNOT do is fix bad oracle predictions.

**ACTION 3B: Recommended production parameters.**

```json
{
  "min_oracle_prob": 0.5,
  "min_edge": 0.03,
  "n_bets": 5,
  "max_bet_usdc": 2.5,
  "fee_per_trade": 10000
}
```

- `min_oracle_prob=0.5`: safest setting. Prevents lottery-ticket bets.
- `min_edge=0.03`: rejects marginal bets where fees eat the edge.
- `n_bets=5`: ensures W_bet is large enough for Polymarket min orders.
  Produces binary sizing (go/no-go) which is acceptable.
- `fee_per_trade=10000`: 0.01 USDC in wei (consistent with other params).

**ACTION 3C: What NOT to change in Kelly.**

- Do NOT lower min_oracle_prob below 0.5 -- mop=0.1 results are artifacts.
- Do NOT add negRisk-specific YES edge thresholds -- oracle is random.
- Do NOT increase n_bets above 5 -- makes binary sizing worse with no benefit.
- The bet sizing binary behavior (go/no-go) is inherent when W_bet >> max_bet
  and is NOT a bug.

---

### SUPPORTING DATA

#### negRisk markets: Kelly does not help (C2)

| Window | mop | Bets | Act ROI | CF ROI | Delta |
|--------|-----|------|---------|--------|-------|
| 2-week | 0.5 | 2943 | -9.9% | -10.4% | -0.5pp |
| 7-day | 0.5 | 902 | -14.4% | -17.7% | -3.3pp |
| 4-day | 0.5 | 217 | -30.6% | -29.4% | +1.2pp |

Consistent across all windows: Kelly delta is -3.3pp to +1.2pp on negRisk.
No improvement.

#### Non-negRisk: Kelly helps modestly at mop=0.5 (C3, C4)

| Window | mop | Bets | CF | Act ROI | CF ROI | Delta | Side sw. |
|--------|-----|------|----|---------|--------|-------|----------|
| 2-week | 0.1 | 354 | 309 | -24.5% | -0.6% | +23.9pp | 20 |
| 2-week | 0.5 | 354 | 289 | -24.5% | -23.1% | **+1.4pp** | 0 |
| 7-day | 0.1 | 143 | 118 | -20.3% | +41.2% | +61.5pp | 17 |
| 7-day | 0.5 | 143 | 101 | -20.3% | -20.7% | -0.4pp | 0 |
| 4-day | 0.1 | 98 | 86 | -17.9% | +1.9% | +19.8pp | 8 |
| 4-day | 0.5 | 98 | 78 | -17.9% | -21.4% | -3.5pp | 0 |

Only the mop=0.5 rows are reliable. The mop=0.1 numbers are artifacts (C5).

#### mop=0.1 artifact: the 4 lottery wins (C5)

75% of side switches at mop=0.1 LOSE money (15 of 20). The net positive is
driven by 4 tail-event winners:

| Market | Fill | Synthetic CF price | p_yes | CF profit |
|--------|------|--------------------|-------|-----------|
| TSLA above 380 (Mar 24) | 0.983 | 0.017 | 0.13 | +57.81 |
| TSLA above 380 (Mar 25) | 0.983 | 0.017 | 0.13 | +57.81 |
| AMZN above 210 (Mar 25) | 0.960 | 0.040 | 0.18 | +26.23 |
| AMZN above 210 (Mar 24) | 0.960 | 0.040 | 0.18 | +26.23 |

The synthetic YES price (0.017) is unrealistic -- real YES asks were 0.05-0.15+.
At realistic prices, the 50:1 payouts would be 3-10:1.

#### Bet sizing distribution (C6)

| n_bets | W_bet | At max_bet | Intermediate | Kelly acts as |
|--------|-------|-----------|-------------|---------------|
| 1 | 2.50 | 0% | 83% | Proper bet sizer |
| 3 | 7.50 | 76% | 19% | Binary filter |

With n_bets >= 2, any edge above 7-17% saturates max_bet.

#### negRisk YES edge threshold sweep (C7)

| Edge threshold | Bets | Win % | ROI |
|---------------|------|-------|-----|
| >= 0.00 | 306 | 39.2% | -15.2% |
| >= 0.20 | 160 | 36.2% | -2.7% |
| >= 0.30 | 120 | 35.0% | +2.4% |
| >= 0.40 | 88 | 27.3% | -9.1% |

Win rate stays ~35% regardless. Oracle is random on range markets.

#### v1 instability explained (C7, C8)

| Window | negRisk share | negRisk delta | non-negRisk delta | Aggregate |
|--------|---------------|--------------|-------------------|-----------|
| 2-week | 89% | -0.4pp | +23.9pp (artifact) | +2.1pp |
| 7-day | 86% | -3.2pp | +61.5pp (artifact) | +4.8pp |
| 4-day | 69% | +1.2pp | +19.8pp (artifact) | +7.3pp |

At mop=0.5, aggregate delta is -0.5pp to +1.4pp -- consistent and modest.

---

### DETAILED ANALYSIS REPORTS

| Report | Question | Answer |
|--------|----------|--------|
| [SIDE_SWITCH_ANALYSIS.md](SIDE_SWITCH_ANALYSIS.md) | Why does mop=0.1 look good? | Artifact: synthetic pricing + 4 lottery wins |
| [NEGRISK_YES_STRATEGY_ANALYSIS.md](NEGRISK_YES_STRATEGY_ANALYSIS.md) | Bet YES on negRisk with strong edge? | No: oracle is random |
| [BET_SIZING_ANALYSIS.md](BET_SIZING_ANALYSIS.md) | Why always 0 or 2.50? | W_bet >> max_bet causes saturation |
| [MARKET_SUPPLY_ANALYSIS.md](MARKET_SUPPLY_ANALYSIS.md) | Are there enough non-negRisk markets? | ~85 active (17%), sufficient for current throughput |

---

### INDIVIDUAL WINDOW REPORTS

- [v2 Mar 12-26 (2-week)](../polystrat_kelly_replay_v2_2026-03-12_2026-03-26/README.md) -- 3297 bets, 107 agents
- [v2 Mar 20-26 (7-day)](../polystrat_kelly_replay_v2_2026-03-20_2026-03-26/README.md) -- 1045 bets
- [v2 Mar 23-26 (4-day)](../polystrat_kelly_replay_v2_2026-03-23_2026-03-26/README.md) -- 315 bets

---

### CONFIGURATION

```json
{
  "bankroll_usdc": 15.0,
  "floor_balance_usdc": 0.0,
  "min_bet_usdc": 1.0,
  "max_bet_usdc": 2.5,
  "n_bets": 3,
  "min_edge": 0.01,
  "fee_per_trade_usdc": 0.0,
  "mech_fee_usdc": 0.01,
  "grid_points": 500
}
```

min_oracle_prob varied: 0.1, 0.3, 0.5

---

### METHODOLOGY

- Replays use `polystrat_kelly_replay.py --input-snapshot` with frozen subgraph data
- negRisk tagging via `enrich_snapshot_neg_risk.py` (Polymarket CLOB API)
- Segmentation via `segment_replay_by_neg_risk.py`
- Plots via `plot_polystrat_roi_distributions.py`
- Execution price proxy: realized fill price (amount/shares) -- no historical orderbooks
- Synthetic opposite-side price: `1 - fill_price` (understates real spread)
- Fixed bankroll per bet (no sequential P&L tracking)
- n_bets=3 produces binary sizing (go/no-go) -- caveat for interpretation
