# FSM Audit Report

**Scope:** All skills under `packages/valory/skills/`
**Dates:** 2026-03-10, 2026-03-16 (consolidated)
**Status:** Most findings fixed. Open items: M3 (third-party), H1, M1, T1.

---

## Critical Findings

### C1: Duplicate Dictionary Key in Transition Function — FIXED
- **File:** `packages/valory/skills/decision_maker_abci/rounds.py:366,370`
- **Issue:** `Event.INSUFFICIENT_BALANCE: RefillRequiredRound` appeared twice in `PolymarketBetPlacementRound`'s transition function. Python silently overwrites the first with the second. Both mapped to the same target, but this copy-paste error could mask a future bug if one is changed.
- **Fix applied:** Removed the duplicate entry, kept one with the comment.

### C2: `set(get_name(...))` Creates Set of Characters — NOT FIXED (third-party)
- **File:** `packages/valory/skills/mech_interact_abci/rounds.py:207`
- **Issue:** `set(get_name(SynchronizedData.mech_responses))` calls `set()` on a string, producing a set of individual characters instead of a single-element set. This means `db_post_conditions` validation checks against wrong keys.
- **Status:** `mech_interact_abci` is a third-party package. The fix (`{get_name(SynchronizedData.mech_responses)}`) should be applied upstream.

## High Findings

### H1: File Pointer at EOF in Error Log — OPEN
- **File:** `packages/valory/skills/chatui_abci/models.py:91-98`
- **Issue:** After `json.load(store_file)` fails with `JSONDecodeError`, `store_file.read()` is called in the error log. But `json.load()` already consumed the file — the pointer is at EOF, so `store_file.read()` returns `""`. The error message always shows an empty string.
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

### M1: Unused Event Enum Members in decision_maker_abci — OPEN
- **File:** `packages/valory/skills/decision_maker_abci/states/base.py:77,83,87`
- **Issue:** Three events defined in the `Event` enum are never referenced in any transition function or `end_block()` return within this skill:
  - `NO_SUBSCRIPTION = "no_subscription"` (line 77)
  - `POLYMARKET_FETCH_MARKETS = "polymarket_fetch_markets"` (line 83) — used in `market_manager_abci` but dead in this skill's own enum
  - `SKIP = "skip"` (line 87)
- **Fix:** Remove these unused enum members, or document them if reserved for future use.

### M2: Operator Precedence Ambiguity in Boolean Expression — FIXED
- **File:** `packages/valory/skills/decision_maker_abci/models.py:570-575`
- **Issue:** Mixed `and`/`or` without explicit parentheses. Python's precedence made this evaluate correctly, but it was fragile and hard to read.
- **Fix applied:** Added explicit parentheses: `(A and B) or (C and D)`.

## Test Findings

### T1: Incomplete Round Event Testing for CheckStopTradingRound — OPEN
- **File:** `packages/valory/skills/check_stop_trading_abci/tests/test_rounds.py`
- **Issue:** Parametrized test covers `SKIP_TRADING`, `REVIEW_BETS`, and `NO_MAJORITY`, but `Event.DONE` (which transitions to `FinishedCheckStopTradingRound`) is not tested.
- **Fix:** Add a test case for the `DONE` event path.

### T2: Missing Test Files — FIXED
- `packages/valory/skills/agent_performance_summary_abci/tests/` — comprehensive tests added
- `packages/valory/skills/chatui_abci/tests/` — `test_rounds.py` and `test_behaviours.py` added
- `packages/valory/skills/tx_settlement_multiplexer_abci/tests/` — `test_rounds.py` and `test_behaviours.py` added

## Low Findings

### L1: Incorrect Docstrings in chatui_abci — FIXED
- **File:** `packages/valory/skills/chatui_abci/rounds.py:20,54,75`
- **Issue:** Module docstring, Event docstring, and `FinishedChatuiLoadRound` docstring all said "check stop trading" instead of "chat UI".
- **Fix applied:** All three corrected.

## Summary

| Severity | Total | Fixed | Open |
|----------|-------|-------|------|
| Critical | 2     | 1     | 1 (third-party `mech_interact_abci`) |
| High     | 1     | 0     | 1    |
| Medium   | 2     | 1     | 1    |
| Test     | 2     | 1     | 1    |
| Low      | 1     | 1     | 0    |

## False Positives Identified During Review

- **VotingRound `negative_event` same as `done_event` in chatui_abci** — Intentional. The transition function only maps `Event.DONE → FinishedChatuiLoadRound`, so both positive and negative votes correctly proceed to the same next state. This round loads config; both outcomes should advance.

## Notes

- **CLI tools skipped:** The `autonomy` CLI was not installed in the audit environment, so `autonomy analyse fsm-specs/handlers/dialogues/docstrings` could not be run. These should be run separately.
- **Library skill conventions respected:** `ROUND_TIMEOUT` defined but unused in library skills (registration_abci, reset_pause_abci, etc.) was not flagged — this is an extensibility convention.
- **False positives excluded:**
  - `reset_pause_abci/models.py` SharedState.setup() mutating class-level `event_to_timeout` — standard framework pattern.
  - `termination_abci/rounds.py` runtime mutation of `transition_function` for BackgroundRound — designed mechanism for wiring background apps.
  - Mutable class-level dicts in `RegistrationStartupBehaviour` — single-instance per agent, acceptable per framework design.
- **Terminal states:** `ImpossibleRound`, `ServiceEvictedRound`, and `FailedMultiplexerRound` are unmapped in the composition chain. These are intentional true terminal states (the agent service stops).
