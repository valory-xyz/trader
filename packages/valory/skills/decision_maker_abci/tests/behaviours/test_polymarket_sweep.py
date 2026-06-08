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

"""Tests for PolymarketSweepBehaviour."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_sweep import (
    PolymarketSweepBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.base import Event


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a PolymarketSweepBehaviour with mocked context."""
    behaviour = object.__new__(PolymarketSweepBehaviour)
    context = MagicMock()
    context.agent_address = "agent"
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    behaviour.__dict__["_context"] = context
    return behaviour


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
    """A synchronized_data mock exposing a DepositWallet address."""
    m = MagicMock()
    m.deposit_wallet_address = dw
    return m


class TestPolymarketSweepBehaviour:
    """Tests for PolymarketSweepBehaviour."""

    def test_sweep_success_emits_done(self) -> None:
        """A successful sweep emits the DONE event."""
        behaviour = _make_behaviour()
        response = MagicMock()
        response.error = None
        response.payload = json.dumps({"swept": True, "amount": 100})
        behaviour.do_connection_request = lambda m, d: ((yield) or response)  # type: ignore[method-assign]
        with patch.object(
            PolymarketSweepBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced("0xDW"),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.DONE.value

    def test_sweep_failure_emits_none(self) -> None:
        """A failed sweep (no response) emits the NONE event (loop)."""
        behaviour = _make_behaviour()
        behaviour.do_connection_request = lambda m, d: ((yield) or None)  # type: ignore[method-assign]
        with patch.object(
            PolymarketSweepBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced("0xDW"),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.NONE.value

    def test_sweep_error_response_emits_none(self) -> None:
        """An error response emits the NONE event."""
        behaviour = _make_behaviour()
        response = MagicMock()
        response.error = "boom"
        behaviour.do_connection_request = lambda m, d: ((yield) or response)  # type: ignore[method-assign]
        with patch.object(
            PolymarketSweepBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced("0xDW"),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.NONE.value

    def test_position_token_ids_from_sampled_bet(self) -> None:
        """Outcome token ids of the sampled bet are returned as ints to sweep."""
        behaviour = _make_behaviour()
        bet = MagicMock()
        bet.outcome_token_ids = {"Yes": "123", "No": "456"}
        with patch.object(
            PolymarketSweepBehaviour,
            "sampled_bet",
            new_callable=PropertyMock,
            return_value=bet,
        ):
            assert behaviour._position_token_ids() == [123, 456]

    def test_position_token_ids_skips_non_int(self) -> None:
        """Non-integer token ids are skipped rather than raising."""
        behaviour = _make_behaviour()
        bet = MagicMock()
        bet.outcome_token_ids = {"Yes": "123", "No": None}
        with patch.object(
            PolymarketSweepBehaviour,
            "sampled_bet",
            new_callable=PropertyMock,
            return_value=bet,
        ):
            assert behaviour._position_token_ids() == [123]
