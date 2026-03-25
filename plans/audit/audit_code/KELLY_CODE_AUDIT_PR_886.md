# Kelly Code Audit Report for PR #886

**PR:** [#886](https://github.com/valory-xyz/trader/pull/886)  
**Latest audited commit:** `6f36d2fab6930e4e2d806dadd12b6b5e5e5189fc`  
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

### High: ChatUI still accepts legacy strategy names, but runtime no longer normalizes them

**Files:**
- `packages/valory/skills/chatui_abci/prompts.py`
- `packages/valory/skills/chatui_abci/handlers.py`
- `packages/valory/skills/decision_maker_abci/behaviours/base.py`

**Issue:**  
ChatUI still exposes and accepts:
- `kelly_criterion_no_conf`
- `bet_amount_per_threshold`

But strategy execution now looks up executables by exact runtime name and does not normalize those old names.

**Why this matters:**  
A user can select an old strategy name through ChatUI, the UI accepts it, it gets stored, and then live execution fails with “no executable was found”, effectively suppressing betting.

**Code references:**
- `packages/valory/skills/chatui_abci/prompts.py:75-81`
- `packages/valory/skills/chatui_abci/handlers.py:426-434`
- `packages/valory/skills/decision_maker_abci/behaviours/base.py:151-167`
- `packages/valory/skills/decision_maker_abci/behaviours/base.py:551-595`

**Audit classification:**  
- Compatibility regression
- Blocking

### Medium: `min_order_shares` is still effectively hardcoded to `5.0`

**Files:**
- `packages/valory/customs/kelly_criterion/kelly_criterion.py`
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py`
- `packages/valory/skills/market_manager_abci/behaviours/polymarket_fetch_market.py`
- `packages/valory/skills/market_manager_abci/bets.py`

**Issue:**  
The plan/spec says `min_order_shares` should be venue-provided, not hardcoded. In the current implementation:
- `Bet` does not appear to persist `min_order_shares`
- caller falls back to `5.0`
- strategy also defaults to `5.0`

**Why this matters:**  
If the real venue minimum differs from `5.0`, the strategy can miscompute admissibility and minimum spend.

**Code references:**
- `packages/valory/customs/kelly_criterion/kelly_criterion.py:342-369`
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:454-481`
- `packages/valory/skills/market_manager_abci/behaviours/polymarket_fetch_market.py:447-473`
- `packages/valory/skills/market_manager_abci/bets.py:150-167`

**Audit classification:**  
- Spec mismatch
- Medium severity

### Medium: previous rebet gate is no longer applied in the live profitability path

**Files:**
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py`
- `packages/valory/skills/market_manager_abci/bets.py`

**Issue:**  
`rebet_allowed()` still exists, but `_is_profitable()` no longer calls it before approving a trade.

**Why this matters:**  
This is a behavior change from the previous flow, and it may allow repeated bets that were previously filtered out.

**Code references:**
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:381-401`
- `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:468-504`
- `packages/valory/skills/market_manager_abci/bets.py:372-392`

**Audit classification:**  
- Regression risk
- Medium severity

---

## Spec Mismatches

### 1. Legacy strategy handling differs from the implementation plan

The implementation plan expected compatibility handling across startup, runtime,
and UI surfaces. The PR summary explicitly says runtime normalization was
removed. The current code still accepts old names in UI surfaces but does not
normalize them at execution time.

### 2. `min_order_shares` propagation does not match the plan/spec

The plan/spec say venue minimum order size should be sourced from
market/orderbook data. The live path still falls back to `5.0`.

---

## Parameter Review

Parameters visibly selected in code/config:
- `floor_balance`
- `n_bets`
- `min_edge`
- `min_oracle_prob`
- `fee_per_trade`
- `grid_points`
- `token_decimals`
- `min_order_shares`

### Notes

- `n_bets=1` matches the current plan default.
- `fee_per_trade` now appears to be expressed in wei-scaled native units, which
  aligns with the latest review feedback.
- `min_order_shares` does **not** fully match the intended source-of-truth model yet.
- Omen `trader` config is missing compatibility keys still required by runtime.

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
- Legacy config values: not fully safe due to runtime normalization gap

### Polymarket (CLOB)

- Empty/malformed orderbook: handled by no-trade path
- Missing token IDs: partially handled
- Missing `min_order_shares`: not fully handled, falls back to `5.0`
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
- `49 passed`

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

## Go / No-Go

**Current result: `no-go`**

### Blocking issues

1. Omen `trader` config removed compatibility keys still required by runtime.
2. ChatUI still accepts legacy strategy names without runtime normalization.

### Non-blocking but important

1. `min_order_shares` is not yet truly venue-provided.
2. Rebet gating behavior changed and should be either restored or explicitly accepted.

---

## Short Conclusion

The PR is close on core Kelly strategy math, and the new `fee_per_trade` unit
handling appears to be moving in the right direction. But it is not merge-ready
yet under the Kelly audit framework because there are still two real runtime
compatibility regressions:
- config keys missing for Omen
- legacy strategy names accepted by UI but not executable at runtime

If those are fixed, the remaining issues become much more manageable.
