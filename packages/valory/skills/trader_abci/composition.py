# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.decision_maker_abci.states.claim_subscription import (
    ClaimRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.decision_maker_abci.states.final_states import (
    FinishedDecisionMakerRound,
    FinishedSubscriptionRound,
    FinishedWithoutDecisionRound,
    FinishedWithoutRedeemingRound,
    RefillRequiredRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sampling import SamplingRound
from packages.valory.skills.market_manager_abci.rounds import (
    FailedMarketManagerRound,
    FinishedMarketManagerRound,
    MarketManagerAbciApp,
    UpdateBetsRound,
)
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
    FinishedDecisionRequestTxRound,
    FinishedRedeemingTxRound,
    FinishedStakingTxRound,
    FinishedSubscriptionTxRound,
    PostTxSettlementRound,
    PreTxSettlementRound,
    TxSettlementMultiplexerAbciApp,
)


abci_app_transition_mapping: AbciAppTransitionMapping = {
    FinishedRegistrationRound: UpdateBetsRound,
    FinishedMarketManagerRound: SamplingRound,
    FailedMarketManagerRound: ResetAndPauseRound,
    FinishedDecisionMakerRound: PreTxSettlementRound,
    ChecksPassedRound: RandomnessTransactionSubmissionRound,
    RefillRequiredRound: ResetAndPauseRound,
    FinishedTransactionSubmissionRound: PostTxSettlementRound,
    FinishedSubscriptionTxRound: ClaimRound,
    FailedTransactionSubmissionRound: HandleFailedTxRound,
    FinishedDecisionRequestTxRound: DecisionReceiveRound,
    FinishedSubscriptionRound: PreTxSettlementRound,
    FinishedBetPlacementTxRound: RedeemRound,
    FinishedRedeemingTxRound: CallCheckpointRound,
    FinishedWithoutDecisionRound: RedeemRound,
    FinishedWithoutRedeemingRound: CallCheckpointRound,
    FinishedStakingRound: ResetAndPauseRound,
    CheckpointCallPreparedRound: PreTxSettlementRound,
    FinishedStakingTxRound: ResetAndPauseRound,
    FinishedResetAndPauseRound: UpdateBetsRound,
    FinishedResetAndPauseErrorRound: ResetAndPauseRound,
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
        TransactionSubmissionAbciApp,
        TxSettlementMultiplexerAbciApp,
        ResetPauseAbciApp,
        StakingAbciApp,
    ),
    abci_app_transition_mapping,
).add_background_app(termination_config)
