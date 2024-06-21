# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains a behaviour for managing the storage of the agent."""

import json
import csv
from abc import ABC
from typing import Any, Dict, Generator, List, Optional, Tuple

from packages.valory.contracts.agent_registry.contract import AgentRegistryContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    CID_PREFIX,
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import AgentToolsSpecs
from packages.valory.skills.decision_maker_abci.policy import (
    EGreedyPolicy,
    EGreedyAccuracyPolicy,
)


POLICY_STORE = "policy_store.json"
AVAILABLE_TOOLS_STORE = "available_tools_store.json"
UTILIZED_TOOLS_STORE = "utilized_tools.json"
ACCURACY_STORE = "accuracy_store.json"


class StorageManagerBehaviour(DecisionMakerBaseBehaviour, ABC):
    """Manages the storage of the policy and the tools."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._mech_id: int = 0
        self._mech_hash: str = ""
        self._utilized_tools: Dict[str, int] = {}
        self._mech_tools: Optional[List[str]] = None

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
    def utilized_tools(self) -> Dict[str, int]:
        """Get the utilized tools."""
        return self._utilized_tools

    @utilized_tools.setter
    def utilized_tools(self, utilized_tools: Dict[str, int]) -> None:
        """Get the utilized tools."""
        self._utilized_tools = utilized_tools

    @property
    def mech_tools_api(self) -> AgentToolsSpecs:
        """Get the mech agent api specs."""
        return self.context.agent_tools

    def setup(self) -> None:
        """Set the behaviour up."""
        try:
            self.utilized_tools = self.synchronized_data.utilized_tools
        except Exception:
            self.utilized_tools = self._try_recover_utilized_tools()
        else:
            if self.utilized_tools is None:
                self.utilized_tools = self._try_recover_utilized_tools()

    def set_mech_agent_specs(self) -> None:
        """Set the mech's agent specs."""
        full_ipfs_hash = CID_PREFIX + self.mech_hash
        ipfs_link = self.params.ipfs_address + full_ipfs_hash
        # The url needs to be dynamically generated as it depends on the ipfs hash
        self.mech_tools_api.__dict__["_frozen"] = False
        self.mech_tools_api.url = ipfs_link
        self.mech_tools_api.__dict__["_frozen"] = True

    def _get_tools_from_benchmark_file(self) -> None:
        """Get the tools from the benchmark dataset."""
        dataset_filepath = (
            self.params.store_path / self.benchmarking_mode.dataset_filename
        )
        with open(dataset_filepath) as read_dataset:
            row = read_dataset.readline()
            if not row:
                # if no headers are in the file, then we finished the benchmarking
                self.context.logger.error("No headers in dataset file.")
                return

        # parse tools from headers
        headers = row.split(self.benchmarking_mode.sep)
        p_yes_part = self.benchmarking_mode.p_yes_field_part
        self.mech_tools = [
            header.replace(p_yes_part, "") for header in headers if p_yes_part in header
        ]

    def _get_mech_id(self) -> WaitableConditionType:
        """Get the mech's id."""
        result = yield from self._mech_contract_interact(
            contract_callable="get_mech_id",
            data_key="id",
            placeholder=get_name(StorageManagerBehaviour.mech_id),
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
            placeholder=get_name(StorageManagerBehaviour.mech_hash),
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
            self.mech_tools_api.reset_retries()
            return True

        if res is None:
            url = self.mech_tools_api.url
            msg = f"Could not get the mech agent's tools from {url}."
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
        if self.benchmarking_mode.enabled:
            self._get_tools_from_benchmark_file()
            return

        for step in (
            self._get_mech_id,
            self._get_mech_hash,
            self._get_mech_tools,
        ):
            yield from self.wait_for_condition_with_sleep(step)

    def _update_utilized_tools(
        self, indexes: List[int], remove_mode: bool = False
    ) -> None:
        """Update the utilized tools' indexes to match the fact that the given ones have been removed or added."""
        if len(indexes) == 0:
            return

        updated_tools = {}
        for tx_hash, tool_idx in self.utilized_tools.items():
            removed = False
            updated_idx = tool_idx

            for idx in indexes:
                if removed:
                    continue

                if tool_idx == idx and remove_mode:
                    removed = True
                    continue

                if tool_idx == idx:
                    updated_idx += 1
                if tool_idx > idx:
                    updated_idx += -1 if remove_mode else 1

            if not removed:
                updated_tools[tx_hash] = updated_idx

        self.context.logger.info(
            f"Updated the utilized tools' indexes: {self.utilized_tools} -> {updated_tools}."
        )
        self.utilized_tools = updated_tools

    def _adjust_policy_tools(self, local: List[str]) -> None:
        """Add or remove tools from the policy to match the remote tools."""
        # remove tools if they are not available anymore
        # process the indices in reverse order to avoid index shifting when removing the unavailable tools later
        reversed_idx = range(len(local) - 1, -1, -1)
        removed_idx = [idx for idx in reversed_idx if local[idx] not in self.mech_tools]
        self.policy.remove_tools(removed_idx)
        self._update_utilized_tools(sorted(removed_idx), remove_mode=True)

        # add tools if there are new ones available
        # process the indices in reverse order to avoid index shifting when adding the new tools later
        reversed_idx = range(len(self.mech_tools) - 1, -1, -1)
        new_idx = [idx for idx in reversed_idx if self.mech_tools[idx] not in local]
        self.policy.add_new_tools(new_idx)
        self._update_utilized_tools(new_idx)

    def _try_recover_policy(self) -> Optional[EGreedyPolicy]:
        """Try to recover the policy from the policy store."""
        try:
            policy_path = self.params.store_path / POLICY_STORE
            with open(policy_path, "r") as f:
                policy = f.read()
                return EGreedyPolicy.deserialize(policy)
        except Exception as e:
            self.context.logger.warning(f"Could not recover the policy: {e}.")
            return None

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

    def _get_init_accuracy_policy(
        self, available_tools: List[str]
    ) -> EGreedyAccuracyPolicy:
        """Get the initial accuracy policy object"""
        acc_policy: EGreedyAccuracyPolicy = None
        self.context.logger.info("Initializing the accuracy policy")
        try:
            acc_path = self.params.store_path / ACCURACY_STORE
            with open(acc_path, "r") as f:
                acc_policy_json = f.read()
                acc_policy = EGreedyAccuracyPolicy.deserialize(acc_policy_json)
        except Exception as e:
            self.context.logger.warning(
                f"The accuracy store was not found. Creating new empty one"
            )
            acc_policy = EGreedyAccuracyPolicy.initial_state(
                self.params.epsilon, available_tools
            )
        finally:
            return acc_policy

    def _update_accuracy_store(self):
        """Update the accuracy store file with the latest information available"""
        accuracy_store = self.accuracy_policy.accuracy_store
        try:
            # get the csv file from IPFS
            self.context.logger.info("Reading accuracy information from IPFS")
            accuracy_link = self.params.ipfs_address + self.params.tools_accuracy_hash
            response = yield from self.get_http_response(
                method="GET", url=accuracy_link
            )
            if response.status_code != 200:
                self.context.logger.error(
                    f"Could not retrieve data from the url {accuracy_link}. "
                    f"Received status code {response.status_code}."
                )
                return None
        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"Could not parse response from ipfs server, "
                f"the following error was encountered {type(e).__name__}: {e}"
            )
            return None

        sep = self.benchmarking_mode.sep
        reader = csv.DictReader(response.body, delimiter=sep)
        for row in reader:
            accuracy_store[row["tool"]] = [
                row["total_requests"],
                row["tool_accuracy"],
            ]

        self.context.logger.info("Parsed accuracy information of the tools")
        print(accuracy_store)
        try:
            # save the updated information at the accuracy_store.json
            self.accuracy_policy.update_accuracy_store(accuracy_store)
            acc_path = self.params.store_path / ACCURACY_STORE
            with open(acc_path, "w") as f:
                f.write(self.accuracy_policy.serialize())
                self.context.logger.info(
                    "Accuracy information updated and saved into the json file"
                )
        except:
            self.context.logger.error("Error trying to save the accuracy policy")

    def _set_accuracy_policy(self) -> None:
        """Set the E Greedy accuracy policy"""
        self.context.logger.warning(
            "The accuracy policy is only working now in benchmarking mode"
        )
        local_tools = self._get_tools_from_benchmark_file()
        if local_tools is None:
            local_tools = self.mech_tools

        # set the list of available tools
        self._acc_policy = self._get_init_accuracy_policy(local_tools)
        self._update_accuracy_store()

    def _set_policy(self) -> None:
        """Set the E Greedy Policy."""
        if self.is_first_period or not self.synchronized_data.is_policy_set:
            self._policy = self._get_init_policy()
            local_tools = self._try_recover_mech_tools()
            if local_tools is None:
                local_tools = self.mech_tools
        else:
            self._policy = self.synchronized_data.policy
            local_tools = self.synchronized_data.available_mech_tools

        self._adjust_policy_tools(local_tools)

    def _try_recover_utilized_tools(self) -> Dict[str, int]:
        """Try to recover the available tools from the tools store."""
        tools_path = self.params.store_path / UTILIZED_TOOLS_STORE
        try:
            with open(tools_path, "r") as tools_file:
                return json.load(tools_file)
        except FileNotFoundError:
            msg = "No file with pending rewards for the policy were found in the local storage."
            self.context.logger.info(msg)
        except Exception as exc:
            msg = f"Could not recover the pending rewards for the policy: {exc}."
            self.context.logger.warning(msg)
        return {}

    def _try_recover_mech_tools(self) -> Optional[List[str]]:
        """Try to recover the available tools from the tools store."""
        try:
            tools_path = self.params.store_path / AVAILABLE_TOOLS_STORE
            with open(tools_path, "r") as f:
                tools = json.load(f)
                return tools
        except Exception as e:
            self.context.logger.warning(f"Could not recover the tools: {e}.")
            return None

    def _setup_policy_and_tools(self) -> Generator[None, None, bool]:
        """Set up the policy and tools."""
        yield from self._get_tools()
        if self._mech_tools is None:
            return False

        if self.benchmarking_mode.enabled:
            self._set_accuracy_policy()
        else:
            self._set_policy()
        return True

    def _store_policy(self) -> None:
        """Store the policy"""
        policy_path = self.params.store_path / POLICY_STORE
        with open(policy_path, "w") as f:
            f.write(self.policy.serialize())

    def _store_available_mech_tools(self) -> None:
        """Store the policy"""
        policy_path = self.params.store_path / AVAILABLE_TOOLS_STORE
        with open(policy_path, "w") as f:
            json.dump(self.mech_tools, f)

    def _store_utilized_tools(self) -> None:
        """Store the utilized tools."""
        tools_path = self.params.store_path / UTILIZED_TOOLS_STORE
        with open(tools_path, "w") as f:
            json.dump(self.utilized_tools, f)

    def _store_all(self) -> None:
        """Store the policy, the available tools and the utilized tools."""
        self._store_policy()
        self._store_available_mech_tools()
        self._store_utilized_tools()
