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

"""Tests for PolymarketTopUpBehaviour."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    DEPOSIT_WALLET_STORE,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_top_up import (
    PUSD_UNITS,
    PolymarketTopUpBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.base import Event

COLLAT = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


def _make_behaviour(tmp_path, with_dw=True):  # type: ignore[no-untyped-def]
    """Return a PolymarketTopUpBehaviour with mocked context.

    When ``with_dw`` is set, a persisted ``deposit_wallet.json`` (owner-matched)
    is written so ``_resolve_deposit_wallet`` resolves the DW from the store.

    :param tmp_path: the temporary store directory.
    :param with_dw: whether to persist a ``deposit_wallet.json`` in the store.
    :return: the constructed behaviour.
    """
    behaviour = object.__new__(PolymarketTopUpBehaviour)
    behaviour.dw_address = None
    behaviour.multisend_batches = []
    context = MagicMock()
    context.agent_address = "agent"
    context.params.store_path = tmp_path
    context.params.polymarket_collateral_address = COLLAT
    context.srr_dialogues.create.return_value = (MagicMock(), MagicMock())
    behaviour.__dict__["_context"] = context
    if with_dw:
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent", "approvals_done": True})
        )
    return behaviour


def _ok():  # type: ignore[no-untyped-def]
    """A generator that yields once and returns True."""
    yield
    return True


def _fail():  # type: ignore[no-untyped-def]
    """A generator that yields once and returns False."""
    yield
    return False


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


def _run(gen):  # type: ignore[no-untyped-def]
    """Drive a generator helper to completion and return its value."""
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


def _synced(dw, bet_amount):  # type: ignore[no-untyped-def]
    """A synchronized_data mock."""
    m = MagicMock()
    m.deposit_wallet_address = dw
    m.bet_amount = bet_amount
    return m


def _resp(body):  # type: ignore[no-untyped-def]
    """A connection response object carrying a JSON payload."""
    r = MagicMock()
    r.error = None
    r.payload = json.dumps(body)
    return r


def _set_balance(behaviour, balance):  # type: ignore[no-untyped-def]
    """Stub the Safe pUSD balance check to a fixed value."""
    behaviour.token_balance = balance
    behaviour.wait_for_condition_with_sleep = lambda cond, **kw: _ok()  # type: ignore[method-assign]


class TestPolymarketTopUpBehaviour:
    """Tests for PolymarketTopUpBehaviour."""

    def test_prepare_tx_with_known_dw(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A known DW + positive buy amount + good multisend → PREPARE_TX."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(DW, 5_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value
        assert payload.tx_hash == "0xsafehash"

    def test_insufficient_safe_balance(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A Safe pUSD balance below the buy amount → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        _set_balance(behaviour, 1_000_000)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 5_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_non_positive_buy_amount_insufficient(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A non-positive buy amount → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 0),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_resolves_dw_via_persisted(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """With no synced DW, the persisted store file resolves it → PREPARE_TX."""
        behaviour = _make_behaviour(tmp_path)
        (tmp_path / DEPOSIT_WALLET_STORE).write_text(
            json.dumps({"dw_address": DW, "dw_owner": "agent", "approvals_done": True})
        )
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(None, 5_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value

    def test_unresolvable_dw_insufficient(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """No DW recorded (synced empty, no persisted file) → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path, with_dw=False)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(None, 5_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_tops_up_the_bet_plus_the_quoted_fee(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The transfer carries the fee, so the SDK will not carve it out.

        Funded with exactly the bet, the SDK sizes the order to ``bet - fee``:
        fewer shares than the strategy sized, and an outright rejection when
        the bet sits on the venue's $1 floor.
        """
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: (  # type: ignore[method-assign]
            (yield) or _resp({"fee_usd": 0.02, "blocked": True})
        )
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        behaviour._sampled_outcome_token_id = lambda: "token123"  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(DW, 1_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value
        # 1.0 pUSD + ceil(0.02 * 1.5 * 1e6) = 1_030_000 base units.
        transferred = int(behaviour.multisend_batches[0].data.hex()[-64:], 16)
        assert transferred == 1_030_000

    def test_fee_reserve_counts_against_the_safe_balance(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A Safe that covers the bet but not the fee defers rather than reverts."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: (  # type: ignore[method-assign]
            (yield) or _resp({"fee_usd": 0.02})
        )
        behaviour._sampled_outcome_token_id = lambda: "token123"  # type: ignore[method-assign]
        _set_balance(behaviour, 1_000_000)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 1_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value

    def test_no_fee_quoted_tops_up_the_bare_bet(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A fee-free market (or an unreadable quote) adds no reserve."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: (  # type: ignore[method-assign]
            (yield) or _resp({"fee_usd": None})
        )
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        behaviour._sampled_outcome_token_id = lambda: "token123"  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(DW, 1_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value
        transferred = int(behaviour.multisend_batches[0].data.hex()[-64:], 16)
        assert transferred == 1_000_000

    def test_unresolvable_token_id_tops_up_the_bare_bet(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """No sampled outcome → no quote to ask for; fall back to the bet."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _ok()  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _ok()  # type: ignore[method-assign]
        behaviour._sampled_outcome_token_id = lambda: None  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=_synced(DW, 1_000_000),
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "tx_hex",
                new_callable=PropertyMock,
                return_value="0xsafehash",
            ),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.PREPARE_TX.value
        transferred = int(behaviour.multisend_batches[0].data.hex()[-64:], 16)
        assert transferred == 1_000_000

    def test_reserve_clears_the_venue_minimum_end_to_end(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The reserve this behaviour computes must satisfy the connection's gate.

        Both halves are pinned separately elsewhere, but with *canned* numbers on
        the other side — so a unit mismatch across the seam, or a
        ``FEE_HEADROOM_RATIO`` too small for the real fee curve, would pass every
        other test. Here the connection's own ``_quote_buy`` produces the fee,
        this behaviour's own arithmetic turns it into a transfer, and the
        connection's own ``_place_bet`` gate then judges the funded wallet.
        """
        from packages.valory.connections.polymarket_client.connection import (
            PolymarketClientConnection,
        )

        # A bet sitting exactly on the venue's $1.00 floor: the OPE-1883 case.
        bet_units = 1_000_000
        conn = object.__new__(PolymarketClientConnection)
        conn.logger = MagicMock()
        conn.client = MagicMock()
        conn.builder_config = None
        conn.dw_address = DW
        conn._ensure_dw_funder = MagicMock()
        conn.client.calculate_market_price.return_value = 0.98

        def _adjust(_tok, amount, _price, balance, _builder=None):  # type: ignore[no-untyped-def]
            """Mirror the SDK's fee rule (py_clob_client_v2/fees.py)."""
            fee = min(amount, balance) * 0.02
            if balance <= amount + fee:
                return max(balance - fee, 0.0)
            return amount

        conn.client._adjust_buy_amount_for_balance.side_effect = _adjust

        # 1. The connection quotes the fee, with the DW swept empty as at top-up.
        conn._read_dw_collateral_balance = MagicMock(return_value=0.0)
        quote, _ = conn._quote_buy(token_id="tok", amount=bet_units / PUSD_UNITS)

        # 2. This behaviour's real arithmetic turns that quote into a transfer.
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp(quote))  # type: ignore[method-assign]
        behaviour._sampled_outcome_token_id = lambda: "tok"  # type: ignore[method-assign]
        behaviour.dw_address = DW
        transferred = _run(behaviour._top_up_amount(bet_units))

        assert transferred > bet_units, "no fee was reserved"

        # 3. The connection's gate judges a DW funded with exactly that transfer.
        from py_clob_client_v2.order_utils import Side
        from py_clob_client_v2.order_utils.model.order_data_v2 import SignedOrderV2
        from py_clob_client_v2.order_utils.model.signature_type_v2 import (
            SignatureTypeV2,
        )

        conn._read_dw_collateral_balance = MagicMock(
            return_value=transferred / PUSD_UNITS
        )
        conn.client.create_market_order.return_value = SignedOrderV2(
            salt="1",
            maker="0x0000000000000000000000000000000000000001",
            signer="0x0000000000000000000000000000000000000002",
            tokenId="tok",
            makerAmount=str(bet_units),
            takerAmount="1020408",
            side=Side.BUY,
            signatureType=SignatureTypeV2.POLY_GNOSIS_SAFE,
            timestamp="1700000000000",
            metadata="0x" + "00" * 32,
            builder="0x" + "00" * 32,
            expiration="0",
            signature="0xdeadbeef",
        )
        conn.client.post_order.return_value = {"status": "matched"}
        response, error = conn._place_bet(
            token_id="tok", amount=bet_units / PUSD_UNITS, funder=DW
        )

        assert error is None, f"the reserve did not clear the venue minimum: {error}"
        assert "below_minimum" not in response
        # And the order reaches the book at the full bet, not bet-minus-fee.
        assert conn.client.create_market_order.call_args.args[0].amount == 1.0

    def test_missing_fee_quote_warns(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An unmeasurable fee is announced; a zero fee is not.

        The two take the same branch but mean different things — one is a
        fee-free market, the other silently reproduces the pre-fix under-funding.
        """
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: (  # type: ignore[method-assign]
            (yield) or _resp({"fee_usd": None})
        )
        behaviour._sampled_outcome_token_id = lambda: "token123"  # type: ignore[method-assign]
        behaviour.dw_address = DW
        assert _run(behaviour._top_up_amount(1_000_000)) == 1_000_000
        behaviour.context.logger.warning.assert_called_once()

    def test_zero_fee_market_adds_no_reserve_silently(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A genuine zero-fee market needs no reserve and no warning."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: (  # type: ignore[method-assign]
            (yield) or _resp({"fee_usd": 0.0})
        )
        behaviour._sampled_outcome_token_id = lambda: "token123"  # type: ignore[method-assign]
        behaviour.dw_address = DW
        assert _run(behaviour._top_up_amount(1_000_000)) == 1_000_000
        behaviour.context.logger.warning.assert_not_called()

    def test_negative_fee_is_refused(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A nonsense fee from across the process boundary reserves nothing."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: (  # type: ignore[method-assign]
            (yield) or _resp({"fee_usd": -1.0})
        )
        behaviour._sampled_outcome_token_id = lambda: "token123"  # type: ignore[method-assign]
        behaviour.dw_address = DW
        assert _run(behaviour._top_up_amount(1_000_000)) == 1_000_000

    def test_sampled_outcome_token_id_resolves(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The token id comes from the sampled bet's chosen outcome."""
        behaviour = _make_behaviour(tmp_path)
        bet = MagicMock()
        bet.get_outcome.return_value = "Yes"
        bet.outcome_token_ids = {"Yes": "token123"}
        with (
            patch.object(
                PolymarketTopUpBehaviour,
                "sampled_bet",
                new_callable=PropertyMock,
                return_value=bet,
            ),
            patch.object(
                PolymarketTopUpBehaviour,
                "outcome_index",
                new_callable=PropertyMock,
                return_value=0,
            ),
        ):
            assert behaviour._sampled_outcome_token_id() == "token123"

    def test_sampled_outcome_token_id_swallows_failures(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """An unresolvable bet yields None rather than failing the top-up."""
        behaviour = _make_behaviour(tmp_path)
        with patch.object(
            PolymarketTopUpBehaviour,
            "sampled_bet",
            new_callable=PropertyMock,
            side_effect=ValueError("no bet"),
        ):
            assert behaviour._sampled_outcome_token_id() is None

    def test_multisend_build_failure_insufficient(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A multisend build failure → INSUFFICIENT_BALANCE."""
        behaviour = _make_behaviour(tmp_path)
        behaviour.do_connection_request = lambda m, d: ((yield) or _resp({"ok": 1}))  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _fail()  # type: ignore[method-assign]
        _set_balance(behaviour, 5_000_000)
        with patch.object(
            PolymarketTopUpBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=_synced(DW, 5_000_000),
        ):
            payload = _drive(behaviour)
        assert payload.event == Event.INSUFFICIENT_BALANCE.value
