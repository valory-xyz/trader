# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The **Trader** is an autonomous agent service built on the [Open Autonomy](https://docs.autonolas.network/) framework. It places bets on prediction markets (Omen, Polymarket) by querying an AI Mech for probability estimates, evaluating profitability, and executing on-chain transactions via a Safe multisig wallet. Runs on Gnosis chain with Tendermint-based consensus for multi-agent operation.

## Common Commands

### Testing
```bash
# Run all skill tests
tox -e py3.10-linux     # or py3.11-linux, py3.10-darwin, etc.

# Run a single skill's tests
pytest packages/valory/skills/<skill_name>/tests/ -v

# Run a specific test
pytest packages/valory/skills/<skill_name>/tests/test_behaviours.py::TestClassName::test_method -v
```

### Linting & Formatting
```bash
make format              # Auto-format (black + isort via tomte)
make code-checks         # All linting: black, isort, flake8, mypy, pylint, darglint
make security            # bandit + safety + gitleaks
make common-checks-1     # copyright, dependencies, linting
make common-checks-2     # hash check, package check, ABCI checks
make all-checks          # Everything
```

### Code Generation & Hashes
```bash
make generators          # Update hashes, copyright headers, ABCI docstrings
make sync-packages       # Sync package versions across the repo
```

### Running
```bash
make run-agent           # Run agent with Tendermint node
./run_agent.sh           # Shell script alternative
./run_service.sh         # Run as a service
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

Trading strategies in `packages/*/customs/` are pluggable modules that determine bet sizing. Examples: `bet_amount_per_threshold`, `kelly_criterion`, `kelly_criterion_no_conf`.

### Contracts

Interfaces to on-chain contracts (FPMM market maker, conditional tokens, Realitio oracle, Gnosis Safe, etc.) live in `packages/valory/contracts/`.

## Code Style

- **Python 3.10+** (compatible with 3.11, not 3.12)
- **Black** formatting, 88-char line length
- **isort** with 3-line output mode and trailing commas
- **Sphinx-style** docstrings (enforced by darglint)
- **Type hints** required (mypy strict optional)
- **Apache 2.0** copyright headers on all files (auto-checked)
- All packages have content-addressed hashes checked in CI — run `make generators` after modifying package contents
