## Trader

Trader is an autonomous service that performs bets on prediction markets on the Gnosis chain.

## Developers

- Clone the repository:

      git clone https://github.com/valory-xyz/trader.git

- System requirements:

    - Python `== 3.10`
    - [Tendermint](https://docs.tendermint.com/v0.34/introduction/install.html) `==0.34.19`
    - [Poetry](https://python-poetry.org/docs/) `>=1.4.0`
    - [Docker Engine](https://docs.docker.com/engine/install/)
    - [Docker Compose](https://docs.docker.com/compose/install/)

- Create development environment:

      poetry install && poetry shell

- Configure command line:

      autonomy init --reset --author valory --remote --ipfs --ipfs-node "/dns/registry.autonolas.tech/tcp/443/https"

- Pull packages:

      autonomy packages sync --update-packages

## Testing the service against Gnosis  Mainnet

* Prepare some environment variables:
    ```
    export RPC_0=INSERT_YOUR_RPC
    export CHAIN_ID=100
    export ALL_PARTICIPANTS='["YOUR_AGENT_ADDRESS"]'
    export SAFE_CONTRACT_ADDRESS="YOUR_SAFE_ADDRESS"
    ```

* Fetch the service
    ```
    autonomy fetch --local --service valory/trader && cd trader
    ```

* Build the image:
    ```
    autonomy build-image
    ```

* Prepare the agent keys:
    ```
    cat > keys.json << EOF
    [
    {
        "address": "<your_agent_address>",
        "private_key": "<your_agent_private_key>"
    }
    ]
    EOF
    ```
* Build the deployment and run:
    ```
    autonomy deploy build --n 1 -ltm
    autonomy deploy run --build-dir abci_build/
    ```
