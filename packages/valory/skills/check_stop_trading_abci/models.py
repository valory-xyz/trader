# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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


"""Models for the check stop trading ABCI application."""

from typing import Any, Dict

from aea.exceptions import enforce

from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
)
from packages.valory.skills.staking_abci.models import StakingParams


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class CheckStopTradingParams(StakingParams):
    """CheckStopTrading parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        mech_address = kwargs.get("mech_contract_address", None)
        marketplace_config = kwargs.get("mech_marketplace_config", None)
        mech_marketplace_used = kwargs.get("use_mech_marketplace", None)
        enforce(mech_address is not None, "Mech contract address not specified!")
        enforce(marketplace_config is not None, "Market Place config cannot be empty")
        enforce(mech_marketplace_used is not None, "Flag informing the trader whether to use the mech marketplace cannot be empty")
        self.mech_contract_address: str = str(mech_address)
        self.disable_trading: bool = self._ensure("disable_trading", kwargs, bool)
        self.stop_trading_if_staking_kpi_met: bool = self._ensure(
            "stop_trading_if_staking_kpi_met", kwargs, bool
        )
        if mech_marketplace_used:
            self.use_mech_marketplace: str = mech_marketplace_used

        if marketplace_config:
            self.mech_marketplace_config: Dict[str, Any] = marketplace_config

            # Extract mech_marketplace_address from mech_marketplace_config


            self.mech_marketplace_address: str = marketplace_config.get("mech_marketplace_address", "")

        if mech_marketplace_used:
            self.mech_marketplace_address = self.mech_marketplace_config.get("mech_marketplace_address", "")

        super().__init__(*args, **kwargs)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = CheckStopTradingAbciApp
