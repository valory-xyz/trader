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


ROUNDS_INFO = {
    "BenchmarkingRandomnessRound": {
        "name": "Gathering randomness in benchmarking mode",
        "description": "Gathers randomness in benchmarking mode",
        "transitions": {}
    },
    "BetPlacementRound": {
        "name": "Placing a bet",
        "description": "Attempting to place a bet on a market",
        "transitions": {}
    },
    "BlacklistingRound": {
        "name": "Blacklisting the sampled bet",
        "description": "Blacklists the sampled bet and updates the bets",
        "transitions": {}
    },
    "CallCheckpointRound": {
        "name": "Preparing to call the checkpoint",
        "description": "Preparing to call the checkpoint",
        "transitions": {}
    },
    "CheckBenchmarkingModeRound": {
        "name": "Checking if the benchmarking mode is enabled",
        "description": "Checks if the benchmarking mode is enabled",
        "transitions": {}
    },
    "CheckLateTxHashesRound": {
        "name": "Checking the late transaction hashes",
        "description": "Checks the late transaction hashes to see if any of them have been validated",
        "transitions": {}
    },
    "CheckStopTradingRound": {
        "name": "Checking if the agents should stop trading",
        "description": "Checking if the conditions are met to stop trading",
        "transitions": {}
    },
    "CheckTransactionHistoryRound": {
        "name": "Checking the transaction history",
        "description": "Checks the transaction history to determine if any previous transactions have been validated",
        "transitions": {}
    },
    "ClaimRound": {
        "name": "Preparing a claim transaction",
        "description": "Prepares a claim transaction for the subscription the agent has purchased",
        "transitions": {}
    },
    "CollectSignatureRound": {
        "name": "Signing a transaction",
        "description": "Signs a transaction",
        "transitions": {}
    },
    "DecisionReceiveRound": {
        "name": "Deciding on the bet's answer",
        "description": "Decides on the bet's answer based on mech response.",
        "transitions": {}
    },
    "DecisionRequestRound": {
        "name": "Preparing a mech request transaction",
        "description": "Prepares a mech request transaction to determine the answer to a bet",
        "transitions": {}
    },
    "FailedMultiplexerRound": {
        "name": "Representing a failure in identifying the transmitter round",
        "description": "Represents a failure in identifying the transmitter round",
        "transitions": {}
    },
    "FinalizationRound": {
        "name": "Finalizing the transaction",
        "description": "Represents that the transaction signing has finished",
        "transitions": {}
    },
    "HandleFailedTxRound": {
        "name": "Handling a failed transaction",
        "description": "Handles a failed transaction",
        "transitions": {}
    },
    "ImpossibleRound": {
        "name": "Impossible to reach a decision",
        "description": "Represents that it is impossible to reach a decision with the given parametrization",
        "transitions": {}
    },
    "MechRequestRound": {
        "name": "Performing a request to a Mech",
        "description": "Preforms a mech request to determine the answer of a bet",
        "transitions": {}
    },
    "MechResponseRound": {
        "name": "Collecting the responses from a Mech",
        "description": "Collects the responses from a Mech to determine the answer of a bet",
        "transitions": {}
    },
    "PostTxSettlementRound": {
        "name": "Finishing transaction settlement",
        "description": "Finished the transaction settlement",
        "transitions": {}
    },
    "PreTxSettlementRound": {
        "name": "Ensuring the pre transaction settlement checks have passed",
        "description": "Ensures the pre transaction settlement checks have passed",
        "transitions": {}
    },
    "RandomnessRound": {
        "name": "Gathering randomness",
        "description": "Gathers randomness",
        "transitions": {}
    },
    "RandomnessTransactionSubmissionRound": {
        "name": "Generating randomness",
        "description": "Generates randomness",
        "transitions": {}
    },
    "RedeemRound": {
        "name": "Preparing a redeem transaction",
        "description": "Prepares a transaction to redeem the winnings",
        "transitions": {}
    },
    "RegistrationRound": {
        "name": "Registering an agent",
        "description": "Registers the agents. Waits until the threshold is reached",
        "transitions": {}
    },
    "RegistrationStartupRound": {
        "name": "Registering the agents",
        "description": "Registers the agents. Waits until all agents have registered",
        "transitions": {}
    },
    "ResetAndPauseRound": {
        "name": "Cleaning up and sleeping for some time",
        "description": "Cleans up and sleeps for some time before running again",
        "transitions": {},
    },
    "ResetRound": {
        "name": "Cleaning up and resetting",
        "description": "Cleans up and resets the agent",
        "transitions": {},
    },
    "SamplingRound": {
        "name": "Sampling a bet",
        "description": "Samples a bet",
        "transitions": {}
    },
    "SelectKeeperTransactionSubmissionARound": {
        "name": "Selecting a keeper",
        "description": "Selects a keeper for the transaction submission",
        "transitions": {}
    },
    "SelectKeeperTransactionSubmissionBAfterTimeoutRound": {
        "name": "Selecting a new keeper",
        "description": "Selects a new keeper for the transaction submission after a round timeout of the previous keeper",
        "transitions": {}
    },
    "SelectKeeperTransactionSubmissionBRound": {
        "name": "Selecting a new keeper",
        "description": "Selects a new keeper for the transaction submission",
        "transitions": {}
    },
    "ServiceEvictedRound": {
        "name": "Terminating the service",
        "description": "Terminated the service if it has been evicted from the staking contract",
        "transitions": {}
    },
    "SubscriptionRound": {
        "name": "Ordering a subscription",
        "description": "Purchases a subscription",
        "transitions": {}
    },
    "SynchronizeLateMessagesRound": {
        "name": "Synchronizing the late messages",
        "description": "Synchronizes any late arriving messages",
        "transitions": {}
    },
    "ToolSelectionRound": {
        "name": "Selecting a Mech tool",
        "description": "Selects a Mech tool to use to determine the answer of a bet",
        "transitions": {}
    },
    "UpdateBetsRound": {
        "name": "Updating the bets",
        "description": "Fetching the bets and updates them with the latest information",
        "transitions": {}
    },
    "ValidateTransactionRound": {
        "name": "Validating a transaction",
        "description": "Validates a transaction",
        "transitions": {}
    }
}
