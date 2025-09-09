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

"""This module contains the behaviour of the skill which is responsible for agent performance summary file updation."""

import json
from dataclasses import asdict
from typing import Any, Generator, Optional, Set, Type

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AgentPerformanceSummary,
)
from packages.valory.skills.agent_performance_summary_abci.payloads import (
    FetchPerformanceDataPayload,
)
from packages.valory.skills.agent_performance_summary_abci.rounds import (
    AgentPerformanceSummaryAbciApp,
    FetchPerformanceDataRound,
)


AGENT_PERFORMANCE_SUMMARY_FILE = "agent_performance.json"


class FetchPerformanceSummaryBehaviour(BaseBehaviour):
    """A behaviour to fetch and store the agent performance summary file."""

    matching_round = FetchPerformanceDataRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._agent_performance_summary: Optional[AgentPerformanceSummary] = None

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(
            self.context.state.round_sequence.last_round_transition_timestamp.timestamp()
        )

    def _fetch_agent_performance_summary(self) -> Optional[AgentPerformanceSummary]:
        """Fetch the agent performance summary"""
        current_timestamp = self.synced_timestamp

        performance_summary_data = {
            "timestamp": current_timestamp,
            "metrics": [
                {
                    "name": "Total ROI",
                    "is_primary": True,
                    "description": "With staking rewards included",
                    "value": "88%",
                },
                {
                    "name": "Partial ROI",
                    "is_primary": False,
                    "description": "Clean ROI without staking rewards",
                    "value": "88%",
                },
                {
                    "name": "Prediction accuracy",
                    "is_primary": False,
                    "description": "Percentage of correct predictions",
                    "value": "55.9%",
                },
            ],
            "agent_behavior": "Balanced strategy that spreads predictions, limits risk, and aims for consistent wins.",
        }
        self._agent_performance_summary = AgentPerformanceSummary(
            **performance_summary_data
        )

    def _save_agent_performance_summary(self, agent_performance_summary) -> None:
        """Save the agent performance summary to a file."""
        file_path = self.params.store_path / AGENT_PERFORMANCE_SUMMARY_FILE
        with open(file_path, "w") as f:
            json.dump(
                asdict(agent_performance_summary),
                f,
                indent=2,
            )
        self.context.logger.info(f"Agent performance summary saved to {file_path}.")

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():

            self._fetch_agent_performance_summary()

            if self._agent_performance_summary is None:
                self.context.logger.warning(
                    "Agent performance summary could not be fetched. Saving default values"
                )
                self._agent_performance_summary = AgentPerformanceSummary()

            self._save_agent_performance_summary(self._agent_performance_summary)

            payload = FetchPerformanceDataPayload(
                sender=self.context.agent_address,
                vote=True,
            )

        yield from self.finish_behaviour(payload)

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class AgentPerformanceSummaryRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the AgentPerformanceSummary behaviour."""

    initial_behaviour_cls = FetchPerformanceSummaryBehaviour
    abci_app_cls = AgentPerformanceSummaryAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {FetchPerformanceSummaryBehaviour}  # type: ignore
