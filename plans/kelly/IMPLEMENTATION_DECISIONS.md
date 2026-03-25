# Kelly Implementation Decisions Log

Decisions made during implementation of the unified Kelly criterion strategy
(branch: `jenslee/predict-836-kelly-implementation`).

---

## Commits

1. `9ecbc892` — Add kelly_criterion and fixed_bet strategy packages
2. `8e40e5c9` — Add FETCH_ORDER_BOOK to polymarket connection
3. `d67f0a28` — Integrate Kelly strategy into decision_receive
4. `904b12e0` — Update strategy references for kelly_criterion and fixed_bet
5. `877b53ff` — Update YAML configs for new Kelly strategy
6. `65ce7193` — Delete old strategy packages and update references

---

## Key Decisions

### No TDD for strategy files

Strategy files have a well-defined algorithm from the spec. Implementation
first, then tests. TDD applied to integration tests (decision_receive).

### Strategy owns profitability and side selection

`_is_profitable()` no longer has Omen/Poly branching. The strategy decides:
- Whether to bet (`bet_amount > 0`)
- Which side (`vote`: 0=YES, 1=NO)
- Expected profit

The caller just checks `bet_amount > 0` and `vote is not None`.

### No runtime name normalization

`file_hash_to_strategies` has no env override — it always comes from YAMLs
we control. So old strategy names (`kelly_criterion_no_conf`,
`bet_amount_per_threshold`) can never enter the runtime path. No normalization
needed in `SharedState.setup()` or `get_bet_amount()`.

### bet_amount_per_threshold removed from strategies_kwargs

Since old strategy executables can't be downloaded (we control
`file_hash_to_strategies` in YAMLs, no env override), there's no scenario
where old code runs and needs the `bet_amount_per_threshold` dict. Removed
from all YAMLs.

### Backward compat aliases kept in enums

`TradingStrategy` enums keep `KELLY_CRITERION_NO_CONF` and
`BET_AMOUNT_PER_THRESHOLD` because:
- `chatui_param_store.json` on operator machines may have these values
- Historical bet records in subgraph reference them
- `_get_ui_trading_strategy()` maps both old and new names

ChatUI auto-migrates: when YAML default changes from old to new name,
`initial_trading_strategy != trading_strategy_yaml` triggers a reset.

### Deleted unused strategies

Removed `mike_strat` and `w1kke/always_blue` alongside the old strategies.
Neither was referenced by any production code.

### removed `using_kelly` property

No per-strategy branching in the caller anymore. All strategies have the same
contract (`bet_amount` + `vote`).

### removed `bet_kelly_fraction`

Old Kelly used this as a post-hoc multiplier. New Kelly uses `n_bets` for
bankroll depth control instead.

### removed SLIPPAGE, DEFAULT_MECH_COSTS, remove_fraction_wei from decision_receive

The old Omen/Poly profitability checks used these. Now the strategy handles
all execution modeling internally.

### rebet_allowed not called

Rebetting is not currently supported. The plan notes this explicitly.
When re-enabled, `rebet_allowed()` must be updated to work without
`PredictionResponse.vote`.

### Benchmarking mode preserved

The benchmarking path in `_is_profitable()` still works — it uses
`strategy_vote` instead of `prediction_response.vote` for
`_update_liquidity_info()`.

### ChatUI prompt updated

Strategy descriptions rewritten to be user-friendly while reflecting new
behavior (Kelly evaluates both sides, uses real market conditions).

### Removed bet_threshold

`bet_threshold` was used by the old `_is_profitable()` to set a minimum
viable profit. The new strategy handles this internally via `min_edge` and
the log-utility objective (no-trade is always admissible). Removed from
models.py and all YAMLs.

### Removed SLIPPAGE and DEFAULT_MECH_COSTS

Dead constants in `decision_receive.py` — only used by the old Omen/Poly
profitability checks which are now replaced by strategy-internal logic.

### Deleted mike_strat and always_blue

Unused strategies with no references from production code.

---

## Deviations from Plan

### Skipped: runtime name normalization (plan 3.3.3)

Plan called for mapping `kelly_criterion_no_conf` → `kelly_criterion` in
`SharedState.setup()` and `get_bet_amount()`. Skipped because
`file_hash_to_strategies` has no env override — old names can never enter
the runtime path. YAMLs we control always have the correct names.

Instead, legacy names were removed from the ChatUI `TradingStrategy` enum
so the HTTP API rejects them. The auto-migration in `_ensure_chatui_store()`
resets old names in `chatui_param_store.json` on startup when the YAML
default changes. Handler display mappings keep old name string literals
for historical data. The `predictions_helper.py` enum (separate from
chatui) keeps old names for subgraph historical data.

### Deferred: PredictionResponse.vote/.win_probability removal (plan 3.8)

Plan called for deleting these properties and updating all consumers.
Deferred because the selling flow (`should_sell_outcome_tokens`) still
uses `prediction_response.vote`. Inline `int(p_no > p_yes)` is used in
`async_act` for the selling path instead.

### Changed: bet_amount_per_threshold removed from strategies_kwargs (plan 3.5.1)

Plan said to keep it for migration. Removed because old strategy
executables can't be downloaded — `file_hash_to_strategies` has no env
override, so it always comes from YAMLs we control.

### Changed: _update_with_values_from_chatui backward compat removed

Plan section 3.3.3 had code to propagate `fixed_bet_size` into
`bet_amount_per_threshold` dict. Removed since the dict no longer exists
in `strategies_kwargs`.

### Added: deleted mike_strat, always_blue, jhehemann

Not in original plan. Removed unused third-party strategies that had no
references from production code.

### Added: removed bet_threshold

Not explicitly in plan. Dead after `_is_profitable` rewrite — the strategy
handles minimum viable profit internally via `min_edge` and log-utility.

## Completed

- [x] `autonomy packages lock` — hashes updated
- [x] Full test suite — 3291 passed
- [x] Linting — black, isort, flake8, mypy, pylint, darglint all pass
- [x] `tox.ini` updated for new strategy test paths
- [x] `_calc_binary_shares` and `_get_bet_sample_info` removed (dead code)
- [x] PR #886 opened targeting parent branch (PR #882)
- [x] `fee_per_trade` changed to wei for consistency with all other kwargs
- [x] Test files flattened (no subdirectory) to avoid IPFS handler bug
- [x] Coverage improved to 99.98% (pragmas on unsupported benchmarking paths)
- [x] Audit finding 1 fixed: added missing ChatUI compat keys to base skill YAMLs
- [x] Audit finding 2 fixed: removed legacy names from ChatUI enum, added migration tests
- [x] Audit R1 fixed: `update_investments()` now uses `strategy_vote` instead of `prediction_response.vote`
- [x] Audit R2 fixed: `rebet_allowed()` restored in `_is_profitable()`, uses `strategy_vote` for side comparison
- [x] Added `strategy_vote` field to `Bet` dataclass (backward compat with old JSON)
- [x] `min_order_size` extracted from CLOB orderbook response
- [x] Selling flow commented as unsupported, needs updates when enabled
- [x] Verified: bet placement and redeem use `synchronized_data.vote` (correct — comes from strategy)

## Remaining Work

- PredictionResponse.vote and .win_probability kept as fallback for old
  stored bets without strategy_vote and for unsupported selling flow
- `_compute_new_tokens_distribution` kept — still used by benchmarking
- Regression tests RT1 (strategy vote diverges from mech) and RT2
  (selling flow unaffected) recommended by audit — not yet added
- `_compute_new_tokens_distribution` kept — still used by
  `_calculate_new_liquidity` (benchmarking path)
- `min_order_shares` not yet venue-provided (audit finding 3 — non-blocking)
- `rebet_allowed` not called (audit finding 4 — intentional, not currently supported)
