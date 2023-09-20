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

"""This module contains an Epsilon Greedy Policy implementation."""

import json
import random
from dataclasses import is_dataclass, asdict, dataclass
from typing import Any, List, Optional


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
class EGreedyPolicy:
    """An e-Greedy policy for the tool selection."""

    eps: float
    n_tools: int
    counts: List[int]
    rewards: List[float]

    @classmethod
    def initial_state(cls, eps: float, n_tools: int) -> "EGreedyPolicy":
        """Return an instance on its initial state."""
        if n_tools == 0:
            error = f"Cannot initialize an e Greedy Policy with {n_tools=}"
            raise ValueError(error)

        return EGreedyPolicy(eps, n_tools, [0] * n_tools, [0.0] * n_tools)

    @classmethod
    def deserialize(cls, policy: str) -> "EGreedyPolicy":
        """Deserialize a string to an `EGreedyPolicy` object."""
        return EGreedyPolicy(**json.loads(policy))

    @property
    def random_tool(self) -> int:
        """Get the index of a tool randomly."""
        return random.randrange(self.n_tools)  # nosec

    @property
    def reward_rates(self) -> List[float]:
        """Get the reward rates."""
        return [reward / count for reward, count in zip(self.rewards, self.counts)]

    def add_new_tools(self, n_new: int) -> None:
        """Add new tools to the current policy."""
        self.n_tools += n_new
        self.counts.extend([0] * n_new)
        self.rewards.extend([0.0] * n_new)

    def remove_tools(self, indexes: List[int]) -> None:
        """Remove the knowledge for the tools corresponding to the given indexes."""
        self.n_tools -= len(indexes)
        for i in indexes:
            try:
                del self.counts[i]
                del self.rewards[i]
            except IndexError as exc:
                error = "Attempted to remove tools using incorrect indexes!"
                raise ValueError(error) from exc

    def select_tool(self) -> Optional[int]:
        """Select a Mech tool and return its index."""
        if self.n_tools == 0:
            return None

        if sum(self.counts) == 0 or random.random() < self.eps:  # nosec
            return self.random_tool

        return argmax(self.reward_rates)

    def add_reward(self, index: int, reward: float) -> None:
        """Add a reward for the tool corresponding to the given index."""
        self.counts[index] += 1
        self.rewards[index] += reward

    def serialize(self) -> str:
        """Return the policy serialized."""
        return json.dumps(self, cls=DataclassEncoder, sort_keys=True)
