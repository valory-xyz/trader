# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for ToolSelectionBehaviour._select_tool (allowed_tools restriction logic)."""

from typing import Callable, Generator, List, Optional
from unittest.mock import MagicMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.tool_selection import (
    ToolSelectionBehaviour,
)
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


def _make_behaviour(
    policy: EGreedyPolicy,
    mech_tools: set,
    allowed_tools: Optional[List[str]] = None,
    randomness: str = RANDOMNESS,
) -> _TestableBehaviour:
    """Return a _TestableBehaviour wired with mocked dependencies."""
    behaviour = object.__new__(_TestableBehaviour)  # type: ignore[type-abstract]

    # context
    context = MagicMock()
    behaviour.context = context

    # benchmarking_mode disabled so we use synchronized_data.most_voted_randomness
    benchmarking_mode = MagicMock()
    benchmarking_mode.enabled = False
    behaviour.benchmarking_mode = benchmarking_mode  # type: ignore[misc]

    # synchronized_data
    sync_data = MagicMock()
    sync_data.most_voted_randomness = randomness
    behaviour.synchronized_data = sync_data  # type: ignore[misc]

    # shared_state / chatui_config
    shared_state = MagicMock()
    shared_state.chatui_config.allowed_tools = allowed_tools
    behaviour.shared_state = shared_state  # type: ignore[misc]

    # policy and mech_tools
    behaviour.policy = policy  # type: ignore[misc]
    behaviour.mech_tools = mech_tools

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


class TestSelectToolEmptyIntersection:
    """Tests for _select_tool when allowed_tools has no intersection with mech_tools."""

    def test_falls_back_to_unrestricted_policy_and_logs_warning(self) -> None:
        """When no allowed tool exists in mech_tools, fallback to full policy + warning."""
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

        assert result == "tool-a"
        mock_select.assert_called_once_with(RANDOMNESS)
        behaviour.context.logger.warning.assert_called_once()  # type: ignore[attr-defined]
        warning_msg: str = behaviour.context.logger.warning.call_args[0][0]  # type: ignore[attr-defined]
        assert "Falling back" in warning_msg

    def test_original_policy_store_not_mutated_on_fallback(self) -> None:
        """Even the fallback path must leave the original accuracy_store untouched."""
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

        assert set(policy.accuracy_store.keys()) == original_keys
