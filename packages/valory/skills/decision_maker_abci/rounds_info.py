# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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
        "description": "Gathers randomness in benchmarking mode",
        "transitions": {},
    },
    "bet_placement_round": {
        "name": "Placing a bet",
        "description": "Attempting to place a bet on a market",
        "transitions": {},
    },
    "blacklisting_round": {
        "name": "Blacklisting the sampled bet",
        "description": "Blacklists the sampled bet and updates the bets",
        "transitions": {},
    },
    "call_checkpoint_round": {
        "name": "Preparing to call the checkpoint",
        "description": "Preparing to call the checkpoint",
        "transitions": {},
    },
    "check_benchmarking_mode_round": {
        "name": "Checking if the benchmarking mode is enabled",
        "description": "Checks if the benchmarking mode is enabled",
        "transitions": {},
    },
    "check_late_tx_hashes_round": {
        "name": "Checking the late transaction hashes",
        "description": "Checks the late transaction hashes to see if any of them have been validated",
        "transitions": {},
    },
    "check_stop_trading_round": {
        "name": "Checking if the agents should stop trading",
        "description": "Checking if the conditions are met to stop trading",
        "transitions": {},
    },
    "check_transaction_history_round": {
        "name": "Checking the transaction history",
        "description": "Checks the transaction history to determine if any previous transactions have been validated",
        "transitions": {},
    },
    "claim_round": {
        "name": "Preparing a claim transaction",
        "description": "Prepares a claim transaction for the subscription the agent has purchased",
        "transitions": {},
    },
    "collect_signature_round": {
        "name": "Signing a transaction",
        "description": "Signs a transaction",
        "transitions": {},
    },
    "decision_receive_round": {
        "name": "Deciding on the bet's answer",
        "description": "Decides on the bet's answer based on mech response.",
        "transitions": {},
    },
    "decision_request_round": {
        "name": "Preparing a mech request transaction",
        "description": "Prepares a mech request transaction to determine the answer to a bet",
        "transitions": {},
    },
    "failed_multiplexer_round": {
        "name": "Representing a failure in identifying the transmitter round",
        "description": "Represents a failure in identifying the transmitter round",
        "transitions": {},
    },
    "finalization_round": {
        "name": "Finalizing the transaction",
        "description": "Represents that the transaction signing has finished",
        "transitions": {},
    },
    "handle_failed_tx_round": {
        "name": "Handling a failed transaction",
        "description": "Handles a failed transaction",
        "transitions": {},
    },
    "impossible_round": {
        "name": "Impossible to reach a decision",
        "description": "Represents that it is impossible to reach a decision with the given parametrization",
        "transitions": {},
    },
    "mech_request_round": {
        "name": "Performing a request to a Mech",
        "description": "Preforms a mech request to determine the answer of a bet",
        "transitions": {},
    },
    "mech_response_round": {
        "name": "Collecting the responses from a Mech",
        "description": "Collects the responses from a Mech to determine the answer of a bet",
        "transitions": {},
    },
    "post_tx_settlement_round": {
        "name": "Finishing transaction settlement",
        "description": "Finished the transaction settlement",
        "transitions": {},
    },
    "pre_tx_settlement_round": {
        "name": "Ensuring the pre transaction settlement checks have passed",
        "description": "Ensures the pre transaction settlement checks have passed",
        "transitions": {},
    },
    "randomness_round": {
        "name": "Gathering randomness",
        "description": "Gathers randomness",
        "transitions": {},
    },
    "randomness_transaction_submission_round": {
        "name": "Generating randomness",
        "description": "Generates randomness",
        "transitions": {},
    },
    "redeem_round": {
        "name": "Preparing a redeem transaction",
        "description": "Prepares a transaction to redeem the winnings",
        "transitions": {},
    },
    "registration_round": {
        "name": "Registering an agent",
        "description": "Registers the agents. Waits until the threshold is reached",
        "transitions": {},
    },
    "registration_startup_round": {
        "name": "Registering the agents",
        "description": "Registers the agents. Waits until all agents have registered",
        "transitions": {},
    },
    "reset_and_pause_round": {
        "name": "Cleaning up and sleeping for some time",
        "description": "Cleans up and sleeps for some time before running again",
        "transitions": {},
    },
    "reset_round": {
        "name": "Cleaning up and resetting",
        "description": "Cleans up and resets the agent",
        "transitions": {},
    },
    "sampling_round": {
        "name": "Sampling a bet",
        "description": "Samples a bet",
        "transitions": {},
    },
    "select_keeper_transaction_submission_a_round": {
        "name": "Selecting a keeper",
        "description": "Selects a keeper for the transaction submission",
        "transitions": {},
    },
    "select_keeper_transaction_submission_b_after_timeout_round": {
        "name": "Selecting a new keeper",
        "description": "Selects a new keeper for the transaction submission after a round timeout of the previous keeper",
        "transitions": {},
    },
    "select_keeper_transaction_submission_b_round": {
        "name": "Selecting a new keeper",
        "description": "Selects a new keeper for the transaction submission",
        "transitions": {},
    },
    "sell_outcome_tokens_round": {
        "name": "Selling the outcome tokens",
        "description": "Sells the outcome tokens",
        "transitions": {},
    },
    "service_evicted_round": {
        "name": "Terminating the service",
        "description": "Terminated the service if it has been evicted from the staking contract",
        "transitions": {},
    },
    "subscription_round": {
        "name": "Ordering a subscription",
        "description": "Purchases a subscription",
        "transitions": {},
    },
    "synchronize_late_messages_round": {
        "name": "Synchronizing the late messages",
        "description": "Synchronizes any late arriving messages",
        "transitions": {},
    },
    "tool_selection_round": {
        "name": "Selecting a Mech tool",
        "description": "Selects a Mech tool to use to determine the answer of a bet",
        "transitions": {},
    },
    "update_bets_round": {
        "name": "Updating the bets",
        "description": "Fetching the bets and updates them with the latest information",
        "transitions": {},
    },
    "validate_transaction_round": {
        "name": "Validating a transaction",
        "description": "Validates a transaction",
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
