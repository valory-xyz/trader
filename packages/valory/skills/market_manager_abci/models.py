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


"""Custom objects for the MarketManager ABCI application."""

import builtins
from typing import Any, Dict, Iterator, List, Tuple

from packages.valory.protocols.http import HttpMessage
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


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = MarketManagerAbciApp


class Subgraph(ApiSpecs):
    """Specifies `ApiSpecs` with common functionality for subgraphs."""

    def process_response(self, response: HttpMessage) -> Any:
        """Process the response."""
        res = super().process_response(response)
        if res is not None:
            return res

        error_data = self.response_info.error_data
        expected_error_type = getattr(builtins, self.response_info.error_type)
        if isinstance(error_data, expected_error_type):
            error_message_key = self.context.params.the_graph_error_message_key
            error_message = error_data.get(error_message_key, None)
            if self.context.params.the_graph_payment_required_error in error_message:
                err = "Payment required for subsequent requests for the current 'The Graph' API key!"
                self.context.logger.error(err)
        return None


class OmenSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the OMEN's subgraph specifications."""


class NetworkSubgraph(Subgraph):
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
        self.the_graph_error_message_key: str = self._ensure(
            "the_graph_error_message_key", kwargs, str
        )
        self.the_graph_payment_required_error: str = self._ensure(
            "the_graph_payment_required_error", kwargs, str
        )
        self.olas_token_address: str = self._ensure("olas_token_address", kwargs, str)
        self.http_handler_hostname_regex: str = self._ensure(
            "http_handler_hostname_regex", kwargs, str
        )
        super().__init__(*args, **kwargs)

    @property
    def creators_iterator(self) -> Iterator[Tuple[str, List[str]]]:
        """Return an iterator of market per creators."""
        return iter(self.creator_per_market.items())
