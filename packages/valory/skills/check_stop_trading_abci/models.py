# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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
from packages.valory.skills.mech_interact_abci.models import MechMarketplaceConfig
from packages.valory.skills.staking_abci.models import StakingParams


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class CheckStopTradingParams(StakingParams):
    """
    Parameters for the CheckStopTrading component.

    Controls trading behavior based on staking KPIs and marketplace configuration.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters object with trading configuration."""
        # Validate required parameters
        self._validate_required_params(kwargs)

        # Initialize basic parameters
        self.mech_contract_address: str = str(kwargs["mech_contract_address"])
        self.disable_trading: bool = self._ensure("disable_trading", kwargs, bool)
        self.stop_trading_if_staking_kpi_met: bool = self._ensure(
            "stop_trading_if_staking_kpi_met", kwargs, bool
        )
        self.use_mech_marketplace: bool = bool(kwargs["use_mech_marketplace"])
        self.enable_position_review: bool = bool(kwargs["enable_position_review"])
        self.review_period_seconds: int = int(kwargs["review_period_seconds"])

        # Default KPI request address is the mech contract
        self.staking_kpi_mech_count_request_address: str = self.mech_contract_address

        # Configure marketplace if enabled
        if self.use_mech_marketplace:
            self._configure_marketplace(kwargs)

        super().__init__(*args, **kwargs)

    def _validate_required_params(self, kwargs: Dict[str, Any]) -> None:
        """Validate that required parameters are present."""
        mech_address = kwargs.get("mech_contract_address")
        use_mech_flag = kwargs.get("use_mech_marketplace")

        enforce(
            mech_address is not None,
            "Missing required parameter: 'mech_contract_address'",
        )
        enforce(
            use_mech_flag is not None,
            "Missing required parameter: 'use_mech_marketplace'",
        )

    def _configure_marketplace(self, kwargs: Dict[str, Any]) -> None:
        """Configure marketplace settings when marketplace is enabled."""
        marketplace_config = kwargs.get("mech_marketplace_config", {})
        enforce(marketplace_config is not None, "Market place config cannot be empty")

        # Create MechMarketplaceConfig instance from the config dict
        self.mech_marketplace_config = MechMarketplaceConfig(
            **kwargs["mech_marketplace_config"]
        )

        # Update the KPI request address to use marketplace address
        self.staking_kpi_mech_count_request_address = str(
            self.mech_marketplace_config.mech_marketplace_address
        )


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = CheckStopTradingAbciApp
