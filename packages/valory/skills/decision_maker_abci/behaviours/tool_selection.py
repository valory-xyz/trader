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

    def _select_tool(self) -> Generator[None, None, Optional[int]]:
        """Select a Mech tool based on an e-greedy policy and return its index."""
        success = yield from self._setup_policy_and_tools()
        if not success:
            return None

        randomness = self.synchronized_data.most_voted_randomness
        if self.benchmarking_mode.enabled:
            selected_idx = self.accuracy_policy.select_tool(randomness)
        else:
            selected_idx = self.policy.select_tool(randomness)
        selected = self.mech_tools[selected_idx] if selected_idx is not None else "NaN"
        self.context.logger.info(f"Selected the mech tool {selected!r}.")
        return selected_idx

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            mech_tools = policy = utilized_tools = None
            selected_tool = yield from self._select_tool()
            if selected_tool is not None:
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
