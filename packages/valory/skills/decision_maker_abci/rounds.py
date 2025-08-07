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
from packages.valory.skills.decision_maker_abci.states.randomness import (
    BenchmarkingRandomnessRound,
    RandomnessRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)


class DecisionMakerAbciApp(AbciApp[Event]):
    """DecisionMakerAbciApp

    Initial round: CheckBenchmarkingModeRound

    Initial states: {CheckBenchmarkingModeRound, ClaimRound, DecisionReceiveRound, HandleFailedTxRound, RandomnessRound, RedeemRound}

    Transition states:
        0. CheckBenchmarkingModeRound
            - benchmarking enabled: 1.
            - benchmarking disabled: 14.
            - no majority: 0.
            - round timeout: 0.
            - none: 20.
            - done: 20.
            - subscription error: 20.
        1. BenchmarkingRandomnessRound
            - done: 3.
            - round timeout: 1.
            - no majority: 1.
            - none: 20.
        2. RandomnessRound
            - done: 3.
            - round timeout: 2.
            - no majority: 2.
            - none: 20.
        3. SamplingRound
            - done: 4.
            - none: 16.
            - no majority: 3.
            - round timeout: 3.
            - new simulated resample: 3.
            - benchmarking enabled: 6.
            - benchmarking finished: 21.
            - fetch error: 20.
        4. SubscriptionRound
            - done: 18.
            - mock tx: 6.
            - no subscription: 6.
            - none: 4.
            - subscription error: 4.
            - no majority: 4.
            - round timeout: 4.
        5. ClaimRound
            - done: 6.
            - subscription error: 5.
            - no majority: 5.
            - round timeout: 5.
        6. ToolSelectionRound
            - done: 7.
            - none: 6.
            - no majority: 6.
            - round timeout: 6.
        7. DecisionRequestRound
            - done: 15.
            - mock mech request: 8.
            - slots unsupported error: 9.
            - no majority: 7.
            - round timeout: 7.
        8. DecisionReceiveRound
            - done: 10.
            - done no sell: 13.
            - done sell: 22.
            - mech response error: 9.
            - no majority: 8.
            - tie: 9.
            - unprofitable: 9.
            - round timeout: 8.
        9. BlacklistingRound
            - done: 16.
            - mock tx: 16.
            - none: 20.
            - no majority: 9.
            - round timeout: 9.
            - fetch error: 20.
        10. BetPlacementRound
            - done: 13.
            - mock tx: 11.
            - insufficient balance: 19.
            - calc buy amount failed: 12.
            - no majority: 10.
            - round timeout: 10.
            - none: 20.
        11. RedeemRound
            - done: 13.
            - mock tx: 3.
            - no redeeming: 17.
            - no majority: 11.
            - redeem round timeout: 17.
            - none: 20.
        12. HandleFailedTxRound
            - blacklist: 9.
            - no op: 11.
            - no majority: 12.
        13. FinishedDecisionMakerRound
        14. BenchmarkingModeDisabledRound
        15. FinishedDecisionRequestRound
        16. FinishedWithoutDecisionRound
        17. FinishedWithoutRedeemingRound
        18. FinishedSubscriptionRound
        19. RefillRequiredRound
        20. ImpossibleRound
        21. BenchmarkingDoneRound
        22. SellOutcomeTokensRound
            - done: 13.
            - calc sell amount failed: 12.
            - mock tx: 10.
            - no majority: 22.
            - round timeout: 22.
            - none: 20.

    Final states: {BenchmarkingDoneRound, BenchmarkingModeDisabledRound, FinishedDecisionMakerRound, FinishedDecisionRequestRound, FinishedSubscriptionRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound}

    Timeouts:
        round timeout: 30.0
        redeem round timeout: 3600.0
    """

    initial_round_cls: AppState = CheckBenchmarkingModeRound
    initial_states: Set[AppState] = {
        CheckBenchmarkingModeRound,
        RandomnessRound,
        HandleFailedTxRound,
        DecisionReceiveRound,
        RedeemRound,
        ClaimRound,
    }
    transition_function: AbciAppTransitionFunction = {
        CheckBenchmarkingModeRound: {
            Event.BENCHMARKING_ENABLED: BenchmarkingRandomnessRound,
            Event.BENCHMARKING_DISABLED: BenchmarkingModeDisabledRound,
            Event.NO_MAJORITY: CheckBenchmarkingModeRound,
            Event.ROUND_TIMEOUT: CheckBenchmarkingModeRound,
            # added because of `autonomy analyse fsm-specs`
            # falsely reporting them as missing from the transition
            Event.NONE: ImpossibleRound,
            Event.DONE: ImpossibleRound,
            Event.SUBSCRIPTION_ERROR: ImpossibleRound,
        },
        BenchmarkingRandomnessRound: {
            Event.DONE: SamplingRound,
            Event.ROUND_TIMEOUT: BenchmarkingRandomnessRound,
            Event.NO_MAJORITY: BenchmarkingRandomnessRound,
            # added because of `autonomy analyse fsm-specs`
            # falsely reporting this as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        RandomnessRound: {
            Event.DONE: SamplingRound,
            Event.ROUND_TIMEOUT: RandomnessRound,
            Event.NO_MAJORITY: RandomnessRound,
            # added because of `autonomy analyse fsm-specs`
            # falsely reporting this as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        SamplingRound: {
            Event.DONE: SubscriptionRound,
            Event.NONE: FinishedWithoutDecisionRound,
            Event.NO_MAJORITY: SamplingRound,
            Event.ROUND_TIMEOUT: SamplingRound,
            Event.NEW_SIMULATED_RESAMPLE: SamplingRound,
            Event.BENCHMARKING_ENABLED: ToolSelectionRound,
            Event.BENCHMARKING_FINISHED: BenchmarkingDoneRound,
            # this is here because of `autonomy analyse fsm-specs`
            # falsely reporting it as missing from the transition
            MarketManagerEvent.FETCH_ERROR: ImpossibleRound,
        },
        SubscriptionRound: {
            Event.DONE: FinishedSubscriptionRound,
            # skip placing the subscription tx and the claiming round
            Event.MOCK_TX: ToolSelectionRound,
            Event.NO_SUBSCRIPTION: ToolSelectionRound,
            Event.NONE: SubscriptionRound,
            Event.SUBSCRIPTION_ERROR: SubscriptionRound,
            Event.NO_MAJORITY: SubscriptionRound,
            Event.ROUND_TIMEOUT: SubscriptionRound,
        },
        ClaimRound: {
            Event.DONE: ToolSelectionRound,
            Event.SUBSCRIPTION_ERROR: ClaimRound,
            Event.NO_MAJORITY: ClaimRound,
            Event.ROUND_TIMEOUT: ClaimRound,
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
            Event.DONE_NO_SELL: FinishedDecisionMakerRound,
            Event.DONE_SELL: SellOutcomeTokensRound,
            Event.MECH_RESPONSE_ERROR: BlacklistingRound,
            Event.NO_MAJORITY: DecisionReceiveRound,
            Event.TIE: BlacklistingRound,
            Event.UNPROFITABLE: BlacklistingRound,
            # loop on the same state until Mech deliver is received
            Event.ROUND_TIMEOUT: DecisionReceiveRound,
        },
        BlacklistingRound: {
            Event.DONE: FinishedWithoutDecisionRound,
            Event.MOCK_TX: FinishedWithoutDecisionRound,
            # degenerate round on purpose, should never have reached here
            Event.NONE: ImpossibleRound,
            Event.NO_MAJORITY: BlacklistingRound,
            Event.ROUND_TIMEOUT: BlacklistingRound,
            # this is here because of `autonomy analyse fsm-specs`
            # falsely reporting it as missing from the transition
            MarketManagerEvent.FETCH_ERROR: ImpossibleRound,
        },
        BetPlacementRound: {
            Event.DONE: FinishedDecisionMakerRound,
            # skip the bet placement tx
            Event.MOCK_TX: RedeemRound,
            # degenerate round on purpose, owner must refill the safe
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,
            Event.CALC_BUY_AMOUNT_FAILED: HandleFailedTxRound,
            Event.NO_MAJORITY: BetPlacementRound,
            Event.ROUND_TIMEOUT: BetPlacementRound,
            # this is here because of `autonomy analyse fsm-specs`
            # falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        RedeemRound: {
            Event.DONE: FinishedDecisionMakerRound,
            Event.MOCK_TX: SamplingRound,
            Event.NO_REDEEMING: FinishedWithoutRedeemingRound,
            Event.NO_MAJORITY: RedeemRound,
            # in case of a round timeout, there likely is something wrong with redeeming
            # it could be the RPC, or some other issue.
            # We don't want to be stuck trying to redeem.
            Event.REDEEM_ROUND_TIMEOUT: FinishedWithoutRedeemingRound,
            # this is here because of `autonomy analyse fsm-specs` falsely
            # reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        HandleFailedTxRound: {
            Event.BLACKLIST: BlacklistingRound,
            Event.NO_OP: RedeemRound,
            Event.NO_MAJORITY: HandleFailedTxRound,
        },
        FinishedDecisionMakerRound: {},
        BenchmarkingModeDisabledRound: {},
        FinishedDecisionRequestRound: {},
        FinishedWithoutDecisionRound: {},
        FinishedWithoutRedeemingRound: {},
        FinishedSubscriptionRound: {},
        RefillRequiredRound: {},
        ImpossibleRound: {},
        BenchmarkingDoneRound: {},
        SellOutcomeTokensRound: {
            Event.DONE: FinishedDecisionMakerRound,
            # skip the bet placement tx
            Event.CALC_SELL_AMOUNT_FAILED: HandleFailedTxRound,
            Event.MOCK_TX: BetPlacementRound,
            Event.NO_MAJORITY: SellOutcomeTokensRound,
            Event.ROUND_TIMEOUT: SellOutcomeTokensRound,
            # this is here because of `autonomy analyse fsm-specs` falsely
            # reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
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
            get_name(SynchronizedData.agreement_id),
        }
    )
    final_states: Set[AppState] = {
        FinishedDecisionMakerRound,
        BenchmarkingModeDisabledRound,
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
        RandomnessRound: set(),
        CheckBenchmarkingModeRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedDecisionMakerRound: {
            get_name(SynchronizedData.sampled_bet_index),
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        BenchmarkingModeDisabledRound: set(),
        FinishedDecisionRequestRound: set(),
        FinishedSubscriptionRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
            get_name(SynchronizedData.agreement_id),
        },
        FinishedWithoutDecisionRound: {get_name(SynchronizedData.sampled_bet_index)},
        FinishedWithoutRedeemingRound: set(),
        RefillRequiredRound: set(),
        ImpossibleRound: set(),
        BenchmarkingDoneRound: {
            get_name(SynchronizedData.mocking_mode),
            get_name(SynchronizedData.next_mock_data_row),
        },
    }
