## Trader

Trader is an autonomous service that performs bets on existing prediction markets. The service roughly works as follows:

1. Retrieve information on existing prediction markets that fulfill specific conditions, such as markets created by designated addresses.
2. Utilize a sampling strategy to select one of the markets for predicting its outcome.
3. Send a request to an [AI Mech](https://github.com/valory-xyz/mech) to assess the probabilities of the market's answers and obtain confidence values for the estimates.
4. If the response from the [AI Mech](https://github.com/valory-xyz/mech) meets certain criteria indicating profitability, the service will place a bet on that market. The betting amount can be adjusted based on the confidence level provided by the AI Mech.
5. In case the bet is deemed unprofitable, the market will be blacklisted for a configurable duration.
6. Repeat the aforementioned steps in a cyclic manner.

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
  - `OMEN_CREATORS`: addresses of the market creator(s) that the service will track
    for placing bets on Omen.
  - `BET_AMOUNT_PER_THRESHOLD_X`: amount (wei) to bet when the prediction returned by the AI Mech surpasses a threshold of `X`% confidence.
  - `BET_THRESHOLD`: minimum amount (wei) for placing a bet, after calculating the profit.

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
