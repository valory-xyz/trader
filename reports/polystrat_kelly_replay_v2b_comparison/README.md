### Polystrat Kelly Replay v2b -- v1-Matching Parameters Comparison

**Date:** 2026-03-26
**Data period:** 2026-03-12 to 2026-03-26 (2 weeks). Analyzed at three overlapping
windows: 4-day (Mar 23-26, 315 bets), 7-day (Mar 20-26, 1045 bets), and 2-week
(Mar 12-26, 3297 bets, 107 agents). All conclusions are based on the full 2-week
dataset unless stated otherwise. The shorter windows are used to check consistency.
**New in v2b:** Uses v1-matching parameters (n_bets=1) with the v2 negRisk segmentation,
to enable direct comparison between v1 results and negRisk-aware analysis.

---

#### Parameter Comparison

The key difference between v2 and v2b is `n_bets`: v2 uses n_bets=3 (produces
binary go/no-go sizing), v2b uses n_bets=1 (produces proper intermediate Kelly
sizing, matching the v1 original configuration).

| Parameter | v1 | v2 | v2b (this) |
|-----------|----|----|-----------|
| n_bets | 1 | 3 | **1** |
| max_bet | 2.5 | 2.5 | 2.5 |
| bankroll | 15.0 | 15.0 | 15.0 |
| min_edge | 0.01 | 0.01 | 0.01 |
| min_oracle_prob | 0.1 (fixed) | varied (0.1/0.3/0.5) | varied (0.1/0.3/0.5) |
| W_bet | 2.50 | 7.50 | **2.50** |
| Bet sizing | Intermediate (0% at max) | Binary (76% at max) | Intermediate (0% at max) |

v2b uses n_bets=1 like v1, so W_bet = min(1 x 2.5, 15) = 2.5. This produces
proper Kelly sizing (intermediate values) rather than the binary go/no-go of v2.

**v2b fixed parameters:** bankroll=15, max_bet=2.5, **n_bets=1**, min_bet=1.0,
min_edge=0.01, fee=0, mech_fee=0.01, grid_points=500.
min_oracle_prob varied: 0.1, 0.3, 0.5. With n_bets=1, W_bet=2.5 (proper sizing).

**See also [v2 comparison](../polystrat_kelly_replay_v2_comparison/README.md)**
for the same analysis with **n_bets=3** (binary sizing, larger W_bet=7.5).

---

#### Cross-Window Results (mop=0.1 and mop=0.5)

| Window | mop | Segment | Bets | CF | Y | N | Sw | Act ROI | CF ROI | Delta |
|--------|-----|---------|------|----|---|---|----|---------| -------|-------|
| 2-week | 0.1 | all | 3297 | 2364 | 329 | 2035 | 13 | -11.3% | -13.3% | -1.9pp |
| 2-week | 0.1 | negRisk | 2943 | 2094 | 238 | 1856 | 6 | -9.9% | -13.0% | -3.1pp |
| 2-week | 0.1 | non-negRisk | 354 | 270 | 91 | 179 | 7 | -24.5% | -14.8% | **+9.7pp** |
| 2-week | 0.5 | all | 3297 | 2351 | 320 | 2031 | 0 | -11.3% | -14.3% | -3.0pp |
| 2-week | 0.5 | negRisk | 2943 | 2088 | 232 | 1856 | 0 | -9.9% | -12.9% | -3.0pp |
| 2-week | 0.5 | non-negRisk | 354 | 263 | 88 | 175 | 0 | -24.5% | -24.6% | -0.2pp |
| 7-day | 0.1 | non-negRisk | 143 | 97 | 27 | 70 | 5 | -20.3% | +3.7% | **+23.9pp** |
| 7-day | 0.5 | non-negRisk | 143 | 92 | 25 | 67 | 0 | -20.3% | -24.2% | -3.9pp |
| 4-day | 0.1 | non-negRisk | 98 | 81 | 22 | 59 | 4 | -17.9% | +7.7% | **+25.6pp** |
| 4-day | 0.5 | non-negRisk | 98 | 77 | 20 | 57 | 0 | -17.9% | -24.9% | -7.0pp |

---

#### Key Observations (v2b vs v2)

**With n_bets=1, Kelly performs differently than with n_bets=3:**

| Metric | v2 (n=3) | v2b (n=1) | Difference |
|--------|---------|----------|-----------|
| CF bets placed (2-week, mop=0.5) | 2680 | 2351 | v2b places fewer bets |
| Non-negRisk delta (mop=0.5) | +1.4pp | -0.2pp | v2b slightly worse |
| Non-negRisk delta (mop=0.1) | +23.9pp (artifact) | +9.7pp | v2b lower but more realistic |
| At max_bet | 76% | 0% | v2b produces varied sizes |
| negRisk delta (mop=0.5) | -0.5pp | -3.0pp | v2b worse on negRisk |

**The side switch count drops from 20 (v2) to 7 (v2b) at mop=0.1 on non-negRisk.**
With n_bets=1, W_bet=2.5 is smaller, so the optimizer is more conservative and
fewer bets pass the log-growth threshold.

**The non-negRisk mop=0.1 improvement (+9.7pp) is the same synthetic-pricing
artifact identified in the v2 analysis.** Of the 7 side switches at mop=0.1:
- 5 LOSE money (71%)
- 2 WIN on AMZN "close above 210" at synthetic YES price 0.04 (real was ~0.10+)
- The oracle says p_yes=0.18 for these wins -- it does NOT predict them
- At realistic CLOB prices, the payout drops from 25x to ~10x

This is the same pattern as the v2
[SIDE_SWITCH_ANALYSIS](../polystrat_kelly_replay_v2_comparison/SIDE_SWITCH_ANALYSIS.md):
lottery-ticket bets at unrealistic synthetic prices. The improvement shrinks
from +23.9pp (v2) to +9.7pp (v2b) only because n_bets=1 limits bet sizes.

**At mop=0.5, v2b shows -0.2pp on non-negRisk vs v2's +1.4pp.**
With smaller W_bet, Kelly is more conservative and fewer bets are taken. The
modest improvement from v2 disappears.

**Fine-grained mop analysis (see [PARAMETER_DEEP_ANALYSIS.md](PARAMETER_DEEP_ANALYSIS.md))
shows that mop=0.30 through mop=0.50 produce identical results.** The transition
happens at mop=0.20: below that, side switches appear; above, they vanish.
For non-negRisk markets, mop=0.30 is the recommended safe floor.

---

#### Consistency Check: v2b mop=0.1 matches v1 exactly

The v1 report (4-day window) showed: aggregate delta = +7.31pp at mop=0.1.
The v2b report (4-day window) shows: aggregate delta = +7.31pp at mop=0.1.

This confirms the v2b replay is using identical parameters to v1.

---

#### Summary

| Finding | v2 (n=3) | v2b (n=1, v1 params) |
|---------|---------|---------------------|
| Kelly helps negRisk? | No (-0.5pp) | No (-3.0pp) |
| Kelly helps non-negRisk at mop=0.5? | Modest (+1.4pp) | Neutral (-0.2pp) |
| Kelly helps non-negRisk at mop=0.1? | +23.9pp (artifact) | +9.7pp (smaller artifact) |
| Bet sizing | Binary (76% at max) | Proper intermediate (0% at max) |
| Side switches (non-negRisk, mop=0.1) | 20 | 7 |

The v1-matching parameters (n_bets=1) produce proper Kelly sizing but are more
conservative, resulting in smaller or no improvement at mop=0.5.

The mop=0.1 improvements remain present but smaller, and are still partially
driven by synthetic-pricing artifacts on side switches.

---

#### Individual Window Reports

- [v2b Mar 12-26](../polystrat_kelly_replay_v2b_2026-03-12_2026-03-26/README.md) -- 3297 bets
- [v2b Mar 20-26](../polystrat_kelly_replay_v2b_2026-03-20_2026-03-26/README.md) -- 1045 bets
- [v2b Mar 23-26](../polystrat_kelly_replay_v2b_2026-03-23_2026-03-26/README.md) -- 315 bets

#### Deep-Dive Analysis

- [PARAMETER_DEEP_ANALYSIS.md](PARAMETER_DEEP_ANALYSIS.md) -- fine-grained mop sweep (0.10-0.50), side switch investigation, bet sizing distribution

#### Compare with

- [v2 comparison (n_bets=3)](../polystrat_kelly_replay_v2_comparison/README.md)
- [v1 comparison (original)](../polystrat_kelly_replay_comparison_2026-03-20_vs_2026-03-23/README.md)
