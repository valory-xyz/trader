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
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval import (
    PolymarketSetApprovalBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketSetApprovalPayload,
)

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolymarketSetApprovalBehaviour:
    """Tests for PolymarketSetApprovalBehaviour."""

    def test_init(self) -> None:
        """__init__ should set buy_amount to 0."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_set_approval.DecisionMakerBaseBehaviour.__init__",
            return_value=None,
        ):
            behaviour = PolymarketSetApprovalBehaviour(
                name="test", skill_context=MagicMock()
            )
            assert behaviour.buy_amount == 0

    def test_build_erc20_approve_data(self) -> None:
        """_build_erc20_approve_data should generate correct function data."""
        behaviour = _make_behaviour()
        result = behaviour._build_erc20_approve_data(
            "0x1234567890123456789012345678901234567890", 100
        )
        assert result.startswith("0x095ea7b3")
        # Should contain the spender address padded to 32 bytes
        assert "1234567890123456789012345678901234567890" in result.lower()

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
        """_build_set_approval_for_all_data should generate correct data for approved=True."""
        behaviour = _make_behaviour()
        result = behaviour._build_set_approval_for_all_data(
            "0x1234567890123456789012345678901234567890", True
        )
        assert result.startswith("0xa22cb465")
        # Approved=True should end with ...0001 padded
        assert result.endswith("0" * 63 + "1")

    def test_build_set_approval_for_all_data_not_approved(self) -> None:
        """_build_set_approval_for_all_data should generate correct data for approved=False."""
        behaviour = _make_behaviour()
        result = behaviour._build_set_approval_for_all_data(
            "0x1234567890123456789012345678901234567890", False
        )
        assert result.startswith("0xa22cb465")
        assert result.endswith("0" * 64)

    def test_async_act_builder_program_disabled(self) -> None:
        """When builder program is disabled, should prepare approval transaction."""
        behaviour = _make_behaviour()

        payloads_sent = []

        def mock_prepare() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock prepare approval tx."""
            yield  # type: ignore[no-untyped-def]
            return "0xhash"

        behaviour._prepare_approval_tx = mock_prepare  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock()

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

    def test_async_act_builder_program_enabled(self) -> None:
        """When builder program is enabled, should call _set_approval."""
        behaviour = _make_behaviour()

        set_approval_called = []

        def mock_set_approval() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock set approval."""
            set_approval_called.append(True)  # type: ignore[no-untyped-def]
            behaviour.payload = PolymarketSetApprovalPayload(
                "test_agent", None, None, False
            )
            yield

        behaviour._set_approval = mock_set_approval  # type: ignore[method-assign]

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
        """_prepare_approval_tx should build 6 batches and return tx_hex on success."""
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
        # Should have 6 batches: 3 USDC approves + 3 CTF setApprovalForAll
        assert len(behaviour.multisend_batches) == 6

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
