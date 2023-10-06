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
from typing import Any, Dict, Generator, List, Optional

from packages.valory.contracts.agent_registry.contract import AgentRegistryContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    CID_PREFIX,
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import AgentToolsSpecs
from packages.valory.skills.decision_maker_abci.payloads import ToolSelectionPayload
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)


class ToolSelectionBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents select a mech tool."""

    matching_round = ToolSelectionRound

    POLICY_STORE = "policy_store.json"
    AVAILABLE_TOOLS_STORE = "available_tools_store.json"
    UTILIZED_TOOLS_STORE = "utilized_tools.json"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._mech_id: int = 0
        self._mech_hash: str = ""
        self._mech_tools: Optional[List[str]] = None

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
    def mech_tools(self) -> List[str]:
        """Get the mech agent's tools."""
        if self._mech_tools is None:
            raise ValueError("The mech's tools have not been set.")
        return self._mech_tools

    @mech_tools.setter
    def mech_tools(self, mech_tools: List[str]) -> None:
        """Set the mech agent's tools."""
        self._mech_tools = mech_tools

    @property
    def utilized_tools(self) -> Dict[str, int]:
        """Get the utilized tools."""
        if self.is_first_period:
            tools = self._try_recover_utilized_tools()
            if tools is not None:
                return tools
            return {}
        return self.synchronized_data.utilized_tools

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
        self.set_mech_agent_specs()
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
        # keep only the relevant mech tools, sorted
        # we sort the tools to avoid using dictionaries in the policy implementation,
        # so that we can easily assess which index corresponds to which tool
        res = sorted(set(res) - self.params.irrelevant_tools)
        self.context.logger.info(f"Relevant tools to the prediction task: {res}.")

        if len(res) == 0:
            self.context.logger.error("The relevant mech agent's tools are empty!")
            return False
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

    def _adjust_policy_tools(self) -> None:
        """Add or remove tools from the policy to match the remote tools."""
        local = self.synchronized_data.available_mech_tools

        # remove tools if they are not available anymore
        # process the indices in reverse order to avoid index shifting when removing the unavailable tools later
        reversed_idx = range(len(local) - 1, -1, -1)
        removed_idx = [idx for idx in reversed_idx if local[idx] not in self.mech_tools]
        self.policy.remove_tools(removed_idx)

        # add tools if there are new ones available
        # process the indices in reverse order to avoid index shifting when adding the new tools later
        reversed_idx = range(len(self.mech_tools) - 1, -1, -1)
        new_idx = [idx for idx in reversed_idx if self.mech_tools[idx] not in local]
        self.policy.add_new_tools(new_idx)

    def _set_policy(self) -> None:
        """Set the E Greedy Policy."""
        if self.is_first_period:
            self._policy = self._get_init_policy()
            recovered_tools = self._try_recover_mech_tools()
            self.mech_tools = list(set(self.mech_tools + recovered_tools))
        else:
            self._policy = self.synchronized_data.policy
            self._adjust_policy_tools()

    def _get_init_policy(self) -> EGreedyPolicy:
        """Get the initial policy"""
        # try to read the policy from the policy store
        policy = self._try_recover_policy()
        if policy is not None:
            # we successfully recovered the policy, so we return it
            return policy

        # we could not recover the policy, so we create a new one
        n_relevant = len(self.mech_tools)
        policy = EGreedyPolicy.initial_state(self.params.epsilon, n_relevant)
        return policy

    def _try_recover_policy(self) -> Optional[EGreedyPolicy]:
        """Try to recover the policy from the policy store."""
        try:
            policy_path = self.params.policy_store_path / self.POLICY_STORE
            with open(policy_path, "r") as f:
                policy = f.read()
                return EGreedyPolicy.deserialize(policy)
        except Exception as e:
            self.context.logger.warning(f"Could not recover the policy: {e}.")
            return None

    def _try_recover_utilized_tools(self) -> Optional[Dict[str, Any]]:
        """Try to recover the available tools from the tools store."""
        try:
            tools_path = self.params.policy_store_path / self.UTILIZED_TOOLS_STORE
            with open(tools_path, "r") as f:
                tools = json.load(f)
                return tools
        except Exception as e:
            self.context.logger.warning(f"Could not recover the tools: {e}.")
            return None

    def _try_recover_mech_tools(self) -> List[str]:
        """Try to recover the available tools from the tools store."""
        try:
            tools_path = self.params.policy_store_path / self.AVAILABLE_TOOLS_STORE
            with open(tools_path, "r") as f:
                tools = json.load(f)
                return tools
        except Exception as e:
            self.context.logger.warning(f"Could not recover the tools: {e}.")
            return []

    def _select_tool(self) -> Generator[None, None, Optional[int]]:
        """Select a Mech tool based on an e-greedy policy and return its index."""
        yield from self._get_tools()
        self._set_policy()
        selected_idx = self.policy.select_tool()
        selected = self.mech_tools[selected_idx] if selected_idx is not None else "NaN"
        self.context.logger.info(f"Selected the mech tool {selected!r}.")
        return selected_idx

    def _store_policy(self) -> None:
        """Store the policy"""
        policy_path = self.params.policy_store_path / self.POLICY_STORE
        with open(policy_path, "w") as f:
            f.write(self.policy.serialize())

    def _store_available_mech_tools(self) -> None:
        """Store the policy"""
        policy_path = self.params.policy_store_path / self.AVAILABLE_TOOLS_STORE
        with open(policy_path, "w") as f:
            json.dump(self.mech_tools, f)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            mech_tools = policy = utilized_tools = None
            selected_tool = yield from self._select_tool()
            if selected_tool is not None:
                mech_tools = json.dumps(self.mech_tools)
                policy = self.policy.serialize()
                utilized_tools = json.dumps(self.utilized_tools, sort_keys=True)

            payload = ToolSelectionPayload(
                self.context.agent_address,
                mech_tools,
                policy,
                utilized_tools,
                selected_tool,
            )

        self._store_policy()
        self._store_available_mech_tools()
        yield from self.finish_behaviour(payload)
