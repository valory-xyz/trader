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


"""Custom objects for the MarketManager ABCI application."""

from typing import Any, Dict, Iterator, List, Tuple

from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS
from packages.valory.skills.market_manager_abci.rounds import MarketManagerAbciApp


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


GNOSIS_RPC_TIMEOUT_DAYS = 25


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = MarketManagerAbciApp


class OmenSubgraph(ApiSpecs):
    """A model that wraps ApiSpecs for the OMEN's subgraph specifications."""


class NetworkSubgraph(ApiSpecs):
    """A model that wraps ApiSpecs for the network's subgraph specifications."""


class MarketManagerParams(BaseParams):
    """Market manager's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        # this is a mapping from a prediction market spec's attribute to the creators we want to take into account
        self.creator_per_market: Dict[str, List[str]] = self._ensure(
            "creator_per_subgraph", kwargs, Dict[str, List[str]]
        )
        self.slot_count: int = self._ensure("slot_count", kwargs, int)

        if self.slot_count != BINARY_N_SLOTS:
            raise ValueError(
                f"Only a slot_count `2` is currently supported. `{self.slot_count}` was found in the configuration."
            )

        self.opening_margin: int = self._ensure("opening_margin", kwargs, int)
        self.languages: List[str] = self._ensure("languages", kwargs, List[str])
        self.average_block_time: int = self._ensure("average_block_time", kwargs, int)
        self.abt_error_mult: int = self._ensure("abt_error_mult", kwargs, int)
        self._redeem_margin_days: int = 0
        self.redeem_margin_days = self._ensure("redeem_margin_days", kwargs, int)
        super().__init__(*args, **kwargs)

    @property
    def redeem_margin_days(self) -> int:
        """Get the margin in days of the redeeming information."""
        return self._redeem_margin_days

    @redeem_margin_days.setter
    def redeem_margin_days(self, redeem_margin_days: int) -> None:
        """Get the margin in days of the redeeming information."""
        value_enforcement = (
            f"The value needs to be in the exclusive range (0, {GNOSIS_RPC_TIMEOUT_DAYS}) "
            f"and manual redeeming has to be performed for markets older than {GNOSIS_RPC_TIMEOUT_DAYS - 1} days."
        )

        if redeem_margin_days <= 0:
            raise ValueError(
                "The margin in days for the redeeming information (`redeem_margin_days`) "
                f"cannot be set to {redeem_margin_days} <= 0. {value_enforcement}"
            )
        if redeem_margin_days >= GNOSIS_RPC_TIMEOUT_DAYS:
            raise ValueError(
                "Due to a constraint of the Gnosis RPCs, it is not possible to configure the redeeming "
                f"information's time window to exceed {GNOSIS_RPC_TIMEOUT_DAYS - 1} days "
                f"(currently {redeem_margin_days=}). To clarify, these RPCs experience timeouts "
                "when attempting to filter for historical on-chain events. "
                "Practical testing of the service has revealed that timeouts consistently occur for blocks "
                f"approximately {GNOSIS_RPC_TIMEOUT_DAYS} days old. {value_enforcement}"
            )

        self._redeem_margin_days = redeem_margin_days

    @property
    def creators_iterator(self) -> Iterator[Tuple[str, List[str]]]:
        """Return an iterator of market per creators."""
        return iter(self.creator_per_market.items())
