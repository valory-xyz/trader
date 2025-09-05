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


"""Models for the Staking ABCI application."""

import os
from pathlib import Path
from typing import Any

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


def get_store_path(kwargs: dict) -> Path:
    """Get the path of the store."""
    path = kwargs.get("store_path", "")
    if not path:
        msg = "The path to the store must be provided as a keyword argument."
        raise ValueError(msg)

    # check if the path exists, and we can write to it
    if (
        not os.path.isdir(path)
        or not os.access(path, os.W_OK)
        or not os.access(path, os.R_OK)
    ):
        msg = f"The store path {path!r} is not a directory or is not writable."
        raise ValueError(msg)

    return Path(path)


class StakingParams(BaseParams):
    """Staking parameters."""

    mech_chain_id: str

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
        self.store_path = get_store_path(kwargs)
        super().__init__(*args, **kwargs)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = StakingAbciApp
