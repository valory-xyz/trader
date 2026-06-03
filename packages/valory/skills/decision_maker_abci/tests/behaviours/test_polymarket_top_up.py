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

"""Tests for PolymarketTopUpBehaviour."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_top_up import (
    PolymarketTopUpBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.base import Event

COLLAT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


def _make_behaviour(tmp_path):  # type: ignore[no-untyped-def]
    """Return a PolymarketTopUpBehaviour with mocked context."""
    behaviour = object.__new__(PolymarketTopUpBehaviour)
    behaviour.dw_address = None
    behaviour.multisend_batches = []
    context = MagicMock()
    context.agent_address = "agent"
    context.params.store_path = tmp_path
    context.params.polymarket_collateral_address = COLLAT
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    behaviour.__dict__["_context"] = context
    return behaviour


def _ok():  # type: ignore[no-untyped-def]
    """A generator that yields once and returns True."""
    yield
    return True


def _fail():  # type: ignore[no-untyped-def]
    """A generator that yields once and returns False."""
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


def _synced(dw, bet_amount):  # type: ignore[no-untyped-def]
    """A synchronized_data mock."""
    m = MagicMock()
    m.deposit_wallet_address = dw
    m.bet_amount = bet_amount
    return m


def _resp(body):  # type: ignore[no-untyped-def]
    """A connection response object carrying a JSON payload."""
    r = MagicMock()
    r.error = None
    r.payload = json.dumps(body)
    return r


def _set_balance(behaviour, balance):  # type: ignore[no-untyped-def]
    """Stub the Safe pUSD balance check to a fixed value."""
    behaviour.token_balance = balance
    behaviour.wait_for_condition_with_sleep = lambda cond, **kw: _ok()  # type: ignore[method-assign]


class TestPolymarketTopUpBehaviour:
    """Tests for PolymarketTopUpBehaviour."""

    def test_prepare_tx_with_known_dw(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A known DW + positive buy amount + good multisend → PREPARE_TX."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(DW, 5_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value
        assert payload.tx_hash == "0xsafehash"
        assert payload.dw_address == DW

    def test_insufficient_safe_balance(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A Safe pUSD balance below the buy amount → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        _set_balance(behaviour, 1_000_000)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 5_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_non_positive_buy_amount_insufficient(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A non-positive buy amount → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 0),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_resolves_dw_via_persisted(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """With no synced DW, the persisted store file resolves it → PREPARE_TX."""
        behaviour = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent", "approvals_done": True})
        )
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(None, 5_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value

    def test_unresolvable_dw_insufficient(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """No DW recorded (synced empty, no persisted file) → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(None, 5_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_multisend_build_failure_insufficient(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A multisend build failure → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _fail()  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 5_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value
