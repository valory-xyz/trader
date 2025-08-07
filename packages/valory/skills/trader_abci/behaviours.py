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

"""This module contains the behaviours for the trader skill."""

from typing import Set, Type

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.chatui_abci.behaviours import ChatuiRoundBehaviour
from packages.valory.skills.check_stop_trading_abci.behaviours import (
    CheckStopTradingRoundBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.round_behaviour import (
    AgentDecisionMakerRoundBehaviour,
)
from packages.valory.skills.market_manager_abci.behaviours import (
    MarketManagerRoundBehaviour,
)
from packages.valory.skills.mech_interact_abci.behaviours.round_behaviour import (
    MechInteractRoundBehaviour,
)
from packages.valory.skills.registration_abci.behaviours import (
    AgentRegistrationRoundBehaviour,
    RegistrationStartupBehaviour,
)
from packages.valory.skills.reset_pause_abci.behaviours import (
    ResetPauseABCIConsensusBehaviour,
)
from packages.valory.skills.staking_abci.behaviours import StakingRoundBehaviour
from packages.valory.skills.termination_abci.behaviours import (
    BackgroundBehaviour,
    TerminationAbciBehaviours,
)
from packages.valory.skills.trader_abci.composition import TraderAbciApp
from packages.valory.skills.transaction_settlement_abci.behaviours import (
    TransactionSettlementRoundBehaviour,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.behaviours import (
    PostTxSettlementFullBehaviour,
)


class TraderConsensusBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the trader."""

    initial_behaviour_cls = RegistrationStartupBehaviour
    abci_app_cls = TraderAbciApp

    behaviours: Set[Type[BaseBehaviour]] = {
        *AgentRegistrationRoundBehaviour.behaviours,
        *AgentDecisionMakerRoundBehaviour.behaviours,
        *MarketManagerRoundBehaviour.behaviours,
        *MechInteractRoundBehaviour.behaviours,
        *ResetPauseABCIConsensusBehaviour.behaviours,
        *TerminationAbciBehaviours.behaviours,
        *TransactionSettlementRoundBehaviour.behaviours,
        *PostTxSettlementFullBehaviour.behaviours,
        *StakingRoundBehaviour.behaviours,
        *CheckStopTradingRoundBehaviour.behaviours,
        *ChatuiRoundBehaviour.behaviours,
    }
    background_behaviours_cls = {BackgroundBehaviour}  # type: ignore
