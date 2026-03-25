# Kelly Code Audit Framework

## Purpose

This document is the implementation audit framework for the Kelly rollout.
Its goal is to validate that the code matches the intended model and does not
introduce execution, pricing, or regression bugs.

The audit must also verify that the implementation follows the approved rollout
documents, in particular:

- `plans/KELLY_IMPLEMENTATION_PLAN.md`
- `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`

It should be used once implementation starts and again before merge.

Unless the implementation explicitly claims to provide execution-time slippage
or revalidation protections, the audit should treat those controls as important
follow-up safeguards rather than default merge blockers.

---

## Scope

The code audit covers:

- New Kelly strategy implementation
- Decision-maker integration
- Polymarket (CLOB) and Omen (FPMM) pricing/execution paths
- Orderbook/pool input wiring
- Profitability and rebet logic
- Config and ChatUI compatibility
- API-call behavior
- Execution-time safety checks and follow-up safeguards

---

## Primary Audit Questions

### 1. Spec Adherence

Check whether the code matches the approved design.

Questions:

- Does the code implement the intended Kelly objective?
- Does the implementation fully follow `plans/KELLY_IMPLEMENTATION_PLAN.md`?
- Does the implementation remain consistent with the normative algorithm spec in
  `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`?
- Does the implementation differ from the algorithm provided in PR `#5` of this repo?
- Does the implementation use the intended venue execution model for each venue:
  Polymarket (CLOB) and Omen (FPMM)?
- Are all parameters interpreted with the correct units?
- Does it preserve documented compatibility behavior?
- If execution-time protections are not yet implemented, is that scope boundary
  stated honestly and consistently?

Expected output:

- List of mismatches between implementation, rollout plan, and approved specs

### 1A. Parameter Selection and Defaults

The audit must explicitly identify the parameters that require a concrete
implementation or configuration choice, and whether the chosen values match the
suggested values in:

- `plans/KELLY_IMPLEMENTATION_PLAN.md`
- `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`

At minimum, the audit should review:

- `floor_balance`
- `max_bet`
- `min_bet`
- `n_bets`
- `min_edge`
- `min_oracle_prob`
- `fee_per_trade`
- `grid_points`
- `token_decimals`
- `min_order_shares`

For each parameter, the audit output should state:

- whether it is required, optional, derived, or venue-provided
- where its source of truth lives
- the implemented or configured value
- the suggested/default value from the plan/spec, if any
- whether the current value matches the suggested one
- if it differs, whether the deviation is intentional and justified

Expected output:

- A parameter-selection table including:
  - whether the parameter is required, optional, derived, or venue-provided
  - where its source of truth lives
  - the implemented or configured value
  - the suggested/default value from the plan/spec, if any
  - whether the current value matches the suggested one
  - if it differs, whether the deviation is intentional and justified
- A list of parameter mismatches vs suggested defaults/spec guidance
- A short note on whether any mismatch is blocking, accepted, or needs follow-up

### 2. Pricing Logic Integrity

Audit the full pricing chain, not just the optimizer.

Checks:

- Are the same pricing assumptions used in:
  - sizing
  - expected-profit calculation
  - rebet logic
  - execution-time validation, if such validation is implemented
- Are venue fees and external friction fees separated consistently?
- Is `expected_profit` computed with the exact same accounting as the Kelly objective?

Expected output:

- Statement of whether pricing logic is internally consistent

### 2A. Numerical Safety and Domain Checks

The audit must explicitly check whether the implementation uses mathematical
operations that can become invalid for some inputs, and whether the code guards
those cases by returning no-trade / rejecting the candidate instead of
crashing or producing undefined results.

This is required by the current Kelly plan/spec because the documented math
contains domain-sensitive operations, including:

- `log(W_bet)` for the no-trade baseline
- `log(W_win)` and `log(W_lose)` inside the Kelly objective
- division in the Omen FPMM execution model:
  `(x * y) / (y + alpha * b)`
- fee normalization and `alpha = 1 - bet_fee_fraction`
- grid construction when `grid_points` is too small

Questions:

- Can `W_bet <= 0`, making `log(W_bet)` invalid?
- Can `W_win <= 0` or `W_lose <= 0`, making `log(...)` invalid for some
  candidate bets?
- Can the Omen denominator `y + alpha * b` become zero or negative?
- Can any price, size, fee, or decimal conversion lead to division by zero,
  invalid normalization, or impossible outputs?
- Does the code reject invalid candidates/inputs cleanly rather than throwing
  runtime exceptions or propagating `nan` / `inf`?

Expected output:

- A list of domain-sensitive operations used by the implementation
- Confirmation of the guards that protect each one
- Any remaining numerical crash risk or undefined-math risk

### 3. Slippage and Quote-to-Execution Drift

The implementation should be audited for stale-price risks. For the current
rollout, this review is primarily to make the risk explicit and confirm that no
incorrect safety guarantee is being implied.

Questions:

- Could we size with one price snapshot and execute against a materially different one?
- Are we validating price movement before placement?
- Do we have protection if best ask or VWAP for target size moves?
- Do we reject a trade when the execution basis moves outside tolerance?

Recommended controls:

- Snapshot sizing inputs
- Recompute executable price before placement
- Reject if execution price exceeds configured slippage threshold
- Reject if minimum executable spend rises above the chosen size

Expected output:

- Clear answer on whether slippage protection exists
- If it does not yet exist, an explicit accepted-risk note and follow-up item

### 4. Regression Risk

Audit the implementation for behavior regressions.

Checks:

- Does Omen (FPMM) still work correctly?
- Does Polymarket (CLOB) still work correctly?
- Does the `fixed_bet` replacement for `bet_amount_per_threshold` behave as
  intended?
- Does caller integration still follow the plan's rule that the caller should
  not keep separate decision/profitability code paths for each strategy unless
  the implementation plan explicitly requires it?
- Does ChatUI config hydration and validation still work, including
  `default_max_bet_size` / `absolute_max_bet_size` compatibility?
- Are legacy strategy names (`kelly_criterion_no_conf`,
  `bet_amount_per_threshold`) still normalized correctly on startup, runtime,
  and UI/reporting surfaces?
- Do service/agent/skill config updates remain compatible with the migration
  path described in the implementation plan?

Expected output:

- Regression findings list

### 5. API-Call Regression

Check the real request pattern introduced by the implementation.

Questions:

- Are we making more requests than expected?
- Are we replacing old pricing logic or only adding calls on top?
- Are there repeated fetches for the same data in one cycle?
- Can any request be reused from already-fetched data?

Expected output:

- Real API-call profile vs expected design budget

### 6. Failure-Mode Handling

Audit how the code behaves in bad or edge cases.

Checks should be reviewed explicitly for both venues where applicable, and
should distinguish shared issues from venue-specific ones.

Shared checks:

- Missing market price
- Invalid decimals / wrong unit scale
- Legacy config values still present

Polymarket (CLOB) checks:

- Empty or malformed orderbook
- Missing token IDs
- Missing `min_order_shares` or invalid venue minimum metadata
- Partial depth for minimum fill
- Book changes between sizing and placement

Omen (FPMM) checks:

- Pool values invalid or zero
- Missing or invalid pool-side token amounts
- Missing or invalid venue fee input (`bet_fee`)
- Pool/marginal-price changes between sizing and placement

Expected output:

- List of edge cases covered vs uncovered
- Clear separation between bugs in implemented behavior and accepted follow-up
  safeguards not yet implemented

---

## Required Technical Checks

### A. Model Checks

- [ ] Kelly objective is implemented as specified
- [ ] Omen execution uses FPMM model correctly
- [ ] Polymarket execution walks the book correctly
- [ ] `expected_profit` follows the exact optimizer accounting
- [ ] Venue fee is not double-counted
- [ ] External friction is not omitted

### A1. Parameter Checks

- [ ] All required parameters are present and wired correctly
- [ ] Parameter units/scales match the plan and algorithm spec
- [ ] Tunable parameters selected by the implementation are explicitly identified
- [ ] Chosen parameter values are compared against suggested defaults/spec values
- [ ] Any deviation from suggested values is documented and justified
- [ ] Venue-provided parameters (for example `min_order_shares`) are not treated
  as hardcoded universal constants

### A2. Numerical Safety Checks

- [ ] `W_bet` is guarded so the baseline does not evaluate `log(0)` or `log` of
  a negative value
- [ ] Candidate evaluation guards `W_win` and `W_lose` so the optimizer does not
  evaluate invalid `log(...)` inputs
- [ ] Omen FPMM execution guards the denominator `y + alpha * b` against zero or
  negative values
- [ ] Fee normalization / `alpha` handling cannot silently produce invalid math
- [ ] Grid construction handles small/invalid `grid_points` safely
- [ ] Invalid numeric states fail closed (reject side / no-trade) instead of
  crashing or emitting undefined results

### B. Pricing-to-Execution Checks

These checks are important, but for the current Kelly rollout they are **not
merge blockers by default**. If they are not yet implemented, the audit should:

- record the gap explicitly
- mark it as a follow-up execution-safety item
- state that implementation may proceed with a risk flag / accepted scope note

They only become blocking if the implementation claims to provide
execution-time price protection but does so incorrectly or inconsistently.

- [ ] Sizing price basis is logged or observable
- [ ] Placement price basis is logged or observable
- [ ] Slippage tolerance exists or the absence is explicitly accepted
- [ ] Minimum executable size is validated at execution time if needed
- [ ] There is no silent mismatch between sizing assumptions and placement assumptions

### C. Regression Checks

- [ ] Omen (FPMM) path remains functional
- [ ] Polymarket (CLOB) path remains functional
- [ ] `fixed_bet` replacement behavior matches the implementation plan
- [ ] Caller integration does not reintroduce separate strategy-specific
  decision/profitability code paths unless the plan explicitly requires them
- [ ] ChatUI still loads and validates settings, including compatibility keys
- [ ] Legacy strategy names do not break startup, runtime execution, or UI/reporting
- [ ] Service/agent/skill config migration remains compatible with the plan

### D. Performance / Request Checks

- [ ] API calls per market/cycle are within expected budget
- [ ] Duplicate requests are eliminated where possible
- [ ] No unnecessary new calls are made only for convenience

---

## Suggested Runtime Safeguards

These should be considered part of the audit even if not all are implemented
immediately. For this rollout, missing safeguards in this section should usually
be recorded as follow-up work with a risk flag, not treated as automatic
implementation blockers.

- Log the full sizing snapshot:
  - venue
  - side
  - market price
  - orderbook or pool state
  - min executable size
  - bet size
  - expected profit
  - g improvement

- Before placing an order:
  - refetch or validate execution basis
  - recompute executable cost for intended size
  - reject if price moved beyond tolerance
  - reject if minimum executable spend now exceeds the selected bet

- Record both:
  - sizing price basis
  - execution price basis

This helps detect bugs where a trade is sized using one assumption but executed with another.

---

## Minimum Test Categories

### Strategy Tests

- Correctness of optimizer
- Correctness of venue execution models
- Correct expected profit computation
- Correct fee accounting
- Correct no-trade behavior

### Integration Tests

- Decision-maker passes the right inputs
- Omen inputs are wired correctly
- Polymarket inputs are wired correctly
- Compatibility config still loads
- Legacy strategy names still resolve

### Regression Tests

- Existing balanced strategy remains unchanged
- Existing non-Kelly profitability logic remains unchanged
- No startup regressions due to config or package mapping

### Safety Tests

These tests are recommended to add as the execution-safety layer matures. Their
absence should be called out, but does not by itself block the current Kelly
implementation if the sizing logic is otherwise correct and the limitation is
explicitly accepted.

- Stale orderbook / changed best ask
- Changed VWAP for target fill
- Missing min order size
- Mismatch between intended and executable fill

---

## Review Output Template

Use this structure when reporting a code audit:

### Findings

- Ordered by severity
- Include file/line references
- Focus on bugs, regressions, ambiguous pricing behavior, and clearly labeled
  accepted follow-up risks

### Spec Mismatches

- Code behavior that differs from:
  - `plans/KELLY_IMPLEMENTATION_PLAN.md`
  - `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`
  - the approved design derived from those documents

### Parameter Review

- List the parameters that required selection
- Show chosen values vs suggested/default values
- Call out any justified deviations

### Pricing / Execution Risks

- Any mismatch between sizing and execution assumptions
- Explicitly note when execution-time validation is still a follow-up item and
  not a blocker for proceeding with the implementation

### Regression Risks

- Existing functionality that may have been affected

### Test Gaps

- Missing test coverage required for confidence
- Missing coverage for domain-sensitive math and numerical edge cases

### Go / No-Go

- Merge readiness assessment
- Distinguish between blocking correctness/regression issues in implemented
  logic and accepted follow-up execution-safety work
- Missing execution-time slippage/revalidation controls alone should not force
  `no-go` if the implementation is otherwise correct and the audit records the
  risk clearly as accepted follow-up work
