# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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
from time import time
from typing import Any, Dict, List, Optional, Tuple, Union

from packages.valory.skills.decision_maker_abci.utils.scaling import scale_value


RandomnessType = Union[int, float, str, bytes, bytearray, None]

VOLUME_FACTOR_REGULARIZATION = 0.1
UNSCALED_WEIGHTED_ACCURACY_INTERVAL = (-0.5, 80.5)
SCALED_WEIGHTED_ACCURACY_INTERVAL = (0, 1)


class DataclassEncoder(json.JSONEncoder):
    """A custom JSON encoder for dataclasses."""

    def default(self, o: Any) -> Any:
        """The default JSON encoder."""
        if is_dataclass(o):
            return asdict(o)
        return super().default(o)


def argmax(li: Union[Tuple, List]) -> int:
    """Get the index of the max value within the provided tuple or list."""
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


@dataclass
class ConsecutiveFailures:
    """The consecutive failures of a tool."""

    n_failures: int = 0
    timestamp: int = 0

    def increase(self, timestamp: int) -> None:
        """Increase the number of consecutive failures."""
        self.n_failures += 1
        self.timestamp = timestamp

    def reset(self, timestamp: int) -> None:
        """Reset the number of consecutive failures."""
        self.n_failures = 0
        self.timestamp = timestamp

    def update_status(self, timestamp: int, has_failed: bool) -> None:
        """Update the number of consecutive failures."""
        if has_failed:
            self.increase(timestamp)
        else:
            self.reset(timestamp)


class EGreedyPolicyDecoder(json.JSONDecoder):
    """A custom JSON decoder for the e greedy policy."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the custom JSON decoder."""
        super().__init__(object_hook=self.hook, *args, **kwargs)

    @staticmethod
    def hook(
        data: Dict[str, Any],
    ) -> Union[
        "EGreedyPolicy",
        AccuracyInfo,
        ConsecutiveFailures,
        Dict[str, "EGreedyPolicy"],
        Dict[str, ConsecutiveFailures],
    ]:
        """Perform the custom decoding."""
        for cls_ in (AccuracyInfo, ConsecutiveFailures, EGreedyPolicy):
            cls_attributes = cls_.__annotations__.keys()  # pylint: disable=no-member
            if sorted(cls_attributes) == sorted(data.keys()):
                # if the attributes match the ones of the current class, use it to perform the deserialization
                return cls_(**data)

        return data


@dataclass
class EGreedyPolicy:
    """An e-Greedy policy for the tool selection based on tool accuracy."""

    eps: float
    consecutive_failures_threshold: int
    quarantine_duration: int
    accuracy_store: Dict[str, AccuracyInfo] = field(default_factory=dict)
    weighted_accuracy: Dict[str, float] = field(default_factory=dict)
    consecutive_failures: Dict[str, ConsecutiveFailures] = field(default_factory=dict)
    updated_ts: int = 0

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
        """Get the policy's tools."""
        return list(self.accuracy_store.keys())

    @property
    def n_tools(self) -> int:
        """Get the number of the policy's tools."""
        return len(self.accuracy_store)

    @property
    def n_requests(self) -> int:
        """Get the total number of requests."""
        return sum(
            acc_info.requests + acc_info.pending
            for acc_info in self.accuracy_store.values()
        )

    @property
    def has_updated(self) -> bool:
        """Whether the policy has ever been updated since its genesis or not."""
        return self.n_requests > 0

    @property
    def random_tool(self) -> str:
        """Get the name of a tool randomly."""
        return random.choice(list(self.accuracy_store.keys()))  # nosec

    def is_quarantined(self, tool: str) -> bool:
        """Check if the policy is valid."""
        if tool not in self.consecutive_failures:
            return False

        failures = self.consecutive_failures[tool]
        return (
            failures.n_failures > self.consecutive_failures_threshold
            and failures.timestamp + self.quarantine_duration > int(time())
        )

    @property
    def valid_tools(self) -> List[str]:
        """Get the policy's tools."""
        return list(
            tool for tool in self.accuracy_store.keys() if not self.is_quarantined(tool)
        )

    @property
    def valid_weighted_accuracy(self) -> Dict[str, float]:
        """Get the valid weighted accuracy."""
        if not self.weighted_accuracy:
            # Log or raise an error if no tools are present
            raise ValueError(
                "Weighted accuracy is empty. Ensure tools are initialized."
            )
        return {
            tool: acc
            for tool, acc in self.weighted_accuracy.items()
            if not self.is_quarantined(tool)
        }

    @property
    def best_tool(self) -> Optional[str]:
        """Get the best non-quarantined tool, or fallback gracefully."""
        # Get valid weighted accuracies
        valid_weighted_accuracy = self.valid_weighted_accuracy
        if valid_weighted_accuracy:
            valid_tools, valid_weighted_accuracies = zip(
                *valid_weighted_accuracy.items()
            )
        else:
            # Fallback to all tools if no valid tools are available
            valid_tools, valid_weighted_accuracies = zip(
                *self.weighted_accuracy.items()
            )

        # Determine the best tool based on weighted accuracies
        best_index = argmax(valid_weighted_accuracies)
        return valid_tools[best_index]

    def update_weighted_accuracy(self) -> None:
        """Update the weighted accuracy for each tool."""
        self.weighted_accuracy = {
            tool: scale_value(
                (
                    acc_info.accuracy
                    + ((acc_info.requests - acc_info.pending) / self.n_requests)
                    * VOLUME_FACTOR_REGULARIZATION
                ),
                UNSCALED_WEIGHTED_ACCURACY_INTERVAL,
                SCALED_WEIGHTED_ACCURACY_INTERVAL,
            )
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

    def tool_responded(self, tool: str, timestamp: int, failed: bool = True) -> None:
        """Update the policy based on the given tool's response."""
        if tool not in self.consecutive_failures:
            self.consecutive_failures[tool] = ConsecutiveFailures()
        self.consecutive_failures[tool].update_status(timestamp, failed)

    def update_accuracy_store(self, tool: str, winning: bool) -> None:
        """Update the accuracy store for the given tool."""
        acc_info = self.accuracy_store[tool]
        total_correct_answers = acc_info.accuracy * acc_info.requests
        if winning:
            total_correct_answers += 1

        acc_info.requests += 1
        acc_info.pending -= 1
        acc_info.accuracy = total_correct_answers / acc_info.requests
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
            f"\t{tool} tool:\n"
            f"\t\tQuarantined: {self.is_quarantined(tool)}\n"
            f"\t\tTimes used: {self.accuracy_store[tool].requests}\n"
            f"\t\tWeighted Accuracy: {self.weighted_accuracy[tool]}"
            for tool in self.tools
        )
        report += "\n".join(stats)
        report += f"\nBest non-quarantined tool so far is {self.best_tool!r}."
        return report
