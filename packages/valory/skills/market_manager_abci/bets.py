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

import builtins
import dataclasses
import json
import sys
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union


BINARY_N_SLOTS = 2


class BetStatus(Enum):
    """A bet's status."""

    UNPROCESSED = auto()
    PROCESSED = auto()
    BLACKLISTED = auto()


@dataclasses.dataclass
class Bet:
    """A bet's structure."""

    id: str
    market: str
    title: str
    collateralToken: str
    creator: str
    fee: int
    openingTimestamp: int
    outcomeSlotCount: int
    outcomeTokenAmounts: Optional[List[int]]
    outcomeTokenMarginalPrices: Optional[List[float]]
    outcomes: Optional[List[str]]
    scaledLiquidityMeasure: float
    status: BetStatus = BetStatus.UNPROCESSED
    blacklist_expiration: float = -1

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self._validate()
        self._cast()
        self._check_usefulness()

    def __lt__(self, other: "Bet") -> bool:
        """Implements less than operator."""
        return self.scaledLiquidityMeasure < other.scaledLiquidityMeasure

    def _blacklist_forever(self) -> None:
        """Blacklist a bet forever. Should only be used in cases where it is impossible to bet."""
        self.outcomes = None
        self.status = BetStatus.BLACKLISTED
        self.blacklist_expiration = sys.maxsize

    def _validate(self) -> None:
        """Validate the values of the instance."""
        necessary_values = (
            self.id,
            self.market,
            self.title,
            self.collateralToken,
            self.creator,
            self.fee,
            self.openingTimestamp,
            self.outcomeSlotCount,
            self.outcomes,
            self.scaledLiquidityMeasure,
        )
        nulls_exist = any(val is None or val == "null" for val in necessary_values)

        outcomes_lists = (
            self.outcomes,
            self.outcomeTokenAmounts,
            self.outcomeTokenMarginalPrices,
        )
        mismatching_outcomes = any(
            self.outcomeSlotCount != len(outcomes)
            for outcomes in outcomes_lists
            if outcomes is not None
        )

        if nulls_exist or mismatching_outcomes:
            self._blacklist_forever()

    def _cast(self) -> None:
        """Cast the values of the instance."""
        if isinstance(self.status, int):
            self.status = BetStatus(self.status)

        types_to_cast = ("int", "float", "str")
        str_to_type = {getattr(builtins, type_): type_ for type_ in types_to_cast}
        for field, hinted_type in self.__annotations__.items():
            uncasted = getattr(self, field)
            if uncasted is None:
                continue

            for type_to_cast, type_name in str_to_type.items():
                if hinted_type == type_to_cast:
                    setattr(self, field, hinted_type(uncasted))
                if f"{str(List)}[{type_name}]" == str(hinted_type):
                    setattr(self, field, list(type_to_cast(val) for val in uncasted))

    def _check_usefulness(self) -> None:
        """If the bet is deemed unhelpful, then blacklist it."""
        if self.scaledLiquidityMeasure == 0:
            self._blacklist_forever()

    def get_outcome(self, index: int) -> str:
        """Get an outcome given its index."""
        if self.outcomes is None:
            raise ValueError(f"Bet {self} has an incorrect outcomes list of `None`.")
        try:
            return self.outcomes[index]
        except KeyError as exc:
            error = f"Cannot get outcome with index {index} from {self.outcomes}"
            raise ValueError(error) from exc

    def _get_binary_outcome(self, no: bool) -> str:
        """Get an outcome only if it is binary."""
        if self.outcomeSlotCount == BINARY_N_SLOTS:
            return self.get_outcome(int(no))
        requested_outcome = "no" if no else "yes"
        error = (
            f"A {requested_outcome!r} outcome is only available for binary questions."
        )
        raise ValueError(error)

    @property
    def yes(self) -> str:
        """Return the "yes" outcome."""
        return self._get_binary_outcome(False)

    @property
    def no(self) -> str:
        """Return the "no" outcome."""
        return self._get_binary_outcome(True)


class BetsEncoder(json.JSONEncoder):
    """JSON encoder for bets."""

    def default(self, o: Any) -> Any:
        """The default encoder."""
        if isinstance(o, BetStatus):
            return o.value
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


def serialize_bets(bets: List[Bet]) -> Optional[str]:
    """Get the bets serialized."""
    if len(bets) == 0:
        return None
    return json.dumps(bets, cls=BetsEncoder)
