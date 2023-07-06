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


"""Structures for the bets."""

import dataclasses
import json
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union


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
    market: str
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

    @property
    def yes(self) -> str:
        """Return the "yes" outcome."""
        if not self.outcomes:
            return "yes"
        return self.outcomes[0]

    @property
    def no(self) -> str:
        """Return the "no" outcome."""
        if self.outcomes is None or len(self.outcomes) < 2:
            return "no"
        return self.outcomes[1]


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
