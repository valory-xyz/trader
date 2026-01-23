# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.decision_maker_abci.states.fetch_markets_router import (
    FetchMarketsRouterRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    BenchmarkingDoneRound,
    BenchmarkingModeDisabledRound,
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedFetchMarketsRouterRound,
    FinishedPolymarketFetchMarketRound,
    FinishedPolymarketRedeemRound,
    FinishedPolymarketSwapTxPreparationRound,
    FinishedRedeemTxPreparationRound,
    FinishedSetApprovalTxPreparationRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    ImpossibleRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_fetch_market import (
    PolymarketFetchMarketRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_post_set_approval import (
    PolymarketPostSetApprovalRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    PolymarketRedeemRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_set_approval import (
    PolymarketSetApprovalRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_swap import (
    PolymarketSwapUsdcRound,
)
from packages.valory.skills.decision_maker_abci.states.randomness import (
    BenchmarkingRandomnessRound,
    RandomnessRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.redeem_router import (
    RedeemRouterRound,
)
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

    Initial states: {CheckBenchmarkingModeRound, DecisionReceiveRound, DecisionRequestRound, FetchMarketsRouterRound, HandleFailedTxRound, PolymarketPostSetApprovalRound, RandomnessRound, RedeemRouterRound}

    Transition states:
        0. CheckBenchmarkingModeRound
            - benchmarking enabled: 1.
            - benchmarking disabled: 20.
            - set approval: 11.
            - prepare tx: 11.
            - no majority: 0.
            - round timeout: 0.
            - none: 31.
        1. BenchmarkingRandomnessRound
            - done: 3.
            - round timeout: 1.
            - no majority: 1.
            - none: 31.
        2. RandomnessRound
            - done: 3.
            - round timeout: 2.
            - no majority: 2.
            - none: 31.
        3. SamplingRound
            - done: 4.
            - none: 28.
            - no majority: 3.
            - round timeout: 3.
            - new simulated resample: 3.
            - benchmarking enabled: 4.
            - benchmarking finished: 32.
            - fetch error: 31.
        4. ToolSelectionRound
            - done: 5.
            - none: 4.
            - no majority: 4.
            - round timeout: 4.
        5. PolymarketSwapUsdcRound
            - done: 6.
            - none: 6.
            - prepare tx: 26.
            - no majority: 5.
            - round timeout: 5.
            - mock tx: 6.
        6. DecisionRequestRound
            - done: 21.
            - mock mech request: 7.
            - slots unsupported error: 8.
            - no majority: 6.
            - round timeout: 6.
        7. DecisionReceiveRound
            - done: 9.
            - polymarket done: 10.
            - done no sell: 19.
            - done sell: 33.
            - mech response error: 8.
            - no majority: 7.
            - tie: 8.
            - unprofitable: 8.
            - round timeout: 7.
        8. BlacklistingRound
            - done: 14.
            - mock tx: 28.
            - none: 31.
            - no majority: 8.
            - round timeout: 8.
            - fetch error: 31.
        9. BetPlacementRound
            - done: 19.
            - mock tx: 13.
            - insufficient balance: 30.
            - calc buy amount failed: 18.
            - no majority: 9.
            - round timeout: 9.
            - none: 31.
        10. PolymarketBetPlacementRound
            - done: 14.
            - bet placement done: 14.
            - bet placement failed: 10.
            - mock tx: 14.
            - insufficient balance: 30.
            - no majority: 10.
            - round timeout: 10.
            - none: 31.
        11. PolymarketSetApprovalRound
            - done: 12.
            - prepare tx: 27.
            - no majority: 11.
            - round timeout: 11.
            - none: 31.
            - mock tx: 12.
        12. PolymarketPostSetApprovalRound
            - done: 20.
            - approval failed: 11.
            - no majority: 12.
            - round timeout: 12.
            - none: 31.
        13. RedeemRound
            - done: 19.
            - mock tx: 3.
            - no redeeming: 29.
            - no majority: 13.
            - redeem round timeout: 29.
            - none: 31.
        14. RedeemRouterRound
            - done: 13.
            - polymarket done: 15.
            - no majority: 14.
            - none: 14.
        15. PolymarketRedeemRound
            - done: 23.
            - prepare tx: 22.
            - no majority: 15.
            - none: 15.
            - no redeeming: 29.
            - redeem round timeout: 19.
            - mock tx: 23.
        16. FetchMarketsRouterRound
            - done: 24.
            - polymarket fetch markets: 17.
            - no majority: 16.
            - none: 16.
        17. PolymarketFetchMarketRound
            - done: 25.
            - fetch error: 31.
            - no majority: 17.
            - round timeout: 17.
        18. HandleFailedTxRound
            - blacklist: 8.
            - no op: 13.
            - no majority: 18.
        19. FinishedDecisionMakerRound
        20. BenchmarkingModeDisabledRound
        21. FinishedDecisionRequestRound
        22. FinishedRedeemTxPreparationRound
        23. FinishedPolymarketRedeemRound
        24. FinishedFetchMarketsRouterRound
        25. FinishedPolymarketFetchMarketRound
        26. FinishedPolymarketSwapTxPreparationRound
        27. FinishedSetApprovalTxPreparationRound
        28. FinishedWithoutDecisionRound
        29. FinishedWithoutRedeemingRound
        30. RefillRequiredRound
        31. ImpossibleRound
        32. BenchmarkingDoneRound
        33. SellOutcomeTokensRound
            - done: 19.
            - calc sell amount failed: 18.
            - mock tx: 9.
            - no majority: 33.
            - round timeout: 33.
            - none: 31.

    Final states: {BenchmarkingDoneRound, BenchmarkingModeDisabledRound, FinishedDecisionMakerRound, FinishedDecisionRequestRound, FinishedFetchMarketsRouterRound, FinishedPolymarketFetchMarketRound, FinishedPolymarketRedeemRound, FinishedPolymarketSwapTxPreparationRound, FinishedRedeemTxPreparationRound, FinishedSetApprovalTxPreparationRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound}

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
        RedeemRouterRound,
        PolymarketPostSetApprovalRound,
        FetchMarketsRouterRound,
        DecisionRequestRound,
    }
    transition_function: AbciAppTransitionFunction = {
        CheckBenchmarkingModeRound: {
            Event.BENCHMARKING_ENABLED: BenchmarkingRandomnessRound,
            Event.BENCHMARKING_DISABLED: BenchmarkingModeDisabledRound,
            Event.SET_APPROVAL: PolymarketSetApprovalRound,
            Event.PREPARE_TX: PolymarketSetApprovalRound,
            Event.NO_MAJORITY: CheckBenchmarkingModeRound,
            Event.ROUND_TIMEOUT: CheckBenchmarkingModeRound,
            # added because of `autonomy analyse fsm-specs`
            # falsely reporting them as missing from the transition
            Event.NONE: ImpossibleRound,
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
            Event.DONE: ToolSelectionRound,
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
        ToolSelectionRound: {
            Event.DONE: PolymarketSwapUsdcRound,
            Event.NONE: ToolSelectionRound,
            Event.NO_MAJORITY: ToolSelectionRound,
            Event.ROUND_TIMEOUT: ToolSelectionRound,
        },
        PolymarketSwapUsdcRound: {
            Event.DONE: DecisionRequestRound,
            Event.NONE: DecisionRequestRound,
            Event.PREPARE_TX: FinishedPolymarketSwapTxPreparationRound,
            Event.NO_MAJORITY: PolymarketSwapUsdcRound,
            Event.ROUND_TIMEOUT: PolymarketSwapUsdcRound,
            Event.MOCK_TX: DecisionRequestRound,
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
            Event.POLYMARKET_DONE: PolymarketBetPlacementRound,
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
            Event.DONE: RedeemRouterRound,
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
        PolymarketBetPlacementRound: {
            Event.DONE: RedeemRouterRound,
            Event.BET_PLACEMENT_DONE: RedeemRouterRound,
            Event.BET_PLACEMENT_FAILED: PolymarketBetPlacementRound,
            # skip the bet placement tx
            Event.MOCK_TX: RedeemRouterRound,
            # degenerate round on purpose, owner must refill the safe
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,
            Event.NO_MAJORITY: PolymarketBetPlacementRound,
            Event.ROUND_TIMEOUT: PolymarketBetPlacementRound,
            # this is here because of `autonomy analyse fsm-specs`
            # falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        PolymarketSetApprovalRound: {
            Event.DONE: PolymarketPostSetApprovalRound,
            Event.PREPARE_TX: FinishedSetApprovalTxPreparationRound,
            # degenerate round on purpose, owner must refill the safe
            Event.NO_MAJORITY: PolymarketSetApprovalRound,
            Event.ROUND_TIMEOUT: PolymarketSetApprovalRound,
            # this is here because of `autonomy analyse fsm-specs`
            # falsely reporting it as missing from the transition
            Event.NONE: ImpossibleRound,
            Event.MOCK_TX: PolymarketPostSetApprovalRound,
        },
        PolymarketPostSetApprovalRound: {
            Event.DONE: BenchmarkingModeDisabledRound,
            # degenerate round on purpose, owner must refill the safe
            Event.APPROVAL_FAILED: PolymarketSetApprovalRound,
            Event.NO_MAJORITY: PolymarketPostSetApprovalRound,
            Event.ROUND_TIMEOUT: PolymarketPostSetApprovalRound,
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
        RedeemRouterRound: {
            Event.DONE: RedeemRound,
            Event.POLYMARKET_DONE: PolymarketRedeemRound,
            Event.NO_MAJORITY: RedeemRouterRound,
            Event.NONE: RedeemRouterRound,
        },
        PolymarketRedeemRound: {
            Event.DONE: FinishedPolymarketRedeemRound,
            Event.PREPARE_TX: FinishedRedeemTxPreparationRound,
            Event.NO_MAJORITY: PolymarketRedeemRound,
            Event.NONE: PolymarketRedeemRound,
            Event.NO_REDEEMING: FinishedWithoutRedeemingRound,
            Event.REDEEM_ROUND_TIMEOUT: FinishedDecisionMakerRound,
            Event.MOCK_TX: FinishedPolymarketRedeemRound,
        },
        FetchMarketsRouterRound: {
            Event.DONE: FinishedFetchMarketsRouterRound,  # Routes to UpdateBetsRound via composition
            Event.POLYMARKET_FETCH_MARKETS: PolymarketFetchMarketRound,  # Routes internally to PolymarketFetchMarketRound
            Event.NO_MAJORITY: FetchMarketsRouterRound,
            Event.NONE: FetchMarketsRouterRound,
        },
        PolymarketFetchMarketRound: {
            Event.DONE: FinishedPolymarketFetchMarketRound,
            Event.FETCH_ERROR: ImpossibleRound,
            Event.NO_MAJORITY: PolymarketFetchMarketRound,
            Event.ROUND_TIMEOUT: PolymarketFetchMarketRound,
        },
        HandleFailedTxRound: {
            Event.BLACKLIST: BlacklistingRound,
            Event.NO_OP: RedeemRound,
            Event.NO_MAJORITY: HandleFailedTxRound,
        },
        FinishedDecisionMakerRound: {},
        BenchmarkingModeDisabledRound: {},
        FinishedDecisionRequestRound: {},
        FinishedRedeemTxPreparationRound: {},
        FinishedPolymarketRedeemRound: {},
        FinishedFetchMarketsRouterRound: {},
        FinishedPolymarketFetchMarketRound: {},
        FinishedPolymarketSwapTxPreparationRound: {},
        FinishedSetApprovalTxPreparationRound: {},
        FinishedWithoutDecisionRound: {},
        FinishedWithoutRedeemingRound: {},
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
        FinishedRedeemTxPreparationRound,
        FinishedPolymarketRedeemRound,
        FinishedPolymarketSwapTxPreparationRound,
        FinishedSetApprovalTxPreparationRound,
        FinishedWithoutDecisionRound,
        FinishedWithoutRedeemingRound,
        FinishedFetchMarketsRouterRound,
        FinishedPolymarketFetchMarketRound,
        RefillRequiredRound,
        ImpossibleRound,
        BenchmarkingDoneRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
        Event.REDEEM_ROUND_TIMEOUT: 3600.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        RedeemRouterRound: set(),
        FetchMarketsRouterRound: set(),
        DecisionReceiveRound: {
            get_name(SynchronizedData.final_tx_hash),
        },
        HandleFailedTxRound: {
            get_name(SynchronizedData.bets_hash),
        },
        RandomnessRound: set(),
        CheckBenchmarkingModeRound: set(),
        PolymarketPostSetApprovalRound: set(),
        DecisionRequestRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedDecisionMakerRound: {
            get_name(SynchronizedData.sampled_bet_index),
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        BenchmarkingModeDisabledRound: set(),
        FinishedDecisionRequestRound: set(),
        FinishedRedeemTxPreparationRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedPolymarketRedeemRound: set(),
        FinishedPolymarketSwapTxPreparationRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedFetchMarketsRouterRound: set(),
        FinishedPolymarketFetchMarketRound: set(),
        FinishedSetApprovalTxPreparationRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
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
