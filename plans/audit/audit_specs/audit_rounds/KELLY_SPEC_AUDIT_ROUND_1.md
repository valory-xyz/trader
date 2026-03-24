# Kelly Spec Audit Round 1

## Scope

- Document reviewed:
  - `plans/KELLY_IMPLEMENTATION_PLAN.md`
- Reference behavior used:
  - `kelly_poly` PR #5
- Audit framework used:
  - `plans/audit/audit_specs/KELLY_SPEC_AUDIT_FRAMEWORK.md`

Target reviewed:

- trader PR `#882`
- commit `b70cedf4dfbe1f370e0eb7ecd48fef2821196920`

This round supersedes the earlier review against the older `a086d344...` draft.

---

## Expected Model

The plan intends to replace the current Kelly sizing logic with a unified
grid-search-based Kelly implementation that:

- uses a CLOB execution model for Polymarket
- uses an FPMM execution model for Omen
- evaluates both YES and NO independently and lets the strategy choose the side
- compares all candidate bets against a no-trade baseline
- uses `n_bets` and `max_bet` as the main sizing/risk controls

---

## Intentional Deviations

- The rollout replaces `bet_amount_per_threshold` with a new `fixed_bet` strategy.
- The strategy, not `PredictionResponse.vote`, becomes the source of truth for side selection.
- Backward compatibility is explicitly retained for one migration window for
  `kelly_criterion_no_conf` and `bet_amount_per_threshold`.

---

## Findings

### 1. The config/unit contract is still unresolved for Polymarket max-bet values

The plan now preserves `default_max_bet_size` and `absolute_max_bet_size` for
ChatUI compatibility, which is good. But it still leaves a core parameter-contract
question open:

- whether Polymarket config values should be written in native 6-decimal USDC units
- or whether trader normalizes them to an 18-decimal scale before strategy execution

This is explicitly marked as “to be checked with dev”.

Impact:

- the spec does not yet provide a complete parameter/unit contract
- config examples cannot be treated as implementation-ready
- there is still a non-trivial regression risk around max-bet handling

Status:

- blocking

### 2. The Polymarket minimum-spend gate is explicit now, but it still only uses best ask and can understate the true exchange minimum on thin books

The latest plan removed the undefined helper and now states:

```python
b_min_side = max(min_bet, min_order_shares * best_ask_price)
```

This is clearer, and it matches the referenced `final_kelly.py` behavior, but it
still assumes the full `min_order_shares` can be bought at the top level. If the
best ask depth is smaller than `min_order_shares`, then the true minimum
executable spend is higher than this lower bound.

Impact:

- the CLOB path can admit candidate bets below the real exchange minimum
- the “execution-aware” claim is still slightly overstated at the minimum-size boundary
- thin books remain a spec-level edge case

Status:

- major

### 3. API-call budget and execution-time revalidation remain underspecified

The latest draft improves the Polymarket path and explicitly notes that CLOB
adds two orderbook fetches per market. But it still does not fully specify:

- the before/after request budget per market cycle
- which old pricing/profitability calls are removed versus merely bypassed
- whether an explicit pre-placement revalidation step is required for Polymarket
- whether Omen needs an equivalent stale-pool / stale-price guard

The risk section currently says stale orderbooks are acceptable for sizing
because placement uses a fresh order, but that is not yet translated into a
clear design contract for sizing-vs-execution safety.

Impact:

- request-footprint changes are not fully auditable from the spec
- quote-to-execution drift remains only partially addressed
- slippage/staleness expectations are not yet symmetric across venues

Status:

- major

---

## Open Questions

1. Are Polymarket-compatible max-bet values written in native 6-decimal USDC units or normalized to 18 decimals before execution?
2. Is the best-ask-based `b_min_side` intentionally accepted as a lower-bound approximation, or should the minimum executable spend reflect the actual cost of filling `min_order_shares`?
3. What is the accepted per-market request budget after the new Polymarket flow, and do we require execution-time revalidation for both venues?

---

## Outcome

Current result: `no-go`

Reason:

The latest spec is substantially stronger than the earlier draft. It now clearly
covers both-side evaluation, Omen/FPMM data flow, Polymarket minimum-order-share
plumbing, and startup compatibility for legacy Kelly naming.

The remaining blockers are narrower but still important:

- the Polymarket decimal/unit contract is still open
- the Polymarket minimum-spend gate still uses a best-ask approximation

The API-call / staleness story should also be tightened before coding starts.

---

## Technical Check Status

Legend:

- `PASS` = clearly specified in the latest `#882` spec
- `PARTIAL` = directionally addressed, but still incomplete or ambiguous
- `OPEN` = not yet resolved in the latest `#882` spec
- `N/A` = not applicable for this audit round

### A. Model Checks

- [PASS] Kelly objective is implemented as specified
- [PASS] Omen execution uses FPMM model correctly
- [PARTIAL] Polymarket execution walks the book correctly
- [PASS] `expected_profit` follows the exact optimizer accounting
- [PASS] Venue fee is not double-counted
- [PASS] External friction is not omitted

### B. Pricing-to-Execution Checks

- [OPEN] Sizing price basis is logged or observable
- [OPEN] Placement price basis is logged or observable
- [PARTIAL] Slippage tolerance exists or the absence is explicitly accepted
- [OPEN] Minimum executable size is validated at execution time if needed
- [PARTIAL] There is no silent mismatch between sizing assumptions and placement assumptions

### C. Regression Checks

- [PASS] Omen path remains functional
- [PASS] Polymarket path remains functional
- [PASS] ChatUI still loads and validates settings
- [PASS] Legacy Kelly naming does not break startup
- [PASS] Non-Kelly strategy behavior is unchanged where intended

### D. Performance / Request Checks

- [OPEN] API calls per market/cycle are within expected budget
- [OPEN] Duplicate requests are eliminated where possible
- [OPEN] No unnecessary new calls are made only for convenience
