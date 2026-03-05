# CLAUDE.md

## Project Overview

Trader Service — an autonomous multi-agent service that places bets on prediction markets (Omen, Polymarket). Built on the Open Autonomy framework. The service retrieves markets, selects candidates, queries an AI Mech for probability estimates, and places bets when profitable.

## Tech Stack

- **Language**: Python 3.10–3.11
- **Package Manager**: Poetry (>=1.4.0)
- **Framework**: Open Autonomy 0.21.8
- **Key Libraries**: Web3 (>=7), Pydantic 2.11.9, aiohttp, py-clob-client (Polymarket)
- **Testing**: Pytest 7.4.4, tox, hypothesis
- **Linting/Formatting**: tomte (wraps black, isort, flake8, mypy, pylint, darglint, bandit)

## Common Commands

```bash
# Install dependencies
make poetry-install

# Format code (black + isort)
make format            # or: tomte format-code

# Run all linters and type checks
make code-checks       # or: tomte check-code

# Run security checks (bandit, safety, gitleaks)
make security

# Run tests (platform-specific)
tox -e py3.10-darwin   # macOS
tox -e py3.10-linux    # Linux

# Run a specific skill's tests directly
pytest packages/valory/skills/<skill_name>/tests

# Generate ABCI docstrings, update hashes, fix copyrights
make generators

# Update FSM specs for a specific skill
autonomy analyse fsm-specs --update --app-class <AppClass> --package packages/valory/skills/<skill_name>

# Run all checks (format + lint + security + generators + common checks)
make all-checks

# CI linter checks (the full CI lint suite)
make ci-linter-checks
```

## Project Structure

```
packages/valory/
├── agents/              # Agent definitions (trader)
├── connections/         # Network connections (polymarket_client)
├── contracts/           # Smart contract interfaces (Realitio, Conditional Tokens, etc.)
├── customs/             # Trading strategies (kelly_criterion, bet_amount_per_threshold, etc.)
├── services/            # Service definitions (trader, trader_pearl, polymarket_trader)
├── skills/              # ABCI skills (main business logic)
│   ├── trader_abci/                    # Main orchestrator / composed app
│   ├── decision_maker_abci/            # Bet decision logic
│   ├── market_manager_abci/            # Market retrieval and management
│   ├── staking_abci/                   # Staking logic
│   ├── tx_settlement_multiplexer_abci/ # Transaction routing
│   ├── check_stop_trading_abci/        # Pause/stop logic
│   ├── agent_performance_summary_abci/ # Performance tracking
│   ├── chatui_abci/                    # Web interface
│   └── mech_interact_abci/            # Mech communication (external dependency)
└── protocols/           # Message protocols
scripts/                 # Build and deployment utilities
```

## Coding Conventions

- **License header**: Apache 2.0 (Valory AG) on every file — enforced by `tox -e copyright-check`
- **Encoding declaration**: `# -*- coding: utf-8 -*-` at top of files
- **Formatting**: Black (via tomte), isort for imports
- **Type hints**: Required on all functions — mypy with `--disallow-untyped-defs`
- **Docstrings**: Required — checked by darglint
- **Naming**: PascalCase for classes, snake_case for functions/variables, UPPER_SNAKE_CASE for constants
- **Imports**: Organized by isort; relative imports within packages

## Architecture Patterns

Each skill follows the ABCI application pattern:

- **Rounds** (`rounds.py`): Define states and state transitions in a finite state machine (FSM)
- **Behaviours** (`behaviours.py`): Implement round logic, extend `BaseBehaviour`
- **Payloads** (`payloads.py`): Data sent between agents during consensus
- **Models** (`models.py`): Skill parameters and shared state, extend base model classes
- **Handlers** (`handlers.py`): Message handlers, inherit from base handlers in `abstract_round_abci`

The main app (`TraderAbciApp` in `trader_abci`) composes multiple skill FSMs into a single chained application.

When modifying FSM logic, always run `make fix-abci-app-specs` to regenerate the FSM spec files, then `make generators` to update hashes and docstrings.

## Testing

- Tests live in `tests/` subdirectories within each skill package
- Run with pytest via tox (see Common Commands)
- Uses `unittest.mock.MagicMock` for mocking dependencies
- Test classes with setup methods; parametrized tests common
- Coverage tracked via `.coveragerc`

## Important Workflows

After modifying any package:

1. **Update FSM specs**: `make fix-abci-app-specs`
2. **Regenerate hashes**: `autonomy packages lock`
3. **Update copyrights**: included in `make generators`
4. **Check ABCI docstrings**: `tox -e check-abci-docstrings`

After adding/removing dependencies:

1. Update `pyproject.toml` and `tox.ini` ([deps-packages] and [extra-deps] sections)
2. Run `poetry lock` then `make poetry-install`
3. Run `tox -e check-dependencies`
