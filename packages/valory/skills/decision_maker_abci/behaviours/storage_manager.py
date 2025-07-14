# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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
from typing import Any, Dict, Generator, List, Optional, Tuple

from packages.valory.contracts.agent_registry.contract import AgentRegistryContract
from packages.valory.contracts.complementary_service_metadata.contract import (
    ComplementaryServiceMetadata,
)
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
    EGreedyPolicy,
)
from packages.valory.skills.decision_maker_abci.utils.general import suppress_logs


POLICY_STORE = "policy_store_multi_bet_failure_adjusting.json"
AVAILABLE_TOOLS_STORE = "available_tools_store.json"
UTILIZED_TOOLS_STORE = "utilized_tools.json"
GET = "GET"
OK_CODE = 200
NO_METADATA_HASH = "0" * 64


class StorageManagerBehaviour(DecisionMakerBaseBehaviour, ABC):
    """Manages the storage of the policy and the tools."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._mech_id: int = 0
        self._mech_hash: str = ""
        self._utilized_tools: Dict[str, str] = {}
        self._mech_tools: Optional[List[str]] = None
        self._remote_accuracy_information: StringIO = StringIO()

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
    def remote_accuracy_information(self) -> StringIO:
        """Get the accuracy information."""
        return self._remote_accuracy_information

    @remote_accuracy_information.setter
    def remote_accuracy_information(self, accuracy_information: StringIO) -> None:
        """Set the accuracy information."""
        self._remote_accuracy_information = accuracy_information

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

    def detect_new_mm(self) -> WaitableConditionType:
        """Detect whether the new mech marketplace is being used."""
        # suppressing logs: contract method may not exist, but failure is expected during MM version detection
        with suppress_logs():
            # the `get_payment_type` is only available in mechs on the new marketplace
            is_new_mm = yield from self._mech_mm_contract_interact(
                contract_callable="get_payment_type",
                data_key="payment_type",
                placeholder="_",
            )

        if is_new_mm:
            self.context.logger.info(
                f"Mech with address {self.params.mech_contract_address} is on the latest mech marketplace."
            )
            self.shared_state.new_mm_detected = is_new_mm

        return is_new_mm

    def detect_legacy_mm(self) -> Generator:
        """Detect whether the legacy mech marketplace is being used."""
        # suppressing logs: contract method may not exist, but failure is expected during MM version detection
        with suppress_logs():
            # the `get_price` is only available in mechs on the legacy marketplace
            is_legacy_mm = yield from self._mech_contract_interact(
                contract_callable="get_price",
                data_key="price",
                placeholder="_",
            )

        if is_legacy_mm:
            self.context.logger.info(
                f"Mech with address {self.params.mech_contract_address} is on the legacy mech marketplace."
            )
            self.shared_state.new_mm_detected = False
        else:
            # we do not set the flag in the shared state in this case, so that the check is performed again next time
            self.context.logger.error(
                f"Could not verify the mech's version for address {self.params.mech_contract_address}! "
                "Assuming legacy mech marketplace."
            )

    def detect_mm_version(self) -> WaitableConditionType:
        """Detect the mech marketplace version in which the utilized mech belongs to."""
        is_new_mm = yield from self.detect_new_mm()
        if is_new_mm:
            return True
        yield from self.detect_legacy_mm()
        return False

    def using_new_mm(self) -> WaitableConditionType:
        """Whether the new mech marketplace is being used."""
        if self.shared_state.new_mm_detected is not None:
            return self.shared_state.new_mm_detected

        if not self.params.use_mech_marketplace:
            self.shared_state.new_mm_detected = False
            return False

        return (yield from self.detect_mm_version())

    def set_mech_agent_specs(self) -> Generator:
        """Set the mech's agent specs."""
        ipfs_link = (
            self.mech_hash
            if (yield from self.using_new_mm())
            else self.params.ipfs_address + CID_PREFIX + self.mech_hash
        )

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

    def _get_mech_service_id(self) -> WaitableConditionType:
        """Get the mech's id."""
        result = yield from self._mech_mm_contract_interact(
            contract_callable="get_service_id",
            data_key="service_id",
            placeholder=get_name(StorageManagerBehaviour.mech_id),
        )

        return result

    def _get_metadata_uri(self) -> WaitableConditionType:
        """Get the mech's hash."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.metadata_address,
            contract_public_id=ComplementaryServiceMetadata.contract_id,
            contract_callable="get_token_uri",
            data_key="uri",
            placeholder=get_name(StorageManagerBehaviour.mech_hash),
            service_id=self.mech_id,
        )
        return result

    def _check_hash(self) -> None:
        """Check the validity of the obtained mech hash."""
        if self.mech_hash.endswith(NO_METADATA_HASH):
            self.context.logger.error(
                f"No metadata hash was found for the mech with address {self.params.mech_contract_address} "
                f"and id {self.mech_id}!"
            )

    def _get_mech_tools(self) -> WaitableConditionType:
        """Get the mech agent's tools from IPFS."""
        self._check_hash()
        yield from self.set_mech_agent_specs()
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

        metadata_steps = (
            (
                self._get_mech_service_id,
                self._get_metadata_uri,
            )
            if (yield from self.using_new_mm())
            else (
                self._get_mech_id,
                self._get_mech_hash,
            )
        )

        for step in (
            *metadata_steps,
            self._get_mech_tools,
        ):
            yield from self.wait_for_condition_with_sleep(step)

    def _try_recover_policy(self) -> Optional[EGreedyPolicy]:
        """Try to recover the policy from the policy store."""
        try:
            policy_path = self.params.store_path / POLICY_STORE
            with open(policy_path, "r") as f:
                policy_raw = f.read()
                policy = EGreedyPolicy.deserialize(policy_raw)
                # overwrite the configurable parameters
                policy.eps = self.params.epsilon
                policy.consecutive_failures_threshold = self.params.policy_threshold
                policy.quarantine_duration = self.params.tool_quarantine_duration
                return policy
        except Exception as e:
            self.context.logger.warning(f"Could not recover the policy: {e}.")
            return None

    def _get_init_policy(self) -> EGreedyPolicy:
        """Get the initial policy."""
        # try to read the policy from the policy store, and if we cannot recover the policy, we create a new one
        return self._try_recover_policy() or EGreedyPolicy(
            self.params.epsilon,
            self.params.policy_threshold,
            self.params.tool_quarantine_duration,
        )

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
            self.remote_accuracy_information = StringIO(response.body.decode())
        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"Could not parse response from ipfs server, "
                f"the following error was encountered {type(e).__name__}: {e}"
            )
            return False

        return True

    def _remove_irrelevant_tools(self) -> None:
        """Remove irrelevant tools from the accuracy store."""
        accuracy_store = self.policy.accuracy_store
        for tool in accuracy_store.copy():
            if tool not in self.mech_tools:
                accuracy_store.pop(tool, None)

    def _global_info_date_to_unix(self, tool_transaction_date: str) -> Optional[int]:
        """Convert the global information date to unix."""
        datetime_format = self.acc_info_fields.datetime_format
        try:
            tool_transaction_datetime = datetime.strptime(
                tool_transaction_date, datetime_format
            )
        except (ValueError, TypeError):
            self.context.logger.warning(
                f"Could not parse the global info date {tool_transaction_date!r} using format {datetime_format!r}!"
            )
            return None

        return int(tool_transaction_datetime.timestamp())

    def _parse_global_info_row(
        self,
        row: Dict[str, str],
        max_transaction_date: int,
        tool_to_global_info: Dict[str, Dict[str, str]],
    ) -> int:
        """Parse a row of the global information."""
        tool = row[self.acc_info_fields.tool]
        if tool not in self.mech_tools:
            # skip irrelevant tools
            return max_transaction_date

        # store the global information
        tool_to_global_info[tool] = row

        # find the latest transaction date
        tool_transaction_date = row[self.acc_info_fields.max]
        tool_transaction_unix = self._global_info_date_to_unix(tool_transaction_date)
        if (
            tool_transaction_unix is not None
            and tool_transaction_unix > max_transaction_date
        ):
            return tool_transaction_unix

        return max_transaction_date

    def _parse_global_info(self) -> Tuple[int, Dict[str, Dict[str, str]]]:
        """Parse the global information of the tools."""
        sep = self.acc_info_fields.sep
        reader: csv.DictReader = csv.DictReader(
            self.remote_accuracy_information, delimiter=sep
        )

        max_transaction_date = 0
        tool_to_global_info: Dict[str, Dict[str, str]] = {}
        for row in reader:
            max_transaction_date = self._parse_global_info_row(
                row, max_transaction_date, tool_to_global_info
            )

        return max_transaction_date, tool_to_global_info

    def _should_use_global_info(self, global_update_timestamp: int) -> bool:
        """Whether we should use the global information of the tools."""
        local_update_timestamp = self.policy.updated_ts
        local_update_offset = self.params.policy_store_update_offset
        return global_update_timestamp > local_update_timestamp - local_update_offset

    def _overwrite_local_info(
        self, tool_to_global_info: Dict[str, Dict[str, str]]
    ) -> None:
        """Overwrite the local information with the global information."""
        self.context.logger.info(
            "The local policy store will be overwritten with global information."
        )

        accuracy_store = self.policy.accuracy_store
        for tool, row in tool_to_global_info.items():
            accuracy_store[tool] = AccuracyInfo(
                int(row[self.acc_info_fields.requests]),
                # naturally, no global information is available for pending.
                # set it using the local policy if this information exists
                accuracy_store.get(tool, AccuracyInfo()).pending,
                float(row[self.acc_info_fields.accuracy]),
            )
            self.policy.updated_ts = int(datetime.now().timestamp())

    def _update_accuracy_store(
        self,
        global_update_timestamp: int,
        tool_to_global_info: Dict[str, Dict[str, str]],
    ) -> None:
        """
        Update the accuracy store using the latest accuracy information.

        The current method should only be called at the first period.

        :param global_update_timestamp: the timestamp of the latest global information update
        :param tool_to_global_info: the global information of the tools
        """
        if self._should_use_global_info(global_update_timestamp):
            self._overwrite_local_info(tool_to_global_info)

        # update the accuracy store by adding tools for which we do not have any global information yet
        for tool in self.mech_tools:
            self.policy.accuracy_store.setdefault(tool, AccuracyInfo())

    def _update_policy_tools(self) -> None:
        """Update the policy's tools and their accuracy with the latest information available if `with_global_info`."""
        self.context.logger.info("Updating information of the policy...")
        self._remove_irrelevant_tools()
        global_info = self._parse_global_info()
        self._update_accuracy_store(*global_info)
        self.policy.update_weighted_accuracy()

    def _set_policy(self) -> Generator:
        """Set the E Greedy Policy."""
        if self.is_first_period or not self.synchronized_data.is_policy_set:
            self.context.logger.debug("Setting initial policy")
            self._policy = self._get_init_policy()
        else:
            self.context.logger.debug(
                "Reading policy information from synchronized data"
            )
            self._policy = self.synchronized_data.policy

        yield from self.wait_for_condition_with_sleep(
            self._fetch_accuracy_info, sleep_time_override=self.params.sleep_time
        )

        if self.is_first_period:
            self._update_policy_tools()

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
