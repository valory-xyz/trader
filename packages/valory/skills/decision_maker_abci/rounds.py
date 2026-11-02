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
    FailedAgentTopUpTxRound,
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
    FinishedRankingRequestRound,
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
from packages.valory.skills.decision_maker_abci.states.ranking import (
    RankingReceiveRound,
    RankingRequestRound,
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

    Initial states: {CheckBenchmarkingModeRound, DecisionReceiveRound, DecisionRequestRound, HandleFailedTxRound, OmenWithdrawRound, PolymarketBetPlacementRound, PolymarketPostSetApprovalRound, PolymarketWithdrawRound, PolymarketWithdrawTopUpRound, PostBetUpdateRound, PostOmenWithdrawRound, RandomnessRound, RankingReceiveRound, RedeemRouterRound}

    Transition states:
        0. CheckBenchmarkingModeRound
            - benchmarking enabled: 1.
            - benchmarking disabled: 10.
            - set approval: 16.
            - no majority: 0.
            - round timeout: 0.
            - none: 39.
        1. BenchmarkingRandomnessRound
            - done: 5.
            - round timeout: 1.
            - no majority: 1.
            - none: 39.
        2. RandomnessRound
            - done: 3.
            - round timeout: 2.
            - no majority: 2.
            - none: 39.
        3. RankingRequestRound
            - done: 26.
            - none: 5.
            - no majority: 3.
            - round timeout: 3.
        4. RankingReceiveRound
            - done: 36.
            - none: 9.
            - no majority: 4.
            - round timeout: 4.
        5. SamplingRound
            - done: 6.
            - none: 36.
            - no majority: 5.
            - round timeout: 5.
            - new simulated resample: 5.
            - benchmarking enabled: 6.
            - benchmarking finished: 40.
        6. ToolSelectionRound
            - done: 7.
            - none: 6.
            - no majority: 6.
            - round timeout: 6.
        7. PolymarketSwapUsdcRound
            - done: 8.
            - none: 8.
            - prepare tx: 31.
            - no majority: 7.
            - round timeout: 7.
            - mock tx: 8.
        8. DecisionRequestRound
            - done: 25.
            - mock mech request: 9.
            - slots unsupported error: 11.
            - no majority: 8.
            - round timeout: 8.
        9. DecisionReceiveRound
            - done: 12.
            - polymarket done: 14.
            - done no sell: 23.
            - done sell: 41.
            - mech response error: 11.
            - no majority: 9.
            - tie: 11.
            - unprofitable: 11.
            - round timeout: 9.
        10. PolymarketWrapCollateralRound
            - done: 24.
            - none: 24.
            - prepare tx: 34.
            - mock tx: 24.
            - no majority: 10.
            - round timeout: 10.
        11. BlacklistingRound
            - done: 36.
            - mock tx: 36.
            - none: 39.
            - no majority: 11.
            - round timeout: 11.
        12. BetPlacementRound
            - done: 23.
            - mock tx: 18.
            - insufficient balance: 38.
            - calc buy amount failed: 21.
            - no majority: 12.
            - round timeout: 12.
        13. PolymarketBetPlacementRound
            - done: 15.
            - bet placement done: 15.
            - bet placement failed: 13.
            - bet placement impossible: 11.
            - insufficient balance: 38.
            - mock tx: 29.
            - no majority: 13.
            - round timeout: 13.
        14. PolymarketTopUpRound
            - done: 13.
            - prepare tx: 32.
            - insufficient balance: 38.
            - mock tx: 13.
            - no majority: 14.
            - round timeout: 14.
        15. PolymarketSweepRound
            - done: 29.
            - none: 15.
            - mock tx: 29.
            - no majority: 15.
            - round timeout: 15.
        16. PolymarketSetApprovalRound
            - done: 17.
            - prepare tx: 35.
            - no majority: 16.
            - round timeout: 16.
            - none: 39.
            - mock tx: 17.
        17. PolymarketPostSetApprovalRound
            - done: 10.
            - approval failed: 16.
            - no majority: 17.
            - round timeout: 17.
            - none: 39.
        18. RedeemRound
            - done: 23.
            - mock tx: 5.
            - no redeeming: 37.
            - no majority: 18.
            - redeem round timeout: 37.
        19. RedeemRouterRound
            - done: 18.
            - polymarket done: 20.
            - no majority: 19.
            - none: 19.
        20. PolymarketRedeemRound
            - done: 28.
            - prepare tx: 27.
            - no majority: 20.
            - no redeeming: 37.
            - redeem round timeout: 23.
            - mock tx: 28.
        21. HandleFailedTxRound
            - blacklist: 11.
            - no op: 18.
            - agent topup failed: 48.
            - no majority: 21.
        22. PostBetUpdateRound
            - done: 30.
            - none: 22.
            - no majority: 22.
            - round timeout: 22.
        23. FinishedDecisionMakerRound
        24. BenchmarkingModeDisabledRound
        25. FinishedDecisionRequestRound
        26. FinishedRankingRequestRound
        27. FinishedRedeemTxPreparationRound
        28. FinishedPolymarketRedeemRound
        29. FinishedPolymarketBetPlacementRound
        30. FinishedPostBetUpdateRound
        31. FinishedPolymarketSwapTxPreparationRound
        32. FinishedPolymarketTopUpTxPreparationRound
        33. FinishedPolymarketWithdrawTopUpTxPreparationRound
        34. FinishedPolymarketWrapCollateralTxPreparationRound
        35. FinishedSetApprovalTxPreparationRound
        36. FinishedWithoutDecisionRound
        37. FinishedWithoutRedeemingRound
        38. RefillRequiredRound
        39. ImpossibleRound
        40. BenchmarkingDoneRound
        41. SellOutcomeTokensRound
            - done: 23.
            - calc sell amount failed: 21.
            - mock tx: 12.
            - no majority: 41.
            - round timeout: 41.
            - none: 39.
        42. PolymarketWithdrawTopUpRound
            - prepare tx: 33.
            - withdrawal done: 47.
            - none: 42.
            - done: 43.
            - mock tx: 43.
            - insufficient balance: 47.
            - no majority: 42.
            - round timeout: 42.
        43. PolymarketWithdrawRound
            - withdrawal done: 47.
            - withdrawal round timeout: 47.
            - no majority: 43.
            - none: 43.
        44. OmenWithdrawRound
            - prepare tx: 46.
            - withdrawal done: 47.
            - withdrawal round timeout: 47.
            - no majority: 44.
            - done: 47.
            - mock tx: 47.
        45. PostOmenWithdrawRound
            - withdrawal done: 47.
            - withdrawal round timeout: 47.
            - no majority: 45.
            - none: 45.
        46. FinishedOmenWithdrawRound
        47. WithdrawalIdleRound
        48. FailedAgentTopUpTxRound

    Final states: {BenchmarkingDoneRound, BenchmarkingModeDisabledRound, FailedAgentTopUpTxRound, FinishedDecisionMakerRound, FinishedDecisionRequestRound, FinishedOmenWithdrawRound, FinishedPolymarketBetPlacementRound, FinishedPolymarketRedeemRound, FinishedPolymarketSwapTxPreparationRound, FinishedPolymarketTopUpTxPreparationRound, FinishedPolymarketWithdrawTopUpTxPreparationRound, FinishedPolymarketWrapCollateralTxPreparationRound, FinishedPostBetUpdateRound, FinishedRankingRequestRound, FinishedRedeemTxPreparationRound, FinishedSetApprovalTxPreparationRound, FinishedWithoutDecisionRound, FinishedWithoutRedeemingRound, ImpossibleRound, RefillRequiredRound, WithdrawalIdleRound}

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
        RankingReceiveRound,
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
            Event.DONE: RankingRequestRound,
            Event.ROUND_TIMEOUT: RandomnessRound,
            Event.NO_MAJORITY: RandomnessRound,
            # added because of `autonomy analyse fsm-specs`
            # falsely reporting this as missing from the transition
            Event.NONE: ImpossibleRound,
        },
        RankingRequestRound: {
            # the list needs renewing: the ranking goes straight to the mech
            Event.DONE: FinishedRankingRequestRound,
            Event.NONE: SamplingRound,
            Event.NO_MAJORITY: RankingRequestRound,
            Event.ROUND_TIMEOUT: RankingRequestRound,
        },
        RankingReceiveRound: {
            # a ranking answer was stored; a prediction answer carries no payload
            Event.DONE: FinishedWithoutDecisionRound,
            Event.NONE: DecisionReceiveRound,
            Event.NO_MAJORITY: RankingReceiveRound,
            Event.ROUND_TIMEOUT: RankingReceiveRound,
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
            Event.AGENT_TOPUP_FAILED: FailedAgentTopUpTxRound,
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
        FinishedRankingRequestRound: {},
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
        FailedAgentTopUpTxRound: {},
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
        FinishedRankingRequestRound,
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
        FailedAgentTopUpTxRound,
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
        RankingReceiveRound: set(),
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
        FinishedRankingRequestRound: set(),
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
        FailedAgentTopUpTxRound: set(),
    }
