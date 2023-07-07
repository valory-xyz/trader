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

"""This module contains the models for the skill."""

from typing import Any, Dict

from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.market_manager_abci.models import (
    MarketManagerParams as BaseParams,
)


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = DecisionMakerAbciApp


class DecisionMakerParams(BaseParams):
    """Decision maker's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.mech_agent_id: int = self._ensure("mech_agent_id", kwargs, int)
        self.mech_tool: int = self._ensure("mech_tool", kwargs, str)
        # this is a mapping from the confidence of a bet's choice to the amount we are willing to bet
        self.bet_amount_per_threshold: Dict[float, int] = self._ensure(
            "bet_amount_per_threshold", kwargs, Dict[float, int]
        )
        # the threshold amount in WEI starting from which we are willing to place a bet
        self.bet_threshold: int = self._ensure("bet_threshold", kwargs, str)
        # the duration, in seconds, of blacklisting a bet before retrying to make an estimate for it
        self.blacklisting_duration: int = self._ensure(
            "blacklisting_duration", kwargs, int
        )
        super().__init__(*args, **kwargs)

    def get_bet_amount(self, confidence: float) -> int:
        """Get the bet amount given a prediction's confidence."""
        threshold = round(confidence, 1)
        return self.bet_amount_per_threshold[threshold]
