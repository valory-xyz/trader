# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

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
    EGreedyPolicy,
)
from packages.valory.skills.decision_maker_abci.utils.tool_suitability import (
    is_prediction_tool,
)

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
        self._mech_tools: Set[str] = set()
        self._remote_accuracy_information: StringIO = StringIO()
        # Tool-suitability classifier cache, populated per boot by
        # `_fetch_mech_manifests`; keyed by lowercased tool name.
        self._tool_metadata: Dict[str, Dict[str, Any]] = {}
        self._pending_cid: Optional[str] = None

    @property
    def mech_tools(self) -> Set[str]:
        """Get the mech agent's tools."""
        if not self._mech_tools:
            raise ValueError("The mech's tools have not been set.")
        return self._mech_tools

    @mech_tools.setter
    def mech_tools(self, mech_tools: Set[str]) -> None:
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

    def set_mech_agent_specs(self) -> None:
        """Set the mech's agent specs."""
        ipfs_link = (
            self.mech_hash
            if self.synchronized_data.is_marketplace_v2
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
        self.mech_tools = {
            header.replace(p_yes_part, "") for header in headers if p_yes_part in header
        }

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
        res = {str(tool).lower() for tool in res}

        if len(res) == 0:
            self.context.logger.error("The mech agent's manifest is empty!")
            return False
        # V1-only operator allowlist intersection. The V2 marketplace path
        # branches early in `_get_tools` and never reaches this method; V2
        # sets `mech_tools` from `synchronized_data.mech_tools` and applies
        # the suitability classifier downstream in
        # `tool_selection._fetch_mech_manifests`. The `is_marketplace_v2`
        # guard below mirrors that upstream branch as belt-and-suspenders
        # so a future refactor of `_get_tools` can't accidentally route V2
        # through here and apply this V1-shaped allowlist.
        if (
            self.params.mech_marketplace_v1_suitable_tools
            and not self.synchronized_data.is_marketplace_v2
        ):
            res &= self.params.mech_marketplace_v1_suitable_tools
            if not res:
                self.context.logger.error(
                    "V1 operator allowlist "
                    "`mech_marketplace_v1_suitable_tools` produced an empty "
                    "intersection with the on-chain tool set; check the "
                    "allowlist against the mech's actual tool list. Returning "
                    "False so the retry loop handles the misconfiguration."
                )
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

        if self.synchronized_data.is_marketplace_v2:
            self.mech_tools = self.synchronized_data.mech_tools
            return

        for step in (
            self._get_mech_id,
            self._get_mech_hash,
            self._get_mech_tools,
        ):
            yield from self.wait_for_condition_with_sleep(step)

    def _fetch_mech_manifests(self) -> Generator[None, None, None]:
        """Populate `self._tool_metadata` from each unique mech manifest."""
        self._tool_metadata = {}
        if not self.synchronized_data.is_marketplace_v2:
            return
        if self.benchmarking_mode.enabled:
            return

        seen_cids: Set[str] = set()
        for mech in self.synchronized_data.mechs_info:
            metadata_str = (
                mech.service.metadata_str if mech.service is not None else None
            )
            if metadata_str is None or metadata_str in seen_cids:
                continue
            seen_cids.add(metadata_str)
            self._pending_cid = metadata_str
            yield from self.wait_for_condition_with_sleep(self._fetch_one_manifest)

        self._pending_cid = None

        if seen_cids and not self._tool_metadata:
            self.context.logger.warning(
                "Tool-suitability classifier has no metadata for any of "
                f"{len(seen_cids)} mech manifest CIDs; the suitability filter "
                "will be skipped and the round will proceed against the raw "
                "mech_tools set."
            )
        elif seen_cids:
            self.context.logger.info(
                f"Tool-suitability classifier fetched {len(seen_cids)} unique "
                f"mech manifest CID(s); {len(self._tool_metadata)} tool entries "
                "available for classification."
            )

    def _fetch_one_manifest(self) -> WaitableConditionType:
        """Fetch the manifest for `self._pending_cid`, with bounded retries."""
        metadata_str = self._pending_cid
        if metadata_str is None:
            return True

        self.mech_tools_api.__dict__["_frozen"] = False
        try:
            self.mech_tools_api.url = (
                self.params.ipfs_address + CID_PREFIX + metadata_str
            )
        finally:
            # Restore the freeze even if `url` setting raises, so the shared
            # `mech_tools_api` on `self.context` stays consistent for the rest
            # of the round.
            self.mech_tools_api.__dict__["_frozen"] = True

        specs = self.mech_tools_api.get_spec()
        res_raw = yield from self.get_http_response(**specs)
        extracted = self._extract_tool_metadata(res_raw)

        if extracted:
            self._tool_metadata.update(extracted)
            self.mech_tools_api.reset_retries()
            return True

        # `AgentToolsSpecs` extends `ApiSpecs` directly and does NOT define
        # `is_permanent_error` (only `MechToolsSpecs` does, on the mech-interact
        # side). Inline a minimal status-code classifier: 2xx is permanent
        # because we already failed `process_response`/extract on a 2xx body
        # (malformed content, not a flake); 4xx is a gateway rejection. 5xx
        # falls through to the transient retry path.
        status = getattr(res_raw, "status_code", None)
        is_permanent = status is not None and (
            200 <= status < 300 or 400 <= status < 500
        )
        if is_permanent:
            self.context.logger.warning(
                f"Tool-suitability classifier could not extract metadata "
                f"for CID {metadata_str!r} "
                f"(status={status}, permanent error); this mech manifest "
                "will not contribute to the suitability filter."
            )
            self.mech_tools_api.reset_retries()
            return True

        self.mech_tools_api.increment_retries()
        if self.mech_tools_api.is_retries_exceeded():
            self.context.logger.warning(
                f"Tool-suitability classifier could not extract metadata "
                f"for CID {metadata_str!r} "
                f"(status={getattr(res_raw, 'status_code', '?')}); "
                "retries exhausted, this mech manifest will not contribute "
                "to the suitability filter."
            )
            self.mech_tools_api.reset_retries()
            return True

        return False

    @staticmethod
    def _extract_tool_metadata(res_raw: Any) -> Dict[str, Dict[str, Any]]:
        """Pull `toolMetadata` from the IPFS body, keyed by lowercased name."""
        try:
            body = json.loads(res_raw.body.decode())
        except (AttributeError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        raw = body.get("toolMetadata") if isinstance(body, dict) else None
        if not isinstance(raw, dict):
            return {}
        return {
            str(name).lower(): meta
            for name, meta in raw.items()
            if isinstance(meta, dict)
        }

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

    def _prune_accuracy_store_to_current_tools(self) -> None:
        """Drop accuracy_store entries that are no longer in self.mech_tools."""
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
        self._prune_accuracy_store_to_current_tools()
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

    def _maybe_publish_suitable_tools(self) -> Generator[None, None, None]:
        """Publish the suitability-filtered tool set for the ChatUI, once per boot.

        Runs from ``_setup_policy_and_tools``, so under stop-trading -- when
        ``ToolSelectionRound`` never executes -- the redeem path still populates
        ``shared_state.available_prediction_tools`` and the ChatUI shows the
        post-classifier universe instead of the raw ``available_mech_tools``.

        Gated on ``is None`` so ``ToolSelectionRound``'s richer per-round publish
        (with its mech/tool-pin narrowing) wins whenever the agent is actually
        trading; this only fills the stop-trading gap. The ``is None`` gate is
        what makes it re-run once per boot: ``available_prediction_tools`` is
        in-memory shared state, so it is ``None`` again after any restart. (On a
        Tendermint-reset restart ``is_policy_set`` also resets, routing the
        redeem behaviour through ``super()``; on a db-replay restart it does not,
        which is why the redeem overrides also call this from their
        ``is_policy_set`` short-circuit branch.)

        V2-only (the classifier needs the mech manifest) and skipped in
        benchmarking mode. It now sits on the redeem path, so a persistent IPFS
        outage costs up to ``retries`` x ``rpc_sleep_time`` per manifest CID
        before the redeem behaviour can proceed -- tune ``retries`` if that boot
        stall matters. On a manifest fetch failure or an all-unsuitable verdict
        it leaves the field unpublished (both cases logged), so the ChatUI
        degrades to the raw set rather than hiding every tool.
        ``available_mech_tools`` is never narrowed here, so the e-greedy policy
        keeps learning across all tools.

        :yield: None
        """
        if self.shared_state.available_prediction_tools is not None:
            return
        if not self.synchronized_data.is_marketplace_v2:
            return
        if self.benchmarking_mode.enabled:
            return
        # The redeem short-circuit can call this with an empty tool set; guard
        # before the fetch so the `self.mech_tools` property below never raises.
        if not self._mech_tools:
            return

        yield from self._fetch_mech_manifests()
        if not self._tool_metadata:
            return

        suitable = {
            tool
            for tool in self.mech_tools
            if is_prediction_tool(self._tool_metadata.get(tool))
        }
        if not suitable:
            self.context.logger.warning(
                f"Tool-suitability classifier marked all {len(self.mech_tools)} "
                "tool(s) as unsuitable during setup; the ChatUI will fall back "
                "to the raw mech_tools set."
            )
            return

        self.context.logger.info(
            f"Published {len(suitable)} suitable prediction tool(s) for the "
            "ChatUI from the setup path (e.g. while trading is paused)."
        )
        self.shared_state.available_prediction_tools = frozenset(suitable)

    def _setup_policy_and_tools(self) -> Generator[None, None, bool]:
        """Set up the policy and tools."""
        yield from self._get_tools()
        if not self._mech_tools:
            return False

        yield from self._set_policy()
        yield from self._maybe_publish_suitable_tools()
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
            json.dump(list(self.mech_tools), f)

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
