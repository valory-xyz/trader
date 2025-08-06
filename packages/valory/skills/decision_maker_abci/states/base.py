# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""This module contains the base functionality for the rounds of the decision-making abci app."""

import json
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    DeserializedCollection,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.market_manager_abci.rounds import (
    SynchronizedData as MarketManagerSyncedData,
)
from packages.valory.skills.mech_interact_abci.states.base import (
    MechInteractionResponse,
    MechMetadata,
)
from packages.valory.skills.staking_abci.rounds import StakingState
from packages.valory.skills.transaction_settlement_abci.rounds import (
    SynchronizedData as TxSettlementSyncedData,
)


class Event(Enum):
    """Event enumeration for the price estimation demo."""

    DONE = "done"
    DONE_SELL = "done_sell"
    DONE_NO_SELL = "done_no_sell"
    NONE = "none"
    BENCHMARKING_ENABLED = "benchmarking_enabled"
    BENCHMARKING_DISABLED = "benchmarking_disabled"
    BENCHMARKING_FINISHED = "benchmarking_finished"
    MOCK_MECH_REQUEST = "mock_mech_request"
    MOCK_TX = "mock_tx"
    MECH_RESPONSE_ERROR = "mech_response_error"
    SLOTS_UNSUPPORTED_ERROR = "slots_unsupported_error"
    TIE = "tie"
    UNPROFITABLE = "unprofitable"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    CALC_BUY_AMOUNT_FAILED = "calc_buy_amount_failed"
    CALC_SELL_AMOUNT_FAILED = "calc_sell_amount_failed"
    NO_REDEEMING = "no_redeeming"
    BLACKLIST = "blacklist"
    NO_OP = "no_op"
    SUBSCRIPTION_ERROR = "subscription_error"
    NO_SUBSCRIPTION = "no_subscription"
    ROUND_TIMEOUT = "round_timeout"
    REDEEM_ROUND_TIMEOUT = "redeem_round_timeout"
    NO_MAJORITY = "no_majority"
    NEW_SIMULATED_RESAMPLE = "new_simulated_resample"


class SynchronizedData(MarketManagerSyncedData, TxSettlementSyncedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def sampled_bet_index(self) -> int:
        """Get the sampled bet."""
        return int(self.db.get_strict("sampled_bet_index"))

    @property
    def benchmarking_finished(self) -> bool:
        """Get the flag of benchmarking finished."""
        return bool(self.db.get_strict("benchmarking_finished"))

    @property
    def simulated_day(self) -> bool:
        """Get the flag of simulated_day."""
        return bool(self.db.get_strict("simulated_day"))

    @property
    def is_mech_price_set(self) -> bool:
        """Get whether mech's price is known."""
        return bool(self.db.get("mech_price", False))

    @property
    def available_mech_tools(self) -> List[str]:
        """Get all the available mech tools."""
        tools = self.db.get_strict("available_mech_tools")
        return json.loads(tools)

    @property
    def is_policy_set(self) -> bool:
        """Get whether the policy is set."""
        return bool(self.db.get("policy", False))

    @property
    def policy(self) -> EGreedyPolicy:
        """Get the policy."""
        policy = self.db.get_strict("policy")
        return EGreedyPolicy.deserialize(policy)

    @property
    def has_tool_selection_run(self) -> bool:
        """Get whether the tool selection has run."""
        mech_tool = self.db.get("mech_tool", None)
        return mech_tool is not None

    @property
    def mech_tool(self) -> str:
        """Get the selected mech tool."""
        return str(self.db.get_strict("mech_tool"))

    @property
    def utilized_tools(self) -> Dict[str, str]:
        """Get a mapping of the utilized tools' indexes for each transaction."""
        tools = str(self.db.get_strict("utilized_tools"))
        return json.loads(tools)

    @property
    def redeemed_condition_ids(self) -> Set[str]:
        """Get the condition ids of all the redeemed positions."""
        ids = self.db.get("redeemed_condition_ids", None)
        if ids is None:
            return set()
        return set(json.loads(ids))

    @property
    def payout_so_far(self) -> int:
        """Get the payout of all the redeemed positions so far."""
        payout = self.db.get("payout_so_far", None)
        if payout is None:
            return 0
        return int(payout)

    @property
    def vote(self) -> Optional[int]:
        """Get the bet's vote index."""
        vote = self.db.get_strict(
            "vote"
        )  # vote might be set to None, but must always present
        return int(vote) if vote is not None else None

    @property
    def previous_vote(self) -> Optional[int]:
        """Get the bet's previous vote index."""
        previous_vote = self.db.get_strict(
            "previous_vote"
        )  # previous_vote might be set to None, but must always present
        return int(previous_vote) if previous_vote is not None else None

    @property
    def review_bets_for_selling(self) -> bool:
        """Get the status of the review bets for selling."""
        db_value = self.db.get("review_bets_for_selling", None)
        if not isinstance(db_value, bool):
            return False
        return bool(db_value)

    @property
    def confidence(self) -> float:
        """Get the vote's confidence."""
        return float(self.db.get_strict("confidence"))

    @property
    def bet_amount(self) -> int:
        """Get the calculated bet amount."""
        return int(self.db.get_strict("bet_amount"))

    @property
    def weighted_accuracy(self) -> float:
        """Get the weighted accuracy of the selected tool."""
        tool_name = self.mech_tool
        store_tools = set(self.policy.weighted_accuracy.keys())
        if tool_name not in store_tools:
            raise ValueError(
                f"The tool {tool_name} was selected but it is not available in the policy!"
            )
        return self.policy.weighted_accuracy[tool_name]

    @property
    def is_profitable(self) -> bool:
        """Get whether the current vote is profitable or not."""
        return bool(self.db.get_strict("is_profitable"))

    @property
    def did_transact(self) -> bool:
        """Get whether the service performed any transactions in the current period."""
        return bool(self.db.get("tx_submitter", None))

    @property
    def tx_submitter(self) -> str:
        """Get the round that submitted a tx to transaction_settlement_abci."""
        return str(self.db.get_strict("tx_submitter"))

    @property
    def participant_to_decision(self) -> DeserializedCollection:
        """Get the participants to decision-making."""
        return self._get_deserialized("participant_to_decision")

    @property
    def participant_to_tx_prep(self) -> DeserializedCollection:
        """Get the participants to bet-placement."""
        return self._get_deserialized("participant_to_tx_prep")

    @property
    def participant_to_handle_failed_tx(self) -> DeserializedCollection:
        """Get the participants to `HandleFailedTxRound`."""
        return self._get_deserialized("participant_to_handle_failed_tx")

    @property
    def agreement_id(self) -> str:
        """Get the agreement id."""
        return str(self.db.get_strict("agreement_id"))

    @property
    def claim(self) -> bool:
        """Get the claim."""
        return bool(self.db.get_strict("claim"))

    @property
    def mech_price(self) -> int:
        """Get the mech's request price."""
        return int(self.db.get_strict("mech_price"))

    @property
    def mech_requests(self) -> List[MechMetadata]:
        """Get the mech requests."""
        serialized = self.db.get("mech_requests", "[]")
        if serialized is None:
            serialized = "[]"
        requests = json.loads(serialized)
        return [MechMetadata(**metadata_item) for metadata_item in requests]

    @property
    def mocking_mode(self) -> Optional[bool]:
        """Get whether the mocking mode should be enabled."""
        mode = self.db.get_strict("mocking_mode")
        if mode is None:
            return None
        return bool(mode)

    @property
    def next_mock_data_row(self) -> int:
        """Get the next_mock_data_row."""
        next_mock_data_row = self.db.get("next_mock_data_row", 1)
        if next_mock_data_row is None:
            return 1
        return int(next_mock_data_row)

    @property
    def mech_responses(self) -> List[MechInteractionResponse]:
        """Get the mech responses."""
        serialized = self.db.get("mech_responses", "[]")
        if serialized is None:
            serialized = "[]"
        responses = json.loads(serialized)
        return [MechInteractionResponse(**response_item) for response_item in responses]

    @property
    def wallet_balance(self) -> int:
        """Get the balance of the wallet."""
        wallet_balance = self.db.get("wallet_balance", 0)
        if wallet_balance is None:
            return 0
        return int(wallet_balance)

    @property
    def decision_receive_timestamp(self) -> int:
        """Get the timestamp of the mech decision."""
        decision_receive_timestamp = self.db.get("decision_receive_timestamp", 0)
        if decision_receive_timestamp is None:
            return 0
        return int(decision_receive_timestamp)

    @property
    def is_staking_kpi_met(self) -> bool:
        """Get the status of the staking kpi."""
        return bool(self.db.get("is_staking_kpi_met", False))

    @property
    def service_staking_state(self) -> StakingState:
        """Get the service's staking state."""
        return StakingState(self.db.get("service_staking_state", 0))

    @property
    def after_bet_attempt(self) -> bool:
        """Get the service's staking state."""
        return bool(self.db.get("after_bet_attempt", False))

    @property
    def should_be_sold(self) -> bool:
        """Get the flag of should_be_sold."""
        db_value = self.db.get("should_be_sold", None)
        if not isinstance(db_value, bool):
            return False
        return bool(db_value)


class TxPreparationRound(CollectSameUntilThresholdRound):
    """A round for preparing a transaction."""

    payload_class = MultisigTxPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key: Tuple[str, ...] = (
        get_name(SynchronizedData.tx_submitter),
        get_name(SynchronizedData.most_voted_tx_hash),
        get_name(SynchronizedData.mocking_mode),
    )
    collection_key = get_name(SynchronizedData.participant_to_tx_prep)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        if event == Event.DONE and synced_data.mocking_mode:
            return synced_data, Event.MOCK_TX

        return res
