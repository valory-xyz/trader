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

## Testing the service against Gnosis Mainnet

- Prepare some environment variables:

    ```bash
    export RPC_0=INSERT_YOUR_RPC

    export CHAIN_ID=100
    export ALL_PARTICIPANTS='["YOUR_AGENT_ADDRESS"]'
    export SAFE_CONTRACT_ADDRESS="YOUR_SAFE_ADDRESS"
    export OMEN_CREATORS='["CREATOR_0", "CREATOR_1", ...]'

    # Optional. The following example values bet a variable amount depending on the
    # prediction confidence. Here, amounts vary between 0.03 xDAI (60% confidence)
    # and 0.1 xDAI (100% confidence). Please, adjust these values accordingly.
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

    # Threshold for placing a bet 0.005 xDAI
    export BET_THRESHOLD=5000000000000000

    export PROMPT_TEMPLATE='With the given question "@{question}" and the `yes` option represented by `@{yes}` and the `no` option represented by `@{no}`, what are the respective probabilities of `p_yes` and `p_no` occurring?'
    ```

  Replace the above placeholders with their respective actual values:
  - `RPC_0`: RPC endpoint for the agent (you can get an RPC endpoint, e.g. [here](https://getblock.io/)).
  - `CHAIN_ID`: identifier of the chain on which the service is running.
  - `ALL_PARTICIPANTS`: list of all the agent addresses participating in the service.
    You need to obtain at least one Gnosis address to associate it with an agent of the service.
    This demo is for running the service with a single agent.
    In case you want to run it with more agents, please obtain more addresses, edit the keys' generation command below,
    and replace the `--n 1` argument in the `autonomy deploy build` command below with the number of your agents.
  - `SAFE_CONTRACT_ADDRESS`: address of the agents' multisig wallet \*.
  - `OMEN_CREATORS`: addresses of the market creator(s) that the service will track
    for placing bets on Omen.
  - `BET_AMOUNT_PER_THRESHOLD_X`: amount (wei) to bet when the prediction returned by the AI Mech surpasses a threshold of `X`% confidence.
  - `BET_THRESHOLD`: threshold (wei) for placing a bet. That is, a bet will only be placed if `expected_return - bet_fees >= BET_THRESHOLD`. [See below](#some-notes-on-the-service).
  - `PROMPT_TEMPLATE`: prompt to be used with the prediction AI Mech. Please keep it as a single line including the placeholders `@{question}`, `@{yes}` and `@{no}`.

\* The trader agent runs as part of a **trader service**, 
which is an [autonomous service](https://docs.autonolas.network/open-autonomy/get_started/what_is_an_agent_service/) 
that is represented on-chain in the Autonolas protocol by a Safe multisig, 
corresponding to the variable `SAFE_CONTRACT_ADDRESS`. 
Follow the next steps to compute the **Safe address** corresponding to your agent address:

- Visit https://registry.olas.network/services/mint and connect to the Gnosis network. For this demo, we recommend connecting using a wallet with a Gnosis EOA account that you own.
- In the field *"Owner address"* input a Gnosis address for which you will be able to sign later using a supported wallet. If you want to use the address you are connected to, click on *"Prefill Address"*.
- Click on *"Generate Hash & File"* and enter the value corresponding to the `service/valory/trader/0.1.0` key in `packages.json`
- In the field *"Canonical agent Ids"* enter the number `12`
- In the field *"No. of slots to canonical agent Ids"* enter the number `1`
- In the field *"Cost of agent instance bond (wei)"* enter the number `10000000000000000`
- In the field *"Threshold"* enter the number `1`
- Press the *"Submit"* button. Your wallet will ask you to approve the transaction. Once the transaction is settled, you should see a message indicating that the service NFT has been minted successfully. You should also see that the service is in _Pre-Registration_ state.
- Next, you can navigate to https://registry.olas.network/services#my-services, select your service and go through the steps:
  1. Activate registration
  2. Register agents: here, you must use the same public key that you use in the `ALL_PARTICIPANTS` value.
  3. This is the last step. A transaction for the safe deployment is already prepared and needs to be executed.
- After completing the process you will be able to retrieve the value for the variable `SAFE_CONTRACT_ADDRESS` from the field *"Safe contract address"* as shown in an example below

<img src="/img/safe_address_screenshot.png" alt="Safe address field]" width="500"/>

- Fetch the service

    ```bash
    autonomy fetch --local --service valory/trader && cd trader
    ```

- Build the image:

    ```bash
    autonomy build-image
    ```

- Prepare the agent keys for running the service with a single agent:

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

- Build the deployment with a single agent and run:

    ```bash
    autonomy deploy build --n 1 -ltm
    autonomy deploy run --build-dir abci_build/
    ```

## Some notes on the service

Please take into consideration the following:

- If the service does not have enough funds for placing a bet, you will see an `Event.INSUFICIENT_FUNDS` in the service logs.
- If the service determines that a bet is not profitable (i.e., `expected_return - bet_fees < BET_THRESHOLD`), you will see an `Event.UNPROFITABLE` in the service logs, and the service will transition into the blacklisting round. This round blacklists a bet for a predetermined amount of time. This can be adjusted by using the `BLACKLISTING_DURATION` environment variable.
- For simplicity, the current implementation considers `expected_return = bet_amount`, although this calculation might be refined.
- When assigning `BET_THRESHOLD` take into consideration that fees (at the time of writing this guide) are in the range of 0.02 xDAI. See, for example, [here](https://api.thegraph.com/subgraphs/name/protofire/omen-xdai/graphql?query=%7B%0A++fixedProductMarketMakers%28%0A++++where%3A+%7B%0A++++++creator_in%3A+%5B%220x89c5cc945dd550BcFfb72Fe42BfF002429F46Fec%22%5D%2C%0A++++++outcomeSlotCount%3A+2%2C%0A++++++isPendingArbitration%3A+false%0A++++%7D%2C%0A++++orderBy%3A+creationTimestamp%0A++++orderDirection%3A+desc%0A++%29%7B%0A++++fee%0A++%7D%0A%7D). We urge you to keep an eye on these fees, as they might vary.
- The trader service can be run as a multi-agent system. If you want to explore this option, extra environment variables need to be defined, i.e. in the case of 4 agents

    ```bash
    export RPC_0=INSERT_YOUR_RPC
    export RPC_1=INSERT_YOUR_RPC
    export RPC_2=INSERT_YOUR_RPC
    export RPC_3=INSERT_YOUR_RPC
    export ALL_PARTICIPANTS='["AGENT_ADDRESS_0,AGENT_ADDRESS_1,AGENT_ADDRESS_2,AGENT_ADDRESS_3"]'
    ```
where   `RPC_i` is the RPC endpoint for agent `AGENT_ADDRESS_i`

