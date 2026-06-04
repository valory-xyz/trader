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

"""Tests for the DepositWallet top-up / sweep payloads."""

import dataclasses

from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketSweepPayload,
    PolymarketTopUpPayload,
)


class TestPolymarketTopUpPayload:
    """Tests for PolymarketTopUpPayload."""

    def test_fields(self) -> None:
        """The payload carries the event dataclass field (no dw_address)."""
        names = {f.name for f in dataclasses.fields(PolymarketTopUpPayload)}
        assert "event" in names
        assert "dw_address" not in names

    def test_construction_and_data(self) -> None:
        """Event is part of the consensus data dict."""
        payload = PolymarketTopUpPayload(
            sender="agent",
            tx_submitter="round",
            tx_hash="0xhash",
            mocking_mode=False,
            event="prepare_tx",
        )
        assert payload.event == "prepare_tx"
        assert payload.data["event"] == "prepare_tx"

    def test_defaults_none(self) -> None:
        """Event defaults to None."""
        payload = PolymarketTopUpPayload(sender="agent")
        assert payload.event is None


class TestPolymarketSweepPayload:
    """Tests for PolymarketSweepPayload."""

    def test_fields(self) -> None:
        """The payload carries the event dataclass field (no dw_address)."""
        names = {f.name for f in dataclasses.fields(PolymarketSweepPayload)}
        assert "event" in names
        assert "dw_address" not in names

    def test_construction_and_data(self) -> None:
        """Event is part of the consensus data dict."""
        payload = PolymarketSweepPayload(
            sender="agent",
            event="done",
        )
        assert payload.data["event"] == "done"
