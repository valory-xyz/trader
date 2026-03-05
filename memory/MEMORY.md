# Trader Repo Memory

## Project Overview
ABCI-based multi-agent trading framework using Valory's Open Autonomy stack.
Current branch: `chore/polystrat-tests`

## Key Architecture
- `packages/valory/skills/decision_maker_abci/` - Decision making skill (bet placement, approvals, redemption)
- `packages/valory/skills/market_manager_abci/` - Market management skill (fetch markets, update bets)
- `packages/valory/connections/polymarket_client/` - Polymarket CLOB client connection
- `packages/valory/skills/agent_performance_summary_abci/` - Performance tracking

## Testing Patterns
- Tests bypass `__init__` of AEA connection classes using `object.__new__(ClassName)`
- AEA `Component` stores config in `._configuration` (not `.configuration` which is read-only property)
- Read-only properties (`most_voted_payload_values`, `most_voted_payload`, `payload_values_count`) must be mocked with `PropertyMock`:
  ```python
  with patch.object(type(round_), "property_name", new_callable=PropertyMock, return_value=val):
  ```
- Round tests patch parent `end_block` via full module path, e.g.:
  `"packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"`
- AEA `SrrDialogues.create()` returns `(message, dialogue)` NOT `(dialogue, message)`

## Polymarket Test Files Created
- `packages/valory/connections/polymarket_client/tests/__init__.py`
- `packages/valory/connections/polymarket_client/tests/test_connection.py` - 120 tests, 99% coverage
- `packages/valory/skills/decision_maker_abci/tests/test_polymarket_states.py` - 46 tests, 100% coverage
- `packages/valory/skills/decision_maker_abci/tests/test_payloads.py` - Updated to include Polymarket payloads

## Bug Found
**`connection.py` line 916-917**: Dead/unreachable code.
```python
pages_fetched = (len(all_trades) + limit - 1) // limit if all_trades else 0
if pages_fetched == 0 and len(all_trades) > 0:  # NEVER TRUE
    pages_fetched = 1
```
When `all_trades` is non-empty, `pages_fetched` is always ≥ 1. The branch at line 917 can never execute.

## PolyApiException Constructor
`PolyApiException(resp=None, error_msg=None)` — no `method` keyword arg (despite how some code references it).
