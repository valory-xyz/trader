#!/usr/bin/env bash

export STORE_PATH='/tmp/'

REPO_PATH=$PWD

# Remove previous service build
if test -d trader; then
  echo "Removing previous service build"
  sudo rm -r trader
fi

# Push packages and fetch service
make clean

autonomy push-all

autonomy fetch --local --service valory/trader && cd trader

# Build the image
autonomy init --reset --author valory --remote --ipfs --ipfs-node "/dns/registry.autonolas.tech/tcp/443/https"
autonomy build-image

# Copy .env file
cp $REPO_PATH/.env .

# Copy the keys and build the deployment
cp $REPO_PATH/keys.json .
autonomy deploy build -ltm

# Run the deployment
build_dir=$(find . -maxdepth 1 -type d -name "abci_build*")
autonomy deploy run --build-dir $build_dir