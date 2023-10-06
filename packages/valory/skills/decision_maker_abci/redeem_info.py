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


"""Structures for the redeeming."""

import dataclasses
from typing import Any, List

from hexbytes import HexBytes


@dataclasses.dataclass(frozen=True)
class Condition:
    """A structure for an OMEN condition."""

    id: HexBytes
    outcomeSlotCount: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        super().__setattr__("outcomeSlotCount", int(self.outcomeSlotCount))

        if isinstance(self.id, str):
            super().__setattr__("id", HexBytes(self.id))

    @property
    def index_sets(self) -> List[int]:
        """Get the index sets."""
        return [i + 1 for i in range(self.outcomeSlotCount)]


@dataclasses.dataclass(frozen=True)
class Question:
    """A structure for an OMEN question."""

    id: bytes
    data: str

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        if isinstance(self.id, str):
            super().__setattr__("id", bytes.fromhex(self.id[2:]))


@dataclasses.dataclass(frozen=True)
class FPMM:
    """A structure for an OMEN FPMM."""

    answerFinalizedTimestamp: int
    collateralToken: str
    condition: Condition
    creator: str
    creationTimestamp: int
    currentAnswer: str
    question: Question
    templateId: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        super().__setattr__(
            "answerFinalizedTimestamp", int(self.answerFinalizedTimestamp)
        )
        super().__setattr__("templateId", int(self.templateId))
        super().__setattr__("creationTimestamp", int(self.creationTimestamp))

        if isinstance(self.condition, dict):
            super().__setattr__("condition", Condition(**self.condition))

        if isinstance(self.question, dict):
            super().__setattr__("question", Question(**self.question))

    @property
    def current_answer_index(self) -> int:
        """Get the index of the market's current answer."""
        return int(self.currentAnswer, 16)


@dataclasses.dataclass(frozen=True)
class Trade:
    """A structure for an OMEN trade."""

    fpmm: FPMM
    outcomeIndex: int
    outcomeTokenMarginalPrice: float
    outcomeTokensTraded: int
    transactionHash: str

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        super().__setattr__("outcomeIndex", int(self.outcomeIndex))
        super().__setattr__(
            "outcomeTokenMarginalPrice", float(self.outcomeTokenMarginalPrice)
        )
        super().__setattr__("outcomeTokensTraded", int(self.outcomeTokensTraded))

        if isinstance(self.fpmm, dict):
            super().__setattr__("fpmm", FPMM(**self.fpmm))

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        return isinstance(other, Trade) and (
            self.fpmm.condition.id == other.fpmm.condition.id
            or self.fpmm.question.id == other.fpmm.question.id
        )

    def __hash__(self) -> int:
        """Custom hashing operator."""
        return hash(self.fpmm.condition.id) + hash(self.fpmm.question.id)

    @property
    def is_winning(self) -> bool:
        """Return whether the current position is winning."""
        our_answer = self.outcomeIndex
        correct_answer = self.fpmm.current_answer_index
        return our_answer == correct_answer

    @property
    def claimable_amount(self) -> int:
        """Get the claimable amount of the current market."""
        amount = self.outcomeTokensTraded
        if self.is_winning:
            return amount
        return -amount
