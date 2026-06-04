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

"""Tests for the DepositWallet top-up and withdrawal-top-up rounds."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_top_up import (
    PolymarketTopUpRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_withdraw_top_up import (
    PolymarketWithdrawTopUpRound,
)

DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
SUPER = (
    "packages.valory.skills.decision_maker_abci.states."
    "polymarket_top_up.TxPreparationRound.end_block"
)


def _round(cls):  # type: ignore[no-untyped-def]
    """Build a round instance without running the full constructor."""
    r = object.__new__(cls)
    r.context = MagicMock()
    return r


def _values(event):  # type: ignore[no-untyped-def]
    """Build a payload-values tuple: (tx_submitter, tx_hash, mocking, event)."""
    return (None, None, False, event)


class TestPolymarketTopUpRoundEndBlock:
    """Tests for PolymarketTopUpRound.end_block."""

    def test_returns_none_when_super_none(self) -> None:
        """end_block returns None when the base round is still running."""
        r = _round(PolymarketTopUpRound)
        with patch(SUPER, return_value=None):
            assert r.end_block() is None

    def test_no_majority_passthrough(self) -> None:
        """A NO_MAJORITY result is returned unchanged (no event switch)."""
        r = _round(PolymarketTopUpRound)
        synced = MagicMock()
        with patch(SUPER, return_value=(synced, Event.NO_MAJORITY)):
            out = r.end_block()
        assert out == (synced, Event.NO_MAJORITY)

    def test_emits_payload_event(self) -> None:
        """The payload-carried event is emitted (DW is not persisted/threaded)."""
        r = _round(PolymarketTopUpRound)
        synced = MagicMock(spec=SynchronizedData)
        synced.update.return_value = synced
        with (
            patch(SUPER, return_value=(synced, Event.DONE)),
            patch.object(
                PolymarketTopUpRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=_values(Event.PREPARE_TX.value),
            ),
        ):
            out_synced, event = r.end_block()
        assert event == Event.PREPARE_TX
        assert out_synced is synced
        for call in synced.update.call_args_list:
            assert "deposit_wallet_address" not in call.kwargs

    def test_emits_insufficient_balance_event(self) -> None:
        """An INSUFFICIENT_BALANCE payload event is emitted unchanged."""
        r = _round(PolymarketTopUpRound)
        synced = MagicMock(spec=SynchronizedData)
        synced.update.return_value = synced
        with (
            patch(SUPER, return_value=(synced, Event.DONE)),
            patch.object(
                PolymarketTopUpRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=_values(Event.INSUFFICIENT_BALANCE.value),
            ),
        ):
            _out_synced, event = r.end_block()
        assert event == Event.INSUFFICIENT_BALANCE


class TestPolymarketWithdrawTopUpRound:
    """Tests for the withdrawal-top-up round (inherits top-up end_block)."""

    def test_is_subclass_with_none_event(self) -> None:
        """The withdrawal top-up loops on NONE rather than INSUFFICIENT_BALANCE."""
        assert issubclass(PolymarketWithdrawTopUpRound, PolymarketTopUpRound)
        assert PolymarketWithdrawTopUpRound.none_event == Event.NONE

    def test_emits_withdrawal_done(self) -> None:
        """A WITHDRAWAL_DONE payload event is emitted via the inherited end_block."""
        r = _round(PolymarketWithdrawTopUpRound)
        synced = MagicMock(spec=SynchronizedData)
        synced.update.return_value = synced
        with (
            patch(SUPER, return_value=(synced, Event.DONE)),
            patch.object(
                PolymarketWithdrawTopUpRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=_values(Event.WITHDRAWAL_DONE.value),
            ),
        ):
            _, event = r.end_block()
        assert event == Event.WITHDRAWAL_DONE
