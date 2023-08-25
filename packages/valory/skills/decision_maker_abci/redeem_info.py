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
import json
from typing import List


@dataclasses.dataclass
class Condition:
    """A structure for an OMEN condition."""

    id: str
    outcomeSlotCount: int

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        self.outcomeSlotCount = int(self.outcomeSlotCount)

    @property
    def index_sets(self) -> List[str]:
        """Get the index sets."""
        return [str(i + 1) for i in range(self.outcomeSlotCount)]


@dataclasses.dataclass
class Answer:
    """A structure for an OMEN answer."""

    answer: str
    bondAggregate: str


@dataclasses.dataclass
class AnswerData:
    """A structure for the answers' data."""

    answers: List[str]
    bonds: List[str]


@dataclasses.dataclass
class Question:
    """A structure for an OMEN question."""

    id: str
    data: str
    answers: List[Answer]

    def __post_init__(self) -> None:
        """Post initialization to adjust the values."""
        if isinstance(self.answers, str):
            self.answers = [Answer(**answer) for answer in json.loads(self.answers)]

    @property
    def answer_data(self) -> AnswerData:
        """Get the answers' data."""
        answers, bonds = [], []
        for answer in self.answers:
            answers.append(answer.answer)
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

        if isinstance(self.condition, str):
            self.condition = Condition(**json.loads(self.condition))

        if isinstance(self.question, str):
            self.question = Question(**json.loads(self.question))

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

        if isinstance(self.fpmm, str):
            self.fpmm = FPMM(**json.loads(self.fpmm))

    @property
    def claimable_amount(self) -> float:
        """Get the claimable amount of the current market."""
        return self.outcomeTokenMarginalPrice * self.outcomeTokensTraded
