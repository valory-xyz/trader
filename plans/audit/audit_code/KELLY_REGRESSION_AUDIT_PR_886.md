# Kelly Regression Audit — PR #886

**Date**: 2026-03-25
**Scope**: Regression risks, regression test gaps, and suggested additional regression tests
**Branch**: `jenslee/predict-836-kelly-implementation`
**Base**: `jenslee/predict-836-fix-fpmm-to-clob-kelly-mismatch`
**Framework**: `plans/audit/audit_code/KELLY_CODE_AUDIT_FRAMEWORK.md` (sections 4, C, Regression Tests)

---

## Summary of Architectural Change

The PR moves profitability and side selection from the caller (`_is_profitable`) into
the strategy. Previously, `_is_profitable` had separate Omen/Polymarket branches that
each computed profitability and derived `vote` from `prediction_response.vote`. Now:

- The strategy returns `bet_amount`, `vote`, `expected_profit`, `g_improvement`.
- The caller checks `bet_amount > 0` and `vote is not None`.
- `prediction_response.vote` (mech's higher-probability side) is still used for selling.

This shift creates a **split-authority model**: the strategy decides the trading side,
but several downstream code paths still read `prediction_response.vote` or
`bet.prediction_response.vote`. This is the primary source of regression risk.

---

## Regression Issues — Ordered by Severity

### R1. CRITICAL — `Bet.update_investments()` uses `prediction_response.vote`, not strategy vote

**File**: `packages/valory/skills/market_manager_abci/bets.py:340`
**Code**:
```python
def update_investments(self, amount: int) -> bool:
    vote = self.prediction_response.vote
    if vote is None:
        return False
    outcome = self.get_outcome(vote)
    ...
```

`update_investments` is called from `_update_selected_bet` (line 543 of
`decision_receive.py`), which is invoked during benchmarking mode (line 666).
The bet's `prediction_response` is the *mech's* assessment, not the strategy's
chosen side. The Kelly strategy can choose NO even when `prediction_response.vote`
= 0 (YES), if NO has better log-growth.

**Impact**: In benchmarking mode, investment amounts may be tracked under the
wrong outcome (YES vs NO). This corrupts benchmarking P&L reporting.

**In production** (non-benchmarking): `_update_selected_bet` is not called, so this
code path is not hit for live trading. However, this is a latent bug that will
surface when benchmarking is used to validate the Kelly strategy.

**Recommendation**: Pass `strategy_vote` to `_update_selected_bet` and use it to
override `prediction_response.vote` before calling `update_investments`, or refactor
`update_investments` to accept a `vote` parameter directly.

---

### R2. HIGH — `rebet_allowed` is incompatible with strategy-owns-side model

**File**: `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:381-401`
**Code**:
```python
def rebet_allowed(self, prediction_response, potential_net_profit):
    bet.prediction_response = prediction_response
    vote = bet.prediction_response.vote          # <-- mech's vote, not strategy's
    bet.position_liquidity = bet.outcomeTokenAmounts[vote] if vote else 0
```

And in `Bet.rebet_allowed` (`bets.py:387`):
```python
if self.prediction_response.vote == prediction_response.vote:
    higher_liquidity = self.position_liquidity >= liquidity
    return more_confident and higher_liquidity
```

**Impact**: When rebetting is re-enabled, this method compares the *mech's*
vote (probability-based) against the previous *mech's* vote, not the strategy's
chosen side. If the Kelly strategy picks NO while the mech's higher-prob side is YES,
`rebet_allowed` will:
1. Set `position_liquidity` using the wrong token index
2. Compare votes incorrectly (same mech vote ≠ same strategy side)

The PR description acknowledges "rebet_allowed not called" and "must be updated to
work without PredictionResponse.vote". This is documented but has **no regression
test** proving the method is indeed unreachable, and no guard preventing accidental
re-introduction.

**Recommendation**: Add an explicit `raise NotImplementedError("...")` or a guard
that logs an error, so rebet cannot silently run with wrong logic. Add a regression
test that asserts `rebet_allowed` is never called in the current flow.

---

### R3. HIGH — `strategies_kwargs` in service YAML missing ChatUI compat keys

**File**: `packages/valory/services/trader/service.yaml:130`
**Default value**:
```json
{"floor_balance":0,"n_bets":1,"min_edge":0.03,"min_oracle_prob":0.5,"fee_per_trade":0.01,"grid_points":500}
```

**File**: `packages/valory/agents/trader/aea-config.yaml:245`
**Default value**:
```json
{"floor_balance":500000000000000000,"default_max_bet_size":2000000000000000000,
 "absolute_min_bet_size":25000000000000000,"absolute_max_bet_size":2000000000000000000,
 "n_bets":1,"min_edge":0.03,"min_oracle_prob":0.5,"fee_per_trade":0.01,"grid_points":500}
```

The service YAML env-default overrides the aea-config default at runtime. Operators
deploying via the service YAML without explicitly setting `STRATEGIES_KWARGS` will
get defaults **without** `default_max_bet_size`, `absolute_min_bet_size`, or
`absolute_max_bet_size`.

In `get_bet_amount` (`base.py:564`):
```python
kwargs["min_bet"] = self.params.strategies_kwargs["absolute_min_bet_size"]
```

This will **KeyError** if the key is missing.

Additionally, `_ensure_chatui_store()` reads these keys. Missing keys would cause the
ChatUI config hydration to fail.

**Impact**: Startup crash for operators who deploy using the service definition
without overriding `STRATEGIES_KWARGS`.

**Recommendation**: Add `default_max_bet_size`, `absolute_min_bet_size`, and
`absolute_max_bet_size` to the service YAML defaults, matching the aea-config values.

---

### R4. MEDIUM — `async_act` dead code branch (lines 636-646)

**File**: `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:636-646`

```python
elif (
    prediction_response is not None          # always True here
    and self.benchmarking_mode.enabled
    and not self._rows_exceeded
):
    self._write_benchmark_results(prediction_response, bet_amount)
    ...
```

This `elif` follows `if prediction_response is not None:` (line 603). Since the outer
`if` already guards for `prediction_response is not None`, the `elif` can only be
reached when `prediction_response is None` — at which point the `elif` condition
`prediction_response is not None` is always `False`. This branch is unreachable.

**Impact**: Benchmarking results for "mech returned data but trade not profitable"
are never written. This was previously handled in the old `_is_profitable` flow.
In the new code, `_is_profitable` writes benchmarking results internally (lines
516-523), but only when it's actually called. If the selling flow takes priority
(line 614-622), the benchmarking write is skipped.

**Recommendation**: Review the intended benchmarking write coverage. This may be
harmless (benchmarking doesn't use the selling path) or a regression in benchmarking
fidelity. Add a test that exercises the benchmarking+selling path.

---

### R5. MEDIUM — Bet's `prediction_response` is never updated after strategy decision

In the non-benchmarking flow:
1. `_is_profitable` runs, strategy returns `strategy_vote`
2. `store_bets()` is called (line 633)
3. The bet's `prediction_response` attribute still holds the *default* or *previous* value

The bet's `.prediction_response` is only updated inside `rebet_allowed` (line 388),
which is not called. Any downstream code that reads `bet.prediction_response` for
reporting, performance tracking, or future rebet evaluation will see stale data.

**Impact**: The `strategy` field on the bet IS set (via `base.py`'s execute_strategy),
but the `prediction_response` on the stored bet does not reflect the current mech
response that led to the trade. Historical bet records will have incorrect
prediction_response data.

---

### R6. MEDIUM — `fee_per_trade` unit ambiguity between config and code

**Config** (`service.yaml:130`): `"fee_per_trade": 0.01`
**Commit message** (6f36d2f): "All strategies_kwargs values are now in wei"

In the Kelly strategy (`kelly_criterion.py:271`):
```python
fee_per_trade: float = kwargs.get("fee_per_trade", DEFAULT_FEE_PER_TRADE)
```

The `fee_per_trade` value from config (0.01) is used directly in `optimize_side`
as a native-unit deduction (`w_win = w_bet - cost + n_shares - fee`), where
`w_bet`, `cost`, and `n_shares` are all in native units (xDAI/USDC).

If 0.01 is native units (0.01 xDAI), this is correct. But the commit message claims
values are "in wei", which would make 0.01 effectively zero (0.01 wei ≈ 0 xDAI).

Contrast with `max_bet` which IS in wei and IS converted: `max_bet = max_bet_wei / scale`.

`fee_per_trade` is NOT converted by `/ scale`. So the YAML value 0.01 is interpreted
as 0.01 native units, which is correct behavior but contradicts the commit message.

**Impact**: Currently correct (0.01 xDAI fee), but the commit message creates
confusion. A future contributor may "fix" this by changing the YAML value to wei
(e.g., 10000000000000000), which would produce a massive fee deduction.

**Recommendation**: Clarify the unit convention. Either convert `fee_per_trade`
from wei like other params, or document that it is an exception.

---

### R7. LOW — No guard against CLOB orderbook fetch failure for both sides

**File**: `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:454-466`

If both orderbook fetches return `None` (API timeout, connection issue), both
`orderbook_asks_yes` and `orderbook_asks_no` remain `None`. The Kelly strategy
will reject both sides ("no orderbook asks available") and return no-trade.

This is **correct fail-safe behavior** but there is no regression test covering
this scenario. A future change that makes the strategy ignore missing orderbooks
could silently introduce a bug.

---

### R8. LOW — `min_order_shares` hardcoded fallback

**File**: `packages/valory/skills/decision_maker_abci/behaviours/decision_receive.py:468`
```python
min_order_shares = getattr(bet, "min_order_shares", None) or 5.0
```

The fallback of 5.0 shares is a Polymarket-specific constant. If the bet object
has `min_order_shares = 0` or `min_order_shares = 0.0`, the `or 5.0` will
override it to 5.0 (since 0 is falsy). This could prevent valid bets on markets
where the venue minimum is less than 5 shares.

---

## Regression Test Coverage Analysis

### Existing Tests (from PR)

| Test Class | Count | What It Tests |
|---|---|---|
| `TestIsProfitable` | 8 | Strategy positive/zero/None vote, CLOB orderbook fetch, benchmarking |
| `TestFetchOrderbook` | 3 | Success, None response, error response |
| `TestRebetAllowed` | 2 | Allowed / not allowed (basic mocking) |
| `TestShouldSellOutcomeTokens` | 4 | None pred, zero tokens, low/high confidence |

### Missing Regression Tests — Detailed

#### RT1. Strategy vote diverges from prediction_response.vote

**Why**: The core architectural change is that the strategy owns the vote. But no
test verifies correct behavior when `strategy_vote != prediction_response.vote`.

**Suggested tests**:

```
test_is_profitable_strategy_vote_differs_from_mech:
    Setup: prediction_response with p_yes=0.7 (mech says YES, vote=0)
           strategy returns vote=1 (NO has better log-growth)
    Assert: is_profitable=True, strategy_vote=1, bet_amount > 0
    Assert: payload vote = 1 (not 0)

test_is_profitable_strategy_vote_yes_when_mech_says_no:
    Setup: prediction_response with p_yes=0.3 (mech says NO, vote=1)
           strategy returns vote=0 (YES has better log-growth)
    Assert: strategy_vote=0
```

#### RT2. Selling flow unaffected by strategy changes

**Why**: The selling flow still uses `prediction_response.vote` and should be
unaffected by the Kelly changes. No test verifies this end-to-end.

**Suggested tests**:

```
test_async_act_selling_ignores_strategy_vote:
    Setup: review_bets_for_selling_mode=True
           prediction_response with p_yes=0.8 (vote=0)
           should_sell_outcome_tokens returns True
    Assert: payload vote = opposite of sell_vote (= 1)
    Assert: _is_profitable is NOT called
    Assert: strategy_vote is not used

test_async_act_selling_with_p_yes_equals_p_no:
    Setup: review_bets_for_selling_mode=True
           prediction_response with p_yes=0.5, p_no=0.5
    Assert: sell_vote is None
    Assert: should_sell_outcome_tokens is not called
    Assert: payload vote is None
```

#### RT3. Benchmarking mode investment tracking

**Why**: `update_investments` uses `prediction_response.vote`, not strategy_vote.
This is a latent bug (R1).

**Suggested tests**:

```
test_benchmarking_investment_tracked_under_correct_outcome:
    Setup: benchmarking_mode=True
           prediction_response with p_yes=0.7 (mech vote=0)
           strategy returns vote=1 (NO)
    Assert: investment tracked under outcome "No", not "Yes"
    NOTE: This test will FAIL with current code, proving the R1 bug.

test_benchmarking_update_selected_bet_uses_strategy_vote:
    Setup: benchmarking_mode=True, strategy returns vote=1
    Assert: _update_selected_bet records strategy_vote correctly
```

#### RT4. ChatUI migration and compat keys

**Why**: ChatUI auto-migration from old strategy names and compat key presence
are critical for operator upgrades.

**Suggested tests**:

```
test_chatui_store_migrates_kelly_criterion_no_conf:
    Setup: chatui_param_store.json with trading_strategy="kelly_criterion_no_conf"
           YAML has trading_strategy="kelly_criterion"
    Assert: _ensure_chatui_store detects mismatch and migrates to "kelly_criterion"

test_chatui_store_migrates_bet_amount_per_threshold:
    Same as above with "bet_amount_per_threshold"

test_chatui_accepts_all_available_strategies_via_http:
    Setup: POST to ChatUI with each strategy name
    Assert: "kelly_criterion" -> accepted
    Assert: "fixed_bet" -> accepted
    Assert: "kelly_criterion_no_conf" -> accepted (backward compat)
    Assert: "bet_amount_per_threshold" -> accepted (backward compat)
    Assert: "nonexistent_strategy" -> rejected

test_strategies_kwargs_has_chatui_compat_keys:
    Setup: Load strategies_kwargs from default config
    Assert: "default_max_bet_size" in strategies_kwargs
    Assert: "absolute_min_bet_size" in strategies_kwargs
    Assert: "absolute_max_bet_size" in strategies_kwargs
```

#### RT5. Config compatibility under env-override scenarios

**Why**: Operators may have `STRATEGIES_KWARGS` env vars from the old config
that include removed keys (`bet_kelly_fraction`) or miss new keys.

**Suggested tests**:

```
test_old_strategies_kwargs_with_bet_kelly_fraction:
    Setup: STRATEGIES_KWARGS={"bet_kelly_fraction": 0.5, ...old keys...}
    Assert: Strategy ignores unknown kwargs, does not crash
    Assert: Strategy uses defaults for missing new params

test_strategies_kwargs_missing_new_kelly_params:
    Setup: STRATEGIES_KWARGS={"floor_balance": 0}
    Assert: Strategy falls back to defaults for n_bets, min_edge, etc.
    Assert: No crash

test_get_bet_amount_missing_absolute_min_bet_size:
    Setup: strategies_kwargs without "absolute_min_bet_size"
    Assert: KeyError is raised (proving R3)
    NOTE: This test documents the regression from R3.
```

#### RT6. `_get_ui_trading_strategy` mapping completeness

**Why**: Three separate implementations exist (chatui handlers, trader handlers,
predictions_helper). They must all map the same strategy names consistently.

**Suggested tests**:

```
test_ui_trading_strategy_mapping_consistency:
    For each of: chatui_abci, trader_abci, predictions_helper, polymarket_predictions_helper
    Assert: "kelly_criterion" -> "risky"
    Assert: "kelly_criterion_no_conf" -> "risky"
    Assert: "fixed_bet" -> "balanced"
    Assert: "bet_amount_per_threshold" -> "balanced"
    Assert: None -> "balanced" (or None for predictions_helper)
```

#### RT7. Omen (FPMM) path end-to-end

**Why**: The framework mandates "Omen (FPMM) path remains functional." Tests
exist for the strategy in isolation but not for the full decision_receive ->
strategy -> payload path for Omen.

**Suggested tests**:

```
test_is_profitable_fpmm_end_to_end:
    Setup: is_running_on_polymarket=False
           bet with real-looking outcomeTokenAmounts and prices
           strategy configured for FPMM
    Assert: get_bet_amount called with market_type="fpmm"
    Assert: tokens_yes and tokens_no passed correctly
    Assert: bet_fee passed correctly
    Assert: orderbook args are None

test_is_profitable_fpmm_with_high_fee:
    Setup: bet.fee = large value (e.g., 10% of pool)
    Assert: Strategy still computes without crash
    Assert: Alpha = 1 - fee_fraction is positive
```

#### RT8. Polymarket (CLOB) path end-to-end

**Suggested tests**:

```
test_is_profitable_clob_with_missing_token_ids:
    Setup: bet.outcome_token_ids = None
    Assert: No crash, orderbook_asks remain None
    Assert: Strategy gracefully returns no-trade

test_is_profitable_clob_with_partial_token_ids:
    Setup: bet.outcome_token_ids = {"Yes": "token_yes", "No": None}
    Assert: Only YES orderbook fetched
    Assert: Strategy can still evaluate YES side

test_is_profitable_clob_both_orderbook_failures:
    Setup: Both _fetch_orderbook calls return None
    Assert: Strategy returns no-trade
    Assert: No crash
```

#### RT9. `rebet_allowed` is never called in current flow

**Suggested tests**:

```
test_async_act_does_not_call_rebet_allowed:
    Setup: Normal non-selling, non-benchmarking flow
    Assert: rebet_allowed is never invoked
    NOTE: This documents the intentional disconnection and will catch
    accidental reintroduction.
```

#### RT10. `fixed_bet` strategy as replacement for `bet_amount_per_threshold`

**Suggested tests**:

```
test_fixed_bet_returns_expected_profit_zero:
    Setup: Run fixed_bet strategy
    Assert: Result dict does NOT contain "expected_profit"
           or it is 0/absent
    NOTE: fixed_bet doesn't compute expected_profit, but the caller
    reads strategy_result.get("expected_profit", 0). Verify this
    doesn't break the logging at decision_receive.py:497.

test_fixed_bet_returns_g_improvement_absent:
    Setup: Run fixed_bet strategy
    Assert: strategy_result.get("g_improvement") is None/0
    NOTE: This is used at decision_receive.py:828 in tests. Verify
    the caller handles absence gracefully.
```

---

## Regression Checklist (from Framework Section C)

| Check | Status | Notes |
|---|---|---|
| Omen (FPMM) path remains functional | **Partial** | Strategy tested in isolation; no end-to-end `_is_profitable` test for FPMM with real pool values |
| Polymarket (CLOB) path remains functional | **Partial** | Orderbook fetch tested; no test for missing token_ids or dual-failure |
| `fixed_bet` replacement behaves as intended | **Pass** | 17 tests; side selection matches old `bet_amount_per_threshold` logic |
| Caller integration no separate code paths | **Pass** | `_is_profitable` is unified; no venue branching |
| ChatUI loads and validates settings | **Gap** | No test for ChatUI migration from old strategy names; compat keys missing from service YAML defaults (R3) |
| Legacy strategy names resolve | **Partial** | Enum backward compat aliases exist; `_get_ui_trading_strategy` maps correctly; no test for ChatUI HTTP POST with old names |
| Service/agent/skill config compatible | **Gap** | Service YAML `strategies_kwargs` default missing ChatUI compat keys (R3) |

---

## Summary of Recommended Additional Regression Tests

| ID | Priority | Description |
|---|---|---|
| RT1 | **Critical** | Strategy vote diverges from mech vote |
| RT2 | **High** | Selling flow unaffected by strategy changes |
| RT3 | **High** | Benchmarking investment tracking (proves R1 bug) |
| RT4 | **High** | ChatUI migration from old strategy names |
| RT5 | **High** | Config compat under env-override scenarios |
| RT6 | **Medium** | UI strategy mapping consistency across 4 implementations |
| RT7 | **Medium** | FPMM end-to-end through decision_receive |
| RT8 | **Medium** | CLOB edge cases (missing tokens, dual failure) |
| RT9 | **Medium** | Assert rebet_allowed is never called |
| RT10 | **Low** | fixed_bet missing expected_profit/g_improvement fields |

---

## Go / No-Go Assessment (Regression Only)

**Conditional Go** with the following blocking items:

1. **R3 must be fixed before merge**: Service YAML `strategies_kwargs` defaults need
   ChatUI compat keys. Without this, fresh operator deployments will crash.

2. **R1 should be fixed or explicitly accepted**: Investment tracking in benchmarking
   mode uses wrong vote. If benchmarking won't be used until a follow-up PR, this
   can be accepted with a documented risk flag. Otherwise, fix before merge.

3. **RT1 and RT2 should be added**: The core architectural change (strategy owns vote)
   needs at least one test proving the vote correctly propagates when it differs
   from the mech's prediction_response.vote.

All other items (R2, R4-R8, RT3-RT10) are recommended follow-up improvements and
do not block the merge.
