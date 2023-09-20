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

"""This module contains the behaviour of the skill which is responsible for selecting a mech tool."""

import json
from typing import Any, Generator, List, Optional

from packages.valory.contracts.agent_registry.contract import AgentRegistryContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    CID_PREFIX,
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import (
    AgentToolsSpecs,
    EGreedyPolicy,
)
from packages.valory.skills.decision_maker_abci.payloads import ToolSelectionPayload
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)


class ToolSelectionBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents select a mech tool."""

    matching_round = ToolSelectionRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._mech_id: int = 0
        self._mech_hash: str = ""
        self.mech_tools: Optional[List[str]] = None

    @property
    def mech_id(self) -> int:
        """Get the mech's id."""
        return self._mech_id

    @mech_id.setter
    def mech_id(self, mech_id: int) -> None:
        """Set the mech's id."""
        self._mech_id = mech_id

    @property
    def mech_hash(self) -> str:
        """Get the hash of the mech agent."""
        return self._mech_hash

    @mech_hash.setter
    def mech_hash(self, mech_hash: str) -> None:
        """Set the hash of the mech agent."""
        self._mech_hash = mech_hash

    @property
    def mech_tools_api(self) -> AgentToolsSpecs:
        """Get the mech agent api specs."""
        return self.context.agent_tools

    def set_mech_agent_specs(self) -> None:
        """Set the mech's agent specs."""
        full_ipfs_hash = CID_PREFIX + self.mech_hash
        ipfs_link = self.params.ipfs_address + full_ipfs_hash
        # The url needs to be dynamically generated as it depends on the ipfs hash
        self.mech_tools_api.__dict__["_frozen"] = False
        self.mech_tools_api.url = ipfs_link
        self.mech_tools_api.__dict__["_frozen"] = True

    def _get_mech_id(self) -> WaitableConditionType:
        """Get the mech's id."""
        result = yield from self._mech_contract_interact(
            contract_callable="get_mech_id",
            data_key="id",
            placeholder=get_name(ToolSelectionBehaviour.mech_id),
        )

        return result

    def _get_mech_hash(self) -> WaitableConditionType:
        """Get the mech's hash."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.agent_registry_address,
            contract_public_id=AgentRegistryContract.contract_id,
            contract_callable="get_hash",
            data_key="hash",
            placeholder=get_name(ToolSelectionBehaviour.mech_hash),
            agent_id=self.mech_id,
        )
        return result

    def _get_mech_tools(self) -> WaitableConditionType:
        """Get the mech agent's tools from IPFS."""
        specs = self.mech_tools_api.get_spec()
        res_raw = yield from self.get_http_response(**specs)
        res = self.mech_tools_api.process_response(res_raw)

        if self.mech_tools_api.is_retries_exceeded():
            error = "Retries were exceeded while trying to get the mech agent's data."
            self.context.logger.error(error)
            return True

        if res is None:
            msg = f"Could not get the mech agent's tools from {self.mech_tools_api.api_id}"
            self.context.logger.error(msg)
            self.mech_tools_api.increment_retries()
            return False

        self.context.logger.info(f"Retrieved the mech agent's tools: {res}.")
        if len(res) == 0:
            res = None
            self.context.logger.error("The mech agent's tools are empty!")
        self.mech_tools = res
        self.mech_tools_api.reset_retries()
        return True

    def _get_tools(
        self,
    ) -> Generator[None, None, None]:
        """Get the Mech's tools."""
        for step in (
            self._get_mech_id,
            self._get_mech_hash,
            self._get_mech_tools,
        ):
            yield from self.wait_for_condition_with_sleep(step)

    def _adjust_policy_tools(self, tools: List[str]) -> None:
        """Add or remove tools from the policy to match the remote tools."""
        # remove tools if they are not available anymore
        local = set(self.synchronized_data.available_mech_tools)
        remote = set(tools)
        relevant_remote = remote - self.params.irrelevant_tools
        removed_tools_idx = [
            idx for idx, tool in enumerate(local) if tool not in relevant_remote
        ]
        if len(removed_tools_idx) > 0:
            self.policy.remove_tools(removed_tools_idx)

        # add tools if there are new ones available
        new_tools = remote - local
        n_new_tools = len(new_tools)
        if n_new_tools > 0:
            self.policy.add_new_tools(n_new_tools)

    def _set_policy(self, tools: List[str]) -> None:
        """Set the E Greedy Policy."""
        if self.synchronized_data.period_count == 0:
            self._policy = EGreedyPolicy.initial_state(self.params.epsilon, len(tools))
        else:
            self._policy = self.synchronized_data.policy
            self._adjust_policy_tools(tools)

    def _select_tool(self) -> Generator[None, None, Optional[int]]:
        """Select a Mech tool based on an e-greedy policy and return its index."""
        yield from self._get_tools()
        if self.mech_tools is None:
            return None

        self._set_policy(self.mech_tools)
        return self.policy.select_tool()

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            mech_tools = policy = None
            selected_tool = yield from self._select_tool()
            if selected_tool is not None:
                mech_tools = json.dumps(self.mech_tools)
                policy = self.policy.serialize()

            payload = ToolSelectionPayload(
                self.context.agent_address,
                mech_tools,
                policy,
                selected_tool,
            )

        yield from self.finish_behaviour(payload)
