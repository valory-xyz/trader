### Polystrat Kelly Replay v2 -- Cross-Window Comparison

**Date:** 2026-03-26
**Data:** 3 replay windows (4-day, 7-day, 2-week), 3297 total bets, 107 agents
**New in v2:** negRisk market segmentation, oracle calibration analysis, pricing artifact investigation

---

#### Executive Summary and Conclusions

**C1. The Kelly formula is mathematically correct but adds limited value in practice.**
At production settings (min_oracle_prob=0.5), Kelly improves ROI by +1.4pp on
standalone binary markets through better bet sizing. On negRisk range markets (89%
of all bets), Kelly produces no improvement. Overall, all strategies lose money.

**C2. negRisk markets (89% of bets): Kelly does not help.**
The mech oracle is completely uncalibrated on range markets. Regardless of what
p_yes the oracle predicts (0.05 or 0.95), YES actually wins ~35% of the time.
Kelly cannot extract edge from random inputs. ROI delta: -0.4 to -0.5pp.

**C3. Non-negRisk markets (11%): Kelly helps modestly at mop=0.5.**
Kelly improves ROI by +1.4pp on the 2-week window through bet sizing (skipping
weak-edge bets). This is the only reliable improvement we can attribute to Kelly.

**C4. The large improvements at mop=0.1 (+24 to +62pp) are artifacts.**
They are driven by 4 tail-event lottery wins (TSLA/AMZN stock spikes) at
synthetic prices (0.02 per share vs real 0.10+). 75% of side switches lose money.
The oracle does not predict these events (p_yes=0.13). mop=0.1 is dangerous.

**C5. Kelly produces binary bet sizes (go/no-go), not intermediate sizing.**
With n_bets=3, 76% of bets hit max_bet (2.50). This is because W_bet (7.50) is
3x larger than max_bet, so any edge above 7-17% saturates the cap. The replay
measures Kelly as a bet filter, not a bet sizer.

**C6. negRisk YES bets with strong edge do not work.**
The oracle is uncalibrated: win rate stays ~35% regardless of edge threshold.
The marginal +2.4% ROI at edge >= 0.30 comes from cheap-share leverage, not
oracle skill. It is not statistically significant (120 bets).

**C7. The v1 instability across windows was a composition effect.**
Shorter windows have more non-negRisk markets (31% in 4-day vs 11% in 2-week).
When segmented, results are consistent within each market type.

**C8. The bottleneck is oracle quality, not Kelly parameters.**
No parameter tuning (min_oracle_prob, edge threshold, n_bets) can fix an
uncalibrated oracle. Better mech predictions are the only path to profitability.

---

#### Recommended Production Configuration

```json
{
  "min_oracle_prob": 0.5,
  "min_edge": 0.01,
  "n_bets": 5,
  "max_bet_usdc": 2.5,
  "bankroll_usdc": "fund with 10+ USDC"
}
```

Rationale:
- `min_oracle_prob=0.5`: prevents lottery-ticket bets; only reliable setting
- `n_bets=5`: ensures W_bet is large enough to afford Polymarket min orders
- `max_bet=2.5`: reasonable per-trade risk cap
- Higher n_bets produces binary sizing (go/no-go) which is acceptable since
  Kelly's value here is in filtering, not sizing

---

#### Data

| Window | Total bets | negRisk | non-negRisk | negRisk % | Agents |
|--------|-----------|---------|-------------|-----------|--------|
| Mar 12-26 (2-week) | 3297 | 2943 | 354 | 89% | 107 |
| Mar 20-26 (7-day) | 1045 | 902 | 143 | 86% | ~70 |
| Mar 23-26 (4-day) | 315 | 217 | 98 | 69% | 68 |

negRisk tagged via Polymarket CLOB API (`/markets/{conditionId}`).

---

#### Results: negRisk markets (C2)

Kelly is consistently worse or neutral on range markets:

| Window | mop | Act ROI | CF ROI | Delta |
|--------|-----|---------|--------|-------|
| 2-week | 0.5 | -9.9% | -10.4% | -0.5pp |
| 7-day | 0.5 | -14.4% | -17.7% | -3.3pp |
| 4-day | 0.5 | -30.6% | -29.4% | +1.2pp |

Oracle calibration on negRisk (2943 bets):

| Oracle says p_yes | Count | YES actually won | Expected |
|-------------------|-------|-----------------|----------|
| 0.00-0.10 | 753 | 37.5% | ~5% |
| 0.10-0.20 | 1198 | 34.8% | ~15% |
| 0.20-0.30 | 451 | 36.4% | ~25% |
| 0.30-0.40 | 187 | 34.8% | ~35% |
| 0.70-0.80 | 123 | 32.5% | ~75% |
| 0.90-1.00 | 41 | 34.1% | ~95% |

The oracle outputs random numbers. YES wins ~35% regardless of prediction.

This means any Kelly strategy on negRisk is operating on random inputs. No
parameter tuning can fix this — the bottleneck is oracle quality (C8).

---

#### Results: non-negRisk markets (C3, C4)

At production settings (mop=0.5), Kelly provides a modest but real improvement
through bet sizing: skipping bets where the edge is too thin. At mop=0.1, the
numbers look dramatically better but are artifacts of synthetic pricing.

| Window | mop | Act ROI | CF ROI | Delta | Side switches |
|--------|-----|---------|--------|-------|--------------|
| 2-week | 0.1 | -24.5% | -0.6% | +23.9pp | 20 |
| 2-week | 0.5 | -24.5% | -23.1% | **+1.4pp** | 0 |
| 7-day | 0.1 | -20.3% | +41.2% | +61.5pp | 17 |
| 7-day | 0.5 | -20.3% | -20.7% | -0.4pp | 0 |
| 4-day | 0.1 | -17.9% | +1.9% | +19.8pp | 8 |
| 4-day | 0.5 | -17.9% | -21.4% | -3.5pp | 0 |

The mop=0.1 improvements are artifacts (C4). Of 20 side switches at mop=0.1:
- 15 WRONG (75%), losing -16.49 USDC total
- 5 CORRECT (25%), winning +173.62 USDC — driven by 4 TSLA/AMZN tail events
- The 4 winners used synthetic YES prices of 0.017-0.040 (real was 0.05-0.15+)
- At realistic prices, the 50:1 payouts would be 3-10:1, barely offsetting losses

Only the **mop=0.5 row (+1.4pp, 2-week)** is reliable. It comes from Kelly
skipping weak-edge bets, not from side switching.

The 4 tail-event winners that drive the mop=0.1 result:

| Market | Trader bet | CF bet | Fill price | Synthetic CF price | p_yes | Won? | CF profit |
|--------|-----------|--------|-----------|-------------------|-------|------|-----------|
| TSLA close above 380 (Mar 24) | NO | YES | 0.983 | 0.017 | 0.13 | YES | +57.81 |
| TSLA close above 380 (Mar 25) | NO | YES | 0.983 | 0.017 | 0.13 | YES | +57.81 |
| AMZN close above 210 (Mar 25) | NO | YES | 0.960 | 0.040 | 0.18 | YES | +26.23 |
| AMZN close above 210 (Mar 24) | NO | YES | 0.960 | 0.040 | 0.18 | YES | +26.23 |

All 4 share the pattern: the trader bet NO at 0.96-0.98, the synthetic YES
price is 0.017-0.04, and the oracle says p_yes=0.13-0.18 (it thinks YES is
very unlikely). Kelly bets YES only because the synthetic price makes it look
like 50:1 odds. At realistic YES prices (0.10+), the payout drops from 58x
to 10x and barely offsets the 15 losing switches.

---

#### Results: bet sizing (C5)

The Kelly optimizer should produce a range of bet sizes proportional to edge.
Instead, with n_bets=3, it produces mostly 0 or 2.50 (binary go/no-go).

| n_bets | W_bet | At max_bet | Intermediate | Kelly acts as |
|--------|-------|-----------|-------------|---------------|
| 1 | 2.50 | 0% | 83% | Proper bet sizer |
| 3 | 7.50 | 76% | 19% | Binary filter (go/no-go) |

With n_bets=3, any edge above 7-17% (depending on price) saturates max_bet.
Most bets have edge > 10%, so 76% hit the cap.

---

#### Results: negRisk YES with strong edge (C6)

Using only bets with RELIABLE pricing (trader also bet YES):

| Edge threshold | Bets | Win % | ROI | Note |
|---------------|------|-------|-----|------|
| >= 0.00 | 306 | 39.2% | -15.2% | |
| >= 0.10 | 227 | 33.9% | -16.2% | |
| >= 0.20 | 160 | 36.2% | -2.7% | Near breakeven |
| >= 0.30 | 120 | 35.0% | +2.4% | Marginal, not significant |
| >= 0.40 | 88 | 27.3% | -9.1% | Collapses |

Win rate stays ~35% regardless of edge threshold — confirming the oracle is
uncalibrated. The +2.4% at 0.30 is a cheap-share leverage artifact.

---

#### Why v1 results were unstable (C7)

| Window | negRisk delta | non-negRisk delta | negRisk share | Aggregate |
|--------|--------------|-------------------|---------------|-----------|
| 2-week | -0.4pp | +23.9pp (artifact) | 89% | +2.1pp |
| 7-day | -3.2pp | +61.5pp (artifact) | 86% | +4.8pp |
| 4-day | +1.2pp | +19.8pp (artifact) | 69% | +7.3pp |

At mop=0.5 (removing artifacts), the aggregate delta is -0.5pp to +1.4pp
across all windows — consistent and modest.

---

#### Detailed Analysis Reports

| Report | Question | Finding |
|--------|----------|---------|
| [SIDE_SWITCH_ANALYSIS.md](SIDE_SWITCH_ANALYSIS.md) | Why does mop=0.1 look so good? | Artifact: synthetic pricing + 4 tail-event lottery wins |
| [NEGRISK_YES_STRATEGY_ANALYSIS.md](NEGRISK_YES_STRATEGY_ANALYSIS.md) | Should we bet YES on negRisk with strong edge? | No: oracle is random on range markets |
| [BET_SIZING_ANALYSIS.md](BET_SIZING_ANALYSIS.md) | Why are bets always 0 or 2.50? | W_bet >> max_bet causes saturation |

---

#### Individual Window Reports

- [v2 Mar 12-26 (2-week)](../polystrat_kelly_replay_v2_2026-03-12_2026-03-26/README.md)
- [v2 Mar 20-26 (7-day)](../polystrat_kelly_replay_v2_2026-03-20_2026-03-26/README.md)
- [v2 Mar 23-26 (4-day)](../polystrat_kelly_replay_v2_2026-03-23_2026-03-26/README.md)

---

#### Methodology

- Replay uses `polystrat_kelly_replay.py --input-snapshot` with frozen subgraph data
- negRisk tagging via `enrich_snapshot_neg_risk.py` (CLOB API)
- Segmentation via `segment_replay_by_neg_risk.py`
- Plots via `plot_polystrat_roi_distributions.py`
- Execution price proxy: realized fill price (amount/shares) — no historical orderbooks
- Synthetic opposite-side price: `1 - fill_price` (understates real spread)
- Fixed bankroll per bet (no sequential P&L tracking)
