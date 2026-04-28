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
from packages.valory.skills.decision_maker_abci.states.final_states import (
    BenchmarkingDoneRound,
    BenchmarkingModeDisabledRound,
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedPolymarketBetPlacementRound,
    FinishedPolymarketRedeemRound,
    FinishedPolymarketSwapTxPreparationRound,
    FinishedPolymarketWrapCollateralTxPreparationRound,
    FinishedPostBetUpdateRound,
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
from packages.valory.skills.decision_maker_abci.states.polymarket_wrap_collateral import (
    PolymarketWrapCollateralRound,
)
from packages.valory.skills.decision_maker_abci.states.post_bet_update import (
    PostBetUpdateRound,
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

    Initial states: {CheckBenchmarkingModeRound, DecisionReceiveRound, DecisionRequestRound, HandleFailedTxRound, PolymarketPostSetApprovalRound, PostBetUpdateRound, RandomnessRound, RedeemRouterRound}

    Transition states:
        0. CheckBenchmarkingModeRound
            - benchmarking enabled: 1.
            - benchmarking disabled: 8.
            - set approval: 12.
            - prepare tx: 12.
            - no majority: 0.
            - round timeout: 0.
            - none: 32.
        1. BenchmarkingRandomnessRound
            - done: 3.
            - round timeout: 1.
            - no majority: 1.
            - none: 32.
        2. RandomnessRound
            - done: 3.
            - round timeout: 2.
            - no majority: 2.
            - none: 32.
        3. SamplingRound
            - done: 4.
            - none: 29.
            - no majority: 3.
            - round timeout: 3.
            - new simulated resample: 3.
            - benchmarking enabled: 4.
            - benchmarking finished: 33.
            - fetch error: 32.
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
            - slots unsupported error: 9.
            - no majority: 6.
            - round timeout: 6.
        7. DecisionReceiveRound
            - done: 10.
            - polymarket done: 11.
            - done no sell: 19.
            - done sell: 34.
            - mech response error: 9.
            - no majority: 7.
            - tie: 9.
            - unprofitable: 9.
            - round timeout: 7.
        8. PolymarketWrapCollateralRound
            - done: 20.
            - none: 20.
            - prepare tx: 27.
            - mock tx: 20.
            - no majority: 8.
            - round timeout: 8.
        9. BlacklistingRound
            - done: 29.
            - mock tx: 29.
            - none: 32.
            - no majority: 9.
            - round timeout: 9.
            - fetch error: 32.
        10. BetPlacementRound
            - done: 19.
            - mock tx: 14.
            - insufficient balance: 31.
            - calc buy amount failed: 17.
            - no majority: 10.
            - round timeout: 10.
            - none: 32.
        11. PolymarketBetPlacementRound
            - done: 24.
            - bet placement done: 24.
            - bet placement failed: 11.
            - bet placement impossible: 9.
            - insufficient balance: 31.
            - mock tx: 24.
            - no majority: 11.
            - round timeout: 11.
            - none: 32.
        12. PolymarketSetApprovalRound
            - done: 13.
            - prepare tx: 28.
            - no majority: 12.
            - round timeout: 12.
            - none: 32.
            - mock tx: 13.
        13. PolymarketPostSetApprovalRound
            - done: 8.
            - approval failed: 12.
            - no majority: 13.
            - round timeout: 13.
            - none: 32.
        14. RedeemRound
            - done: 19.
            - mock tx: 3.
            - no redeeming: 30.
            - no majority: 14.
            - redeem round timeout: 30.
            - none: 32.
        15. RedeemRouterRound
            - done: 14.
            - polymarket done: 16.
            - no majority: 15.
            - none: 15.
        16. PolymarketRedeemRound
            - done: 23.
            - prepare tx: 22.
            - no majority: 16.
            - none: 16.
            - no redeeming: 30.
            - redeem round timeout: 19.
            - mock tx: 23.
        17. HandleFailedTxRound
            - blacklist: 9.
            - no op: 14.
            - no majority: 17.
        18. PostBetUpdateRound
            - done: 25.
            - none: 18.
            - no majority: 18.
            - round timeout: 18.
        19. FinishedDecisionMakerRound
        20. BenchmarkingModeDisabledRound
        21. FinishedDecisionRequestRound
        22. FinishedRedeemTxPreparationRound
        23. FinishedPolymarketRedeemRound
        24. FinishedPolymarketBetPlacementRound
        25. FinishedPostBetUpdateRound
        26. FinishedPolymarketSwapTxPreparationRound
        27. FinishedPolymarketWrapCollateralTxPreparationRound
        28. FinishedSetApprovalTxPreparationRound
        29. FinishedWithoutDecisionRound
        30. FinishedWithoutRedeemingRound
        31. RefillRequiredRound
        32. ImpossibleRound
        33. BenchmarkingDoneRound
        34. SellOutcomeTokensRound
            - done: 19.
            - calc sell amount failed: 17.
            - mock tx: 10.
            - no majority: 34.
            - round timeout: 34.
            - none: 32.

    Final states: {BenchmarkingDoneRound, BenchmarkingModeDisabledRound, FinishedDecisionMakerRound, FinishedDecisionRequestRound, FinishedPolymarketBetPlacementRound, FinishedPolymarketRedeemRound, FinishedPolymarketSwapTxPreparationRound, FinishedPolymarketWrapCollateralTxPreparationRound, FinishedPostBetUpdateRound, FinishedRedeemTxPreparationRound, FinishedSetApprovalTxPreparationRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound}

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
        DecisionRequestRound,
        PostBetUpdateRound,
    }
    transition_function: AbciAppTransitionFunction = {
        CheckBenchmarkingModeRound: {
            Event.BENCHMARKING_ENABLED: BenchmarkingRandomnessRound,
            # Route the "cycle starts" path through the wrap round so any
            # USDC.e the user deposited between cycles is converted to pUSD
            # before the bankroll check. On Omen cycles the wrap round's
            # is_running_on_polymarket guard makes it a cheap no-op.
            Event.BENCHMARKING_DISABLED: PolymarketWrapCollateralRound,
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
        PolymarketWrapCollateralRound: {
            # No wrap needed (balance at or below dust): start the trading
            # cycle. BenchmarkingModeDisabled routes to FetchMarketsRouter in
            # the composed trader_abci, which drives sampling → mech →
            # decision → bet placement.
            Event.DONE: BenchmarkingModeDisabledRound,
            Event.NONE: BenchmarkingModeDisabledRound,
            # Wrap tx built: hand off to Safe tx settlement.
            Event.PREPARE_TX: FinishedPolymarketWrapCollateralTxPreparationRound,
            Event.MOCK_TX: BenchmarkingModeDisabledRound,
            Event.NO_MAJORITY: PolymarketWrapCollateralRound,
            Event.ROUND_TIMEOUT: PolymarketWrapCollateralRound,
        },
        BlacklistingRound: {
            # After blacklisting a market we end the cycle via the checkpoint;
            # any winnings will be picked up by the early-redeem at the start
            # of the next cycle. Pre-fix this used to detour through
            # `RedeemRouterRound`, but redemption now runs at the start of
            # every cycle so the detour is redundant — and routing back to
            # `RedeemRouterRound` would re-enter the trading flow and break
            # the "one bet attempt per cycle" invariant.
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
        PolymarketBetPlacementRound: {
            # Polymarket bets are placed off-chain via py-clob-client, so
            # there is no on-chain tx for the multiplexer to route. Pre-fix
            # this round detoured through `RedeemRouterRound` to redeem any
            # winnings before ending the cycle, but redemption now runs at
            # the start of every cycle, so we wrap up directly via the
            # staking checkpoint instead.
            Event.DONE: FinishedPolymarketBetPlacementRound,
            Event.BET_PLACEMENT_DONE: FinishedPolymarketBetPlacementRound,
            Event.BET_PLACEMENT_FAILED: PolymarketBetPlacementRound,
            Event.BET_PLACEMENT_IMPOSSIBLE: BlacklistingRound,
            # degenerate round on purpose, owner must refill the safe
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,
            # skip the bet placement tx
            Event.MOCK_TX: FinishedPolymarketBetPlacementRound,
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
            # Insert the wrap step: approvals are confirmed, now make sure any
            # USDC.e in the Safe is converted to pUSD before the trading
            # cycle's bankroll check runs.
            Event.DONE: PolymarketWrapCollateralRound,
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
        HandleFailedTxRound: {
            Event.BLACKLIST: BlacklistingRound,
            Event.NO_OP: RedeemRound,
            Event.NO_MAJORITY: HandleFailedTxRound,
        },
        PostBetUpdateRound: {
            Event.DONE: FinishedPostBetUpdateRound,
            Event.NONE: PostBetUpdateRound,
            Event.NO_MAJORITY: PostBetUpdateRound,
            Event.ROUND_TIMEOUT: PostBetUpdateRound,
        },
        FinishedDecisionMakerRound: {},
        BenchmarkingModeDisabledRound: {},
        FinishedDecisionRequestRound: {},
        FinishedRedeemTxPreparationRound: {},
        FinishedPolymarketRedeemRound: {},
        FinishedPolymarketBetPlacementRound: {},
        FinishedPostBetUpdateRound: {},
        FinishedPolymarketSwapTxPreparationRound: {},
        FinishedPolymarketWrapCollateralTxPreparationRound: {},
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
        FinishedPolymarketBetPlacementRound,
        FinishedPostBetUpdateRound,
        FinishedPolymarketSwapTxPreparationRound,
        FinishedPolymarketWrapCollateralTxPreparationRound,
        FinishedSetApprovalTxPreparationRound,
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
        RedeemRouterRound: set(),
        # problematic check in `chain` does not allow to set `final_tx_hash` as a precondition here
        DecisionReceiveRound: set(),
        # problematic check in `chain` does not allow to set `bets_hash` as a precondition here
        HandleFailedTxRound: set(),
        RandomnessRound: set(),
        CheckBenchmarkingModeRound: {get_name(SynchronizedData.is_marketplace_v2)},
        PolymarketPostSetApprovalRound: set(),
        DecisionRequestRound: set(),
        PostBetUpdateRound: set(),
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
        FinishedPolymarketBetPlacementRound: set(),
        FinishedPostBetUpdateRound: set(),
        FinishedPolymarketSwapTxPreparationRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedPolymarketWrapCollateralTxPreparationRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
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
