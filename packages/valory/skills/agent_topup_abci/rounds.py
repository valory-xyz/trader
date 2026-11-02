# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""This module contains the rounds for the agent top-up ABCI application."""

from abc import ABC
from enum import Enum
from typing import Dict, Optional, Set, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    CollectionRound,
    DegenerateRound,
    DeserializedCollection,
    get_name,
)
from packages.valory.skills.agent_topup_abci.payloads import AgentTopUpPayload
from packages.valory.skills.transaction_settlement_abci.rounds import (
    SynchronizedData as TxSettlementSyncedData,
)


class Event(Enum):
    """Event enumeration for the agent top-up skill."""

    DONE = "done"
    PREPARE_TX = "prepare_tx"
    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"


class SynchronizedData(TxSettlementSyncedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def tx_submitter(self) -> str:
        """Get the round that submitted a tx to transaction_settlement_abci."""
        return str(self.db.get_strict("tx_submitter"))

    @property
    def participant_to_topup(self) -> DeserializedCollection:
        """Get the participants to the agent top-up round."""
        serialized = self.db.get_strict("participant_to_topup")
        return CollectionRound.deserialize_collection(serialized)


class AgentTopUpRound(CollectSameUntilThresholdRound):
    """A round that prepares the next Agent Safe to Agent Signer top-up tx, if one is due."""

    payload_class = AgentTopUpPayload
    done_event: Enum = Event.PREPARE_TX
    none_event: Enum = Event.DONE
    no_majority_event: Enum = Event.NO_MAJORITY
    selection_key = (
        get_name(SynchronizedData.tx_submitter),
        get_name(SynchronizedData.most_voted_tx_hash),
    )
    collection_key = get_name(SynchronizedData.participant_to_topup)
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        last_submitter = synced_data.db.get(
            get_name(SynchronizedData.tx_submitter), None
        )
        if event == Event.DONE and last_submitter == self.auto_round_id():
            # The check is over, so a later failure in this period is not a top-up one.
            return (
                synced_data.update(
                    synchronized_data_class=SynchronizedData,
                    tx_submitter=FinishedAgentTopUpRound.auto_round_id(),
                ),
                Event.DONE,
            )
        return res


class AgentTopUpTxPreparedRound(DegenerateRound, ABC):
    """A round that represents a top-up Safe tx has been prepared for settlement."""


class FinishedAgentTopUpRound(DegenerateRound, ABC):
    """A round that represents the top-up check has finished."""


class AgentTopUpAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """AgentTopUpAbciApp

    Initial round: AgentTopUpRound

    Initial states: {AgentTopUpRound}

    Transition states:
        0. AgentTopUpRound
            - done: 2.
            - prepare tx: 1.
            - no majority: 0.
            - round timeout: 0.
        1. AgentTopUpTxPreparedRound
        2. FinishedAgentTopUpRound

    Final states: {AgentTopUpTxPreparedRound, FinishedAgentTopUpRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = AgentTopUpRound
    transition_function: AbciAppTransitionFunction = {
        AgentTopUpRound: {
            Event.DONE: FinishedAgentTopUpRound,
            Event.PREPARE_TX: AgentTopUpTxPreparedRound,
            Event.NO_MAJORITY: AgentTopUpRound,
            Event.ROUND_TIMEOUT: AgentTopUpRound,
        },
        AgentTopUpTxPreparedRound: {},
        FinishedAgentTopUpRound: {},
    }
    final_states: Set[AppState] = {
        AgentTopUpTxPreparedRound,
        FinishedAgentTopUpRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {AgentTopUpRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        AgentTopUpTxPreparedRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedAgentTopUpRound: set(),
    }
