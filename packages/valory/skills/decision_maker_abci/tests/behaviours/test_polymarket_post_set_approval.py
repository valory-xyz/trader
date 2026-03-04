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

"""Tests for PolymarketPostSetApprovalBehaviour."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval import (
    PolymarketPostSetApprovalBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketPostSetApprovalPayload,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_post_set_approval import (
    PolymarketPostSetApprovalRound,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():  # type: ignore[no-untyped-def]
    """A no-op generator that yields once."""
    yield  # type: ignore[no-untyped-def]


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a PolymarketPostSetApprovalBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketPostSetApprovalBehaviour)  # type: ignore[no-untyped-def]
    behaviour.buy_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolymarketPostSetApprovalBehaviour:
    """Tests for PolymarketPostSetApprovalBehaviour."""

    def test_matching_round(self) -> None:
        """matching_round should be PolymarketPostSetApprovalRound."""
        assert (
            PolymarketPostSetApprovalBehaviour.matching_round
            == PolymarketPostSetApprovalRound
        )

    def test_init(self) -> None:
        """__init__ should set buy_amount to 0."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval.DecisionMakerBaseBehaviour.__init__",
            return_value=None,
        ):
            behaviour = PolymarketPostSetApprovalBehaviour(
                name="test", skill_context=MagicMock()
            )
            assert behaviour.buy_amount == 0

    def test_write_allowances_file_success(self) -> None:
        """_write_allowances_file should write correct JSON."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                behaviour._write_allowances_file(True)

            allowances_path = Path(tmpdir) / "polymarket.json"
            assert allowances_path.exists()
            with open(allowances_path) as f:
                data = json.load(f)
            assert data["allowances_set"] is True

    def test_write_allowances_file_false(self) -> None:
        """_write_allowances_file should write allowances_set=False."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                behaviour._write_allowances_file(False)

            allowances_path = Path(tmpdir) / "polymarket.json"
            with open(allowances_path) as f:
                data = json.load(f)
            assert data["allowances_set"] is False

    def test_write_allowances_file_error_logged(self) -> None:
        """_write_allowances_file should log error on exception."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(store_path=Path("/nonexistent/path"))
            behaviour._write_allowances_file(True)

        behaviour.__dict__["_context"].logger.error.assert_called()

    def test_check_approval_error_response(self) -> None:
        """_check_approval should handle error response."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.error = "Connection failed"
        response.payload = None

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(store_path=Path(tempfile.mkdtemp()))
            with patch(
                "packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval.SrrDialogues"
            ):
                mock_srr_instance = MagicMock()
                mock_srr_instance.create.return_value = (MagicMock(), MagicMock())

                with patch.object(
                    type(behaviour), "context", new_callable=PropertyMock
                ) as mock_ctx:
                    ctx = MagicMock()
                    ctx.agent_address = "test_agent"
                    ctx.srr_dialogues = mock_srr_instance
                    mock_ctx.return_value = ctx

                    gen = behaviour._check_approval()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert isinstance(behaviour.payload, PolymarketPostSetApprovalPayload)
        assert behaviour.payload.vote is False

    def test_check_approval_none_response(self) -> None:
        """_check_approval should handle None response."""
        behaviour = _make_behaviour()

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or None)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(store_path=Path(tempfile.mkdtemp()))
            with patch(
                "packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval.SrrDialogues"
            ):
                with patch.object(
                    type(behaviour), "context", new_callable=PropertyMock
                ) as mock_ctx:
                    ctx = MagicMock()
                    ctx.agent_address = "test_agent"
                    ctx.srr_dialogues = MagicMock()
                    ctx.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
                    mock_ctx.return_value = ctx

                    gen = behaviour._check_approval()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert isinstance(behaviour.payload, PolymarketPostSetApprovalPayload)
        assert behaviour.payload.vote is False

    def test_check_approval_success(self) -> None:
        """_check_approval should handle successful approval."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.error = None
        response.payload = json.dumps(
            {
                "all_approvals_set": True,
                "usdc_allowances": {},
                "ctf_approvals": {},
            }
        )

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(store_path=Path(tempfile.mkdtemp()))
            with patch(
                "packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval.SrrDialogues"
            ):
                mock_srr_instance = MagicMock()
                mock_srr_instance.create.return_value = (MagicMock(), MagicMock())

                with patch.object(
                    type(behaviour), "context", new_callable=PropertyMock
                ) as mock_ctx:
                    ctx = MagicMock()
                    ctx.agent_address = "test_agent"
                    ctx.srr_dialogues = mock_srr_instance
                    mock_ctx.return_value = ctx

                    gen = behaviour._check_approval()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert isinstance(behaviour.payload, PolymarketPostSetApprovalPayload)
        assert behaviour.payload.vote is True

    def test_check_approval_not_all_set(self) -> None:
        """_check_approval should handle when not all approvals are set."""
        behaviour = _make_behaviour()

        response = MagicMock()
        response.error = None
        response.payload = json.dumps(
            {
                "all_approvals_set": False,
                "usdc_allowances": {},
                "ctf_approvals": {},
            }
        )

        behaviour.do_connection_request = lambda msg, dlg: ((yield) or response)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(store_path=Path(tempfile.mkdtemp()))
            with patch(
                "packages.valory.skills.decision_maker_abci.behaviours.polymarket_post_set_approval.SrrDialogues"
            ):
                with patch.object(
                    type(behaviour), "context", new_callable=PropertyMock
                ) as mock_ctx:
                    ctx = MagicMock()
                    ctx.agent_address = "test_agent"
                    ctx.srr_dialogues = MagicMock()
                    ctx.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
                    mock_ctx.return_value = ctx

                    gen = behaviour._check_approval()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert isinstance(behaviour.payload, PolymarketPostSetApprovalPayload)
        assert behaviour.payload.vote is False

    def test_async_act(self) -> None:
        """async_act should call _check_approval and finish_behaviour."""
        behaviour = _make_behaviour()

        payloads_sent = []

        def mock_check_approval() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock check approval."""
            behaviour.payload = PolymarketPostSetApprovalPayload("test_agent", True)  # type: ignore[no-untyped-def]
            yield

        behaviour._check_approval = mock_check_approval  # type: ignore[method-assign]

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
        assert isinstance(payloads_sent[0], PolymarketPostSetApprovalPayload)

    def test_finish_behaviour(self) -> None:
        """finish_behaviour should send transaction, wait, and set done."""
        behaviour = _make_behaviour()

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        payload = PolymarketPostSetApprovalPayload("test_agent", True)

        gen = behaviour.finish_behaviour(payload)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        assert len(payloads_sent) == 1
        behaviour.set_done.assert_called_once()
