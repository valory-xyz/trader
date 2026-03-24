# Kelly Code Audit Framework

## Purpose

This document is the implementation audit framework for the Kelly rollout.
Its goal is to validate that the code matches the intended model and does not
introduce execution, pricing, or regression bugs.

It should be used once implementation starts and again before merge.

---

## Scope

The code audit covers:

- New Kelly strategy implementation
- Decision-maker integration
- Omen and Polymarket pricing paths
- Orderbook/pool input wiring
- Profitability and rebet logic
- Config and ChatUI compatibility
- API-call behavior
- Execution-time safety checks

---

## Primary Audit Questions

### 1. Spec Adherence

Check whether the code matches the approved design.

Questions:

- Does the code implement the intended Kelly objective?
- Does it use the intended venue execution model for each venue?
- Are all parameters interpreted with the correct units?
- Does it preserve documented compatibility behavior?

Expected output:

- List of mismatches between spec and code

### 2. Pricing Logic Integrity

Audit the full pricing chain, not just the optimizer.

Checks:

- Are the same pricing assumptions used in:
  - sizing
  - expected-profit calculation
  - rebet logic
  - execution-time validation
- Are venue fees and external friction fees separated consistently?
- Is `expected_profit` computed with the exact same accounting as the Kelly objective?

Expected output:

- Statement of whether pricing logic is internally consistent

### 3. Slippage and Quote-to-Execution Drift

The implementation must be audited for stale-price risks.

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

- Clear answer on whether slippage protection exists and is sufficient

### 4. Regression Risk

Audit the implementation for behavior regressions.

Checks:

- Does Omen still work correctly?
- Does Polymarket still work correctly?
- Does non-Kelly logic still behave the same?
- Does fallback strategy behavior still work?
- Does ChatUI/config hydration still work?
- Are legacy strategy names still handled correctly where needed?

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

Checks:

- Empty or malformed orderbook
- Missing token IDs
- Missing market price
- Missing min order size
- Invalid decimals
- Partial depth for minimum fill
- Book changes between sizing and placement
- Pool values invalid or zero
- Legacy config values still present

Expected output:

- List of edge cases covered vs uncovered

---

## Required Technical Checks

### A. Model Checks

- [ ] Kelly objective is implemented as specified
- [ ] Omen execution uses FPMM model correctly
- [ ] Polymarket execution walks the book correctly
- [ ] `expected_profit` follows the exact optimizer accounting
- [ ] Venue fee is not double-counted
- [ ] External friction is not omitted

### B. Pricing-to-Execution Checks

- [ ] Sizing price basis is logged or observable
- [ ] Placement price basis is logged or observable
- [ ] Slippage tolerance exists or the absence is explicitly accepted
- [ ] Minimum executable size is validated at execution time if needed
- [ ] There is no silent mismatch between sizing assumptions and placement assumptions

### C. Regression Checks

- [ ] Omen path remains functional
- [ ] Polymarket path remains functional
- [ ] ChatUI still loads and validates settings
- [ ] Legacy Kelly naming does not break startup
- [ ] Non-Kelly strategy behavior is unchanged where intended

### D. Performance / Request Checks

- [ ] API calls per market/cycle are within expected budget
- [ ] Duplicate requests are eliminated where possible
- [ ] No unnecessary new calls are made only for convenience

---

## Suggested Runtime Safeguards

These should be considered part of the audit even if not all are implemented immediately.

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
- Focus on bugs, regressions, and ambiguous pricing behavior

### Spec Mismatches

- Code behavior that differs from approved design

### Pricing / Execution Risks

- Any mismatch between sizing and execution assumptions

### Regression Risks

- Existing functionality that may have been affected

### Test Gaps

- Missing test coverage required for confidence

### Go / No-Go

- Merge readiness assessment
