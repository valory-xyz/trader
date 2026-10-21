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

"""Tests for the Polymarket Protocol V2 approvals set by the setup round.

Polymarket's contract migration guide says existing CTF approvals do not carry
over to Protocol V2: the DepositWallet must approve ExchangeV3 to spend pUSD and
to operate its PositionManager positions, and the Safe must let the Router
operate its PositionManager positions to claim V2 winnings. The retired CLOB v1
NegRiskAdapter is no longer approved by the DepositWallet, and AutoRedeemer is
never approved.
"""

import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (
    PolymarketSetApprovalBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import MultiSendOperation
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
    DW_APPROVALS_VERSION,
)
from packages.valory.skills.decision_maker_abci.tests.polymarket_approvals import (
    APPROVE,
    AUTO_REDEEMER,
    Call,
    DW_V1_APPROVALS,
    DW_V2_APPROVALS,
    EXCHANGE_V3,
    MAX_UINT256,
    POSITION_MANAGER,
    PUSD,
    SAFE_EXISTING_APPROVALS,
    SAFE_ROUTER_APPROVAL,
    SET_APPROVAL_FOR_ALL,
    addresses_in,
    decode,
    decode_dw_calls,
    distinct_addresses,
    docs_addresses,
    expected_calls,
    random_addresses,
)

DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
AGENT = "agent"
RANDOM_SEED = 20260501
RANDOM_CASES = 250

# Marks a record written without an ``approvals_version`` key.
MISSING = object()

# The documented addresses, and a distinct set that shows params are read.
ADDRESS_SETS = (docs_addresses(), distinct_addresses())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_behaviour(
    addresses: Dict[str, str], store_path: Optional[Path] = None
) -> PolymarketSetApprovalBehaviour:
    """Return a PolymarketSetApprovalBehaviour whose params hold ``addresses``.

    The params are a plain namespace, so reading an undeclared param fails.

    :param addresses: the address params.
    :param store_path: the directory holding the persisted state files.
    :return: the behaviour.
    """
    behaviour = object.__new__(PolymarketSetApprovalBehaviour)
    behaviour.buy_amount = 0
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""
    context = MagicMock()
    context.agent_address = AGENT
    context.params = SimpleNamespace(
        store_path=store_path,
        mech_chain_id="polygon",
        polymarket_builder_program_enabled=False,
        **addresses,
    )
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    behaviour.__dict__["_context"] = context
    return behaviour


def _run(gen: Generator[Any, Any, Any]) -> Any:
    """Drive a generator to completion and return its value.

    :param gen: the generator.
    :return: the generator's return value.
    """
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _gen_return(value: Any) -> Generator[None, None, Any]:
    """Yield once and return ``value``.

    :param value: the value to return.
    :yield: once.
    :return: ``value``.
    """
    yield
    return value


def _decode_multisend(batches: List[Any]) -> List[Call]:
    """Decode the Safe multisend batches.

    :param batches: the multisend batches.
    :return: the decoded calls.
    """
    for batch in batches:
        assert batch.operation == MultiSendOperation.CALL
    return [decode(b.to, b.data, b.value) for b in batches]


def _run_multisend(behaviour: PolymarketSetApprovalBehaviour) -> Any:
    """Run ``_prepare_approval_tx`` with the multisend encoding mocked out.

    :param behaviour: the behaviour.
    :return: the prepared transaction hash.
    """
    behaviour._build_multisend_data = lambda: _gen_return(True)  # type: ignore[method-assign]
    behaviour._build_multisend_safe_tx_hash = lambda: _gen_return(True)  # type: ignore[method-assign]
    with patch.object(
        type(behaviour), "tx_hex", new_callable=PropertyMock
    ) as mock_tx_hex:
        mock_tx_hex.return_value = "0xsafetx"
        return _run(behaviour._prepare_approval_tx())


def _install_relayer(
    behaviour: PolymarketSetApprovalBehaviour,
    sent: List[Tuple[RequestType, dict]],
    mined: bool = True,
) -> None:
    """Replace the connection with a fake relayer that records every request.

    :param behaviour: the behaviour.
    :param sent: list the requests are appended to.
    :param mined: whether relayed batches mine successfully.
    """

    def _send(request_type: RequestType, params: dict) -> Generator[None, None, Any]:
        yield
        sent.append((request_type, params))
        if request_type == RequestType.EXEC_WALLET_BATCH:
            return {"transaction_id": f"tx-{len(sent)}", "dw_address": DW}
        if request_type == RequestType.RELAYER_TX:
            state = "STATE_MINED" if mined else "STATE_FAILED"
            return {"state": state, "terminal": True, "ok": mined}
        return None

    behaviour._send_polymarket_request = _send  # type: ignore[method-assign]
    behaviour._verify_dw_owner = lambda dw: _gen_return(AGENT)  # type: ignore[method-assign, assignment]
    behaviour.sleep = lambda seconds: (yield)  # type: ignore[method-assign]


def _batches(sent: List[Tuple[RequestType, dict]]) -> List[dict]:
    """Return the params of every ``EXEC_WALLET_BATCH`` request sent.

    :param sent: the recorded requests.
    :return: the batch request params.
    """
    return [p for rt, p in sent if rt == RequestType.EXEC_WALLET_BATCH]


def _write_record(
    store: Path, approvals_done: bool = True, approvals_version: Any = MISSING
) -> None:
    """Write a DepositWallet record, by default in the shape used before V2.

    :param store: the store directory.
    :param approvals_done: the recorded approvals flag.
    :param approvals_version: the recorded approvals version, or ``MISSING``
        to leave the key out.
    """
    record: Dict[str, Any] = {
        "dw_address": DW,
        "dw_owner": AGENT,
        "approvals_done": approvals_done,
    }
    if approvals_version is not MISSING:
        record["approvals_version"] = approvals_version
    (store / DEPOSIT_WALLET_STORE).write_text(json.dumps(record))


def _read_record(store: Path) -> Dict[str, Any]:
    """Read the persisted DepositWallet record.

    :param store: the store directory.
    :return: the record.
    """
    return json.loads((store / DEPOSIT_WALLET_STORE).read_text())


def _upgrade_batch(addresses: Dict[str, str], store: Path) -> List[Call]:
    """Relay the upgrade batch for a pre-V2 record and return its decoded calls.

    :param addresses: the address params.
    :param store: the store directory.
    :return: the decoded calls of the single relayed batch.
    """
    _write_record(store, approvals_done=True)
    sent: List[Tuple[RequestType, dict]] = []
    behaviour = _make_behaviour(addresses, store)
    _install_relayer(behaviour, sent)
    _run(behaviour._provision_deposit_wallet())
    batches = _batches(sent)
    assert len(batches) == 1
    return decode_dw_calls(batches[0]["transactions"])


# ---------------------------------------------------------------------------
# DepositWallet trading-approval batch
# ---------------------------------------------------------------------------


class TestDepositWalletV2Approvals:
    """The DepositWallet batch carries the V2 approvals and drops NegRiskAdapter."""

    def test_dw_batch_includes_v2_exchange_approvals(self) -> None:
        """The batch is the four V1 approvals plus both V2 approvals, nothing else.

        pUSD ``approve(ExchangeV3, MaxUint256)`` and PositionManager
        ``setApprovalForAll(ExchangeV3, true)`` are added; both NegRiskAdapter
        approvals are gone; AutoRedeemer and the Router are never approved.
        Checked for the documented addresses and for a distinct set.
        """
        for addresses in ADDRESS_SETS:
            self._check_dw_batch(addresses)

    @staticmethod
    def _check_dw_batch(addresses: Dict[str, str]) -> None:
        """Check the full DepositWallet batch built for ``addresses``.

        :param addresses: the address params.
        """
        txs = _make_behaviour(addresses)._build_dw_trading_approvals()
        calls = decode_dw_calls(txs)

        assert sorted(calls) == sorted(
            expected_calls(DW_V1_APPROVALS + DW_V2_APPROVALS, addresses)
        )
        assert all(t["value"] == "0" for t in txs)
        exchange_v3 = addresses["polymarket_exchange_v3_address"]
        assert (
            addresses["polymarket_collateral_address"],
            APPROVE,
            exchange_v3,
            MAX_UINT256,
            "0",
        ) in calls
        assert (
            addresses["polymarket_position_manager_address"],
            SET_APPROVAL_FOR_ALL,
            exchange_v3,
            1,
            "0",
        ) in calls
        raw = json.dumps(txs).lower()
        for absent in (
            "polymarket_neg_risk_adapter_address",
            "polymarket_router_address",
            "polymarket_ctf_collateral_adapter_address",
            "polymarket_neg_risk_ctf_collateral_adapter_address",
        ):
            assert addresses[absent] not in addresses_in(calls), absent
            assert addresses[absent][2:].lower() not in raw, absent
        assert AUTO_REDEEMER not in addresses_in(calls)

    def test_dw_batch_v2_approval_randomized(self) -> None:
        """For random addresses every call decodes to its declared approval.

        Fixed seed, 250 cases. Every pUSD approval to ExchangeV3 encodes
        exactly ``2**256 - 1``.
        """
        rng = random.Random(RANDOM_SEED)  # nosec B311
        expected_approvals = DW_V1_APPROVALS + DW_V2_APPROVALS
        for _ in range(RANDOM_CASES):
            a = random_addresses(rng)
            calls = decode_dw_calls(_make_behaviour(a)._build_dw_trading_approvals())
            assert sorted(calls) == sorted(expected_calls(expected_approvals, a)), a
            to_exchange_v3 = [
                c
                for c in calls
                if c[1] == APPROVE and c[2] == a["polymarket_exchange_v3_address"]
            ]
            assert [c[3] for c in to_exchange_v3] == [MAX_UINT256], a


class TestDepositWalletApprovalRecordVersioning:
    """A pre-V2 DepositWallet record gets only the missing V2 approvals, once."""

    def test_upgraded_install_gets_v2_dw_approvals_once(self, tmp_path: Path) -> None:
        """``approvals_done: true`` from before V2 sends the two V2 calls once.

        The first run relays exactly the missing V2 approvals; once that batch
        is mined, the record carries the current approvals version and the
        second run relays nothing.

        :param tmp_path: the store directory.
        """
        _write_record(tmp_path, approvals_done=True)
        sent: List[Tuple[RequestType, dict]] = []

        first = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(first, sent)
        _run(first._provision_deposit_wallet())

        batches = _batches(sent)
        assert len(batches) == 1
        assert batches[0]["dw_address"] == DW
        calls = decode_dw_calls(batches[0]["transactions"])
        assert sorted(calls) == sorted(
            expected_calls(DW_V2_APPROVALS, docs_addresses())
        )
        assert (PUSD, APPROVE, EXCHANGE_V3, MAX_UINT256, "0") in calls
        assert (POSITION_MANAGER, SET_APPROVAL_FOR_ALL, EXCHANGE_V3, 1, "0") in calls

        assert _read_record(tmp_path) == {
            "dw_address": DW,
            "dw_owner": AGENT,
            "approvals_done": True,
            "approvals_version": DW_APPROVALS_VERSION,
        }

        sent.clear()
        second = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(second, sent)
        _run(second._provision_deposit_wallet())
        assert _batches(sent) == []

    @pytest.mark.parametrize(
        "approvals_version, sends_upgrade",
        [
            (MISSING, True),
            (None, True),
            (1, True),
            (3, True),
            ("2", True),
            (DW_APPROVALS_VERSION, False),
        ],
        ids=["missing", "none", "stale", "newer", "string", "current"],
    )
    def test_recorded_approvals_version_selects_batch(
        self, tmp_path: Path, approvals_version: Any, sends_upgrade: bool
    ) -> None:
        """Only exactly the current approvals version skips the upgrade batch.

        Any other recorded version means the record predates Protocol V2: the
        two V2 calls are relayed and the full batch is never built. With the
        current version nothing is built or relayed.

        :param tmp_path: the store directory.
        :param approvals_version: the recorded approvals version.
        :param sends_upgrade: whether the two V2 calls are relayed.
        """
        _write_record(
            tmp_path, approvals_done=True, approvals_version=approvals_version
        )
        sent: List[Tuple[RequestType, dict]] = []
        behaviour = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(behaviour, sent)
        built: List[str] = []
        build_full = behaviour._build_dw_trading_approvals
        build_v2 = behaviour._build_dw_v2_trading_approvals

        def _full() -> list:
            built.append("full")
            return build_full()

        def _v2() -> list:
            built.append("v2")
            return build_v2()

        behaviour._build_dw_trading_approvals = _full  # type: ignore[method-assign]
        behaviour._build_dw_v2_trading_approvals = _v2  # type: ignore[method-assign]

        _run(behaviour._provision_deposit_wallet())

        assert "full" not in built
        batches = _batches(sent)
        if sends_upgrade:
            assert len(batches) == 1
            assert sorted(decode_dw_calls(batches[0]["transactions"])) == sorted(
                expected_calls(DW_V2_APPROVALS, docs_addresses())
            )
            assert _read_record(tmp_path)["approvals_version"] == DW_APPROVALS_VERSION
        else:
            assert batches == []
            assert built == []

    def test_upgraded_install_v2_dw_approvals_retry_until_mined(
        self, tmp_path: Path
    ) -> None:
        """An unmined upgrade batch is retried with the same two calls only.

        :param tmp_path: the store directory.
        """
        _write_record(tmp_path, approvals_done=True)
        sent: List[Tuple[RequestType, dict]] = []

        first = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(first, sent, mined=False)
        _run(first._provision_deposit_wallet())
        retry = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(retry, sent, mined=True)
        _run(retry._provision_deposit_wallet())
        done = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(done, sent, mined=True)
        _run(done._provision_deposit_wallet())

        batches = _batches(sent)
        assert len(batches) == 2
        expected = sorted(expected_calls(DW_V2_APPROVALS, docs_addresses()))
        for batch in batches:
            assert sorted(decode_dw_calls(batch["transactions"])) == expected

    def test_fresh_install_gets_full_v2_dw_batch_once(self, tmp_path: Path) -> None:
        """A DepositWallet without confirmed approvals gets the full batch once.

        :param tmp_path: the store directory.
        """
        _write_record(tmp_path, approvals_done=False)
        sent: List[Tuple[RequestType, dict]] = []

        first = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(first, sent)
        _run(first._provision_deposit_wallet())
        second = _make_behaviour(docs_addresses(), tmp_path)
        _install_relayer(second, sent)
        _run(second._provision_deposit_wallet())

        batches = _batches(sent)
        assert len(batches) == 1
        assert sorted(decode_dw_calls(batches[0]["transactions"])) == sorted(
            expected_calls(DW_V1_APPROVALS + DW_V2_APPROVALS, docs_addresses())
        )


# ---------------------------------------------------------------------------
# Safe approvals
# ---------------------------------------------------------------------------


class TestSafeRouterApproval:
    """The Safe lets the Router operate its PositionManager positions."""

    def test_safe_approves_router_for_v2_positions(self) -> None:
        """The multisend keeps the eight Safe approvals and adds the Router one.

        The new call is PositionManager ``setApprovalForAll(Router, true)``,
        sent from the Safe as a plain CALL with no value. ExchangeV3 and
        AutoRedeemer are never approved by the Safe. Checked for the
        documented addresses and for a distinct set.
        """
        for addresses in ADDRESS_SETS:
            self._check_multisend(addresses)

    @staticmethod
    def _check_multisend(addresses: Dict[str, str]) -> None:
        """Check the Safe multisend built for ``addresses``.

        :param addresses: the address params.
        """
        behaviour = _make_behaviour(addresses)
        assert _run_multisend(behaviour) == "0xsafetx"

        calls = _decode_multisend(behaviour.multisend_batches)
        assert calls == expected_calls(
            SAFE_EXISTING_APPROVALS + (SAFE_ROUTER_APPROVAL,), addresses
        )
        assert calls[-1] == (
            addresses["polymarket_position_manager_address"],
            SET_APPROVAL_FOR_ALL,
            addresses["polymarket_router_address"],
            1,
            "0",
        )
        assert addresses["polymarket_exchange_v3_address"] not in addresses_in(calls)
        assert AUTO_REDEEMER not in addresses_in(calls)


# ---------------------------------------------------------------------------
# ExchangeV3 allowance amount
# ---------------------------------------------------------------------------


class TestExchangeV3ApprovalAmount:
    """The relayer only accepts a MaxUint256 pUSD approval to ExchangeV3."""

    def test_exchange_v3_approval_is_max_uint256(self, tmp_path: Path) -> None:
        """Every pUSD approval to ExchangeV3 that any path builds is MaxUint256.

        The DepositWallet batch and the upgrade batch each approve ExchangeV3
        exactly once, for ``2**256 - 1``. Regression: across those batches and
        the Safe multisend, no bounded approval to ExchangeV3 is ever built.
        Checked for the documented addresses and for a distinct set.

        :param tmp_path: the store directory.
        """
        for index, addresses in enumerate(ADDRESS_SETS):
            store = tmp_path / str(index)
            store.mkdir()
            self._check_exchange_v3_amounts(addresses, store)

    @staticmethod
    def _check_exchange_v3_amounts(addresses: Dict[str, str], store: Path) -> None:
        """Check every ExchangeV3 approval built for ``addresses``.

        :param addresses: the address params.
        :param store: the store directory.
        """
        exchange_v3 = addresses["polymarket_exchange_v3_address"]
        pusd = addresses["polymarket_collateral_address"]
        full = decode_dw_calls(_make_behaviour(addresses)._build_dw_trading_approvals())
        upgrade = _upgrade_batch(addresses, store)
        for calls in (full, upgrade):
            approvals = [c for c in calls if c[1] == APPROVE and c[2] == exchange_v3]
            assert approvals == [(pusd, APPROVE, exchange_v3, 2**256 - 1, "0")]

        safe = _make_behaviour(addresses)
        _run_multisend(safe)
        built = full + upgrade + _decode_multisend(safe.multisend_batches)
        bounded = [
            c
            for c in built
            if c[1] == APPROVE and c[2] == exchange_v3 and c[3] != MAX_UINT256
        ]
        assert bounded == []
        relayed = addresses_in(full + upgrade)
        assert addresses["polymarket_neg_risk_adapter_address"] not in relayed
        assert addresses["polymarket_router_address"] not in relayed
