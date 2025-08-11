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

"""This module contains the round behaviour for the 'decision_maker_abci' skill."""

from typing import Set, Type

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.bet_placement import (
    BetPlacementBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.check_benchmarking import (
    CheckBenchmarkingModeBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.claim_subscription import (
    ClaimSubscriptionBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.decision_receive import (
    DecisionReceiveBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.decision_request import (
    DecisionRequestBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.handle_failed_tx import (
    HandleFailedTxBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.order_subscription import (
    OrderSubscriptionBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.randomness import (
    BenchmarkingRandomnessBehaviour,
    RandomnessBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.reedem import RedeemBehaviour
from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    SamplingBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.sell_outcome_tokens import (
    SellOutcomeTokensBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.tool_selection import (
    ToolSelectionBehaviour,
)
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp


class AgentDecisionMakerRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the decision-making."""

    initial_behaviour_cls = SamplingBehaviour
    abci_app_cls = DecisionMakerAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {
        SamplingBehaviour,  # type: ignore
        DecisionRequestBehaviour,  # type: ignore
        DecisionReceiveBehaviour,  # type: ignore
        BlacklistingBehaviour,  # type: ignore
        BetPlacementBehaviour,  # type: ignore
        SellOutcomeTokensBehaviour,  # type: ignore
        RedeemBehaviour,  # type: ignore
        HandleFailedTxBehaviour,  # type: ignore
        ToolSelectionBehaviour,  # type: ignore
        OrderSubscriptionBehaviour,
        ClaimSubscriptionBehaviour,
        RandomnessBehaviour,  # type: ignore
        BenchmarkingRandomnessBehaviour,  # type: ignore
        CheckBenchmarkingModeBehaviour,  # type: ignore
    }
