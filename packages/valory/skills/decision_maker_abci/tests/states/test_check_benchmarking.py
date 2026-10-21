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
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import VotingRound
from packages.valory.skills.decision_maker_abci.rounds import CheckBenchmarkingModeRound
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
    DW_APPROVALS_VERSION,
)
from packages.valory.skills.decision_maker_abci.tests.polymarket_approvals import (
    DW_V2_APPROVALS,
    POSITION_MANAGER,
    ROUTER,
    decode_dw_calls,
    docs_addresses,
    expected_calls,
)

# A DepositWallet record whose approvals are confirmed for the current set.
_CURRENT_DW_RECORD = {
    "dw_address": "0xDW",
    "dw_owner": "0xagent",
    "approvals_done": True,
    "approvals_version": DW_APPROVALS_VERSION,
}


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


def _current_allowances(tmpdir) -> None:  # type: ignore[no-untyped-def]
    """Write a ``polymarket.json`` stamped with the current CLOB version."""
    from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
        POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
    )

    with open(Path(tmpdir) / "polymarket.json", "w") as f:
        json.dump(
            {
                "allowances_set": True,
                "clob_version": POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
            },
            f,
        )


def _write_dw(tmpdir, data) -> None:  # type: ignore[no-untyped-def]
    """Write a ``deposit_wallet.json`` with the given payload."""
    with open(Path(tmpdir) / "deposit_wallet.json", "w") as f:
        json.dump(data, f)


def test_end_block_allowances_current_and_dw_present_skips() -> None:
    """Allowances current AND a DW owned by the agent EOA skips approval.

    This is the only configuration that may bypass SET_APPROVAL: a
    restart with valid state. Owner matching is case-insensitive.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_context.agent_address = "0xAGENT"
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        _current_allowances(tmpdir)
        _write_dw(tmpdir, _CURRENT_DW_RECORD)

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.BENCHMARKING_DISABLED


def test_end_block_allowances_current_but_no_dw_reapproves() -> None:
    """Allowances current but NO DepositWallet recorded re-enters setup.

    Covers a fresh canonical-Safe or grandfathered Polystrat whose
    ``polymarket.json`` already looks current: setup must still run to
    provision the DepositWallet.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_context.agent_address = "0xAGENT"
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        _current_allowances(tmpdir)  # no deposit_wallet.json

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_allowances_current_but_dw_owner_mismatch_reapproves() -> None:
    """Allowances current but a DW owned by a different EOA re-enters setup.

    Covers mnemonic-recovery rotation: the recorded ``dw_owner`` no longer
    matches the agent EOA, so the DW must be re-provisioned under the new
    EOA.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_context.agent_address = "0xAGENT"
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        _current_allowances(tmpdir)
        _write_dw(tmpdir, {"dw_address": "0xDW", "dw_owner": "0xOLD"})

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_allowances_current_but_dw_no_address_reapproves() -> None:
    """A DW record without an address is treated as not-ready (re-enters setup)."""
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_context.agent_address = "0xAGENT"
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        _current_allowances(tmpdir)
        _write_dw(tmpdir, {"dw_owner": "0xAGENT"})  # no dw_address

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def test_end_block_allowances_current_but_dw_invalid_json_reapproves() -> None:
    """A malformed ``deposit_wallet.json`` is treated as not-ready."""
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_context.agent_address = "0xAGENT"
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        _current_allowances(tmpdir)
        with open(Path(tmpdir) / "deposit_wallet.json", "w") as f:
            f.write("not valid json")

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


@pytest.mark.parametrize(
    "record",
    [
        {"dw_address": "0xDW", "dw_owner": "0xagent", "approvals_done": True},
        {**_CURRENT_DW_RECORD, "approvals_version": None},
        {**_CURRENT_DW_RECORD, "approvals_version": DW_APPROVALS_VERSION - 1},
        {**_CURRENT_DW_RECORD, "approvals_version": DW_APPROVALS_VERSION + 1},
        {**_CURRENT_DW_RECORD, "approvals_version": str(DW_APPROVALS_VERSION)},
        {**_CURRENT_DW_RECORD, "approvals_done": False},
        {"dw_address": "0xDW", "dw_owner": "0xagent", "approvals_done": False},
        {
            "dw_address": "0xDW",
            "dw_owner": "0xagent",
            "approvals_version": DW_APPROVALS_VERSION,
        },
        {**_CURRENT_DW_RECORD, "approvals_done": "true"},
        {**_CURRENT_DW_RECORD, "approvals_done": 1},
    ],
    ids=[
        "pre_v2",
        "version_none",
        "version_stale",
        "version_newer",
        "version_string",
        "approvals_pending",
        "approvals_pending_pre_v2",
        "approvals_flag_missing",
        "approvals_flag_string",
        "approvals_flag_int",
    ],
)
def test_end_block_allowances_current_but_dw_approvals_not_current_reapproves(
    record: Dict[str, Any],
) -> None:
    """Current Safe allowances do not skip setup while the DW approvals lag.

    The gate is skipped only for a record whose ``approvals_done`` is ``True``
    and whose ``approvals_version`` is exactly the current one; a pre-V2
    record, a stale or foreign version, or unconfirmed approvals re-enter
    SET_APPROVAL even when ``polymarket.json`` carries the current stamp.

    :param record: the persisted DepositWallet record.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        _current_allowances(tmpdir)
        _write_dw(tmpdir, record)
        event = _end_block_event(tmpdir)

    assert event == Event.SET_APPROVAL


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


def test_clob_version_constant_is_v5() -> None:
    """The CLOB-version stamp must be ``v5``.

    Tying the constant down ensures the v4→v5 migration trigger lands; a
    silent revert to ``v4`` would let installs whose Safe approvals predate
    Protocol V2 short-circuit the approval round and never grant the Router
    ``setApprovalForAll`` on the PositionManager.
    """
    from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
        POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
    )

    assert POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION == "v5"


def test_end_block_polymarket_stale_v4_allowances_file_reapproves() -> None:
    """A v4 file must trigger re-approval so the Safe approves the Router.

    A ``v4`` stamp was written before the Safe's PositionManager
    ``setApprovalForAll(Router, true)`` existed, so even with a DepositWallet
    recorded for the current agent EOA the round must re-enter SET_APPROVAL.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_context.agent_address = "0xAGENT"
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        with open(Path(tmpdir) / "polymarket.json", "w") as f:
            json.dump({"allowances_set": True, "clob_version": "v4"}, f)
        _write_dw(tmpdir, _CURRENT_DW_RECORD)

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


def _drive(gen) -> Any:  # type: ignore[no-untyped-def]
    """Drive a generator to completion and return its value."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _end_block_event(tmpdir: str) -> Enum:
    """Run the check-benchmarking round on ``tmpdir`` and return its event."""
    context = MagicMock()
    context.params.is_running_on_polymarket = True
    context.params.store_path = tmpdir
    context.agent_address = "0xAGENT"
    round_instance = CheckBenchmarkingModeRound(
        synchronized_data=MagicMock(spec=SynchronizedData), context=context
    )
    result = round_instance.end_block()
    assert result is not None
    return result[1]


def _safe_multisend_calls() -> List[Tuple[str, str]]:
    """Build the Safe approval multisend and return ``(to, calldata hex)`` pairs."""
    from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (  # noqa: WPS433
        PolymarketSetApprovalBehaviour,
    )

    behaviour = object.__new__(PolymarketSetApprovalBehaviour)
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""
    context = MagicMock()
    context.params = SimpleNamespace(**docs_addresses())
    behaviour.__dict__["_context"] = context

    def _ok():  # type: ignore[no-untyped-def]
        yield
        return True

    behaviour._build_multisend_data = _ok  # type: ignore[method-assign]
    behaviour._build_multisend_safe_tx_hash = _ok  # type: ignore[method-assign]
    with patch.object(
        type(behaviour), "tx_hex", new_callable=PropertyMock
    ) as mock_tx_hex:
        mock_tx_hex.return_value = "0xsafetx"
        _drive(behaviour._prepare_approval_tx())
    return [(b.to, bytes(b.data).hex()) for b in behaviour.multisend_batches]


def _post_check(tmpdir: str, all_approvals_set: bool) -> bool:
    """Run the post-approval check against a connection reply; return the vote."""
    from packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval import (  # noqa: WPS433
        PolymarketPostSetApprovalBehaviour,
    )

    behaviour = object.__new__(PolymarketPostSetApprovalBehaviour)
    context = MagicMock()
    context.agent_address = "0xAGENT"
    context.params.store_path = Path(tmpdir)
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    behaviour.__dict__["_context"] = context
    response = MagicMock()
    response.error = None
    response.payload = json.dumps({"all_approvals_set": all_approvals_set})

    def _reply(message, dialogue):  # type: ignore[no-untyped-def]
        yield
        return response

    behaviour.do_connection_request = _reply  # type: ignore[method-assign, assignment]
    _drive(behaviour._check_approval())
    return behaviour.payload.vote


def test_upgraded_install_gets_safe_router_approval_once() -> None:
    """An upgraded install enters the approval round once, then skips it.

    The install carries the pre-upgrade ``v4`` allowances stamp with every
    existing Safe approval set and a DepositWallet recorded for the agent EOA.
    After the upgrade the round is entered, the Safe multisend sends the
    PositionManager ``setApprovalForAll(Router, true)``, and once the check
    confirms it on chain the next period skips the approval round.
    """
    router_call = (
        POSITION_MANAGER,
        "a22cb465" + "00" * 12 + ROUTER[2:].lower() + "00" * 31 + "01",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(Path(tmpdir) / "polymarket.json", "w") as f:
            json.dump({"allowances_set": True, "clob_version": "v4"}, f)
        _write_dw(tmpdir, _CURRENT_DW_RECORD)

        # First period after the upgrade: the approval round is entered.
        assert _end_block_event(tmpdir) == Event.SET_APPROVAL
        calls = _safe_multisend_calls()
        assert calls.count(router_call) == 1

        # The Router approval is not on chain yet: the round is entered again.
        assert _post_check(tmpdir, all_approvals_set=False) is False
        assert _end_block_event(tmpdir) == Event.SET_APPROVAL

        # Once on chain, the check passes and the next period skips the round.
        assert _post_check(tmpdir, all_approvals_set=True) is True
        with open(Path(tmpdir) / "polymarket.json") as f:
            stamp = json.load(f)
        assert stamp == {"allowances_set": True, "clob_version": "v5"}
        assert _end_block_event(tmpdir) == Event.BENCHMARKING_DISABLED
        assert _end_block_event(tmpdir) == Event.BENCHMARKING_DISABLED


def _provision_dw(tmpdir: str, mined: bool) -> List[List[Dict[str, Any]]]:
    """Run the setup behaviour's DepositWallet provisioning against a relayer.

    :param tmpdir: the store directory.
    :param mined: whether the relayed approvals batch mines.
    :return: the transactions of every relayed approvals batch.
    """
    from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (  # noqa: WPS433
        PolymarketSetApprovalBehaviour,
    )

    behaviour = object.__new__(PolymarketSetApprovalBehaviour)
    context = MagicMock()
    context.agent_address = "0xAGENT"
    context.params = SimpleNamespace(
        store_path=Path(tmpdir), mech_chain_id="polygon", **docs_addresses()
    )
    behaviour.__dict__["_context"] = context
    batches: List[Dict[str, Any]] = []

    def _send(request_type: RequestType, params: dict) -> Generator[None, None, Any]:
        yield
        if request_type == RequestType.EXEC_WALLET_BATCH:
            batches.append(params)
            return {"transaction_id": "tx"}
        if request_type == RequestType.RELAYER_TX:
            return {"terminal": True, "ok": mined}
        return None

    def _owner(dw_address: str) -> Generator[None, None, str]:
        yield
        return "0xAGENT"

    behaviour._send_polymarket_request = _send  # type: ignore[method-assign, assignment]
    behaviour._verify_dw_owner = _owner  # type: ignore[method-assign, assignment]
    behaviour.sleep = lambda seconds: (yield)  # type: ignore[method-assign]
    _drive(behaviour._provision_deposit_wallet())
    return [batch["transactions"] for batch in batches]


def test_unmined_dw_upgrade_reenters_setup_although_safe_check_passes() -> None:
    """A pre-V2 DW whose upgrade batch is not mined keeps re-entering setup.

    The install carries a pre-V2 DepositWallet record and a current Safe
    allowances file. In the approval pass the DW upgrade batch is relayed but
    not mined while the Safe check passes; the next period must still enter
    SET_APPROVAL. Once the batch mines, the period after skips the round.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        _current_allowances(tmpdir)
        _write_dw(
            tmpdir,
            {"dw_address": "0xDW", "dw_owner": "0xagent", "approvals_done": True},
        )

        relayed = _provision_dw(tmpdir, mined=False)
        assert [sorted(decode_dw_calls(txs)) for txs in relayed] == [
            sorted(expected_calls(DW_V2_APPROVALS, docs_addresses()))
        ]
        assert _post_check(tmpdir, all_approvals_set=True) is True
        assert _end_block_event(tmpdir) == Event.SET_APPROVAL

        assert len(_provision_dw(tmpdir, mined=True)) == 1
        assert _post_check(tmpdir, all_approvals_set=True) is True
        assert _end_block_event(tmpdir) == Event.BENCHMARKING_DISABLED


def test_end_block_polymarket_stale_v3_allowances_file_reapproves() -> None:
    """A v3 file must trigger re-approval after the v4 collateral-adapter swap.

    Bumping ``POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION`` to ``v4`` invalidates
    every Safe's prior ``allowances_set: true`` stamped under v3 (the
    original ``CtfCollateralAdapter`` / ``NegRiskCtfCollateralAdapter``
    addresses). Without that bump, the round short-circuits to
    ``BENCHMARKING_DISABLED`` and the agent never grants
    ``setApprovalForAll`` to the new adapter addresses — so the first
    ``redeemPositions`` call against them reverts.
    """
    mock_context = MagicMock()
    mock_context.params.is_running_on_polymarket = True
    mock_synced_data = MagicMock(spec=SynchronizedData)

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_context.params.store_path = tmpdir
        allowances_path = Path(tmpdir) / "polymarket.json"
        with open(allowances_path, "w") as f:
            json.dump({"allowances_set": True, "clob_version": "v3"}, f)

        round_instance = CheckBenchmarkingModeRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        result = round_instance.end_block()

    assert result is not None
    _, event = result
    assert event == Event.SET_APPROVAL


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
