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

"""This module contains the trader ABCI application."""

from packages.valory.skills.abstract_round_abci.abci_app_chain import (
    AbciAppTransitionMapping,
    chain,
)
from packages.valory.skills.abstract_round_abci.base import BackgroundAppConfig
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
from packages.valory.skills.decision_maker_abci.states.claim_subscription import (
    ClaimRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    BenchmarkingDoneRound,
    BenchmarkingModeDisabledRound,
    FinishedDecisionMakerRound,
    FinishedDecisionRequestRound,
    FinishedSubscriptionRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.randomness import RandomnessRound
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.market_manager_abci.rounds import (
    FailedMarketManagerRound,
    FinishedMarketManagerRound,
    MarketManagerAbciApp,
    UpdateBetsRound,
)
from packages.valory.skills.mech_interact_abci.rounds import MechInteractAbciApp
from packages.valory.skills.mech_interact_abci.states.final_states import (
    FinishedMechRequestRound,
    FinishedMechRequestSkipRound,
    FinishedMechResponseRound,
    FinishedMechResponseTimeoutRound,
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
    FinishedRedeemingTxRound,
    FinishedSellOutcomeTokensTxRound,
    FinishedStakingTxRound,
    FinishedSubscriptionTxRound,
    PostTxSettlementRound,
    PreTxSettlementRound,
    TxSettlementMultiplexerAbciApp,
)


abci_app_transition_mapping: AbciAppTransitionMapping = {
    FinishedRegistrationRound: CheckBenchmarkingModeRound,
    BenchmarkingModeDisabledRound: UpdateBetsRound,
    FinishedMarketManagerRound: CheckStopTradingRound,
    FinishedCheckStopTradingRound: RandomnessRound,
    FinishedWithSkipTradingRound: RedeemRound,
    FinishedWithReviewBetsRound: RandomnessRound,
    FailedMarketManagerRound: ResetAndPauseRound,
    FinishedDecisionMakerRound: PreTxSettlementRound,
    ChecksPassedRound: RandomnessTransactionSubmissionRound,
    RefillRequiredRound: ResetAndPauseRound,
    FinishedTransactionSubmissionRound: PostTxSettlementRound,
    FinishedSubscriptionTxRound: ClaimRound,
    FailedTransactionSubmissionRound: HandleFailedTxRound,
    FinishedDecisionRequestRound: MechRequestRound,
    FinishedMechRequestRound: PreTxSettlementRound,
    FinishedMechRequestTxRound: MechResponseRound,
    FinishedMechResponseRound: DecisionReceiveRound,
    FinishedMechResponseTimeoutRound: HandleFailedTxRound,
    FinishedMechRequestSkipRound: RedeemRound,
    FinishedSubscriptionRound: PreTxSettlementRound,
    FinishedBetPlacementTxRound: RedeemRound,
    FinishedSellOutcomeTokensTxRound: RedeemRound,
    FinishedRedeemingTxRound: CallCheckpointRound,
    FinishedWithoutDecisionRound: RedeemRound,
    FinishedWithoutRedeemingRound: CallCheckpointRound,
    FinishedStakingRound: ResetAndPauseRound,
    CheckpointCallPreparedRound: PreTxSettlementRound,
    FinishedStakingTxRound: ResetAndPauseRound,
    FinishedResetAndPauseRound: CheckBenchmarkingModeRound,
    FinishedResetAndPauseErrorRound: ResetAndPauseRound,
    # this has no effect, because the `BenchmarkingDoneRound` is terminal
    BenchmarkingDoneRound: ResetAndPauseRound,
}

termination_config = BackgroundAppConfig(
    round_cls=BackgroundRound,
    start_event=Event.TERMINATE,
    abci_app=TerminationAbciApp,
)


TraderAbciApp = chain(
    (
        AgentRegistrationAbciApp,
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
