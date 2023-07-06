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

from dataclasses import dataclass
from string import Template
from typing import Optional

from aea.skills.tasks import Task
from mech_client.interact import interact

BET_PROMPT = Template(
    """
    With the given question "${question}" 
    and the `yes` option represented by ${yes} 
    and the `no` option represented by ${no}, 
    what are the respective probabilities of `p_yes` and `p_no` occurring?
    """
)


@dataclass
class PredictionResponse:
    """A response of a prediction."""

    p_yes: float
    p_no: float
    confidence: float
    info_utility: float

    def __post_init__(self):
        """Runs checks on whether the current prediction response is valid or not."""
        # all the fields are probabilities
        probabilities = (getattr(self, field) for field in self.__annotations__)
        if (
            any(not (0 <= prob <= 1) for prob in probabilities)
            or self.p_yes + self.p_no != 1
        ):
            raise ValueError("Invalid prediction response initialization.")


@dataclass
class MechInteractionResponse:
    """A structure for the response of a mech interaction task."""

    prediction: Optional[PredictionResponse] = None
    message: str = "Success"


class MechInteractionTask(Task):
    """Perform an interaction with a mech."""

    def execute(
        self,
        question: str,
        yes: str,
        no: str,
        agent_id: int,
        tool: str,
        private_key_path: str,
    ) -> MechInteractionResponse:
        """Execute the task."""
        prompt = BET_PROMPT.substitute(question=question, yes=yes, no=no)
        res = interact(prompt, agent_id, tool, private_key_path)

        try:
            prediction = PredictionResponse(**res)
        except (ValueError, TypeError):
            error_msg = f"The response's format was unexpected: {res}"
            return MechInteractionResponse(message=error_msg)
        else:
            return MechInteractionResponse(prediction)
