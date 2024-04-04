# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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
from typing import Dict, List, Optional, Set, Tuple

from packages.valory.skills.abstract_round_abci.base import (
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
from packages.valory.skills.transaction_settlement_abci.rounds import (
    SynchronizedData as TxSettlementSyncedData,
)


class Event(Enum):
    """Event enumeration for the price estimation demo."""

    DONE = "done"
    NONE = "none"
    MECH_RESPONSE_ERROR = "mech_response_error"
    SLOTS_UNSUPPORTED_ERROR = "slots_unsupported_error"
    TIE = "tie"
    UNPROFITABLE = "unprofitable"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    NO_REDEEMING = "no_redeeming"
    BLACKLIST = "blacklist"
    NO_OP = "no_op"
    SUBSCRIPTION_ERROR = "subscription_error"
    NO_SUBSCRIPTION = "no_subscription"
    ROUND_TIMEOUT = "round_timeout"
    REDEEM_ROUND_TIMEOUT = "redeem_round_timeout"
    NO_MAJORITY = "no_majority"


class SynchronizedData(MarketManagerSyncedData, TxSettlementSyncedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def sampled_bet_index(self) -> int:
        """Get the sampled bet."""
        return int(self.db.get_strict("sampled_bet_index"))

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
    def policy(self) -> EGreedyPolicy:
        """Get the policy."""
        policy = self.db.get_strict("policy")
        return EGreedyPolicy.deserialize(policy)

    @property
    def mech_tool_idx(self) -> int:
        """Get the mech tool's index."""
        return int(self.db.get_strict("mech_tool_idx"))

    @property
    def mech_tool(self) -> str:
        """Get the selected mech tool."""
        try:
            return self.available_mech_tools[self.mech_tool_idx]
        except IndexError as exc:
            error = f"{self.mech_tool_idx=} is not available in {self.available_mech_tools=}."
            raise IndexError(error) from exc

    @property
    def utilized_tools(self) -> Dict[str, int]:
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
        vote = self.db.get_strict("vote")
        return int(vote) if vote is not None else None

    @property
    def confidence(self) -> float:
        """Get the vote's confidence."""
        return float(self.db.get_strict("confidence"))

    @property
    def bet_amount(self) -> int:
        """Get the calculated bet amount."""
        return int(self.db.get_strict("bet_amount"))

    @property
    def is_profitable(self) -> bool:
        """Get whether the current vote is profitable or not."""
        return bool(self.db.get_strict("is_profitable"))

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
    def mech_responses(self) -> List[MechInteractionResponse]:
        """Get the mech responses."""
        serialized = self.db.get("mech_responses", "[]")
        if serialized is None:
            serialized = "[]"
        responses = json.loads(serialized)
        return [MechInteractionResponse(**response_item) for response_item in responses]

    @property
    def stop_trading(self) -> bool:
        """Get whether agent should stop trading."""
        return bool(self.db.get("stop_trading", False))


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
    )
    collection_key = get_name(SynchronizedData.participant_to_tx_prep)
