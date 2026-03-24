# PREDICT-691: Fix agent crash from sleep overflow in performance summary

**Date:** 2026-03-23
**Linear:** PREDICT-691
**Status:** Not started
**Branch:** (TBD)

---

## Problem

Agent crashes with `OverflowError: date value out of range` after running for a long time.

**Root cause:** `suggested_sleep_time` = `backoff_factor ** retries_attempted` grows exponentially without bound. The `retries_attempted` counter on the `ApiSpecs` subgraph object persists across FSM cycles and only resets on success. If a subgraph stays down for many cycles, `retries_attempted` grows until `2^n` seconds overflows `datetime.timedelta`.

**Crash path:**
```
behaviours.py:1188 _build_profit_over_time_data
  → behaviours.py:1236 _perform_initial_backfill
    → requests.py:462 _fetch_daily_profit_statistics
      → requests.py:191 _fetch_from_subgraph
        → requests.py:160 _handle_response → self.sleep(sleep_time)
          → behaviour_utils.py:263 datetime.timedelta(0, seconds) → OverflowError
```

**Threshold:** ~46 failed retries with default `backoff_factor=2.0` → `2^46 ≈ 7e13` seconds → overflow.

---

## Affected call sites

| # | File | Line | Package | Owner |
|---|------|------|---------|-------|
| 1 | `packages/valory/skills/agent_performance_summary_abci/graph_tooling/requests.py` | 159-160 | dev | **trader** |
| 2 | `packages/valory/skills/market_manager_abci/graph_tooling/requests.py` | 163-164 | dev | **trader** |
| 3 | `packages/valory/skills/abstract_round_abci/common.py` | 147-149 | third_party | **open-autonomy** |

Sites 1 and 2 are in-scope for the trader hotfix. Site 3 requires a separate fix in open-autonomy (per plan agreed in Linear comments).

---

## Fix

Three changes at both dev-owned call sites: clamp sleep time, skip sleep after exhaustion, and add missing `clean_up()`.

### Change 1: Clamp sleep time

**File 1:** `packages/valory/skills/agent_performance_summary_abci/graph_tooling/requests.py`

```python
# Before (line 159-160):
sleep_time = subgraph.retries_info.suggested_sleep_time
yield from self.sleep(sleep_time)

# After:
sleep_time = min(subgraph.retries_info.suggested_sleep_time, _MAX_SLEEP_TIME)
yield from self.sleep(sleep_time)
```

**File 2:** `packages/valory/skills/market_manager_abci/graph_tooling/requests.py`

```python
# Before (line 163-164):
sleep_time = subgraph.retries_info.suggested_sleep_time
yield from self.sleep(sleep_time)

# After:
sleep_time = min(subgraph.retries_info.suggested_sleep_time, _MAX_SLEEP_TIME)
yield from self.sleep(sleep_time)
```

**Constant** (add to both files):
```python
_MAX_SLEEP_TIME = 300.0  # 5 minutes; prevents OverflowError in timedelta
```

#### Why 300s

- Large enough to preserve backoff benefit (default max at 5 retries is only 32s)
- Small enough to never overflow `datetime.timedelta`
- Aligns with typical round timeout values in the framework

### Change 2: Skip sleep after retries exhausted

In both `_handle_response` methods, the sleep fires unconditionally even after `is_retries_exceeded()` sets `FetchStatus.FAIL`. This wastes up to 300s per call when the subgraph has already given up.

**File 1:** `packages/valory/skills/agent_performance_summary_abci/graph_tooling/requests.py`

```python
# Before (lines 155-160):
            if subgraph.is_retries_exceeded():
                self._fetch_status = FetchStatus.FAIL

            if sleep_on_fail:
                sleep_time = subgraph.retries_info.suggested_sleep_time
                yield from self.sleep(sleep_time)

# After:
            if subgraph.is_retries_exceeded():
                self._fetch_status = FetchStatus.FAIL
            elif sleep_on_fail:
                sleep_time = min(subgraph.retries_info.suggested_sleep_time, _MAX_SLEEP_TIME)
                yield from self.sleep(sleep_time)
```

**File 2:** `packages/valory/skills/market_manager_abci/graph_tooling/requests.py`

```python
# Before (lines 159-164):
            if subgraph.is_retries_exceeded():
                self._fetch_status = FetchStatus.FAIL

            if sleep_on_fail:
                sleep_time = subgraph.retries_info.suggested_sleep_time
                yield from self.sleep(sleep_time)

# After:
            if subgraph.is_retries_exceeded():
                self._fetch_status = FetchStatus.FAIL
            elif sleep_on_fail:
                sleep_time = min(subgraph.retries_info.suggested_sleep_time, _MAX_SLEEP_TIME)
                yield from self.sleep(sleep_time)
```

### Change 3: Add `clean_up()` to `agent_performance_summary_abci`

`market_manager_abci` already resets retry counters in `clean_up()` (line 429). `agent_performance_summary_abci` has **no** `clean_up()`, so `retries_attempted` accumulates unbounded across FSM cycles — the agent will always sleep the full capped 300s after enough failures, even if the subgraph recovers.

**File:** `packages/valory/skills/agent_performance_summary_abci/graph_tooling/requests.py`

Add to `APTQueryingBehaviour`:

```python
def clean_up(self) -> None:
    """Clean up the resources."""
    subgraph_names = (
        "polygon_mech_subgraph",
        "olas_mech_subgraph",
        "olas_agents_subgraph",
        "polymarket_agents_subgraph",
        "open_markets_subgraph",
        "polymarket_bets_subgraph",
        "gnosis_staking_subgraph",
        "polygon_staking_subgraph",
    )
    for name in subgraph_names:
        subgraph_specs = getattr(self.context, name, None)
        if subgraph_specs is not None:
            subgraph_specs.reset_retries()
```

---

## Tests

- Add a test to each file that verifies `sleep_time` is clamped when `suggested_sleep_time` exceeds `_MAX_SLEEP_TIME`.
- Add a test verifying no sleep occurs when `is_retries_exceeded()` returns True.
- Add a test for `APTQueryingBehaviour.clean_up()` verifying all subgraph retry counters are reset.

---

## Known risks

- **`mech_interact_abci/graph_tooling/requests.py:109-111`** has the same vulnerable pattern (`yield from self.sleep(sleep_time)` with no cap). This is a **third-party** package — fix must go upstream. Same overflow can occur there once retries accumulate.
- **`abstract_round_abci/common.py:147-149`** (third-party) also lacks a cap. Already tracked in Linear for an open-autonomy fix.
- **Round timeout vs cap**: If round timeouts are close to 300s, a capped sleep could consume most of the round budget. In practice default backoff at 5 retries is only 32s, so this only matters if retries accumulate past the cap — which Change 3 (clean_up) mitigates.
- Once upstream OA and mech_interact fixes land and trader bumps those deps, the trader-side clamps become redundant (but harmless).

---

## Follow-up (not in scope)

- **open-autonomy proper fix:** Clamp inside `behaviour_utils.py:sleep()` itself and/or cap `suggested_sleep_time` in `RetriesInfo`. Tracked separately per Linear comment thread.
- **mech_interact_abci fix:** Same clamp + skip-after-exhaustion needed upstream.
