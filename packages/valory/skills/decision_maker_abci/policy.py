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

"""This module contains an Epsilon Greedy Policy implementation."""

import json
import random
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, List, Optional, Union


RandomnessType = Union[int, float, str, bytes, bytearray, None]


class DataclassEncoder(json.JSONEncoder):
    """A custom JSON encoder for dataclasses."""

    def default(self, o: Any) -> Any:
        """The default JSON encoder."""
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)


def argmax(li: List) -> int:
    """Get the index of the max value within the provided list."""
    return li.index((max(li)))


@dataclass
class AccuracyInfo:
    """The accuracy information of a tool."""

    # the number of requests that this tool has responded to
    requests: int = 0
    # the number of pending evaluations, i.e., responses for which we have not redeemed yet
    pending: int = 0
    # the accuracy of the tool
    accuracy: float = 0.0


class EGreedyPolicyDecoder(json.JSONDecoder):
    """A custom JSON decoder for the e greedy policy."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the custom JSON decoder."""
        super().__init__(object_hook=self.hook, *args, **kwargs)

    @staticmethod
    def hook(
        data: Dict[str, Any]
    ) -> Union["EGreedyPolicy", AccuracyInfo, Dict[str, "EGreedyPolicy"]]:
        """Perform the custom decoding."""
        for cls_ in (AccuracyInfo, EGreedyPolicy):
            cls_attributes = cls_.__annotations__.keys()  # pylint: disable=no-member
            if sorted(cls_attributes) == sorted(data.keys()):
                # if the attributes match the ones of the current class, use it to perform the deserialization
                return cls_(**data)

        return data


@dataclass
class EGreedyPolicy:
    """An e-Greedy policy for the tool selection based on tool accuracy."""

    eps: float
    accuracy_store: Dict[str, AccuracyInfo] = field(default_factory=dict)
    weighted_accuracy: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Perform post-initialization checks."""
        if not (0 <= self.eps <= 1):
            error = f"Cannot initialize the policy with an epsilon value of {self.eps}. Must be between 0 and 1."
            raise ValueError(error)
        self.update_weighted_accuracy()

    @classmethod
    def deserialize(cls, policy: str) -> "EGreedyPolicy":
        """Deserialize a string to an `EGreedyPolicy` object."""
        return json.loads(policy, cls=EGreedyPolicyDecoder)

    @property
    def tools(self) -> List[str]:
        """Get the number of the policy's tools."""
        return list(self.accuracy_store.keys())

    @property
    def n_tools(self) -> int:
        """Get the number of the policy's tools."""
        return len(self.accuracy_store)

    @property
    def n_requests(self) -> int:
        """Get the total number of requests."""
        return sum(acc_info.requests for acc_info in self.accuracy_store.values())

    @property
    def has_updated(self) -> bool:
        """Whether the policy has ever been updated since its genesis or not."""
        return self.n_requests > 0

    @property
    def random_tool(self) -> str:
        """Get the name of a tool randomly."""
        return random.choice(list(self.accuracy_store.keys()))  # nosec

    @property
    def best_tool(self) -> str:
        """Get the best tool."""
        weighted_accuracy = list(self.weighted_accuracy.values())
        best = argmax(weighted_accuracy)
        return self.tools[best]

    def update_weighted_accuracy(self) -> None:
        """Update the weighted accuracy for each tool."""
        self.weighted_accuracy = {
            tool: (acc_info.accuracy / 100)
            * (acc_info.requests - acc_info.pending)
            / self.n_requests
            for tool, acc_info in self.accuracy_store.items()
        }

    def select_tool(self, randomness: RandomnessType = None) -> Optional[str]:
        """Select a Mech tool and return its index."""
        if self.n_tools == 0:
            return None

        if randomness is not None:
            random.seed(randomness)

        if not self.has_updated or random.random() < self.eps:  # nosec
            return self.random_tool

        return self.best_tool

    def tool_used(self, tool: str) -> None:
        """Increase the times used for the given tool."""
        self.accuracy_store[tool].pending += 1
        self.update_weighted_accuracy()

    def update_accuracy_store(self, tool: str) -> None:
        """Update the accuracy store for the given tool."""
        self.accuracy_store[tool].requests += 1
        self.accuracy_store[tool].pending -= 1
        self.update_weighted_accuracy()

    def serialize(self) -> str:
        """Return the accuracy policy serialized."""
        return json.dumps(self, cls=DataclassEncoder, sort_keys=True)

    def stats_report(self) -> str:
        """Report policy statistics."""
        if not self.has_updated:
            return "No policy statistics available."

        report = "Policy statistics so far (only for resolved markets):\n"
        stats = (
            f"{tool} tool:\n"
            f"\tTimes used: {self.accuracy_store[tool].requests}\n"
            f"\tWeighted Accuracy: {self.weighted_accuracy[tool]}"
            for tool in self.tools
        )
        report += "\n".join(stats)
        report += f"Best tool so far is {self.best_tool!r}."
        return report
