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
    FinishedOmenWithdrawRound,
    FinishedPolymarketBetPlacementRound,
    FinishedPolymarketRedeemRound,
    FinishedPolymarketSwapTxPreparationRound,
    FinishedPolymarketTopUpTxPreparationRound,
    FinishedPolymarketWithdrawTopUpTxPreparationRound,
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
from packages.valory.skills.decision_maker_abci.states.omen_withdraw import (
    OmenWithdrawRound,
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
from packages.valory.skills.decision_maker_abci.states.polymarket_sweep import (
    PolymarketSweepRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_top_up import (
    PolymarketTopUpRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_withdraw import (
    PolymarketWithdrawRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_withdraw_top_up import (
    PolymarketWithdrawTopUpRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_wrap_collateral import (
    PolymarketWrapCollateralRound,
)
from packages.valory.skills.decision_maker_abci.states.post_bet_update import (
    PostBetUpdateRound,
)
from packages.valory.skills.decision_maker_abci.states.post_omen_withdraw import (
    PostOmenWithdrawRound,
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
from packages.valory.skills.decision_maker_abci.states.withdrawal_idle import (
    WithdrawalIdleRound,
)


class DecisionMakerAbciApp(AbciApp[Event]):
    """DecisionMakerAbciApp

    Initial round: CheckBenchmarkingModeRound

    Initial states: {CheckBenchmarkingModeRound, DecisionReceiveRound, DecisionRequestRound, HandleFailedTxRound, OmenWithdrawRound, PolymarketBetPlacementRound, PolymarketPostSetApprovalRound, PolymarketWithdrawRound, PolymarketWithdrawTopUpRound, PostBetUpdateRound, PostOmenWithdrawRound, RandomnessRound, RedeemRouterRound}

    Transition states:
        0. CheckBenchmarkingModeRound
            - benchmarking enabled: 1.
            - benchmarking disabled: 8.
            - set approval: 14.
            - no majority: 0.
            - round timeout: 0.
            - none: 36.
        1. BenchmarkingRandomnessRound
            - done: 3.
            - round timeout: 1.
            - no majority: 1.
            - none: 36.
        2. RandomnessRound
            - done: 3.
            - round timeout: 2.
            - no majority: 2.
            - none: 36.
        3. SamplingRound
            - done: 4.
            - none: 33.
            - no majority: 3.
            - round timeout: 3.
            - new simulated resample: 3.
            - benchmarking enabled: 4.
            - benchmarking finished: 37.
        4. ToolSelectionRound
            - done: 5.
            - none: 4.
            - no majority: 4.
            - round timeout: 4.
        5. PolymarketSwapUsdcRound
            - done: 6.
            - none: 6.
            - prepare tx: 28.
            - no majority: 5.
            - round timeout: 5.
            - mock tx: 6.
        6. DecisionRequestRound
            - done: 23.
            - mock mech request: 7.
            - slots unsupported error: 9.
            - no majority: 6.
            - round timeout: 6.
        7. DecisionReceiveRound
            - done: 10.
            - polymarket done: 12.
            - done no sell: 21.
            - done sell: 38.
            - mech response error: 9.
            - no majority: 7.
            - tie: 9.
            - unprofitable: 9.
            - round timeout: 7.
        8. PolymarketWrapCollateralRound
            - done: 22.
            - none: 22.
            - prepare tx: 31.
            - mock tx: 22.
            - no majority: 8.
            - round timeout: 8.
        9. BlacklistingRound
            - done: 33.
            - mock tx: 33.
            - none: 36.
            - no majority: 9.
            - round timeout: 9.
        10. BetPlacementRound
            - done: 21.
            - mock tx: 16.
            - insufficient balance: 35.
            - calc buy amount failed: 19.
            - no majority: 10.
            - round timeout: 10.
        11. PolymarketBetPlacementRound
            - done: 13.
            - bet placement done: 13.
            - bet placement failed: 11.
            - bet placement impossible: 9.
            - insufficient balance: 35.
            - mock tx: 26.
            - no majority: 11.
            - round timeout: 11.
        12. PolymarketTopUpRound
            - done: 11.
            - prepare tx: 29.
            - insufficient balance: 35.
            - mock tx: 11.
            - no majority: 12.
            - round timeout: 12.
        13. PolymarketSweepRound
            - done: 26.
            - none: 13.
            - mock tx: 26.
            - no majority: 13.
            - round timeout: 13.
        14. PolymarketSetApprovalRound
            - done: 15.
            - prepare tx: 32.
            - no majority: 14.
            - round timeout: 14.
            - none: 36.
            - mock tx: 15.
        15. PolymarketPostSetApprovalRound
            - done: 8.
            - approval failed: 14.
            - no majority: 15.
            - round timeout: 15.
            - none: 36.
        16. RedeemRound
            - done: 21.
            - mock tx: 3.
            - no redeeming: 34.
            - no majority: 16.
            - redeem round timeout: 34.
        17. RedeemRouterRound
            - done: 16.
            - polymarket done: 18.
            - no majority: 17.
            - none: 17.
        18. PolymarketRedeemRound
            - done: 25.
            - prepare tx: 24.
            - no majority: 18.
            - no redeeming: 34.
            - redeem round timeout: 21.
            - mock tx: 25.
        19. HandleFailedTxRound
            - blacklist: 9.
            - no op: 16.
            - no majority: 19.
        20. PostBetUpdateRound
            - done: 27.
            - none: 20.
            - no majority: 20.
            - round timeout: 20.
        21. FinishedDecisionMakerRound
        22. BenchmarkingModeDisabledRound
        23. FinishedDecisionRequestRound
        24. FinishedRedeemTxPreparationRound
        25. FinishedPolymarketRedeemRound
        26. FinishedPolymarketBetPlacementRound
        27. FinishedPostBetUpdateRound
        28. FinishedPolymarketSwapTxPreparationRound
        29. FinishedPolymarketTopUpTxPreparationRound
        30. FinishedPolymarketWithdrawTopUpTxPreparationRound
        31. FinishedPolymarketWrapCollateralTxPreparationRound
        32. FinishedSetApprovalTxPreparationRound
        33. FinishedWithoutDecisionRound
        34. FinishedWithoutRedeemingRound
        35. RefillRequiredRound
        36. ImpossibleRound
        37. BenchmarkingDoneRound
        38. SellOutcomeTokensRound
            - done: 21.
            - calc sell amount failed: 19.
            - mock tx: 10.
            - no majority: 38.
            - round timeout: 38.
            - none: 36.
        39. PolymarketWithdrawTopUpRound
            - prepare tx: 30.
            - withdrawal done: 44.
            - none: 39.
            - done: 40.
            - mock tx: 40.
            - insufficient balance: 44.
            - no majority: 39.
            - round timeout: 39.
        40. PolymarketWithdrawRound
            - withdrawal done: 44.
            - withdrawal round timeout: 44.
            - no majority: 40.
            - none: 40.
        41. OmenWithdrawRound
            - prepare tx: 43.
            - withdrawal done: 44.
            - withdrawal round timeout: 44.
            - no majority: 41.
            - done: 44.
            - mock tx: 44.
        42. PostOmenWithdrawRound
            - withdrawal done: 44.
            - withdrawal round timeout: 44.
            - no majority: 42.
            - none: 42.
        43. FinishedOmenWithdrawRound
        44. WithdrawalIdleRound

    Final states: {BenchmarkingDoneRound, BenchmarkingModeDisabledRound, FinishedDecisionMakerRound, FinishedDecisionRequestRound, FinishedOmenWithdrawRound, FinishedPolymarketBetPlacementRound, FinishedPolymarketRedeemRound, FinishedPolymarketSwapTxPreparationRound, FinishedPolymarketTopUpTxPreparationRound, FinishedPolymarketWithdrawTopUpTxPreparationRound, FinishedPolymarketWrapCollateralTxPreparationRound, FinishedPostBetUpdateRound, FinishedRedeemTxPreparationRound, FinishedSetApprovalTxPreparationRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound, WithdrawalIdleRound}

    Timeouts:
        round timeout: 30.0
        redeem round timeout: 3600.0
        withdrawal round timeout: 1800.0
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
        PolymarketWithdrawRound,
        OmenWithdrawRound,
        PostOmenWithdrawRound,
        # Re-entered after a top-up settles in tx_settlement_multiplexer
        # (FinishedPolymarketTopUpTxRound -> PolymarketBetPlacementRound).
        PolymarketBetPlacementRound,
        # Withdrawal entry (from check_stop_trading_abci) lands on the CTF
        # top-up; the sell-loop is re-entered after that top-up settles.
        PolymarketWithdrawTopUpRound,
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
            Event.POLYMARKET_DONE: PolymarketTopUpRound,
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
        },
        PolymarketBetPlacementRound: {
            # Polymarket bets are placed off-chain via py-clob-client, so
            # there is no on-chain tx for the multiplexer to route. Pre-fix
            # this round detoured through `RedeemRouterRound` to redeem any
            # winnings before ending the cycle, but redemption now runs at
            # the start of every cycle, so we wrap up directly via the
            # staking checkpoint instead.
            # a matched order leaves realized pUSD (+ any unspent
            # float) in the DepositWallet, so success routes through the sweep
            # round which returns it to the Safe before the cycle wraps up.
            Event.DONE: PolymarketSweepRound,
            Event.BET_PLACEMENT_DONE: PolymarketSweepRound,
            Event.BET_PLACEMENT_FAILED: PolymarketBetPlacementRound,
            # Impossible / insufficient leave the DW pre-funded but unspent;
            # that residual is reclaimed by the next cycle's top-up sweep, so
            # these keep their original terminals.
            Event.BET_PLACEMENT_IMPOSSIBLE: BlacklistingRound,
            # degenerate round on purpose, owner must refill the safe
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,
            # skip the bet placement tx
            Event.MOCK_TX: FinishedPolymarketBetPlacementRound,
            Event.NO_MAJORITY: PolymarketBetPlacementRound,
            Event.ROUND_TIMEOUT: PolymarketBetPlacementRound,
        },
        PolymarketTopUpRound: {
            # DW already funded → straight to placement.
            Event.DONE: PolymarketBetPlacementRound,
            # pUSD transfer Safe→DW built → settle, then return to placement.
            Event.PREPARE_TX: FinishedPolymarketTopUpTxPreparationRound,
            # Safe cannot fund the buy → owner must refill the safe.
            Event.INSUFFICIENT_BALANCE: RefillRequiredRound,
            # MOCK_TX inherited from TxPreparationRound and silenced by the
            # end_block override; routed defensively for the FSM linter.
            Event.MOCK_TX: PolymarketBetPlacementRound,
            Event.NO_MAJORITY: PolymarketTopUpRound,
            Event.ROUND_TIMEOUT: PolymarketTopUpRound,
        },
        PolymarketSweepRound: {
            # Funds returned to the Safe (or DW already empty) → wrap up cycle.
            Event.DONE: FinishedPolymarketBetPlacementRound,
            # Failed sweep loops; funds linger in the DW until the next pass.
            Event.NONE: PolymarketSweepRound,
            # MOCK_TX inherited from TxPreparationRound and silenced by the
            # end_block override; routed defensively for the FSM linter.
            Event.MOCK_TX: FinishedPolymarketBetPlacementRound,
            Event.NO_MAJORITY: PolymarketSweepRound,
            Event.ROUND_TIMEOUT: PolymarketSweepRound,
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
        FinishedPolymarketTopUpTxPreparationRound: {},
        FinishedPolymarketWithdrawTopUpTxPreparationRound: {},
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
        PolymarketWithdrawTopUpRound: {
            # CTF batch transfer Safe→DW built → settle, then enter the loop.
            Event.PREPARE_TX: FinishedPolymarketWithdrawTopUpTxPreparationRound,
            # Nothing sellable → skip straight to idle.
            Event.WITHDRAWAL_DONE: WithdrawalIdleRound,
            Event.NONE: PolymarketWithdrawTopUpRound,
            # DONE / MOCK_TX / INSUFFICIENT_BALANCE inherited from
            # TxPreparationRound and silenced by the end_block override; routed
            # defensively for the FSM linter (never actually emitted).
            Event.DONE: PolymarketWithdrawRound,
            Event.MOCK_TX: PolymarketWithdrawRound,
            Event.INSUFFICIENT_BALANCE: WithdrawalIdleRound,
            Event.NO_MAJORITY: PolymarketWithdrawTopUpRound,
            Event.ROUND_TIMEOUT: PolymarketWithdrawTopUpRound,
        },
        PolymarketWithdrawRound: {
            Event.WITHDRAWAL_DONE: WithdrawalIdleRound,
            Event.WITHDRAWAL_ROUND_TIMEOUT: WithdrawalIdleRound,
            Event.NO_MAJORITY: PolymarketWithdrawRound,
            Event.NONE: PolymarketWithdrawRound,
        },
        OmenWithdrawRound: {
            Event.PREPARE_TX: FinishedOmenWithdrawRound,
            Event.WITHDRAWAL_DONE: WithdrawalIdleRound,
            Event.WITHDRAWAL_ROUND_TIMEOUT: WithdrawalIdleRound,
            Event.NO_MAJORITY: OmenWithdrawRound,
            # DONE / MOCK_TX inherited from `TxPreparationRound` and silenced
            # by the `end_block` override (which switches `DONE` to the
            # payload-carried `event` field). Routed defensively to the
            # terminal so the FSM linter sees them; never actually emitted.
            Event.DONE: WithdrawalIdleRound,
            Event.MOCK_TX: WithdrawalIdleRound,
        },
        PostOmenWithdrawRound: {
            Event.WITHDRAWAL_DONE: WithdrawalIdleRound,
            # Receipt parsing is deterministic — retrying the same input
            # won't unblock a real bug. Escape to the idle terminal so
            # the agent can resume normal operation; the chatui store
            # has already captured any per-position errors from the
            # planning round upstream. Mirrors the OmenWithdrawRound
            # timeout transition above.
            Event.WITHDRAWAL_ROUND_TIMEOUT: WithdrawalIdleRound,
            Event.NO_MAJORITY: PostOmenWithdrawRound,
            Event.NONE: PostOmenWithdrawRound,
        },
        FinishedOmenWithdrawRound: {},
        WithdrawalIdleRound: {},
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
        FinishedPolymarketTopUpTxPreparationRound,
        FinishedPolymarketWithdrawTopUpTxPreparationRound,
        FinishedPolymarketWrapCollateralTxPreparationRound,
        FinishedSetApprovalTxPreparationRound,
        FinishedOmenWithdrawRound,
        FinishedWithoutDecisionRound,
        FinishedWithoutRedeemingRound,
        RefillRequiredRound,
        ImpossibleRound,
        BenchmarkingDoneRound,
        WithdrawalIdleRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
        Event.REDEEM_ROUND_TIMEOUT: 3600.0,
        Event.WITHDRAWAL_ROUND_TIMEOUT: 1800.0,
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
        # Reached via cross-skill mapping from check_stop_trading_abci.
        PolymarketWithdrawRound: set(),
        OmenWithdrawRound: set(),
        # Reached via cross-skill mapping from tx_settlement_multiplexer_abci
        # (FinishedOmenWithdrawTxRound -> PostOmenWithdrawRound).
        PostOmenWithdrawRound: set(),
        # Reached via cross-skill mapping from tx_settlement_multiplexer_abci
        # (FinishedPolymarketTopUpTxRound -> PolymarketBetPlacementRound).
        PolymarketBetPlacementRound: set(),
        # Withdrawal entry from check_stop_trading_abci
        # (FinishedWithWithdrawalPolymarketRound -> PolymarketWithdrawTopUpRound).
        PolymarketWithdrawTopUpRound: set(),
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
        FinishedPolymarketTopUpTxPreparationRound: {
            get_name(SynchronizedData.tx_submitter),
            get_name(SynchronizedData.most_voted_tx_hash),
        },
        FinishedPolymarketWithdrawTopUpTxPreparationRound: {
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
        FinishedOmenWithdrawRound: {
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
        WithdrawalIdleRound: set(),
    }
