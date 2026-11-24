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

"""Tests for the olas_mech contract package."""

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterator, List, Tuple
from unittest.mock import MagicMock, patch

import pytest
import yaml
from aea_ledger_ethereum import EthereumApi
from eth_abi import decode as abi_decode
from web3 import Web3
from web3.exceptions import (
    ContractCustomError,
    ContractLogicError,
    ContractPanicError,
    Web3RPCError,
)

from packages.valory.contracts.olas_mech import contract as contract_module
from packages.valory.contracts.olas_mech.contract import (
    MARKETPLACE_DELIVER_WITH_CAP_SIGNATURE,
    MARKETPLACE_DELIVER_WITH_NONCES_SIGNATURE,
    MAX_INFLIGHT_SIMULATIONS,
    OlasMechContract,
    SIMULATION_OK_KEY,
    SIMULATION_RPC_DEADLINE_SECONDS,
    SIMULATION_TIMED_OUT_KEY,
    simulate_with_deadline,
)

_ABI_PATH = Path(__file__).parent.parent / "build" / "AgentMech.json"
_REQUESTER = "0x1111111111111111111111111111111111111111"
_SENDER = "0x3333333333333333333333333333333333333333"
_MECH = "0x2222222222222222222222222222222222222222"
_MARKETPLACE = "0x4444444444444444444444444444444444444444"
_MARKETPLACE_CHECKSUM_INPUT = "0x343f2b005cf6d70ba610cd9f1f1927049414b582"
# Selectors of the marketplace's own settlement overloads (MechMarketplace ABI).
_MARKETPLACE_CAP_SELECTOR = "c2ee2841"
_MARKETPLACE_NONCES_SELECTOR = "39a6aac7"
_EXEC_TYPES = ["address", "uint256", "bytes", "uint8", "uint256"]
_CAP_TYPES = ["address", "(bytes,bytes,bytes)[]", "uint256[]", "uint256[]", "bytes"]
_NONCES_TYPES = [
    "address",
    "(bytes,bytes,bytes)[]",
    "uint256[]",
    "uint256[]",
    "uint256[]",
    "uint256[]",
    "bytes",
]
_DELIVER_WITH_SIGS = [
    {
        "requestData": b"\xaa" * 32,
        "signature": b"\xbb" * 65,
        "deliveryData": b"\xcc" * 32,
    },
    {
        "requestData": b"\xdd" * 32,
        "signature": b"\xee" * 65,
        "deliveryData": b"\xff" * 32,
    },
]
_CAP_OVERLOAD_SIGNATURE = (
    "deliverMarketplaceWithSignatures("
    "address,(bytes,bytes,bytes)[],uint256[],uint256[],bytes)"
)
_LEGACY_OVERLOAD_SIGNATURE = (
    "deliverMarketplaceWithSignatures(address,(bytes,bytes,bytes)[],uint256[],bytes)"
)
_NONCES_OVERLOAD_SIGNATURE = (
    "deliverMarketplaceWithSignatures("
    "address,(bytes,bytes,bytes)[],uint256[],uint256[],uint256[],uint256[],bytes)"
)


def _web3_contract() -> object:
    """Build a Web3 contract instance from the packaged ABI."""
    with open(_ABI_PATH) as f:
        artifact = json.load(f)
    return Web3().eth.contract(abi=artifact["abi"])


def _offline_ledger_api() -> EthereumApi:
    """An EthereumApi that never connects: contract reads and simulation are patched."""
    return EthereumApi(address="http://127.0.0.1:9")


def _call_through_exec(method: str, **kwargs: Any) -> Tuple[Dict, MagicMock]:
    """Invoke a settlement builder with the packaged ABI, patching only the simulation."""
    with (
        patch.object(OlasMechContract, "get_instance", return_value=_web3_contract()),
        patch.object(
            contract_module,
            "simulate_with_deadline",
            return_value={SIMULATION_OK_KEY: True, SIMULATION_TIMED_OUT_KEY: False},
        ) as simulate,
    ):
        result = getattr(OlasMechContract, method)(
            ledger_api=_offline_ledger_api(),
            contract_address=_MECH,
            marketplace_address=_MARKETPLACE,
            sender=_SENDER,
            requester=_REQUESTER,
            deliverWithSignatures=_DELIVER_WITH_SIGS,
            paymentData=b"",
            **kwargs,
        )
    return result, simulate


def _split_exec(calldata: bytes) -> Tuple[str, Tuple]:
    """Return the outer selector and the decoded ``exec`` arguments."""
    return calldata[:4].hex(), abi_decode(_EXEC_TYPES, calldata[4:])


_CAP_KWARGS = {"deliveryRates": [99, 150], "maxRates": [100, 200]}
_NONCES_KWARGS = {
    "deliveryRates": [99, 150],
    "maxRates": [100, 200],
    "nonces": [4243, 4242],
    "deadlines": [1_900_000_000, 1_900_000_060],
}


@pytest.mark.parametrize(
    "method, kwargs, inner_selector",
    [
        ("get_offchain_deliver_data_with_cap", _CAP_KWARGS, _MARKETPLACE_CAP_SELECTOR),
        (
            "get_offchain_deliver_data_with_nonces",
            _NONCES_KWARGS,
            _MARKETPLACE_NONCES_SELECTOR,
        ),
    ],
)
class TestSettlementThroughExec:
    """The 5-/7-arg deliveries are marketplace calls run by the mech's ``exec``."""

    def test_outer_call_is_a_plain_exec_to_the_marketplace(
        self, method: str, kwargs: Dict, inner_selector: str
    ) -> None:
        """exec(marketplace, 0, inner, CALL, 0): no value, no delegatecall, all gas."""
        result, _ = _call_through_exec(method, **kwargs)
        selector, (to, value, _inner, operation, tx_gas) = _split_exec(result["data"])
        exec_selector = Web3.keccak(text="exec(address,uint256,bytes,uint8,uint256)")
        assert selector == exec_selector.hex()[:8]
        assert to.lower() == _MARKETPLACE.lower()
        assert (value, operation, tx_gas) == (0, 0, 0)

    def test_inner_call_selects_the_marketplace_overload(
        self, method: str, kwargs: Dict, inner_selector: str
    ) -> None:
        """The wrapped call's first 4 bytes are the marketplace overload's selector."""
        result, _ = _call_through_exec(method, **kwargs)
        _, (_to, _value, inner, _op, _gas) = _split_exec(result["data"])
        assert inner[:4].hex() == inner_selector

    def test_simulation_runs_the_exec_call_from_the_safe_on_the_mech(
        self, method: str, kwargs: Dict, inner_selector: str
    ) -> None:
        """The simulated call is exactly the returned calldata, sent to the mech."""
        result, simulate = _call_through_exec(method, **kwargs)
        (_ledger, address, sender, data, deadline), _ = simulate.call_args
        assert (address, sender) == (_MECH, _SENDER)
        assert data == "0x" + result["data"].hex()
        assert deadline == SIMULATION_RPC_DEADLINE_SECONDS
        assert result[SIMULATION_OK_KEY] is True
        assert result[SIMULATION_TIMED_OUT_KEY] is False

    def test_deadline_reaches_the_simulation(
        self, method: str, kwargs: Dict, inner_selector: str
    ) -> None:
        """A caller's ``deadline_seconds`` bounds the exec simulation."""
        _, simulate = _call_through_exec(method, deadline_seconds=3.5, **kwargs)
        (_ledger, _address, _sender, _data, deadline), _ = simulate.call_args
        assert deadline == 3.5


def test_cap_inner_call_round_trips_its_arguments() -> None:
    """The wrapped 5-arg call decodes back to the requester, items and both rate arrays."""
    result, _ = _call_through_exec("get_offchain_deliver_data_with_cap", **_CAP_KWARGS)
    _, (_to, _value, inner, _op, _gas) = _split_exec(result["data"])
    requester, items, rates, caps, payment = abi_decode(_CAP_TYPES, inner[4:])
    assert requester.lower() == _REQUESTER.lower()
    assert [item[0] for item in items] == [b"\xaa" * 32, b"\xdd" * 32]
    assert [item[2] for item in items] == [b"\xcc" * 32, b"\xff" * 32]
    assert (list(rates), list(caps), payment) == ([99, 150], [100, 200], b"")


def test_nonces_inner_call_round_trips_its_arguments_in_order() -> None:
    """The wrapped 7-arg call keeps rates, caps, nonces and deadlines aligned."""
    result, _ = _call_through_exec(
        "get_offchain_deliver_data_with_nonces", **_NONCES_KWARGS
    )
    _, (_to, _value, inner, _op, _gas) = _split_exec(result["data"])
    decoded = abi_decode(_NONCES_TYPES, inner[4:])
    assert decoded[0].lower() == _REQUESTER.lower()
    assert [item[1] for item in decoded[1]] == [b"\xbb" * 65, b"\xee" * 65]
    assert list(decoded[2]) == [99, 150]
    assert list(decoded[3]) == [100, 200]
    assert list(decoded[4]) == [4243, 4242]
    assert list(decoded[5]) == [1_900_000_000, 1_900_000_060]


@pytest.mark.parametrize(
    "signature, selector",
    [
        (_CAP_OVERLOAD_SIGNATURE, _MARKETPLACE_CAP_SELECTOR),
        (_NONCES_OVERLOAD_SIGNATURE, _MARKETPLACE_NONCES_SELECTOR),
        (MARKETPLACE_DELIVER_WITH_CAP_SIGNATURE, _MARKETPLACE_CAP_SELECTOR),
        (MARKETPLACE_DELIVER_WITH_NONCES_SIGNATURE, _MARKETPLACE_NONCES_SELECTOR),
    ],
)
def test_marketplace_signatures_hash_to_the_marketplace_selectors(
    signature: str, selector: str
) -> None:
    """The overload signatures used for encoding hash to the marketplace's selectors."""
    assert Web3.keccak(text=signature).hex()[:8] == selector


@pytest.mark.parametrize(
    "verdict",
    [
        {SIMULATION_OK_KEY: False, SIMULATION_TIMED_OUT_KEY: False},
        {SIMULATION_OK_KEY: False, SIMULATION_TIMED_OUT_KEY: True},
    ],
)
def test_unsuccessful_simulation_verdict_is_reported(verdict: Dict) -> None:
    """A reverted or inconclusive exec simulation comes back unchanged."""
    with (
        patch.object(OlasMechContract, "get_instance", return_value=_web3_contract()),
        patch.object(contract_module, "simulate_with_deadline", return_value=verdict),
    ):
        result = OlasMechContract.get_offchain_deliver_data_with_cap(
            ledger_api=_offline_ledger_api(),
            contract_address=_MECH,
            marketplace_address=_MARKETPLACE,
            sender=_SENDER,
            requester=_REQUESTER,
            deliverWithSignatures=_DELIVER_WITH_SIGS[:1],
            deliveryRates=[99],
            maxRates=[100],
            paymentData=b"",
        )
    assert {key: result[key] for key in verdict} == verdict


class TestGetOffchainDeliverDataLegacy:
    """`get_offchain_deliver_data` keeps resolving the 4-arg overload against the refreshed ABI."""

    def test_calldata_selects_the_four_arg_overload(self) -> None:
        """First 4 bytes match the legacy 4-arg signature's selector.

        The bare-name lookup the flag-off path relies on must keep picking the
        4-arg overload as the ABI gains more.
        """
        deliver_with_sigs = [
            {
                "requestData": b"\xaa" * 32,
                "signature": b"\xbb" * 65,
                "deliveryData": b"\xcc" * 32,
            }
        ]
        with (
            patch.object(
                OlasMechContract, "get_instance", return_value=_web3_contract()
            ),
            patch.object(
                contract_module,
                "simulate_with_deadline",
                return_value={SIMULATION_OK_KEY: True, SIMULATION_TIMED_OUT_KEY: False},
            ),
        ):
            result = OlasMechContract.get_offchain_deliver_data(
                ledger_api=_offline_ledger_api(),
                contract_address=_MECH,
                sender=_SENDER,
                requester=_REQUESTER,
                deliverWithSignatures=deliver_with_sigs,
                deliveryRates=[100],
                paymentData=b"",
            )
        expected = Web3().keccak(text=_LEGACY_OVERLOAD_SIGNATURE).hex()[:8]
        assert result["data"][:4].hex() == expected


def test_mech_marketplace_is_returned_checksummed() -> None:
    """The mech's ``mechMarketplace()`` comes back in checksum form."""
    instance = Web3().eth.contract(abi=_web3_contract().abi)
    instance.functions = MagicMock()
    instance.functions.mechMarketplace.return_value.call.return_value = (
        _MARKETPLACE_CHECKSUM_INPUT
    )
    with patch.object(OlasMechContract, "get_instance", return_value=instance):
        result = OlasMechContract.get_mech_marketplace(
            ledger_api=_offline_ledger_api(), contract_address=_MECH
        )
    assert result == {
        "mech_marketplace": Web3.to_checksum_address(_MARKETPLACE_CHECKSUM_INPUT)
    }


_SHORT_DEADLINE = 0.2
# Generous upper bound on how long a bounded call may take to return.
_PROMPT_RETURN_SECONDS = 1.5
_RELEASE_WAIT_SECONDS = 5.0
_LEDGER_CONNECTION_YAML = (
    Path(__file__).parents[3] / "connections" / "ledger" / "connection.yaml"
)

_OK = {SIMULATION_OK_KEY: True, SIMULATION_TIMED_OUT_KEY: False}
_FAILED = {SIMULATION_OK_KEY: False, SIMULATION_TIMED_OUT_KEY: False}
_INCONCLUSIVE = {SIMULATION_OK_KEY: False, SIMULATION_TIMED_OUT_KEY: True}


class _FakeEth:
    """Minimal ``web3.eth`` stand-in whose ``call`` runs an injected behaviour."""

    def __init__(self, behaviour: Callable[[], object]) -> None:
        """Store the behaviour run on each ``call``."""
        self._behaviour = behaviour
        self.calls = 0

    def call(self, _tx: dict) -> object:
        """Run the injected behaviour as the simulated ``eth_call``."""
        self.calls += 1
        return self._behaviour()


class _FakeApi:
    """Minimal ``EthereumApi.api`` stand-in exposing ``eth`` and address helper."""

    def __init__(self, behaviour: Callable[[], object]) -> None:
        """Wire up the fake ``eth`` object."""
        self.eth = _FakeEth(behaviour)

    @staticmethod
    def to_checksum_address(address: str) -> str:
        """Return the address unchanged; checksumming is irrelevant to the bound."""
        return address


class _FakeLedgerApi:
    """Minimal ``EthereumApi`` stand-in for exercising simulations directly."""

    def __init__(self, behaviour: Callable[[], object]) -> None:
        """Wire up the fake ``api`` object."""
        self.api = _FakeApi(behaviour)


class _Hang:
    """``eth_call`` behaviour that blocks until the test releases it."""

    def __init__(self) -> None:
        """Create the release and start signals."""
        self.release = threading.Event()
        self.started = threading.Event()

    def __call__(self) -> object:
        """Block until released, then return an empty result."""
        self.started.set()
        self.release.wait(_RELEASE_WAIT_SECONDS)
        return b""


def _raising(error: Exception) -> Callable[[], object]:
    """Return an ``eth_call`` behaviour that raises ``error``."""

    def _raise() -> object:
        raise error

    return _raise


def _simulate(
    ledger: _FakeLedgerApi, deadline: float = _SHORT_DEADLINE, data: str = "0x"
) -> dict:
    return simulate_with_deadline(ledger, _MECH, _SENDER, data, deadline)  # type: ignore[arg-type]


def _calldata(index: int) -> str:
    """Return distinct calldata per ``index``, so calls are not the same call."""
    return f"0x{index:08x}"


@pytest.fixture
def hang() -> Iterator[_Hang]:
    """Yield a hanging behaviour and free every simulation slot afterwards."""
    behaviour = _Hang()
    yield behaviour
    behaviour.release.set()
    acquired: List[bool] = [
        contract_module._inflight_simulations.acquire(timeout=_RELEASE_WAIT_SECONDS)
        for _ in range(MAX_INFLIGHT_SIMULATIONS)
    ]
    for got in acquired:
        if got:
            contract_module._inflight_simulations.release()
    assert all(acquired), "a simulation thread did not exit after release"
    assert not contract_module._inflight_calls


class TestSimulateWithDeadline:
    """``simulate_with_deadline`` separates node answers from inconclusive outcomes."""

    def test_returning_call_is_ok(self) -> None:
        """A returning ``eth_call`` is a conclusive success."""
        assert _simulate(_FakeLedgerApi(lambda: b"")) == _OK

    @pytest.mark.parametrize(
        "error",
        [
            ContractLogicError("execution reverted: GS026", data="0x08c379a0"),
            ContractLogicError("execution reverted", data="0x"),
            ContractLogicError("execution reverted", data="Reverted 0x08c379a0"),
            ContractLogicError("execution reverted", data=None),
            ContractLogicError("execution reverted", data="no data"),
            ContractCustomError("0xb7a4f2c1", data="0xb7a4f2c1"),
            ContractPanicError("Panic error 0x11", data="0x4e487b71"),
        ],
    )
    def test_revert_is_a_conclusive_failure(self, error: Exception) -> None:
        """Only a revert reported by the node is charged as a failed simulation."""
        assert _simulate(_FakeLedgerApi(_raising(error))) == _FAILED

    @pytest.mark.parametrize(
        "error",
        [
            TimeoutError("read timed out"),
            ConnectionResetError("connection reset by peer"),
            Web3RPCError("{'code': -32005, 'message': 'rate limit exceeded'}"),
            Web3RPCError("{'code': -32000, 'message': 'header not found'}"),
            ValueError("execution reverted: GS026"),
            KeyError("result"),
            ContractLogicError("header not found", data=None),
            ContractLogicError(
                "execution reverted: daily request count exceeded",
                data={"see": "https://infura.io/dashboard"},
            ),
            ContractCustomError("rate limit exceeded", data="rate limit exceeded"),
        ],
    )
    def test_non_revert_error_is_inconclusive(self, error: Exception) -> None:
        """Any error other than a revert, including RPC-level errors, is inconclusive."""
        assert _simulate(_FakeLedgerApi(_raising(error))) == _INCONCLUSIVE

    def test_hanging_call_is_inconclusive_on_the_deadline(self, hang: _Hang) -> None:
        """A call that overruns returns on the deadline, not when the call unblocks."""
        begin = time.monotonic()
        result = _simulate(_FakeLedgerApi(hang))
        elapsed = time.monotonic() - begin

        assert result == _INCONCLUSIVE
        assert hang.started.is_set()
        assert elapsed < _PROMPT_RETURN_SECONDS

    def test_full_pool_is_inconclusive_without_calling(self, hang: _Hang) -> None:
        """With every slot held by a hung call, a new call never starts."""
        for index in range(MAX_INFLIGHT_SIMULATIONS):
            assert (
                _simulate(_FakeLedgerApi(hang), data=_calldata(index)) == _INCONCLUSIVE
            )

        fresh = _FakeLedgerApi(lambda: b"")
        begin = time.monotonic()
        result = _simulate(
            fresh,
            deadline=_RELEASE_WAIT_SECONDS,
            data=_calldata(MAX_INFLIGHT_SIMULATIONS),
        )
        elapsed = time.monotonic() - begin

        assert result == _INCONCLUSIVE
        assert fresh.api.eth.calls == 0
        assert elapsed < _PROMPT_RETURN_SECONDS

    def test_thread_start_failure_is_inconclusive_and_frees_the_slot(
        self, hang: _Hang
    ) -> None:
        """A worker that cannot start leaves no slot held."""
        with patch.object(
            contract_module.threading.Thread,
            "start",
            side_effect=RuntimeError("can't start new thread"),
        ):
            for _ in range(MAX_INFLIGHT_SIMULATIONS + 1):
                assert _simulate(_FakeLedgerApi(hang)) == _INCONCLUSIVE
        assert not contract_module._inflight_calls
        assert not hang.started.is_set()
        assert _simulate(_FakeLedgerApi(lambda: b"")) == _OK

    def test_slot_is_reusable_after_a_hung_call_ends(self, hang: _Hang) -> None:
        """A slot held by a hung call is returned once that call finishes."""
        for index in range(MAX_INFLIGHT_SIMULATIONS):
            _simulate(_FakeLedgerApi(hang), data=_calldata(index))
        hang.release.set()

        deadline = time.monotonic() + _RELEASE_WAIT_SECONDS
        result = _INCONCLUSIVE
        while result != _OK and time.monotonic() < deadline:
            result = _simulate(_FakeLedgerApi(lambda: b""))
        assert result == _OK

    def test_same_call_in_flight_is_inconclusive_without_calling(
        self, hang: _Hang
    ) -> None:
        """A call still running from an earlier simulation is not started again."""
        assert _simulate(_FakeLedgerApi(hang)) == _INCONCLUSIVE

        repeat = _FakeLedgerApi(lambda: b"")
        begin = time.monotonic()
        result = _simulate(repeat, deadline=_RELEASE_WAIT_SECONDS)
        elapsed = time.monotonic() - begin

        assert result == _INCONCLUSIVE
        assert repeat.api.eth.calls == 0
        assert elapsed < _PROMPT_RETURN_SECONDS

    def test_other_calls_run_while_one_is_in_flight(self, hang: _Hang) -> None:
        """Only the same call is held back; different calldata still simulates."""
        _simulate(_FakeLedgerApi(hang), data=_calldata(0))
        assert _simulate(_FakeLedgerApi(lambda: b""), data=_calldata(1)) == _OK

    def test_same_call_runs_again_once_the_earlier_one_ends(self, hang: _Hang) -> None:
        """The in-flight mark is cleared when the earlier call returns."""
        _simulate(_FakeLedgerApi(hang))
        hang.release.set()

        deadline = time.monotonic() + _RELEASE_WAIT_SECONDS
        result = _INCONCLUSIVE
        while result != _OK and time.monotonic() < deadline:
            result = _simulate(_FakeLedgerApi(lambda: b""))
        assert result == _OK


def test_default_deadline_fits_a_retried_ledger_request() -> None:
    """The default deadline outlasts two request attempts of the ledger connection.

    A shorter deadline fires together with the first attempt's timeout, so a
    request that stalls once is reported inconclusive before its retry runs.
    """
    with open(_LEDGER_CONNECTION_YAML, encoding="utf-8") as f:
        config = yaml.safe_load(f)["config"]
    request_timeouts = [
        api["timeout"] for api in config["ledger_apis"].values() if "timeout" in api
    ]
    assert request_timeouts
    assert SIMULATION_RPC_DEADLINE_SECONDS > 2 * max(request_timeouts)


class TestDeliverDataCarriesTheVerdict:
    """The deliver-data callables return the simulation verdict with the calldata."""

    def test_simulate_tx_keeps_its_data_key(self) -> None:
        """``simulate_tx`` still reports ``simulation_ok`` under ``data``."""
        ledger = _FakeLedgerApi(lambda: b"")
        result = OlasMechContract.simulate_tx(ledger, _MECH, _SENDER, "0x")  # type: ignore[arg-type]
        assert result == {"data": True, SIMULATION_TIMED_OUT_KEY: False}

    def test_marketplace_deliver_data_honours_the_deadline(self, hang: _Hang) -> None:
        """The deadline argument bounds the marketplace deliver simulation."""
        instance = SimpleNamespace(encode_abi=lambda **_kwargs: "0xabcd")
        begin = time.monotonic()
        with patch.object(OlasMechContract, "get_instance", return_value=instance):
            result = OlasMechContract.get_marketplace_deliver_data(
                _FakeLedgerApi(hang),  # type: ignore[arg-type]
                _MECH,
                _SENDER,
                requestIds=[],
                datas=[],
                deadline_seconds=_SHORT_DEADLINE,
            )
        elapsed = time.monotonic() - begin

        assert result == {"data": b"\xab\xcd", **_INCONCLUSIVE}
        assert elapsed < _PROMPT_RETURN_SECONDS


_REQUESTER = "0x3e45c17F8bd7F07f1e0e25C95389956e93eD663f"


class _ChecksummingApi(_FakeApi):
    """``_FakeApi`` whose address helper really checksums, as ``web3`` does."""

    @staticmethod
    def to_checksum_address(address: str) -> str:
        """Return the EIP-55 form of ``address``."""
        return str(Web3.to_checksum_address(address))


class TestOffchainDeliverDataRequesterCase:
    """The off-chain deliver calldata is built whatever case the stored requester has."""

    @staticmethod
    def _mech_instance() -> object:
        abi = json.loads(
            (
                Path(contract_module.__file__).parent / "build" / "AgentMech.json"
            ).read_text()
        )["abi"]
        return Web3().eth.contract(address=Web3.to_checksum_address(_MECH), abi=abi)

    @pytest.mark.parametrize(
        "requester",
        [_REQUESTER, _REQUESTER.lower(), _REQUESTER.upper().replace("0X", "0x")],
    )
    def test_requester_case_does_not_change_the_calldata(self, requester: str) -> None:
        """Lowercase, uppercase and checksum spellings encode to the same calldata."""
        instance = self._mech_instance()
        ledger = _FakeLedgerApi(lambda: b"")
        ledger.api = _ChecksummingApi(lambda: b"")
        with patch.object(OlasMechContract, "get_instance", return_value=instance):
            result = OlasMechContract.get_offchain_deliver_data(
                ledger,  # type: ignore[arg-type]
                _MECH,
                _SENDER,
                requester=requester,
                deliverWithSignatures=[],
                deliveryRates=[],
                paymentData=b"",
                deadline_seconds=_SHORT_DEADLINE,
            )
        expected = instance.encode_abi(  # type: ignore[attr-defined]
            abi_element_identifier="deliverMarketplaceWithSignatures",
            args=[_REQUESTER, [], [], b""],
        )
        assert result["data"] == bytes.fromhex(expected[2:])
        assert result[SIMULATION_OK_KEY] is True
