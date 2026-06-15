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
from typing import Dict, Generator, Optional, Tuple

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

        # Publish the post-suitability, pre-pin set for the ChatUI to validate
        # and display tool pins against (see chatui handler ``_available_tools``).
        # ``candidate`` here is the suitability-filtered universe with the
        # raw-set fallback already applied above, so a manifest outage degrades
        # to the full set rather than blocking the user from pinning anything.
        # It is only ever empty if ``mech_tools`` itself is empty (no tools
        # discovered); the ``None`` default on the shared field instead means
        # "not published yet, fall back to ``available_mech_tools``".
        # Publishing pre-pin is deliberate: the user pins applied below do not
        # mutate the main policy object — only an ephemeral deepcopy is
        # restricted in ``_select_tool`` — so accuracy keeps accumulating across
        # all tools between rounds.
        self.shared_state.available_prediction_tools = frozenset(candidate)

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
        if allowed_tools and candidate:
            # Non-destructive read-side revalidation. Intersect only with the
            # pinned tools that are actually selectable this round. If every
            # pinned tool has dropped out of the selectable set -- drifted out
            # of suitability, pinned through a cold-start / IPFS-outage fallback
            # window, or the serving mechs stopped offering it -- ignore the pin
            # this round so the round proceeds instead of self-looping on
            # Event.NONE. The stored pin is left untouched (it re-applies
            # automatically once a pinned tool becomes selectable again) and the
            # policy/accuracy_store is never altered. Genuine mech-pin conflicts
            # that empty ``candidate`` upstream keep their ``selected_mechs``
            # cause (handled separately; see issue #991).
            effective = candidate & set(allowed_tools)
            if effective:
                candidate = effective
            else:
                self.context.logger.warning(
                    f"None of the pinned allowed_tools {sorted(allowed_tools)} "
                    "are in the current selectable set; ignoring the tool pin "
                    "this round so selection can proceed. The pin is left intact "
                    "and re-applies once a pinned tool becomes selectable again."
                )

        return candidate, cause

    def _select_tool(self) -> Generator[None, None, Optional[str]]:
        """Pick a tool via e-greedy policy on the candidate set."""
        success = yield from self._setup_policy_and_tools()
        if not success:
            # No tools available this round (transient mech-info outage, V2 cold
            # start before MechInformationRound, etc.), so ``_candidate_tools``
            # does not run and ``available_prediction_tools`` is left at its
            # prior value. That is deliberate: leaving the last-known-good set is
            # safer than clearing it, since clearing makes the ChatUI fall back
            # to the raw ``available_mech_tools`` (re-exposing unsuitable tools).
            # Any pin that goes stale in the meantime is caught non-destructively
            # by the read-side revalidation in ``_candidate_tools`` next round.
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
