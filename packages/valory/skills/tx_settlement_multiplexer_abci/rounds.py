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

"""This package contains the rounds of `TxSettlementMultiplexerAbciApp`."""

import json
from enum import Enum
from typing import Any, Dict, Optional, Set, Tuple

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    DegenerateRound,
    NONE_EVENT_ATTRIBUTE,
    VotingRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.order_subscription import (
    SubscriptionRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.mech_interact_abci.states.request import MechRequestRound
from packages.valory.skills.staking_abci.rounds import CallCheckpointRound


class Event(Enum):
    """Multiplexing events."""

    CHECKS_PASSED = "checks_passed"
    REFILL_REQUIRED = "refill_required"
    MECH_REQUESTING_DONE = "mech_requesting_done"
    BET_PLACEMENT_DONE = "bet_placement_done"
    SELL_OUTCOME_TOKENS_DONE = "sell_outcome_tokens_done"
    REDEEMING_DONE = "redeeming_done"
    STAKING_DONE = "staking_done"
    SUBSCRIPTION_DONE = "subscription_done"
    ROUND_TIMEOUT = "round_timeout"
    UNRECOGNIZED = "unrecognized"
    NO_MAJORITY = "no_majority"


class PreTxSettlementRound(VotingRound):
    """A round that will be called before the tx settlement."""

    payload_class = VotingPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.CHECKS_PASSED
    none_event = Event.REFILL_REQUIRED
    negative_event = Event.REFILL_REQUIRED
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_votes)
    # the none event is not required because the `VotingPayload` payload does not allow for `None` values
    extended_requirements = tuple(
        attribute
        for attribute in VotingRound.required_class_attributes
        if attribute != NONE_EVENT_ATTRIBUTE
    )


class PostTxSettlementRound(CollectSameUntilThresholdRound):
    """A round that will be called after tx settlement is done."""

    payload_class: Any = object()
    synchronized_data_class = SynchronizedData
    # no class attributes are required because this round is overriding the `end_block` method
    extended_requirements = ()

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """
        The end block.

        This is a special type of round. No consensus is necessary here.
        There is no need to send a tx through, nor to check for a majority.
        We simply use this round to check which round submitted the tx,
        and move to the next state in accordance with that.

        :return: the synchronized data and the event, otherwise `None` if the round is still running.
        """
        submitter_to_event: Dict[str, Event] = {
            MechRequestRound.auto_round_id(): Event.MECH_REQUESTING_DONE,
            BetPlacementRound.auto_round_id(): Event.BET_PLACEMENT_DONE,
            SellOutcomeTokensRound.auto_round_id(): Event.SELL_OUTCOME_TOKENS_DONE,
            RedeemRound.auto_round_id(): Event.REDEEMING_DONE,
            CallCheckpointRound.auto_round_id(): Event.STAKING_DONE,
            SubscriptionRound.auto_round_id(): Event.SUBSCRIPTION_DONE,
        }

        synced_data = SynchronizedData(self.synchronized_data.db)
        event = submitter_to_event.get(synced_data.tx_submitter, Event.UNRECOGNIZED)

        # if a mech request was just performed, increase the utilized tool's counter
        if event == Event.MECH_REQUESTING_DONE:
            policy = synced_data.policy
            policy.tool_used(synced_data.mech_tool)
            policy_update = policy.serialize()
            self.synchronized_data.update(policy=policy_update)

        # if a bet was just placed, edit the utilized tools mapping
        if event in (Event.BET_PLACEMENT_DONE, Event.SELL_OUTCOME_TOKENS_DONE):
            utilized_tools = synced_data.utilized_tools
            utilized_tools[synced_data.final_tx_hash] = synced_data.mech_tool
            tools_update = json.dumps(utilized_tools, sort_keys=True)
            self.synchronized_data.update(utilized_tools=tools_update)

        return synced_data, event


class ChecksPassedRound(DegenerateRound):
    """Round that represents all the pre tx settlement checks have passed."""


class FinishedMechRequestTxRound(DegenerateRound):
    """Finished mech requesting round."""


class FinishedBetPlacementTxRound(DegenerateRound):
    """Finished bet placement round."""


class FinishedSellOutcomeTokensTxRound(DegenerateRound):
    """Finished sell outcome tokens round."""


class FinishedRedeemingTxRound(DegenerateRound):
    """Finished redeeming round."""


class FinishedStakingTxRound(DegenerateRound):
    """Finished staking round."""


class FinishedSubscriptionTxRound(DegenerateRound):
    """Finished subscription round."""


class FailedMultiplexerRound(DegenerateRound):
    """Round that represents failure in identifying the transmitter round."""


class TxSettlementMultiplexerAbciApp(AbciApp[Event]):
    """TxSettlementMultiplexerAbciApp

    Initial round: PreTxSettlementRound

    Initial states: {PostTxSettlementRound, PreTxSettlementRound}

    Transition states:
        0. PreTxSettlementRound
            - checks passed: 2.
            - refill required: 0.
            - no majority: 0.
            - round timeout: 0.
        1. PostTxSettlementRound
            - mech requesting done: 3.
            - bet placement done: 4.
            - sell outcome tokens done: 5.
            - redeeming done: 7.
            - staking done: 8.
            - subscription done: 6.
            - round timeout: 1.
            - unrecognized: 9.
        2. ChecksPassedRound
        3. FinishedMechRequestTxRound
        4. FinishedBetPlacementTxRound
        5. FinishedSellOutcomeTokensTxRound
        6. FinishedSubscriptionTxRound
        7. FinishedRedeemingTxRound
        8. FinishedStakingTxRound
        9. FailedMultiplexerRound

    Final states: {ChecksPassedRound, FailedMultiplexerRound, FinishedBetPlacementTxRound, FinishedMechRequestTxRound, FinishedRedeemingTxRound, FinishedSellOutcomeTokensTxRound, FinishedStakingTxRound, FinishedSubscriptionTxRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: AppState = PreTxSettlementRound
    initial_states: Set[AppState] = {PreTxSettlementRound, PostTxSettlementRound}
    transition_function: AbciAppTransitionFunction = {
        PreTxSettlementRound: {
            Event.CHECKS_PASSED: ChecksPassedRound,
            Event.REFILL_REQUIRED: PreTxSettlementRound,
            Event.NO_MAJORITY: PreTxSettlementRound,
            Event.ROUND_TIMEOUT: PreTxSettlementRound,
        },
        PostTxSettlementRound: {
            Event.MECH_REQUESTING_DONE: FinishedMechRequestTxRound,
            Event.BET_PLACEMENT_DONE: FinishedBetPlacementTxRound,
            Event.SELL_OUTCOME_TOKENS_DONE: FinishedSellOutcomeTokensTxRound,
            Event.REDEEMING_DONE: FinishedRedeemingTxRound,
            Event.STAKING_DONE: FinishedStakingTxRound,
            Event.SUBSCRIPTION_DONE: FinishedSubscriptionTxRound,
            Event.ROUND_TIMEOUT: PostTxSettlementRound,
            Event.UNRECOGNIZED: FailedMultiplexerRound,
        },
        ChecksPassedRound: {},
        FinishedMechRequestTxRound: {},
        FinishedBetPlacementTxRound: {},
        FinishedSellOutcomeTokensTxRound: {},
        FinishedSubscriptionTxRound: {},
        FinishedRedeemingTxRound: {},
        FinishedStakingTxRound: {},
        FailedMultiplexerRound: {},
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    final_states: Set[AppState] = {
        ChecksPassedRound,
        FinishedMechRequestTxRound,
        FinishedBetPlacementTxRound,
        FinishedSellOutcomeTokensTxRound,
        FinishedRedeemingTxRound,
        FinishedStakingTxRound,
        FinishedSubscriptionTxRound,
        FailedMultiplexerRound,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        PreTxSettlementRound: {get_name(SynchronizedData.tx_submitter)},
        PostTxSettlementRound: {get_name(SynchronizedData.tx_submitter)},
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        ChecksPassedRound: set(),
        FinishedMechRequestTxRound: set(),
        FinishedBetPlacementTxRound: set(),
        FinishedSellOutcomeTokensTxRound: set(),
        FinishedRedeemingTxRound: set(),
        FinishedStakingTxRound: set(),
        FailedMultiplexerRound: set(),
        FinishedSubscriptionTxRound: set(),
    }
