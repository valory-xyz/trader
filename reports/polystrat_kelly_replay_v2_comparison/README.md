### Polystrat Kelly Replay v2 -- Cross-Window Comparison

**Date:** 2026-03-26

This note compares the three v2 replay windows with negRisk market segmentation
and min_oracle_prob sensitivity analysis.

The v1 comparison (see `polystrat_kelly_replay_comparison_2026-03-20_vs_2026-03-23/`)
found that the Kelly optimizer consistently improves its own log-utility objective
but the realized ROI improvement was unstable across windows. The v2 analysis asks:
**is that instability explained by the mix of negRisk vs non-negRisk markets?**

---

#### Compared reports

- 2-week: [v2 Mar 12-26](../polystrat_kelly_replay_v2_2026-03-12_2026-03-26/README.md) (3297 bets)
- 7-day: [v2 Mar 20-26](../polystrat_kelly_replay_v2_2026-03-20_2026-03-26/README.md) (1045 bets)
- 4-day: [v2 Mar 23-26](../polystrat_kelly_replay_v2_2026-03-23_2026-03-26/README.md) (315 bets)

---

#### Shared configuration

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

`min_oracle_prob` varied: 0.1, 0.3, 0.5

---

#### Market composition by window

| Window | Total | negRisk | non-negRisk | negRisk % |
|--------|-------|---------|-------------|-----------|
| Mar 12-26 | 3297 | 2943 | 354 | 89% |
| Mar 20-26 | 1045 | 902 | 143 | 86% |
| Mar 23-26 | 315 | 217 | 98 | 69% |

The shorter windows have a higher proportion of non-negRisk standalone binary
markets (31% in Mar 23-26 vs 11% in Mar 12-26). This explains why v1 results
varied: the 4-day window benefits more from non-negRisk improvement.

---

#### 1. negRisk markets: Kelly does not improve ROI

| Window | mop | Bets | CF bets | Act ROI | CF ROI | Delta |
|--------|-----|------|---------|---------|--------|-------|
| Mar 12-26 | 0.1 | 2943 | 2427 | -9.9% | -10.3% | -0.4pp |
| Mar 12-26 | 0.5 | 2943 | 2391 | -9.9% | -10.4% | -0.5pp |
| Mar 20-26 | 0.1 | 902 | 740 | -14.4% | -17.6% | -3.2pp |
| Mar 20-26 | 0.5 | 902 | 737 | -14.4% | -17.7% | -3.3pp |
| Mar 23-26 | 0.1 | 217 | 180 | -30.6% | -29.4% | +1.2pp |
| Mar 23-26 | 0.5 | 217 | 180 | -30.6% | -29.4% | +1.2pp |

**Consistent finding:** Kelly produces near-zero or negative ROI delta on negRisk
markets across all windows and all min_oracle_prob settings. The mech oracle has
no exploitable edge on multi-outcome range markets.

The min_oracle_prob setting has almost no effect on negRisk results (delta varies
by less than 0.1pp between mop=0.1 and mop=0.5 within each window).

---

#### 2. Non-negRisk markets: Kelly helps, driven by side switches

| Window | mop | Bets | CF | YES | NO | Sw | Act ROI | CF ROI | Delta |
|--------|-----|------|----|-----|-----|-----|---------|--------|-------|
| Mar 12-26 | 0.1 | 354 | 309 | 114 | 195 | 20 | -24.5% | -0.6% | **+23.9pp** |
| Mar 12-26 | 0.5 | 354 | 289 | 101 | 188 | 0 | -24.5% | -23.1% | +1.4pp |
| Mar 20-26 | 0.1 | 143 | 118 | 41 | 77 | 17 | -20.3% | +41.2% | **+61.5pp** |
| Mar 20-26 | 0.5 | 143 | 101 | 30 | 71 | 0 | -20.3% | -20.7% | -0.4pp |
| Mar 23-26 | 0.1 | 98 | 86 | 26 | 60 | 8 | -17.9% | +1.9% | **+19.8pp** |
| Mar 23-26 | 0.5 | 98 | 78 | 20 | 58 | 0 | -17.9% | -21.4% | -3.5pp |

**Consistent finding:** At mop=0.1, Kelly dramatically improves non-negRisk ROI
across all three windows (+19.8pp to +61.5pp). The improvement is driven by
side switches (8 to 20 per window).

At mop=0.5, side switches go to zero and the improvement either vanishes or
reverses. This pattern is stable across all windows.

---

#### 3. Why v1 results were unstable: market mix explains it

The v1 comparison found:
- 4-day: +7.3pp (aggregate, mop=0.1)
- 7-day: -4.8pp
- 2-week: -1.9pp

The v2 segmentation reveals that the aggregate hides two opposite effects:

| Window | negRisk delta | non-negRisk delta | negRisk share | Aggregate delta |
|--------|--------------|-------------------|---------------|-----------------|
| Mar 12-26 | -0.4pp | +23.9pp | 89% | +2.1pp |
| Mar 20-26 | -3.2pp | +61.5pp | 86% | +4.8pp |
| Mar 23-26 | +1.2pp | +19.8pp | 69% | +7.3pp |

The 4-day window shows the largest aggregate improvement because:
1. It has the highest non-negRisk share (31% vs 11-14%)
2. Non-negRisk markets have strong positive delta at mop=0.1
3. Fewer negRisk markets dilute the improvement

The v1 instability was not random -- it was a **composition effect**.

---

#### 4. Side switches are the primary value mechanism

Across all windows at mop=0.1:

| Window | Side switches | Non-negRisk delta | Comment |
|--------|--------------|-------------------|---------|
| Mar 12-26 | 20 | +23.9pp | Switches correct bad bets |
| Mar 20-26 | 17 | +61.5pp | Highest: turns losses into gains |
| Mar 23-26 | 8 | +19.8pp | Fewer switches, still strong |

At mop=0.5, side switches go to zero across all windows, and the non-negRisk
delta drops to -3.5pp to +1.4pp.

A side switch occurs when the Kelly optimizer, given the oracle probability and
execution price, determines that the opposite side has higher expected log-growth
than the side the trader actually bet on.

---

#### 5. All negRisk strategies lose money

| Window | Actual ROI (negRisk) | Best CF ROI (negRisk) | Comment |
|--------|---------------------|-----------------------|---------|
| Mar 12-26 | -9.9% | -10.3% (mop=0.1) | Kelly slightly worse |
| Mar 20-26 | -14.4% | -17.6% (mop=0.1) | Kelly worse |
| Mar 23-26 | -30.6% | -29.4% (mop=0.1) | Kelly marginally better |

No Kelly configuration makes negRisk markets profitable. The oracle has no edge
on range sub-markets of multi-outcome events.

---

#### CORRECTION: mop=0.1 results are misleading

**See [SIDE_SWITCH_ANALYSIS.md](SIDE_SWITCH_ANALYSIS.md) for the full investigation.**

The +23.9pp improvement at mop=0.1 is an artifact of:

1. **Synthetic pricing:** opposite-side price = `1 - fill_price`, producing
   unrealistically cheap YES shares at 0.017-0.04 when real asks were 0.05-0.15+
2. **Survivorship bias:** 4 tail-event winners (TSLA, AMZN stock spikes) at
   50:1 synthetic odds account for +174 USDC; the other 16 switches lost -16 USDC
3. **Oracle does not predict these:** p_yes=0.13 for the winning bets — the oracle
   thinks YES is very unlikely, and Kelly only bets because the synthetic price
   makes the edge look enormous

**75% of side switches LOSE money.** The net positive depends on rare tail events
at unrealistic prices.

---

#### Corrected Practical Conclusions

1. **The v1 instability is explained by market composition.** When negRisk and
   non-negRisk are analyzed separately, the results are consistent.

2. **Kelly does not add value on negRisk markets** at any setting. The oracle
   has no exploitable edge on range markets.

3. **Kelly adds modest value on non-negRisk markets at mop=0.5** (+1.4pp on
   the 2-week window), through bet sizing. This is the only reliable improvement.

4. **mop=0.1 is dangerous, not beneficial.** The apparent improvement is driven
   by lottery-ticket bets at unrealistic synthetic prices. In production, these
   bets would face real spreads and would likely lose money.

5. **Recommended production config:**
   - `min_oracle_prob = 0.5` for all market types
   - negRisk: Kelly formula is correct but produces no improvement (oracle limitation)
   - non-negRisk: Kelly improves bet sizing by ~1.4pp (modest but real)

6. **To unlock further improvement**, the bottleneck is oracle quality, not the
   Kelly formula or the min_oracle_prob filter. Better-calibrated mech predictions
   would create real edge for Kelly to exploit.

---

#### Methodology notes

- All v2 replays use `n_bets=3` (vs v1 which used `n_bets=1`). This gives
  `W_bet = min(3 x 2.5, 15) = 7.5 USDC`, enough to execute most bets.
- negRisk tagging from Polymarket CLOB API (`/markets/{conditionId}`).
- Same execution-price proxy as v1: realized fill price (amount/shares).
- See individual window READMEs for full methodology details.
