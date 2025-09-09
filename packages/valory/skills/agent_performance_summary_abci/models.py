#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the models for the skill."""

from dataclasses import dataclass, field
from typing import Any, List, Optional, Type

from aea.skills.base import SkillContext

from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
)


@dataclass
class AgentPerformanceMetrics:
    """Agent performance metrics."""

    name: str
    is_primary: bool
    value: str  # eg. "75%"
    description: Optional[str] = (
        None  # Can have HTML tags like <b>bold</b> or <i>italic</i>
    )


@dataclass
class AgentPerformanceSummary:
    """
    Agent performance summary.

    - If the agent has any activity, fields will be filled.
    - Otherwise, initial state with nulls and empty arrays.
    """

    timestamp: Optional[int] = None  # UNIX timestamp (in seconds, UTC)
    metrics: List[AgentPerformanceMetrics] = field(default_factory=list)
    agent_behavior: Optional[str] = None


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls: Type[AbciApp] = AgentPerformanceSummaryAbciApp

    def __init__(self, *args: Any, skill_context: SkillContext, **kwargs: Any) -> None:
        """Initialize the state."""
        super().__init__(*args, skill_context=skill_context, **kwargs)
