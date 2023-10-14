## Trader service

Trader is an autonomous service that performs **bets on existing prediction markets**. The service interacts with an [AI Mech](https://github.com/valory-xyz/mech) (a service that executes AI tasks), and its workflow is as follows:

1. Retrieve information on existing prediction markets (for example, markets created by a given address).
2. Select one of these markets for betting.
3. Send a request to an [AI Mech](https://github.com/valory-xyz/mech) to estimate the probability of the event referenced by the prediction market question, and what confidence the AI Mech has on that prediction.
    - The service will typically bet higher amounts for higher confidence predictions coming from the AI Mech.
    - These parameters are configurable.
4. If the response from the [AI Mech](https://github.com/valory-xyz/mech) meets certain criteria indicating profitability, the service will place a bet on that market. The betting amount can be adjusted based on the confidence level provided by the AI Mech.
5. In case the bet is deemed unprofitable, the market will be blacklisted for a configurable duration.
6. Repeat these steps continuously.

The Trader service is an [agent service](https://docs.autonolas.network/open-autonomy/get_started/what_is_an_agent_service/) (or autonomous service) based on the [Open Autonomy framework](https://docs.autonolas.network/open-autonomy/). Below we show you how to prepare your environment, how to prepare the agent keys, and how to configure and run the service.

## Prepare the environment

- System requirements:

  - Python `== 3.10`
  - [Poetry](https://python-poetry.org/docs/) `>=1.4.0`
  - [Docker Engine](https://docs.docker.com/engine/install/)
  - [Docker Compose](https://docs.docker.com/compose/install/)

- Clone this repository:

      git clone https://github.com/valory-xyz/trader.git

- Create a development environment:

      poetry install && poetry shell

- Configure the Open Autonomy framework:

      autonomy init --reset --author valory --remote --ipfs --ipfs-node "/dns/registry.autonolas.tech/tcp/443/https"

- Pull packages required to run the service:

      autonomy packages sync --update-packages

## Prepare the keys and the Safe

You need a **Gnosis keypair** and a **[Safe](https://safe.global/) address** to run the service.

First, prepare the `keys.json` file with the Gnosis keypair of your agent. (Replace the uppercase placeholders below):

    cat > keys.json << EOF
    [
    {
        "address": "YOUR_AGENT_ADDRESS",
        "private_key": "YOUR_AGENT_PRIVATE_KEY"
    }
    ]
    EOF

Next, prepare the [Safe](https://safe.global/). The trader agent runs as part of a **trader service**, 
which is an [autonomous service](https://docs.autonolas.network/open-autonomy/get_started/what_is_an_agent_service/) 
represented on-chain in the [Autonolas Protocol](https://docs.autonolas.network/protocol/) by a [Safe](https://safe.global/) multisig. Follow the next steps to obtain a **Safe address** corresponding to your agent address:

1. Visit https://registry.olas.network/services/mint and connect to the Gnosis network. We recommend connecting using a wallet with a Gnosis EOA account that you own.
2. Fill in the following fields:
    - *"Owner address"*: a Gnosis address for which you will be able to sign later using a supported wallet. If you want to use the address you are connected to, click on *"Prefill Address"*.
    - Click on *"Generate Hash & File"* and enter the value corresponding to the `service/valory/trader/0.1.0` key in [`packages.json`](https://github.com/valory-xyz/trader/blob/main/packages/packages.json)
    - *"Canonical agent Ids"*: enter the number `12`
    - *"No. of slots to canonical agent Ids"*: enter the number `1`
    - *"Cost of agent instance bond (wei)"*: enter the number `10000000000000000`
    - *"Threshold"*: enter the number `1`
3. Press the *"Submit"* button. Your wallet will ask you to approve the transaction. Once the transaction is settled, you should see a message indicating that the service NFT has been minted successfully. You should also see that the service is in _Pre-Registration_ state.
4. Next, you can navigate to https://registry.olas.network/services#my-services, select your service and go through the steps:
    1. Activate registration
    2. Register agents: **here, you must use your agent address**.
    3. This is the last step. A transaction for the Safe deployment is already prepared and needs to be executed.
5. After completing the process you should see that your service is **Deployed**, and you will be able to retrieve your **Safe contract address** as shown in the image below:

<img src="/img/safe_address_screenshot.png" alt="Safe address field" width="500"/>


**You need to provide some funds (XDAI) both to your agent address and to the Safe address in order to place bets on prediction markets.**

## Configure the service

Set up the following environment variables, which will modify the performance of the trading agent. **Please read their description below**. We provide some defaults, but feel free to experiment with different values. Note that you need to provide `YOUR_AGENT_ADDRESS` and `YOUR_SAFE_ADDRESS` from the section above.

```bash
export RPC_0=INSERT_YOUR_RPC
export CHAIN_ID=100

export ALL_PARTICIPANTS='["YOUR_AGENT_ADDRESS"]'
export SAFE_CONTRACT_ADDRESS="YOUR_SAFE_ADDRESS"
export OMEN_CREATORS='["0x89c5cc945dd550BcFfb72Fe42BfF002429F46Fec"]'

export BET_AMOUNT_PER_THRESHOLD_000=0
export BET_AMOUNT_PER_THRESHOLD_010=0
export BET_AMOUNT_PER_THRESHOLD_020=0
export BET_AMOUNT_PER_THRESHOLD_030=0
export BET_AMOUNT_PER_THRESHOLD_040=0
export BET_AMOUNT_PER_THRESHOLD_050=0
export BET_AMOUNT_PER_THRESHOLD_060=30000000000000000
export BET_AMOUNT_PER_THRESHOLD_070=40000000000000000
export BET_AMOUNT_PER_THRESHOLD_080=60000000000000000
export BET_AMOUNT_PER_THRESHOLD_090=80000000000000000
export BET_AMOUNT_PER_THRESHOLD_100=100000000000000000

export BET_THRESHOLD=5000000000000000

export PROMPT_TEMPLATE='With the given question "@{question}" and the `yes` option represented by `@{yes}` and the `no` option represented by `@{no}`, what are the respective probabilities of `p_yes` and `p_no` occurring?'
```

These are the description of the variables used by the Trader service:

- `RPC_0`: RPC endpoint for the agent (you can get an RPC endpoint, e.g. [here](https://getblock.io/)).
- `CHAIN_ID`: identifier of the chain on which the service is running (Gnosis=100).
- `ALL_PARTICIPANTS`: list of all the agent addresses participating in the service. In this example we only are using a single agent.
- `SAFE_CONTRACT_ADDRESS`: address of the agents multisig wallet created [in the previous section](#prepare-the-keys-and-the-safe).
- `OMEN_CREATORS`: addresses of the market creator(s) that the service will track
  for placing bets on Omen. The address `0x89c5cc945dd550BcFfb72Fe42BfF002429F46Fec` corresponds to the Market creator agent for the Hackathon.
- `BET_AMOUNT_PER_THRESHOLD_X`: amount (wei) to bet when the prediction returned by the AI Mech surpasses a threshold of `X`% confidence for a given prediction market. In the values provided above the amounts vary between 0.03 xDAI (60% confidence) and 0.1 xDAI (100% confidence).
- `BET_THRESHOLD`: threshold (wei) for placing a bet. A bet will only be placed if `potential_net_profit - BET_THRESHOLD >= 0`. [See below](#some-notes-on-the-service).
- `PROMPT_TEMPLATE`: prompt to be used with the prediction AI Mech. Please keep it as a single line including the placeholders `@{question}`, `@{yes}` and `@{no}`.


## Run the service
Once you have configured (exported) the environment variables, you are in position to run the service.

- Fetch the service:

    ```bash
    autonomy fetch --local --service valory/trader && cd trader
    ```

- Build the Docker image:

    ```bash
    autonomy build-image
    ```

- Copy your `keys.json` file prepared [in the previous section](#prepare-the-keys-and-the-safe) in the same directory:

    ```bash
    cp path/to/keys.json .
    ```

- Build the deployment with a single agent and run:

    ```bash
    autonomy deploy build --n 1 -ltm
    autonomy deploy run --build-dir abci_build/
    ```

## Some notes on the service

Please take into consideration the following:

- If the service does not have enough funds for placing a bet, you will see an `Event.INSUFICIENT_FUNDS` in the service logs.
- If the service determines that a bet is not profitable 
 (i.e., `potential_net_profit - BET_THRESHOLD < 0`), you will see an `Event.UNPROFITABLE` in the service logs, 
 and the service will transition into the blacklisting round. 
 This round blacklists a bet for a predetermined amount of time. 
 This can be adjusted by using the `BLACKLISTING_DURATION` environment variable.
- For simplicity, 
 the current implementation considers `potential_net_profit = num_shares - net_bet_amount - mech_price - BET_THRESHOLD`, 
 although this calculation might be refined. 
 The `net_bet_amount` is the bet amount minus the FPMM's fees.
- When assigning `BET_THRESHOLD` take into consideration that fees (at the time of writing this guide) are in the range of 0.02 xDAI. See, for example, [here](https://api.thegraph.com/subgraphs/name/protofire/omen-xdai/graphql?query=%7B%0A++fixedProductMarketMakers%28%0A++++where%3A+%7B%0A++++++creator_in%3A+%5B%220x89c5cc945dd550BcFfb72Fe42BfF002429F46Fec%22%5D%2C%0A++++++outcomeSlotCount%3A+2%2C%0A++++++isPendingArbitration%3A+false%0A++++%7D%2C%0A++++orderBy%3A+creationTimestamp%0A++++orderDirection%3A+desc%0A++%29%7B%0A++++fee%0A++%7D%0A%7D). We urge you to keep an eye on these fees, as they might vary.

## For advanced users

The trader service can be run as a multi-agent system. If you want to explore this option,
you need, for the case of 4 agents:

  - One `keys.json` file containing 4 addresses and keys.
  - Register these 4 keys in your service Safe as explained [in this section](#prepare-the-keys-and-the-safe).
  - Prepare extra environment variables need to be defined, including
    ```bash
    export RPC_0=INSERT_YOUR_RPC
    export RPC_1=INSERT_YOUR_RPC
    export RPC_2=INSERT_YOUR_RPC
    export RPC_3=INSERT_YOUR_RPC
    export ALL_PARTICIPANTS='["AGENT_ADDRESS_0,AGENT_ADDRESS_1,AGENT_ADDRESS_2,AGENT_ADDRESS_3"]'
    ```

    where   `RPC_i` is the RPC endpoint for agent `AGENT_ADDRESS_i`.

You can also explore the [`service.yaml`](https://github.com/valory-xyz/trader/blob/main/packages/valory/services/trader/service.yaml) file, which contains all the possible configuration variables for the service.

Finally, if you are experienced with the [Open Autonomy](https://docs.autonolas.network/) framework, you can also modify the internal business logic of the service yourself.
