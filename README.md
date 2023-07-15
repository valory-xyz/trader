## Trader

Trader is an autonomous service that performs bets on existing prediction markets on the Omen platform (Gnosis chain). The service roughly works as follows:

1. Monitor existing prediction markets on the Gnosis chain that met a certain condition (e.g., markets created by a set of given addresses).
2. For each suitable market, send a request to an [AI Mech](https://github.com/valory-xyz/mech) to estimate the likelihood of the answers of the market, together with a confidence value when making this prediction.
3. If the response of the [AI Mech](https://github.com/valory-xyz/mech) satisfies a certain confidence, the service will bet a pre-determined amount on that market. The amount to bet can be configured according to the confidence returned by the AI Mech.
4. Repeat steps 1-3.

## Developers

- System requirements:

    - Python `== 3.10`
    - [Tendermint](https://docs.tendermint.com/v0.34/introduction/install.html) `==0.34.19`
    - [Poetry](https://python-poetry.org/docs/) `>=1.4.0`
    - [Docker Engine](https://docs.docker.com/engine/install/)
    - [Docker Compose](https://docs.docker.com/compose/install/)

- Clone the repository:

      git clone https://github.com/valory-xyz/trader.git

- Create development environment:

      poetry install && poetry shell

- Configure command line:

      autonomy init --reset --author valory --remote --ipfs --ipfs-node "/dns/registry.autonolas.tech/tcp/443/https"

- Pull packages:

      autonomy packages sync --update-packages

## Testing the service against Gnosis  Mainnet

* Prepare some environment variables:

    ```bash
    export RPC_0=INSERT_YOUR_RPC
    export RPC_1=INSERT_YOUR_RPC
    export RPC_2=INSERT_YOUR_RPC
    export RPC_3=INSERT_YOUR_RPC
    export CHAIN_ID=100
    export ALL_PARTICIPANTS='["YOUR_AGENT_ADDRESS"]'
    export SAFE_CONTRACT_ADDRESS="YOUR_SAFE_ADDRESS"
    export OMEN_CREATORS='["CREATOR_0", "CREATOR_1", ...]'
    
    # Optional
    export BET_AMOUNT_PER_THRESHOLD_000=0
    export BET_AMOUNT_PER_THRESHOLD_000=0
    export BET_AMOUNT_PER_THRESHOLD_010=0
    export BET_AMOUNT_PER_THRESHOLD_020=0
    export BET_AMOUNT_PER_THRESHOLD_030=0
    export BET_AMOUNT_PER_THRESHOLD_040=0
    export BET_AMOUNT_PER_THRESHOLD_050=0
    export BET_AMOUNT_PER_THRESHOLD_060=600000000000000000
    export BET_AMOUNT_PER_THRESHOLD_070=900000000000000000
    export BET_AMOUNT_PER_THRESHOLD_080=1000000000000000000
    export BET_AMOUNT_PER_THRESHOLD_090=10000000000000000000
    export BET_AMOUNT_PER_THRESHOLD_100=100000000000000000000
    export BET_THRESHOLD=100000000000000000
    ```

  Substitute the above placeholders with their respective actual values:
  - `RPC_i`: RPC endpoint per agent.
  - `CHAIN_ID`: identifier of the chain on which the service is running.
  - `ALL_PARTICIPANTS`: list of all the agent addresses participating in the service.
    This demo is for running the service with a single agent.
    In case you want to run it with more agents, please edit the keys generation command below,
    and replace the `--n 1` argument in the `build` command with the number of your agents.
  - `SAFE_CONTRACT_ADDRESS`: address of the agents' multisig wallet.
  - `OMEN_CREATORS`: addresses of the market maker(s) that the service will track
    for placing bets on Omen.
  - `BET_AMOUNT_PER_THRESHOLD_X`: amount (wei) to bet when the prediction returned by the AI Mech surpasses a threshold of `X`% confidence.
  - `BET_THRESHOLD`: minimum amount (wei) for placing a bet.

* Fetch the service

    ```bash
    autonomy fetch --local --service valory/trader && cd trader
    ```

* Build the image:

    ```bash
    autonomy build-image
    ```

* Prepare the agent keys for running the service with a single agent:

    ```bash
    cat > keys.json << EOF
    [
    {
        "address": "<your_agent_address>",
        "private_key": "<your_agent_private_key>"
    }
    ]
    EOF
    ```

  Please replace with your agent's address and private key in the command above.

* Build the deployment with a single agent and run:

    ```bash
    autonomy deploy build --n 1 -ltm
    autonomy deploy run --build-dir abci_build/
    ```
