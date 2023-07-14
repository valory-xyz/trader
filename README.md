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
    export RPC_1=INSERT_YOUR_RPC
    export RPC_2=INSERT_YOUR_RPC
    export RPC_3=INSERT_YOUR_RPC
    export CHAIN_ID=100
    export ALL_PARTICIPANTS='["YOUR_AGENT_ADDRESS"]'
    export SAFE_CONTRACT_ADDRESS="YOUR_SAFE_ADDRESS"
    export OMEN_CREATORS='["CREATOR_0", "CREATOR_1", ...]'
    ```
  Please substitute the above placeholders with their respective actual values:
- Replace `RPC_i` with the RPC endpoint per agent.
- Replace `CHAIN_ID` with the identifier of the chain on which the service is running.
- Replace `ALL_PARTICIPANTS` with a list of the actual addresses of the service's participants. 
  This demo is for running the service with a single agent. 
  In case you want to run it with more agents, please edit the keys generation command below, 
  and replace the `--n 1` argument in the `build` command with the number of your agents.
- Replace `SAFE_CONTRACT_ADDRESS` with the specific address of the agents' multisig wallet.
- Replace `OMEN_CREATORS` with the relevant addresses of the creators that the service will track 
  for placing bets on Omen.

* Fetch the service
    ```
    autonomy fetch --local --service valory/trader && cd trader
    ```

* Build the image:
    ```
    autonomy build-image
    ```

* Prepare the agent keys for running the service with a single agent:
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
  Please replace with your agent's address and private key in the command above.
* Build the deployment with a single agent and run:
    ```
    autonomy deploy build --n 1 -ltm
    autonomy deploy run --build-dir abci_build/
    ```
