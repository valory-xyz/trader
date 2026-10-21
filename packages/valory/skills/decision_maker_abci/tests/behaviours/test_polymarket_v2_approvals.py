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

Every calldata check decodes the ABI words independently (selector plus two
32-byte words) instead of reusing the encoders under test.
"""

import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

from web3 import Web3

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (
    PolymarketSetApprovalBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import MultiSendOperation

# Polygon addresses from https://docs.polymarket.com/resources/contracts
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF_COLLATERAL_ADAPTER = "0xAdA100Db00Ca00073811820692005400218FcE1f"
NEG_RISK_CTF_COLLATERAL_ADAPTER = "0xadA2005600Dec949baf300f4C6120000bDB6eAab"
EXCHANGE_V3 = "0xe3333700cA9d93003F00f0F71f8515005F6c00Aa"
POSITION_MANAGER = "0x006F54F7f9A22e0000CC2AB60031000000ae9fEF"
ROUTER = "0x12121212006e4CD160D18e3f00711DA5c3372600"
AUTO_REDEEMER = "0xa1200000d0002264C9a1698e001292D00E1b00af"

MAX_UINT256 = 2**256 - 1
APPROVE = "095ea7b3"  # approve(address,uint256)
SET_APPROVAL_FOR_ALL = "a22cb465"  # setApprovalForAll(address,bool)

DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
AGENT = "agent"
RANDOM_SEED = 20260501
RANDOM_CASES = 250

# A decoded call: (target, selector, address argument, uint argument, value).
Call = Tuple[str, str, str, int, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docs_addresses() -> Dict[str, str]:
    """Return the address params set to the documented Polygon addresses.

    :return: a mapping of address param name to address.
    """
    return {
        "polymarket_collateral_address": PUSD,
        "polymarket_ctf_address": CTF,
        "polymarket_ctf_exchange_address": CTF_EXCHANGE,
        "polymarket_neg_risk_ctf_exchange_address": NEG_RISK_CTF_EXCHANGE,
        "polymarket_neg_risk_adapter_address": NEG_RISK_ADAPTER,
        "polymarket_ctf_collateral_adapter_address": CTF_COLLATERAL_ADAPTER,
        "polymarket_neg_risk_ctf_collateral_adapter_address": (
            NEG_RISK_CTF_COLLATERAL_ADAPTER
        ),
        "polymarket_exchange_v3_address": EXCHANGE_V3,
        "polymarket_position_manager_address": POSITION_MANAGER,
        "polymarket_router_address": ROUTER,
    }


def _random_addresses(rng: random.Random) -> Dict[str, str]:
    """Return the address params set to distinct random checksum addresses.

    :param rng: the seeded random generator.
    :return: a mapping of address param name to a random address.
    """
    names = list(_docs_addresses())
    seen: set = set()
    out: Dict[str, str] = {}
    for name in names:
        while True:
            addr = Web3.to_checksum_address(f"0x{rng.getrandbits(160):040x}")
            if addr not in seen:
                break
        seen.add(addr)
        out[name] = addr
    return out


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


def _to_bytes(data: Any) -> bytes:
    """Coerce 0x-hex text or bytes calldata to bytes.

    :param data: the calldata.
    :return: the calldata bytes.
    """
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    text = str(data)
    return bytes.fromhex(text[2:] if text.startswith("0x") else text)


def _decode(target: str, data: Any, value: Any) -> Call:
    """Decode an approve / setApprovalForAll call from its ABI words.

    :param target: the call target.
    :param data: the calldata.
    :param value: the native value sent with the call.
    :return: the decoded call.
    """
    raw = _to_bytes(data)
    assert len(raw) == 4 + 32 + 32, f"unexpected calldata length {len(raw)}"
    selector = raw[:4].hex()
    address_word, uint_word = raw[4:36], raw[36:68]
    assert address_word[:12] == bytes(12), "address word is not left-padded"
    argument = Web3.to_checksum_address("0x" + address_word[12:].hex())
    return (
        Web3.to_checksum_address(target),
        selector,
        argument,
        int.from_bytes(uint_word, "big"),
        str(value),
    )


def _decode_dw_calls(calls: List[Dict[str, Any]]) -> List[Call]:
    """Decode the ``{"to", "data", "value"}`` calls of a DepositWallet batch.

    :param calls: the batch calls.
    :return: the decoded calls.
    """
    return [_decode(c["to"], c["data"], c["value"]) for c in calls]


def _decode_multisend(batches: List[Any]) -> List[Call]:
    """Decode the Safe multisend batches.

    :param batches: the multisend batches.
    :return: the decoded calls.
    """
    for batch in batches:
        assert batch.operation == MultiSendOperation.CALL
    return [_decode(b.to, b.data, b.value) for b in batches]


def _v1_dw_calls(a: Dict[str, str]) -> List[Call]:
    """Return the DepositWallet V1 trading approvals that stay in the batch.

    :param a: the address params.
    :return: the expected calls.
    """
    pusd, ctf = a["polymarket_collateral_address"], a["polymarket_ctf_address"]
    exchange = a["polymarket_ctf_exchange_address"]
    neg_risk_exchange = a["polymarket_neg_risk_ctf_exchange_address"]
    return [
        (pusd, APPROVE, exchange, MAX_UINT256, "0"),
        (pusd, APPROVE, neg_risk_exchange, MAX_UINT256, "0"),
        (ctf, SET_APPROVAL_FOR_ALL, exchange, 1, "0"),
        (ctf, SET_APPROVAL_FOR_ALL, neg_risk_exchange, 1, "0"),
    ]


def _v2_dw_calls(a: Dict[str, str]) -> List[Call]:
    """Return the two DepositWallet V2 trading approvals.

    :param a: the address params.
    :return: the expected calls.
    """
    exchange_v3 = a["polymarket_exchange_v3_address"]
    return [
        (a["polymarket_collateral_address"], APPROVE, exchange_v3, MAX_UINT256, "0"),
        (
            a["polymarket_position_manager_address"],
            SET_APPROVAL_FOR_ALL,
            exchange_v3,
            1,
            "0",
        ),
    ]


def _existing_safe_calls(a: Dict[str, str]) -> List[Call]:
    """Return the eight existing Safe approvals, in their multisend order.

    :param a: the address params.
    :return: the expected calls.
    """
    pusd, ctf = a["polymarket_collateral_address"], a["polymarket_ctf_address"]
    exchange = a["polymarket_ctf_exchange_address"]
    neg_risk_exchange = a["polymarket_neg_risk_ctf_exchange_address"]
    adapter = a["polymarket_neg_risk_adapter_address"]
    return [
        (pusd, APPROVE, exchange, MAX_UINT256, "0"),
        (ctf, SET_APPROVAL_FOR_ALL, exchange, 1, "0"),
        (pusd, APPROVE, neg_risk_exchange, MAX_UINT256, "0"),
        (ctf, SET_APPROVAL_FOR_ALL, neg_risk_exchange, 1, "0"),
        (pusd, APPROVE, adapter, MAX_UINT256, "0"),
        (ctf, SET_APPROVAL_FOR_ALL, adapter, 1, "0"),
        (
            ctf,
            SET_APPROVAL_FOR_ALL,
            a["polymarket_ctf_collateral_adapter_address"],
            1,
            "0",
        ),
        (
            ctf,
            SET_APPROVAL_FOR_ALL,
            a["polymarket_neg_risk_ctf_collateral_adapter_address"],
            1,
            "0",
        ),
    ]


def _safe_router_call(a: Dict[str, str]) -> Call:
    """Return the Safe's PositionManager ``setApprovalForAll(Router, true)``.

    :param a: the address params.
    :return: the expected call.
    """
    return (
        a["polymarket_position_manager_address"],
        SET_APPROVAL_FOR_ALL,
        a["polymarket_router_address"],
        1,
        "0",
    )


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


def _write_pre_v2_record(store: Path, approvals_done: bool = True) -> None:
    """Write a DepositWallet record in the shape used before Protocol V2.

    :param store: the store directory.
    :param approvals_done: the recorded approvals flag.
    """
    (store / DEPOSIT_WALLET_STORE).write_text(
        json.dumps(
            {"dw_address": DW, "dw_owner": AGENT, "approvals_done": approvals_done}
        )
    )


def _all_calldata_words(calls: List[Call]) -> List[str]:
    """Return every address that appears in ``calls`` as target or argument.

    :param calls: the decoded calls.
    :return: the addresses.
    """
    return [c[0] for c in calls] + [c[2] for c in calls]


# ---------------------------------------------------------------------------
# DepositWallet trading-approval batch
# ---------------------------------------------------------------------------


class TestDepositWalletV2Approvals:
    """The DepositWallet batch carries the V2 approvals and drops NegRiskAdapter."""

    def test_dw_batch_includes_v2_exchange_approvals(self) -> None:
        """The batch is the four V1 approvals plus both V2 approvals, nothing else.

        pUSD ``approve(ExchangeV3, MaxUint256)`` and PositionManager
        ``setApprovalForAll(ExchangeV3, true)`` are added; both NegRiskAdapter
        approvals are gone; AutoRedeemer is never approved.
        """
        a = _docs_addresses()
        calls = _decode_dw_calls(_make_behaviour(a)._build_dw_trading_approvals())

        assert len(calls) == 6
        assert sorted(calls) == sorted(_v1_dw_calls(a) + _v2_dw_calls(a))
        assert (PUSD, APPROVE, EXCHANGE_V3, MAX_UINT256, "0") in calls
        assert (POSITION_MANAGER, SET_APPROVAL_FOR_ALL, EXCHANGE_V3, 1, "0") in calls
        addresses = _all_calldata_words(calls)
        assert NEG_RISK_ADAPTER not in addresses
        assert AUTO_REDEEMER not in addresses
        assert ROUTER not in addresses

    def test_dw_batch_has_no_neg_risk_adapter_approval(self) -> None:
        """Neither a pUSD allowance nor operator rights go to the NegRiskAdapter."""
        a = _docs_addresses()
        txs = _make_behaviour(a)._build_dw_trading_approvals()
        raw = json.dumps(txs).lower()

        assert NEG_RISK_ADAPTER[2:].lower() not in raw
        assert len(txs) == 6
        targets = sorted(Web3.to_checksum_address(t["to"]) for t in txs)
        assert targets == sorted([PUSD, PUSD, PUSD, CTF, CTF, POSITION_MANAGER])
        assert all(t["value"] == "0" for t in txs)

    def test_dw_batch_v2_approval_randomized(self) -> None:
        """For random addresses every call decodes to its target and spender.

        Fixed seed, 250 cases. Every pUSD approval to ExchangeV3 encodes
        exactly ``2**256 - 1`` and the batch never references the
        NegRiskAdapter, the Router or the Safe-only collateral adapters.
        """
        rng = random.Random(RANDOM_SEED)  # nosec B311
        for _ in range(RANDOM_CASES):
            a = _random_addresses(rng)
            calls = _decode_dw_calls(_make_behaviour(a)._build_dw_trading_approvals())
            assert sorted(calls) == sorted(_v1_dw_calls(a) + _v2_dw_calls(a)), a
            exchange_v3_approvals = [
                c
                for c in calls
                if c[1] == APPROVE and c[2] == a["polymarket_exchange_v3_address"]
            ]
            assert len(exchange_v3_approvals) == 1, a
            assert exchange_v3_approvals[0][0] == a["polymarket_collateral_address"]
            assert exchange_v3_approvals[0][3] == MAX_UINT256
            addresses = _all_calldata_words(calls)
            for absent in (
                "polymarket_neg_risk_adapter_address",
                "polymarket_router_address",
                "polymarket_ctf_collateral_adapter_address",
                "polymarket_neg_risk_ctf_collateral_adapter_address",
            ):
                assert a[absent] not in addresses, (absent, a)


class TestDepositWalletApprovalRecordVersioning:
    """A pre-V2 DepositWallet record gets only the missing V2 approvals, once."""

    def test_upgraded_install_gets_v2_dw_approvals_once(self, tmp_path: Path) -> None:
        """``approvals_done: true`` from before V2 sends the two V2 calls once.

        The first run relays exactly the missing V2 approvals; once that batch
        is mined, the second run relays nothing.

        :param tmp_path: the store directory.
        """
        _write_pre_v2_record(tmp_path, approvals_done=True)
        sent: List[Tuple[RequestType, dict]] = []

        first = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(first, sent)
        _run(first._provision_deposit_wallet())

        batches = _batches(sent)
        assert len(batches) == 1
        assert batches[0]["dw_address"] == DW
        calls = _decode_dw_calls(batches[0]["transactions"])
        assert sorted(calls) == sorted(_v2_dw_calls(_docs_addresses()))
        assert (PUSD, APPROVE, EXCHANGE_V3, MAX_UINT256, "0") in calls
        assert (POSITION_MANAGER, SET_APPROVAL_FOR_ALL, EXCHANGE_V3, 1, "0") in calls

        record = json.loads((tmp_path / DEPOSIT_WALLET_STORE).read_text())
        assert record["dw_address"] == DW
        assert record["dw_owner"] == AGENT
        assert record["approvals_done"] is True

        sent.clear()
        second = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(second, sent)
        _run(second._provision_deposit_wallet())
        assert _batches(sent) == []

    def test_upgraded_install_v2_dw_approvals_retry_until_mined(
        self, tmp_path: Path
    ) -> None:
        """An unmined upgrade batch is retried with the same two calls only."""
        _write_pre_v2_record(tmp_path, approvals_done=True)
        sent: List[Tuple[RequestType, dict]] = []

        first = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(first, sent, mined=False)
        _run(first._provision_deposit_wallet())
        retry = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(retry, sent, mined=True)
        _run(retry._provision_deposit_wallet())
        done = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(done, sent, mined=True)
        _run(done._provision_deposit_wallet())

        batches = _batches(sent)
        assert len(batches) == 2
        expected = sorted(_v2_dw_calls(_docs_addresses()))
        for batch in batches:
            assert sorted(_decode_dw_calls(batch["transactions"])) == expected

    def test_fresh_install_gets_full_v2_dw_batch_once(self, tmp_path: Path) -> None:
        """A DepositWallet without confirmed approvals gets the full batch once."""
        _write_pre_v2_record(tmp_path, approvals_done=False)
        sent: List[Tuple[RequestType, dict]] = []

        first = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(first, sent)
        _run(first._provision_deposit_wallet())
        second = _make_behaviour(_docs_addresses(), tmp_path)
        _install_relayer(second, sent)
        _run(second._provision_deposit_wallet())

        batches = _batches(sent)
        assert len(batches) == 1
        a = _docs_addresses()
        assert sorted(_decode_dw_calls(batches[0]["transactions"])) == sorted(
            _v1_dw_calls(a) + _v2_dw_calls(a)
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
        AutoRedeemer are never approved by the Safe.
        """
        a = _docs_addresses()
        behaviour = _make_behaviour(a)
        assert _run_multisend(behaviour) == "0xsafetx"

        calls = _decode_multisend(behaviour.multisend_batches)
        assert len(calls) == 9
        assert calls[:8] == _existing_safe_calls(a)
        assert calls[8] == (POSITION_MANAGER, SET_APPROVAL_FOR_ALL, ROUTER, 1, "0")
        assert calls.count(_safe_router_call(a)) == 1
        addresses = _all_calldata_words(calls)
        assert EXCHANGE_V3 not in addresses
        assert AUTO_REDEEMER not in addresses

    def test_safe_multisend_router_approval_randomized(self) -> None:
        """For random addresses the Safe multisend decodes to the nine calls.

        Fixed seed, 250 cases.
        """
        rng = random.Random(RANDOM_SEED + 1)  # nosec B311
        for _ in range(RANDOM_CASES):
            a = _random_addresses(rng)
            behaviour = _make_behaviour(a)
            _run_multisend(behaviour)
            calls = _decode_multisend(behaviour.multisend_batches)
            assert calls == _existing_safe_calls(a) + [_safe_router_call(a)], a
            assert a["polymarket_exchange_v3_address"] not in (
                _all_calldata_words(calls)
            )


# ---------------------------------------------------------------------------
# ExchangeV3 allowance amount
# ---------------------------------------------------------------------------


class TestExchangeV3ApprovalAmount:
    """The relayer only accepts a MaxUint256 pUSD approval to ExchangeV3."""

    def test_exchange_v3_approval_is_max_uint256(self, tmp_path: Path) -> None:
        """Both the DepositWallet batch and the upgrade batch approve MaxUint256."""
        a = _docs_addresses()
        full = _decode_dw_calls(_make_behaviour(a)._build_dw_trading_approvals())

        _write_pre_v2_record(tmp_path, approvals_done=True)
        sent: List[Tuple[RequestType, dict]] = []
        behaviour = _make_behaviour(a, tmp_path)
        _install_relayer(behaviour, sent)
        _run(behaviour._provision_deposit_wallet())
        batches = _batches(sent)
        assert len(batches) == 1
        upgrade = _decode_dw_calls(batches[0]["transactions"])

        for calls in (full, upgrade):
            approvals = [c for c in calls if c[1] == APPROVE and c[2] == EXCHANGE_V3]
            assert len(approvals) == 1
            assert approvals[0] == (PUSD, APPROVE, EXCHANGE_V3, 2**256 - 1, "0")

    def test_no_bounded_exchange_v3_approval_is_built(self, tmp_path: Path) -> None:
        """Regression: no code path builds a bounded pUSD approval to ExchangeV3.

        Every ``approve`` encoded while building the DepositWallet batch, the
        upgrade batch and the Safe multisend is recorded; at least one targets
        ExchangeV3, and each of those carries ``2**256 - 1``.

        :param tmp_path: the store directory.
        """
        a = _docs_addresses()
        built: List[Tuple[str, int]] = []
        original = PolymarketSetApprovalBehaviour._build_erc20_approve_data

        def _spy(self: Any, spender: str, amount: int) -> str:
            built.append((Web3.to_checksum_address(spender), amount))
            return original(self, spender, amount)

        _write_pre_v2_record(tmp_path, approvals_done=True)
        sent: List[Tuple[RequestType, dict]] = []
        with patch.object(
            PolymarketSetApprovalBehaviour, "_build_erc20_approve_data", _spy
        ):
            _make_behaviour(a)._build_dw_trading_approvals()
            upgrading = _make_behaviour(a, tmp_path)
            _install_relayer(upgrading, sent)
            _run(upgrading._provision_deposit_wallet())
            _run_multisend(_make_behaviour(a))

        to_exchange_v3 = [amount for spender, amount in built if spender == EXCHANGE_V3]
        assert to_exchange_v3, "no pUSD approval to ExchangeV3 was built"
        assert all(amount == MAX_UINT256 for amount in to_exchange_v3)

        relayed = [
            call
            for batch in _batches(sent)
            for call in _decode_dw_calls(batch["transactions"])
        ]
        assert [c for c in relayed if c[1] == APPROVE and c[2] == EXCHANGE_V3] == [
            (PUSD, APPROVE, EXCHANGE_V3, MAX_UINT256, "0")
        ]
        all_addresses = _all_calldata_words(relayed)
        assert AUTO_REDEEMER not in all_addresses
        assert NEG_RISK_ADAPTER not in all_addresses
