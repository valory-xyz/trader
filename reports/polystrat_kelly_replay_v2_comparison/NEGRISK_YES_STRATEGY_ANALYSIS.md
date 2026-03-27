### negRisk YES Strategy Analysis: Should We Bet YES with Strong Edge?

**Date:** 2026-03-26
**Question:** For negRisk markets, should we bypass min_oracle_prob and bet YES
when the edge is very high?

---

#### The Proposed Strategy

```
For negRisk markets:
  YES → bet only if edge (p_oracle - price) > HIGH_THRESHOLD, ignore prob filter
  NO  → normal filters (edge > min_edge AND p_no > min_oracle_prob)
```

#### Data: 2943 negRisk bets (Mar 12-26)

---

#### Finding 1: The oracle is completely uncalibrated on range markets

| Oracle p_yes | Count | YES actually won | Actual win % | Expected ~% |
|-------------|-------|-----------------|-------------|-------------|
| 0.00-0.10 | 753 | 282 | 37.5% | ~5% |
| 0.10-0.20 | 1198 | 417 | 34.8% | ~15% |
| 0.20-0.30 | 451 | 164 | 36.4% | ~25% |
| 0.30-0.40 | 187 | 65 | 34.8% | ~35% |
| 0.70-0.80 | 123 | 40 | 32.5% | ~75% |
| 0.90-1.00 | 41 | 14 | 34.1% | ~95% |

**The oracle has zero discriminative power.** Whether it says 5% or 95%, YES
wins about 35% of the time. The oracle probability is meaningless on range
markets — it cannot distinguish which specific range will occur.

This means **any Kelly strategy that relies on oracle p_yes for negRisk
markets is operating on random inputs.**

---

#### Finding 2: Edge threshold analysis (RELIABLE pricing only)

Using only bets where the trader also bet YES (so the execution price is real,
not synthetic). Simulating at fixed 2.50 USDC per bet:

| Edge threshold | Bets | Won | Lost | Win % | Profit | ROI |
|---------------|------|-----|------|-------|--------|-----|
| >= 0.00 | 306 | 120 | 186 | 39.2% | -116.7 | -15.2% |
| >= 0.05 | 261 | 93 | 168 | 35.6% | -110.3 | -16.8% |
| >= 0.10 | 227 | 77 | 150 | 33.9% | -92.1 | -16.2% |
| >= 0.15 | 195 | 65 | 130 | 33.3% | -66.4 | -13.6% |
| >= 0.20 | 160 | 58 | 102 | 36.2% | -10.8 | -2.7% |
| >= 0.30 | 120 | 42 | 78 | 35.0% | +7.4 | **+2.4%** |
| >= 0.40 | 88 | 24 | 64 | 27.3% | -20.2 | -9.1% |
| >= 0.50 | 60 | 9 | 51 | 15.0% | -68.6 | -45.5% |

**The win rate is ~35% regardless of edge threshold** (confirming the oracle is
uncalibrated). The slight profitability at edge >= 0.30 (+2.4% ROI) comes from
the leverage effect of cheap YES shares, not from oracle skill.

At edge >= 0.50, the win rate collapses to 15% — the oracle is confidently
wrong. Very high oracle p_yes (0.80+) on cheap shares actually predicts LOSING.

---

#### Finding 3: Why edge >= 0.30 appears marginally profitable

When edge >= 0.30, the YES shares are very cheap (price < 0.35).
At a base win rate of ~35% (which is just the average across all ranges):

```
EV at price 0.20 = 0.35 * (1/0.20) - 1 = +0.75 (profitable)
EV at price 0.30 = 0.35 * (1/0.30) - 1 = +0.17 (marginally profitable)
EV at price 0.35 = 0.35 * (1/0.35) - 1 = 0.00 (breakeven)
```

Buying any cheap YES share below ~0.35 on a market where YES wins 35% is
mathematically profitable — **regardless of what the oracle says.** This is
a potential market inefficiency, not an oracle-driven strategy.

But the 35% base rate is measured on this specific 2-week window (2943 bets).
It may not hold in other periods. This needs validation on a much larger sample.

---

#### Finding 4: The proposed strategy doesn't rescue the portfolio

Even if the edge >= 0.30 YES bets are real (+2.4% ROI on 120 bets = +7.40 USDC):
- The ~2000 NO bets lose -480 USDC at -10% ROI
- Combined: still deeply negative
- The YES profits are 1.5% of the NO losses

---

#### Answer to the User's Question

**Should we bet YES on negRisk with strong edge?**

**Not based on oracle edge — the oracle is random on range markets.** The edge
threshold is selecting for cheap YES shares, not for oracle accuracy. Any apparent
profitability at high edge thresholds comes from the leverage of cheap shares
combined with a ~35% base win rate, independent of what the oracle predicts.

If you want to exploit this, it would be a **price-based strategy** (bet YES when
price < 0.30), not an oracle-edge strategy. But:
1. The 35% base rate needs validation on larger samples
2. The real spread (Ask_YES is higher than mid-price) would eat into profits
3. This is completely unrelated to the Kelly criterion or oracle quality

**For production:** Keep mop=0.5. The oracle cannot help on negRisk markets.
The bottleneck is oracle quality on range markets, not the Kelly parameters.

---

#### Implication for the Kelly Implementation

No code changes needed for negRisk handling. The current Kelly + mop=0.5 is
correct: it evaluates both sides, finds no exploitable edge (because the oracle
is uncalibrated), and skips or places small NO bets. This is the right behavior.

The only meaningful improvement path is **better oracle calibration on range
markets.** If the oracle could actually distinguish between "this range has 10%
chance" and "this range has 40% chance" (instead of saying ~35% for everything),
then edge-based YES bets would become viable. Until then, Kelly on negRisk is
sizing noise, not signal.
