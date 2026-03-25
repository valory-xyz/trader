# Kelly Spec Audit Round 2

## Scope

- Documents reviewed:
  - `plans/KELLY_IMPLEMENTATION_PLAN.md`
  - `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`
- Reference behavior used:
  - `kelly_poly` PR #5
- Audit framework used:
  - `plans/audit/audit_specs/KELLY_SPEC_AUDIT_FRAMEWORK.md`

Target reviewed:

- trader PR `#882`
- commit `75ceb67a593f640c9e1fdc8684c4b7f5d6344120`

---

## Expected Model

The current spec set defines a unified grid-search-based Kelly strategy that:

- evaluates YES and NO independently
- uses a CLOB execution model for Polymarket
- uses an FPMM execution model for Omen
- compares all admissible candidate bets against a no-trade baseline
- returns the side and size with the largest positive log-growth improvement

The local algorithm source of truth for math and parameter contract is:

- `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`

The implementation/migration source of truth is:

- `plans/KELLY_IMPLEMENTATION_PLAN.md`

---

## Consistency Check

Result: `pass`

The rollout plan and the local algorithm spec are materially aligned on:

- side selection
- CLOB vs FPMM execution separation
- fee accounting
- `expected_profit` contract
- venue-native decimal handling
- Polymarket minimum-fill handling

The main previous mismatch on Polymarket minimum spend is resolved: both docs now
use walked-book minimum-fill cost for `min_order_shares`, and reject the side if
the book cannot supply the venue minimum.

---

## Intentional Deviations

- The rollout replaces `bet_amount_per_threshold` with `fixed_bet`.
- The strategy, not `PredictionResponse.vote`, becomes the source of truth for
  new-trade side selection.
- Backward compatibility is retained for one migration window for
  `kelly_criterion_no_conf` and `bet_amount_per_threshold`.
- Execution-time slippage/revalidation is explicitly out of scope for the sizing
  algorithm and must be defined separately if required.

---

## Findings

No blocking spec findings in the current spec set.

The current docs are coherent enough to proceed with implementation.

---

## Residual Risks

### 1. `fixed_bet` still has an incomplete profitability contract for unsupported paths

The implementation plan explicitly notes that `fixed_bet` does not return
`expected_profit`, and that this only matters if rebetting is re-enabled in the
future.

Impact:

- not a blocker for current supported flows
- should be revisited before any unsupported rebet path is reactivated

Status:

- accepted risk

### 2. Execution-time validation remains intentionally out of scope for sizing

The plan now documents the API-call budget and states that execution-time
validation is out of scope for the sizing algorithm.

Impact:

- not a spec contradiction
- a future dedicated placement/execution spec is needed if runtime slippage
  protection, stale-quote handling, or execution-time validation are required

Status:

- accepted scope boundary

---

## Open Questions

1. If rebetting is ever re-enabled, should `fixed_bet` compute `expected_profit`,
   or should the caller treat that field as optional for non-Kelly strategies?
2. A future dedicated placement/execution spec should define execution-time
   validation, stale-quote handling, and slippage protection if those guards
   are needed beyond the current sizing-only scope.

---

## Outcome

Current result: `go`

Reason:

Using the audit framework, the current spec set now passes the key coherence
checks:

- local algorithm spec and rollout plan are aligned
- parameter/unit contract is explicit
- venue-specific execution models are distinct
- pricing and fee accounting are internally consistent
- API-call delta is documented

The remaining items are either explicitly unsupported paths or intentionally
out-of-scope placement concerns, not blockers to implementation.

---

## Technical Check Status

Legend:

- `PASS` = clearly specified in the current `#882` spec set
- `PARTIAL` = directionally addressed, but still incomplete or bounded by scope
- `OPEN` = not yet resolved in the current `#882` spec set
- `N/A` = not applicable for this audit round

### A. Model Checks

- [PASS] Kelly objective is implemented as specified
- [PASS] Omen execution uses FPMM model correctly
- [PASS] Polymarket execution walks the book correctly
- [PASS] `expected_profit` follows the exact grid-search accounting
- [PASS] Venue fee is not double-counted
- [PASS] External friction is not omitted

### B. Pricing-to-Execution Checks

- [PARTIAL] Sizing price basis is logged or observable
- [PARTIAL] Placement price basis is logged or observable
- [PARTIAL] Slippage tolerance exists or the absence is explicitly accepted
- [PARTIAL] Minimum executable size is validated at sizing time
- [PARTIAL] There is no silent mismatch between sizing assumptions and placement assumptions

### C. Regression Checks

- [PASS] Omen path remains functional
- [PASS] Polymarket path remains functional
- [PASS] ChatUI still loads and validates settings
- [PASS] Legacy Kelly naming does not break startup
- [PASS] Non-Kelly strategy behavior is unchanged where intended

### D. Performance / Request Checks

- [PASS] API calls per market/cycle are within documented budget
- [PARTIAL] Duplicate requests are eliminated where possible
- [PASS] No unnecessary new calls are added without being documented
