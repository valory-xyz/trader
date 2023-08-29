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
from typing import List, cast

from hexbytes import HexBytes


@dataclasses.dataclass
class Condition:
    """A structure for an OMEN condition."""

    id: HexBytes
    outcomeSlotCount: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self.outcomeSlotCount = int(self.outcomeSlotCount)

        if isinstance(self.id, str):
            self.id = HexBytes(self.id)

    @property
    def index_sets(self) -> List[int]:
        """Get the index sets."""
        return [i + 1 for i in range(self.outcomeSlotCount)]


@dataclasses.dataclass
class Answer:
    """A structure for an OMEN answer."""

    answer: str
    bondAggregate: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self.bondAggregate = int(self.bondAggregate)

    @property
    def answer_bytes(self) -> bytes:
        """Get the answer in bytes."""
        return bytes.fromhex(self.answer[2:])


@dataclasses.dataclass
class AnswerData:
    """A structure for the answers' data."""

    answers: List[bytes]
    bonds: List[int]


@dataclasses.dataclass
class Question:
    """A structure for an OMEN question."""

    id: bytes
    data: str
    answers: List[Answer]

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        if isinstance(self.answers, list):
            self.answers = [Answer(**cast(dict, answer)) for answer in self.answers]

        if isinstance(self.id, str):
            self.id = bytes.fromhex(self.id[2:])

    @property
    def answer_data(self) -> AnswerData:
        """Get the answers' data."""
        answers, bonds = [], []
        for answer in self.answers:
            answers.append(answer.answer_bytes)
            bonds.append(answer.bondAggregate)

        return AnswerData(answers, bonds)


@dataclasses.dataclass
class FPMM:
    """A structure for an OMEN FPMM."""

    collateralToken: str
    condition: Condition
    creator: str
    currentAnswer: str
    question: Question
    templateId: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self.templateId = int(self.templateId)

        if isinstance(self.condition, dict):
            self.condition = Condition(**self.condition)

        if isinstance(self.question, dict):
            self.question = Question(**self.question)

    @property
    def current_answer_index(self) -> int:
        """Get the index of the market's current answer."""
        return int(self.currentAnswer, 16)


@dataclasses.dataclass
class RedeemInfo:
    """A structure with redeeming information."""

    fpmm: FPMM
    outcomeIndex: int
    outcomeTokenMarginalPrice: float
    outcomeTokensTraded: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self.outcomeIndex = int(self.outcomeIndex)
        self.outcomeTokenMarginalPrice = float(self.outcomeTokenMarginalPrice)
        self.outcomeTokensTraded = int(self.outcomeTokensTraded)

        if isinstance(self.fpmm, dict):
            self.fpmm = FPMM(**self.fpmm)

    @property
    def claimable_amount(self) -> int:
        """Get the claimable amount of the current market."""
        return int(self.outcomeTokenMarginalPrice * self.outcomeTokensTraded)
