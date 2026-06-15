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

"""Tests for the DepositWallet funder/sweep additions in PolymarketWithdrawBehaviour."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_withdraw import (
    PolymarketWithdrawBehaviour,
)

DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a PolymarketWithdrawBehaviour with mocked context."""
    behaviour = object.__new__(PolymarketWithdrawBehaviour)
    context = MagicMock()
    context.agent_address = "agent"
    behaviour.__dict__["_context"] = context
    return behaviour


def _run(gen):  # type: ignore[no-untyped-def]
    """Drive a generator to completion, returning its value."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def _synced(dw):  # type: ignore[no-untyped-def]
    m = MagicMock()
    m.deposit_wallet_address = dw
    return m


class TestRequestSellFunder:
    """The sell request carries the DW funder."""

    def test_funder_added_when_dw_known(self) -> None:
        """When a DW is known, the sell params include funder=DW."""
        b = _make_behaviour()
        captured = {}

        def _send(payload):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            yield
            return {"order_id": "o", "status": "matched"}

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        b._extract_response_or_error = lambda r: (r, None)  # type: ignore[method-assign]
        b._resolve_deposit_wallet = lambda: DW  # type: ignore[method-assign]
        _run(b._request_sell("123", 2.0))
        assert captured["payload"]["params"]["funder"] == DW

    def test_no_funder_when_dw_absent(self) -> None:
        """When no DW is known, funder is omitted."""
        b = _make_behaviour()
        captured = {}

        def _send(payload):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            yield
            return {"order_id": "o", "status": "matched"}

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        b._extract_response_or_error = lambda r: (r, None)  # type: ignore[method-assign]
        with patch.object(
            PolymarketWithdrawBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(None),
        ):
            _run(b._request_sell("123", 2.0))
        assert "funder" not in captured["payload"]["params"]


class TestRequestFetchPositionsAddress:
    """The withdrawal position fetch targets the DepositWallet."""

    def test_address_added_when_dw_known(self) -> None:
        """When a DW is known, the fetch params query the DW address."""
        b = _make_behaviour()
        captured = {}

        def _send(payload):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            yield
            return []

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        b._resolve_deposit_wallet = lambda: DW  # type: ignore[method-assign]
        _run(b._request_fetch_positions())
        assert captured["payload"]["params"]["address"] == DW

    def test_no_address_when_dw_absent(self) -> None:
        """When no DW is known, the fetch omits the address override."""
        b = _make_behaviour()
        captured = {}

        def _send(payload):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            yield
            return []

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        with patch.object(
            PolymarketWithdrawBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(None),
        ):
            _run(b._request_fetch_positions())
        assert "address" not in captured["payload"]["params"]


class TestSweepDwToSafe:
    """The post-loop sweep back to the Safe."""

    def test_success_logs_info(self) -> None:
        """A successful sweep logs the result and forwards the token ids."""
        b = _make_behaviour()
        captured: dict = {}

        def _send(payload):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            yield
            return {"swept": True, "amount": 5}

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        b._resolve_deposit_wallet = lambda: DW  # type: ignore[method-assign]
        _run(b._sweep_dw_to_safe([42, 43]))
        b.context.logger.info.assert_called()
        assert captured["payload"]["params"]["token_ids"] == [42, 43]

    def test_default_token_ids_empty(self) -> None:
        """No token ids forwards an empty list (pUSD-only sweep)."""
        b = _make_behaviour()
        captured: dict = {}

        def _send(payload):  # type: ignore[no-untyped-def]
            captured["payload"] = payload
            yield
            return {"swept": False}

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        b._resolve_deposit_wallet = lambda: DW  # type: ignore[method-assign]
        _run(b._sweep_dw_to_safe())
        assert captured["payload"]["params"]["token_ids"] == []

    def test_unknown_dw_skips_dispatch(self) -> None:
        """An unknown DW address warns and skips the dispatch entirely."""
        b = _make_behaviour()
        called = []

        def _send(payload):  # type: ignore[no-untyped-def]
            called.append(payload)
            yield
            return None

        b.send_polymarket_connection_request = _send  # type: ignore[method-assign]
        with patch.object(
            PolymarketWithdrawBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(None),
        ):
            _run(b._sweep_dw_to_safe([42]))
        assert called == []
        b.context.logger.warning.assert_called()

    def test_sellable_token_ids_parses_and_skips(self) -> None:
        """Parseable asset ids are kept as ints; unparseable ones are skipped."""
        b = _make_behaviour()
        sellable = [
            {"asset": "42"},
            {"asset": None},
            {"asset": "notanint"},
            {},
            {"asset": "43"},
        ]
        assert b._sellable_token_ids(sellable) == [42, 43]

    def test_none_response_warns(self) -> None:
        """A missing sweep response logs a warning (non-fatal)."""
        b = _make_behaviour()
        b.send_polymarket_connection_request = lambda p: ((yield) or None)  # type: ignore[method-assign]
        b._resolve_deposit_wallet = lambda: DW  # type: ignore[method-assign]
        _run(b._sweep_dw_to_safe())
        b.context.logger.warning.assert_called()

    def test_error_response_warns(self) -> None:
        """An error sweep response logs a warning (non-fatal)."""
        b = _make_behaviour()
        b.send_polymarket_connection_request = lambda p: (  # type: ignore[method-assign]
            (yield) or {"error": "boom"}
        )
        b._resolve_deposit_wallet = lambda: DW  # type: ignore[method-assign]
        _run(b._sweep_dw_to_safe())
        b.context.logger.warning.assert_called()
