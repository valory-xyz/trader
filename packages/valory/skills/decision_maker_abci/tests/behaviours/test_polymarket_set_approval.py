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

"""Tests for PolymarketSetApprovalBehaviour."""

import json
import random
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Generator, List, Optional, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from web3 import Web3

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (
    PolymarketSetApprovalBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketSetApprovalPayload,
)
from packages.valory.skills.decision_maker_abci.states.check_benchmarking import (
    POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
)
from packages.valory.skills.decision_maker_abci.tests.polymarket_approvals import (
    APPROVE,
    SET_APPROVAL_FOR_ALL,
    decode,
    docs_addresses,
)

RANDOM_SEED = 20260503
RANDOM_CASES = 250

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():  # type: ignore[no-untyped-def]
    """A no-op generator that yields once."""
    yield  # type: ignore[no-untyped-def]


def _return_gen(value):  # type: ignore[no-untyped-def]
    """A generator that yields once and returns a value."""
    yield  # type: ignore[no-untyped-def]
    return value


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a PolymarketSetApprovalBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketSetApprovalBehaviour)  # type: ignore[no-untyped-def]
    behaviour.buy_amount = 0
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


def _run_async_act(store: Path, builder_program_enabled: bool) -> Tuple[bool, Any, int]:
    """Run ``async_act`` against ``store`` and report what the Safe path did.

    The DepositWallet provisioning is stubbed out; the Safe path runs for real
    up to the connection request (relayer path) or up to the multisend
    encoding (multisend path).

    :param store: the store directory.
    :param builder_program_enabled: whether the relayer path is used.
    :return: whether any Safe approval was sent or built, the payload handed
        to ``finish_behaviour`` and how often the DepositWallet was provisioned.
    """
    behaviour = _make_behaviour()
    context = behaviour.__dict__["_context"]
    context.params = SimpleNamespace(
        store_path=store,
        mech_chain_id="polygon",
        polymarket_builder_program_enabled=builder_program_enabled,
        **docs_addresses(),
    )
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    provisioned: List[bool] = []
    requests: List[Any] = []
    multisends: List[bool] = []
    payloads: List[Any] = []

    def _provision() -> Generator[None, None, None]:
        provisioned.append(True)
        yield

    def _request(message: Any, dialogue: Any) -> Generator[None, None, Any]:
        requests.append(message)
        yield
        response = MagicMock()
        response.error = None
        response.payload = json.dumps({"transactionID": "safe-tx"})
        return response

    def _build_multisend_data() -> Generator[None, None, bool]:
        multisends.append(True)
        yield
        return True

    def _finish(payload: Any) -> Generator[None, None, None]:
        payloads.append(payload)
        yield

    behaviour._provision_deposit_wallet = _provision  # type: ignore[method-assign]
    behaviour.do_connection_request = _request  # type: ignore[method-assign, assignment]
    behaviour._build_multisend_data = _build_multisend_data  # type: ignore[method-assign]
    behaviour._build_multisend_safe_tx_hash = lambda: _return_gen(True)  # type: ignore[method-assign]
    behaviour.finish_behaviour = _finish  # type: ignore[method-assign]
    with patch.object(type(behaviour), "tx_hex", new_callable=PropertyMock) as tx_hex:
        tx_hex.return_value = "0xsafetx"
        gen = behaviour.async_act()
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

    set_approval_requests = [
        call
        for call in context.srr_dialogues.create.call_args_list
        if json.loads(call.kwargs["payload"])["request_type"]
        == RequestType.SET_APPROVAL.value
    ]
    sent = bool(
        requests or set_approval_requests or multisends or behaviour.multisend_batches
    )
    assert len(payloads) == 1
    return sent, payloads[0], len(provisioned)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolymarketSetApprovalBehaviour:
    """Tests for PolymarketSetApprovalBehaviour."""

    def test_init(self) -> None:
        """__init__ should set buy_amount to 0."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.base.DecisionMakerBaseBehaviour.__init__",
            return_value=None,
        ):
            behaviour = PolymarketSetApprovalBehaviour(
                name="test", skill_context=MagicMock()
            )
            assert behaviour.buy_amount == 0

    def test_build_erc20_approve_data(self) -> None:
        """_build_erc20_approve_data encodes the spender and amount it is given.

        Fixed seed, 250 random spenders and amounts (including zero and
        ``2**256 - 1``): each call decodes back to ``approve(spender,
        amount)``.
        """
        behaviour = _make_behaviour()
        result = behaviour._build_erc20_approve_data(
            "0x1234567890123456789012345678901234567890", 100
        )
        assert result.startswith("0x095ea7b3")
        # Should contain the spender address padded to 32 bytes
        assert "1234567890123456789012345678901234567890" in result.lower()

        rng = random.Random(RANDOM_SEED)  # nosec B311
        amounts = [0, 1, 2**256 - 1] + [
            rng.getrandbits(rng.randint(1, 256)) for _ in range(RANDOM_CASES - 3)
        ]
        for amount in amounts:
            spender = Web3.to_checksum_address(f"0x{rng.getrandbits(160):040x}")
            data = behaviour._build_erc20_approve_data(spender, amount)
            assert decode(spender, data, 0)[1:4] == (APPROVE, spender, amount)

    def test_build_erc20_approve_data_max_uint(self) -> None:
        """_build_erc20_approve_data should handle max uint256."""
        behaviour = _make_behaviour()
        max_uint = 2**256 - 1
        result = behaviour._build_erc20_approve_data(
            "0x1234567890123456789012345678901234567890", max_uint
        )
        assert result.startswith("0x095ea7b3")
        # Max uint256 should be all f's
        assert "f" * 64 in result.lower()

    def test_build_set_approval_for_all_data_approved(self) -> None:
        """_build_set_approval_for_all_data encodes the operator and flag it is given.

        Fixed seed, 250 random operators and flags: each call decodes back to
        ``setApprovalForAll(operator, approved)``.
        """
        behaviour = _make_behaviour()
        result = behaviour._build_set_approval_for_all_data(
            "0x1234567890123456789012345678901234567890", True
        )
        assert result.startswith("0xa22cb465")
        # Approved=True should end with ...0001 padded
        assert result.endswith("0" * 63 + "1")

        rng = random.Random(RANDOM_SEED + 1)  # nosec B311
        for case in range(RANDOM_CASES):
            operator = Web3.to_checksum_address(f"0x{rng.getrandbits(160):040x}")
            approved = case % 2 == 0
            data = behaviour._build_set_approval_for_all_data(operator, approved)
            assert decode(operator, data, 0)[1:4] == (
                SET_APPROVAL_FOR_ALL,
                operator,
                int(approved),
            )

    def test_build_set_approval_for_all_data_not_approved(self) -> None:
        """_build_set_approval_for_all_data should generate correct data for approved=False."""
        behaviour = _make_behaviour()
        result = behaviour._build_set_approval_for_all_data(
            "0x1234567890123456789012345678901234567890", False
        )
        assert result.startswith("0xa22cb465")
        assert result.endswith("0" * 64)

    def test_async_act_builder_program_disabled(self, tmp_path: Path) -> None:
        """When builder program is disabled, should prepare approval transaction.

        :param tmp_path: a store directory without an allowances file.
        """
        behaviour = _make_behaviour()
        behaviour.__dict__["_context"].params.store_path = tmp_path

        payloads_sent = []

        def mock_prepare() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock prepare approval tx."""
            yield  # type: ignore[no-untyped-def]
            return "0xhash"

        behaviour._prepare_approval_tx = mock_prepare  # type: ignore[method-assign]
        behaviour._provision_deposit_wallet = lambda: (yield)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(store_path=tmp_path)

            behaviour.__dict__["_context"].params.polymarket_builder_program_enabled = (
                False
            )

            behaviour.send_a2a_transaction = lambda payload: (yield)  # type: ignore[method-assign]
            behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[method-assign]
            behaviour.set_done = MagicMock()  # type: ignore[method-assign]

            # Capture payload
            def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
                """Capture finish behaviour payload."""
                payloads_sent.append(payload)  # type: ignore[no-untyped-def]
                yield

            behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PolymarketSetApprovalPayload)

    def test_async_act_builder_program_enabled(self, tmp_path: Path) -> None:
        """When builder program is enabled, should call _set_approval.

        :param tmp_path: a store directory without an allowances file.
        """
        behaviour = _make_behaviour()
        behaviour.__dict__["_context"].params.store_path = tmp_path

        set_approval_called = []

        def mock_set_approval() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock set approval."""
            set_approval_called.append(True)  # type: ignore[no-untyped-def]
            behaviour.payload = PolymarketSetApprovalPayload(
                "test_agent", None, None, False
            )
            yield

        behaviour._set_approval = mock_set_approval  # type: ignore[method-assign]
        behaviour._provision_deposit_wallet = lambda: (yield)  # type: ignore[method-assign]

        behaviour.__dict__["_context"].params.polymarket_builder_program_enabled = True

        payloads_sent = []

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        gen = behaviour.async_act()
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        assert len(set_approval_called) == 1
        assert len(payloads_sent) == 1

    @pytest.mark.parametrize(
        "builder_program_enabled", [True, False], ids=["relayer", "multisend"]
    )
    def test_async_act_skips_safe_approvals_when_allowances_current(
        self, tmp_path: Path, builder_program_enabled: bool
    ) -> None:
        """A current allowances file skips the Safe approvals, nothing else does.

        The DepositWallet is provisioned on every pass. With ``polymarket.json``
        recording ``allowances_set: true`` under the current stamp, no
        ``SET_APPROVAL`` request is sent and no Safe multisend is built, and the
        payload carries no transaction. A missing, unreadable, stale-stamp,
        unstamped or ``allowances_set: false`` file keeps sending the Safe
        approvals.

        :param tmp_path: the parent of each scenario's store directory.
        :param builder_program_enabled: whether the relayer path is used.
        """
        current = {
            "allowances_set": True,
            "clob_version": POLYMARKET_ALLOWANCES_FILE_CLOB_VERSION,
        }
        scenarios: Dict[str, Optional[str]] = {
            "current": json.dumps(current),
            "missing": None,
            "unreadable": "not valid json",
            "stale_stamp": json.dumps({**current, "clob_version": "v4"}),
            "unstamped": json.dumps({"allowances_set": True}),
            "not_set": json.dumps({**current, "allowances_set": False}),
        }
        safe_sent = {}
        for name, content in scenarios.items():
            store = tmp_path / name
            store.mkdir()
            if content is not None:
                (store / "polymarket.json").write_text(content)
            sent, payload, provisioned = _run_async_act(store, builder_program_enabled)
            assert provisioned == 1, name
            safe_sent[name] = sent
            if not sent:
                assert (
                    payload.tx_submitter,
                    payload.tx_hash,
                    payload.mocking_mode,
                ) == (
                    None,
                    None,
                    False,
                ), name

        assert safe_sent == {
            "current": False,
            "missing": True,
            "unreadable": True,
            "stale_stamp": True,
            "unstamped": True,
            "not_set": True,
        }

    def test_set_approval_success(self) -> None:
        """_set_approval should handle successful response."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.error = None
        response.payload = json.dumps({"tx_hash": "0xabc"})

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or response)  # type: ignore[method-assign]

        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval.SrrDialogues"
        ):
            with patch.object(
                type(behaviour), "context", new_callable=PropertyMock
            ) as mock_ctx:
                ctx = MagicMock()
                ctx.agent_address = "test_agent"
                ctx.srr_dialogues = MagicMock()
                ctx.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
                mock_ctx.return_value = ctx

                gen = behaviour._set_approval()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert isinstance(behaviour.payload, PolymarketSetApprovalPayload)

    def test_set_approval_error_response(self) -> None:
        """_set_approval should handle error response."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.error = "Connection failed"
        response.payload = None

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or response)  # type: ignore[method-assign]

        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval.SrrDialogues"
        ):
            with patch.object(
                type(behaviour), "context", new_callable=PropertyMock
            ) as mock_ctx:
                ctx = MagicMock()
                ctx.agent_address = "test_agent"
                ctx.srr_dialogues = MagicMock()
                ctx.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
                mock_ctx.return_value = ctx

                gen = behaviour._set_approval()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert isinstance(behaviour.payload, PolymarketSetApprovalPayload)

    def test_set_approval_none_response(self) -> None:
        """_set_approval should handle None response."""
        behaviour = _make_behaviour()

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or None)  # type: ignore[method-assign]

        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval.SrrDialogues"
        ):
            with patch.object(
                type(behaviour), "context", new_callable=PropertyMock
            ) as mock_ctx:
                ctx = MagicMock()
                ctx.agent_address = "test_agent"
                ctx.srr_dialogues = MagicMock()
                ctx.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
                mock_ctx.return_value = ctx

                gen = behaviour._set_approval()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert isinstance(behaviour.payload, PolymarketSetApprovalPayload)

    def test_set_approval_response_json_null(self) -> None:
        """_set_approval should handle response where payload parses to null."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.error = None
        response.payload = json.dumps(None)  # parses to None -> success is False

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or response)  # type: ignore[method-assign]

        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval.SrrDialogues"
        ):
            with patch.object(
                type(behaviour), "context", new_callable=PropertyMock
            ) as mock_ctx:
                ctx = MagicMock()
                ctx.agent_address = "test_agent"
                ctx.srr_dialogues = MagicMock()
                ctx.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
                mock_ctx.return_value = ctx

                gen = behaviour._set_approval()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert isinstance(behaviour.payload, PolymarketSetApprovalPayload)
        # Should have logged the error (line 131)
        ctx.logger.error.assert_called()

    def test_prepare_approval_tx_success(self) -> None:
        """_prepare_approval_tx should build 9 batches and return tx_hex on success."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_exchange_address="0x3234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_exchange_address="0x4234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x5234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
                polymarket_exchange_v3_address="0x8234567890123456789012345678901234567890",
                polymarket_position_manager_address="0x9234567890123456789012345678901234567890",
                polymarket_router_address="0xa234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_approval_tx()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result == "0xfinalHash"
        # 9 batches: 3 collateral approves for the v2 CTF Exchange + NegRisk
        # CTF Exchange + NegRisk Adapter, 3 CTF setApprovalForAll for the
        # same, 2 CTF setApprovalForAll for CtfCollateralAdapter and
        # NegRiskCtfCollateralAdapter, plus the PositionManager
        # setApprovalForAll for the Router (claims V2 winnings). The
        # collateral adapters intentionally receive no pUSD allowance - their
        # redeem path doesn't pull ERC-20 from the Safe.
        assert len(behaviour.multisend_batches) == 9

    def test_prepare_approval_tx_includes_ctf_collateral_adapter_approval(self) -> None:
        """The redeem-critical CTF setApprovalForAll(CtfCollateralAdapter, true) must be in the batch."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        ctf = "0x2234567890123456789012345678901234567890"
        ctf_collateral_adapter = "0x6234567890123456789012345678901234567890"
        neg_risk_ctf_collateral_adapter = "0x7234567890123456789012345678901234567890"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address=ctf,
                polymarket_ctf_exchange_address="0x3234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_exchange_address="0x4234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x5234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address=ctf_collateral_adapter,
                polymarket_neg_risk_ctf_collateral_adapter_address=neg_risk_ctf_collateral_adapter,
                polymarket_exchange_v3_address="0x8234567890123456789012345678901234567890",
                polymarket_position_manager_address="0x9234567890123456789012345678901234567890",
                polymarket_router_address="0xa234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_approval_tx()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        # Find the CTF setApprovalForAll(CtfCollateralAdapter) entry. Selector
        # 0xa22cb465 is setApprovalForAll(address,bool); the operator address
        # appears in the second parameter slot.
        ctf_approve_adapter_entries = [
            b
            for b in behaviour.multisend_batches
            if b.to.lower() == ctf.lower()
            and b.data.hex().startswith("a22cb465")
            and ctf_collateral_adapter[2:].lower() in b.data.hex().lower()
        ]
        assert len(ctf_approve_adapter_entries) == 1

        ctf_approve_neg_risk_adapter_entries = [
            b
            for b in behaviour.multisend_batches
            if b.to.lower() == ctf.lower()
            and b.data.hex().startswith("a22cb465")
            and neg_risk_ctf_collateral_adapter[2:].lower() in b.data.hex().lower()
        ]
        assert len(ctf_approve_neg_risk_adapter_entries) == 1

    def test_prepare_approval_tx_excludes_collateral_allowance_for_adapters(
        self,
    ) -> None:
        """No ERC-20 approve(adapter, *) is included for either collateral adapter.

        The collateral adapters' redeem path doesn't pull ERC-20 from the
        Safe, so granting them a pUSD allowance is a needless
        attack-surface expansion. This test guards against the prior
        behaviour creeping back in.
        """
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        collateral = "0x1234567890123456789012345678901234567890"
        ctf_collateral_adapter = "0x6234567890123456789012345678901234567890"
        neg_risk_ctf_collateral_adapter = "0x7234567890123456789012345678901234567890"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address=collateral,
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_exchange_address="0x3234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_exchange_address="0x4234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x5234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address=ctf_collateral_adapter,
                polymarket_neg_risk_ctf_collateral_adapter_address=neg_risk_ctf_collateral_adapter,
                polymarket_exchange_v3_address="0x8234567890123456789012345678901234567890",
                polymarket_position_manager_address="0x9234567890123456789012345678901234567890",
                polymarket_router_address="0xa234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_approval_tx()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        # ERC20 approve selector is 0x095ea7b3.
        for adapter in (ctf_collateral_adapter, neg_risk_ctf_collateral_adapter):
            entries = [
                b
                for b in behaviour.multisend_batches
                if b.to.lower() == collateral.lower()
                and b.data.hex().startswith("095ea7b3")
                and adapter[2:].lower() in b.data.hex().lower()
            ]
            assert (
                len(entries) == 0
            ), f"unexpected ERC20 approve(adapter={adapter}) on collateral"

    def test_prepare_approval_tx_multisend_data_fails(self) -> None:
        """_prepare_approval_tx should return empty string when _build_multisend_data fails."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_exchange_address="0x3234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_exchange_address="0x4234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x5234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
                polymarket_exchange_v3_address="0x8234567890123456789012345678901234567890",
                polymarket_position_manager_address="0x9234567890123456789012345678901234567890",
                polymarket_router_address="0xa234567890123456789012345678901234567890",
            )

            gen = behaviour._prepare_approval_tx()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == ""

    def test_prepare_approval_tx_safe_tx_hash_fails(self) -> None:
        """_prepare_approval_tx should return empty string when _build_multisend_safe_tx_hash fails."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data."""
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend safe tx hash that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_exchange_address="0x3234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_exchange_address="0x4234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x5234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
                polymarket_exchange_v3_address="0x8234567890123456789012345678901234567890",
                polymarket_position_manager_address="0x9234567890123456789012345678901234567890",
                polymarket_router_address="0xa234567890123456789012345678901234567890",
            )

            gen = behaviour._prepare_approval_tx()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == ""

    def test_finish_behaviour(self) -> None:
        """finish_behaviour should send transaction, wait for round end, and set done."""
        behaviour = _make_behaviour()

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        payload = PolymarketSetApprovalPayload("test_agent", None, None, False)

        gen = behaviour.finish_behaviour(payload)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0] is payload
        behaviour.set_done.assert_called_once()
