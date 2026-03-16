# Port Configuration for run_agent.sh

## Quick Start

```bash
# Default ports
./run_agent.sh

# Auto-find free ports (starts from 50000)
./run_agent.sh --free-ports

# Custom ports with --free-ports (uses env vars if set)
HTTP_SERVER_PORT=9999 ./run_agent.sh --free-ports
```

## Environment Variables

Set these before running `./run_agent.sh`:

```bash
TENDERMINT_ABCI_PORT=26658    # ABCI port
TENDERMINT_RPC_PORT=26657     # RPC port  
TENDERMINT_P2P_PORT=26656     # P2P port
TENDERMINT_COM_PORT=8080      # COM port
HTTP_SERVER_PORT=8716         # HTTP port
```

## Examples

### With --free-ports
```bash
# All ports auto (50000+)
./run_agent.sh --free-ports

# HTTP=9999, others auto
HTTP_SERVER_PORT=9999 ./run_agent.sh --free-ports

# ABCI=26668, others auto
TENDERMINT_ABCI_PORT=26668 ./run_agent.sh --free-ports

# All ports specified via env
TENDERMINT_ABCI_PORT=26668 \
TENDERMINT_RPC_PORT=26667 \
TENDERMINT_P2P_PORT=26666 \
TENDERMINT_COM_PORT=8081 \
HTTP_SERVER_PORT=8726 \
./run_agent.sh --free-ports
```

### Multiple Agents
```bash
# Agent 1: defaults
./run_agent.sh

# Agent 2: auto ports
./run_agent.sh --free-ports

# Agent 3: custom + auto
TENDERMINT_ABCI_PORT=26678 HTTP_SERVER_PORT=9999 ./run_agent.sh --free-ports
```

### .env File
Create `.env`:
```bash
TENDERMINT_ABCI_PORT=26668
TENDERMINT_RPC_PORT=26667
TENDERMINT_P2P_PORT=26666
TENDERMINT_COM_PORT=8081
HTTP_SERVER_PORT=8726
```

Run: `./run_agent.sh`

## How It Works

### Without --free-ports:
- Uses environment variables if set
- Otherwise uses default ports
- No automatic port finding

### With --free-ports:
1. Checks each port's environment variable
2. If variable is set → uses that port
3. If variable is not set → finds free port (starting from 50000)
4. Ports are allocated in increments of 10 (50000, 50010, 50020, etc.)

## Notes

- `--free-ports` respects environment variables
- Port conflicts prevent startup
- Use different ports for multiple agents
- Ports checked before startup
- Auto ports start from 50000 to avoid conflicts with defaults