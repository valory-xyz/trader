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

"""This module contains the rounds for the decision-making."""

from typing import Dict, Set

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AppState,
    get_name,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.decision_maker_abci.states.claim_subscription import (
    ClaimRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedSubscriptionRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    ImpossibleRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.order_subscription import (
    SubscriptionRound,
)
from packages.valory.skills.decision_maker_abci.states.randomness import RandomnessRound
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)


class DecisionMakerAbciApp(AbciApp[Event]):
    """DecisionMakerAbciApp

    Initial round: SamplingRound

    Initial states: {ClaimRound, DecisionReceiveRound, HandleFailedTxRound, RedeemRound, SamplingRound}

    Transition states:
        0. SamplingRound
            - done: 1.
            - none: 12.
            - no majority: 0.
            - round timeout: 0.
            - fetch error: 16.
        1. SubscriptionRound
            - done: 14.
            - no subscription: 3.
            - none: 1.
            - subscription error: 1.
            - no majority: 1.
            - round timeout: 1.
        2. ClaimRound
            - done: 3.
            - subscription error: 2.
            - no majority: 2.
            - round timeout: 2.
        3. RandomnessRound
            - done: 4.
            - round timeout: 3.
            - no majority: 3.
        4. ToolSelectionRound
            - done: 5.
            - none: 4.
            - no majority: 4.
            - round timeout: 4.
        5. DecisionRequestRound
            - done: 11.
            - slots unsupported error: 7.
            - no majority: 5.
            - round timeout: 5.
            - none: 16.
        6. DecisionReceiveRound
            - done: 8.
            - mech response error: 7.
            - no majority: 6.
            - tie: 7.
            - unprofitable: 7.
            - round timeout: 6.
        7. BlacklistingRound
            - done: 12.
            - none: 16.
            - no majority: 7.
            - round timeout: 7.
            - fetch error: 16.
        8. BetPlacementRound
            - done: 11.
            - insufficient balance: 15.
            - no majority: 8.
            - round timeout: 8.
            - none: 16.
        9. RedeemRound
            - done: 11.
            - no redeeming: 13.
            - no majority: 9.
            - redeem round timeout: 13.
            - none: 16.
        10. HandleFailedTxRound
            - blacklist: 7.
            - no op: 9.
            - no majority: 10.
        11. FinishedDecisionMakerRound
        12. FinishedWithoutDecisionRound
        13. FinishedWithoutRedeemingRound
        14. FinishedSubscriptionRound
        15. RefillRequiredRound
        16. ImpossibleRound

    Final states: {FinishedDecisionMakerRound, FinishedSubscriptionRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound}

    Timeouts:
        round timeout: 30.0
        redeem round timeout: 3600.0
    """

    initial_round_cls: AppState = SamplingRound
    initial_states: Set[AppState] = {
        SamplingRound,
        HandleFailedTxRound,
        DecisionReceiveRound,
        RedeemRound,
        ClaimRound,
    }
    transition_function: AbciAppTransitionFunction = {
        SamplingRound: {
            Event.DONE: SubscriptionRound,
            Event.NONE: FinishedWithoutDecisionRound,
            Event.NO_MAJORITY: SamplingRound,
            Event.ROUND_TIMEOUT: SamplingRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            MarketManagerEvent.FETCH_ERROR: ImpossibleRound,
        },
        SubscriptionRound: {
            Event.DONE: FinishedSubscriptionRound,
            Event.NO_SUBSCRIPTION: RandomnessRound,
            Event.NONE: SubscriptionRound,
            Event.SUBSCRIPTION_ERROR: SubscriptionRound,
            Event.NO_MAJORITY: SubscriptionRound,
            Event.ROUND_TIMEOUT: SubscriptionRound,
        },
        ClaimRound: {
            Event.DONE: RandomnessRound,
            Event.SUBSCRIPTION_ERROR: ClaimRound,
            Event.NO_MAJORITY: ClaimRound,
            Event.ROUND_TIMEOUT: ClaimRound,
        },
        RandomnessRound: {
            Event.DONE: ToolSelectionRound,
            Event.ROUND_TIMEOUT: RandomnessRound,
            Event.NO_MAJORITY: RandomnessRound,
        },
        ToolSelectionRound: {
            Event.DONE: DecisionRequestRound,
            Event.NONE: ToolSelectionRound,
            Event.NO_MAJORITY: ToolSelectionRound,
            Event.ROUND_TIMEOUT: ToolSelectionRound,
        },
        DecisionRequestRound: {
            Event.DONE: FinishedDecisionRequestRound,
            Event.NO_MAJORITY: DecisionRequestRound,
            Event.ROUND_TIMEOUT: DecisionRequestRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        DecisionReceiveRound: {
            Event.DONE: BetPlacementRound,
            Event.MECH_RESPONSE_ERROR: BlacklistingRound,
            Event.NO_MAJORITY: DecisionReceiveRound,
            Event.TIE: BlacklistingRound,
            Event.UNPROFITABLE: BlacklistingRound,
            Event.ROUND_TIMEOUT: DecisionReceiveRound,  # loop on the same state until Mech deliver is received
        },
        BlacklistingRound: {
            Event.DONE: FinishedWithoutDecisionRound,
            Event.NONE: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.NO_MAJORITY: BlacklistingRound,
            Event.ROUND_TIMEOUT: BlacklistingRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            MarketManagerEvent.FETCH_ERROR: ImpossibleRound,
        },
        BetPlacementRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,  # degenerate round on purpose, owner must refill the safe
            Event.NO_MAJORITY: BetPlacementRound,
            Event.ROUND_TIMEOUT: BetPlacementRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        RedeemRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.NO_REDEEMING: FinishedWithoutRedeemingRound,
            Event.NO_MAJORITY: RedeemRound,
            # in case of a round timeout, there likely is something wrong with redeeming
            # it could be the RPC, or some other issue. We don't want to be stuck trying to redeem.
            Event.REDEEM_ROUND_TIMEOUT: FinishedWithoutRedeemingRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        HandleFailedTxRound: {
            Event.BLACKLIST: BlacklistingRound,
            Event.NO_OP: RedeemRound,
            Event.NO_MAJORITY: HandleFailedTxRound,
        },
        FinishedDecisionMakerRound: {},
        FinishedDecisionRequestRound: {},
        FinishedWithoutDecisionRound: {},
        FinishedWithoutRedeemingRound: {},
        FinishedSubscriptionRound: {},
        RefillRequiredRound: {},
        ImpossibleRound: {},
    }
    cross_period_persisted_keys = frozenset(
        {
            get_name(SynchronizedData.available_mech_tools),
            get_name(SynchronizedData.policy),
            get_name(SynchronizedData.utilized_tools),
            get_name(SynchronizedData.redeemed_condition_ids),
            get_name(SynchronizedData.payout_so_far),
        }
    )
    final_states: Set[AppState] = {
        FinishedDecisionMakerRound,
        FinishedDecisionRequestRound,
        FinishedSubscriptionRound,
        FinishedWithoutDecisionRound,
        FinishedWithoutRedeemingRound,
        RefillRequiredRound,
        ImpossibleRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
        Event.REDEEM_ROUND_TIMEOUT: 3600.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        RedeemRound: set(),
        ClaimRound: set(),
        DecisionReceiveRound: {
            get_name(SynchronizedData.final_tx_hash),
        },
        HandleFailedTxRound: {
            get_name(SynchronizedData.bets_hash),
        },
        SamplingRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedDecisionMakerRound: {
            get_name(SynchronizedData.sampled_bet_index),
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedDecisionRequestRound: set(),
        FinishedSubscriptionRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedWithoutDecisionRound: {get_name(SynchronizedData.sampled_bet_index)},
        FinishedWithoutRedeemingRound: set(),
        RefillRequiredRound: set(),
        ImpossibleRound: set(),
    }
