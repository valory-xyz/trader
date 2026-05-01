# Trader

The **Trader** repo hosts the [Olas](https://olas.network/) prediction-market agents. A single agent package — `valory/trader` — is shipped as two separate services, each pinned to a different chain and market venue:

| Service | Stack name | Chain | Market venue | Collateral |
|---|---|---|---|---|
| `valory/trader_pearl` | **Omenstrat** | Gnosis (`chain_id=100`) | [Omen](https://aiomen.eth.limo/) | xDAI / wxDAI |
| `valory/polymarket_trader` | **Polystrat** | Polygon (`chain_id=137`) | [Polymarket](https://polymarket.com/) (CLOB v2) | pUSD (wraps from USDC.e) |

Both services run as **single-agent (sovereign) deployments** distributed via [Pearl](https://olas.network/operate). The agent queries an [AI Mech](https://github.com/valory-xyz/mech) for probability estimates, evaluates profitability, and executes on-chain via a Safe multisig.

The high-level loop is the same in both flavors:

1. Retrieve open prediction markets.
2. Pick a market to investigate.
3. Ask an AI Mech for `p_yes` / `p_no` and a confidence score.
4. If the bet clears the configured profitability threshold, place it; otherwise temporarily blacklist the market.
5. Settle / redeem winning positions.
6. Repeat.

The Trader is built on the [Open Autonomy framework](https://stack.olas.network/open-autonomy/) (ABCI skills, FSMs, content-addressed packages).

---

## Prepare the environment

System requirements:

- Python `>=3.10, <3.15`
- [uv](https://docs.astral.sh/uv/)
- [Docker Engine](https://docs.docker.com/engine/install/) and [Docker Compose](https://docs.docker.com/compose/install/) (only needed for `autonomy deploy` style runs)
- Linux or macOS (Windows is supported for the agent runner binary, see `Makefile`)

Clone and install:

```bash
git clone https://github.com/valory-xyz/trader.git
cd trader
uv sync --all-groups
```

Configure the Open Autonomy framework and pull the package set:

```bash
uv run autonomy init --reset --author valory --remote --ipfs --ipfs-node "/dns/registry.autonolas.tech/tcp/443/https"
uv run autonomy packages sync --update-packages
```

> Always run `autonomy`, `aea`, `aea-helpers`, `pytest` and friends through `uv run` — the tools come from the `uv`-managed venv, not the system Python.

---

## Prepare the keys and the Safe

You need an EOA keypair for the agent and a Safe multisig that the agent will operate. The chain depends on which service you're running:

- **Omenstrat (`trader_pearl`)** → Gnosis Safe, EOA funded with xDAI for gas.
- **Polystrat (`polymarket_trader`)** → Polygon Safe; The Safe needs USDC.e (auto-wrapped to pUSD) or pUSD for betting capital and POL for the mech-payment swap stream.

Create `keys.json` in the repo root:

```bash
cat > keys.json << EOF
[
  {
    "address": "YOUR_AGENT_ADDRESS",
    "private_key": "YOUR_AGENT_PRIVATE_KEY"
  }
]
EOF
```

For end users, the Safe is created and registered automatically through Pearl. If you are setting up the service manually for development, follow the [Olas Protocol service registration flow](https://stack.olas.network/open-autonomy/) and use the relevant `service/...` hash from [`packages/packages.json`](./packages/packages.json):

- `service/valory/trader_pearl/0.1.0`
- `service/valory/polymarket_trader/0.1.0`

---

## Configure the service

The two services share most variables (Open Autonomy plumbing, Mech interaction, staking, agent performance summary) and differ in the chain / market parameters. The full list lives in each service's `service.yaml`:

- [`packages/valory/services/trader_pearl/service.yaml`](./packages/valory/services/trader_pearl/service.yaml)
- [`packages/valory/services/polymarket_trader/service.yaml`](./packages/valory/services/polymarket_trader/service.yaml)

The minimum every deployment needs:

```bash
export ALL_PARTICIPANTS='["YOUR_AGENT_ADDRESS"]'
export SAFE_CONTRACT_ADDRESS="YOUR_SAFE_ADDRESS"
```

### Omenstrat (`trader_pearl`) — Gnosis / Omen

```bash
export GNOSIS_LEDGER_RPC="https://rpc-gate.autonolas.tech/gnosis-rpc/"
export RPC_URLS='{"gnosis":"https://rpc-gate.autonolas.tech/gnosis-rpc/"}'

# Strategy + sizing knobs (see "Strategy configuration" below)
export TRADING_STRATEGY=kelly_criterion
export STRATEGIES_KWARGS='{"floor_balance":0,"default_max_bet_size":2000000000000000000,"absolute_min_bet_size":25000000000000000,"absolute_max_bet_size":2000000000000000000,"n_bets":1,"min_edge":0.03,"min_oracle_prob":0.5,"fee_per_trade":10000000000000000,"grid_points":500}'

# Optional: override the default Omen market creator(s) the agent tracks
export CREATOR_PER_SUBGRAPH='{"omen_subgraph":["0xFfc8029154ECD55ABED15BD428bA596E7D23f557"]}'
```

### Polystrat (`polymarket_trader`) — Polygon / Polymarket CLOB v2

> **Local-dev gotcha.** The agent-level [`aea-config.yaml`](./packages/valory/agents/trader/aea-config.yaml) defaults are **Omen-flavored** (`is_running_on_polymarket=false`, `mech_chain_id=gnosis`, `default_chain_id=gnosis`, Omen-scaled `strategies_kwargs`, Omen `tools_accuracy_hash`, `use_multi_bets_mode=true`, etc.). Service-level overrides only apply when you run via `autonomy deploy` against `valory/polymarket_trader`. If you run the agent directly with `make run-agent` / `aea-helpers run-agent`, you **must** pass the full Polystrat override set below — otherwise the agent will start in Omenstrat mode against Polygon RPCs and behave incorrectly.

```bash
# REQUIRED — flips the agent into Polystrat mode
export IS_RUNNING_ON_POLYMARKET=true
export MECH_CHAIN_ID=polygon
export DEFAULT_CHAIN_ID=polygon

export POLYGON_LEDGER_RPC="https://rpc-gate.autonolas.tech/polygon-rpc/"
export RPC_URLS='{"polygon":"https://rpc-gate.autonolas.tech/polygon-rpc/"}'

# Strategy + sizing knobs — pUSD (6 decimals), so values are scaled accordingly
export TRADING_STRATEGY=kelly_criterion
export STRATEGIES_KWARGS='{"floor_balance":0,"default_max_bet_size":2500000,"absolute_min_bet_size":1000000,"absolute_max_bet_size":2500000,"n_bets":1,"min_edge":0.01,"min_oracle_prob":0.1,"fee_per_trade":10000,"grid_points":500}'

# Polystrat market-filter defaults differ from agent-level aea-config defaults
export USE_MULTI_BETS_MODE=false
export IS_OUTCOME_SIDE_THRESHOLD_FILTER_ENABLED=true
export EXCLUDE_NEG_RISK_MARKETS=true
export POLYMARKET_BUILDER_PROGRAM_ENABLED=false

# Polystrat-specific Mech accuracy hash
export TOOLS_ACCURACY_HASH=QmdNF1cidJASsVKSnbvSSmZLLaYfBPixBzpT4Pw3ZvmYTu
```

The full set of Polystrat overrides lives in [`polymarket_trader/service.yaml`](./packages/valory/services/polymarket_trader/service.yaml) — diff it against [`aea-config.yaml`](./packages/valory/agents/trader/aea-config.yaml) if you suspect drift.

The v2 collateral is **pUSD** (`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`). The agent accepts USDC.e in the Safe and wraps it to pUSD on demand via the Polymarket Collateral Onramp.

### Common variables

| Variable | Description |
|---|---|
| `GNOSIS_LEDGER_RPC` / `POLYGON_LEDGER_RPC` | RPC endpoint per chain. We use `https://rpc-gate.autonolas.tech/{gnosis,polygon}-rpc/` in production. Also flows into the per-skill `ledger` connection. |
| `RPC_URLS` | Dict of `{chain: url}` consumed by `funds_manager` for balance / multicall reads. Pearl sets this to e.g. `{"polygon":"https://rpc-gate.autonolas.tech/polygon-rpc/"}` (or the gnosis equivalent). Keep in sync with the per-chain `*_LEDGER_RPC`. |
| `IS_RUNNING_ON_POLYMARKET` | Master switch between Polystrat (`true`) and Omenstrat (`false`). The service-level YAMLs default this correctly, but **`aea-config.yaml` defaults to `false`** — so any local-dev run that goes through `aea-helpers run-agent` must set this explicitly to run Polystrat. See the Polystrat section above for the full override set. |
| `ALL_PARTICIPANTS` | List of agent EOAs participating in the service. Single-agent deployments pass a one-element list. |
| `SAFE_CONTRACT_ADDRESS` / `SAFE_CONTRACT_ADDRESSES` | The agent's Safe multisig (the dict form is `{"gnosis":"0x..."}` or `{"polygon":"0x..."}`). |
| `TRADING_STRATEGY` | Bet-sizing strategy name. Defaults to `kelly_criterion`; `fixed_bet` is the other shipped option. |
| `STRATEGIES_KWARGS` | Dict of strategy parameters (`min_edge`, `default_max_bet_size`, `absolute_min/max_bet_size`, `fee_per_trade`, `n_bets`, `min_oracle_prob`, `floor_balance`, `grid_points`). Replaces the old `BET_AMOUNT_PER_THRESHOLD_*` / `BET_THRESHOLD` env vars. |
| `FILE_HASH_TO_STRATEGIES` | Maps the IPFS hash of a `customs/` package to the strategy names it provides. Defaulted; only override if you ship a new strategy. |
| `CREATOR_PER_SUBGRAPH` | Dict mapping market-spec subgraph name to creator addresses to track (Omen-only by default). |
| `PROMPT_TEMPLATE` | Single-line prompt for the prediction Mech, with `@{question}`, `@{yes}`, `@{no}` placeholders. |

`POLYGON_LEDGER_CHAIN_ID` / `GNOSIS_LEDGER_CHAIN_ID` exist too but default to the right values (137 / 100), so you don't normally need to set them.

---

## Run the service

### Local development — `aea-helpers run-agent`

This is the day-to-day developer loop. It runs the agent directly out of the working tree without Docker.

1. Populate `.env` with the variables above (or `export` them in your shell).
2. Place your `ethereum_private_key.txt` in the repo root (or generate with `uv run autonomy generate-key ethereum`).
3. Run:

   ```bash
   make run-agent
   ```

   which is a wrapper for:

   ```bash
   uv run aea-helpers run-agent --name valory/trader --connection-key
   ```

   Logs are tee'd to `./logs/agent_log_latest.log` and a timestamped file in `./logs/`.

To run multiple agents on the same machine without port conflicts, add `--free-ports`.

### Service deployment — `autonomy deploy`

For a containerized run that mirrors the Pearl-distributed deployment:

```bash
# Pick the service flavor you want
uv run autonomy fetch --local --service valory/trader_pearl       # Omenstrat
# or
uv run autonomy fetch --local --service valory/polymarket_trader  # Polystrat

cd trader_pearl   # or polymarket_trader
uv run autonomy build-image
cp ../keys.json .
uv run autonomy deploy build --n 1 -ltm
build_dir=$(ls -d abci_build_????/ 2>/dev/null || echo "abci_build")
uv run autonomy deploy run --build-dir $build_dir
```

### Pearl-distributed binary

Production agents run as a PyInstaller-packaged single-file binary built by `make build-agent-runner` (Linux/Windows) or `make build-agent-runner-mac` (macOS, with codesign). The output `dist/agent_runner_bin` is what Pearl ships to end users. `make check-agent-runner` smoke-tests the resulting binary.

### Create a release

```bash
uv run aea-helpers make-release --version <VERSION> --env <ENV> --description "<DESCRIPTION>"
```

---

## Repo layout

After `autonomy packages sync`, the layout looks like:

```
packages/valory/
├── agents/trader/                       # The single agent definition
├── connections/
│   ├── polymarket_client/               # Polystrat: CLOB v2 client + Safe relayer
│   └── ...                              # http_client, http_server, ipfs, ledger, x402, genai, ...
├── contracts/                           # FPMM, Conditional Tokens, Realitio, Safe, ERC-20/1155, ...
├── customs/                             # Pluggable bet-sizing strategies (see below)
├── services/
│   ├── trader_pearl/                    # Omenstrat service definition
│   └── polymarket_trader/               # Polystrat service definition
└── skills/
    ├── trader_abci/                     # Top-level FSM composition
    ├── decision_maker_abci/             # Bet evaluation + placement (largest skill)
    ├── market_manager_abci/             # Market discovery (Omen + Polymarket variants)
    ├── mech_interact_abci/              # Mech request/response
    ├── staking_abci/                    # Staking management
    ├── tx_settlement_multiplexer_abci/  # Routes settlement transactions
    ├── check_stop_trading_abci/         # Pause/stop conditions
    ├── agent_performance_summary_abci/  # Performance + payout tracking
    ├── chatui_abci/                     # Web UI hooks
    └── funds_manager/                   # Funds bookkeeping
```

### Strategy configuration

Bet-sizing strategies are pluggable [Open Autonomy `customs/`](./packages/valory/customs/) packages, loaded from IPFS by hash and dispatched at runtime:

| Strategy | Notes |
|---|---|
| [`kelly_criterion`](./packages/valory/customs/kelly_criterion) | Execution-aware Kelly sizing for both CLOB (Polymarket) and FPMM (Omen) markets. **Default.** |
| [`fixed_bet`](./packages/valory/customs/fixed_bet) | Constant bet size regardless of confidence. Useful for benchmarking and as a fallback. |

The active strategy is picked by `TRADING_STRATEGY`. All sizing knobs are passed to it via the `STRATEGIES_KWARGS` dict. The shipped Omen / Polymarket defaults differ only in scale (Omen values are 18-decimal wxDAI; Polymarket values are 6-decimal pUSD). Tunable keys:

| Key | Meaning |
|---|---|
| `min_edge` | Minimum AI-Mech edge over market price to consider a bet profitable. Replaces the old `BET_THRESHOLD`. |
| `default_max_bet_size`, `absolute_min_bet_size`, `absolute_max_bet_size` | Per-bet size bounds in collateral units (chain-native wei). |
| `n_bets` | How many bets to consider per round. |
| `min_oracle_prob` | Minimum Mech confidence required to enter a position. |
| `fee_per_trade` | Expected fee deduction in collateral units, used in profitability math. |
| `floor_balance` | Don't trade if Safe balance would drop below this. |
| `grid_points` | Resolution of the Kelly search grid. |

To ship a new strategy:

1. Drop a new package under `packages/<author>/customs/<name>/` and lock it (`uv run autonomy packages lock`).
2. Add its IPFS hash → name mapping to `FILE_HASH_TO_STRATEGIES`.
3. Set `TRADING_STRATEGY=<name>`.

---

## Development workflow

After modifying any package:

1. **Lint and format**: `uv run tomte format-code` and `uv run tomte check-code` (or `make format` / `make code-checks`).
2. **Update FSM specs** (only the trader-owned skills, never `make generators`):

   ```bash
   make fix-abci-app-specs
   ```

3. **Lock package hashes**:

   ```bash
   uv run autonomy packages lock
   ```

4. **Run the relevant tests**:

   ```bash
   uv run pytest packages/valory/skills/<skill_name>/tests/ -v
   ```

   or the full suite via `tox`:

   ```bash
   uv run tox -e py3.10-linux   # 3.11/3.12/3.13/3.14 also supported
   ```

5. **Run the CI lint suite** before pushing: `make ci-linter-checks`.

CI enforces 100% coverage on touched modules — see `CLAUDE.md` for the per-module `--cov` pattern.

### Dependency changes

If you add or remove a dependency:

1. Edit `pyproject.toml` and the `[deps-packages]` / `[extra-deps]` blocks in `tox.ini`.
2. `uv lock && uv sync --all-groups`.
3. `uv run tox -e check-dependencies`.

---

## Notes on profitability

- If the agent does not have enough funds to place a bet, you'll see `Event.INSUFICIENT_FUNDS` in the logs.
- If a bet is deemed unprofitable (the strategy's expected edge is below `STRATEGIES_KWARGS.min_edge` after fees), you'll see `Event.UNPROFITABLE` and the market is blacklisted for a configurable duration.
- For Omen, fees are queryable via the [Omen subgraph on The Graph](https://thegraph.com/explorer); they have historically sat around 0.02 xDAI but should be re-checked.
- For Polymarket CLOB v2, fee math is delegated to the protocol — see `client.get_clob_market_info(condition_id)["fd"]`.

---

## Further reading

- Architecture and conventions: [`CLAUDE.md`](./CLAUDE.md).
- Contributing: [`CONTRIBUTING.md`](./CONTRIBUTING.md).
- Security policy: [`SECURITY.md`](./SECURITY.md).
- [Open Autonomy framework](https://stack.olas.network/open-autonomy/)
