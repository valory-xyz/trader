# PREDICT-827: Omenstrat shows "Swap POL to USDC.E"

## Problem

When Omenstrat runs, the activity UI shows "Swapping POL to USDC for placing mech requests" — a Polymarket-specific label that confuses Omenstrat users. The round itself executes but no-ops (skips swap) when `is_running_on_polymarket` is False.

## Approach

Override Polymarket-specific round labels with generic text in the HTTP handler's `setup()`, conditioned on `is_running_on_polymarket`.

## Changes

### 1. `packages/valory/skills/decision_maker_abci/handlers.py`

In `setup()`, after line 164 (`self.rounds_info = load_rounds_info_with_transitions()`), add:

```python
if not self.context.params.is_running_on_polymarket:
    polymarket_label_overrides = {
        "polymarket_swap_usdc_round": {
            "name": "Preparing for next step",
            "description": "Checks and prepares before continuing.",
        },
        "polymarket_bet_placement_round": {
            "name": "Opening a trade",
            "description": "Attempts to open a trade on a prediction market.",
        },
        "polymarket_set_approval_round": {
            "name": "Setting approval",
            "description": "Attempts to set approval on a prediction market.",
        },
        "polymarket_post_set_approval_round": {
            "name": "Post setting approval",
            "description": "Attempts to finalize the approval setting on a prediction market.",
        },
        "polymarket_redeem_round": {
            "name": "Redeeming winnings",
            "description": "Redeems winnings from resolved trades.",
        },
        "polymarket_fetch_market_round": {
            "name": "Fetching markets",
            "description": "Fetches available prediction markets.",
        },
    }
    for round_key, overrides in polymarket_label_overrides.items():
        if round_key in self.rounds_info:
            self.rounds_info[round_key].update(overrides)
```

### 2. Update hashes

After modifying handler, run `autonomy packages lock` to update content-addressed hashes.

## Testing

- Add a unit test in the handler tests that verifies:
  - When `is_running_on_polymarket=False`, the `polymarket_swap_usdc_round` label does NOT contain "POL" or "Polymarket"
  - When `is_running_on_polymarket=True`, the original labels are preserved

## Notes

- No FSM changes needed — the rounds still exist and execute (as no-ops), we just relabel them
- Only `rounds_info.py` labels are affected; round class docstrings are untouched
- The override dict is checked with `if round_key in self.rounds_info` to avoid KeyError if rounds are added/removed in the future
