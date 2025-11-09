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


"""Structures for the bets."""

import builtins
import dataclasses
import json
import sys
from enum import Enum
from typing import Any, Dict, List, Optional, Union


P_YES_FIELD = "p_yes"
P_NO_FIELD = "p_no"
CONFIDENCE_FIELD = "confidence"
INFO_UTILITY_FIELD = "info_utility"
BINARY_N_SLOTS = 2
DAY_IN_SECONDS = 24 * 60 * 60


class BinaryOutcome(Enum):
    """The outcome of a binary bet."""

    YES = "Yes"
    NO = "No"

    @classmethod
    def from_string(cls, value: str) -> "BinaryOutcome":
        """Get enum from string value."""
        try:
            return cls(value.capitalize())
        except ValueError:
            raise ValueError(f"Invalid binary outcome: {value}")


class QueueStatus(Enum):
    """The status of a bet in the queue."""

    # Common statuses
    EXPIRED = -1  # Bets that have expired, i.e., the market is not live anymore
    FRESH = 0  # Fresh bets that have just been added
    TO_PROCESS = 1  # Bets that are ready to be processed
    PROCESSED = 2  # Bets that have been processed
    REPROCESSED = 3  # Bets that have been reprocessed
    BENCHMARKING_DONE = 4

    def is_fresh(self) -> bool:
        """Check if the bet is fresh."""
        return self == QueueStatus.FRESH

    def is_expired(self) -> bool:
        """Check if the bet is expired."""
        return self == QueueStatus.EXPIRED

    def move_to_process(self) -> "QueueStatus":
        """Move the bet to the process status."""
        if self == QueueStatus.FRESH:
            return QueueStatus.TO_PROCESS
        return self

    def move_to_fresh(self) -> "QueueStatus":
        """Move the bet to the fresh status."""
        if self not in [QueueStatus.EXPIRED, QueueStatus.BENCHMARKING_DONE]:
            return QueueStatus.FRESH
        return self

    def next_status(self) -> "QueueStatus":
        """Get the next status in the queue."""
        if self == QueueStatus.TO_PROCESS:
            return QueueStatus.PROCESSED
        elif self == QueueStatus.PROCESSED:
            return QueueStatus.REPROCESSED
        elif self != QueueStatus.REPROCESSED:
            return QueueStatus.FRESH
        return self


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
    queue_status: QueueStatus = QueueStatus.FRESH
    # a mapping from vote to investment amounts
    investments: Dict[str, List[int]] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self._validate()
        self._cast()
        self._check_usefulness()
        if BinaryOutcome.YES.value not in self.investments:
            self.investments[BinaryOutcome.YES.value] = []
        if BinaryOutcome.NO.value not in self.investments:
            self.investments[BinaryOutcome.NO.value] = []

    def __lt__(self, other: "Bet") -> bool:
        """Implements less than operator."""
        return self.scaledLiquidityMeasure < other.scaledLiquidityMeasure

    @property
    def yes_investments(self) -> List[int]:
        """Get the yes investments."""
        return self.investments[self.yes]

    @property
    def no_investments(self) -> List[int]:
        """Get the no investments."""
        return self.investments[self.no]

    @property
    def n_yes_bets(self) -> int:
        """Get the number of yes bets."""
        return len(self.yes_investments)

    @property
    def n_no_bets(self) -> int:
        """Get the number of no bets."""
        return len(self.no_investments)

    @property
    def n_bets(self) -> int:
        """Get the number of bets."""
        return self.n_yes_bets + self.n_no_bets

    @property
    def invested_amount_yes(self) -> int:
        """Get the amount invested in yes bets."""
        return sum(self.yes_investments)

    @property
    def invested_amount_no(self) -> int:
        """Get the amount invested in no bets."""
        return sum(self.no_investments)

    @property
    def invested_amount(self) -> int:
        """Get the amount invested in bets."""
        return self.invested_amount_yes + self.invested_amount_no

    @staticmethod
    def opposite_vote(vote: int) -> int:
        """Get the opposite vote."""
        return vote ^ 1

    def blacklist_forever(self) -> None:
        """Blacklist a bet forever. Should only be used in cases where it is impossible to bet."""
        self.outcomes = None
        self.processed_timestamp = sys.maxsize
        self.queue_status = QueueStatus.EXPIRED

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
            self.blacklist_forever()

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
            self.blacklist_forever()

    def get_outcome(self, index: int) -> str:
        """Get an outcome given its index."""
        if self.outcomes is None:
            raise ValueError(f"Bet {self} has an incorrect outcomes list of `None`.")
        try:
            return self.outcomes[index].capitalize()
        except KeyError as exc:
            error = f"Cannot get outcome with index {index} from {self.outcomes}"
            raise ValueError(error) from exc

    def _get_binary_outcome(self, no: bool) -> str:
        """Get an outcome only if it is binary."""
        if self.outcomeSlotCount == BINARY_N_SLOTS:
            return self.get_outcome(int(no))
        requested_outcome = BinaryOutcome.NO if no else BinaryOutcome.YES
        error = (
            f"A {requested_outcome!r} outcome is only available for binary questions."
        )
        raise ValueError(error)

    @property
    def yes(self) -> str:
        """Return the "Yes" outcome."""
        return self._get_binary_outcome(False)

    @property
    def no(self) -> str:
        """Return the "No" outcome."""
        return self._get_binary_outcome(True)

    def get_vote_amount(self, vote: int) -> int:
        """Get the amount invested in a vote."""
        vote_name = self.get_outcome(vote)
        return sum(self.investments[vote_name])

    def reset_investments(self) -> None:
        """Reset the investments."""
        for outcome in BinaryOutcome:
            self.investments[outcome.value] = []

    def append_investment_amount(self, vote: int, amount: int) -> None:
        """Append an investment amount to the vote."""
        vote_name = self.get_outcome(vote)
        if vote_name not in self.investments:
            self.investments[vote_name] = []
        self.investments[vote_name].append(amount)

    def set_investment_amount(self, vote: int, amount: int) -> None:
        """Set the investment amount for a vote."""
        vote_name = self.get_outcome(vote)
        self.investments[vote_name] = [amount]

    def update_investments(self, amount: int) -> bool:
        """Get the investments for the current vote type."""
        vote = self.prediction_response.vote
        if vote is None:
            return False

        if vote is None:
            return False

        outcome = self.get_outcome(vote)

        # method to reset the investment amount for a vote
        if amount == 0:
            self.set_investment_amount(vote, 0)
            return True

        self.investments[outcome] = [*self.investments[outcome], amount]
        return True

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

    def set_processed_sell_check(self, processed_time: int) -> None:
        """Set the processed sell check."""
        # stored in memory, lost on restart. todo: figure if makes sense to preserve
        self.last_processed_sell_check = processed_time

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

    def is_ready_to_sell(self, current_timestamp: int, opening_margin: int) -> bool:
        """If more than 24 hours have passed since the bet was opened, it should be checked for selling."""
        return (
            current_timestamp
            > (self.openingTimestamp - opening_margin) + DAY_IN_SECONDS
            and self.invested_amount > 0  # only consider selling if has tokens
        )


class BetsEncoder(json.JSONEncoder):
    """JSON encoder for bets."""

    def default(self, o: Any) -> Any:
        """The default encoder."""
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        if isinstance(o, QueueStatus):
            return o.value
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
            data["queue_status"] = QueueStatus(data["queue_status"])
            return Bet(**data)
        # if the data contains an id key, but does not match the bet attributes exactly, process it as a bet
        elif "id" in data_attributes:
            # Extract only the attributes that exist in both Bet and data to ensure compatibility
            common_attributes = set(bet_annotations) & set(data_attributes)
            data = {key: data[key] for key in common_attributes}
            # Convert queue_status to a QueueStatus enum if present in data
            if "queue_status" in data:
                data["queue_status"] = QueueStatus(data["queue_status"])
            return Bet(**data)
        return data


def serialize_bets(bets: List[Bet]) -> Optional[str]:
    """Get the bets serialized."""
    if len(bets) == 0:
        return None
    return json.dumps(bets, cls=BetsEncoder)
