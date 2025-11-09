# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""This module contains the behaviour of the skill which is responsible for selecting a mech tool."""

import json
from typing import Generator, Optional

from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    StorageManagerBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import ToolSelectionPayload
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)


class ToolSelectionBehaviour(StorageManagerBehaviour):
    """A behaviour in which the agents select a mech tool."""

    matching_round = ToolSelectionRound

    def _select_tool(self) -> Generator[None, None, Optional[str]]:
        """Select a Mech tool based on an e-greedy policy and return its index."""
        success = yield from self._setup_policy_and_tools()
        if not success:
            return None

        # If chat UI mech tool is provided, use it directly and skip randomness/policy.
        chatui_mech_tool = self.shared_state.chatui_config.mech_tool
        if chatui_mech_tool is not None:
            selected_tool = self.shared_state.chatui_config.mech_tool
        else:
            randomness = (
                (self.benchmarking_mode.randomness if self.is_first_period else None)
                if self.benchmarking_mode.enabled
                else self.synchronized_data.most_voted_randomness
            )
            selected_tool = self.policy.select_tool(randomness)

        self.context.logger.info(f"Selected the mech tool {selected_tool!r}.")
        return selected_tool

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            mech_tools = policy = utilized_tools = None
            selected_tool = yield from self._select_tool()
            if selected_tool is not None:
                # the period will increment when the benchmarking finishes
                benchmarking_running = self.synchronized_data.period_count == 0
                if (
                    self.benchmarking_mode.enabled
                    and benchmarking_running
                    and not self.shared_state.last_benchmarking_has_run
                ):
                    self.policy.tool_used(selected_tool)
                mech_tools = json.dumps(self.mech_tools)
                policy = self.policy.serialize()
                utilized_tools = json.dumps(self.utilized_tools, sort_keys=True)
                self._store_all()

            payload = ToolSelectionPayload(
                self.context.agent_address,
                mech_tools,
                policy,
                utilized_tools,
                selected_tool,
            )

        yield from self.finish_behaviour(payload)
