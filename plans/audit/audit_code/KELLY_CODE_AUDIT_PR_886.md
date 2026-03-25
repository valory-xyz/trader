# Kelly Code Audit Report for PR #886

**PR:** [#886](https://github.com/valory-xyz/trader/pull/886)  
**Latest audited commit:** `0eb18e7b596f12729647ea8835b4158e62002988`  
**Title:** `feat: unified Kelly criterion implementation (PREDICT-836)`

## Scope

This audit was run against the Kelly code audit framework in:
- `plans/audit/audit_code/KELLY_CODE_AUDIT_FRAMEWORK.md`

Reference docs used during audit:
- `plans/KELLY_IMPLEMENTATION_PLAN.md`
- `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`

## Review Comments Read

Review comments currently visible on the PR:

1. `n_bets` is considered too conservative:
   - [discussion 1](https://github.com/valory-xyz/trader/pull/886#discussion_r2987835481)
   - [discussion 2](https://github.com/valory-xyz/trader/pull/886#discussion_r2987836954)

2. `fee_per_trade` unit consistency:
   - [question](https://github.com/valory-xyz/trader/pull/886#discussion_r2987865308)
   - [suggested fix](https://github.com/valory-xyz/trader/pull/886#discussion_r2987883301)

There were no separate issue comments on the PR when checked.

---

## Findings

### High: Omen `trader` config removed compatibility keys that runtime still requires

**Files:**
- `packages/valory/skills/decision_maker_abci/behaviours/base.py`
- `packages/valory/skills/chatui_abci/models.py`
- `packages/valory/services/trader/service.yaml`
- `packages/valory/skills/trader_abci/skill.yaml`

**Issue:**  
The runtime still assumes `strategies_kwargs` contains:
- `absolute_min_bet_size`
- `default_max_bet_size`

But those keys are missing from the Omen `trader` service/skill config in this PR.

**Why this matters:**  
- `get_bet_amount()` reads `absolute_min_bet_size` directly.
- ChatUI store hydration reads `default_max_bet_size` and `absolute_min_bet_size` directly.

That means the Omen service can crash with `KeyError` during normal runtime paths.

**Code references:**
- `packages/valory/skills/decision_maker_abci/behaviours/base.py:563-564`
- `packages/valory/skills/chatui_abci/models.py:136-145`
- `packages/valory/services/trader/service.yaml:129-130`
- `packages/valory/skills/trader_abci/skill.yaml:243-250`

**Audit classification:**  
- Correctness / compatibility regression
- Blocking

### Resolved: live legacy strategy-name acceptance is now restricted correctly

**Files:**
- `packages/valory/skills/chatui_abci/prompts.py`
- `packages/valory/skills/chatui_abci/handlers.py`
- `packages/valory/skills/decision_maker_abci/behaviours/base.py`

**Issue:**  
This was a previous blocker. The latest PR head no longer includes the legacy
aliases in the live accepted strategy set.

**Why this matters:**  
The old aliases are still mapped for display and compatibility helpers, but
they are no longer accepted as active runtime strategy values. That removes the
runtime path where ChatUI could store a legacy strategy name that had no
executable implementation.

**Code references:**
- `packages/valory/skills/chatui_abci/prompts.py:79-80`
- `packages/valory/skills/chatui_abci/handlers.py:426-434`
- `packages/valory/skills/chatui_abci/tests/test_handlers.py:615-667`

**Audit classification:**  
- Resolved in latest audited commit

### Resolved: `min_order_shares` is now sourced from the Polymarket orderbook response

**Files:**
- `packages/valory/customs/kelly_criterion/kelly_criterion.py`
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py`
- `packages/valory/skills/market_manager_abci/behaviours/polymarket_fetch_market.py`
- `packages/valory/skills/market_manager_abci/bets.py`

**Issue:**  
This was a previous blocker. The latest PR head now extracts
`min_order_size` from the Polymarket `/book` response and passes it into Kelly
sizing as `min_order_shares`.

**Why this matters:**  
This matches the intended design more closely and removes the hardcoded `5.0`
fallback from the live Polymarket decision path.

**Code references:**
- `packages/valory/connections/polymarket_client/connection.py:540-545`
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:454-475`

**Audit classification:**  
- Resolved in latest audited commit

### High: previous rebet gate is no longer applied in the live profitability path

**Files:**
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py`
- `packages/valory/skills/market_manager_abci/bets.py`

**Issue:**  
`rebet_allowed()` still exists, but `_is_profitable()` no longer calls it before approving a trade.

**Why this matters:**  
This is not just an internal refactor. The previous decision path applied an
additional repeat-bet guard before approving another trade on the same market.
The new path no longer does so, which means the trader can place repeated bets
on the same market without the prior confidence/liquidity/profit comparison
gate. We should maintain the policy to avoid rebetting when the new candidate
does not improve on the previous bet under the existing
confidence/liquidity/profit checks. Since the new path skips that guard, this is
a blocking policy regression.

**Code references:**
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:381-401`
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:468-504`
- `packages/valory/skills/market_manager_abci/bets.py:372-392`

**Audit classification:**  
- Regression / policy regression
- Blocking

---

## Spec Mismatches

### 1. Repeat-bet policy differs from the previous live decision flow

The previous decision path applied an additional repeat-bet guard before
approving another trade on the same market. The current path still skips that
guard after the strategy returns a positive result.

---

## Parameter Review

| Parameter | Kind | Source of truth | Implemented/configured value in PR `886` | Suggested/default | Match? | Notes |
|---|---|---|---|---|---|---|
| `floor_balance` | configurable | service / skill YAML | `1_000_000` on Polymarket, `5e17` on `trader_pearl`, `0` on `trader` | plan/spec allows venue-specific config | Partial | Values are intentional per service, but `trader` config differs from the plan examples |
| `max_bet` | configurable | ChatUI `max_bet_size` or strategy default | defaulted via strategy if not overridden; ChatUI/runtime still expects `default_max_bet_size` compatibility key | `5e6` USDC / `8e17` xDAI in plan | Partial | Runtime still depends on compatibility keys; restored in `trader_abci` skill YAML but still missing in `trader` service YAML |
| `min_bet` | configurable / derived from config | `absolute_min_bet_size` in `strategies_kwargs`, then passed to strategy | present in Polymarket and `trader_pearl`; restored in `trader_abci` skill YAML; still missing in `trader` service YAML | plan expects compatibility key retained | No | Real runtime issue remains at service level |
| `n_bets` | configurable | service / skill YAML | `1` | `1` | Yes | Matches current plan/spec default, though review comments suggest it may be too conservative |
| `min_edge` | configurable | service / skill YAML | `0.03` | `0.03` | Yes | Matches |
| `min_oracle_prob` | configurable | service / skill YAML | `0.5` | `0.5` | Yes | Matches |
| `fee_per_trade` | configurable | service / skill YAML | `10000` USDC-wei on Polymarket, `1e16` xDAI-wei on Omen | docs still say `0.01` native units, code expects wei-scaled int | Partial | Code/config are internally consistent; docs lag behind |
| `grid_points` | configurable | service / skill YAML | `500` | `500` | Yes | Matches |
| `token_decimals` | derived | collateral token in caller | `6` for USDC, `18` otherwise | venue-derived | Yes | Correctly derived in caller |
| `price_yes` | required runtime input | current market/orderbook snapshot | passed from `Bet.outcomeTokenMarginalPrices` | venue runtime data | Yes | Used as intended |
| `price_no` | required runtime input | current market/orderbook snapshot | passed from `Bet.outcomeTokenMarginalPrices` | venue runtime data | Yes | Used as intended |
| `orderbook_asks_yes` | venue-provided | Polymarket `/book` | fetched live | fetched live | Yes | Present |
| `orderbook_asks_no` | venue-provided | Polymarket `/book` | fetched live | fetched live | Yes | Present |
| `min_order_shares` | venue-provided | Polymarket `/book min_order_size` | extracted from the fetched orderbook response and passed into strategy | venue-provided | Yes | Fixed in latest audited commit |
| `tokens_yes` | venue-provided | Omen `Bet.outcomeTokenAmounts` | passed live | venue runtime data | Yes | Present |
| `tokens_no` | venue-provided | Omen `Bet.outcomeTokenAmounts` | passed live | venue runtime data | Yes | Present |
| `bet_fee` | venue-provided | Omen `Bet.fee` | passed live, normalized in strategy | venue runtime data | Yes | Looks correct in code path |

### Notes

- `n_bets=1` matches the current plan/spec default, even if reviewers may want
  a less conservative production value.
- `fee_per_trade` is now implemented as wei-scaled native units in the code and
  bundled YAML configs.
- `min_order_shares` now matches the intended Polymarket source-of-truth model.
- The `trader_abci` skill YAML restored compatibility keys, but the `trader` service YAML is still missing them.

---

## Pricing / Execution Risks

### Passes

- Polymarket is modeled as CLOB.
- Omen is modeled as FPMM.
- The Kelly implementation guards:
  - `log(W_bet)`
  - `log(W_win)`
  - `log(W_lose)`
  - FPMM denominator `y + alpha * b`

### Accepted non-blocking gap

Execution-time revalidation / slippage protection is still absent. Under the
audit framework, this is not a blocker by itself as long as it is treated as
accepted follow-up work rather than falsely implied as implemented.

---

## Failure-Mode Coverage

### Shared

- Missing market price: partially handled
- Invalid decimal scale: partially handled
- Legacy config values: partially handled; live strategy-name acceptance issue appears resolved

### Polymarket (CLOB)

- Empty/malformed orderbook: handled by no-trade path
- Missing token IDs: partially handled
- Missing `min_order_shares`: now handled via the Polymarket `/book` response
- Partial depth for minimum fill: handled in strategy

### Omen (FPMM)

- Invalid/zero pool values: partially guarded
- Invalid denominator in FPMM formula: guarded
- Venue fee input normalization: appears improved after latest `fee_per_trade`
  fix, but still worth explicit verification in full integration tests

---

## Test / Verification Notes

### Ran successfully

```bash
pytest packages/valory/customs/kelly_criterion/test_kelly_criterion.py -q
```

Result:
- `52 passed`

### Could not run in this environment

```bash
pytest packages/valory/skills/decision_maker_abci/tests/behaviours/test_base.py -q
pytest packages/valory/skills/decision_maker_abci/tests/behaviours/test_decision_receive.py -q
```

Reason:
- missing test dependency: `hypothesis`

So the integration audit is source-based for those areas, not fully
test-verified in this environment.

---

## Audit Coverage Checklist

### 1. Spec Adherence

- [x] Checked against `plans/KELLY_IMPLEMENTATION_PLAN.md`
- [x] Checked against `plans/kelly/UNIFIED_KELLY_ALGO_SPEC.md`
- [x] Compared behavior vs PR `#5` at a high level
- [x] Checked venue model mapping: Polymarket (CLOB), Omen (FPMM)
- [x] Called out spec mismatches
- [ ] Exhaustively mapped every intentional deviation from PR `#5`

### 1A. Parameter Selection and Defaults

- [x] Added parameter table to the report
- [x] Included source of truth / current value / suggested value / match
- [x] Called out mismatches
- [ ] Verified every parameter value against all service variants beyond the main touched paths

### 2. Pricing Logic Integrity

- [x] Reviewed sizing/accounting flow in strategy
- [x] Reviewed `expected_profit` consistency
- [x] Reviewed fee separation
- [x] Reviewed caller integration around profitability approval
- [ ] Fully validated every downstream consumer of `expected_profit`

### 2A. Numerical Safety and Domain Checks

- [x] Checked `log(W_bet)`, `log(W_win)`, `log(W_lose)`
- [x] Checked FPMM denominator guard
- [x] Checked `grid_points` clamp
- [ ] Ran dedicated numerical edge-case integration tests outside unit strategy tests

### 3. Slippage and Quote-to-Execution Drift

- [x] Reviewed this area conceptually
- [x] Treated it as non-blocking follow-up per framework
- [ ] Verified placement-time protection implementation, because none is really present

### 4. Regression Risk

- [x] Checked Polymarket path
- [x] Checked Omen path
- [x] Checked fixed-bet replacement
- [x] Checked legacy-name/runtime compatibility
- [x] Checked config migration risks
- [x] Identified repeat-bet policy regression
- [ ] Fully verified all UI/reporting surfaces by execution, not just source review

### 5. API-Call Regression

- [x] Reviewed the new Polymarket orderbook-fetch pattern
- [x] Confirmed `min_order_size` comes from the same `/book` call
- [ ] Produced a formal per-cycle API budget from live traces

### 6. Failure-Mode Handling

- [x] Reviewed shared failure modes
- [x] Reviewed Polymarket-specific failure modes
- [x] Reviewed Omen-specific failure modes
- [x] Investigated `min_order_shares` handling with live API samples
- [ ] Exhaustively tested malformed/live failure cases end to end

### Verification Actually Performed

- [x] Read PR comments
- [x] Fetched latest PR `886` head
- [x] Audited source code directly
- [x] Ran strategy tests: `52 passed`
- [x] Sampled 10 live Polymarket markets for `min_order_size`
- [ ] Ran `decision_maker_abci` behavior tests
  Reason: blocked by missing `hypothesis`
- [ ] Ran full test suite for the PR in this environment

### Coverage Summary

This report covers the audit framework substantially, but not completely.
The strongest coverage areas are:

- source-level review of strategy and caller integration
- config/runtime mismatch detection
- parameter review
- numerical safety review
- live Polymarket API sampling for `min_order_size`

The weakest coverage areas are:

- end-to-end integration execution
- full behavior-test validation
- exhaustive downstream verification of all consumer paths

Accordingly, this should be treated as a strong source audit with partial test
validation, not as a full execution-certified signoff.

---

## Go / No-Go

**Current result: `no-go`**

### Blocking issues

1. Omen `trader` service config still omits compatibility keys required by runtime.
2. The previous repeat-bet guard is no longer applied before approving a new trade.

### Non-blocking but important

1. `min_order_shares` now appears fixed and no longer belongs in the open-issues list.

---

## Short Conclusion

The PR is much closer now. The Polymarket `min_order_size` plumbing looks
fixed, legacy strategy aliases are no longer part of the live accepted
strategy set, and the Kelly strategy tests pass on the latest audited head. But
it is still not merge-ready yet under the Kelly audit framework because two
blocking issues remain:
- compatibility keys are still missing in the deployed `trader` service YAML
- the repeat-bet guard is still not enforced in the live buy path
