# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""This module contains the information about the rounds that is used by the Decision Maker Http handler."""

from pathlib import Path
from typing import Dict

import yaml
from aea.protocols.generator.common import _camel_case_to_snake_case


ROUNDS_INFO = {
    "benchmarking_randomness_round": {
        "name": "Gathering randomness in benchmarking mode",
        "description": "Introduces randomness so the agent can run realistic benchmarking tests.",
        "transitions": {},
    },
    "bet_placement_round": {
        "name": "Placing a bet",
        "description": "Attempts to place a bet on a prediction market.",
        "transitions": {},
    },
    "blacklisting_round": {
        "name": "Blacklisting the sampled bet",
        "description": "Removes the selected bet from consideration and updates the list of available bets.",
        "transitions": {},
    },
    "call_checkpoint_round": {
        "name": "Checking reward status",
        "description": "Verifies if the agent meets the conditions to earn staking rewards.",
        "transitions": {},
    },
    "check_benchmarking_mode_round": {
        "name": "Checking if the benchmarking mode is enabled",
        "description": "Verifies whether the benchmarking mode is active.",
        "transitions": {},
    },
    "check_late_tx_hashes_round": {
        "name": "Reviewing pending actions",
        "description": "Checks whether past actions on-chain have finished processing.",
        "transitions": {},
    },
    "check_stop_trading_round": {
        "name": "Checking if trading should stop",
        "description": "The agent checks its KPIs to decide whether to pause placing new bets.",
        "transitions": {},
    },
    "check_transaction_history_round": {
        "name": "Reviewing activity history",
        "description": "Looks at previous transactions to confirm whether they were completed.",
        "transitions": {},
    },
    "collect_signature_round": {
        "name": "Signing a transaction",
        "description": "Signs the transaction so it can be submitted to the network.",
        "transitions": {},
    },
    "decision_receive_round": {
        "name": "Making a prediction",
        "description": "The agent reviews the information it received to make its prediction for the bet.",
        "transitions": {},
    },
    "decision_request_round": {
        "name": "Requesting bet outcome",
        "description": "Requests external information needed to determine the answer to a bet.",
        "transitions": {},
    },
    "failed_multiplexer_round": {
        "name": "Handling a system error",
        "description": "Handles a situation where the agent could not choose the next step.",
        "transitions": {},
    },
    "finalization_round": {
        "name": "Completing the action",
        "description": "Finishes the signing and preparation of the submitted action.",
        "transitions": {},
    },
    "handle_failed_tx_round": {
        "name": "Handling a failed transaction",
        "description": "Responds to a transaction that was not successfully processed.",
        "transitions": {},
    },
    "impossible_round": {
        "name": "Unable to decide",
        "description": "The agent cannot determine a bet’s outcome with the available data.",
        "transitions": {},
    },
    "mech_request_round": {
        "name": "Requesting outcome data",
        "description": "Asks an external service for information needed to resolve a bet.",
        "transitions": {},
    },
    "mech_purchase_subscription_round": {
        "name": "Preparing subscription purchase",
        "description": "Prepares a purchase needed for accessing external data services.",
        "transitions": {},
    },
    "mech_response_round": {
        "name": "Receiving outcome data",
        "description": "Collects outcome information from the external service.",
        "transitions": {},
    },
    "polymarket_bet_placement_round": {
        "name": "Placing a bet on Polymarket",
        "description": "Attempts to place a bet on a Polymarket prediction market.",
        "transitions": {},
    },
    "polymarket_set_approval_round": {
        "name": "Setting approval on Polymarket",
        "description": "Attempts to set approval on a Polymarket prediction market.",
        "transitions": {},
    },
    "polymarket_post_set_approval_round": {
        "name": "Post setting approval on Polymarket",
        "description": "Attempts to finalize the approval setting on a Polymarket prediction market.",
        "transitions": {},
    },
    "post_tx_settlement_round": {
        "name": "Finalizing transaction settlement",
        "description": "Finalizes the transaction settlement",
        "transitions": {},
    },
    "pre_tx_settlement_round": {
        "name": "Preparing settlement",
        "description": "Ensures everything is ready before finalizing a transaction.",
        "transitions": {},
    },
    "randomness_round": {
        "name": "Gathering randomness",
        "description": "Adds a bit of natural variation that helps the agent choose which tools to use next.",
        "transitions": {},
    },
    "randomness_transaction_submission_round": {
        "name": "Generating randomness",
        "description": "Generates randomness.",
        "transitions": {},
    },
    "redeem_round": {
        "name": "Preparing a redeem transaction",
        "description": "Prepares a transaction to redeem winnings from a resolved bet.",
        "transitions": {},
    },
    "registration_round": {
        "name": "Registering an agent",
        "description": "Gets the agent ready and waits for enough agents to join the system.",
        "transitions": {},
    },
    "registration_startup_round": {
        "name": "Starting up",
        "description": "Sets up the necessary components the agent needs to operate.",
        "transitions": {},
    },
    "reset_and_pause_round": {
        "name": "Taking a short break",
        "description": "Cleans up temporary data and pauses briefly before continuing.",
        "transitions": {},
    },
    "reset_round": {
        "name": "Resetting",
        "description": "Resets the agent before moving to the next step.",
        "transitions": {},
    },
    "sampling_round": {
        "name": "Sampling a bet",
        "description": "Selects a potential bet for the agent to consider.",
        "transitions": {},
    },
    "select_keeper_transaction_submission_a_round": {
        "name": "Enabling agent to send the transaction",
        "description": "Aligns agent components for transaction submission.",
        "transitions": {},
    },
    "select_keeper_transaction_submission_b_after_timeout_round": {
        "name": "Enabling agent to send the transaction",
        "description": "Aligns agent components for transaction submission.",
        "transitions": {},
    },
    "select_keeper_transaction_submission_b_round": {
        "name": "Enabling agent to send the transaction",
        "description": "Aligns agent components for transaction submission.",
        "transitions": {},
    },
    "sell_outcome_tokens_round": {
        "name": "Selling tokens of unresolved bets",
        "description": "The agent sells its tokens before resolution to manage risk.",
        "transitions": {},
    },
    "service_evicted_round": {
        "name": "Stopping the agent",
        "description": "Stops the agent if it has been removed from eligibility for staking rewards.",
        "transitions": {},
    },
    "synchronize_late_messages_round": {
        "name": "Syncing messages",
        "description": "Processes any messages or updates that arrived late.",
        "transitions": {},
    },
    "tool_selection_round": {
        "name": "Choosing the tool used for making a prediction",
        "description": "Selects which external tool to use for determining a bet’s outcome.",
        "transitions": {},
    },
    "update_bets_round": {
        "name": "Updating bet list",
        "description": "Retrieves the latest market information and updates available bets.",
        "transitions": {},
    },
    "validate_transaction_round": {
        "name": "Validating a transaction",
        "description": "Checks whether a submitted transaction has completed successfully.",
        "transitions": {},
    },
    "chatui_load_round": {
        "name": "Loading ChatUI configuration",
        "description": "Loads configuration for the agent’s chat interface.",
        "transitions": {},
    },
    "fetch_performance_data_round": {
        "name": "Fetching agent performance data",
        "description": "Retrieves the latest performance statistics for the agent.",
        "transitions": {},
    },
    "redeem_router_round": {
        "name": "Deciding between redeem tools",
        "description": "A round for switching between Omen and Polymarket redeem rounds.",
        "transitions": {},
    },
    "polymarket_redeem_round": {
        "name": "Redeeming winnings from Polymarket",
        "description": "Redeems winnings from resolved Polymarket bets.",
        "transitions": {},
    },
    "fetch_markets_router_round": {
        "name": "Routing to market fetching logic",
        "description": "Routes between Omen and Polymarket market fetching based on configuration.",
        "transitions": {},
    },
    "polymarket_fetch_market_round": {
        "name": "Fetching Polymarket markets",
        "description": "Fetches multiple markets from Polymarket using category tags with filtering.",
        "transitions": {},
    },
    "polymarket_swap_usdc_round": {
        "name": "Swapping POL to USDC for placing mech requests",
        "description": "Swaps POL tokens to USDC tokens",
        "transitions": {},
    },
}


def load_fsm_spec() -> Dict:
    """Load the chained FSM spec"""
    with open(
        Path(__file__).parent.parent / "trader_abci" / "fsm_specification.yaml",
        "r",
        encoding="utf-8",
    ) as spec_file:
        return yaml.safe_load(spec_file)


def load_rounds_info_with_transitions() -> Dict:
    """Load the rounds info with the transitions"""

    fsm = load_fsm_spec()

    rounds_info_with_transitions: Dict = ROUNDS_INFO
    for source_info, target_round in fsm["transition_func"].items():
        # Removes the brackets from the source info tuple and splits it into round and event
        source_round, event = source_info[1:-1].split(", ")
        rounds_info_with_transitions[_camel_case_to_snake_case(source_round)][
            "transitions"
        ][event.lower()] = _camel_case_to_snake_case(target_round)

    return rounds_info_with_transitions
