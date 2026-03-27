### Deep Analysis: n_bets=1 Parameter Tuning

**Date:** 2026-03-26
**Base config:** n_bets=1, max_bet=2.5, bankroll=15, min_edge=0.01, fee=0, mech_fee=0.01
**Varied:** min_oracle_prob from 0.10 to 0.50 (fine-grained, 0.05 steps)
**Data:** 2-week window (3297 bets: 2943 negRisk, 354 non-negRisk)

---

#### Results: min_oracle_prob sensitivity at n_bets=1

| mop | CF bets | Skip | All delta | negR delta | nonN delta | nonN ROI | nonN side sw |
|-----|---------|------|-----------|-----------|------------|----------|-------------|
| 0.10 | 2364 | 933 | -1.9pp | -3.1pp | **+9.7pp** | -14.8% | 7 |
| 0.15 | 2364 | 933 | -1.9pp | -3.1pp | **+9.7pp** | -14.8% | 7 |
| 0.20 | 2356 | 941 | -3.1pp | -3.0pp | -0.8pp | -25.3% | 4 |
| 0.25 | 2355 | 942 | -3.1pp | -3.0pp | -0.7pp | -25.1% | 3 |
| 0.30 | 2352 | 945 | -3.0pp | -3.0pp | -0.1pp | -24.6% | 0 |
| 0.35 | 2352 | 945 | -3.0pp | -3.0pp | -0.1pp | -24.6% | 0 |
| 0.40 | 2351 | 946 | -3.0pp | -3.0pp | -0.1pp | -24.6% | 0 |
| 0.45 | 2351 | 946 | -3.0pp | -3.0pp | -0.1pp | -24.6% | 0 |
| 0.50 | 2351 | 946 | -3.0pp | -3.0pp | -0.1pp | -24.6% | 0 |

---

#### Key Observations

**1. There are exactly two regimes, with the transition at mop=0.20**

- **mop 0.10-0.15:** +9.7pp on non-negRisk, 7 side switches, -14.8% CF ROI
- **mop 0.20-0.50:** -0.1 to -0.8pp on non-negRisk, 0-4 side switches, ~-24.6% CF ROI

The jump from mop=0.15 to mop=0.20 is where 3 side switches disappear and the
non-negRisk delta drops from +9.7pp to -0.8pp. This is a cliff, not a gradient.

**2. mop 0.30 to 0.50 produces identical results**

From mop=0.30 onward, the numbers are virtually identical: same CF bets (2351-2352),
same delta (-0.1pp), zero side switches. The filter is not binding in this range
because all the markets where it matters have oracle p_yes below 0.30.

This means **mop=0.30 and mop=0.50 are functionally equivalent** for this market
composition. Choosing between them is a matter of safety margin, not ROI.

**3. The +9.7pp at mop=0.10 comes from 2 winning side switches on AMZN**

The 7 side switches at mop=0.10-0.15:

| Market | Actual | CF | Fill | Synth CF | p_yes | Won? | CF profit |
|--------|--------|-----|------|----------|-------|------|-----------|
| AMZN close above 205 | YES | NO | 0.978 | 0.022 | 0.80 | NO (lose) | -1.01 |
| META close above 660 | NO | YES | 0.980 | 0.020 | 0.28 | NO (lose) | -1.01 |
| AAPL close above 245 | YES | NO | 0.950 | 0.050 | 0.72 | NO (lose) | -1.01 |
| GOOGL close above 295 | YES | NO | 0.960 | 0.040 | 0.72 | NO (lose) | -1.01 |
| GOOGL close above 295 | YES | NO | 0.960 | 0.040 | 0.77 | NO (lose) | -1.01 |
| **AMZN close above 210** | **NO** | **YES** | 0.960 | **0.040** | 0.18 | **WIN** | **+23.99** |
| **AMZN close above 210** | **NO** | **YES** | 0.960 | **0.040** | 0.18 | **WIN** | **+23.99** |

5 of 7 switches lose (71%). The two winners are both AMZN above 210, where:
- The trader bet NO at 0.96
- The oracle said p_yes=0.18 (thinks YES is very unlikely)
- Synthetic YES price = 0.04 (unrealistic -- real ask was likely 0.10+)
- YES happened to win -> 25x synthetic payout

This is the same artifact pattern from the v2 analysis but with fewer switches
(7 vs 20) because n_bets=1 is more conservative.

**4. Bet size distribution is proper Kelly sizing (not binary)**

At n_bets=1, bet sizes are well-distributed:

| Bucket | Count | % |
|--------|-------|---|
| 1.00 (min) | 574-587 | 24-25% |
| 1.01-1.50 | 628 | 27% |
| 1.51-2.00 | 541 | 23% |
| 2.01-2.49 | 600 | 25-26% |
| 2.50 (max) | 8 | 0% |

This confirms n_bets=1 produces proper intermediate sizing. The issue is not
sizing quality -- it is that the sizing does not translate into ROI improvement
because the oracle predictions are not informative enough for the bet sizes
to differentiate good from bad opportunities.

**5. negRisk delta is -3.0pp regardless of mop**

The oracle is random on range markets, so mop doesn't matter for negRisk.
The -3.0pp comes from Kelly being conservative at W_bet=2.5 (sizes smaller
than the actual bets, reducing exposure to markets that happen to win).

---

#### What Your Preferred Config (mop=0.10) Actually Does

With n_bets=1, min_edge=0.01, mop=0.10:

- Takes 2364 of 3297 bets (72%)
- Skips 933 bets (28%) where log-growth is insufficient
- Produces proper intermediate bet sizes (avg 1.56 USDC)
- **On negRisk: -3.1pp** (Kelly sizes smaller, misses some winners)
- **On non-negRisk: +9.7pp** driven by 2 AMZN tail-event wins at synthetic pricing
- **7 side switches: 2 win, 5 lose (29% win rate)**

The non-negRisk improvement is not from better bet sizing -- it is from 2
lucky cross-side bets at unrealistic synthetic prices.

---

#### mop=0.30 vs mop=0.40: Your Investigation Range

These produce identical results: -0.1pp on non-negRisk, 0 side switches, same
bets taken. No differentiation.

The reason: on non-negRisk markets in this dataset, oracle p_yes values that
trigger side switches are all below 0.20 (the AMZN/META/GOOGL cross-side bets
have p_yes = 0.18-0.28). Raising mop from 0.30 to 0.40 filters nothing new.

---

#### Assessment by Market Type

**negRisk markets (2943 bets, 89%):**

| mop | negR CF | negR delta | Comment |
|-----|---------|-----------|---------|
| 0.10 | 2094 | -3.1pp | Slightly worse |
| 0.30 | 2089 | -3.0pp | Same |
| 0.50 | 2088 | -3.0pp | Same |

Kelly does not help on negRisk at any mop. The -3.0pp comes from Kelly being
conservative at W_bet=2.5 (sizes smaller than actual, reducing exposure to
markets that occasionally win). The mop setting is irrelevant -- the oracle
is uncalibrated on range markets regardless.

**Recommendation for negRisk:** mop does not matter. Consider filtering negRisk
markets entirely from the sampling pipeline -- this saves 79% of dollar losses
without any Kelly parameter change.

**Non-negRisk markets (354 bets, 11%):**

| mop | nonN CF | nonN delta | Side sw | nonN ROI | Artifact? |
|-----|---------|-----------|---------|----------|-----------|
| 0.10 | 270 | +9.7pp | 7 | -14.8% | YES -- 2 AMZN lottery wins |
| 0.20 | 267 | -0.8pp | 4 | -25.3% | Partially -- 4 switches |
| 0.30 | 263 | -0.1pp | 0 | -24.6% | No -- clean result |
| 0.40 | 263 | -0.1pp | 0 | -24.6% | No -- identical to 0.30 |
| 0.50 | 263 | -0.1pp | 0 | -24.6% | No -- identical to 0.30 |

The non-negRisk improvement at mop=0.10 (+9.7pp) is the **same synthetic-pricing
artifact** identified in the v2
[SIDE_SWITCH_ANALYSIS](../polystrat_kelly_replay_v2_comparison/SIDE_SWITCH_ANALYSIS.md).
The 2 AMZN side switches use synthetic YES prices of 0.04 (real was ~0.10+),
inflating payout from ~10x to 25x. The oracle says p_yes=0.18 -- it thinks YES
is unlikely. 71% of the side switches at mop=0.10 lose money.

At mop=0.20, 4 switches remain. At mop=0.30+, all side switches disappear and
the result stabilizes at -0.1pp (neutral).

**Recommendation for non-negRisk:** mop=0.30 is the safe floor. It eliminates
all side-switch artifacts while remaining less restrictive than 0.50. Results
at 0.30, 0.40, and 0.50 are identical for this market composition. Below 0.30,
the improvement depends on unreliable synthetic pricing of cross-side bets.

---

#### Combined Recommendation

| Market type | mop | Rationale |
|-------------|-----|-----------|
| negRisk | Any (0.30-0.50) | Oracle is random; mop doesn't matter; consider filtering entirely |
| non-negRisk | 0.30 | Safe floor; eliminates artifacts; identical to 0.40-0.50 in practice |

If the trader implements negRisk filtering in the sampling pipeline, then
only the non-negRisk row matters, and **mop=0.30 with n_bets=1** is the
recommended starting point. It produces proper Kelly sizing and neutral ROI
delta (-0.1pp) -- which is the honest baseline before oracle improvements.

Setting mop below 0.20 enables side switches that look profitable in replay
but rely on synthetic opposite-side pricing that does not reflect real CLOB
spreads. Until the replay methodology is improved with historical orderbook
data, results below mop=0.20 should not be trusted.
