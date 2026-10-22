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

"""Tests for the DepositWallet provisioning in PolymarketSetApprovalBehaviour."""

import json
from unittest.mock import MagicMock

import pytest

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (
    PolymarketSetApprovalBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
    DW_APPROVALS_VERSION,
)

DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
PUSD, CTF, EXCHANGE, NEG_RISK_EXCHANGE, NEG_RISK_ADAPTER, EXCHANGE_V3, PM = (
    "0x" + byte * 20 for byte in ("c0", "cf", "e1", "e2", "da", "e3", "a0")
)
APPROVE, SET_APPROVAL_FOR_ALL, MAX_UINT256 = "095ea7b3", "a22cb465", 2**256 - 1
V2_CALLS = [
    (PUSD, APPROVE, EXCHANGE_V3, MAX_UINT256),
    (PM, SET_APPROVAL_FOR_ALL, EXCHANGE_V3, 1),
]
FULL_CALLS = [
    (PUSD, APPROVE, EXCHANGE, MAX_UINT256),
    (PUSD, APPROVE, NEG_RISK_EXCHANGE, MAX_UINT256),
    (PUSD, APPROVE, NEG_RISK_ADAPTER, MAX_UINT256),
    (CTF, SET_APPROVAL_FOR_ALL, EXCHANGE, 1),
    (CTF, SET_APPROVAL_FOR_ALL, NEG_RISK_EXCHANGE, 1),
    (CTF, SET_APPROVAL_FOR_ALL, NEG_RISK_ADAPTER, 1),
] + V2_CALLS


def _make_behaviour(tmp_path):  # type: ignore[no-untyped-def]
    """Return a PolymarketSetApprovalBehaviour with mocked context."""
    behaviour = object.__new__(PolymarketSetApprovalBehaviour)
    context = MagicMock()
    context.agent_address = "agent"
    context.params.store_path = tmp_path
    context.params.mech_chain_id = "polygon"
    context.params.polymarket_collateral_address = PUSD
    context.params.polymarket_ctf_address = CTF
    context.params.polymarket_ctf_exchange_address = EXCHANGE
    context.params.polymarket_neg_risk_ctf_exchange_address = NEG_RISK_EXCHANGE
    context.params.polymarket_neg_risk_adapter_address = NEG_RISK_ADAPTER
    context.params.polymarket_exchange_v3_address = EXCHANGE_V3
    context.params.polymarket_position_manager_address = PM
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    behaviour.__dict__["_context"] = context
    return behaviour


def _run(gen):  # type: ignore[no-untyped-def]
    """Drive a generator to completion, returning its value."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _persist_record(tmp_path, approvals_done=False, **extra):  # type: ignore[no-untyped-def]
    """Write a deposit_wallet.json record (as _resolve_or_deploy_dw does)."""
    (tmp_path / DEPOSIT_WALLET_STORE).write_text(
        json.dumps(
            {
                "dw_address": DW,
                "dw_owner": "agent",
                "approvals_done": approvals_done,
                **extra,
            }
        )
    )


def _decode(call):  # type: ignore[no-untyped-def]
    """Decode an approve / setApprovalForAll call to (target, selector, arg, uint)."""
    data = call["data"][2:]
    assert call["value"] == "0" and len(data) == 136 and data[8:32] == "0" * 24
    return call["to"], data[:8], "0x" + data[32:72], int(data[72:], 16)


def _resp(body):  # type: ignore[no-untyped-def]
    """A connection response object carrying a JSON payload."""
    r = MagicMock()
    r.error = None
    r.payload = json.dumps(body)
    return r


class TestSendPolymarketRequest:
    """The connection-request helper."""

    def test_success(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A good response is parsed and returned."""
        b = _make_behaviour(tmp_path)
        b.do_connection_request = lambda m, d: ((yield) or _resp({"dw_address": DW}))  # type: ignore[method-assign]
        out = _run(b._send_polymarket_request(RequestType.DEPLOY_DW, {}))
        assert out == {"dw_address": DW}

    def test_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An error response yields None."""
        b = _make_behaviour(tmp_path)
        err = MagicMock()
        err.error = "boom"
        b.do_connection_request = lambda m, d: ((yield) or err)  # type: ignore[method-assign]
        out = _run(b._send_polymarket_request(RequestType.DEPLOY_DW, {}))
        assert out is None


class TestExtractErrorMessage:
    """The connection error-payload decoder."""

    def test_none_payload(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A missing payload yields a generic fallback."""
        b = _make_behaviour(tmp_path)
        assert b._extract_error_message(None) == "unspecified error"

    def test_non_json_payload(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A non-JSON payload is returned verbatim."""
        b = _make_behaviour(tmp_path)
        assert b._extract_error_message("boom plain") == "boom plain"

    def test_error_dict_payload(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An error dict surfaces its ``error`` field."""
        b = _make_behaviour(tmp_path)
        assert b._extract_error_message(json.dumps({"error": "bad"})) == "bad"

    def test_dict_without_error_key(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A dict with no ``error`` key falls back to the raw payload."""
        b = _make_behaviour(tmp_path)
        payload = json.dumps({"ok": 1})
        assert b._extract_error_message(payload) == payload


class TestWriteDepositWalletFile:
    """The DW state persistence helper."""

    def test_writes_file(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A confirmed record carries the DW, owner, flag and approvals version."""
        b = _make_behaviour(tmp_path)
        assert b._write_deposit_wallet_file(DW, "agent", approvals_done=True)
        data = json.loads((tmp_path / DEPOSIT_WALLET_STORE).read_text())
        assert data == {
            "dw_address": DW,
            "dw_owner": "agent",
            "approvals_done": True,
            "approvals_version": DW_APPROVALS_VERSION,
        }

    def test_writes_pending_approvals(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Identity-only writes record approvals_done=False and no version."""
        b = _make_behaviour(tmp_path)
        assert b._write_deposit_wallet_file(DW, "agent", approvals_done=False)
        data = json.loads((tmp_path / DEPOSIT_WALLET_STORE).read_text())
        assert data == {"dw_address": DW, "dw_owner": "agent", "approvals_done": False}

    def test_oserror_is_logged(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An OSError while writing is logged, not raised, and returns False."""
        b = _make_behaviour(tmp_path)
        store = MagicMock()
        store.__truediv__ = lambda self, other: "/nonexistent/dir/x"
        b.context.params.store_path = store
        assert b._write_deposit_wallet_file(DW, "agent", approvals_done=True) is False
        b.context.logger.error.assert_called()


class TestInvalidateDepositWalletFile:
    """The DW cache-invalidation helper."""

    def test_removes_existing_file(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An existing store file is deleted so setup re-deploys."""
        b = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text("{}")
        b._invalidate_deposit_wallet_file()
        assert not (tmp_path / DEPOSIT_WALLET_STORE).exists()

    def test_absent_file_is_noop(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Invalidating when no file exists is a silent no-op."""
        b = _make_behaviour(tmp_path)
        b._invalidate_deposit_wallet_file()
        b.context.logger.error.assert_not_called()

    def test_oserror_is_logged(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An OSError during unlink is logged, not raised."""
        b = _make_behaviour(tmp_path)
        path = MagicMock()
        path.unlink.side_effect = OSError("boom")
        store = MagicMock()
        store.__truediv__ = lambda self, other: path
        b.context.params.store_path = store
        b._invalidate_deposit_wallet_file()
        b.context.logger.error.assert_called()


class TestVerifyDwOwner:
    """The on-chain owner read used for the rotation / stale-state check."""

    def test_owner_matches(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A readable owner is returned to the caller."""
        b = _make_behaviour(tmp_path)
        msg = MagicMock()
        msg.performative = ContractApiMessage.Performative.STATE
        msg.state.body = {"owner": "agent"}
        b.get_contract_api_response = lambda **kw: ((yield) or msg)  # type: ignore[method-assign]
        assert _run(b._verify_dw_owner(DW)) == "agent"

    def test_owner_mismatch_returns_owner(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A non-matching owner is returned so the caller can act on it."""
        b = _make_behaviour(tmp_path)
        msg = MagicMock()
        msg.performative = ContractApiMessage.Performative.STATE
        msg.state.body = {"owner": "0xOTHER"}
        b.get_contract_api_response = lambda **kw: ((yield) or msg)  # type: ignore[method-assign]
        assert _run(b._verify_dw_owner(DW)) == "0xOTHER"

    def test_unreadable_owner_returns_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A non-STATE response is treated as 'still deploying' (None)."""
        b = _make_behaviour(tmp_path)
        msg = MagicMock()
        msg.performative = ContractApiMessage.Performative.ERROR
        b.get_contract_api_response = lambda **kw: ((yield) or msg)  # type: ignore[method-assign]
        assert _run(b._verify_dw_owner(DW)) is None


def _gen_return(value):  # type: ignore[no-untyped-def]
    """A generator that yields once and returns ``value``."""
    yield
    return value


class TestReadDepositWalletFile:
    """The persisted-state reader."""

    def test_reads_existing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A valid store file is parsed."""
        b = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent"})
        )
        assert b._read_deposit_wallet_file()["dw_address"] == DW

    def test_absent_returns_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A missing store file yields None."""
        assert _make_behaviour(tmp_path)._read_deposit_wallet_file() is None

    def test_malformed_returns_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A malformed store file yields None."""
        b = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text("not json")
        assert b._read_deposit_wallet_file() is None


class TestAwaitRelayerTx:
    """The cooperative relayer-tx poll loop."""

    def test_terminal_on_first_poll(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A terminal poll is returned immediately and forwards is_deploy."""
        b = _make_behaviour(tmp_path)
        seen = []

        def _send(rt, p):  # type: ignore[no-untyped-def]
            seen.append(p)
            return _gen_return({"terminal": True, "ok": True, "dw_address": DW})

        b._send_polymarket_request = _send  # type: ignore[method-assign]
        out = _run(b._await_relayer_tx("tx", is_deploy=True))
        assert out["ok"] is True
        assert seen[0] == {"transaction_id": "tx", "is_deploy": True}

    def test_default_is_not_deploy(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The approval-batch path forwards is_deploy=False by default."""
        b = _make_behaviour(tmp_path)
        seen = []

        def _send(rt, p):  # type: ignore[no-untyped-def]
            seen.append(p)
            return _gen_return({"terminal": True, "ok": True})

        b._send_polymarket_request = _send  # type: ignore[method-assign]
        _run(b._await_relayer_tx("tx"))
        assert seen[0] == {"transaction_id": "tx", "is_deploy": False}

    def test_times_out(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A never-terminal poll exhausts the backoff budget and returns None."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"terminal": False}
        )
        b.sleep = lambda s: (yield)  # type: ignore[method-assign]
        assert _run(b._await_relayer_tx("tx")) is None


class TestResolveOrDeployDw:
    """DW resolution: persisted state vs deploy + receipt discovery."""

    def test_persisted_owner_match(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A persisted DW with matching owner is reused without deploying."""
        b = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent"})
        )
        sent = []
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            sent.append(rt)  # type: ignore[func-returns-value]
        )
        assert _run(b._resolve_or_deploy_dw()) == DW
        assert sent == []  # no relayer call

    def test_persisted_owner_mismatch_redeploys(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A persisted DW owned by a different EOA triggers a fresh deploy."""
        b = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "0xOTHER"})
        )
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"dw_address": DW, "deployed": True, "owner": "agent"}
        )
        assert _run(b._resolve_or_deploy_dw()) == DW

    def test_deploy_already_registered(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An already-registered DW is returned and persisted."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"dw_address": DW, "deployed": True, "owner": "agent"}
        )
        assert _run(b._resolve_or_deploy_dw()) == DW
        assert (tmp_path / DEPOSIT_WALLET_STORE).exists()

    def test_deploy_then_discover_from_receipt(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A fresh deploy is awaited and the DW read from the receipt."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"transaction_id": "tx"}
        )
        b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return(  # type: ignore[method-assign]
            {"ok": True, "dw_address": DW}
        )
        assert _run(b._resolve_or_deploy_dw()) == DW
        assert (tmp_path / DEPOSIT_WALLET_STORE).exists()

    def test_deploy_request_none(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A failed deploy request resolves to None."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(None)  # type: ignore[method-assign]
        assert _run(b._resolve_or_deploy_dw()) is None

    def test_deploy_no_tx_id(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A deploy response without a tx id resolves to None."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"dw_address": None}
        )
        assert _run(b._resolve_or_deploy_dw()) is None

    def test_deploy_not_mined(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A deploy that never mines resolves to None."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"transaction_id": "tx"}
        )
        b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return(None)  # type: ignore[method-assign]
        assert _run(b._resolve_or_deploy_dw()) is None

    def test_deploy_mined_no_address(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A mined deploy whose receipt yields no DW address warns and re-resolves."""
        b = _make_behaviour(tmp_path)
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"transaction_id": "tx"}
        )
        b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return({"ok": True})  # type: ignore[method-assign]
        assert _run(b._resolve_or_deploy_dw()) is None
        b.context.logger.warning.assert_called()


class TestProvisionDepositWallet:
    """End-to-end DW provisioning."""

    def test_unresolvable_dw_returns(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """When the DW cannot be resolved, no approvals are attempted."""
        b = _make_behaviour(tmp_path)
        b._resolve_or_deploy_dw = lambda: _gen_return(None)  # type: ignore[method-assign]
        sent = []
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            sent.append(rt)  # type: ignore[func-returns-value]
        )
        _run(b._provision_deposit_wallet())
        assert sent == []

    def test_full_provision_mined(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A resolved, owner-matched DW sets approvals, waits, and persists."""
        b = _make_behaviour(tmp_path)
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: _gen_return("agent")  # type: ignore[method-assign]
        sent = []

        def _send(rt, p):  # type: ignore[no-untyped-def]
            yield
            sent.append(rt)
            return {"transaction_id": "tx"}

        b._send_polymarket_request = _send  # type: ignore[method-assign]
        b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return({"ok": True})  # type: ignore[method-assign]
        _run(b._provision_deposit_wallet())
        assert RequestType.EXEC_WALLET_BATCH in sent
        # approvals_done is persisted only after the mined confirmation.
        data = json.loads((tmp_path / DEPOSIT_WALLET_STORE).read_text())
        assert data["approvals_done"] is True

    def test_owner_mismatch_invalidates_and_skips(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An on-chain owner mismatch invalidates the cache and skips approvals."""
        b = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text("{}")
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: _gen_return("0xOTHER")  # type: ignore[method-assign]
        sent = []
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            sent.append(rt)  # type: ignore[func-returns-value]
        )
        _run(b._provision_deposit_wallet())
        assert sent == []  # no EXEC_WALLET_BATCH attempted
        assert not (tmp_path / DEPOSIT_WALLET_STORE).exists()
        b.context.logger.warning.assert_called()

    def test_approvals_request_failed(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A failed approvals request is logged, not fatal."""
        b = _make_behaviour(tmp_path)
        _persist_record(tmp_path)
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: (yield)  # type: ignore[method-assign]
        b._send_polymarket_request = lambda rt, p: _gen_return(None)  # type: ignore[method-assign]
        _run(b._provision_deposit_wallet())
        b.context.logger.warning.assert_called()

    def test_approvals_not_mined(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Unmined approvals leave a pre-V2 record as it was, so the gate re-enters."""
        b = _make_behaviour(tmp_path)
        _persist_record(tmp_path, approvals_done=True)
        record = (tmp_path / DEPOSIT_WALLET_STORE).read_text()
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: (yield)  # type: ignore[method-assign]
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"transaction_id": "tx"}
        )
        b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return(None)  # type: ignore[method-assign]
        _run(b._provision_deposit_wallet())
        b.context.logger.warning.assert_called()
        assert (tmp_path / DEPOSIT_WALLET_STORE).read_text() == record

    def test_owner_unverifiable_no_record_defers(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Owner unreadable AND no prior record → defer, no approvals attempted."""
        b = _make_behaviour(tmp_path)
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: (yield)  # type: ignore[method-assign]
        sent = []
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            sent.append(rt)  # type: ignore[func-returns-value]
        )
        _run(b._provision_deposit_wallet())
        assert sent == []
        b.context.logger.warning.assert_called()

    def test_approvals_already_recorded_skips(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A recorded approvals_done=True skips the (idempotent) approvals batch."""
        b = _make_behaviour(tmp_path)
        _persist_record(
            tmp_path, approvals_done=True, approvals_version=DW_APPROVALS_VERSION
        )
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: _gen_return("agent")  # type: ignore[method-assign]
        sent = []
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            sent.append(rt)  # type: ignore[func-returns-value]
        )
        _run(b._provision_deposit_wallet())
        assert sent == []  # EXEC_WALLET_BATCH skipped
        b.context.logger.info.assert_called()

    @pytest.mark.parametrize(
        "record, expected",
        [
            ({"approvals_done": True}, [V2_CALLS]),
            ({"approvals_done": True, "approvals_version": None}, [V2_CALLS]),
            ({"approvals_done": True, "approvals_version": 1}, [V2_CALLS]),
            ({"approvals_done": True, "approvals_version": 3}, [V2_CALLS]),
            ({"approvals_done": True, "approvals_version": "2"}, [V2_CALLS]),
            ({"approvals_done": True, "approvals_version": DW_APPROVALS_VERSION}, []),
            ({"approvals_version": DW_APPROVALS_VERSION}, [FULL_CALLS]),
        ],
        ids=["pre_v2", "none", "stale", "newer", "string", "current", "pending"],
    )
    def test_upgraded_install_gets_v2_dw_approvals_once(  # type: ignore[no-untyped-def]
        self, tmp_path, record, expected
    ) -> None:
        """A record gets only the approvals it lacks, then nothing on the next run."""
        _persist_record(tmp_path, **record)
        batches = []
        for _ in range(2):
            b = _make_behaviour(tmp_path)
            b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
            b._verify_dw_owner = lambda dw: _gen_return("agent")  # type: ignore[method-assign]
            b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
                batches.append(p) or {"transaction_id": "tx"}  # type: ignore[func-returns-value]
            )
            b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return({"ok": True})  # type: ignore[method-assign]
            _run(b._provision_deposit_wallet())
        assert all(p["dw_address"] == DW for p in batches)
        assert [sorted(map(_decode, p["transactions"])) for p in batches] == [
            sorted(calls) for calls in expected
        ]
        assert json.loads((tmp_path / DEPOSIT_WALLET_STORE).read_text()) == {
            "dw_address": DW,
            "dw_owner": "agent",
            "approvals_done": True,
            "approvals_version": DW_APPROVALS_VERSION,
        }

    @pytest.mark.parametrize("written", [True, False])
    def test_mined_logged_only_after_record_written(self, tmp_path, written) -> None:  # type: ignore[no-untyped-def]
        """A mined batch is logged as mined only when its record was written."""
        b = _make_behaviour(tmp_path)
        _persist_record(tmp_path)
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: _gen_return("agent")  # type: ignore[method-assign]
        b._send_polymarket_request = lambda rt, p: _gen_return(  # type: ignore[method-assign]
            {"transaction_id": "tx"}
        )
        b._await_relayer_tx = lambda tx, is_deploy=False: _gen_return({"ok": True})  # type: ignore[method-assign]
        b._write_deposit_wallet_file = MagicMock(return_value=written)  # type: ignore[method-assign]
        _run(b._provision_deposit_wallet())
        info = str(b.context.logger.info.call_args_list)
        warning = str(b.context.logger.warning.call_args_list)
        assert (f"DepositWallet {DW} trading approvals mined." in info) is written
        assert (f"DepositWallet {DW} approvals tx tx mined" in warning) is not written
        assert ("will be re-sent on the next pass" in warning) is not written

    def test_approvals_no_tx_id_retries(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Approvals response without a transaction_id is not marked done."""
        b = _make_behaviour(tmp_path)
        # The real _resolve_or_deploy_dw persists the DW record (dw_owner from
        # the deploy receipt); write it so the owner-unverifiable defer and the
        # already-approved skip are both bypassed and the approvals path runs.
        _persist_record(tmp_path, approvals_done=False)
        b._resolve_or_deploy_dw = lambda: _gen_return(DW)  # type: ignore[method-assign]
        b._verify_dw_owner = lambda dw: (yield)  # type: ignore[method-assign]
        b._send_polymarket_request = lambda rt, p: _gen_return({})  # type: ignore[method-assign]
        _run(b._provision_deposit_wallet())
        b.context.logger.warning.assert_called()
        # An unconfirmed batch must not advance approvals_done.
        data = json.loads((tmp_path / DEPOSIT_WALLET_STORE).read_text())
        assert data["approvals_done"] is False


class TestBuildDwTradingApprovals:
    """Behaviour-side construction of the 8 DW trading-approval calls."""

    def test_builds_eight_calls(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """4 pUSD approves, 3 CTF and 1 PositionManager setApprovalForAll."""
        b = _make_behaviour(tmp_path)
        p = b.context.params
        p.polymarket_collateral_address = "0x" + "c0" * 20
        p.polymarket_ctf_address = "0x" + "cf" * 20
        p.polymarket_ctf_exchange_address = "0x" + "e1" * 20
        p.polymarket_neg_risk_ctf_exchange_address = "0x" + "e2" * 20
        p.polymarket_neg_risk_adapter_address = "0x" + "da" * 20
        txs = b._build_dw_trading_approvals()
        assert len(txs) == 8
        collateral = [t for t in txs if t["to"] == p.polymarket_collateral_address]
        ctf = [t for t in txs if t["to"] == p.polymarket_ctf_address]
        assert len(collateral) == 4
        assert len(ctf) == 3
        assert all(t["data"].startswith("0x095ea7b3") for t in collateral)
        assert all(t["data"].startswith("0xa22cb465") for t in ctf)
        assert all(t["value"] == "0" for t in txs)

    def test_dw_batch_includes_v2_exchange_approvals(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The batch approves both exchanges and the NegRiskAdapter, then V2."""
        txs = _make_behaviour(tmp_path)._build_dw_trading_approvals()
        assert list(map(_decode, txs)) == FULL_CALLS

    @pytest.mark.parametrize(
        "builder", ["_build_dw_trading_approvals", "_build_dw_v2_trading_approvals"]
    )
    def test_exchange_v3_approval_is_max_uint256(self, tmp_path, builder) -> None:  # type: ignore[no-untyped-def]
        """Every pUSD approval to ExchangeV3 is exactly MaxUint256, never bounded."""
        calls = map(_decode, getattr(_make_behaviour(tmp_path), builder)())
        assert [c[3] for c in calls if c[1:3] == (APPROVE, EXCHANGE_V3)] == [
            MAX_UINT256
        ]
