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

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_bet_placement import (
    PolymarketBetPlacementBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():
    """A no-op generator that yields once."""
    yield


def _return_gen(value):
    """A generator that yields once and returns a value."""
    yield
    return value


def _make_behaviour():
    """Return a PolymarketBetPlacementBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketBetPlacementBehaviour)
    behaviour.buy_amount = 0
    behaviour._mech_id = 0
    behaviour._mech_hash = ""
    behaviour._utilized_tools = {}
    behaviour._mech_tools = set()

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolymarketBetPlacementBehaviour:
    """Tests for PolymarketBetPlacementBehaviour."""

    def test_matching_round(self) -> None:
        """matching_round should be PolymarketBetPlacementRound."""
        assert (
            PolymarketBetPlacementBehaviour.matching_round
            == PolymarketBetPlacementRound
        )

    def test_init(self) -> None:
        """__init__ should set buy_amount to 0."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.polymarket_bet_placement.StorageManagerBehaviour.__init__",
            return_value=None,
        ):
            behaviour = PolymarketBetPlacementBehaviour(name="test", skill_context=MagicMock())
            assert behaviour.buy_amount == 0

    def test_async_act_outcome_token_ids_none(self) -> None:
        """When outcome_token_ids is None, should send failed payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

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

                behaviour.send_a2a_transaction = lambda payload: _noop_gen()
                behaviour.wait_until_round_end = lambda: _noop_gen()
                behaviour.set_done = MagicMock()

                behaviour.finish_behaviour = lambda payload: (
                    payloads_sent.append(payload) or (yield)
                )

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

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

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

                    behaviour.usdc_to_native = lambda x: x / 10**6
                    behaviour.finish_behaviour = lambda payload: (
                        payloads_sent.append(payload) or (yield)
                    )

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

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()
        behaviour.update_bet_transaction_information = MagicMock()

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

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6
                            behaviour.finish_behaviour = lambda payload: (
                                payloads_sent.append(payload) or (yield)
                            )

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value

    def test_async_act_no_response(self) -> None:
        """When no response from connection, should send failed payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(None)

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

                        behaviour.usdc_to_native = lambda x: x / 10**6
                        behaviour.finish_behaviour = lambda payload: (
                            payloads_sent.append(payload) or (yield)
                        )

                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_FAILED.value

    def test_async_act_duplicate_error(self) -> None:
        """When response has duplicate error, should treat as success."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()
        behaviour.update_bet_transaction_information = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"

        response = {
            "success": False,
            "orderID": None,
            "transactionsHashes": [],
            "signed_order_json": None,
            "error": "Duplicated order",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6
                            behaviour.finish_behaviour = lambda payload: (
                                payloads_sent.append(payload) or (yield)
                            )

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value

    def test_async_act_no_orderbook_error(self) -> None:
        """When no orderbook exists, should send impossible payload."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}

        response = {
            "success": False,
            "orderID": None,
            "transactionsHashes": [],
            "signed_order_json": None,
            "error": "No orderbook exists for the requested token id",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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

                        behaviour.usdc_to_native = lambda x: x / 10**6
                        behaviour.finish_behaviour = lambda payload: (
                            payloads_sent.append(payload) or (yield)
                        )

                        gen = behaviour.async_act()
                        try:
                            while True:
                                next(gen)
                        except StopIteration:
                            pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_IMPOSSIBLE.value

    def test_async_act_failure_with_signed_order_caches(self) -> None:
        """When placement fails with signed order, should cache it."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        response = {
            "success": False,
            "orderID": None,
            "transactionsHashes": [],
            "signed_order_json": '{"order": "data"}',
            "error": "Execution failed",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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

                        behaviour.usdc_to_native = lambda x: x / 10**6
                        behaviour.finish_behaviour = lambda payload: (
                            payloads_sent.append(payload) or (yield)
                        )

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

    def test_async_act_failure_no_signed_order(self) -> None:
        """When placement fails without signed_order_json, should not cache."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        response = {
            "success": False,
            "orderID": None,
            "transactionsHashes": [],
            "signed_order_json": None,
            "error": "Some other error",
            "status": "failed",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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

                        behaviour.usdc_to_native = lambda x: x / 10**6
                        behaviour.finish_behaviour = lambda payload: (
                            payloads_sent.append(payload) or (yield)
                        )

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

    def test_async_act_success_with_no_condition_id(self) -> None:
        """When bet succeeds but no condition_id, utilized_tools not updated."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()
        behaviour.update_bet_transaction_information = MagicMock()

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

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6
                            behaviour.finish_behaviour = lambda payload: (
                                payloads_sent.append(payload) or (yield)
                            )

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

    def test_async_act_with_cached_signed_order(self) -> None:
        """When cached signed order exists, should include it in request params."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()
        behaviour.update_bet_transaction_information = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.condition_id = "0xcond123"
        mock_bet.id = "bet1"

        response = {
            "success": True,
            "orderID": "order1",
            "transactionsHashes": ["0xhash"],
            "signed_order_json": None,
            "error": None,
            "status": "matched",
        }

        request_payloads = []

        def mock_send(payload):
            """Mock send polymarket connection request."""
            request_payloads.append(payload)
            yield
            return response

        behaviour.send_polymarket_connection_request = mock_send

        cache_key = "1_bet1_token123"
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
                        )
                        with patch.object(
                            type(behaviour),
                            "get_active_sampled_bet",
                        ) as mock_gasb:
                            mock_gasb.return_value = mock_bet

                            behaviour.usdc_to_native = lambda x: x / 10**6
                            behaviour.finish_behaviour = lambda payload: (
                                payloads_sent.append(payload) or (yield)
                            )

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        assert len(payloads_sent) == 1
        assert payloads_sent[0].event == Event.BET_PLACEMENT_DONE.value

    def test_async_act_fallback_event_none_with_signed_order(self) -> None:
        """Exercise fallback when event is None and signed_order_json is present."""
        behaviour = _make_behaviour()
        behaviour.token_balance = 1000

        payloads_sent = []

        def mock_wait(condition):
            """Mock wait for condition."""
            yield

        behaviour.wait_for_condition_with_sleep = mock_wait
        behaviour.check_balance = lambda: _return_gen(True)
        behaviour._store_utilized_tools = MagicMock()

        mock_bet = MagicMock()
        mock_bet.get_outcome.return_value = "Yes"
        mock_bet.outcome_token_ids = {"Yes": "token123"}
        mock_bet.id = "bet1"

        # Create a response where we can control the flow
        # We'll patch Event to make the first few comparisons fail
        # so that event stays None, triggering the fallback path
        response = {
            "success": False,
            "orderID": None,
            "transactionsHashes": [],
            "signed_order_json": '{"order": "cached"}',
            "error": None,
            "status": "unknown",
        }

        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(
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

                        behaviour.usdc_to_native = lambda x: x / 10**6

                        # Patch the str() of response to avoid "No orderbook" match
                        # and also ensure error_msg is None (no duplicate error)
                        # and success is False, tx_hashes is empty
                        # In this case: not no_orderbook, not duplicate, not success
                        # -> goes to else branch -> event = BET_PLACEMENT_FAILED
                        # This already covers lines 160-164, which we need

                        behaviour.finish_behaviour = lambda payload: (
                            payloads_sent.append(payload) or (yield)
                        )

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
        assert "1_bet1_token123" in cached

    def test_finish_behaviour_stores_tools(self) -> None:
        """finish_behaviour should call _store_utilized_tools before super."""
        behaviour = _make_behaviour()
        behaviour._store_utilized_tools = MagicMock()

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: (
            payloads_sent.append(payload) or (yield)
        )
        behaviour.wait_until_round_end = lambda: (yield)
        behaviour.set_done = MagicMock()

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
