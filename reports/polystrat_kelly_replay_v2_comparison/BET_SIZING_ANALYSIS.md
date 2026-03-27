### Why Kelly Produces Binary Bet Sizes (Go/No-Go)

**Date:** 2026-03-26
**Problem:** Kelly almost always outputs either 0 (skip) or 2.50 (max_bet),
never intermediate values like 1.30 or 1.80.

---

#### The Evidence

From the 2-week replay (mop=0.5, n_bets=3):

| Bet size | Count | % |
|----------|-------|---|
| 0 (skip) | 617 | 19% |
| 2.50 (max_bet) | 2031 | **76%** |
| 1.01-2.49 (intermediate) | 514 | 19% |
| 1.00 (min_bet) | 135 | 5% |

76% of all placed bets hit the max_bet cap. Kelly is not sizing — it's deciding
yes or no.

---

#### Root Cause: W_bet >> max_bet

With the replay config: `bankroll=15, n_bets=3, max_bet=2.5`:
- `W_bet = min(3 x 2.5, 15) = 7.5`
- `max_bet / W_bet = 2.5 / 7.5 = 0.333`

Kelly's optimal fraction: `f* = (p - c) / (1 - c)`

The bet hits max_bet when `f* > 0.333`. This happens at very small edges:

| Price c | Min edge to hit cap | Equivalent |
|---------|--------------------|-----------|
| 0.20 | 26.6% | Oracle p >= price + 0.27 |
| 0.50 | 16.7% | Oracle p >= price + 0.17 |
| 0.70 | 10.0% | Oracle p >= price + 0.10 |
| 0.80 | 6.7% | Oracle p >= price + 0.07 |
| 0.90 | 3.3% | Oracle p >= price + 0.03 |

For NO bets at price 0.80, ANY edge above 6.7% saturates the cap. Most replay
bets have edge > 10%, so they all max out.

**The math:** Kelly sizes as a fraction of `W_bet`. When `W_bet` is 3x larger
than `max_bet`, the unconstrained optimal bet is almost always above `max_bet`.

---

#### Verification: n_bets=1 produces proper Kelly sizing

On 200 sample bets, comparing n_bets=1 vs n_bets=3:

| Config | W_bet | At max | Intermediate | At min | Skip |
|--------|-------|--------|-------------|--------|------|
| n_bets=1 | 2.50 | **0%** | **83%** | 17% | 32% |
| n_bets=3 | 7.50 | **82%** | 15% | 3% | 24% |

With `n_bets=1`, Kelly produces a full range: 1.00, 1.11, 1.25, 1.43, 1.80,
2.14, 2.35... This is proper Kelly sizing — bet proportional to edge.

With `n_bets=3`, 82% of bets hit the cap because `W_bet` is too large relative
to `max_bet`.

---

#### The Fundamental Tension

| | n_bets=1 | n_bets=3 |
|---|---------|---------|
| W_bet | max_bet (2.5) | 3 x max_bet (7.5) |
| Kelly sizing | Proper range | Binary (go/no-go) |
| Can afford min orders | Often no (W_bet too small) | Yes |
| Bet count (from log analysis) | 2/42 | 16/42 |

`n_bets=1` gives proper sizing but can't afford most bets (Polymarket min order
= 5 shares x price >= 1.20 USDC, close to W_bet=2.5).

`n_bets=3` can afford bets but degenerates into a binary filter.

---

#### What the Replay Actually Measures

Given the binary behavior, the replay is NOT measuring Kelly's bet-sizing value.
It's measuring Kelly as a **bet filter**: should this trade be taken or skipped?

The 617 skipped bets (19%) are where Kelly says "no edge" and the rest are
"edge exists, bet max." The +1.4pp improvement at mop=0.5 comes from the
FILTERING (skipping bad bets), not from SIZING (betting 1.30 vs 2.10).

---

#### Recommended Fix

The cleanest fix is to **use `W_bet = max_bet`** for the log-utility calculation
(equivalent to `n_bets=1`), but keep a separate **solvency check** using the
real wallet balance:

```
# Solvency: can we afford the minimum order?
if wallet < b_min:
    skip

# Kelly sizing: fraction of max_bet
W_bet = max_bet  # NOT n_bets * max_bet
G(b) = p * log(W_bet - cost + shares) + (1-p) * log(W_bet - cost)
# This produces intermediate values: 0.50, 1.20, 1.80, 2.30...

# Cap
B = min(B, max_bet)
```

This separates the two concerns:
1. **Can I afford this bet?** (wallet solvency check)
2. **How much should I bet?** (Kelly sizing against max_bet)

This is what `final_kelly.py` in the kelly_poly repo implements via the
`n_bets` parameter: at `n_bets=1`, `W_bet = max_bet`, and the optimizer
produces proper intermediate sizes.

---

#### Impact on Replay Interpretation

The current replay results are still valid as a **bet filter comparison**:
"does Kelly skip the right bets?" The answer is yes (marginal +1.4pp on
non-negRisk at mop=0.5).

But the replay does NOT demonstrate Kelly's sizing value. To test sizing,
the replay would need to be re-run with `n_bets=1` and a wallet solvency
check that doesn't constrain the optimizer.
