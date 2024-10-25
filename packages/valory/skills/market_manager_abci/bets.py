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


"""Structures for the bets."""

import builtins
import dataclasses
import json
import sys
from typing import Any, Dict, List, Optional, Union


P_YES_FIELD = "p_yes"
P_NO_FIELD = "p_no"
CONFIDENCE_FIELD = "confidence"
INFO_UTILITY_FIELD = "info_utility"
BINARY_N_SLOTS = 2


@dataclasses.dataclass(init=False)
class PredictionResponse:
    """A response of a prediction."""

    p_yes: float
    p_no: float
    confidence: float
    info_utility: float

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the mech's prediction ignoring extra keys."""
        self.p_yes = float(kwargs.pop(P_YES_FIELD))
        self.p_no = float(kwargs.pop(P_NO_FIELD))
        self.confidence = float(kwargs.pop(CONFIDENCE_FIELD))
        self.info_utility = float(kwargs.pop(INFO_UTILITY_FIELD))

        # all the fields are probabilities; run checks on whether the current prediction response is valid or not.
        probabilities = (getattr(self, field_) for field_ in self.__annotations__)
        if (
            any(not (0 <= prob <= 1) for prob in probabilities)
            or self.p_yes + self.p_no != 1
        ):
            raise ValueError("Invalid prediction response initialization.")

    @property
    def vote(self) -> Optional[int]:
        """Return the vote. `0` represents "yes" and `1` represents "no"."""
        if self.p_no != self.p_yes:
            return int(self.p_no > self.p_yes)
        return None

    @property
    def win_probability(self) -> float:
        """Return the probability estimation for winning with vote."""
        return max(self.p_no, self.p_yes)


def get_default_prediction_response() -> PredictionResponse:
    """Get the default prediction response."""
    return PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.5, info_utility=0.5)


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
    outcomeTokenAmounts: List[int]
    outcomeTokenMarginalPrices: List[float]
    outcomes: Optional[List[str]]
    scaledLiquidityMeasure: float
    prediction_response: PredictionResponse = dataclasses.field(
        default_factory=get_default_prediction_response
    )
    position_liquidity: int = 0
    potential_net_profit: int = 0
    processed_timestamp: int = 0
    n_bets: int = 0

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
        self.processed_timestamp = sys.maxsize

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
            self.outcomeTokenAmounts,
            self.outcomeTokenMarginalPrices,
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

    def update_market_info(self, bet: "Bet") -> None:
        """Update the bet's market information."""
        if (
            self.processed_timestamp == sys.maxsize
            or bet.processed_timestamp == sys.maxsize
        ):
            # do not update the bet if it has been blacklisted forever
            return
        self.outcomeTokenAmounts = bet.outcomeTokenAmounts.copy()
        self.outcomeTokenMarginalPrices = bet.outcomeTokenMarginalPrices.copy()
        self.scaledLiquidityMeasure = bet.scaledLiquidityMeasure

    def rebet_allowed(
        self,
        prediction_response: PredictionResponse,
        liquidity: int,
        potential_net_profit: int,
    ) -> bool:
        """Check if a rebet is allowed based on the previous bet's information."""
        if self.n_bets == 0:
            # it's the first time betting, always allow it
            return True

        more_confident = (
            self.prediction_response.win_probability
            >= prediction_response.win_probability
        )
        if self.prediction_response.vote == prediction_response.vote:
            higher_liquidity = self.position_liquidity >= liquidity
            return more_confident and higher_liquidity
        else:
            profit_increases = self.potential_net_profit >= potential_net_profit
            return more_confident and profit_increases


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
    def hook(data: Dict[str, Any]) -> Union[Bet, PredictionResponse, Dict[str, Bet]]:
        """Perform the custom decoding."""
        # if this is a `PredictionResponse`
        prediction_attributes = sorted(PredictionResponse.__annotations__.keys())
        data_attributes = sorted(data.keys())
        if prediction_attributes == data_attributes:
            return PredictionResponse(**data)

        # if this is a `Bet`
        bet_annotations = sorted(Bet.__annotations__.keys())
        if bet_annotations == data_attributes:
            return Bet(**data)

        return data


def serialize_bets(bets: List[Bet]) -> Optional[str]:
    """Get the bets serialized."""
    if len(bets) == 0:
        return None
    return json.dumps(bets, cls=BetsEncoder)
