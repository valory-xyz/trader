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

"""This package contains the tests for Decision Maker"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from packages.valory.skills.abstract_round_abci.base import VotingRound
from packages.valory.skills.decision_maker_abci.rounds import CheckBenchmarkingModeRound
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


def test_check_benchmarking_mode_round_initialization() -> None:
    """Test the initialization of CheckBenchmarkingModeRound."""
    round_instance = CheckBenchmarkingModeRound(MagicMock(), MagicMock())

    # Test that the round is properly initialized with the correct event types
    assert round_instance.done_event == Event.BENCHMARKING_ENABLED
    assert round_instance.negative_event == Event.BENCHMARKING_DISABLED

    # Check that it inherits from VotingRound
    assert isinstance(round_instance, VotingRound)


def test_check_benchmarking_mode_round_events() -> None:
    """Test that the correct events are used in the CheckBenchmarkingModeRound."""
    round_instance = CheckBenchmarkingModeRound(MagicMock(), MagicMock())

    # Assert that the done_event is BENCHMARKING_ENABLED
    assert round_instance.done_event == Event.BENCHMARKING_ENABLED

    # Assert that the negative_event is BENCHMARKING_DISABLED
    assert round_instance.negative_event == Event.BENCHMARKING_DISABLED


def test_end_block_polymarket_allowances_set_current_version() -> None:
    """A file stamped with the current CLOB version skips approval."""
    from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
        POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
    )

    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        allowances_path = Path(tmpdir) / "polymarket.json"
        with open(allowances_path, "w") as f:
            json.dump(
                {
                    "allowances_set": True,
                    "clob_version": POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
                },
                f,
            )

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.BENCHMARKING_DISABLED


def test_end_block_polymarket_stale_v1_allowances_file_reapproves() -> None:
    """A legacy v1 file (no ``clob_version``) must trigger re-approval.

    This guards the v2-cutover invariant: an agent carrying a v1-era
    ``allowances_set: true`` file must not bypass the approval round,
    because the v1 allowances point at retired exchange contracts.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        allowances_path = Path(tmpdir) / "polymarket.json"
        with open(allowances_path, "w") as f:
            json.dump({"allowances_set": True}, f)  # no clob_version

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    # With a stale (unversioned) file, the round must NOT short-circuit
    # to BENCHMARKING_DISABLED — it falls through to SET_APPROVAL so the
    # agent re-issues approvals against v2 addresses.
    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_polymarket_stale_v2_allowances_file_reapproves() -> None:
    """A v2 file must trigger re-approval after the v3 collateral-adapter cutover.

    Bumping ``POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION`` to ``v3`` invalidates
    every Safe's prior ``allowances_set: true`` stamped under v2, so the
    agent re-issues the expanded approval set that includes
    ``setApprovalForAll`` for the new ``CtfCollateralAdapter`` /
    ``NegRiskCtfCollateralAdapter``. Without that bump, redeem would target
    the new adapters with stale operator approvals and silently no-op.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        allowances_path = Path(tmpdir) / "polymarket.json"
        with open(allowances_path, "w") as f:
            json.dump({"allowances_set": True, "clob_version": "v2"}, f)

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_clob_version_constant_is_v3() -> None:
    """The CLOB-version stamp must be ``v3``.

    Tying the constant down ensures the v2→v3 migration trigger lands; a
    silent revert to ``v2`` would let stale persisted files short-circuit
    the approval round.
    """
    from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
        POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
    )

    assert POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION == "v3"


def test_end_block_polymarket_allowances_not_set() -> None:
    """Test end_block on Polymarket with allowances not set."""
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        allowances_path = Path(tmpdir) / "polymarket.json"
        with open(allowances_path, "w") as f:
            json.dump({"allowances_set": False}, f)

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_polymarket_no_allowances_file() -> None:
    """Test end_block on Polymarket with no allowances file."""
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        # No file created

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_polymarket_invalid_json() -> None:
    """Test end_block on Polymarket with invalid JSON in allowances file."""
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        allowances_path = Path(tmpdir) / "polymarket.json"
        with open(allowances_path, "w") as f:
            f.write("not valid json")

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_non_polymarket_delegates_to_super() -> None:
    """Test end_block delegates to super when not on Polymarket."""
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = False
    mock_synced_data = MagicMock(spec=SynchronizedData)

    round_instance = CheckBenchmarkingModeRound(
        synchronized_data=mock_synced_data, context=mock_context
    )
    with patch.object(VotingRound, "end_block", return_value=None):
        result = round_instance.end_block()

    assert result is None
