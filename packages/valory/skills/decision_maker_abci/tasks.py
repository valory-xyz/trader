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

"""Contains the background tasks of the decision maker skill."""

import json
from dataclasses import dataclass
from typing import Any, Optional

from aea.skills.tasks import Task
from mech_client.interact import interact


@dataclass
class PredictionResponse:
    """A response of a prediction."""

    p_yes: float
    p_no: float
    confidence: float
    info_utility: float

    def __post_init__(self) -> None:
        """Runs checks on whether the current prediction response is valid or not."""
        # all the fields are probabilities
        probabilities = (getattr(self, field) for field in self.__annotations__)
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


@dataclass
class MechInteractionResponse:
    """A structure for the response of a mech interaction task."""

    prediction: Optional[PredictionResponse] = None
    error: str = "Unknown"

    @classmethod
    def incorrect_format(cls, res: Any) -> "MechInteractionResponse":
        """Return an incorrect format response."""
        response = cls()
        response.error = f"The response's format was unexpected: {res}"
        return response


class MechInteractionTask(Task):
    """Perform an interaction with a mech."""

    def execute(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> MechInteractionResponse:
        """Execute the task."""
        res = interact(*args, **kwargs)

        try:
            prediction_result = res["result"]
            deserialized_prediction = json.loads(prediction_result)
            prediction = PredictionResponse(**deserialized_prediction)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            return MechInteractionResponse.incorrect_format(res)
        else:
            return MechInteractionResponse(prediction)
