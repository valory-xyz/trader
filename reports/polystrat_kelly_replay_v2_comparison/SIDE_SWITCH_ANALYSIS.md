### Side Switch Analysis: Why mop=0.1 Results Are Misleading

**Date:** 2026-03-26
**Status:** CORRECTIVE — revises conclusions from the v2 cross-window comparison

---

#### The Claim (from initial v2 analysis)

> At mop=0.1, Kelly dramatically improves non-negRisk ROI through side switches
> (+23.9pp on Mar 12-26, +61.5pp on Mar 20-26, +19.8pp on Mar 23-26).

#### The Reality

The improvement is an **artifact of synthetic pricing and survivorship bias**.

---

#### Side Switch Breakdown (Mar 12-26, non-negRisk)

Of 20 side switches:

| Outcome | Count | Total profit delta |
|---------|-------|--------------------|
| CORRECT (Kelly picked winning side) | **5** | +173.62 USDC |
| WRONG (Kelly picked losing side) | **15** | -16.49 USDC |
| **Net** | **20** | **+157.13 USDC** |

**75% of side switches lose money.** The net positive is entirely driven by
4 extreme winners.

---

#### The 4 Extreme Winners

| Market | Act | CF | Fill price | Synthetic CF price | p_yes | Won? | CF profit |
|--------|-----|----|-----------|-------------------|-------|------|-----------|
| TSLA close above 380 (Mar 24) | NO | YES | 0.983 | **0.017** | 0.13 | YES won | +57.81 |
| TSLA close above 380 (Mar 25) | NO | YES | 0.983 | **0.017** | 0.13 | YES won | +57.81 |
| AMZN close above 210 (Mar 25) | NO | YES | 0.960 | **0.040** | 0.18 | YES won | +26.23 |
| AMZN close above 210 (Mar 24) | NO | YES | 0.960 | **0.040** | 0.18 | YES won | +26.23 |

All 4 share the same pattern:

1. **Trader bet NO** at very high price (0.96-0.98 per share)
2. **Synthetic YES price = 1 - fill = 0.017-0.040** (absurdly cheap)
3. **Oracle says p_yes = 0.13-0.18** (oracle AGREES this is unlikely)
4. **YES actually won** (rare event / market moved)
5. **Counterfactual payout = bet / 0.017 = 50:1 odds**

---

#### Three Problems

**Problem 1: Synthetic pricing is unrealistic for side switches**

The synthetic YES price of 0.017 comes from `1 - NO_fill_price`. But the real
YES ask on the CLOB would have been much higher. From our live log analysis,
Ask_YES + Ask_NO > 1.0 with spreads of 5-20%. A realistic YES ask for a market
where NO trades at 0.98 would be 0.05-0.15, not 0.017.

At a realistic YES price of 0.10 (instead of 0.017), the payout multiplier drops
from 58x to 10x. The 4 extreme winners would produce ~40 USDC instead of ~168 USDC,
barely offsetting the 16 losers (-16.49 USDC).

**Problem 2: The oracle does NOT predict these events**

The oracle gives p_yes = 0.13 for TSLA and 0.18 for AMZN. The oracle thinks
these outcomes are VERY UNLIKELY. Kelly bets YES anyway because the synthetic
price (0.017) makes it look like a massive edge: `0.13 - 0.017 = +11.3%`.

But at a realistic price of 0.10, the edge shrinks to `0.13 - 0.10 = +3%` — barely
above min_edge. And with the oracle being wrong 87% of the time at p_yes=0.13,
this is lottery-ticket buying, not edge exploitation.

**Problem 3: Survivorship bias**

The 4 winners are all **rare events that happened to occur in this specific
window**. In a different 2-week window where TSLA didn't spike above 380 and
AMZN didn't spike above 210, these same switches would all be losses, and
the mop=0.1 delta would be deeply negative.

---

#### Corrected Assessment

| mop | Non-negRisk delta | Reliable? | Reason |
|-----|-------------------|-----------|--------|
| 0.1 | +23.9pp | **NO** | Driven by 4 synthetic-priced lottery wins |
| 0.3 | +1.9pp | Marginal | Only 1 side switch, small effect |
| 0.5 | +1.4pp | **YES** | No side switches, improvement from bet sizing |

**mop=0.5 is the correct production setting.** The +1.4pp improvement at mop=0.5
comes from Kelly sizing bets proportional to edge, not from risky side switches.

**mop=0.1 is dangerous** because:
- It enables lottery-ticket YES bets at unrealistic synthetic prices
- 75% of side switches lose money
- The apparent profit depends on rare tail events
- The oracle probability (p_yes=0.13) does not support these bets

---

#### What Would a Safe Lower mop Look Like?

If we wanted to lower mop below 0.5, we'd need ALL of:
1. The oracle has demonstrated calibration at low probabilities
2. The execution price is from a real orderbook (not synthetic)
3. The edge is large enough to survive the spread (20%+)
4. The strategy doesn't rely on 50:1 payouts from tail events

None of these conditions are currently met. Until the oracle is validated at
low-probability regimes and historical orderbooks are available for replay,
**mop=0.5 remains the safest choice**.

---

#### Revision to v2 Comparison Report

The cross-window comparison's finding 2 ("Kelly helps at mop=0.1") should be
revised to:

> The apparent improvement at mop=0.1 is an artifact of synthetic opposite-side
> pricing and survivorship bias from 4 extreme tail-event winners. The only
> reliable improvement is at mop=0.5 (+1.4pp on non-negRisk, from bet sizing).
