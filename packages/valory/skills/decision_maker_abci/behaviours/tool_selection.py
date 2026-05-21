# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

import copy
import json
from typing import Any, Dict, Generator, Optional, Set, Tuple

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    CID_PREFIX,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    StorageManagerBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import ToolSelectionPayload
from packages.valory.skills.decision_maker_abci.states.tool_selection import (
    ToolSelectionRound,
)
from packages.valory.skills.decision_maker_abci.utils.tool_suitability import (
    explain_prediction_tool,
    is_prediction_tool,
)


class ToolSelectionBehaviour(StorageManagerBehaviour):
    """A behaviour in which the agents select a mech tool."""

    matching_round = ToolSelectionRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(**kwargs)
        self._tool_metadata: Dict[str, Dict[str, Any]] = {}
        self._pending_cid: Optional[str] = None

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

    def _candidate_tools(self) -> Tuple[set, Optional[str]]:
        """Apply suitability, ChatUI mech pin, ChatUI tool pin (in order)."""
        candidate = set(self.mech_tools)
        cause: Optional[str] = None

        if self._tool_metadata:
            suitable = {
                tool
                for tool in candidate
                if is_prediction_tool(self._tool_metadata.get(tool))
            }
            if suitable:
                if suitable != candidate:
                    rejected: Dict[str, list] = {}
                    no_manifest: list = []
                    for tool in sorted(candidate - suitable):
                        meta = self._tool_metadata.get(tool)
                        if meta is None:
                            no_manifest.append(tool)
                        else:
                            _, reason = explain_prediction_tool(meta)
                            rejected.setdefault(reason, []).append(tool)
                    self.context.logger.info(
                        "Tool-suitability classifier narrowed "
                        f"{len(candidate)} -> {len(suitable)} tools; "
                        f"rejected by classifier: {dict(sorted(rejected.items()))}"
                    )
                    if no_manifest:
                        self.context.logger.warning(
                            f"{len(no_manifest)} tool(s) dropped because no "
                            "manifest data was available (CID fetch failed or "
                            "empty toolMetadata entry); see per-CID WARNINGs. "
                            f"Tools: {no_manifest[:10]}"
                        )
                candidate = suitable
            elif candidate:
                self.context.logger.warning(
                    "Tool-suitability classifier marked every candidate as "
                    "unsuitable; keeping the raw mech_tools set so the round "
                    "can proceed."
                )

        selected_mechs = self.shared_state.chatui_config.selected_mechs
        if selected_mechs and not self.benchmarking_mode.enabled:
            selected_lower = {m.lower() for m in selected_mechs}
            tools_from_pinned_mechs = {
                tool
                for mech in self.synchronized_data.mechs_info
                if mech.address.lower() in selected_lower
                for tool in mech.relevant_tools
            }
            candidate &= tools_from_pinned_mechs
            if not candidate:
                cause = "selected_mechs"

        allowed_tools = self.shared_state.chatui_config.allowed_tools
        if allowed_tools:
            candidate &= set(allowed_tools)
            if not candidate and cause is None:
                cause = "allowed_tools"

        return candidate, cause

    def _select_tool(self) -> Generator[None, None, Optional[str]]:
        """Pick a tool via e-greedy policy on the candidate set."""
        success = yield from self._setup_policy_and_tools()
        if not success:
            return None

        yield from self._fetch_mech_manifests()

        randomness = (
            (self.benchmarking_mode.randomness if self.is_first_period else None)
            if self.benchmarking_mode.enabled
            else self.synchronized_data.most_voted_randomness
        )

        candidate_tools, cause = self._candidate_tools()
        if not candidate_tools:
            if cause is not None:
                self.context.logger.warning(
                    f"ChatUI {cause!r} restriction left no candidate tools; "
                    "skipping this round so the user can adjust the pin."
                )
                return None
            selected_tool = self.policy.select_tool(randomness)
        elif candidate_tools != self.mech_tools:
            restricted_policy = copy.deepcopy(self.policy)
            restricted_policy.accuracy_store = {
                t: v
                for t, v in restricted_policy.accuracy_store.items()
                if t in candidate_tools
            }
            restricted_policy.update_weighted_accuracy()
            selected_tool = restricted_policy.select_tool(randomness)
        else:
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
                mech_tools = json.dumps(list(self.mech_tools))
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
