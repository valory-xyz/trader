# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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


"""Models for the Staking ABCI application."""

from typing import Any, Optional

from packages.valory.skills.abstract_round_abci.models import BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.staking_abci.rounds import StakingAbciApp


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class StakingParams(BaseParams):
    """Staking parameters."""

    mech_chain_id: Optional[str]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.staking_contract_address: str = self._ensure(
            "staking_contract_address", kwargs, str
        )
        self.staking_interaction_sleep_time: int = self._ensure(
            "staking_interaction_sleep_time", kwargs, int
        )
        self.mech_activity_checker_contract: str = self._ensure(
            "mech_activity_checker_contract", kwargs, str
        )
        super().__init__(*args, **kwargs)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = StakingAbciApp
