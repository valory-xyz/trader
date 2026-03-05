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

"""Tests for CheckBenchmarkingModeBehaviour."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.check_benchmarking import (
    CheckBenchmarkingModeBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():  # type: ignore[no-untyped-def]
    """A no-op generator that yields once."""
    yield


def _make_behaviour(benchmarking_enabled=False):  # type: ignore[no-untyped-def]
    """Return a CheckBenchmarkingModeBehaviour with mocked dependencies."""
    behaviour = object.__new__(CheckBenchmarkingModeBehaviour)

    context = MagicMock()
    context.agent_address = "test_agent"
    context.benchmark_tool.measure.return_value.local.return_value.__enter__ = (
        MagicMock()
    )
    context.benchmark_tool.measure.return_value.local.return_value.__exit__ = (
        MagicMock()
    )
    behaviour.__dict__["_context"] = context

    benchmarking_mode = MagicMock()
    benchmarking_mode.enabled = benchmarking_enabled

    return behaviour, benchmarking_mode


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckBenchmarkingModeBehaviour:
    """Tests for CheckBenchmarkingModeBehaviour.async_act."""

    def test_async_act_sends_benchmarking_enabled_true(self) -> None:
        """When benchmarking is enabled, payload vote should be True."""
        behaviour, bm_mode = _make_behaviour(benchmarking_enabled=True)

        payloads_sent = []

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = bm_mode

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], VotingPayload)
        assert payloads_sent[0].vote is True

    def test_async_act_sends_benchmarking_enabled_false(self) -> None:
        """When benchmarking is disabled, payload vote should be False."""
        behaviour, bm_mode = _make_behaviour(benchmarking_enabled=False)

        payloads_sent = []

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = bm_mode

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], VotingPayload)
        assert payloads_sent[0].vote is False

    def test_matching_round_is_correct(self) -> None:
        """matching_round should reference CheckBenchmarkingModeRound."""
        from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
            CheckBenchmarkingModeRound,
        )

        assert (
            CheckBenchmarkingModeBehaviour.matching_round == CheckBenchmarkingModeRound
        )
