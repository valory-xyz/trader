# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The **Trader** repo hosts the Olas prediction-market agents. A single agent package (`valory/trader`) is shipped as two services:

| Service | Stack name | Chain | Venue |
|---|---|---|---|
| `valory/trader_pearl` | **Omenstrat** | Gnosis | [Omen](https://aiomen.eth.limo/) |
| `valory/polymarket_trader` | **Polystrat** | Polygon | [Polymarket](https://polymarket.com/) (CLOB v2) |

Both run as **single-agent (sovereign) deployments** distributed via Pearl. The agent queries an AI Mech for probability estimates, evaluates profitability, and executes on-chain via a Safe multisig. Built on [Open Autonomy](https://stack.olas.network/) (ABCI skills, FSMs, content-addressed packages); Tendermint is framework plumbing, not the deployment shape.

When working locally with `make run-agent` / `aea-helpers run-agent`, the agent-level [`aea-config.yaml`](./packages/valory/agents/trader/aea-config.yaml) defaults are **Omen-flavored** — service-level `polymarket_trader/service.yaml` overrides only apply under `autonomy deploy`. Local Polystrat dev requires explicit overrides (`IS_RUNNING_ON_POLYMARKET=true`, `MECH_CHAIN_ID=polygon`, `DEFAULT_CHAIN_ID=polygon`, pUSD-scaled `STRATEGIES_KWARGS`, the Polymarket `TOOLS_ACCURACY_HASH`, and the chain-specific market-filter flags). See `README.md` for the full set.

## Tech Stack

- **Framework**: Open Autonomy
- **Package management**: `uv` (versions pinned in `pyproject.toml` — check there for the current Python range and dependencies; do not duplicate them here)
- **Task running**: `Makefile` + `tox`
- **Lint / format**: `tomte` (wraps black, isort, flake8, mypy, pylint, darglint, bandit)
- **Tests**: `pytest` + `hypothesis`

## Common Commands

### Testing
```bash
# Run all skill tests (pick the env that matches your interpreter; 3.10–3.14 supported)
uv run tox -e py3.10-linux     # or py3.11/3.12/3.13/3.14-linux, *-darwin, etc.

# Run a single skill's tests
uv run pytest packages/valory/skills/<skill_name>/tests/ -v

# Run a specific test
uv run pytest packages/valory/skills/<skill_name>/tests/test_behaviours.py::TestClassName::test_method -v
```

### Linting & Formatting
```bash
make format              # Auto-format (black + isort via tomte)
make code-checks         # All linting: black, isort, flake8, mypy, pylint, darglint
make security            # bandit + safety + gitleaks
make common-checks-1     # copyright, dependencies, linting
make common-checks-2     # hash check, package check, ABCI checks
make all-checks          # Everything
make ci-linter-checks    # CI linter checks (the full CI lint suite)
```

### Code Generation & Hashes
```bash
make generators          # Update hashes, copyright headers, ABCI docstrings
make sync-packages       # Sync package versions across the repo
# Update FSM specs for a specific skill
autonomy analyse fsm-specs --update --app-class <AppClass> --package packages/valory/skills/<skill_name>
```

### Running
```bash
# Local single-agent dev loop (wraps `uv run aea-helpers run-agent --name valory/trader --connection-key`)
make run-agent

# Containerized service deployment (pick the flavor)
uv run autonomy fetch --local --service valory/trader_pearl       # Omenstrat
uv run autonomy fetch --local --service valory/polymarket_trader  # Polystrat
```

## Project Structure

```
packages/valory/
├── agents/trader/                      # The single agent definition (used by both services)
├── connections/                        # polymarket_client (Polystrat CLOB v2), genai, x402, http_*, ipfs, ledger, ...
├── contracts/                          # Smart contract interfaces (FPMM, Conditional Tokens, Realitio, Safe, ERC-20/1155, ...)
├── customs/                            # Pluggable bet-sizing strategies: fixed_bet, kelly_criterion
├── services/
│   ├── trader_pearl/                   # Omenstrat service (Gnosis / Omen)
│   └── polymarket_trader/              # Polystrat service (Polygon / Polymarket CLOB v2)
└── skills/
    ├── trader_abci/                    # Main orchestrator / composed app
    ├── decision_maker_abci/            # Bet evaluation + placement (largest skill)
    ├── market_manager_abci/            # Market discovery (Omen + Polymarket variants)
    ├── mech_interact_abci/             # Mech communication
    ├── staking_abci/                   # Staking management
    ├── tx_settlement_multiplexer_abci/ # Routes settlement transactions
    ├── check_stop_trading_abci/        # Pause/stop conditions
    ├── agent_performance_summary_abci/ # Performance + payout tracking
    ├── chatui_abci/                    # Web UI hooks
    └── funds_manager/                  # Funds bookkeeping (uses RPC_URLS)
```

## Architecture

### ABCI Skill Pattern (core abstraction)

Every skill follows the Open Autonomy ABCI pattern — a finite state machine (FSM) replicated across agents via Tendermint consensus. Each skill contains:

- **`rounds.py`** — State (Round) classes defining consensus logic and transitions
- **`behaviours.py`** — Behaviours that execute at each FSM state (one per round)
- **`payloads.py`** — Data payloads agents submit to reach consensus
- **`handlers.py`** — Message handlers for incoming protocol messages
- **`models.py`** — Parameters (from YAML config) and shared state
- **`composition.py`** — FSM composition when orchestrating multiple skills
- **`fsm_specification.yaml`** — Machine-readable FSM spec (auto-checked by CI)
- **`skill.yaml`** — Metadata, dependencies, and configuration with env var substitution (`${VAR:type:default}`)

### Key Skills (composed in `trader_abci`)

| Skill | Purpose |
|---|---|
| `market_manager_abci` | Fetches and filters tradeable prediction markets |
| `decision_maker_abci` | Core trading logic — evaluates bets for profitability (largest skill) |
| `mech_interact_abci` | Communicates with AI Mech for probability estimates |
| `staking_abci` | Agent staking management |
| `tx_settlement_multiplexer_abci` | Routes transactions to correct settlement handler |
| `check_stop_trading_abci` | Evaluates stop-trading conditions |

Skills are composed via `chain()` in `trader_abci/composition.py`, which wires FSM transitions across skills.

### Custom Strategies (pluggable)

Trading strategies in `packages/valory/customs/` are pluggable modules that determine bet sizing. Currently shipped: `kelly_criterion` (default) and `fixed_bet`. The active strategy is picked by the `TRADING_STRATEGY` env var; sizing parameters flow through `STRATEGIES_KWARGS`. Strategies are loaded by IPFS hash via the `FILE_HASH_TO_STRATEGIES` map.

### Contracts

Interfaces to on-chain contracts (FPMM market maker, conditional tokens, Realitio oracle, Gnosis Safe, etc.) live in `packages/valory/contracts/`.

## Coding Conventions

- **Python**: range pinned in `pyproject.toml` (currently 3.10–3.14)
- **Black** formatting, 88-char line length
- **isort** with 3-line output mode and trailing commas
- **Sphinx-style** docstrings (enforced by darglint)
- **Type hints** required (mypy strict optional)
- **Apache 2.0** copyright headers on all files (auto-checked)
- **Encoding declaration**: `# -*- coding: utf-8 -*-` at top of files
- All packages have content-addressed hashes checked in CI — run `make generators` after modifying package contents

## Testing

- Tests live in `tests/` subdirectories within each skill package
- Run with pytest via tox (see Common Commands)
- Uses `unittest.mock.MagicMock` for mocking dependencies
- Test classes with setup methods; parametrized tests common
- Coverage tracked via `.coveragerc`
- **CI enforces 100% coverage** — after making changes, run coverage against **every file you modified**, not just the primary one. Use `--cov=packages.valory.skills.<skill>.<module>` for each changed module.

## Important Workflows

After modifying any package:

1. **Update FSM specs**: `make fix-abci-app-specs`
2. **Regenerate hashes**: `autonomy packages lock`
3. **Update copyrights**: included in `make generators`
4. **Check ABCI docstrings**: `tox -e check-abci-docstrings`

After adding/removing dependencies:

1. Update `pyproject.toml` and `tox.ini` ([deps-packages] and [extra-deps] sections)
2. Run `uv lock` then `uv sync --all-groups`
3. Run `tox -e check-dependencies`
