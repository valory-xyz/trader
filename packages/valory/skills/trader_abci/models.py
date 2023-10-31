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

"""Custom objects for the trader ABCI application."""

from typing import Dict, Type, Union, cast

from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.decision_maker_abci.models import (
    AgentToolsSpecs as DecisionMakerAgentToolsSpecs,
)
from packages.valory.skills.decision_maker_abci.models import DecisionMakerParams
from packages.valory.skills.decision_maker_abci.models import (
    MechResponseSpecs as DecisionMakerMechResponseSpecs,
)
from packages.valory.skills.decision_maker_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.decision_maker_abci.rounds import (
    Event as DecisionMakerEvent,
)
from packages.valory.skills.market_manager_abci.models import (
    NetworkSubgraph as MarketManagerNetworkSubgraph,
)
from packages.valory.skills.market_manager_abci.models import (
    OmenSubgraph as MarketManagerOmenSubgraph,
)
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)
from packages.valory.skills.reset_pause_abci.rounds import Event as ResetPauseEvent
from packages.valory.skills.termination_abci.models import TerminationParams
from packages.valory.skills.trader_abci.composition import TraderAbciApp
from packages.valory.skills.transaction_settlement_abci.rounds import Event as TSEvent


EventType = Union[
    Type[MarketManagerEvent],
    Type[DecisionMakerEvent],
    Type[TSEvent],
    Type[ResetPauseEvent],
]
EventToTimeoutMappingType = Dict[
    Union[MarketManagerEvent, DecisionMakerEvent, TSEvent, ResetPauseEvent],
    float,
]


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool
OmenSubgraph = MarketManagerOmenSubgraph
NetworkSubgraph = MarketManagerNetworkSubgraph
MechResponseSpecs = DecisionMakerMechResponseSpecs
AgentToolsSpecs = DecisionMakerAgentToolsSpecs

MARGIN = 5


class RandomnessApi(ApiSpecs):
    """A model for randomness api specifications."""


class TraderParams(DecisionMakerParams, TerminationParams):
    """A model to represent the trader params."""


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = TraderAbciApp

    @property
    def params(self) -> TraderParams:
        """Get the parameters."""
        return cast(TraderParams, self.context.params)

    def setup(self) -> None:
        """Set up."""
        super().setup()

        events = (MarketManagerEvent, DecisionMakerEvent, TSEvent, ResetPauseEvent)
        round_timeout = self.params.round_timeout_seconds
        round_timeout_overrides = {
            cast(EventType, event).ROUND_TIMEOUT: round_timeout for event in events
        }
        reset_pause_timeout = self.params.reset_pause_duration + MARGIN
        event_to_timeout_overrides: EventToTimeoutMappingType = {
            **round_timeout_overrides,
            TSEvent.RESET_TIMEOUT: round_timeout,
            TSEvent.VALIDATE_TIMEOUT: self.params.validate_timeout,
            TSEvent.FINALIZE_TIMEOUT: self.params.finalize_timeout,
            TSEvent.CHECK_TIMEOUT: self.params.history_check_timeout,
            ResetPauseEvent.RESET_AND_PAUSE_TIMEOUT: reset_pause_timeout,
        }

        for event, override in event_to_timeout_overrides.items():
            TraderAbciApp.event_to_timeout[event] = override
