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
- commit `40022fb485183623ad7de16316de9658ef4adcdc`

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

### 1. `expected_profit` still uses a deleted variable, so the core return contract is internally inconsistent

The latest plan correctly moves from `win_probability` to `p_yes` / `p_no` and
states that `PredictionResponse.win_probability` is dead code. However, the core
strategy pseudocode still computes:

```python
expected_profit = (
    win_probability * best_result["shares"] - best_result["spend"] - fee_per_trade
)
```

That variable no longer exists in the proposed contract. Implemented literally,
the strategy would either fail or quietly reintroduce the old single-side
semantics into the downstream profitability field.

Impact:

- the main strategy pseudocode is not self-consistent
- `expected_profit` is not well defined for the chosen side
- implementation risk is high because the bug sits in the central return path

Status:

- blocking

### 2. The CLOB minimum-fill helper is referenced but never defined in the algorithm section

The updated plan correctly switches Polymarket minimum spend to a walked-book
calculation:

```python
min_fill_cost, _ = walk_book_for_shares(sorted_asks, min_order_shares)
```

But `walk_book_for_shares()` is never defined anywhere in the strategy design,
while only `walk_book()` is specified.

Impact:

- the CLOB pricing path is still incomplete at the spec level
- the most important Polymarket sizing safeguard is underspecified
- reviewers cannot verify exact behavior for partial depth, insufficient depth,
  or non-fillable minimum-share scenarios

Status:

- blocking

### 3. The `fixed_bet` migration is inconsistent across strategy-reference sections

The plan introduces `fixed_bet` as the replacement for
`bet_amount_per_threshold`, and `chatui_abci/prompts.py` includes the new enum
member. But `agent_performance_summary_abci/graph_tooling/predictions_helper.py`
still shows:

```python
class TradingStrategy(enum.Enum):
    KELLY_CRITERION = "kelly_criterion"
    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
```

while the very next section maps `TradingStrategy.FIXED_BET.value`.

Impact:

- the migration spec is not internally consistent
- if followed literally, downstream graph tooling will be missing the new enum member
- this creates avoidable regression risk in reporting/UI surfaces

Status:

- blocking

### 4. The config/unit contract is still unresolved for Polymarket max-bet values

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

### 5. API-call budget and execution-time revalidation remain underspecified

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

1. Is `expected_profit` explicitly computed with the probability of the selected side (`p_yes` for YES, `p_no = 1 - p_yes` for NO), rather than with a stale shared variable such as `win_probability`?
2. What is the exact contract of `walk_book_for_shares()` when the orderbook cannot supply `min_order_shares`?
3. Should `agent_performance_summary_abci` fully migrate to `FIXED_BET`, or intentionally keep both names during the migration window?
4. Are Polymarket-compatible max-bet values written in native 6-decimal USDC units or normalized to 18 decimals before execution?
5. What is the accepted per-market request budget after the new Polymarket flow, and do we require execution-time revalidation for both venues?

---

## Outcome

Current result: `no-go`

Reason:

The latest spec is substantially stronger than the earlier draft. It now clearly
covers both-side evaluation, Omen/FPMM data flow, Polymarket minimum-order-share
plumbing, and startup compatibility for legacy Kelly naming.

The remaining blockers are narrower but still important:

- the central `expected_profit` formula is using a deleted variable
- the minimum-fill helper for CLOB is not fully specified
- the `fixed_bet` migration is inconsistent across reference sections
- the Polymarket decimal/unit contract is still open

Implementation should wait until those are resolved, and the API-call /
staleness story should be tightened before coding starts.

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
- [OPEN] `expected_profit` follows the exact optimizer accounting
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
- [PARTIAL] Non-Kelly strategy behavior is unchanged where intended

### D. Performance / Request Checks

- [OPEN] API calls per market/cycle are within expected budget
- [OPEN] Duplicate requests are eliminated where possible
- [OPEN] No unnecessary new calls are made only for convenience
