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

"""Coverage-completion tests for the DepositWallet top-up / sweep behaviours."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_sweep import (
    PolymarketSweepBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_top_up import (
    PolymarketTopUpBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_withdraw_top_up import (
    PolymarketWithdrawTopUpBehaviour,
    SAFE_BATCH_TRANSFER_SELECTOR,
)
from packages.valory.skills.decision_maker_abci.states.base import Event

DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
SAFE = "0x1111111111111111111111111111111111111111"


def _run(gen):  # type: ignore[no-untyped-def]
    """Drive a generator to completion, returning its value."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _bare(cls):  # type: ignore[no-untyped-def]
    """Bare instance with a mocked context."""
    b = object.__new__(cls)
    b.__dict__["_context"] = MagicMock()
    return b


def _check_finish(cls) -> None:  # type: ignore[no-untyped-def]
    """finish_behaviour sends the a2a tx, waits, and marks the behaviour done."""
    b = _bare(cls)
    b.send_a2a_transaction = lambda p: (yield)  # type: ignore[misc]
    b.wait_until_round_end = lambda: (yield)  # type: ignore[misc]
    b.set_done = MagicMock()
    _run(b.finish_behaviour(MagicMock()))
    b.set_done.assert_called_once()


class TestInit:
    """The behaviour constructors run the base initializer."""

    def test_top_up_init(self) -> None:
        """The PolymarketTopUpBehaviour init starts with no DW."""
        with patch.object(DecisionMakerBaseBehaviour, "__init__", return_value=None):
            b = PolymarketTopUpBehaviour(name="t", skill_context=MagicMock())
        assert b.dw_address is None

    def test_sweep_init(self) -> None:
        """The PolymarketSweepBehaviour constructs."""
        with patch.object(DecisionMakerBaseBehaviour, "__init__", return_value=None):
            PolymarketSweepBehaviour(name="t", skill_context=MagicMock())

    def test_withdraw_top_up_init(self) -> None:
        """The PolymarketWithdrawTopUpBehaviour constructs."""
        with patch.object(
            DecisionMakerBaseBehaviour,
            "__init__",
            return_value=None,
        ):
            PolymarketWithdrawTopUpBehaviour(name="t", skill_context=MagicMock())


class TestFinishBehaviour:
    """The shared finish_behaviour consensus block."""

    def test_top_up_finish(self) -> None:
        """Top-up finish_behaviour completes the consensus round."""
        _check_finish(PolymarketTopUpBehaviour)

    def test_sweep_finish(self) -> None:
        """Sweep finish_behaviour completes the consensus round."""
        _check_finish(PolymarketSweepBehaviour)

    def test_withdraw_top_up_finish(self) -> None:
        """Withdraw-top-up finish_behaviour completes the consensus round."""
        _check_finish(PolymarketWithdrawTopUpBehaviour)


class TestSendConnectionRequestErrors:
    """The connection-request helpers return None on error."""

    def test_top_up_send_error(self) -> None:
        """A failed connection request yields None (top-up)."""
        b = _bare(PolymarketTopUpBehaviour)
        b.context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
        b.do_connection_request = lambda m, d: ((yield) or None)  # type: ignore[method-assign]
        assert _run(b._send_polymarket_request(RequestType.SWEEP_DW, {})) is None

    def test_withdraw_send_error(self) -> None:
        """A failed connection request yields None (withdraw top-up)."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        b.context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
        b.do_connection_request = lambda m, d: ((yield) or None)  # type: ignore[method-assign]
        assert (
            _run(b._send_polymarket_request(RequestType.FETCH_ALL_POSITIONS, {}))
            is None
        )


class TestTopUpTxHashFailure:
    """A safe-tx-hash build failure short-circuits to INSUFFICIENT_BALANCE."""

    def test_tx_hash_failure(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The top-up multisend hash failure path sets INSUFFICIENT_BALANCE."""
        b = _bare(PolymarketTopUpBehaviour)
        b.dw_address = None
        b.multisend_batches = []
        b.context.params.store_path = tmp_path
        b.context.params.polymarket_collateral_address = (
            "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
        )

        def _ok():  # type: ignore[no-untyped-def]
            yield
            return True

        def _fail():  # type: ignore[no-untyped-def]
            yield
            return False

        b._send_polymarket_request = lambda rt, p: ((yield) or {"dw_address": DW})  # type: ignore[method-assign]
        b._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        b._build_multisend_safe_tx_hash = lambda: _fail()  # type: ignore[method-assign]
        b.token_balance = 5_000_000
        b.wait_for_condition_with_sleep = lambda cond, **kw: _ok()  # type: ignore[method-assign]
        synced = MagicMock()
        synced.deposit_wallet_address = DW
        synced.bet_amount = 5_000_000
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            _run(b._prepare_top_up())
        assert b.payload.event == Event.INSUFFICIENT_BALANCE.value


class TestWithdrawHelpers:
    """Direct coverage of the withdraw-top-up helpers."""

    def test_build_safe_batch_transfer_data(self) -> None:
        """The CTF safeBatchTransferFrom calldata begins with the selector."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        data = b._build_safe_batch_transfer_data(SAFE, DW, [1, 2], [1000, 2000])
        assert isinstance(data, bytes)
        assert data.startswith(SAFE_BATCH_TRANSFER_SELECTOR)

    def test_resolve_uses_synced_dw(self) -> None:
        """_resolve_deposit_wallet returns the synced DW without a deploy call."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        synced = MagicMock()
        synced.deposit_wallet_address = DW
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            assert b._resolve_deposit_wallet() == DW

    def test_fetch_sellable_error(self) -> None:
        """_fetch_sellable returns None when the connection errors."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        b._send_polymarket_request = lambda rt, p: ((yield) or None)  # type: ignore[method-assign]
        assert _run(b._fetch_sellable()) is None

    def test_send_polymarket_request_success(self) -> None:
        """The real _send_polymarket_request parses a good response."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        b.context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
        resp = MagicMock()
        resp.error = None
        resp.payload = json.dumps({"dw_address": DW})
        b.do_connection_request = lambda m, d: ((yield) or resp)  # type: ignore[method-assign]
        out = _run(b._send_polymarket_request(RequestType.DEPLOY_DW, {}))
        assert out == {"dw_address": DW}

    def test_tx_hash_failure_emits_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A withdrawal-top-up safe-tx-hash build failure emits NONE."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        b.multisend_batches = []
        b.context.params.store_path = tmp_path
        b.context.params.polymarket_ctf_address = (
            "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
        )

        def _ok():  # type: ignore[no-untyped-def]
            yield
            return True

        def _fail():  # type: ignore[no-untyped-def]
            yield
            return False

        def _send(rt, p):  # type: ignore[no-untyped-def]
            yield
            if rt == RequestType.FETCH_ALL_POSITIONS:
                return [{"asset": "1", "size": 2.0}]
            return {"dw_address": DW}

        b._send_polymarket_request = _send  # type: ignore[method-assign]
        b._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        b._build_multisend_safe_tx_hash = lambda: _fail()  # type: ignore[method-assign]
        synced = MagicMock()
        synced.deposit_wallet_address = DW
        synced.safe_contract_address = SAFE
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            _run(b._prepare_withdraw_top_up())
        assert b.payload.event == Event.NONE.value


class TestTopUpResolveNoneResponse:
    """The resolvers return None when no DW is recorded."""

    def test_resolve_none(self) -> None:
        """No synced and no persisted DW → the top-up resolver returns None."""
        b = _bare(PolymarketTopUpBehaviour)
        synced = MagicMock()
        synced.deposit_wallet_address = None
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            assert b._resolve_deposit_wallet() is None

    def test_withdraw_resolve_none(self) -> None:
        """No synced and no persisted DW → the withdraw-top-up resolver returns None."""
        b = _bare(PolymarketWithdrawTopUpBehaviour)
        synced = MagicMock()
        synced.deposit_wallet_address = None
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            assert b._resolve_deposit_wallet() is None


class TestPersistedDwResolve:
    """On restart, the top-up resolvers prefer the persisted DW (no re-deploy)."""

    def _setup(self, cls, tmp_path):  # type: ignore[no-untyped-def]
        b = _bare(cls)
        b.context.params.store_path = tmp_path
        b.context.agent_address = "agent"
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent"})
        )
        return b

    def test_top_up_uses_persisted(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The top-up resolver returns the persisted DW without a deploy call."""
        b = self._setup(PolymarketTopUpBehaviour, tmp_path)
        sent = []
        b._send_polymarket_request = lambda rt, p: ((yield) or sent.append(rt))  # type: ignore[method-assign, func-returns-value]
        synced = MagicMock()
        synced.deposit_wallet_address = None
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            assert b._resolve_deposit_wallet() == DW
        assert sent == []

    def test_withdraw_uses_persisted(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The withdraw-top-up resolver returns the persisted DW (no deploy)."""
        b = self._setup(PolymarketWithdrawTopUpBehaviour, tmp_path)
        sent = []
        b._send_polymarket_request = lambda rt, p: ((yield) or sent.append(rt))  # type: ignore[method-assign, func-returns-value]
        synced = MagicMock()
        synced.deposit_wallet_address = None
        with patch.object(
            PolymarketWithdrawTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=synced,
        ):
            assert b._resolve_deposit_wallet() == DW
        assert sent == []
