# FSM Audit Report

**Scope:** All 12 skills under `packages/valory/skills/`
**Date:** 2026-03-10
**Status:** Reviewed and fixed (except test findings)

## Critical Findings

### C3: Duplicate Dictionary Key in Transition Function — FIXED
- **File:** `packages/valory/skills/decision_maker_abci/rounds.py:366,370`
- **Issue:** `Event.INSUFFICIENT_BALANCE: RefillRequiredRound` appeared twice in `PolymarketBetPlacementRound`'s transition function entry. Python silently overwrites the first with the second. Both mapped to the same target, but this copy-paste error could mask a future bug if one is changed.
- **Fix applied:** Removed the duplicate entry, kept one with the comment.

### M3 (elevated to Critical): `set(get_name(...))` Creates Set of Characters — NOT FIXED (third-party package)
- **File:** `packages/valory/skills/mech_interact_abci/rounds.py:207`
- **Issue:** `set(get_name(SynchronizedData.mech_responses))` called `set()` on a string, producing a set of individual characters (`{'m','e','c','h','_','r','s','p','o','n'}`) instead of a set containing one string (`{"mech_responses"}`). This meant db_post_conditions validation checked against wrong keys.
- **Status:** `mech_interact_abci` is a third-party package not maintained in this repository. The fix (`{get_name(SynchronizedData.mech_responses)}`) should be applied upstream.

## High Findings

No findings.

## Medium Findings

### C2: Operator Precedence Ambiguity in Boolean Expression — FIXED
- **File:** `packages/valory/skills/decision_maker_abci/models.py:570-575`
- **Issue:** Mixed `and`/`or` without explicit parentheses. Python's precedence made this evaluate correctly, but it was fragile and hard to read.
- **Fix applied:** Added explicit parentheses: `(A and B) or (C and D)`.

## Test Findings (not fixed — handled separately)

### T3: Missing Test Files
- **File:** `packages/valory/skills/agent_performance_summary_abci/tests/` — no test directory exists at all
- **File:** `packages/valory/skills/chatui_abci/tests/` — missing `test_rounds.py` and `test_behaviours.py`
- **File:** `packages/valory/skills/tx_settlement_multiplexer_abci/tests/` — missing `test_rounds.py` and `test_behaviours.py`
- **Issue:** These skills lack round and behaviour test coverage. Without tests, correctness of `end_block()` logic, payload handling, and state transitions is unverified.

## Low Findings

### L3: Incorrect Docstrings — FIXED
- **File:** `packages/valory/skills/chatui_abci/rounds.py:20`
- **Issue:** Module docstring said `"check stop trading ABCI application"` but this is the chatui skill.
- **Fix applied:** Changed to `"chat UI ABCI application"`.
- **File:** `packages/valory/skills/chatui_abci/rounds.py:75`
- **Issue:** `FinishedChatuiLoadRound` docstring said `"check stop trading has finished"`.
- **Fix applied:** Changed to `"chat UI loading has finished"`.

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| Critical | 2     | 1 (M3 is in third-party `mech_interact_abci`, not fixed here) |
| High     | 0     | —     |
| Medium   | 1     | 1     |
| Test     | 3 (skills missing tests) | 0 (handled separately) |
| Low      | 1 (2 instances) | 2     |

## False Positives Identified During Review

- **M2: VotingRound `negative_event` same as `done_event` in chatui_abci** — Originally flagged but determined to be intentional. The transition function only maps `Event.DONE → FinishedChatuiLoadRound`, so both positive and negative votes correctly proceed to the same next state. This round loads config; both outcomes should advance.

## Notes

- **CLI tools skipped:** The `autonomy` CLI is not installed in this environment, so `autonomy analyse fsm-specs/handlers/dialogues/docstrings` could not be run. These should be run separately.
- **Library skill conventions respected:** `ROUND_TIMEOUT` defined but unused in library skills (registration_abci, reset_pause_abci, etc.) was not flagged — this is an extensibility convention.
- **False positives excluded:**
  - `reset_pause_abci/models.py` SharedState.setup() mutating class-level `event_to_timeout` — this is the standard framework pattern for configuring timeouts from parameters.
  - `termination_abci/rounds.py` runtime mutation of `transition_function` for BackgroundRound — this is the designed mechanism for wiring background apps.
  - Mutable class-level dicts in `RegistrationStartupBehaviour` — single-instance per agent, acceptable per framework design.
- **Terminal states:** `ImpossibleRound`, `ServiceEvictedRound`, and `FailedMultiplexerRound` are unmapped in the composition chain. These appear to be intentional true terminal states (the agent service stops).
