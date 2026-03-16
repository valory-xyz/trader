#!/bin/bash

# Default port values
DEFAULT_TENDERMINT_ABCI_PORT=26658
DEFAULT_TENDERMINT_RPC_PORT=26657
DEFAULT_TENDERMINT_P2P_PORT=26656
DEFAULT_TENDERMINT_COM_PORT=8080
DEFAULT_HTTP_SERVER_PORT=8716

# Parse command line arguments
FREE_PORTS=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --free-ports)
      FREE_PORTS=true
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--free-ports]"
      echo ""
      echo "Options:"
      echo "  --free-ports    Automatically find free ports for services"
      echo "                  (uses environment variables if set, otherwise finds free ports)"
      echo ""
      echo "Without flags: uses default ports or values from environment variables:"
      echo "  TENDERMINT_ABCI_PORT (default: 26658)"
      echo "  TENDERMINT_RPC_PORT (default: 26657)"
      echo "  TENDERMINT_P2P_PORT (default: 26656)"
      echo "  TENDERMINT_COM_PORT (default: 8080)"
      echo "  HTTP_SERVER_PORT (default: 8716)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

cleanup() {
    echo "Terminating tendermint..."
    if kill -0 "$tm_subprocess_pid" 2>/dev/null; then
        kill "$tm_subprocess_pid"
        wait "$tm_subprocess_pid" 2>/dev/null
    fi
    echo "Tendermint terminated"
}

# Link cleanup to the exit signal
trap cleanup EXIT

# Remove previous agent if exists
if test -d agent; then
  echo "Removing previous agent build"
  sudo rm -r agent
fi

# Remove empty directories to avoid wrong hashes
find . -empty -type d -delete
make clean

# Ensure hashes are updated
autonomy packages lock

# Fetch the agent
autonomy fetch --local --agent valory/trader --alias agent

# Generate and set port environment variables
echo "Generating port environment variables..."
if [ -f scripts/generate_port_env.py ]; then
  # Build command arguments
  cmd_args="--config agent/aea-config.yaml"
  
  if [ "$FREE_PORTS" = true ]; then
    echo "Using free ports mode: automatically finding available ports"
    # For each port: use env var if set, otherwise use 0 (auto-find)
    if [ -n "${TENDERMINT_ABCI_PORT:-}" ]; then
      cmd_args="$cmd_args --abci-port $TENDERMINT_ABCI_PORT"
    else
      cmd_args="$cmd_args --abci-port 0"
    fi
    
    if [ -n "${TENDERMINT_RPC_PORT:-}" ]; then
      cmd_args="$cmd_args --rpc-port $TENDERMINT_RPC_PORT"
    else
      cmd_args="$cmd_args --rpc-port 0"
    fi
    
    if [ -n "${TENDERMINT_P2P_PORT:-}" ]; then
      cmd_args="$cmd_args --p2p-port $TENDERMINT_P2P_PORT"
    else
      cmd_args="$cmd_args --p2p-port 0"
    fi
    
    if [ -n "${TENDERMINT_COM_PORT:-}" ]; then
      cmd_args="$cmd_args --com-port $TENDERMINT_COM_PORT"
    else
      cmd_args="$cmd_args --com-port 0"
    fi
    
    if [ -n "${HTTP_SERVER_PORT:-}" ]; then
      cmd_args="$cmd_args --http-port $HTTP_SERVER_PORT"
    else
      cmd_args="$cmd_args --http-port 0"
    fi
  else
    # Add port arguments with default values if not set
    # Use 0 for dynamic allocation if variable is not set
    if [ -n "${TENDERMINT_ABCI_PORT:-}" ]; then
      cmd_args="$cmd_args --abci-port $TENDERMINT_ABCI_PORT"
    else
      cmd_args="$cmd_args --abci-port $DEFAULT_TENDERMINT_ABCI_PORT"
    fi
    
    if [ -n "${TENDERMINT_RPC_PORT:-}" ]; then
      cmd_args="$cmd_args --rpc-port $TENDERMINT_RPC_PORT"
    else
      cmd_args="$cmd_args --rpc-port $DEFAULT_TENDERMINT_RPC_PORT"
    fi
    
    if [ -n "${TENDERMINT_P2P_PORT:-}" ]; then
      cmd_args="$cmd_args --p2p-port $TENDERMINT_P2P_PORT"
    else
      cmd_args="$cmd_args --p2p-port $DEFAULT_TENDERMINT_P2P_PORT"
    fi
    
    if [ -n "${TENDERMINT_COM_PORT:-}" ]; then
      cmd_args="$cmd_args --com-port $TENDERMINT_COM_PORT"
    else
      cmd_args="$cmd_args --com-port $DEFAULT_TENDERMINT_COM_PORT"
    fi
    
    if [ -n "${HTTP_SERVER_PORT:-}" ]; then
      cmd_args="$cmd_args --http-port $HTTP_SERVER_PORT"
    else
      cmd_args="$cmd_args --http-port $DEFAULT_HTTP_SERVER_PORT"
    fi
  fi
  
  # Execute the command and set environment variables
  # Read output and export each variable
  while IFS= read -r line; do
    if [[ "$line" == export* ]]; then
      # Execute export command as-is to export variables
      eval "$line"
    fi
  done < <(python scripts/generate_port_env.py $cmd_args)
  
  echo "Using ports:"
  echo "  ABCI: ${TENDERMINT_ABCI_PORT:-not set}"
  echo "  RPC: ${TENDERMINT_RPC_PORT:-not set}"
  echo "  P2P: ${TENDERMINT_P2P_PORT:-not set}"
  echo "  COM: ${TENDERMINT_COM_PORT:-not set}"
  echo "  HTTP: ${HTTP_SERVER_PORT:-not set}"
  
  echo ""
  echo "Agent environment variables set:"
  echo "  TENDERMINT_ABCI_PORT=${TENDERMINT_ABCI_PORT:-}"
  echo "  TENDERMINT_RPC_PORT=${TENDERMINT_RPC_PORT:-}"
  echo "  TENDERMINT_P2P_PORT=${TENDERMINT_P2P_PORT:-}"
  echo "  TENDERMINT_COM_PORT=${TENDERMINT_COM_PORT:-}"
  echo "  HTTP_SERVER_PORT=${HTTP_SERVER_PORT:-}"
  echo "  CONNECTION_ABCI_CONFIG_PORT=${CONNECTION_ABCI_CONFIG_PORT:-}"
  echo "  CONNECTION_HTTP_SERVER_CONFIG_PORT=${CONNECTION_HTTP_SERVER_CONFIG_PORT:-}"
  echo "  SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_URL=${SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_URL:-}"
  echo "  SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_COM_URL=${SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_COM_URL:-}"
  echo "  SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL=${SKILL_TRADER_ABCI_MODELS_PARAMS_ARGS_TENDERMINT_P2P_URL:-}"
else
  echo "Warning: generate_port_env.py not found, using default ports"
  # Default port values
  TENDERMINT_ABCI_PORT=${TENDERMINT_ABCI_PORT:-$DEFAULT_TENDERMINT_ABCI_PORT}
  TENDERMINT_RPC_PORT=${TENDERMINT_RPC_PORT:-$DEFAULT_TENDERMINT_RPC_PORT}
  TENDERMINT_P2P_PORT=${TENDERMINT_P2P_PORT:-$DEFAULT_TENDERMINT_P2P_PORT}
  TENDERMINT_COM_PORT=${TENDERMINT_COM_PORT:-$DEFAULT_TENDERMINT_COM_PORT}
  HTTP_SERVER_PORT=${HTTP_SERVER_PORT:-$DEFAULT_HTTP_SERVER_PORT}
fi

# Replace params with env vars
if [ -f .env ]; then
  source .env
else
  echo "Warning: .env file not found, skipping environment variables"
fi

# Run aea-config-replace quietly
python scripts/aea-config-replace.py 2>/dev/null

# Copy and add the keys and issue certificates
cd agent
cp $PWD/../ethereum_private_key.txt .
autonomy add-key ethereum ethereum_private_key.txt
autonomy add-key ethereum ethereum_private_key.txt --connection
autonomy issue-certificates

# Run tendermint
rm -r ~/.tendermint
tendermint init > /dev/null 2>&1
echo "Starting Tendermint..."
tendermint node \
  --proxy_app=tcp://127.0.0.1:$TENDERMINT_ABCI_PORT \
  --rpc.laddr=tcp://127.0.0.1:$TENDERMINT_RPC_PORT \
  --p2p.laddr=tcp://0.0.0.0:$TENDERMINT_P2P_PORT \
  --p2p.seeds= \
  --consensus.create_empty_blocks=true > /dev/null 2>&1 &
tm_subprocess_pid=$!

# Run the agent with environment variables
echo "Starting agent with configured ports..."
aea -s run --aev