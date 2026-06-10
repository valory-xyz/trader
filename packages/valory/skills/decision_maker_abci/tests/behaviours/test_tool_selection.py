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

"""Tests for ToolSelectionBehaviour._select_tool and async_act."""

import json
from typing import Any, Callable, Dict, Generator, List, Optional
from unittest.mock import MagicMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.base import CID_PREFIX
from packages.valory.skills.decision_maker_abci.behaviours.tool_selection import (
    ToolSelectionBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import ToolSelectionPayload
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    EGreedyPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RANDOMNESS = "0xdeadbeef"


def _make_policy(*tool_names: str) -> EGreedyPolicy:
    """Return an EGreedyPolicy populated with the given tool names.

    AccuracyInfo is seeded with requests=1 so that n_requests > 0 and
    EGreedyPolicy.__post_init__ doesn't raise ZeroDivisionError.

    :param tool_names: names of tools to add to the policy.
    :return: configured EGreedyPolicy instance.
    """
    return EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=3,
        quarantine_duration=100,
        accuracy_store={name: AccuracyInfo(requests=1) for name in tool_names},
    )


def _mock_setup(success: bool) -> Callable[..., Generator[None, None, bool]]:
    """Return a generator function that immediately returns ``success``."""

    def _gen(self: object) -> Generator[None, None, bool]:
        return success
        yield  # makes it a generator function

    return _gen


def _run_select_tool(behaviour: "ToolSelectionBehaviour") -> Optional[str]:
    """Drive _select_tool() to completion and return its value."""
    gen = behaviour._select_tool()
    result = None
    try:
        while True:
            next(gen)
    except StopIteration as exc:
        result = exc.value
    return result


class _TestableBehaviour(ToolSelectionBehaviour):
    """Shadows read-only AEA properties with plain instance attributes."""

    context = None  # type: ignore[assignment]
    shared_state = None  # type: ignore[assignment]
    synchronized_data = None  # type: ignore[assignment]
    benchmarking_mode = None  # type: ignore[assignment]
    policy = None  # type: ignore[assignment]
    mech_tools = None  # type: ignore[assignment]
    mech_tools_api = None  # type: ignore[assignment]
    params = None  # type: ignore[assignment]


def _make_behaviour(
    policy: EGreedyPolicy,
    mech_tools: set,
    allowed_tools: Optional[List[str]] = None,
    selected_mechs: Optional[List[str]] = None,
    mechs_info: Optional[List[Any]] = None,
    randomness: str = RANDOMNESS,
) -> _TestableBehaviour:
    """Return a _TestableBehaviour wired with mocked dependencies."""
    behaviour = object.__new__(_TestableBehaviour)  # type: ignore[type-abstract]

    # context
    context = MagicMock()
    behaviour.context = context  # type: ignore[assignment]

    # benchmarking_mode disabled so we use synchronized_data.most_voted_randomness
    benchmarking_mode = MagicMock()
    benchmarking_mode.enabled = False
    behaviour.benchmarking_mode = benchmarking_mode  # type: ignore[assignment]

    # synchronized_data. Default to V1 so the new V2-only IPFS-fetch loop in
    # `_fetch_mech_manifests` short-circuits; V2-specific tests override this.
    sync_data = MagicMock()
    sync_data.most_voted_randomness = randomness
    sync_data.mechs_info = mechs_info or []
    sync_data.is_marketplace_v2 = False
    behaviour.synchronized_data = sync_data  # type: ignore[assignment]

    # shared_state / chatui_config
    shared_state = MagicMock()
    shared_state.chatui_config.allowed_tools = allowed_tools
    shared_state.chatui_config.selected_mechs = selected_mechs
    behaviour.shared_state = shared_state  # type: ignore[assignment]

    # policy / mech_tools / classifier cache. `object.__new__` above skips
    # __init__, so we set `_tool_metadata` explicitly.
    behaviour.policy = policy  # type: ignore[assignment]
    behaviour.mech_tools = mech_tools  # type: ignore[assignment]
    behaviour._tool_metadata = {}  # type: ignore[attr-defined]

    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSelectToolSetupFailure:
    """Tests for _select_tool when _setup_policy_and_tools fails."""

    def test_returns_none_when_setup_fails(self) -> None:
        """_select_tool must return None immediately if _setup_policy_and_tools fails."""
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(policy, {"tool-a", "tool-b"})

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(False)
        ):
            result = _run_select_tool(behaviour)

        assert result is None


class TestSelectToolNoAllowedTools:
    """Tests for _select_tool when no allowed_tools restriction is set."""

    def test_unrestricted_policy_used_when_no_allowed_tools(self) -> None:
        """With allowed_tools=None the full policy must be used without deepcopy."""
        policy = _make_policy("tool-a", "tool-b", "tool-c")
        behaviour = _make_behaviour(
            policy, {"tool-a", "tool-b", "tool-c"}, allowed_tools=None
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(
                policy, "select_tool", return_value="tool-b"
            ) as mock_select:
                result = _run_select_tool(behaviour)

        assert result == "tool-b"
        mock_select.assert_called_once_with(RANDOMNESS)

    def test_empty_list_treated_as_no_restriction(self) -> None:
        """allowed_tools=[] (falsy) must fall through to unrestricted policy."""
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(policy, {"tool-a", "tool-b"}, allowed_tools=[])

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(
                policy, "select_tool", return_value="tool-a"
            ) as mock_select:
                result = _run_select_tool(behaviour)

        assert result == "tool-a"
        mock_select.assert_called_once_with(RANDOMNESS)


class TestSelectToolWithAllowedTools:
    """Tests for _select_tool with a valid allowed_tools intersection."""

    def test_restricted_policy_used_for_valid_intersection(self) -> None:
        """When allowed_tools intersects mech_tools, a restricted deepcopy is used."""
        policy = _make_policy("tool-a", "tool-b", "tool-c")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b", "tool-c"},
            allowed_tools=["tool-a", "tool-b"],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            result = _run_select_tool(behaviour)

        # Result must be one of the allowed tools
        assert result in {"tool-a", "tool-b"}

    def test_original_policy_store_not_mutated(self) -> None:
        """The original policy accuracy_store must be intact after a restricted selection."""
        policy = _make_policy("tool-a", "tool-b", "tool-c")
        original_keys = set(policy.accuracy_store.keys())
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b", "tool-c"},
            allowed_tools=["tool-a"],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            _run_select_tool(behaviour)

        assert set(policy.accuracy_store.keys()) == original_keys

    def test_single_allowed_tool_always_selected(self) -> None:
        """When only one tool is allowed and valid, it must always be returned."""
        policy = _make_policy("tool-a", "tool-b", "tool-c", "tool-d")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b", "tool-c", "tool-d"},
            allowed_tools=["tool-c"],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            result = _run_select_tool(behaviour)

        assert result == "tool-c"

    def test_partial_intersection_restricts_to_valid_subset(self) -> None:
        """allowed_tools with some unknown entries must restrict to the valid ones only."""
        policy = _make_policy("tool-a", "tool-b", "tool-c")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b", "tool-c"},
            # "unknown" is not in mech_tools
            allowed_tools=["unknown", "tool-c"],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            result = _run_select_tool(behaviour)

        # Only tool-c is valid ("unknown" is not in mech_tools)
        assert result == "tool-c"


class TestSelectToolStaleAllowedTools:
    """allowed_tools with no selectable overlap is relaxed, not a hard stall.

    Variant (b) read-side revalidation: rather than emptying ``candidate`` and
    self-looping on ``Event.NONE``, an ``allowed_tools`` pin whose entries are
    all outside the current selectable set (drifted out of suitability, pinned
    through a cold-start / IPFS-outage fallback window, or no longer served) is
    ignored for the round. The round proceeds on the full selectable set, the
    stored pin is left intact (it re-applies once a tool is selectable again),
    and the policy/accuracy_store is never altered.
    """

    def test_all_stale_relaxes_and_warns(self) -> None:
        """A fully unsatisfiable pin relaxes to the full set + warns, not None."""
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b"},
            allowed_tools=["nonexistent-x", "nonexistent-y"],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(
                policy, "select_tool", return_value="tool-a"
            ) as mock_select:
                result = _run_select_tool(behaviour)

        # Relaxed to the full selectable set rather than returning None.
        assert result == "tool-a"
        mock_select.assert_called_once_with(RANDOMNESS)
        behaviour.context.logger.warning.assert_called_once()  # type: ignore[attr-defined]
        warning_msg: str = behaviour.context.logger.warning.call_args[0][0]  # type: ignore[attr-defined]
        assert "allowed_tools" in warning_msg

    def test_pin_left_intact_and_policy_untouched(self) -> None:
        """Relaxing must mutate neither the stored pin nor the accuracy_store."""
        policy = _make_policy("tool-a", "tool-b")
        original_keys = set(policy.accuracy_store.keys())
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b"},
            allowed_tools=["ghost-tool"],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            _run_select_tool(behaviour)

        # Non-destructive: the stored pin and the policy accuracy store are
        # both exactly as they were.
        pin = behaviour.shared_state.chatui_config.allowed_tools  # type: ignore[attr-defined]
        assert pin == ["ghost-tool"]
        assert set(policy.accuracy_store.keys()) == original_keys


class TestCandidateToolsStaleAllowedTools:
    """`_candidate_tools` read-side handling of stale allowed_tools pins."""

    def test_all_stale_returns_full_set_no_cause(self) -> None:
        """All-stale pin: relax to the selectable set with no `cause` set.

        ``cause`` staying None is what stops `_select_tool` from emitting
        Event.NONE — i.e. no self-loop.
        """
        policy = _make_policy("a", "b")
        behaviour = _make_behaviour(policy, {"a", "b"}, allowed_tools=["x", "y"])

        candidate, cause = behaviour._candidate_tools()

        assert candidate == {"a", "b"}
        assert cause is None
        behaviour.context.logger.warning.assert_called_once()  # type: ignore[attr-defined]

    def test_partial_stale_keeps_valid_subset_silently(self) -> None:
        """Partial-stale pin: keep the still-selectable entries, no warning."""
        policy = _make_policy("a", "b", "c")
        behaviour = _make_behaviour(
            policy, {"a", "b", "c"}, allowed_tools=["c", "ghost"]
        )

        candidate, cause = behaviour._candidate_tools()

        assert candidate == {"c"}
        assert cause is None
        behaviour.context.logger.warning.assert_not_called()  # type: ignore[attr-defined]

    def test_selected_mechs_collapse_keeps_its_cause(self) -> None:
        """A `selected_mechs` collapse is not masked by the allowed_tools relax.

        When the mech pin empties `candidate` upstream, the allowed_tools block
        is skipped (guarded on a non-empty `candidate`) so `cause` stays
        `selected_mechs` — that stall is tracked separately (issue #991).
        """
        policy = _make_policy("a", "b")
        behaviour = _make_behaviour(
            policy,
            {"a", "b"},
            allowed_tools=["a"],
            selected_mechs=["0xa"],
            mechs_info=[_StubMech("0xa", {"c"})],  # serves neither a nor b
        )

        candidate, cause = behaviour._candidate_tools()

        assert candidate == set()
        assert cause == "selected_mechs"


class _StubMech:
    """Minimal stand-in for MechInfo: just `address` and `relevant_tools`."""

    def __init__(self, address: str, relevant_tools: set) -> None:
        self.address = address
        self.relevant_tools = relevant_tools


class TestSelectToolWithSelectedMechs:
    """Tests for the `selected_mechs` filter layer in _select_tool."""

    def test_restricts_to_tools_served_by_pinned_mechs(self) -> None:
        """Pinned mechs restrict candidates to the union of their relevant_tools."""
        policy = _make_policy("tool-a", "tool-b", "tool-c")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b", "tool-c"},
            selected_mechs=["0xa"],
            mechs_info=[
                _StubMech("0xa", {"tool-a"}),
                _StubMech("0xb", {"tool-b", "tool-c"}),
            ],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            result = _run_select_tool(behaviour)

        # Only `tool-a` is reachable through the pinned mech `0xa`.
        assert result == "tool-a"

    def test_pin_lookup_is_case_insensitive(self) -> None:
        """Mech address comparison must be case-insensitive."""
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b"},
            selected_mechs=["0xABC"],
            mechs_info=[
                _StubMech("0xabc", {"tool-a"}),
                _StubMech("0xdef", {"tool-b"}),
            ],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            result = _run_select_tool(behaviour)

        assert result == "tool-a"

    def test_combined_with_allowed_tools(self) -> None:
        """selected_mechs AND allowed_tools intersect together."""
        policy = _make_policy("tool-a", "tool-b", "tool-c")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b", "tool-c"},
            allowed_tools=["tool-a", "tool-b"],
            selected_mechs=["0xa"],
            mechs_info=[
                _StubMech("0xa", {"tool-b", "tool-c"}),
                _StubMech("0xb", {"tool-a"}),
            ],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            result = _run_select_tool(behaviour)

        # tool-a is allowed but not served by 0xa; tool-b is both allowed and served by 0xa.
        assert result == "tool-b"

    def test_empty_pin_is_no_op(self) -> None:
        """selected_mechs=None must not restrict beyond the existing filters."""
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b"},
            selected_mechs=None,
            mechs_info=[_StubMech("0xa", {"tool-a"})],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool", return_value="tool-b"):
                result = _run_select_tool(behaviour)

        assert result == "tool-b"

    def test_pin_set_but_mechs_info_empty_fails_closed(self) -> None:
        """Pin applies whenever set; empty mechs_info collapses the candidate.

        v2 normally populates mechs_info during MechInformationRound before
        ToolSelectionRound reads it. If it lands here empty (e.g. subgraph
        returned zero matching mechs), the pin yields no candidate and the
        round fails closed rather than silently broadening to the
        unrestricted policy.
        """
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b"},
            selected_mechs=["0xa"],
            mechs_info=[],
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool") as mock_select:
                result = _run_select_tool(behaviour)

        assert result is None
        mock_select.assert_not_called()

    def test_pin_collapse_returns_none_when_mechs_info_present(self) -> None:
        """A genuinely unsatisfiable pin must fail closed (return None).

        When ``mechs_info`` is populated but the pin yields no candidate
        tool, the previous behaviour silently fell back to the unrestricted
        policy. That picked a tool no pinned mech serves, which mech-interact
        rejected one round later with ``no_overlap_with_selected_mechs``.
        Failing closed here surfaces the cause to the consumer immediately
        instead of routing through a dead-end mech request.
        """
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(
            policy,
            {"tool-a", "tool-b"},
            selected_mechs=["0xa"],
            mechs_info=[_StubMech("0xa", {"tool-c"})],  # serves a tool we don't have
        )

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool") as mock_select:
                result = _run_select_tool(behaviour)

        assert result is None
        mock_select.assert_not_called()


def _run_async_act(behaviour: "ToolSelectionBehaviour") -> None:
    """Drive async_act() to completion."""
    gen = behaviour.async_act()
    try:
        while True:
            next(gen)
    except StopIteration:
        pass


class TestAsyncActSelectedToolNone:
    """Tests for async_act when _select_tool returns None."""

    def test_payload_has_none_fields(self) -> None:
        """All optional fields should be None when no tool selected."""
        policy = _make_policy("tool-a")
        behaviour = _make_behaviour(policy, {"tool-a"})

        benchmark_ctx = MagicMock()
        behaviour.context.benchmark_tool.measure.return_value = benchmark_ctx  # type: ignore[attr-defined]
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(False)
        ):
            with patch.object(
                behaviour,
                "finish_behaviour",
                side_effect=lambda p: iter([None]),
            ) as mock_finish:
                _run_async_act(behaviour)

        mock_finish.assert_called_once()
        payload = mock_finish.call_args[0][0]
        assert isinstance(payload, ToolSelectionPayload)
        assert payload.mech_tools is None
        assert payload.policy is None
        assert payload.utilized_tools is None
        assert payload.selected_tool is None


class TestAsyncActSelectedToolNotNone:
    """Tests for async_act when _select_tool returns a valid tool."""

    def test_payload_has_serialized_fields(self) -> None:
        """When a tool is selected, payload should contain serialized data."""
        policy = _make_policy("tool-a", "tool-b")
        behaviour = _make_behaviour(policy, {"tool-a", "tool-b"})
        behaviour._utilized_tools = {"cond1": "tool-a"}

        benchmark_ctx = MagicMock()
        behaviour.context.benchmark_tool.measure.return_value = benchmark_ctx  # type: ignore[attr-defined]
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        # benchmarking disabled
        behaviour.benchmarking_mode.enabled = False  # type: ignore[attr-defined]

        behaviour._store_all = MagicMock()  # type: ignore[method-assign,assignment]

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool", return_value="tool-a"):
                with patch.object(
                    behaviour,
                    "finish_behaviour",
                    side_effect=lambda p: iter([None]),
                ) as mock_finish:
                    _run_async_act(behaviour)

        mock_finish.assert_called_once()
        payload = mock_finish.call_args[0][0]
        assert isinstance(payload, ToolSelectionPayload)
        assert payload.selected_tool == "tool-a"
        assert payload.mech_tools is not None
        mech_tools_parsed = json.loads(payload.mech_tools)
        assert set(mech_tools_parsed) == {"tool-a", "tool-b"}
        assert payload.policy is not None
        assert payload.utilized_tools is not None
        behaviour._store_all.assert_called_once()

    def test_benchmarking_calls_tool_used(self) -> None:
        """Should call policy.tool_used during benchmarking mode."""
        policy = _make_policy("tool-a")
        behaviour = _make_behaviour(policy, {"tool-a"})
        behaviour._utilized_tools = {}

        benchmark_ctx = MagicMock()
        behaviour.context.benchmark_tool.measure.return_value = benchmark_ctx  # type: ignore[attr-defined]
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        # benchmarking enabled, period_count=0, last_benchmarking_has_run=False
        behaviour.benchmarking_mode.enabled = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.period_count = 0  # type: ignore[attr-defined]
        behaviour.shared_state.last_benchmarking_has_run = False  # type: ignore[attr-defined]

        behaviour._store_all = MagicMock()  # type: ignore[method-assign,assignment]

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool", return_value="tool-a"):
                with patch.object(policy, "tool_used") as mock_tool_used:
                    with patch.object(
                        behaviour,
                        "finish_behaviour",
                        side_effect=lambda p: iter([None]),
                    ):
                        _run_async_act(behaviour)

        mock_tool_used.assert_called_once_with("tool-a")

    def test_benchmarking_not_running_skips_tool_used(self) -> None:
        """Should not call policy.tool_used when period_count is not 0."""
        policy = _make_policy("tool-a")
        behaviour = _make_behaviour(policy, {"tool-a"})
        behaviour._utilized_tools = {}

        benchmark_ctx = MagicMock()
        behaviour.context.benchmark_tool.measure.return_value = benchmark_ctx  # type: ignore[attr-defined]
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        # benchmarking enabled but period_count != 0
        behaviour.benchmarking_mode.enabled = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.period_count = 1  # type: ignore[attr-defined]

        behaviour._store_all = MagicMock()  # type: ignore[method-assign,assignment]

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool", return_value="tool-a"):
                with patch.object(policy, "tool_used") as mock_tool_used:
                    with patch.object(
                        behaviour,
                        "finish_behaviour",
                        side_effect=lambda p: iter([None]),
                    ):
                        _run_async_act(behaviour)

        mock_tool_used.assert_not_called()

    def test_benchmarking_last_run_skips_tool_used(self) -> None:
        """Should not call policy.tool_used when last_benchmarking_has_run is True."""
        policy = _make_policy("tool-a")
        behaviour = _make_behaviour(policy, {"tool-a"})
        behaviour._utilized_tools = {}

        benchmark_ctx = MagicMock()
        behaviour.context.benchmark_tool.measure.return_value = benchmark_ctx  # type: ignore[attr-defined]
        benchmark_ctx.local.return_value.__enter__ = MagicMock()
        benchmark_ctx.local.return_value.__exit__ = MagicMock(return_value=False)

        # benchmarking enabled, period_count=0, but last_benchmarking_has_run=True
        behaviour.benchmarking_mode.enabled = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.period_count = 0  # type: ignore[attr-defined]
        behaviour.shared_state.last_benchmarking_has_run = True  # type: ignore[attr-defined]

        behaviour._store_all = MagicMock()  # type: ignore[method-assign,assignment]

        with patch.object(
            _TestableBehaviour, "_setup_policy_and_tools", _mock_setup(True)
        ):
            with patch.object(policy, "select_tool", return_value="tool-a"):
                with patch.object(policy, "tool_used") as mock_tool_used:
                    with patch.object(
                        behaviour,
                        "finish_behaviour",
                        side_effect=lambda p: iter([None]),
                    ):
                        _run_async_act(behaviour)

        mock_tool_used.assert_not_called()


# ---------------------------------------------------------------------------
# Suitability classifier integration: __init__, _extract_tool_metadata,
# _fetch_mech_manifests, and the suitability branch of _candidate_tools.
# ---------------------------------------------------------------------------


class _StubManifestMech:
    """Mech stub with a `.service.metadata_str` for the V2 fetch loop."""

    def __init__(self, address: str, metadata_str: Optional[str]) -> None:
        self.address = address
        self.relevant_tools: set = set()
        self.service = MagicMock(metadata_str=metadata_str)


class _PredictionMetadata:
    """Convenience builders for manifest blobs used in classifier tests."""

    PREDICTION_EXAMPLE = (
        '{"p_yes": 0.6, "p_no": 0.4, "confidence": 0.8, "info_utility": 0.6}'
    )

    @staticmethod
    def predictor(description: str = "Makes binary predictions.") -> dict:
        """Manifest blob that the classifier passes."""
        return {
            "description": description,
            "input": {
                "type": "text",
                "description": "The text to make a prediction on",
            },
            "output": {
                "schema": {
                    "properties": {
                        "result": {
                            "type": "string",
                            "example": _PredictionMetadata.PREDICTION_EXAMPLE,
                        }
                    }
                }
            },
        }

    @staticmethod
    def resolver() -> dict:
        """Manifest blob that the classifier rejects (resolver shape)."""
        return {
            "description": "Resolves prediction markets after they have closed.",
            "input": {"type": "text", "description": "market question"},
            "output": {
                "schema": {
                    "properties": {
                        "result": {
                            "type": "string",
                            "example": (
                                '{"is_valid": true, "is_determinable": true, '
                                '"has_occurred": true}'
                            ),
                        }
                    }
                }
            },
        }


class TestToolSelectionInit:
    """ToolSelectionBehaviour.__init__ initializes the per-round cache."""

    def test_tool_metadata_starts_empty(self) -> None:
        """The classifier cache must default to an empty dict on instantiation."""
        behaviour = ToolSelectionBehaviour.__new__(ToolSelectionBehaviour)
        ToolSelectionBehaviour.__init__(  # type: ignore[misc]
            behaviour, name="x", skill_context=MagicMock()
        )
        assert behaviour._tool_metadata == {}


class TestExtractToolMetadata:
    """_extract_tool_metadata isolates and lowercases the toolMetadata blob."""

    def test_happy_path_lowercases_and_filters_non_dict(self) -> None:
        """Valid manifest body returns lowercased tool-name keyed dict, dropping non-dicts."""
        body = {
            "tools": ["a", "b"],
            "toolMetadata": {
                "TOOL-A": {"description": "alpha"},
                "tool-b": {"description": "beta"},
                "bogus": "not-a-dict",
            },
        }
        res_raw = MagicMock(body=json.dumps(body).encode())

        out = ToolSelectionBehaviour._extract_tool_metadata(res_raw)

        assert out == {
            "tool-a": {"description": "alpha"},
            "tool-b": {"description": "beta"},
        }

    def test_returns_empty_on_decode_error(self) -> None:
        """Non-UTF-8 body returns empty dict (caught by UnicodeDecodeError)."""
        res_raw = MagicMock(body=b"\xff\xfe garbage")
        assert ToolSelectionBehaviour._extract_tool_metadata(res_raw) == {}

    def test_returns_empty_on_json_error(self) -> None:
        """Malformed JSON returns empty dict."""
        res_raw = MagicMock(body=b"{not json")
        assert ToolSelectionBehaviour._extract_tool_metadata(res_raw) == {}

    def test_returns_empty_when_body_missing_attribute(self) -> None:
        """A response without a `.body` attribute returns empty (AttributeError)."""
        res_raw = object()  # no .body
        assert ToolSelectionBehaviour._extract_tool_metadata(res_raw) == {}

    def test_returns_empty_when_no_tool_metadata_key(self) -> None:
        """Body without `toolMetadata` returns empty dict."""
        res_raw = MagicMock(body=json.dumps({"tools": ["a"]}).encode())
        assert ToolSelectionBehaviour._extract_tool_metadata(res_raw) == {}

    def test_returns_empty_when_tool_metadata_not_a_dict(self) -> None:
        """A `toolMetadata` value that isn't a dict returns empty."""
        res_raw = MagicMock(body=json.dumps({"toolMetadata": ["unexpected"]}).encode())
        assert ToolSelectionBehaviour._extract_tool_metadata(res_raw) == {}


def _attach_mech_tools_api(behaviour: "_TestableBehaviour") -> MagicMock:
    """Wire a writable mech_tools_api stub onto a _TestableBehaviour."""
    api = MagicMock()
    api.__dict__["_frozen"] = True
    api.get_spec.return_value = {"method": "GET", "url": "x"}
    behaviour.mech_tools_api = api  # type: ignore[attr-defined,assignment]
    return api


def _drive_fetch(behaviour: "_TestableBehaviour") -> None:
    """Run _fetch_mech_manifests to completion."""
    gen = behaviour._fetch_mech_manifests()
    try:
        while True:
            next(gen)
    except StopIteration:
        return


class TestFetchMechManifests:
    """_fetch_mech_manifests populates the cache and short-circuits as needed."""

    def test_short_circuits_when_v1(self) -> None:
        """V1 marketplace path never fetches and leaves the cache empty."""
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour.synchronized_data.is_marketplace_v2 = False  # type: ignore[attr-defined]
        behaviour.synchronized_data.mechs_info = [  # type: ignore[attr-defined]
            _StubManifestMech("0xa", "cid-1"),
        ]
        _attach_mech_tools_api(behaviour)
        behaviour._tool_metadata = {"stale": {"description": "x"}}

        called = {"n": 0}

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            called["n"] += 1
            return MagicMock(body=b"{}")
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        _drive_fetch(behaviour)

        assert behaviour._tool_metadata == {}
        assert called["n"] == 0

    def test_short_circuits_when_benchmarking_enabled(self) -> None:
        """Benchmark mode never hits IPFS."""
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour.synchronized_data.is_marketplace_v2 = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.mechs_info = [  # type: ignore[attr-defined]
            _StubManifestMech("0xa", "cid-1"),
        ]
        _attach_mech_tools_api(behaviour)
        behaviour.benchmarking_mode.enabled = True  # type: ignore[attr-defined]

        called = {"n": 0}

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            called["n"] += 1
            return MagicMock(body=b"{}")
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        _drive_fetch(behaviour)

        assert behaviour._tool_metadata == {}
        assert called["n"] == 0

    def test_fetches_each_unique_cid_once(self) -> None:
        """Mechs that share a CID resolve to a single HTTP fetch."""
        policy = _make_policy("good", "bad")
        behaviour = _make_behaviour(policy, {"good", "bad"})
        behaviour.synchronized_data.is_marketplace_v2 = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.mechs_info = [  # type: ignore[attr-defined]
            _StubManifestMech("0xa", "cid-1"),
            _StubManifestMech("0xb", "cid-1"),  # same CID
            _StubManifestMech("0xc", "cid-2"),
            _StubManifestMech("0xd", None),  # no CID, skipped
        ]
        api = _attach_mech_tools_api(behaviour)

        body = {
            "toolMetadata": {
                "good": _PredictionMetadata.predictor(),
                "bad": _PredictionMetadata.resolver(),
            }
        }
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )

        call_count = {"n": 0}

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            call_count["n"] += 1
            return MagicMock(body=json.dumps(body).encode())
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        _drive_fetch(behaviour)

        # 2 unique CIDs -> 2 HTTP calls (the dup CID and the None one are skipped).
        assert call_count["n"] == 2
        assert set(behaviour._tool_metadata) == {"good", "bad"}
        # Final URL must reflect ipfs_address + CID_PREFIX + last CID so a refactor
        # that drops CID_PREFIX or swaps the concat order trips the test.
        assert api.url == "https://ipfs.example/" + CID_PREFIX + "cid-2"
        api.reset_retries.assert_called()

    def test_extraction_failure_leaves_cache_partially_populated(self) -> None:
        """A manifest with no toolMetadata is silently skipped, others still land."""
        policy = _make_policy("tool")
        behaviour = _make_behaviour(policy, {"tool"})
        behaviour.synchronized_data.is_marketplace_v2 = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.mechs_info = [  # type: ignore[attr-defined]
            _StubManifestMech("0xgood", "cid-good"),
            _StubManifestMech("0xbad", "cid-bad"),
        ]
        _attach_mech_tools_api(behaviour)
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )

        bodies = [
            MagicMock(
                body=json.dumps(
                    {"toolMetadata": {"tool": _PredictionMetadata.predictor()}}
                ).encode()
            ),
            MagicMock(body=b"not-json", status_code=404),  # extraction failure
        ]

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            return bodies.pop(0)
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        _drive_fetch(behaviour)

        assert set(behaviour._tool_metadata) == {"tool"}
        # Per-CID warning fires for the failing manifest so the silent skip is
        # visible in logs.
        warnings = [
            call.args[0]
            for call in behaviour.context.logger.warning.call_args_list  # type: ignore[attr-defined]
        ]
        assert any("cid-bad" in msg for msg in warnings)

    def test_warns_when_every_manifest_fails(self) -> None:
        """A summary warning fires when every CID extraction fails.

        Without this warning the classifier-bypass case is silent.
        """
        policy = _make_policy("tool")
        behaviour = _make_behaviour(policy, {"tool"})
        behaviour.synchronized_data.is_marketplace_v2 = True  # type: ignore[attr-defined]
        behaviour.synchronized_data.mechs_info = [  # type: ignore[attr-defined]
            _StubManifestMech("0xa", "cid-a"),
            _StubManifestMech("0xb", "cid-b"),
        ]
        _attach_mech_tools_api(behaviour)
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            return MagicMock(body=b"not-json", status_code=404)
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        _drive_fetch(behaviour)

        assert behaviour._tool_metadata == {}
        warnings = [
            call.args[0]
            for call in behaviour.context.logger.warning.call_args_list  # type: ignore[attr-defined]
        ]
        assert any(
            "no metadata for any of" in msg and "suitability filter" in msg
            for msg in warnings
        )


def _drive_fetch_one(behaviour: "_TestableBehaviour") -> bool:
    """Drive _fetch_one_manifest to completion and return its bool value."""
    gen = behaviour._fetch_one_manifest()
    try:
        while True:
            next(gen)
    except StopIteration as exc:
        return bool(exc.value)
    return False  # unreachable; keeps mypy happy


class TestFetchOneManifest:
    """_fetch_one_manifest implements the canonical retry contract."""

    def test_success_resets_retries_and_returns_true(self) -> None:
        """A valid manifest updates the cache, resets retries, returns True."""
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour._pending_cid = "cid-ok"
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )
        api = _attach_mech_tools_api(behaviour)
        body = {"toolMetadata": {"t": _PredictionMetadata.predictor()}}

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            return MagicMock(body=json.dumps(body).encode())
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        done = _drive_fetch_one(behaviour)

        assert done is True
        assert behaviour._tool_metadata == {"t": _PredictionMetadata.predictor()}
        api.reset_retries.assert_called()
        api.increment_retries.assert_not_called()

    def test_permanent_error_resets_and_returns_true(self) -> None:
        """A permanent error skips retries, logs a warning, returns True."""
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour._pending_cid = "cid-bad"
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )
        api = _attach_mech_tools_api(behaviour)
        api.is_permanent_error.return_value = True

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            return MagicMock(body=b"not-json", status_code=404)
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        done = _drive_fetch_one(behaviour)

        assert done is True
        assert behaviour._tool_metadata == {}
        api.reset_retries.assert_called()
        api.increment_retries.assert_not_called()
        warnings = [
            call.args[0]
            for call in behaviour.context.logger.warning.call_args_list  # type: ignore[attr-defined]
        ]
        assert any("permanent error" in msg for msg in warnings)

    def test_transient_error_within_budget_returns_false(self) -> None:
        """A transient error increments retries and yields a re-invoke.

        The outer driver re-invokes on False until the budget burns.
        """
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour._pending_cid = "cid-flaky"
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )
        api = _attach_mech_tools_api(behaviour)
        api.is_permanent_error.return_value = False
        api.is_retries_exceeded.return_value = False

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            return MagicMock(body=b"not-json", status_code=503)
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        done = _drive_fetch_one(behaviour)

        assert done is False
        assert behaviour._tool_metadata == {}
        api.increment_retries.assert_called_once()
        api.reset_retries.assert_not_called()

    def test_transient_error_when_retries_exceeded_returns_true(self) -> None:
        """When the retry budget is burned, the warning fires and we give up."""
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour._pending_cid = "cid-dead"
        behaviour.params = MagicMock(  # type: ignore[attr-defined,assignment]
            ipfs_address="https://ipfs.example/"
        )
        api = _attach_mech_tools_api(behaviour)
        api.is_permanent_error.return_value = False
        api.is_retries_exceeded.return_value = True

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            return MagicMock(body=b"not-json", status_code=503)
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        done = _drive_fetch_one(behaviour)

        assert done is True
        assert behaviour._tool_metadata == {}
        api.increment_retries.assert_called_once()
        api.reset_retries.assert_called()
        warnings = [
            call.args[0]
            for call in behaviour.context.logger.warning.call_args_list  # type: ignore[attr-defined]
        ]
        assert any("retries exhausted" in msg for msg in warnings)

    def test_returns_true_when_no_pending_cid(self) -> None:
        """A None pending_cid short-circuits without hitting the network."""
        behaviour = _make_behaviour(_make_policy("t"), {"t"})
        behaviour._pending_cid = None
        _attach_mech_tools_api(behaviour)

        called = {"n": 0}

        def _http_gen(**_kw: Any) -> Generator[None, None, Any]:
            called["n"] += 1
            return MagicMock(body=b"{}")
            yield  # generator function

        behaviour.get_http_response = _http_gen  # type: ignore[method-assign,assignment]

        done = _drive_fetch_one(behaviour)

        assert done is True
        assert called["n"] == 0


class TestCandidateToolsSuitability:
    """_candidate_tools applies the suitability classifier when metadata exists."""

    def test_suitability_keeps_prediction_tools_and_drops_others(self) -> None:
        """Classifier passes prediction tools, drops resolver-shaped ones."""
        policy = _make_policy("good", "bad")
        behaviour = _make_behaviour(policy, {"good", "bad"})
        behaviour._tool_metadata = {
            "good": _PredictionMetadata.predictor(),
            "bad": _PredictionMetadata.resolver(),
        }

        candidate, cause = behaviour._candidate_tools()

        assert candidate == {"good"}
        assert cause is None
        # The "every candidate unsuitable" fallback WARNING must NOT fire when
        # any predictor survives; mutating the `elif candidate:` guard to a
        # plain `if candidate:` would trip this assertion.
        behaviour.context.logger.warning.assert_not_called()  # type: ignore[attr-defined]

    def test_suitability_emptied_keeps_raw_mech_tools_and_warns(self) -> None:
        """If classifier rejects every tool, fall back to raw mech_tools + log a warning."""
        policy = _make_policy("only")
        behaviour = _make_behaviour(policy, {"only"})
        behaviour._tool_metadata = {"only": _PredictionMetadata.resolver()}

        candidate, cause = behaviour._candidate_tools()

        assert candidate == {"only"}
        assert cause is None
        behaviour.context.logger.warning.assert_called()  # type: ignore[attr-defined]

    def test_suitability_skipped_when_no_metadata(self) -> None:
        """Empty metadata cache leaves the candidate set untouched."""
        policy = _make_policy("a", "b")
        behaviour = _make_behaviour(policy, {"a", "b"})
        behaviour._tool_metadata = {}

        candidate, cause = behaviour._candidate_tools()

        assert candidate == {"a", "b"}
        assert cause is None

    def test_publishes_filtered_set_to_shared_state(self) -> None:
        """The post-suitability set is published for the ChatUI to read."""
        policy = _make_policy("good", "bad")
        behaviour = _make_behaviour(policy, {"good", "bad"})
        behaviour._tool_metadata = {
            "good": _PredictionMetadata.predictor(),
            "bad": _PredictionMetadata.resolver(),
        }

        behaviour._candidate_tools()

        published = behaviour.shared_state.available_prediction_tools  # type: ignore[attr-defined]
        assert published == frozenset({"good"})

    def test_published_set_is_pre_pin(self) -> None:
        """The published set is the suitable universe, not the pinned subset.

        An ``allowed_tools`` pin narrows the returned candidate but must not
        shrink the published set — the ChatUI validates pins against the full
        selectable universe, and the policy keeps learning across it.
        """
        policy = _make_policy("good", "also-good")
        behaviour = _make_behaviour(
            policy, {"good", "also-good"}, allowed_tools=["good"]
        )
        behaviour._tool_metadata = {
            "good": _PredictionMetadata.predictor(),
            "also-good": _PredictionMetadata.predictor(),
        }

        candidate, _ = behaviour._candidate_tools()

        assert candidate == {"good"}  # pin applied to the returned set
        published = behaviour.shared_state.available_prediction_tools  # type: ignore[attr-defined]
        assert published == frozenset({"good", "also-good"})

    def test_publishes_raw_set_when_classifier_cannot_run(self) -> None:
        """With no manifest data the published set falls back to raw mech_tools."""
        policy = _make_policy("a", "b")
        behaviour = _make_behaviour(policy, {"a", "b"})
        behaviour._tool_metadata = {}

        behaviour._candidate_tools()

        published = behaviour.shared_state.available_prediction_tools  # type: ignore[attr-defined]
        assert published == frozenset({"a", "b"})

    def test_drop_partition_separates_classifier_from_missing_manifest(
        self,
    ) -> None:
        """Dropped tools are split into rejected vs no-manifest WARNINGs."""
        policy = _make_policy("predictor", "resolver", "ghost")
        behaviour = _make_behaviour(policy, {"predictor", "resolver", "ghost"})
        behaviour._tool_metadata = {
            "predictor": _PredictionMetadata.predictor(),
            "resolver": _PredictionMetadata.resolver(),
            # "ghost" intentionally absent: its CID failed to fetch
        }

        candidate, cause = behaviour._candidate_tools()

        assert candidate == {"predictor"}
        assert cause is None
        infos = [
            call.args[0]
            for call in behaviour.context.logger.info.call_args_list  # type: ignore[attr-defined]
        ]
        assert any(
            "rejected by classifier" in msg
            and "schema_resolver_shape" in msg
            and "resolver" in msg
            for msg in infos
        )
        warnings = [
            call.args[0]
            for call in behaviour.context.logger.warning.call_args_list  # type: ignore[attr-defined]
        ]
        assert any(
            "no manifest data was available" in msg and "ghost" in msg
            for msg in warnings
        )


# ---------------------------------------------------------------------------
# _maybe_publish_suitable_tools — the stop-trading publish path.
#
# Lives on StorageManagerBehaviour (the shared base) so the redeem path
# publishes the suitability-filtered set even when ToolSelectionRound never
# runs. Exercised here through ToolSelectionBehaviour, which inherits it.
# ---------------------------------------------------------------------------


def _drive_publish(behaviour: "ToolSelectionBehaviour") -> None:
    """Drive _maybe_publish_suitable_tools() to completion."""
    gen = behaviour._maybe_publish_suitable_tools()
    try:
        while True:
            next(gen)
    except StopIteration:
        pass


def _stub_fetch(
    behaviour: "_TestableBehaviour", metadata: Dict[str, Dict[str, Any]]
) -> List[bool]:
    """Stub _fetch_mech_manifests to seed _tool_metadata; returns a run flag."""
    # The returned single-element list flips to True when the stub runs, so a
    # test can assert whether the (expensive) fetch was reached or skipped.
    called = [False]

    def _gen() -> Generator[None, None, None]:
        called[0] = True
        behaviour._tool_metadata = dict(metadata)  # type: ignore[attr-defined]
        return
        yield  # make it a generator function

    behaviour._fetch_mech_manifests = _gen  # type: ignore[assignment,method-assign]
    return called


class TestMaybePublishSuitableTools:
    """The setup-path publish that covers the stop-trading window."""

    def _v2_behaviour(self) -> "_TestableBehaviour":
        behaviour = _make_behaviour(
            _make_policy("predictor"), {"predictor", "resolver"}
        )
        behaviour.synchronized_data.is_marketplace_v2 = True  # type: ignore[attr-defined]
        behaviour.shared_state.available_prediction_tools = None  # type: ignore[attr-defined]
        return behaviour

    def test_publishes_suitable_subset_when_unset(self) -> None:
        """A v2 boot with no prior publish narrows raw -> suitable and publishes."""
        behaviour = self._v2_behaviour()
        called = _stub_fetch(
            behaviour,
            {
                "predictor": _PredictionMetadata.predictor(),
                "resolver": _PredictionMetadata.resolver(),
            },
        )

        _drive_publish(behaviour)

        assert called[0] is True
        published = behaviour.shared_state.available_prediction_tools  # type: ignore[attr-defined]
        assert published == frozenset({"predictor"})

    def test_skips_and_keeps_value_when_already_published(self) -> None:
        """An already-populated set (e.g. ToolSelectionRound this boot) is not touched."""
        behaviour = self._v2_behaviour()
        behaviour.shared_state.available_prediction_tools = frozenset({"predictor"})  # type: ignore[attr-defined]
        called = _stub_fetch(behaviour, {"predictor": _PredictionMetadata.predictor()})

        _drive_publish(behaviour)

        # No re-fetch, value left intact.
        assert called[0] is False
        published = behaviour.shared_state.available_prediction_tools  # type: ignore[attr-defined]
        assert published == frozenset({"predictor"})

    def test_skips_for_marketplace_v1(self) -> None:
        """v1 has no manifest classifier; never publish, never fetch."""
        behaviour = self._v2_behaviour()
        behaviour.synchronized_data.is_marketplace_v2 = False  # type: ignore[attr-defined]
        called = _stub_fetch(behaviour, {"predictor": _PredictionMetadata.predictor()})

        _drive_publish(behaviour)

        assert called[0] is False
        assert behaviour.shared_state.available_prediction_tools is None  # type: ignore[attr-defined]

    def test_skips_when_benchmarking(self) -> None:
        """Benchmarking mode short-circuits the fetch and the publish."""
        behaviour = self._v2_behaviour()
        behaviour.benchmarking_mode.enabled = True  # type: ignore[attr-defined]
        called = _stub_fetch(behaviour, {"predictor": _PredictionMetadata.predictor()})

        _drive_publish(behaviour)

        assert called[0] is False
        assert behaviour.shared_state.available_prediction_tools is None  # type: ignore[attr-defined]

    def test_no_publish_on_fetch_failure(self) -> None:
        """An empty metadata cache (IPFS outage) leaves the field unpublished."""
        behaviour = self._v2_behaviour()
        _stub_fetch(behaviour, {})  # fetch yields no metadata

        _drive_publish(behaviour)

        assert behaviour.shared_state.available_prediction_tools is None  # type: ignore[attr-defined]

    def test_no_publish_when_all_unsuitable(self) -> None:
        """If every raw tool is unsuitable, keep None so ChatUI falls back to raw."""
        behaviour = _make_behaviour(_make_policy("resolver"), {"resolver"})
        behaviour.synchronized_data.is_marketplace_v2 = True  # type: ignore[attr-defined]
        behaviour.shared_state.available_prediction_tools = None  # type: ignore[attr-defined]
        _stub_fetch(behaviour, {"resolver": _PredictionMetadata.resolver()})

        _drive_publish(behaviour)

        assert behaviour.shared_state.available_prediction_tools is None  # type: ignore[attr-defined]
