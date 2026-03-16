# FSM Audit Report

**Scope:** All 7 skills in `packages/valory/skills/`:
- `decision_maker_abci`
- `market_manager_abci`
- `staking_abci`
- `check_stop_trading_abci`
- `tx_settlement_multiplexer_abci`
- `agent_performance_summary_abci`
- `chatui_abci`
- `trader_abci` (composition layer)

**Date:** 2026-03-16

**Note:** The `autonomy analyse` CLI tools could not be run (`autonomy` not installed in the current virtualenv). All checks below are manual.

## Critical Findings

### C1: Duplicate Dictionary Key in Transition Function
- **File:** `packages/valory/skills/decision_maker_abci/rounds.py:366,370`
- **Issue:** `Event.INSUFFICIENT_BALANCE` appears twice as a key in `PolymarketBetPlacementRound`'s transition dict. Python silently uses the last value — both map to the same target (`RefillRequiredRound`), so behaviour is accidentally correct, but the duplicate is a latent bug. If either mapping is later changed independently, the first will be silently overwritten.
- **Code:**
  ```python
  PolymarketBetPlacementRound: {
      ...
      Event.INSUFFICIENT_BALANCE: RefillRequiredRound,   # line 366
      Event.MOCK_TX: RedeemRouterRound,
      # degenerate round on purpose, owner must refill the safe
      Event.INSUFFICIENT_BALANCE: RefillRequiredRound,   # line 370 — DUPLICATE
      ...
  }
  ```
- **Fix:** Remove the duplicate entry at line 370 (and its comment at line 369).

## High Findings

### H3: File Pointer at EOF in Error Log
- **File:** `packages/valory/skills/chatui_abci/models.py:98`
- **Issue:** After `json.load(store_file)` fails with `JSONDecodeError`, `store_file.read()` is called in the error log message. But `json.load()` already consumed the file — the pointer is at EOF, so `store_file.read()` returns `""`. The error message will be: `" is not a valid JSON file."` — losing the actual file content.
- **Code:**
  ```python
  with open(chatui_store_path, FILE_READ_MODE) as store_file:
      try:
          return json.load(store_file)
      except json.JSONDecodeError:
          self.context.logger.error(
              f"{store_file.read()} is not a valid JSON file. Resetting the store."
          )
  ```
- **Fix:**
  ```python
  with open(chatui_store_path, FILE_READ_MODE) as store_file:
      raw = store_file.read()
      try:
          return json.loads(raw)
      except json.JSONDecodeError:
          self.context.logger.error(
              f"{raw!r} is not valid JSON. Resetting the store."
          )
  ```

## Medium Findings

### M2: Unused Event Enum Members in decision_maker_abci
- **File:** `packages/valory/skills/decision_maker_abci/states/base.py:77,83,87`
- **Issue:** Three events defined in the `Event` enum are never referenced in any transition function or `end_block()` return within this skill:
  - `NO_SUBSCRIPTION = "no_subscription"` (line 77)
  - `POLYMARKET_FETCH_MARKETS = "polymarket_fetch_markets"` (line 83) — used in `market_manager_abci` but dead in this skill's own enum
  - `SKIP = "skip"` (line 87)
- **Fix:** Remove these unused enum members, or document them if reserved for future use.

### M-style: Operator Precedence Clarity in `is_winning`
- **File:** `packages/valory/skills/decision_maker_abci/models.py:572-577`
- **Issue:** The boolean expression mixes `and`/`or` without explicit parentheses. Due to Python precedence (`and` > `or`), the evaluation is `(YES and p_yes>0.5) or (NO and p_yes<0.5)` — which is likely correct. But the multi-line formatting makes it appear as if `or` might be grouped differently.
- **Code:**
  ```python
  return (
      self.answer == YES
      and self.p_yes > 0.5
      or self.answer == NO
      and self.p_yes < 0.5
  )
  ```
- **Fix:** Add explicit parentheses for clarity:
  ```python
  return (
      (self.answer == YES and self.p_yes > 0.5)
      or (self.answer == NO and self.p_yes < 0.5)
  )
  ```

## Test Findings

### T5: Incomplete Round Event Testing for CheckStopTradingRound
- **File:** `packages/valory/skills/check_stop_trading_abci/tests/test_rounds.py:228-290`
- **Issue:** The parametrized test covers `SKIP_TRADING`, `REVIEW_BETS`, and `NO_MAJORITY`, but `Event.DONE` (which transitions to `FinishedCheckStopTradingRound`) is not tested.
- **Fix:** Add a test case for the `DONE` event path.

## Low Findings

No findings.

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1     |
| High     | 1     |
| Medium   | 2     |
| Test     | 1     |
| Low      | 0     |

## Notes

- **CLI tools not available:** `autonomy analyse fsm-specs`, `handlers`, `dialogues`, and `docstrings` could not be run because `autonomy` is not installed in the current virtualenv. Running these is recommended as a follow-up.
- **False positive exclusions:** `ServiceEvictedRound.end_block()` returning `None` is correct for a `DegenerateRound` (final state, never transitions). The `NO_MAJORITY`/`REFILL_REQUIRED` events in `tx_settlement_multiplexer_abci` are not dead timeouts — they are consensus events, and `ROUND_TIMEOUT` covers the hang scenario. Mutable class-level attributes in behaviours were not flagged per the false positive guidance.
- **The C1 duplicate key (Critical)** happens to map to the same target today, so there is no runtime impact *currently*, but it is a maintenance hazard.
