# Kelly Spec Audit Framework

## Purpose

This document is the pre-implementation audit framework for the Kelly rollout.
Its goal is to validate that the design is coherent before code is written.

It should be used to answer:

- Does the proposed trader logic match the intended model?
- Are all parameters defined clearly and consistently?
- Are we introducing regressions in existing behavior or config surfaces?
- Are we adding unnecessary API calls instead of replacing old logic cleanly?
- Is the pricing model internally consistent from sizing to execution?

---

## Scope

The spec audit covers:

- `plans/KELLY_IMPLEMENTATION_PLAN.md`
- `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`
- Reference behavior from `kelly_poly` PR #5
- Current trader behavior for Omen and Polymarket
- Parameter/config contracts
- Data sources and API-call footprint
- Pricing and profitability logic at the design level

It does not certify the correctness of implementation details. That is handled by
the code audit framework.

---

## Audit Questions

### 1. Model Fidelity

Check whether the design matches PR #5 where intended.

Questions:

- Is `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md` the primary local source of truth for the algorithm?
- Is the implementation plan consistent with the local algorithm spec?
- Does the proposed sizing logic match the intended Kelly objective?
- Are CLOB and FPMM pricing/execution paths explicitly distinct, with no mixed assumptions?
- If the design deviates from PR #5, is that deviation explicit and justified?
- Are Omen and Polymarket both described completely in the data flow?

Expected output:

- Clear statement of consistency between local algorithm spec and rollout plan
- Clear statement of parity vs PR #5
- Explicit list of intentional deviations

### 2. Parameter Contract

Every parameter must be defined with:

- name
- type
- unit/scale
- venue applicability
- source of truth
- whether it is:
  - execution input
  - policy/risk guardrail
  - external friction
  - backward-compat/config-only field

Checks:

- Are `max_bet`, `min_bet`, `floor_balance`, `n_bets`, `bet_fee`, `fee_per_trade`, `market_price`, and `min_order_shares` fully specified?
- Is there any ambiguity about decimal scale?
- Is there any ambiguity about whether a fee is a venue fee or an external friction fee?
- Are config-only compatibility fields distinguished from model parameters?

Expected output:

- A complete parameter table with units and ownership
- A list of unresolved ambiguities

### 3. Data-Flow Completeness

For each venue, verify that the spec states exactly where every input comes from.

Checks for Polymarket:

- Where do `orderbook_asks` come from?
- Where does `market_price` come from?
- Where does `min_order_shares` come from?
- Are all required pricing/execution values fetched once or multiple times?

Checks for Omen:

- Where do `selected_type_tokens_in_pool` and `other_tokens_in_pool` come from?
- Where does `market_price` come from?
- Where does `bet_fee` come from?
- Is the Omen path equally explicit in the new data flow?

Expected output:

- Venue-by-venue input source map
- Missing or implicit dependencies called out

### 4. Regression Surface

Check whether the spec preserves important existing behavior.

Checks:

- Does the design preserve current ChatUI assumptions where needed?
- Does it preserve existing non-Kelly behavior?
- Does it preserve fallback strategy behavior?
- Does it preserve legacy strategy name compatibility where needed?
- Does it preserve current agent/service config assumptions?

Expected output:

- List of possible regressions
- Required compatibility actions

### 5. API-Call Delta

Check whether the new design replaces old logic efficiently or simply adds more requests.

Checks:

- How many API calls are made per market before the change?
- How many API calls are made per market after the change?
- Are new calls replacing old pricing/profitability logic, or layering on top?
- Are there duplicate requests for values already available in memory?

Expected output:

- Per-market/per-cycle API call budget
- Explicit statement of added, removed, and unchanged calls

### 6. Pricing Consistency

The pricing model must be consistent across:

- sizing
- profitability
- execution assumptions
- order placement safety checks

Checks:

- Is the same market data model used for sizing and profitability?
- Are there any places where sizing uses one price basis and execution uses another?
- Is `expected_profit` defined using the same accounting as the Kelly objective?
- Are venue fees and external friction fees separated consistently?

Expected output:

- Pricing consistency checklist
- List of remaining ambiguities

### 7. Timing and Staleness Risk

Check the design for quote-to-execution drift on both venues.

Questions:

- What happens if the Polymarket orderbook changes after sizing?
- What happens if Omen pool reserves / marginal prices change after sizing?
- Does the design require a second execution-time validation?
- Is there a stale-book risk on Polymarket?
- Is there a stale-pool / stale-marginal-price risk on Omen?
- Is the chosen bet still valid if minimum executable spend changes before placement?
- Is the chosen Omen bet still valid if pool state shifts enough that the modeled
  shares or effective price move materially before execution?

Expected output:

- Required slippage/staleness protections for both Polymarket and Omen
- List of unresolved timing assumptions

---

## Required Outputs From Spec Audit

Every spec audit should produce:

1. A pass/fail statement on model coherence
2. A consistency check between local algorithm spec and rollout plan
3. A list of intentional deviations from PR #5
4. A complete parameter/unit contract
5. A venue-by-venue data input map
6. An API-call budget per market/cycle
7. A regression risk list
8. A pricing consistency summary
9. A slippage/staleness risk summary
10. A blocking issues list

---

## Spec Audit Checklist

Use this checklist before implementation begins.

- [ ] The design states exactly what is intended to match PR #5.
- [ ] The local algorithm spec and implementation plan are mutually consistent.
- [ ] Any deviation from PR #5 is explicit and justified.
- [ ] Polymarket input flow is fully documented.
- [ ] Omen input flow is fully documented.
- [ ] All parameters are defined with units and venue applicability.
- [ ] Fee accounting is unambiguous.
- [ ] Compatibility with ChatUI/config is explicit.
- [ ] Legacy strategy compatibility is explicit.
- [ ] New API calls are justified and counted.
- [ ] Pricing model is consistent from sizing to execution.
- [ ] Slippage/staleness protections are addressed in the design.
- [ ] No critical ambiguity remains before implementation begins.

---

## Recommended Review Output Template

Use this structure when writing a spec audit review:

### Scope

- Documents reviewed
- Reference behavior used

### Expected Model

- Summary of intended Kelly model
- Venue-specific execution assumptions

### Intentional Deviations

- Explicit differences vs PR #5

### Parameter Contract

- Table or summary of parameters, units, and ownership

### Data Sources

- Per-venue input source map

### API Call Budget

- Before vs after request counts

### Pricing Path

- How pricing moves from sizing to execution

### Regression Risks

- Existing behavior that may break

### Blocking Issues

- Issues that must be resolved before implementation

### Outcome

- Go / no-go recommendation
