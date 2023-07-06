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

import dataclasses
import json
from enum import Enum, auto
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.market_manager_abci.rounds import MarketManagerAbciApp


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class BetStatus(Enum):
    """A bet's status."""

    UNPROCESSED = auto()
    PROCESSED = auto()
    WAITING_RESPONSE = auto()
    RESPONSE_RECEIVED = auto()
    BLACKLISTED = auto()


@dataclasses.dataclass
class Bet:
    """A bet's structure."""

    id: str
    title: str
    creator: str
    fee: int
    openingTimestamp: int
    outcomeSlotCount: int
    outcomeTokenAmounts: List[int]
    outcomeTokenMarginalPrices: List[float]
    outcomes: Optional[List[str]]
    status: BetStatus = BetStatus.UNPROCESSED
    blacklist_expiration: float = -1

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        if self.outcomes == "null":
            self.outcomes = None

        if isinstance(self.status, int):
            super().__setattr__("status", BetStatus(self.status))


class BetsEncoder(json.JSONEncoder):
    """JSON encoder for bets."""

    def default(self, o: Any) -> Any:
        """The default encoder."""
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


class BetsDecoder(json.JSONDecoder):
    """JSON decoder for bets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the Bets JSON decoder."""
        super().__init__(object_hook=self.hook, *args, **kwargs)

    @staticmethod
    def hook(data: Dict[str, Any]) -> Union[Bet, Dict[str, Bet]]:
        """Perform the custom decoding."""
        # if this is a `Bet`
        status_attributes = Bet.__annotations__.keys()
        if sorted(status_attributes) == sorted(data.keys()):
            return Bet(**data)

        return data


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = MarketManagerAbciApp


class RandomnessApi(ApiSpecs):
    """A model that wraps ApiSpecs for randomness api specifications."""


class MarketManagerParams(BaseParams):
    """Market manager's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        # this is a mapping from a prediction market spec's attribute to the creators we want to take into account
        self.creator_per_market: Dict[str, List[str]] = self._ensure(
            "creator_per_subgraph", kwargs, Dict[str, List[str]]
        )
        self.slot_count: int = self._ensure("slot_count", kwargs, int)
        self.opening_margin: int = self._ensure("opening_margin", kwargs, int)
        self.languages: List[str] = self._ensure("languages", kwargs, List[str])
        super().__init__(*args, **kwargs)

    @property
    def creators_iterator(self) -> Iterator[Tuple[str, List[str]]]:
        """Return an iterator of market per creators."""
        return iter(self.creator_per_market.items())
