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
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
    CheckBenchmarkingModeRound,
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
    BenchmarkingDoneRound,
    BenchmarkingModeDisabledRound,
    FinishedBenchmarkingRound,
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

    Initial round: CheckBenchmarkingModeRound

    Initial states: {CheckBenchmarkingModeRound, ClaimRound, DecisionReceiveRound, HandleFailedTxRound, RedeemRound, SamplingRound}

    Transition states:
        0. CheckBenchmarkingModeRound
            - benchmarking enabled: 4.
            - benchmarking disabled: 13.
            - no majority: 0.
            - round timeout: 0.
            - no op: 20.
            - blacklist: 20.
        1. SamplingRound
            - done: 2.
            - none: 16.
            - no majority: 1.
            - round timeout: 1.
            - fetch error: 20.
        2. SubscriptionRound
            - done: 18.
            - mock tx: 4.
            - no subscription: 4.
            - none: 2.
            - subscription error: 2.
            - no majority: 2.
            - round timeout: 2.
        3. ClaimRound
            - done: 4.
            - subscription error: 3.
            - no majority: 3.
            - round timeout: 3.
        4. RandomnessRound
            - done: 5.
            - round timeout: 4.
            - no majority: 4.
        5. ToolSelectionRound
            - done: 6.
            - none: 5.
            - no majority: 5.
            - round timeout: 5.
        6. DecisionRequestRound
            - done: 15.
            - mock mech request: 7.
            - slots unsupported error: 8.
            - no majority: 6.
            - round timeout: 6.
        7. DecisionReceiveRound
            - done: 9.
            - mech response error: 8.
            - no majority: 7.
            - tie: 8.
            - unprofitable: 8.
            - benchmarking finished: 21.
            - round timeout: 7.
        8. BlacklistingRound
            - done: 16.
            - mock tx: 14.
            - none: 20.
            - no majority: 8.
            - round timeout: 8.
            - fetch error: 20.
        9. BetPlacementRound
            - done: 12.
            - mock tx: 14.
            - insufficient balance: 19.
            - no majority: 9.
            - round timeout: 9.
            - none: 20.
        10. RedeemRound
            - done: 12.
            - mock tx: 14.
            - no redeeming: 17.
            - no majority: 10.
            - redeem round timeout: 17.
            - none: 20.
        11. HandleFailedTxRound
            - blacklist: 8.
            - no op: 10.
            - no majority: 11.
        12. FinishedDecisionMakerRound
        13. BenchmarkingModeDisabledRound
        14. FinishedBenchmarkingRound
        15. FinishedDecisionRequestRound
        16. FinishedWithoutDecisionRound
        17. FinishedWithoutRedeemingRound
        18. FinishedSubscriptionRound
        19. RefillRequiredRound
        20. ImpossibleRound
        21. BenchmarkingDoneRound

    Final states: {BenchmarkingDoneRound, BenchmarkingModeDisabledRound, FinishedBenchmarkingRound, FinishedDecisionMakerRound, FinishedDecisionRequestRound, FinishedSubscriptionRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound}

    Timeouts:
        round timeout: 30.0
        redeem round timeout: 3600.0
    """

    initial_round_cls: AppState = CheckBenchmarkingModeRound
    initial_states: Set[AppState] = {
        CheckBenchmarkingModeRound,
        SamplingRound,
        HandleFailedTxRound,
        DecisionReceiveRound,
        RedeemRound,
        ClaimRound,
    }
    transition_function: AbciAppTransitionFunction = {
        CheckBenchmarkingModeRound: {
            Event.BENCHMARKING_ENABLED: RandomnessRound,
            Event.BENCHMARKING_DISABLED: BenchmarkingModeDisabledRound,
            Event.NO_MAJORITY: CheckBenchmarkingModeRound,
            Event.ROUND_TIMEOUT: CheckBenchmarkingModeRound,
            # added because of `autonomy analyse fsm-specs` falsely reporting them as missing from the transition
            Event.NO_OP: ImpossibleRound,
            Event.BLACKLIST: ImpossibleRound,
        },
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
            # skip placing the subscription tx and the claiming round
            Event.MOCK_TX: RandomnessRound,
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
            # skip the request to the mech
            Event.MOCK_MECH_REQUEST: DecisionReceiveRound,
            Event.SLOTS_UNSUPPORTED_ERROR: BlacklistingRound,
            Event.NO_MAJORITY: DecisionRequestRound,
            Event.ROUND_TIMEOUT: DecisionRequestRound,
        },
        DecisionReceiveRound: {
            Event.DONE: BetPlacementRound,
            Event.MECH_RESPONSE_ERROR: BlacklistingRound,
            Event.NO_MAJORITY: DecisionReceiveRound,
            Event.TIE: BlacklistingRound,
            Event.UNPROFITABLE: BlacklistingRound,
            Event.BENCHMARKING_FINISHED: BenchmarkingDoneRound,
            Event.ROUND_TIMEOUT: DecisionReceiveRound,  # loop on the same state until Mech deliver is received
        },
        BlacklistingRound: {
            Event.DONE: FinishedWithoutDecisionRound,
            Event.MOCK_TX: FinishedBenchmarkingRound,
            Event.NONE: ImpossibleRound,  # degenerate round on purpose, should never have reached here
            Event.NO_MAJORITY: BlacklistingRound,
            Event.ROUND_TIMEOUT: BlacklistingRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            MarketManagerEvent.FETCH_ERROR: ImpossibleRound,
        },
        BetPlacementRound: {
            Event.DONE: FinishedDecisionMakerRound,
            # skip the bet placement tx and the redeeming
            Event.MOCK_TX: FinishedBenchmarkingRound,
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,  # degenerate round on purpose, owner must refill the safe
            Event.NO_MAJORITY: BetPlacementRound,
            Event.ROUND_TIMEOUT: BetPlacementRound,
            # this is here because of `autonomy analyse fsm-specs` falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        RedeemRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.MOCK_TX: FinishedBenchmarkingRound,
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
        BenchmarkingModeDisabledRound: {},
        FinishedBenchmarkingRound: {},
        FinishedDecisionRequestRound: {},
        FinishedWithoutDecisionRound: {},
        FinishedWithoutRedeemingRound: {},
        FinishedSubscriptionRound: {},
        RefillRequiredRound: {},
        ImpossibleRound: {},
        BenchmarkingDoneRound: {},
    }
    cross_period_persisted_keys = frozenset(
        {
            get_name(SynchronizedData.available_mech_tools),
            get_name(SynchronizedData.policy),
            get_name(SynchronizedData.utilized_tools),
            get_name(SynchronizedData.redeemed_condition_ids),
            get_name(SynchronizedData.payout_so_far),
            get_name(SynchronizedData.mech_price),
            get_name(SynchronizedData.mocking_mode),
            get_name(SynchronizedData.next_mock_data_row),
        }
    )
    final_states: Set[AppState] = {
        FinishedDecisionMakerRound,
        BenchmarkingModeDisabledRound,
        FinishedBenchmarkingRound,
        FinishedDecisionRequestRound,
        FinishedSubscriptionRound,
        FinishedWithoutDecisionRound,
        FinishedWithoutRedeemingRound,
        RefillRequiredRound,
        ImpossibleRound,
        BenchmarkingDoneRound,
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
        CheckBenchmarkingModeRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedDecisionMakerRound: {
            get_name(SynchronizedData.sampled_bet_index),
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        BenchmarkingModeDisabledRound: set(),
        FinishedBenchmarkingRound: {
            get_name(SynchronizedData.sampled_bet_index),
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
        BenchmarkingDoneRound: set(),
    }
