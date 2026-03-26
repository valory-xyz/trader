# Rollback Branch: v0.32.0 + Forward-Compatible Patches

## Context

We're deploying the new Kelly strategy changes (PRs #882 + #889) but need a rollback branch that can handle operator state left behind by the new code. Specifically, after the new code runs:

- `chatui_param_store.json` may contain `"kelly_criterion"` or `"fixed_bet"` as the trading strategy (old code only knows `"kelly_criterion_no_conf"` / `"bet_amount_per_threshold"`)
- `multi_bets.json` stores `"kelly_criterion"` or `"fixed_bet"` in `bet.strategy` field
- Position details API returns `null` for strategy on bets placed by new code

The rollback branch starts from tag `v0.32.0` and applies 3 surgical patches.

---

## Patch 1: Reverse migration in `_ensure_chatui_store()`

**File:** `packages/valory/skills/chatui_abci/models.py` (line ~114, after `current_store = self._get_current_json_store()`)

**What:** Add a strategy name reverse-migration block before the existing logic runs. Map new names back to old:
- `"kelly_criterion"` -> `"kelly_criterion_no_conf"`
- `"fixed_bet"` -> `"bet_amount_per_threshold"`

**Where exactly:** After line 114 (`current_store = self._get_current_json_store()`) and before line 119 (`if "allowed_tools" not in current_store:`), insert:

```python
# Reverse-migrate strategy names written by newer Kelly code.
_STRATEGY_REVERSE_MAP = {
    "kelly_criterion": "kelly_criterion_no_conf",
    "fixed_bet": "bet_amount_per_threshold",
}
ts = current_store.get("trading_strategy")
if ts in _STRATEGY_REVERSE_MAP:
    current_store["trading_strategy"] = _STRATEGY_REVERSE_MAP[ts]
its = current_store.get("initial_trading_strategy")
if its in _STRATEGY_REVERSE_MAP:
    current_store["initial_trading_strategy"] = _STRATEGY_REVERSE_MAP[its]
```

This runs before `ChatuiConfig(**current_store)` is constructed, so the rest of the function sees only old names.

---

## Patch 2: Omen position details strategy mapping

**File:** `packages/valory/skills/agent_performance_summary_abci/graph_tooling/predictions_helper.py`

**a) Add new names to `TradingStrategy` enum (line ~63):**
```python
class TradingStrategy(enum.Enum):
    """TradingStrategy"""

    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
    KELLY_CRITERION = "kelly_criterion"
    FIXED_BET = "fixed_bet"
```

**b) Update `_get_ui_trading_strategy()` (line ~824):**
```python
def _get_ui_trading_strategy(self, selected_value: Optional[str]) -> Optional[str]:
    """Get the UI trading strategy."""
    if selected_value is None:
        return None

    strategy_map = {
        TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value: TradingStrategyUI.BALANCED.value,
        TradingStrategy.KELLY_CRITERION_NO_CONF.value: TradingStrategyUI.RISKY.value,
        TradingStrategy.FIXED_BET.value: TradingStrategyUI.BALANCED.value,
        TradingStrategy.KELLY_CRITERION.value: TradingStrategyUI.RISKY.value,
    }
    return strategy_map.get(selected_value)
```

---

## Patch 3: Polymarket position details strategy mapping

**File:** `packages/valory/skills/agent_performance_summary_abci/graph_tooling/polymarket_predictions_helper.py`

**Update `_get_ui_trading_strategy()` (line ~640):**
```python
def _get_ui_trading_strategy(self, strategy: Optional[str]) -> Optional[str]:
    """Get the UI trading strategy representation."""
    if not strategy:
        return None

    strategy_map = {
        TradingStrategy.KELLY_CRITERION_NO_CONF.value: TradingStrategyUI.RISKY.value,
        TradingStrategy.BET_AMOUNT_PER_THRESHOLD.value: TradingStrategyUI.BALANCED.value,
        TradingStrategy.KELLY_CRITERION.value: TradingStrategyUI.RISKY.value,
        TradingStrategy.FIXED_BET.value: TradingStrategyUI.BALANCED.value,
    }
    return strategy_map.get(strategy)
```

This file imports `TradingStrategy` and `TradingStrategyUI` from `predictions_helper.py`, so the new enum members from Patch 2a are already available.

---

## Steps

1. Create branch `rollback/v0.32.0-kelly-compat` from tag `v0.32.0`
2. Apply Patch 1 (chatui reverse migration)
3. Apply Patch 2 (Omen predictions_helper enum + mapping)
4. Apply Patch 3 (Polymarket predictions_helper mapping)
5. Update package hashes with `autonomy packages lock`

---

## Verification

1. **Unit test the reverse migration:** Create a `chatui_param_store.json` with `"trading_strategy": "kelly_criterion"` and verify `_ensure_chatui_store()` normalizes it to `"kelly_criterion_no_conf"`
2. **Unit test position details mapping:** Call `_get_ui_trading_strategy("kelly_criterion")` -> `"risky"`, `_get_ui_trading_strategy("fixed_bet")` -> `"balanced"`
3. **Regression:** Existing tests should still pass -- old names unchanged
