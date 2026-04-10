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

"""This module contains the trader ABCI application."""

from packages.valory.skills.abstract_round_abci.abci_app_chain import (
    AbciAppTransitionMapping,
    chain,
)
from packages.valory.skills.abstract_round_abci.base import BackgroundAppConfig
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
    FetchPerformanceDataRound,
    FinishedFetchPerformanceDataRound,
)
from packages.valory.skills.chatui_abci.rounds import (
    ChatuiAbciApp,
    ChatuiLoadRound,
    FinishedChatuiLoadRound,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
    CheckStopTradingRound,
    FinishedCheckStopTradingRound,
    FinishedWithReviewBetsRound,
    FinishedWithSkipTradingRound,
)
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
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
    FinishedPostBetUpdateRound,
    FinishedRedeemTxPreparationRound,
    FinishedSetApprovalTxPreparationRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_post_set_approval import (
    PolymarketPostSetApprovalRound,
)
from packages.valory.skills.decision_maker_abci.states.post_bet_update import (
    PostBetUpdateRound,
)
from packages.valory.skills.decision_maker_abci.states.randomness import RandomnessRound
from packages.valory.skills.decision_maker_abci.states.redeem_router import (
    RedeemRouterRound,
)
from packages.valory.skills.market_manager_abci.rounds import (
    FailedMarketManagerRound,
    FetchMarketsRouterRound,
    FinishedMarketManagerRound,
    FinishedPolymarketFetchMarketRound,
    MarketManagerAbciApp,
)
from packages.valory.skills.mech_interact_abci.rounds import MechInteractAbciApp
from packages.valory.skills.mech_interact_abci.states.final_states import (
    FailedMechInformationRound,
    FinishedMarketplaceLegacyDetectedRound,
    FinishedMechInformationRound,
    FinishedMechLegacyDetectedRound,
    FinishedMechPurchaseSubscriptionRound,
    FinishedMechRequestRound,
    FinishedMechRequestSkipRound,
    FinishedMechResponseRound,
    FinishedMechResponseTimeoutRound,
)
from packages.valory.skills.mech_interact_abci.states.mech_version import (
    MechVersionDetectionRound,
)
from packages.valory.skills.mech_interact_abci.states.request import MechRequestRound
from packages.valory.skills.mech_interact_abci.states.response import MechResponseRound
from packages.valory.skills.registration_abci.rounds import (
    AgentRegistrationAbciApp,
    FinishedRegistrationRound,
)
from packages.valory.skills.reset_pause_abci.rounds import (
    FinishedResetAndPauseErrorRound,
    FinishedResetAndPauseRound,
    ResetAndPauseRound,
    ResetPauseAbciApp,
)
from packages.valory.skills.staking_abci.rounds import (
    CallCheckpointRound,
    CheckpointCallPreparedRound,
    FinishedStakingRound,
    StakingAbciApp,
)
from packages.valory.skills.termination_abci.rounds import (
    BackgroundRound,
    Event,
    TerminationAbciApp,
)
from packages.valory.skills.transaction_settlement_abci.rounds import (
    FailedRound as FailedTransactionSubmissionRound,
)
from packages.valory.skills.transaction_settlement_abci.rounds import (
    FinishedTransactionSubmissionRound,
    RandomnessTransactionSubmissionRound,
    TransactionSubmissionAbciApp,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    ChecksPassedRound,
    FinishedBetPlacementTxRound,
    FinishedMechRequestTxRound,
    FinishedPolymarketSwapTxRound,
    FinishedRedeemingTxRound,
    FinishedSellOutcomeTokensTxRound,
    FinishedSetApprovalTxRound,
    FinishedStakingTxRound,
    FinishedSubscriptionTxRound,
    PostTxSettlementRound,
    PreTxSettlementRound,
    TxSettlementMultiplexerAbciApp,
)

abci_app_transition_mapping: AbciAppTransitionMapping = {
    FinishedRegistrationRound: FetchPerformanceDataRound,
    FinishedFetchPerformanceDataRound: ChatuiLoadRound,
    FinishedChatuiLoadRound: MechVersionDetectionRound,
    FinishedMarketplaceLegacyDetectedRound: CheckBenchmarkingModeRound,
    FinishedMechLegacyDetectedRound: CheckBenchmarkingModeRound,
    FinishedMechInformationRound: CheckBenchmarkingModeRound,
    FailedMechInformationRound: MechVersionDetectionRound,
    BenchmarkingModeDisabledRound: FetchMarketsRouterRound,
    # Always-redeem-first: route the cycle entry through `RedeemRouterRound`
    # so any unclaimed winning positions are redeemed before the agent
    # attempts to query the mech or place new bets. This prevents the
    # death-spiral where a low safe balance blocks the mech request and
    # the agent can never reach the redeem flow that would refund itself.
    FinishedPolymarketFetchMarketRound: RedeemRouterRound,
    FinishedMarketManagerRound: RedeemRouterRound,
    FinishedCheckStopTradingRound: RandomnessRound,
    # Skip-trading no longer detours through redeem (already done at the
    # start of the cycle); wrap up directly via the staking checkpoint.
    FinishedWithSkipTradingRound: CallCheckpointRound,
    FinishedWithReviewBetsRound: RandomnessRound,
    FailedMarketManagerRound: ResetAndPauseRound,
    FinishedDecisionMakerRound: PreTxSettlementRound,
    ChecksPassedRound: RandomnessTransactionSubmissionRound,
    RefillRequiredRound: ResetAndPauseRound,
    FinishedTransactionSubmissionRound: PostTxSettlementRound,
    FinishedSubscriptionTxRound: RandomnessRound,
    FailedTransactionSubmissionRound: HandleFailedTxRound,
    FinishedDecisionRequestRound: MechRequestRound,
    FinishedMechRequestRound: PreTxSettlementRound,
    FinishedMechRequestTxRound: MechResponseRound,
    FinishedMechResponseRound: DecisionReceiveRound,
    FinishedMechResponseTimeoutRound: HandleFailedTxRound,
    # Mech-request skip, no-decision, and the off-chain Polymarket bet exit
    # all go straight to the staking checkpoint; any winnings produced this
    # period are picked up by the next cycle's early redeem.
    FinishedMechRequestSkipRound: CallCheckpointRound,
    FinishedPolymarketBetPlacementRound: CallCheckpointRound,
    # Omen on-chain bet placement and sell-outcome-tokens go through
    # `PostBetUpdateRound` first, which runs the local-state bookkeeping
    # (advancing the bet's queue status, processed timestamp, invested
    # amount, and strategy) that the legacy design used to do as a side
    # effect of the post-bet `RedeemBehaviour.async_act`. After bookkeeping,
    # the cycle wraps up via the staking checkpoint.
    FinishedBetPlacementTxRound: PostBetUpdateRound,
    FinishedSellOutcomeTokensTxRound: PostBetUpdateRound,
    FinishedPostBetUpdateRound: CallCheckpointRound,
    # Redeem terminals (Omen on-chain via tx settlement, Polymarket
    # on-chain via tx settlement, direct Polymarket DONE/MOCK_TX, and the
    # no-positions-to-redeem path) all hand control back to
    # `CheckStopTradingRound` so the trading decision can run after
    # redemption has been attempted.
    FinishedRedeemingTxRound: CheckStopTradingRound,
    FinishedPolymarketRedeemRound: CheckStopTradingRound,
    FinishedWithoutRedeemingRound: CheckStopTradingRound,
    FinishedPolymarketSwapTxPreparationRound: PreTxSettlementRound,
    FinishedPolymarketSwapTxRound: DecisionRequestRound,
    FinishedRedeemTxPreparationRound: PreTxSettlementRound,
    FinishedSetApprovalTxPreparationRound: PreTxSettlementRound,
    FinishedSetApprovalTxRound: PolymarketPostSetApprovalRound,
    FinishedWithoutDecisionRound: CallCheckpointRound,
    FinishedStakingRound: ResetAndPauseRound,
    CheckpointCallPreparedRound: PreTxSettlementRound,
    FinishedStakingTxRound: ResetAndPauseRound,
    FinishedResetAndPauseRound: FetchPerformanceDataRound,
    FinishedResetAndPauseErrorRound: ResetAndPauseRound,
    # this has no effect, because the `BenchmarkingDoneRound` is terminal
    BenchmarkingDoneRound: ResetAndPauseRound,
    FinishedMechPurchaseSubscriptionRound: PreTxSettlementRound,
}

termination_config = BackgroundAppConfig(
    round_cls=BackgroundRound,
    start_event=Event.TERMINATE,
    abci_app=TerminationAbciApp,
)


TraderAbciApp = chain(
    (
        AgentRegistrationAbciApp,
        AgentPerformanceSummaryAbciApp,
        ChatuiAbciApp,
        DecisionMakerAbciApp,
        MarketManagerAbciApp,
        MechInteractAbciApp,
        TransactionSubmissionAbciApp,
        TxSettlementMultiplexerAbciApp,
        ResetPauseAbciApp,
        StakingAbciApp,
        CheckStopTradingAbciApp,
    ),
    abci_app_transition_mapping,
).add_background_app(termination_config)
