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

"""Tests for PolymarketWithdrawTopUpBehaviour."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from eth_abi import encode as abi_encode
from eth_utils import to_checksum_address  # type: ignore[import-not-found]
from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.connections.polymarket_client.tests import test_connection as pm
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_withdraw import (
    PolymarketWithdrawBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_withdraw_top_up import (
    CTF_DECIMAL_FACTOR,
    PolymarketWithdrawTopUpBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.base import Event

CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
SAFE = "0x1111111111111111111111111111111111111111"


def _make_behaviour(tmp_path, with_dw=True):  # type: ignore[no-untyped-def]
    """Return a PolymarketWithdrawTopUpBehaviour with mocked context.

    When ``with_dw`` is set, a persisted ``deposit_wallet.json`` (owner-matched)
    is written so ``_resolve_deposit_wallet`` resolves the DW from the store.

    :param tmp_path: the temporary store directory.
    :param with_dw: whether to persist a ``deposit_wallet.json`` in the store.
    :return: the constructed behaviour.
    """
    behaviour = object.__new__(PolymarketWithdrawTopUpBehaviour)
    behaviour.multisend_batches = []
    context = MagicMock()
    context.agent_address = "agent"
    context.params.store_path = tmp_path
    context.params.polymarket_ctf_address = CTF
    behaviour.__dict__["_context"] = context
    if with_dw:
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent", "approvals_done": True})
        )
    return behaviour


def _ok():  # type: ignore[no-untyped-def]
    yield
    return True


def _fail():  # type: ignore[no-untyped-def]
    yield
    return False


def _drive(behaviour):  # type: ignore[no-untyped-def]
    """Drive async_act to completion and return the emitted payload."""
    captured = {}

    def capture_finish(payload):  # type: ignore[no-untyped-def]
        captured["payload"] = payload
        yield

    behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]
    gen = behaviour.async_act()
    try:
        while True:
            next(gen)
    except StopIteration:
        pass
    return captured["payload"]


def _synced(dw):  # type: ignore[no-untyped-def]
    m = MagicMock()
    m.deposit_wallet_address = dw
    m.safe_contract_address = SAFE
    return m


def _install_send(behaviour, *, deploy_dw, positions):  # type: ignore[no-untyped-def]
    """Install a _send_polymarket_request stub keyed on request type."""

    def _send(request_type, params):  # type: ignore[no-untyped-def]
        yield
        if request_type == RequestType.FETCH_ALL_POSITIONS:
            return positions
        return deploy_dw

    behaviour._send_polymarket_request = _send  # type: ignore[method-assign]


class TestPolymarketWithdrawTopUpBehaviour:
    """Tests for PolymarketWithdrawTopUpBehaviour."""

    def test_prepare_tx_with_sellable(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Sellable positions build a CTF batch-transfer → PREPARE_TX."""
        behaviour = _make_behaviour(tmp_path)
        _install_send(
            behaviour,
            deploy_dw={"dw_address": DW},
            positions=[{"asset": "123", "size": 2.0}],
        )
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        with (
            patch.object(
                PolymarketWithdrawTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(DW),
            ),
            patch.object(
                PolymarketWithdrawTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value
        assert payload.tx_hash == "0xsafehash"

    def test_no_sellable_emits_withdrawal_done(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """No sellable positions → WITHDRAWAL_DONE (skip straight to idle)."""
        behaviour = _make_behaviour(tmp_path)
        _install_send(behaviour, deploy_dw={"dw_address": DW}, positions=[])
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.WITHDRAWAL_DONE.value

    def test_dust_positions_skipped(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Dust / asset-less / non-numeric positions are filtered out."""
        behaviour = _make_behaviour(tmp_path)
        _install_send(
            behaviour,
            deploy_dw={"dw_address": DW},
            positions=[
                {"asset": "1", "size": 0.0},  # dust
                {"asset": None, "size": 5.0},  # no asset
                {"asset": "2", "size": "bad"},  # non-numeric
            ],
        )
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.WITHDRAWAL_DONE.value

    def test_fetch_error_emits_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A positions fetch error (dict response) → NONE."""
        behaviour = _make_behaviour(tmp_path)
        _install_send(
            behaviour, deploy_dw={"dw_address": DW}, positions={"error": "boom"}
        )
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.NONE.value

    def test_unresolvable_dw_emits_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An unresolvable DW → NONE."""
        behaviour = _make_behaviour(tmp_path, with_dw=False)
        _install_send(behaviour, deploy_dw={"dw_address": None}, positions=[])
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(None),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.NONE.value

    def test_multisend_failure_emits_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A multisend build failure → NONE."""
        behaviour = _make_behaviour(tmp_path)
        _install_send(
            behaviour,
            deploy_dw={"dw_address": DW},
            positions=[{"asset": "123", "size": 2.0}],
        )
        behaviour._build_multisend_data = lambda: _fail()  # type: ignore[method-assign]
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.NONE.value

    def test_amount_scaling(self) -> None:
        """CTF_DECIMAL_FACTOR scales human shares to 6-decimal base units."""
        assert CTF_DECIMAL_FACTOR == 10**6


def _top_up(tmp_path, conn):  # type: ignore[no-untyped-def]
    """Run the withdrawal top-up of the Safe against ``conn`` and apply its batches."""
    behaviour = _make_behaviour(tmp_path)
    behaviour.context.params.configure_mock(**pm.V2_PARAMS)
    behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
    behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
    pm._wire(behaviour, conn)
    with patch.multiple(
        PolymarketWithdrawTopUpBehaviour,
        synchronized_data=PropertyMock(return_value=_synced(DW)),
        tx_hex=PropertyMock(return_value="0xsafehash"),
    ):
        behaviour.synchronized_data.safe_contract_address = pm.V2_SAFE
        assert _drive(behaviour).event == Event.PREPARE_TX.value
    for batch in behaviour.multisend_batches:
        assert batch.value == 0
        pm._apply_transfer(conn.balances, pm.V2_SAFE, batch.to, batch.data)
    return behaviour.multisend_batches


@pytest.mark.parametrize("v1_rows", [(pm.V1_OPEN, pm.V1_00), ()])
def test_v2_position_detected_from_row(tmp_path, v1_rows) -> None:  # type: ignore[no-untyped-def]
    """Each Safe row moves on its own ledger with no bet record; V1 rows that look like V2 stay V1."""
    rows, dw = (pm.V2_OPEN, *v1_rows), to_checksum_address(DW)
    v1_ids = [int(row["token_id"]) for row in v1_rows]
    types = ["address", "address", "uint256[]", "uint256[]", "bytes"]
    v1_batch = pm._selector(f"safeBatchTransferFrom({','.join(types)})") + abi_encode(
        types, [pm.V2_SAFE, dw, v1_ids, [5000000] * len(v1_ids), b""]
    )
    with pm._safe_world(*rows) as conn:
        batches = _top_up(tmp_path, conn)
    v1_batches = [bytes(HexBytes(b.data)) for b in batches if b.to == CTF]
    assert v1_batches == ([v1_batch] if v1_rows else [])
    assert pm._held(conn.balances) == pm._ledger(dw, *rows)


def test_v2_position_withdrawal_by_position_id(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """V2 positions move to the DW, sell by position ID, and the unsold return to the Safe."""
    sells = []

    def sell(token_id, amount, **_):  # type: ignore[no-untyped-def]
        sells.append((token_id, amount))
        return {"status": "unmatched", "filled_shares": 0.0}, None

    with pm._safe_world(pm.V2_OPEN, pm.V1_OPEN) as conn:
        _top_up(tmp_path, conn)
        conn.pages[to_checksum_address(DW)] = conn.pages.pop(pm.V2_SAFE)
        withdraw = object.__new__(PolymarketWithdrawBehaviour)
        withdraw.__dict__["_context"] = MagicMock(agent_address="agent")
        withdraw.context.params.store_path = tmp_path
        withdraw.context.params.withdrawal_max_fak_attempts = 1
        withdraw.finish_behaviour = lambda payload: _ok()  # type: ignore[method-assign]
        conn._sell_position = sell
        pm._wire(withdraw, conn)
        list(withdraw.async_act())
    for (dw, _, txs), _ in conn.relayer_proxy.exec_wallet_batch.call_args_list:
        for tx in txs:
            pm._apply_transfer(conn.balances, dw, tx["target"], tx["data"])
    assert sells == [(pm.V2_OPEN["token_id"], 10.0), (pm.V1_OPEN["token_id"], 5.0)]
    assert pm._held(conn.balances) == pm._ledger(pm.V2_SAFE, pm.V2_OPEN, pm.V1_OPEN)
