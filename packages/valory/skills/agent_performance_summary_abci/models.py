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

import builtins
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

from packages.valory.protocols.http import HttpMessage
from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
)


AGENT_PERFORMANCE_SUMMARY_FILE = "agent_performance.json"


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


class AgentPerformanceSummaryParams(BaseParams):
    """Agent Performance Summary's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.coingecko_olas_in_usd_price_url: str = self._ensure(
            "coingecko_olas_in_usd_price_url", kwargs, str
        )
        self.store_path: Path = self.get_store_path(kwargs)
        super().__init__(*args, **kwargs)

    def get_store_path(self, kwargs: Dict) -> Path:
        """Get the path of the store."""
        path = self._ensure("store_path", kwargs, str)
        # check if path exists, and we can write to it
        if (
            not os.path.isdir(path)
            or not os.access(path, os.W_OK)
            or not os.access(path, os.R_OK)
        ):
            raise ValueError(
                f"Policy store path {path!r} is not a directory or is not writable."
            )
        return Path(path)


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls: Type[AbciApp] = AgentPerformanceSummaryAbciApp

    @property
    def params(self) -> AgentPerformanceSummaryParams:
        """Return the params."""
        return cast(AgentPerformanceSummaryParams, self.context.params)

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(
            self.context.state.round_sequence.last_round_transition_timestamp.timestamp()
        )

    def read_existing_performance_summary(self) -> AgentPerformanceSummary:
        """Read the existing agent performance summary from a file."""
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        try:
            with open(file_path, "r") as f:
                existing_data = AgentPerformanceSummary(**json.load(f))
            return existing_data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.context.logger.warning(
                f"Could not read existing agent performance summary: {e}"
            )
            return AgentPerformanceSummary()

    def overwrite_performance_summary(self, summary: AgentPerformanceSummary) -> None:
        """Write the agent performance summary to a file."""
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE

        with open(file_path, "w") as f:
            json.dump(asdict(summary), f, indent=4)

    def update_agent_behavior(self, behavior: str) -> None:
        """Update the agent behavior in agent performance template file."""
        existing_data = self.read_existing_performance_summary()
        existing_data.agent_behavior = behavior
        existing_data.timestamp = self.synced_timestamp
        self.overwrite_performance_summary(existing_data)


class Subgraph(ApiSpecs):
    """Specifies `ApiSpecs` with common functionality for subgraphs."""

    def process_response(self, response: HttpMessage) -> Any:
        """Process the response."""
        res = super().process_response(response)
        if res is not None:
            return res

        error_data = self.response_info.error_data
        expected_error_type = getattr(builtins, self.response_info.error_type)
        if isinstance(error_data, expected_error_type):
            error_message_key = self.context.params.the_graph_error_message_key
            error_message = error_data.get(error_message_key, None)
            if self.context.params.the_graph_payment_required_error in error_message:
                err = "Payment required for subsequent requests for the current 'The Graph' API key!"
                self.context.logger.error(err)
        return None


class OlasAgentsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Olas Agent's subgraph specifications for trades."""


class OlasMechSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Olas Mech's subgraph specifications."""


class GnosisStakingSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Gnosis Staking's subgraph specifications."""


class OpenMarketsSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Open Markets subgraph specifications."""
