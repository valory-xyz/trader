# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Models for the agent top-up ABCI application."""

from typing import Any

from packages.valory.skills.abstract_round_abci.models import (
    BaseParams,
)
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.agent_topup_abci.rounds import AgentTopUpAbciApp

Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class Params(BaseParams):
    """The agent top-up parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        # Below it, the tx settlement waits for the Agent Signer to be refilled.
        self.agent_balance_threshold: int = self._ensure(
            "agent_balance_threshold", kwargs, int
        )
        super().__init__(*args, **kwargs)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = AgentTopUpAbciApp
