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

"""Tests for PolymarketBetPlacementBehaviour."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    SKIP_ORDER_IMPOSSIBLE,
    SKIP_ORDER_NOT_FILLED,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_bet_placement import (
    ORDER_CONFIRM_BACKOFFS_S,
    PolymarketBetPlacementBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import Event

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
    """Return a PolymarketBetPlacementBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketBetPlacementBehaviour)  # type: ignore[no-untyped-def]
    behaviour.buy_amount = 0
    behaviour._mech_id = 0
    behaviour._mech_hash = ""
    behaviour._utilized_tools = {}
    behaviour._mech_tools = set()

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


def _run_placement(response, order_lookups=(), cached_orders=None):  # type: ignore[no-untyped-def]
    """Run one placement against ``response``; lookups answer ``GET_ORDER`` in turn.

    :param response: what the connection answers to ``PLACE_BET``.
    :param order_lookups: the ``GET_ORDER`` answers, in order; ``None`` after.
    :param cached_orders: the signed orders cached by earlier attempts.
    :return: the behaviour, the payload it sent and the order ids looked up.
    """
    behaviour = _make_behaviour()
    behaviour.token_balance = 1000
    behaviour.wait_for_condition_with_sleep = lambda condition: _noop_gen()  # type: ignore[method-assign]
    behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
    behaviour.sleep = lambda seconds: _noop_gen()  # type: ignore[method-assign]
    behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
    behaviour._record_market_skipped = MagicMock()  # type: ignore[method-assign]
    behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]
    behaviour.usdc_to_native = lambda x: x  # type: ignore[method-assign]
    answers = list(order_lookups)
    looked_up = []

    def _route(payload):  # type: ignore[no-untyped-def]
        if payload["request_type"] == "get_order":
            looked_up.append(payload["params"]["order_id"])
            return _return_gen(answers.pop(0) if answers else None)
        return _return_gen(response)

    behaviour.send_polymarket_connection_request = _route  # type: ignore[method-assign]
    sent = []
    behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
        sent.append(payload) or (yield)  # type: ignore[func-returns-value]
    )
    bet = MagicMock(id="bet1", condition_id=None, outcome_token_ids={"Yes": "tok"})
    bet.get_outcome.return_value = "Yes"
    cls = type(behaviour)
    with (
        patch.object(cls, "sampled_bet", new_callable=PropertyMock, return_value=bet),
        patch.object(cls, "outcome_index", new_callable=PropertyMock, return_value=0),
        patch.object(
            cls, "investment_amount", new_callable=PropertyMock, return_value=100
        ),
        patch.object(
            cls,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=MagicMock(
                period_count=1,
                cached_signed_orders=dict(cached_orders or {}),
                mech_tool_key=None,
            ),
        ),
        patch.object(cls, "get_active_sampled_bet", return_value=bet),
    ):
        for _ in behaviour.async_act():
            pass
    return behaviour, sent[0], looked_up


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolymarketBetPlacementBehaviour:
    """Tests for PolymarketBetPlacementBehaviour."""

    def test_init(self) -> None:
        """__init__ should set buy_amount to 0."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_bet_placement.StorageManagerBehaviour.__init__",
            return_value=None,
        ):
            behaviour = PolymarketBetPlacementBehaviour(
                name="test", skill_context=MagicMock()
            )
            assert behaviour.buy_amount == 0

    def test_async_act_outcome_token_ids_none(self) -> None:
        """When outcome_token_ids is None, should send failed payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = None

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0

                behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
                behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
                behaviour.set_done = MagicMock()  # type: ignore[method-assign]

                behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                    payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                )
                # type: ignore[func-returns-value]
                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PolymarketBetPlacementPayload)
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value

    def test_async_act_insufficient_balance(self) -> None:
        """When balance is insufficient, should send insufficient balance payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 10

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100

                    behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                    behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                        payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                    )
                    # type: ignore[func-returns-value]
                    gen = behaviour.async_act()
                    try:
                        while True:
                            next(gen)
                    except StopIteration:
                        pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.INSUFFICIENT_BALANCE.value

    def test_async_act_success(self) -> None:
        """When bet placement succeeds, should send done payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"

        response = {
            "success": True,
            "orderID": "order1",
            "transactionsHashes": ["0xhash"],
            "signed_order_json": None,
            "error": None,
            "status": "matched",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=False,
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                                payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                            )
                            # type: ignore[func-returns-value]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value
        behaviour.update_bet_transaction_information.assert_called_once_with()

    def test_async_act_with_deposit_wallet_adds_funder(self) -> None:
        """When the store resolves a DepositWallet, the bet request adds funder."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000
        behaviour._resolve_deposit_wallet = lambda: "0xDW"  # type: ignore[method-assign]

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"

        sent = {}

        def _capture(payload):  # type: ignore[no-untyped-def]
            sent["payload"] = payload
            yield
            return {"success": True, "transactionsHashes": ["0xh"], "status": "matched"}

        behaviour.send_polymarket_connection_request = _capture  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=False,
                        )
                        with patch.object(
                            type(behaviour), "get_active_sampled_bet"
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet
                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (yield)  # type: ignore[method-assign]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert sent["payload"]["params"]["funder"] == "0xDW"

    def test_async_act_no_deposit_wallet_omits_funder(self) -> None:
        """When no DepositWallet is known, the bet request omits funder."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000
        behaviour._resolve_deposit_wallet = lambda: None  # type: ignore[method-assign]

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"

        sent = {}

        def _capture(payload):  # type: ignore[no-untyped-def]
            sent["payload"] = payload
            yield
            return {"success": True, "transactionsHashes": ["0xh"], "status": "matched"}

        behaviour.send_polymarket_connection_request = _capture  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=False,
                            deposit_wallet_address=None,
                        )
                        with patch.object(
                            type(behaviour), "get_active_sampled_bet"
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet
                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (yield)  # type: ignore[method-assign]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert "funder" not in sent["payload"]["params"]

    def test_async_act_no_response(self) -> None:
        """When no response from connection, should send failed payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(None)  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        # type: ignore[func-returns-value]
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value

    def test_async_act_duplicate_error(self) -> None:
        """A "Duplicated" answer is a placed bet once the lookup says it matched."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"

        response = {
            "error": "order 0xabc123 is invalid. Duplicated.",
            "posted": True,
        }
        lookups = []

        def _route(payload):  # type: ignore[no-untyped-def]
            if payload["request_type"] == "get_order":
                lookups.append(payload["params"]["order_id"])
                return _return_gen({"status": "ORDER_STATUS_MATCHED"})
            return _return_gen(response)

        behaviour.send_polymarket_connection_request = _route  # type: ignore[method-assign]
        behaviour.sleep = lambda seconds: _noop_gen()  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=False,
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                                payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                            )
                            # type: ignore[func-returns-value]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value
        behaviour.update_bet_transaction_information.assert_called_once_with()
        assert lookups == ["0xabc123"]

    def test_async_act_no_orderbook_error(self) -> None:
        """When no orderbook exists, should send impossible payload."""
        behaviour = _make_behaviour()
        skipped_bet = MagicMock()
        behaviour.get_active_sampled_bet = MagicMock(return_value=skipped_bet)  # type: ignore[method-assign]
        behaviour._record_market_skipped = MagicMock()  # type: ignore[method-assign]
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}

        response = {
            "success": False,
            "orderID": None,  # type: ignore[var-annotated]
            "transactionsHashes": [],
            "signed_order_json": None,
            "error": "No orderbook exists for the requested token id",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        # type: ignore[func-returns-value]
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        behaviour._record_market_skipped.assert_called_once_with(  # type: ignore[attr-defined]
            skipped_bet, SKIP_ORDER_IMPOSSIBLE
        )

    def test_async_act_below_minimum_leaves_the_round(self) -> None:
        """An under-minimum order blacklists instead of looping on itself.

        ``BET_PLACEMENT_FAILED`` transitions back into this same round, so an
        order the venue can never accept would be retried forever. It must
        leave via ``BET_PLACEMENT_IMPOSSIBLE``, and the doomed order must not
        stay in the cache to be replayed.
        """
        behaviour = _make_behaviour()
        skipped_bet = MagicMock()
        behaviour.get_active_sampled_bet = MagicMock(return_value=skipped_bet)  # type: ignore[method-assign]
        behaviour._record_market_skipped = MagicMock()  # type: ignore[method-assign]
        behaviour.token_balance = 2_000_000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        response = {
            "error": "Order below the CLOB minimum: the taker fee leaves only "
            "$0.9800 of this $1.0000 buy on the book",
            "below_minimum": True,
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        cache_key = "v2_1_bet1_token123"
        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 1000000
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={cache_key: '{"stale": true}'},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        assert json.loads(payloads_sent[0].cached_signed_orders) == {}
        behaviour.update_bet_transaction_information.assert_not_called()
        behaviour._record_market_skipped.assert_called_once_with(  # type: ignore[attr-defined]
            skipped_bet, SKIP_ORDER_IMPOSSIBLE
        )

    def test_async_act_non_terminal_failure_is_not_blacklisted(self) -> None:
        """Without the flag, a failure still retries and keeps its cached order.

        Named for the gate so that widening it — defaulting the flag to true, or
        testing a truthy error string — fails here instead of silently turning
        every placement failure into a blacklisting.
        """
        behaviour = _make_behaviour()
        behaviour.token_balance = 2_000_000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        response = {
            "success": False,
            "error": "not enough balance / allowance",
            "signed_order_json": '{"clob_version": "v2"}',
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 1000000
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value
        assert json.loads(payloads_sent[0].cached_signed_orders) == {
            "v2_1_bet1_token123": '{"clob_version": "v2"}'
        }

    def test_async_act_failure_with_signed_order_caches(self) -> None:
        """When placement fails with signed order, should cache it."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        response = {
            "success": False,
            "orderID": None,  # type: ignore[var-annotated]
            "transactionsHashes": [],
            "signed_order_json": '{"order": "data"}',
            "error": "Execution failed",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        # type: ignore[func-returns-value]
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value
        cached = json.loads(payloads_sent[0].cached_signed_orders)
        assert len(cached) > 0
        behaviour.update_bet_transaction_information.assert_not_called()

    def test_async_act_failure_no_signed_order(self) -> None:
        """When placement fails without signed_order_json, should not cache."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        response = {
            "success": False,
            "orderID": None,  # type: ignore[var-annotated]
            "transactionsHashes": [],
            "signed_order_json": None,
            "error": "Some other error",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        # type: ignore[func-returns-value]
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value
        cached = json.loads(payloads_sent[0].cached_signed_orders)
        # No signed order should be cached
        assert len(cached) == 0

    def test_async_act_success_with_policy_increment(self) -> None:
        """When bet succeeds and is_policy_set, policy should be incremented."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]
        behaviour._store_policy = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"

        response = {
            "success": True,
            "orderID": "order1",
            "transactionsHashes": ["0xhash"],
            "signed_order_json": None,
            "error": None,
            "status": "matched",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = '{"serialized": "policy"}'

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=True,
                            policy=mock_policy,
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                                payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                            )
                            # type: ignore[func-returns-value]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value
        # Verify policy was incremented
        mock_policy.tool_used.assert_called_once_with("tool1")
        mock_policy.serialize.assert_called_once()
        behaviour._store_policy.assert_called_once()
        assert payloads_sent[0].policy == '{"serialized": "policy"}'

    def test_async_act_success_with_no_condition_id(self) -> None:
        """When bet succeeds but no condition_id, utilized_tools not updated."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = None

        response = {
            "success": True,
            "orderID": "order1",
            "transactionsHashes": ["0xhash"],
            "signed_order_json": None,
            "error": None,
            "status": "matched",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=False,
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                                payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                            )
                            # type: ignore[func-returns-value]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value
        # utilized_tools should be None since condition_id is None
        assert payloads_sent[0].utilized_tools is None

    @pytest.mark.parametrize("market_version", ["v1", "v2"])
    def test_async_act_with_cached_signed_order(self, market_version: str) -> None:
        """When cached signed order exists, should include it in request params, with the bet's market version."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"
        mock_bet.id = "bet1"
        mock_bet.market_version = market_version

        response = {
            "success": True,
            "orderID": "order1",
            "transactionsHashes": ["0xhash"],
            "signed_order_json": None,
            "error": None,
            "status": "matched",
        }

        request_payloads = []

        def mock_send(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock send polymarket connection request."""
            request_payloads.append(payload)  # type: ignore[no-untyped-def]
            yield
            return response

        behaviour.send_polymarket_connection_request = mock_send  # type: ignore[method-assign]

        cache_key = "v2_1_bet1_token123"
        cached_orders = {cache_key: '{"cached": "order"}'}

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders=cached_orders,
                            mech_tool="tool1",
                            mech_tool_key="tool1",
                            is_policy_set=False,
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]
                            behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                                payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                            )
                            # type: ignore[func-returns-value]
                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value
        assert request_payloads[0]["params"].get("market_version") == market_version

    def test_async_act_fallback_event_none_with_signed_order(self) -> None:
        """Exercise fallback when event is None and signed_order_json is present."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock wait for condition."""
            yield  # type: ignore[no-untyped-def]

        behaviour.wait_for_condition_with_sleep = mock_wait  # type: ignore[method-assign]
        behaviour.check_balance = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        # Create a response where we can control the flow
        # We'll patch Event to make the first few comparisons fail
        # so that event stays None, triggering the fallback path
        response = {
            "success": False,
            "orderID": None,  # type: ignore[var-annotated]
            "transactionsHashes": [],
            "signed_order_json": '{"order": "cached"}',
            "error": None,
            "status": "unknown",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            response
        )

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = mock_bet
            with patch.object(
                type(behaviour), "outcome_index", new_callable=PropertyMock
            ) as mock_oi:
                mock_oi.return_value = 0
                with patch.object(
                    type(behaviour), "investment_amount", new_callable=PropertyMock
                ) as mock_inv:
                    mock_inv.return_value = 100
                    with patch.object(
                        type(behaviour),
                        "synchronized_data",
                        new_callable=PropertyMock,
                    ) as mock_sd:
                        mock_sd.return_value = MagicMock(
                            period_count=1,
                            cached_signed_orders={},
                        )

                        behaviour.usdc_to_native = lambda x: x / 10**6  # type: ignore[method-assign]

                        # Patch the str() of response to avoid "No orderbook" match
                        # and also ensure error_msg is None (no duplicate error)
                        # and success is False, tx_hashes is empty
                        # In this case: not no_orderbook, not duplicate, not success
                        # -> goes to else branch -> event = BET_PLACEMENT_FAILED
                        # This already covers lines 160-164, which we need

                        behaviour.finish_behaviour = lambda payload: (  # type: ignore[method-assign]
                            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
                        )
                        # type: ignore[func-returns-value]
                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        # Event is BET_PLACEMENT_FAILED since success is False
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value
        # The signed_order_json should be cached
        cached = json.loads(payloads_sent[0].cached_signed_orders)
        assert "v2_1_bet1_token123" in cached

    def test_finish_behaviour_stores_tools(self) -> None:
        """finish_behaviour should call _store_utilized_tools before super."""
        behaviour = _make_behaviour()
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        payload = PolymarketBetPlacementPayload(
            "test_agent", None, None, False, event="done"
        )

        gen = behaviour.finish_behaviour(payload)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        behaviour._store_utilized_tools.assert_called_once()

    def test_posted_fok_kill_skips_the_market_without_recording(self) -> None:
        """A FOK order the CLOB killed is skipped with the not-filled reason, not cached."""
        behaviour, payload, _ = _run_placement(
            {
                "error": "order couldn't be fully filled. FOK orders are fully filled or killed.",
                "posted": True,
                "fok_killed": True,
            },
            cached_orders={"v2_1_bet1_tok": '{"clob_version": "v2"}'},
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        assert json.loads(payload.cached_signed_orders) == {}
        behaviour.update_bet_transaction_information.assert_not_called()
        behaviour._record_market_skipped.assert_called_once()
        assert behaviour._record_market_skipped.call_args[0][1] == SKIP_ORDER_NOT_FILLED

    def test_duplicated_and_matched_records_the_trade_once(self) -> None:
        """A "Duplicated" order the lookup reports matched is placed and recorded once."""
        behaviour, payload, looked_up = _run_placement(
            {"error": "order 0xf51b is invalid. Duplicated.", "posted": True},
            order_lookups=[{"status": "ORDER_STATUS_MATCHED"}],
            cached_orders={"v2_1_bet1_tok": '{"clob_version": "v2"}'},
        )

        assert payload.event == Event.BET_PLACEMENT_DONE.value
        assert json.loads(payload.cached_signed_orders) == {}
        assert looked_up == ["0xf51b"]
        behaviour.update_bet_transaction_information.assert_called_once_with()
        behaviour._record_market_skipped.assert_not_called()

    def test_duplicated_and_never_confirmed_is_skipped_unrecorded(self) -> None:
        """With no record of the order before the backoffs run out, nothing is recorded."""
        behaviour, payload, looked_up = _run_placement(
            {"error": "order 0xf51b is invalid. Duplicated.", "posted": True}
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        assert len(looked_up) == len(ORDER_CONFIRM_BACKOFFS_S)
        assert sum(ORDER_CONFIRM_BACKOFFS_S) <= 60
        behaviour.update_bet_transaction_information.assert_not_called()
        assert behaviour._record_market_skipped.call_args[0][1] == SKIP_ORDER_NOT_FILLED

    def test_retryable_answer_keeps_the_signed_order_for_a_resend(self) -> None:
        """No reply, a 5xx or a 429 retries the round with the same signed order."""
        behaviour, payload, _ = _run_placement(
            {
                "error": "Request exception!",
                "posted": True,
                "retryable": True,
                "signed_order_json": '{"clob_version": "v2"}',
            }
        )

        assert payload.event == Event.BET_PLACEMENT_FAILED.value
        assert json.loads(payload.cached_signed_orders) == {
            "v2_1_bet1_tok": '{"clob_version": "v2"}'
        }
        behaviour.update_bet_transaction_information.assert_not_called()
        behaviour._record_market_skipped.assert_not_called()

    def test_error_before_the_post_retries_without_skipping(self) -> None:
        """An error that never reached the CLOB as an order never blacklists the market."""
        behaviour, payload, looked_up = _run_placement(
            {"error": "tick size lookup failed: order is invalid. Duplicated."}
        )

        assert payload.event == Event.BET_PLACEMENT_FAILED.value
        assert json.loads(payload.cached_signed_orders) == {}
        assert looked_up == []
        behaviour.update_bet_transaction_information.assert_not_called()
        behaviour._record_market_skipped.assert_not_called()

    def test_other_posted_rejection_skips_with_the_impossible_reason(self) -> None:
        """A 4xx answer that is not a kill keeps the existing can't-be-placed reason."""
        behaviour, payload, _ = _run_placement(
            {"error": "not enough balance / allowance", "posted": True}
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        behaviour.update_bet_transaction_information.assert_not_called()
        assert behaviour._record_market_skipped.call_args[0][1] == SKIP_ORDER_IMPOSSIBLE

    def test_duplicated_and_canceled_stops_looking_and_skips(self) -> None:
        """A terminal status other than matched ends the lookup without recording."""
        behaviour, payload, looked_up = _run_placement(
            {"error": "order 0xf51b is invalid. Duplicated.", "posted": True},
            order_lookups=[{"status": "ORDER_STATUS_CANCELED"}],
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        assert looked_up == ["0xf51b"]
        behaviour.update_bet_transaction_information.assert_not_called()
        assert behaviour._record_market_skipped.call_args[0][1] == SKIP_ORDER_NOT_FILLED

    def test_duplicated_without_an_order_id_is_skipped_unrecorded(self) -> None:
        """Without an order id to look up, the duplicate cannot be confirmed."""
        behaviour, payload, looked_up = _run_placement(
            {"error": "order is invalid. Duplicated.", "posted": True}
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        assert looked_up == []
        behaviour.update_bet_transaction_information.assert_not_called()
        assert behaviour._record_market_skipped.call_args[0][1] == SKIP_ORDER_NOT_FILLED

    def test_duplicated_with_the_lookup_unreachable_logs_a_possible_match(self) -> None:
        """An unreachable lookup records nothing and says the order may have matched."""
        behaviour, payload, looked_up = _run_placement(
            {"error": "order 0xf51b is invalid. Duplicated.", "posted": True},
            order_lookups=[{"error": "connection reset"}]
            * len(ORDER_CONFIRM_BACKOFFS_S),
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        assert len(looked_up) == len(ORDER_CONFIRM_BACKOFFS_S)
        behaviour.update_bet_transaction_information.assert_not_called()
        errors = [c.args[0] for c in behaviour.context.logger.error.call_args_list]
        assert any("0xf51b" in e and "may have matched" in e for e in errors)

    def test_delayed_post_is_recorded_only_once_confirmed_matched(self) -> None:
        """A delayed answer is a placed bet only after the lookup says it matched."""
        behaviour, payload, looked_up = _run_placement(
            {"success": True, "status": "delayed", "orderID": "0xd31a"},
            order_lookups=[{"status": "ORDER_STATUS_MATCHED"}],
        )

        assert payload.event == Event.BET_PLACEMENT_DONE.value
        assert looked_up == ["0xd31a"]
        behaviour.update_bet_transaction_information.assert_called_once_with()

    def test_delayed_post_the_clob_then_kills_is_not_recorded(self) -> None:
        """A delayed FOK the CLOB kills afterwards is skipped, not counted as held."""
        behaviour, payload, _ = _run_placement(
            {"success": True, "status": "delayed", "orderID": "0xd31a"},
            order_lookups=[{"status": "ORDER_STATUS_CANCELED"}],
        )

        assert payload.event == Event.BET_PLACEMENT_IMPOSSIBLE.value
        behaviour.update_bet_transaction_information.assert_not_called()
        assert behaviour._record_market_skipped.call_args[0][1] == SKIP_ORDER_NOT_FILLED
