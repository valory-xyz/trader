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

"""Tests for the DepositWallet sweep round."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_sweep import (
    PolymarketSweepRound,
)

SUPER = (
    "packages.valory.skills.decision_maker_abci.states."
    "polymarket_sweep.TxPreparationRound.end_block"
)


def _round():  # type: ignore[no-untyped-def]
    """Build a sweep round instance."""
    r = object.__new__(PolymarketSweepRound)
    r.context = MagicMock()
    return r


def _values(event):  # type: ignore[no-untyped-def]
    """Payload-values tuple: (tx_submitter, tx_hash, mocking, event)."""
    return (None, None, False, event)


class TestPolymarketSweepRoundEndBlock:
    """Tests for PolymarketSweepRound.end_block."""

    def test_returns_none_when_super_none(self) -> None:
        """end_block returns None when the base round is still running."""
        r = _round()
        with patch(SUPER, return_value=None):
            assert r.end_block() is None

    def test_no_majority_passthrough(self) -> None:
        """A NO_MAJORITY result is returned unchanged."""
        r = _round()
        synced = MagicMock()
        with patch(SUPER, return_value=(synced, Event.NO_MAJORITY)):
            assert r.end_block() == (synced, Event.NO_MAJORITY)

    def test_emits_done(self) -> None:
        """A successful sweep emits DONE from the payload."""
        r = _round()
        synced = MagicMock()
        with (
            patch(SUPER, return_value=(synced, Event.DONE)),
            patch.object(
                PolymarketSweepRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=_values(Event.DONE.value),
            ),
        ):
            _, event = r.end_block()
        assert event == Event.DONE

    def test_emits_none_on_failure(self) -> None:
        """A failed sweep emits NONE (loop) from the payload."""
        r = _round()
        synced = MagicMock()
        with (
            patch(SUPER, return_value=(synced, Event.DONE)),
            patch.object(
                PolymarketSweepRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=_values(Event.NONE.value),
            ),
        ):
            _, event = r.end_block()
        assert event == Event.NONE
