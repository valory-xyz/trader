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

import csv
import json
from abc import ABC
from datetime import datetime
from io import StringIO
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
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    DataclassEncoder,
    EGreedyPolicy,
)


POLICY_STORE = "policy_store.json"
AVAILABLE_TOOLS_STORE = "available_tools_store.json"
UTILIZED_TOOLS_STORE = "utilized_tools.json"
GET = "GET"
OK_CODE = 200
MAX_STR = "max"
DATETIME_FORMAT_STR = "%Y-%m-%d %H:%M:%S"


class StorageManagerBehaviour(DecisionMakerBaseBehaviour, ABC):
    """Manages the storage of the policy and the tools."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._mech_id: int = 0
        self._mech_hash: str = ""
        self._utilized_tools: Dict[str, str] = {}
        self._mech_tools: Optional[List[str]] = None
        self._accuracy_information: StringIO = StringIO()

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
    def accuracy_information(self) -> StringIO:
        """Get the accuracy information."""
        return self._accuracy_information

    @accuracy_information.setter
    def accuracy_information(self, accuracy_information: StringIO) -> None:
        """Set the accuracy information."""
        self._accuracy_information = accuracy_information

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
    def utilized_tools(self) -> Dict[str, str]:
        """Get the utilized tools."""
        return self._utilized_tools

    @utilized_tools.setter
    def utilized_tools(self, utilized_tools: Dict[str, str]) -> None:
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
        """Get the initial policy."""
        # try to read the policy from the policy store, and if we cannot recover the policy, we create a new one
        return self._try_recover_policy() or EGreedyPolicy(self.params.epsilon)

    def _fetch_accuracy_info(self) -> Generator[None, None, bool]:
        """Fetch the latest accuracy information available."""
        # get the CSV file from IPFS
        self.context.logger.info("Reading accuracy information from IPFS...")
        accuracy_link = self.params.ipfs_address + self.params.tools_accuracy_hash
        response = yield from self.get_http_response(method=GET, url=accuracy_link)
        if response.status_code != OK_CODE:
            self.context.logger.error(
                f"Could not retrieve data from the url {accuracy_link}. "
                f"Received status code {response.status_code}."
            )
            return False

        self.context.logger.info("Parsing accuracy information of the tools...")
        try:
            self.accuracy_information = StringIO(response.body.decode())
        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"Could not parse response from ipfs server, "
                f"the following error was encountered {type(e).__name__}: {e}"
            )
            return False

        return True

    def _fetch_remote_tool_date(self) -> int:
        """Fetch the max transaction date from the remote accuracy storage."""
        self.context.logger.info("Checking remote accuracy information date... ")
        self.context.logger.info("Trying to read max date in file...")
        accuracy_information = self.accuracy_information

        if accuracy_information:
            sep = self.acc_info_fields.sep
            accuracy_information.seek(0)  # Ensure we’re at the beginning
            reader = csv.DictReader(accuracy_information.readlines(), delimiter=sep)

        max_transaction_date = None

        # try to read the maximum transaction date in the remote accuracy info
        try:
            for row in reader:
                current_transaction_date = row.get(MAX_STR)
                if (
                    max_transaction_date is None
                    or current_transaction_date > max_transaction_date
                ):
                    max_transaction_date = current_transaction_date

        except TypeError:
            self.context.logger.warning(
                "Invalid transaction date found. Continuing with local accuracy information..."
            )
            return 0

        if max_transaction_date:
            self.context.logger.info(f"Maximum date found: {max_transaction_date}")
            max_datetime = datetime.strptime(max_transaction_date, DATETIME_FORMAT_STR)
            unix_timestamp = int(max_datetime.timestamp())
            return unix_timestamp

        self.context.logger.info("No maximum date found.")
        return 0

    def _check_local_policy_store_overwrite(self) -> bool:
        """Compare the local and remote policy store dates and decide which to use."""

        local_policy_store_date = self.policy.updated_ts
        remote_policy_store_date = self._fetch_remote_tool_date()
        policy_store_update_offset = self.params.policy_store_update_offset

        self.context.logger.info("Comparing tool accuracy dates...")

        overwrite = (
            True
            if remote_policy_store_date
            > (local_policy_store_date - policy_store_update_offset)
            else False
        )
        self.context.logger.info(f"Local policy store overwrite: {overwrite}.")
        return overwrite

    def _update_accuracy_store(self, local_tools: List[str]) -> None:
        """Update the accuracy store file with the latest information available"""
        self.context.logger.info("Updating accuracy information of the policy...")
        sep = self.acc_info_fields.sep
        reader: csv.DictReader = csv.DictReader(
            self.accuracy_information, delimiter=sep
        )
        accuracy_store = self.policy.accuracy_store

        # update the accuracy store using the latest accuracy information (only entered during the first period)
        for row in reader:
            tool = row[self.acc_info_fields.tool]
            # overwrite local with global information (naturally, no global information is available for pending)
            accuracy_store[tool] = AccuracyInfo(
                int(row[self.acc_info_fields.requests]),
                # set the pending using the local policy if this information exists
                accuracy_store.get(tool, AccuracyInfo()).pending,
                float(row[self.acc_info_fields.accuracy]),
            )

        # update the accuracy store by adding tools which we do not have any global information about yet
        for tool in local_tools:
            accuracy_store.setdefault(tool, AccuracyInfo())

        self.policy.update_weighted_accuracy()

    def _set_policy(self) -> Generator:
        """Set the E Greedy Policy."""
        if self.is_first_period or not self.synchronized_data.is_policy_set:
            self.context.logger.debug("Setting initial policy")
            self._policy = self._get_init_policy()
            local_tools = self._try_recover_mech_tools()
            if local_tools is None:
                local_tools = self.mech_tools
        else:
            self.context.logger.debug(
                "Reading policy information from synchronized data"
            )
            self._policy = self.synchronized_data.policy
            local_tools = self.synchronized_data.available_mech_tools

        yield from self.wait_for_condition_with_sleep(
            self._fetch_accuracy_info, sleep_time_override=self.params.sleep_time
        )
        overwrite_local_store = self._check_local_policy_store_overwrite()

        if self.is_first_period and overwrite_local_store:
            self.policy.updated_ts = int(datetime.now().timestamp())
            self._update_accuracy_store(local_tools)

        elif self.is_first_period:
            policy_json = json.dumps(self.policy, cls=DataclassEncoder)
            self.accuracy_information = StringIO(policy_json)

    def _try_recover_utilized_tools(self) -> Dict[str, str]:
        """Try to recover the utilized tools from the tools store."""
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

        yield from self._set_policy()
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
