#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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
"""This module contains the rounds info for the 'decision_maker_abci' skill."""

ROUNDS_INFO = {
    "benchmarking_randomness_round": {
        "name": "Benchmarking Randomness Round",
        "description": "Gathers randomness in benchmarking mode",
        "transitions": {
            "done": "sampling_round",
            "none": "impossible_round",
            "no_majority": "benchmarking_randomness_round",
            "round_timeout": "benchmarking_randomness_round",
        },
    },
    "bet_placement_round": {
        "name": "Bet Placement Round",
        "description": "Attempting to place a bet on a market.",
        "transitions": {
            "calc_buy_amount_failed": "handle_failed_tx_round",
            "done": "pre_tx_settlement_round",
            "insufficient_balance": "reset_and_pause_round",
            "mock_tx": "redeem_round",
            "none": "impossible_round",
            "no_majority": "bet_placement_round",
            "round_timeout": "bet_placement_round",
        },
    },
    "blacklisting_round": {
        "name": "Blacklisting Round",
        "description": "Blacklisting the sampled bet and updates the bets.",
        "transitions": {
            "done": "redeem_round",
            "fetch_error": "impossible_round",
            "mock_tx": "redeem_round",
            "none": "impossible_round",
            "no_majority": "blacklisting_round",
            "round_timeout": "blacklisting_round",
        },
    },
    "call_checkpoint_round": {
        "name": "Call Checkpoint Round",
        "description": "Preparing to call the checkpoint",
        "transitions": {
            "done": "pre_tx_settlement_round",
            "next_checkpoint_not_reached_yet": "reset_and_pause_round",
            "no_majority": "call_checkpoint_round",
            "round_timeout": "call_checkpoint_round",
            "service_evicted": "service_evicted_round",
            "service_not_staked": "reset_and_pause_round",
        },
    },
    "check_benchmarking_mode_round": {
        "name": "Check Benchmarking Mode Round",
        "description": "Checking if the benchmarking mode is enabled.",
        "transitions": {
            "benchmarking_disabled": "update_bets_round",
            "benchmarking_enabled": "benchmarking_randomness_round",
            "done": "impossible_round",
            "none": "impossible_round",
            "no_majority": "check_benchmarking_mode_round",
            "round_timeout": "check_benchmarking_mode_round",
            "subscription_error": "impossible_round",
        },
    },
    "check_late_tx_hashes_round": {
        "name": "Check Late Tx Hashes Round",
        "description": "Checks the late transaction hashes to see if any of them have been validated",
        "transitions": {
            "check_late_arriving_message": "synchronize_late_messages_round",
            "check_timeout": "check_late_tx_hashes_round",
            "done": "post_tx_settlement_round",
            "negative": "handle_failed_tx_round",
            "none": "handle_failed_tx_round",
            "no_majority": "handle_failed_tx_round",
        },
    },
    "check_stop_trading_round": {
        "name": "Check Stop Trading Round",
        "description": "Checking if the conditions are met to stop trading",
        "transitions": {
            "done": "randomness_round",
            "none": "check_stop_trading_round",
            "no_majority": "check_stop_trading_round",
            "round_timeout": "check_stop_trading_round",
            "skip_trading": "redeem_round",
        },
    },
    "check_transaction_history_round": {
        "name": "Check Transaction History Round",
        "description": "Checks the transaction history to determine if any previous transactions have been validated",
        "transitions": {
            "check_late_arriving_message": "synchronize_late_messages_round",
            "check_timeout": "check_transaction_history_round",
            "done": "post_tx_settlement_round",
            "negative": "select_keeper_transaction_submission_b_round",
            "none": "handle_failed_tx_round",
            "no_majority": "check_transaction_history_round",
        },
    },
    "claim_round": {
        "name": "Claim Round",
        "description": "Prepares a claim transaction for the subscription the agent has purchased",
        "transitions": {
            "done": "tool_selection_round",
            "no_majority": "claim_round",
            "round_timeout": "claim_round",
            "subscription_error": "claim_round",
        },
    },
    "collect_signature_round": {
        "name": "Collect Signature Round",
        "description": "Signs a transaction",
        "transitions": {
            "done": "finalization_round",
            "no_majority": "reset_round",
            "round_timeout": "collect_signature_round",
        },
    },
    "decision_receive_round": {
        "name": "Decision Receive Round",
        "description": "Decides on the bet's answer based on mech response.",
        "transitions": {
            "done": "bet_placement_round",
            "mech_response_error": "blacklisting_round",
            "no_majority": "decision_receive_round",
            "round_timeout": "decision_receive_round",
            "tie": "blacklisting_round",
            "unprofitable": "blacklisting_round",
        },
    },
    "decision_request_round": {
        "name": "Decision Request Round",
        "description": "Prepares a mech request transaction to determine the answer to a bet",
        "transitions": {
            "done": "mech_request_round",
            "mock_mech_request": "decision_receive_round",
            "no_majority": "decision_request_round",
            "round_timeout": "decision_request_round",
            "slots_unsupported_error": "blacklisting_round",
        },
    },
    "failed_multiplexer_round": {
        "name": "Failed Multiplexer Round",
        "description": "Represents a failure in identifying the transmitter round",
        "transitions": {},
    },
    "finalization_round": {
        "name": "Finalization Round",
        "description": "Represents that the transaction signing has finished",
        "transitions": {
            "check_history": "check_transaction_history_round",
            "check_late_arriving_message": "synchronize_late_messages_round",
            "done": "validate_transaction_round",
            "finalization_failed": "select_keeper_transaction_submission_b_round",
            "finalize_timeout": "select_keeper_transaction_submission_b_after_timeout_round",
            "insufficient_funds": "select_keeper_transaction_submission_b_round",
        },
    },
    "handle_failed_tx_round": {
        "name": "Handle Failed Tx Round",
        "description": "Handles a failed transaction",
        "transitions": {
            "blacklist": "blacklisting_round",
            "no_majority": "handle_failed_tx_round",
            "no_op": "redeem_round",
        },
    },
    "impossible_round": {
        "name": "Impossible Round",
        "description": "Represents that it is impossible to reach a decision with the given parametrization",
        "transitions": {},
    },
    "mech_request_round": {
        "name": "Mech Request Round",
        "description": "Preforms a mech request to determine the answer of a bet",
        "transitions": {
            "done": "pre_tx_settlement_round",
            "no_majority": "mech_request_round",
            "round_timeout": "mech_request_round",
            "skip_request": "redeem_round",
        },
    },
    "mech_response_round": {
        "name": "Mech Response Round",
        "description": "Collects the responses from a Mech to determine the answer of a bet",
        "transitions": {
            "done": "decision_receive_round",
            "no_majority": "mech_response_round",
            "round_timeout": "handle_failed_tx_round",
        },
    },
    "post_tx_settlement_round": {
        "name": "Post Tx Settlement Round",
        "description": "Finished the transaction settlement",
        "transitions": {
            "bet_placement_done": "redeem_round",
            "mech_requesting_done": "mech_response_round",
            "redeeming_done": "call_checkpoint_round",
            "round_timeout": "post_tx_settlement_round",
            "staking_done": "reset_and_pause_round",
            "subscription_done": "claim_round",
            "unrecognized": "failed_multiplexer_round",
        },
    },
    "pre_tx_settlement_round": {
        "name": "Pre Tx Settlement Round",
        "description": "Ensures the pre transaction settlement checks have passed",
        "transitions": {
            "checks_passed": "randomness_transaction_submission_round",
            "no_majority": "pre_tx_settlement_round",
            "refill_required": "pre_tx_settlement_round",
            "round_timeout": "pre_tx_settlement_round",
        },
    },
    "randomness_round": {
        "name": "Randomness Round",
        "description": "Gathers randomness",
        "transitions": {
            "done": "sampling_round",
            "none": "impossible_round",
            "no_majority": "randomness_round",
            "round_timeout": "randomness_round",
        },
    },
    "randomness_transaction_submission_round": {
        "name": "Randomness Transaction Submission Round",
        "description": "Generates randomness",
        "transitions": {
            "done": "select_keeper_transaction_submission_a_round",
            "none": "randomness_transaction_submission_round",
            "no_majority": "randomness_transaction_submission_round",
            "round_timeout": "randomness_transaction_submission_round",
        },
    },
    "redeem_round": {
        "name": "Redeem Round",
        "description": "Prepares a transaction to redeem the winnings",
        "transitions": {
            "done": "pre_tx_settlement_round",
            "mock_tx": "sampling_round",
            "none": "impossible_round",
            "no_majority": "redeem_round",
            "no_redeeming": "call_checkpoint_round",
            "redeem_round_timeout": "call_checkpoint_round",
        },
    },
    "registration_round": {
        "name": "Registration Round",
        "description": "Registers the agents. Waits until the threshold is reached",
        "transitions": {
            "done": "check_benchmarking_mode_round",
            "no_majority": "registration_round",
        },
    },
    "registration_startup_round": {
        "name": "Registration Startup Round",
        "description": "Registers the agents. Waits until all agents have registered",
        "transitions": {"done": "check_benchmarking_mode_round"},
    },
    "reset_and_pause_round": {
        "name": "Reset And Pause Round",
        "description": "Cleans up and sleeps for some time before running again",
        "transitions": {
            "done": "check_benchmarking_mode_round",
            "no_majority": "reset_and_pause_round",
            "reset_and_pause_timeout": "reset_and_pause_round",
        },
    },
    "reset_round": {
        "name": "Reset Round",
        "description": "Cleans up and resets the agent",
        "transitions": {
            "done": "randomness_transaction_submission_round",
            "no_majority": "handle_failed_tx_round",
            "reset_timeout": "handle_failed_tx_round",
        },
    },
    "sampling_round": {
        "name": "Sampling Round",
        "description": "Samples a bet",
        "transitions": {
            "benchmarking_enabled": "tool_selection_round",
            "benchmarking_finished": "reset_and_pause_round",
            "done": "subscription_round",
            "fetch_error": "impossible_round",
            "new_simulated_resample": "sampling_round",
            "none": "redeem_round",
            "no_majority": "sampling_round",
            "round_timeout": "sampling_round",
        },
    },
    "select_keeper_transaction_submission_a_round": {
        "name": "Select Keeper Transaction Submission A Round",
        "description": "Selects a keeper for the transaction submission",
        "transitions": {
            "done": "collect_signature_round",
            "incorrect_serialization": "handle_failed_tx_round",
            "no_majority": "reset_round",
            "round_timeout": "select_keeper_transaction_submission_a_round",
        },
    },
    "select_keeper_transaction_submission_b_after_timeout_round": {
        "name": "Select Keeper Transaction Submission B After Timeout Round",
        "description": "Selects a new keeper for the transaction submission after a round timeout of the previous "
        "keeper",
        "transitions": {
            "check_history": "check_transaction_history_round",
            "check_late_arriving_message": "synchronize_late_messages_round",
            "done": "finalization_round",
            "incorrect_serialization": "handle_failed_tx_round",
            "no_majority": "reset_round",
            "round_timeout": "select_keeper_transaction_submission_b_after_timeout_round",
        },
    },
    "select_keeper_transaction_submission_b_round": {
        "name": "Select Keeper Transaction Submission B Round",
        "description": "Selects a new keeper for the transaction submission",
        "transitions": {
            "done": "finalization_round",
            "incorrect_serialization": "handle_failed_tx_round",
            "no_majority": "reset_round",
            "round_timeout": "select_keeper_transaction_submission_b_round",
        },
    },
    "service_evicted_round": {
        "name": "Service Evicted Round",
        "description": "Terminated the service if it has been evicted from the staking contract",
        "transitions": {},
    },
    "subscription_round": {
        "name": "Subscription Round",
        "description": "Purchases a subscription",
        "transitions": {
            "done": "pre_tx_settlement_round",
            "mock_tx": "tool_selection_round",
            "none": "subscription_round",
            "no_majority": "subscription_round",
            "no_subscription": "tool_selection_round",
            "round_timeout": "subscription_round",
            "subscription_error": "subscription_round",
        },
    },
    "synchronize_late_messages_round": {
        "name": "Synchronize Late Messages Round",
        "description": "Synchronizes any late arriving messages",
        "transitions": {
            "done": "check_late_tx_hashes_round",
            "none": "select_keeper_transaction_submission_b_round",
            "round_timeout": "synchronize_late_messages_round",
            "suspicious_activity": "handle_failed_tx_round",
        },
    },
    "tool_selection_round": {
        "name": "Tool Selection Round",
        "description": "Selects a Mech tool to use to determine the answer of a bet",
        "transitions": {
            "done": "decision_request_round",
            "none": "tool_selection_round",
            "no_majority": "tool_selection_round",
            "round_timeout": "tool_selection_round",
        },
    },
    "update_bets_round": {
        "name": "Update Bets Round",
        "description": "Fetching the bets and updates them with the latest information",
        "transitions": {
            "done": "check_stop_trading_round",
            "fetch_error": "reset_and_pause_round",
            "no_majority": "update_bets_round",
            "round_timeout": "update_bets_round",
        },
    },
    "validate_transaction_round": {
        "name": "Validate Transaction Round",
        "description": "Validates a transaction",
        "transitions": {
            "done": "post_tx_settlement_round",
            "negative": "check_transaction_history_round",
            "none": "select_keeper_transaction_submission_b_round",
            "no_majority": "validate_transaction_round",
            "validate_timeout": "check_transaction_history_round",
        },
    },
}
