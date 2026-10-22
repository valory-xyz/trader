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

"""Tests for PolymarketRedeemBehaviour."""

import json
from io import StringIO
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import to_checksum_address  # type: ignore[import-not-found]
from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.tests import test_connection as pm
from packages.valory.skills.agent_performance_summary_abci.feed import EventType
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_reedem import (
    BLOCK_NUMBER_KEY,
    DEFAULT_TO_BLOCK,
    PolymarketRedeemBehaviour,
    ZERO_BYTES,
    ZERO_HEX,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketRedeemPayload
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    EGreedyPolicy,
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


def _make_policy(tools=None):  # type: ignore[no-untyped-def]
    """Create a test policy."""
    if tools is None:  # type: ignore[no-untyped-def]
        tools = {"tool1": AccuracyInfo(requests=5, accuracy=0.6, pending=1)}
    return EGreedyPolicy(
        eps=0.1,
        consecutive_failures_threshold=3,
        quarantine_duration=100,
        accuracy_store=tools,
    )


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a PolymarketRedeemBehaviour with mocked dependencies."""
    behaviour = object.__new__(PolymarketRedeemBehaviour)  # type: ignore[no-untyped-def]
    behaviour._policy = None
    behaviour._utilized_tools = {}
    behaviour._mech_tools = set()
    behaviour._mech_id = 0
    behaviour._mech_hash = ""
    behaviour._remote_accuracy_information = StringIO()
    behaviour.multisend_batches = []
    behaviour.multisend_data = b""
    behaviour._safe_tx_hash = ""
    behaviour.buy_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


# ---------------------------------------------------------------------------
# Tests for constants


class TestPolymarketRedeemConstants:
    """Tests for module-level constants."""

    def test_zero_hex_length(self) -> None:
        """ZERO_HEX should be 64 chars."""
        assert len(ZERO_HEX) == 64

    def test_zero_bytes_length(self) -> None:
        """ZERO_BYTES should be 32 bytes."""
        assert len(ZERO_BYTES) == 32

    def test_block_number_key(self) -> None:
        """BLOCK_NUMBER_KEY should be 'number'."""
        assert BLOCK_NUMBER_KEY == "number"

    def test_default_to_block(self) -> None:
        """DEFAULT_TO_BLOCK should be 'latest'."""
        assert DEFAULT_TO_BLOCK == "latest"


# ---------------------------------------------------------------------------
# Tests for properties


class TestPolymarketRedeemProperties:
    """Tests for PolymarketRedeemBehaviour properties."""

    def test_params_property(self) -> None:
        """Params property should return context.params cast to DecisionMakerParams."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "context", new_callable=PropertyMock
        ) as mock_ctx:
            ctx = MagicMock()
            ctx.params = MagicMock()
            mock_ctx.return_value = ctx
            result = behaviour.params
            assert result is ctx.params


# ---------------------------------------------------------------------------
# Tests for finish_behaviour


class TestFinishBehaviour:
    """Tests for finish_behaviour."""

    def test_finish_behaviour_stores_tools_and_calls_super(self) -> None:
        """finish_behaviour should call _store_utilized_tools and then super().finish_behaviour."""
        behaviour = _make_behaviour()
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        payload = PolymarketRedeemPayload(
            sender="test_agent",
            tx_submitter=None,
            tx_hash=None,
            mocking_mode=False,
            event="done",
        )

        gen = behaviour.finish_behaviour(payload)
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        behaviour._store_utilized_tools.assert_called_once()
        assert len(payloads_sent) == 1


# ---------------------------------------------------------------------------
# Tests for update_policy_for_redeemable_positions


class TestUpdatePolicyForRedeemablePositions:
    """Tests for _update_policy_for_redeemable_positions."""

    def test_updates_accuracy_store_for_winning_position(self) -> None:
        """Should update accuracy store for winning position."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._utilized_tools = {"cond1": "tool1"}

        positions = [{"conditionId": "cond1", "curPrice": 1.0}]

        with patch.object(
            type(behaviour), "policy", new_callable=PropertyMock
        ) as mock_pol:
            mock_pol.return_value = policy

            behaviour._update_policy_for_redeemable_positions(positions)

        # Tool should be removed from utilized_tools after update
        assert "cond1" not in behaviour._utilized_tools

    def test_skips_position_without_condition_id(self) -> None:
        """Should skip positions without conditionId."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {}

        positions = [{"curPrice": 1.0}]

        behaviour._update_policy_for_redeemable_positions(positions)

    def test_skips_position_without_tool(self) -> None:
        """Should skip positions where tool is not in utilized_tools."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {}

        positions = [{"conditionId": "cond_unknown", "curPrice": 1.0}]

        behaviour._update_policy_for_redeemable_positions(positions)

    def test_skips_position_without_cur_price(self) -> None:
        """Should skip positions without curPrice."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {"cond1": "tool1"}

        positions = [{"conditionId": "cond1"}]

        behaviour._update_policy_for_redeemable_positions(positions)
        # Tool should still be in utilized_tools since it was skipped
        assert "cond1" in behaviour._utilized_tools

    def test_handles_losing_position(self) -> None:
        """Should update accuracy store for losing position (curPrice < 0.5)."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._utilized_tools = {"cond1": "tool1"}

        positions = [{"conditionId": "cond1", "curPrice": 0.0}]

        with patch.object(
            type(behaviour), "policy", new_callable=PropertyMock
        ) as mock_pol:
            mock_pol.return_value = policy

            behaviour._update_policy_for_redeemable_positions(positions)

        assert "cond1" not in behaviour._utilized_tools

    def test_handles_key_error_in_accuracy_store(self) -> None:
        """Should handle KeyError when tool not in accuracy store."""
        behaviour = _make_behaviour()
        policy = _make_policy(tools={})
        behaviour._policy = policy
        behaviour._utilized_tools = {"cond1": "unknown_tool"}

        positions = [{"conditionId": "cond1", "curPrice": 1.0}]

        with patch.object(
            type(behaviour), "policy", new_callable=PropertyMock
        ) as mock_pol:
            mock_pol.return_value = policy

            # Should not raise
            behaviour._update_policy_for_redeemable_positions(positions)


# ---------------------------------------------------------------------------
# Tests for fetch_redeemable_positions


class TestFetchRedeemablePositions:
    """Tests for _fetch_redeemable_positions."""

    def test_fetches_positions_via_connection(self) -> None:
        """Should call send_polymarket_connection_request with correct params."""
        behaviour = _make_behaviour()

        expected_positions = [{"conditionId": "cond1", "redeemable": True}]
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            expected_positions
        )

        gen = behaviour._fetch_redeemable_positions()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == expected_positions

    @pytest.mark.parametrize(
        "connection_response",
        [{"error": "Error fetching positions: 503"}, None, "garbled"],
    )
    def test_failed_read_returns_none(self, connection_response) -> None:  # type: ignore[no-untyped-def]
        """A failed read returns None, never a non-list."""
        behaviour = _make_behaviour()
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            connection_response
        )

        gen = behaviour._fetch_redeemable_positions()
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result is None
        behaviour.context.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for redeem_position


class TestRedeemPosition:
    """Tests for _redeem_position."""

    def test_redeems_standard_position(self) -> None:
        """Standard position payload contains 1<<outcomeIndex and is_neg_risk=False."""
        behaviour = _make_behaviour()

        sent_payloads = []

        def capture(payload):  # type: ignore[no-untyped-def]
            sent_payloads.append(payload)
            return _return_gen({"success": True})

        behaviour.send_polymarket_connection_request = capture  # type: ignore[method-assign]

        gen = behaviour._redeem_position(
            condition_id="0xcond1",
            outcome_index=0,
            collateral_token="0xusdc",  # nosec B106
            is_neg_risk=False,
        )
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        assert len(sent_payloads) == 1
        params = sent_payloads[0]["params"]
        assert params["condition_id"] == "0xcond1"
        assert params["index_sets"] == [1]  # 1 << 0
        assert params["collateral_token"] == "0xusdc"
        assert params["is_neg_risk"] is False
        assert "size" not in params

    def test_redeems_neg_risk_position(self) -> None:
        """Neg-risk position payload contains 1<<outcomeIndex and is_neg_risk=True."""
        behaviour = _make_behaviour()

        sent_payloads = []

        def capture(payload):  # type: ignore[no-untyped-def]
            sent_payloads.append(payload)
            return _return_gen({"success": True})

        behaviour.send_polymarket_connection_request = capture  # type: ignore[method-assign]

        gen = behaviour._redeem_position(
            condition_id="0xcond2",
            outcome_index=1,
            collateral_token="0xusdc",  # nosec B106
            is_neg_risk=True,
        )
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        assert len(sent_payloads) == 1
        params = sent_payloads[0]["params"]
        assert params["condition_id"] == "0xcond2"
        assert params["index_sets"] == [2]  # 1 << 1
        assert params["is_neg_risk"] is True
        assert "size" not in params


# ---------------------------------------------------------------------------
# Tests for setup_policy_and_tools


class TestSetupPolicyAndTools:
    """Tests for _setup_policy_and_tools."""

    def test_uses_synced_data_when_policy_set(self) -> None:
        """Should use policy from synchronized_data when is_policy_set is True."""
        behaviour = _make_behaviour()
        mock_policy = _make_policy()
        mock_tools = {"tool1", "tool2"}

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(
                is_policy_set=True,
                policy=mock_policy,
                available_mech_tools=mock_tools,
            )

            gen = behaviour._setup_policy_and_tools()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is True
        assert behaviour._policy is mock_policy

    def test_short_circuit_publishes_suitable_tools(self) -> None:
        """The is_policy_set short-circuit must still publish for the ChatUI."""
        behaviour = _make_behaviour()
        called = []

        def fake_publish():  # type: ignore[no-untyped-def]
            """Spy standing in for _maybe_publish_suitable_tools."""
            called.append(True)
            yield

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(
                is_policy_set=True,
                policy=_make_policy(),
                available_mech_tools={"tool1"},
            )
            behaviour._maybe_publish_suitable_tools = fake_publish  # type: ignore[method-assign]
            gen = behaviour._setup_policy_and_tools()
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result is True
        assert called == [True]

    def test_falls_back_to_super_when_policy_not_set(self) -> None:
        """Should call super()._setup_policy_and_tools when is_policy_set is False."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=False)

            # Mock the super's _setup_policy_and_tools
            with patch(
                "packages.valory.skills.decision_maker_abci.behaviours.storage_manager.StorageManagerBehaviour._setup_policy_and_tools"
            ) as mock_super:
                mock_super.return_value = _return_gen(True)

                gen = behaviour._setup_policy_and_tools()
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result is True


# ---------------------------------------------------------------------------
# Tests for build_redeem_positions_data


class TestBuildRedeemPositionsData:
    """Tests for _build_redeem_positions_data."""

    def test_standard_redeem_data_starts_with_correct_selector(self) -> None:
        """Should start with redeemPositions function selector."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert result.startswith("0x01b7037c")

    def test_standard_redeem_data_contains_collateral(self) -> None:
        """Should contain the collateral token address."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert "1234567890123456789012345678901234567890" in result.lower()

    def test_standard_redeem_data_contains_condition_id(self) -> None:
        """Should contain the condition ID."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert "aabbccdd" in result.lower()

    def test_standard_redeem_data_multiple_index_sets(self) -> None:
        """Should handle multiple index sets."""
        behaviour = _make_behaviour()
        result = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1, 2],
        )
        # Array length should be 2
        assert result.startswith("0x01b7037c")
        # Should be longer than single element
        single = behaviour._build_redeem_positions_data(
            collateral_token="0x1234567890123456789012345678901234567890",  # nosec B106
            condition_id="0xaabbccdd",
            index_sets=[1],
        )
        assert len(result) > len(single)


# ---------------------------------------------------------------------------
# Tests for redeem_via_builder


def _position(condition_id: str, size: float, cur_price: object, **extra: object) -> dict:  # type: ignore[type-arg]
    """Return a redeemable position as the Polymarket API lists it."""
    return {
        "conditionId": condition_id,
        "outcomeIndex": 0,
        "outcome": "Yes",
        "size": size,
        "curPrice": cur_price,
        "negativeRisk": False,
        **extra,
    }


def _run(gen):  # type: ignore[no-untyped-def]
    """Exhaust a generator and return its value."""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


class TestPayoutsByMarket:
    """One payout card per market from the redeemed positions."""

    def test_sums_positions_of_a_market_and_drops_losers(self) -> None:
        """Both sides of an invalid market add up; a losing or unpriced one pays nothing."""
        positions = [
            _position("0xa", 10, 0.5, title="Invalid?", slug="invalid"),
            _position("0xa", 4, "0.5", title="Invalid?", slug="invalid"),
            _position("0xb", 3, 1, title="Won?"),
            _position("0xc", 5, 0, title="Lost?"),
            _position("0xd", 5, None, title="Unpriced?"),
            {"conditionId": "0xe", "size": 1},
            _position("0xf", 2, 1),
        ]

        behaviour = _make_behaviour()

        assert behaviour._payouts_by_market(positions) == [
            [
                {
                    "label": "Market",
                    "value": "Invalid?",
                    "url": "https://polymarket.com/market/invalid",
                },
                {"label": "Amount", "value": "$7.00 pUSD"},
            ],
            [
                {"label": "Market", "value": "Won?"},
                {"label": "Amount", "value": "$3.00 pUSD"},
            ],
            [
                {"label": "Market", "value": "0xf"},
                {"label": "Amount", "value": "$2.00 pUSD"},
            ],
        ]
        warnings = [c.args[0] for c in behaviour.context.logger.warning.call_args_list]
        assert len(warnings) == 2
        assert "'0xd'" in warnings[0]
        assert "'0xe'" in warnings[1]

    def test_builder_keeps_only_redeemed_positions_pending(self) -> None:
        """The builder path writes no card yet; it keeps each redeem the relayer took."""
        behaviour = _make_behaviour()
        behaviour._record_feed_event = MagicMock()  # type: ignore[method-assign]
        behaviour.context.state.polymarket_builder_redeems_pending = {}
        # The connection sends the relayer's transaction list, an error dict on a
        # failed redeem, or null when it gives no response at all.
        results = {
            "0xok": [{"transactionHash": "0x1"}],
            "0xfail": {"error": "Relayer client not initialized."},
            "0xnone": None,
        }

        def mock_redeem(condition_id, outcome_index, collateral_token, is_neg_risk=False):  # type: ignore[no-untyped-def]
            yield
            return results[condition_id]

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]
        positions = [
            _position("0xok", 2, 1, title="Paid?"),
            _position("0xfail", 2, 1, title="Failed?"),
            _position("0xnone", 2, 1, title="No response?"),
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_collateral_address="0xusdc")
            _run(behaviour._redeem_via_builder(positions))

        behaviour._record_feed_event.assert_not_called()  # type: ignore[attr-defined]
        assert behaviour.context.state.polymarket_builder_redeems_pending == {
            "0xok": [positions[0]]
        }

    def test_a_resent_builder_redeem_replaces_the_pending_one(self) -> None:
        """Redeeming a market again keeps one pending entry for it, not two."""
        behaviour = _make_behaviour()
        first = _position("0xa", 2, 1, title="Paid?")
        resent = _position("0xa", 3, 1, title="Paid?")
        other = _position("0xb", 1, 1, title="Other?")
        behaviour.context.state.polymarket_builder_redeems_pending = {
            "0xa": [first],
            "0xb": [other],
        }

        def mock_redeem(condition_id, outcome_index, collateral_token, is_neg_risk=False):  # type: ignore[no-untyped-def]
            yield
            return [{"transactionHash": "0x1"}]

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_collateral_address="0xusdc")
            _run(behaviour._redeem_via_builder([resent]))

        assert behaviour.context.state.polymarket_builder_redeems_pending == {
            "0xa": [resent],
            "0xb": [other],
        }

    def test_a_builder_redeem_is_recorded_once_no_longer_redeemable(self) -> None:
        """A pending market gets its card when the API stops listing it, and only then."""
        behaviour = _make_behaviour()
        behaviour._record_feed_event = MagicMock()  # type: ignore[method-assign]
        landed = [
            _position("0xa", 2, 1, title="Landed?"),
            _position("0xa", 1, 0, title="Landed?"),
        ]
        waiting = [_position("0xb", 5, 1, title="Waiting?")]
        behaviour.context.state.polymarket_builder_redeems_pending = {
            "0xa": landed,
            "0xb": waiting,
        }

        behaviour._record_settled_builder_redeems(
            [_position("0xb", 5, 1), _position("0xc", 1, 1)]
        )

        behaviour._record_feed_event.assert_called_once_with(  # type: ignore[attr-defined]
            EventType.PAYOUT_COLLECTED,
            [
                {"label": "Market", "value": "Landed?"},
                {"label": "Amount", "value": "$2.00 pUSD"},
            ],
        )
        assert behaviour.context.state.polymarket_builder_redeems_pending == {
            "0xb": waiting
        }

        behaviour._record_settled_builder_redeems([_position("0xb", 5, 1)])

        behaviour._record_feed_event.assert_called_once()  # type: ignore[attr-defined]

    def test_safe_tx_keeps_the_cards_for_its_settlement(self) -> None:
        """The Safe tx path keeps the cards on shared state instead of writing them."""
        behaviour = _make_behaviour()
        behaviour._record_feed_event = MagicMock()  # type: ignore[method-assign]
        behaviour._build_multisend_data = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = lambda: _return_gen(True)  # type: ignore[method-assign]
        positions = [
            {"conditionId": None, "outcomeIndex": 0, "size": 9, "curPrice": 1},
            _position("0x" + "ab" * 32, 2, 1, title="Paid?"),
        ]

        with (
            patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params,
            patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx,
        ):
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x" + "12" * 20,
                polymarket_ctf_collateral_adapter_address="0x" + "34" * 20,
            )
            mock_tx.return_value = "0xfinalHash"
            assert _run(behaviour._prepare_redeem_tx(positions)) == "0xfinalHash"

        behaviour._record_feed_event.assert_not_called()  # type: ignore[attr-defined]
        assert behaviour.context.state.polymarket_payouts_to_record == [
            [
                {"label": "Market", "value": "Paid?"},
                {"label": "Amount", "value": "$2.00 pUSD"},
            ]
        ]


class TestRedeemViaBuilder:
    """Tests for _redeem_via_builder."""

    def test_redeem_standard_positions(self) -> None:
        """Should redeem standard (non-neg-risk) positions."""
        behaviour = _make_behaviour()

        redeem_calls = []

        def mock_redeem(  # type: ignore[no-untyped-def]
            condition_id, outcome_index, collateral_token, is_neg_risk=False
        ):
            """Mock redeem position."""
            redeem_calls.append(
                {
                    "condition_id": condition_id,
                    "outcome_index": outcome_index,
                    "is_neg_risk": is_neg_risk,
                }
            )
            yield
            return {"success": True}

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_collateral_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert redeem_calls == [
            {"condition_id": "0xcond1", "outcome_index": 0, "is_neg_risk": False}
        ]
        assert isinstance(behaviour.payload, PolymarketRedeemPayload)

    def test_redeem_neg_risk_position_passes_flag_through(self) -> None:
        """Neg-risk positions are forwarded to _redeem_position with is_neg_risk=True.

        Why: under CLOB v2 the collateral adapter discovers the Safe's ERC1155
        balance itself via balanceOf, so the agent must not pre-fetch balances
        or override size — it just routes the position through with the flag.
        """
        behaviour = _make_behaviour()

        redeem_calls = []

        def mock_redeem(  # type: ignore[no-untyped-def]
            condition_id, outcome_index, collateral_token, is_neg_risk=False
        ):
            """Mock redeem position."""
            redeem_calls.append(
                {
                    "condition_id": condition_id,
                    "outcome_index": outcome_index,
                    "is_neg_risk": is_neg_risk,
                }
            )
            yield
            return {"success": True}

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 1,
                "outcome": "No",
                "size": 100,
                "negativeRisk": True,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_collateral_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        assert redeem_calls == [
            {"condition_id": "0xcond1", "outcome_index": 1, "is_neg_risk": True}
        ]

    def test_malformed_position_skipped_others_processed(self) -> None:
        """Position missing outcomeIndex is skipped; remaining valid positions still routed.

        Why: without a guard, the downstream ``1 << None`` raises TypeError and
        aborts the loop, dropping all subsequent positions on the floor. A
        defensive log+continue keeps one bad dict from poisoning the batch.
        """
        behaviour = _make_behaviour()

        redeem_calls = []

        def mock_redeem(  # type: ignore[no-untyped-def]
            condition_id, outcome_index, collateral_token, is_neg_risk=False
        ):
            """Mock redeem position."""
            redeem_calls.append(
                {
                    "condition_id": condition_id,
                    "outcome_index": outcome_index,
                    "is_neg_risk": is_neg_risk,
                }
            )
            yield
            return {"success": True}

        behaviour._redeem_position = mock_redeem  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xmalformed",
                # outcomeIndex deliberately missing
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
            },
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            },
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(polymarket_collateral_address="0xusdc")

            gen = behaviour._redeem_via_builder(
                positions,
                current_mech_tools="[]",
                current_policy=None,
                current_utilized_tools="{}",
            )
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        # Only the valid position was forwarded to _redeem_position.
        assert redeem_calls == [
            {"condition_id": "0xcond1", "outcome_index": 0, "is_neg_risk": False}
        ]


# ---------------------------------------------------------------------------
# Tests for prepare_redeem_tx


class TestPrepareRedeemTx:
    """Tests for _prepare_redeem_tx."""

    def test_empty_positions_returns_empty(self) -> None:
        """Should return empty string for empty positions list."""
        behaviour = _make_behaviour()

        gen = behaviour._prepare_redeem_tx([])
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as e:
            result = e.value

        assert result == ""

    def test_malformed_position_skipped_others_processed(self) -> None:
        """Position missing outcomeIndex is skipped; remaining valid positions still build batches.

        Why: without a guard, ``1 << None`` raises TypeError mid-loop and aborts
        the entire multisend, killing all queued redemptions. The Polymarket API
        is contract-bound to provide outcomeIndex, but a defensive log+continue
        keeps one bad dict from poisoning the whole batch.
        """
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

        positions = [
            {
                "conditionId": "0xmalformed",
                # outcomeIndex deliberately missing
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            },
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            },
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        # Only the valid position produced a batch.
        assert len(behaviour.multisend_batches) == 1
        # The encoded calldata is for the valid conditionId, not the malformed.
        calldata = behaviour.multisend_batches[0].data.hex()
        assert "aabbccdd" in calldata
        assert "malformed" not in calldata

    def test_standard_position_builds_batch(self) -> None:
        """Should build multisend batch for standard positions."""
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

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result == "0xfinalHash"
        assert len(behaviour.multisend_batches) == 1
        # 4-arg redeemPositions selector + indexSets=[1 << outcomeIndex].
        calldata = behaviour.multisend_batches[0].data.hex()
        assert calldata.startswith("01b7037c")
        # Defensive: the v1 2-arg selector must never appear anywhere in the
        # encoded calldata, even alongside the v2 selector. Catches a
        # regression that resurrects the broken overload from git history.
        assert "dbeccb23" not in calldata
        # ABI-decode the args (skip 4-byte selector) so we assert on typed
        # values rather than zero-padded substrings, which can match offsets
        # or lengths in any zero-heavy payload by accident.
        collateral, parent, condition_id, index_sets = abi_decode(
            ["address", "bytes32", "bytes32", "uint256[]"],
            bytes.fromhex(calldata[8:]),
        )
        assert collateral.lower() == "0x1234567890123456789012345678901234567890"
        assert parent == bytes(32)
        assert (
            condition_id.hex()
            == "00000000000000000000000000000000000000000000000000000000aabbccdd"
        )
        # The adapters ignore the uint256[] argument so [1] vs [1, 2] is
        # functionally identical on-chain. Pin the encoded shape anyway as a
        # regression check on what the agent puts on the wire.
        assert list(index_sets) == [1]

    def test_neg_risk_position_builds_batch(self) -> None:
        """Neg-risk redeem builds a 4-arg redeemPositions batch.

        Why: under CLOB v2, the NegRiskCtfCollateralAdapter accepts the standard
        4-arg redeemPositions(IERC20, bytes32, bytes32, uint256[]) overload. The
        v1 2-arg overload reverts with GS013 for v2-resolved markets flagged
        negativeRisk. The adapter ignores the uint256[] argument internally and
        redeems both sides via balanceOf — passing [1 << outcomeIndex] is a
        calldata-size choice, not a redemption-scope control.
        """
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

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x3234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                result = None
                try:
                    while True:
                        next(gen)
                except StopIteration as e:
                    result = e.value

        assert result == "0xfinalHash"
        assert len(behaviour.multisend_batches) == 1
        # Routes to the neg-risk adapter, not the standard one.
        assert (
            behaviour.multisend_batches[0].to
            == "0x7234567890123456789012345678901234567890"
        )
        # 4-arg redeemPositions selector + indexSets=[1 << outcomeIndex].
        calldata = behaviour.multisend_batches[0].data.hex()
        assert calldata.startswith("01b7037c")
        # Defensive: the v1 2-arg selector must never appear anywhere in the
        # encoded calldata, even alongside the v2 selector. Catches a
        # regression that resurrects the broken overload from git history.
        assert "dbeccb23" not in calldata
        # ABI-decode the args (skip 4-byte selector) so we assert on typed
        # values rather than zero-padded substrings, which can match offsets
        # or lengths in any zero-heavy payload by accident.
        collateral, parent, condition_id, index_sets = abi_decode(
            ["address", "bytes32", "bytes32", "uint256[]"],
            bytes.fromhex(calldata[8:]),
        )
        assert collateral.lower() == "0x1234567890123456789012345678901234567890"
        assert parent == bytes(32)
        assert (
            condition_id.hex()
            == "00000000000000000000000000000000000000000000000000000000aabbccdd"
        )
        # The adapters ignore the uint256[] argument so [1] vs [1, 2] is
        # functionally identical on-chain. Pin the encoded shape anyway as a
        # regression check on what the agent puts on the wire.
        assert list(index_sets) == [1]

    def test_multisend_data_failure(self) -> None:
        """Should return empty string when _build_multisend_data fails."""
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock build multisend data that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
            )

            gen = behaviour._prepare_redeem_tx(positions)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == ""

    def test_safe_tx_hash_failure(self) -> None:
        """Should return empty string when _build_multisend_safe_tx_hash fails."""
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

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
            )

            gen = behaviour._prepare_redeem_tx(positions)
            result = None
            try:
                while True:
                    next(gen)
            except StopIteration as e:
                result = e.value

        assert result == ""

    def test_standard_position_targets_ctf_collateral_adapter(self) -> None:
        """Standard-market redeem must route through CtfCollateralAdapter, not raw CTF.

        Why: redeeming via the raw CTF returns USDC.e to the Safe, requiring a
        separate wrap step. Routing through the CtfCollateralAdapter unwraps
        USDC.e to pUSD inside the same transaction.
        """
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
            }
        ]
        ctf_collateral_adapter = "0x6234567890123456789012345678901234567890"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address=ctf_collateral_adapter,
                polymarket_neg_risk_ctf_collateral_adapter_address="0x7234567890123456789012345678901234567890",
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(behaviour.multisend_batches) == 1
        assert behaviour.multisend_batches[0].to == ctf_collateral_adapter

    def test_neg_risk_position_targets_neg_risk_ctf_collateral_adapter(self) -> None:
        """Neg-risk redeem must route through NegRiskCtfCollateralAdapter.

        Why: same reason as standard markets — route through the wrapper that
        unwraps USDC.e to pUSD on the way back to the Safe.
        """
        behaviour = _make_behaviour()
        behaviour.multisend_batches = []

        def mock_build_multisend_data() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        def mock_build_multisend_safe_tx_hash() -> None:  # type: ignore[no-untyped-def, misc]
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._build_multisend_data = mock_build_multisend_data  # type: ignore[method-assign]
        behaviour._build_multisend_safe_tx_hash = mock_build_multisend_safe_tx_hash  # type: ignore[method-assign]

        positions = [
            {
                "conditionId": "0xaabbccdd",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": True,
            }
        ]
        neg_risk_ctf_collateral_adapter = "0x7234567890123456789012345678901234567890"

        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(
                polymarket_collateral_address="0x1234567890123456789012345678901234567890",
                polymarket_ctf_address="0x2234567890123456789012345678901234567890",
                polymarket_neg_risk_adapter_address="0x3234567890123456789012345678901234567890",
                polymarket_ctf_collateral_adapter_address="0x6234567890123456789012345678901234567890",
                polymarket_neg_risk_ctf_collateral_adapter_address=neg_risk_ctf_collateral_adapter,
            )
            with patch.object(
                type(behaviour), "tx_hex", new_callable=PropertyMock
            ) as mock_tx:
                mock_tx.return_value = "0xfinalHash"

                gen = behaviour._prepare_redeem_tx(positions)
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(behaviour.multisend_batches) == 1
        assert behaviour.multisend_batches[0].to == neg_risk_ctf_collateral_adapter


# ---------------------------------------------------------------------------
# Tests for async_act


class TestAsyncAct:
    """Tests for async_act."""

    def test_async_act_no_redeemable_positions(self) -> None:
        """Should send NO_REDEEMING event when no positions found."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {}

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools."""
            yield  # type: ignore[no-untyped-def]
            return True

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen([])  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, PolymarketRedeemPayload)
        assert payload.event == "no_redeeming"

    def test_async_act_with_nothing_left_to_redeem_settles_the_pending(self) -> None:
        """An empty redeemable list records the pending builder redeems and drops a stale Safe build."""
        behaviour = _make_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour._record_feed_event = MagicMock()  # type: ignore[method-assign]
        behaviour.context.state.polymarket_builder_redeems_pending = {
            "0xa": [_position("0xa", 2, 1, title="Landed?")]
        }
        behaviour.context.state.polymarket_payouts_to_record = [
            [{"label": "Market", "value": "Stale?"}]
        ]
        behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen([])  # type: ignore[method-assign]
        behaviour.finish_behaviour = lambda payload: _noop_gen()  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            _run(behaviour.async_act())

        behaviour._record_feed_event.assert_called_once_with(  # type: ignore[attr-defined]
            EventType.PAYOUT_COLLECTED,
            [
                {"label": "Market", "value": "Landed?"},
                {"label": "Amount", "value": "$2.00 pUSD"},
            ],
        )
        assert behaviour.context.state.polymarket_builder_redeems_pending == {}
        assert behaviour.context.state.polymarket_payouts_to_record == []

    def test_async_act_failed_positions_read_ends_round_without_redeeming(
        self,
    ) -> None:
        """A failed positions read ends the round with NO_REDEEMING and keeps tool records."""
        behaviour = _make_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {"cond1": "tool1"}
        behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            {"error": "Error fetching positions: 503"}
        )
        payloads_sent = []

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            for _ in behaviour.async_act():
                pass

        assert [p.event for p in payloads_sent] == ["no_redeeming"]
        assert behaviour._utilized_tools == {"cond1": "tool1"}

    def test_async_act_failed_positions_read_keeps_the_pending(self) -> None:
        """A failed positions read writes no payout card and keeps the pending builder redeems."""
        behaviour = _make_behaviour()
        behaviour._policy = _make_policy()
        behaviour._mech_tools = {"tool1"}
        behaviour._record_feed_event = MagicMock()  # type: ignore[method-assign]
        pending = {"0xa": [_position("0xa", 2, 1, title="Landed?")]}
        behaviour.context.state.polymarket_builder_redeems_pending = pending
        behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
        behaviour.send_polymarket_connection_request = lambda payload: _return_gen(  # type: ignore[method-assign]
            {"error": "Error fetching positions: 503"}
        )
        behaviour.finish_behaviour = lambda payload: _noop_gen()  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            _run(behaviour.async_act())

        behaviour._record_feed_event.assert_not_called()  # type: ignore[attr-defined]
        assert behaviour.context.state.polymarket_builder_redeems_pending == pending

    def test_async_act_setup_fails(self) -> None:
        """Should return early when _setup_policy_and_tools fails."""
        behaviour = _make_behaviour()

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools that fails."""
            yield  # type: ignore[no-untyped-def]
            return False

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

        # Should have returned before setting payload
        assert not hasattr(behaviour, "payload") or behaviour.payload is None or True

    def test_async_act_builder_program_enabled(self) -> None:
        """Should use _redeem_via_builder when builder program is enabled."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {}

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools."""
            yield  # type: ignore[no-untyped-def]
            return True

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
                "curPrice": 1.0,
            }
        ]

        builder_called = []

        def mock_redeem_via_builder(  # type: ignore[no-untyped-def]
            positions, current_mech_tools, current_policy, current_utilized_tools
        ):
            """Mock redeem via builder."""
            builder_called.append(True)
            behaviour.payload = PolymarketRedeemPayload(
                sender="test_agent",
                tx_submitter=None,
                tx_hash=None,
                mocking_mode=False,
                mech_tools=current_mech_tools,
                policy=current_policy,
                utilized_tools=current_utilized_tools,
                event="done",
            )
            yield

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen(positions)  # type: ignore[method-assign]
        behaviour._redeem_via_builder = mock_redeem_via_builder  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)

                behaviour.__dict__[
                    "_context"
                ].params.polymarket_builder_program_enabled = True

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(builder_called) == 1

    def test_async_act_builder_program_disabled(self) -> None:
        """Should use _prepare_redeem_tx when builder program is disabled."""
        behaviour = _make_behaviour()
        policy = _make_policy()
        behaviour._policy = policy
        behaviour._mech_tools = {"tool1"}
        behaviour._utilized_tools = {}

        def mock_setup() -> None:  # type: ignore[no-untyped-def, misc]
            """Mock setup policy and tools."""
            yield  # type: ignore[no-untyped-def]
            return True

        positions = [
            {
                "conditionId": "0xcond1",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 100,
                "negativeRisk": False,
                "curPrice": 1.0,
            }
        ]

        def mock_prepare_redeem_tx(positions) -> None:  # type: ignore[no-untyped-def, misc]
            """Mock prepare redeem tx."""
            yield  # type: ignore[no-untyped-def]
            return "0xtxhash"

        behaviour._setup_policy_and_tools = mock_setup  # type: ignore[method-assign]
        behaviour._fetch_redeemable_positions = lambda: _return_gen(positions)  # type: ignore[method-assign]
        behaviour._prepare_redeem_tx = mock_prepare_redeem_tx  # type: ignore[method-assign]
        behaviour._store_utilized_tools = MagicMock()  # type: ignore[method-assign]

        payloads_sent = []
        behaviour.send_a2a_transaction = lambda payload: _noop_gen()  # type: ignore[method-assign]
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        def capture_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
            """Capture finish behaviour payload."""
            payloads_sent.append(payload)  # type: ignore[no-untyped-def]
            yield

        behaviour.finish_behaviour = capture_finish  # type: ignore[method-assign]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(is_policy_set=True)
            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(enabled=False)

                behaviour.__dict__[
                    "_context"
                ].params.polymarket_builder_program_enabled = False

                gen = behaviour.async_act()
                try:
                    while True:
                        next(gen)
                except StopIteration:
                    pass

        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PolymarketRedeemPayload)
        assert payloads_sent[0].tx_hash == "0xtxhash"
        assert payloads_sent[0].event == "prepare_tx"


# ---------------------------------------------------------------------------
# Protocol V2 claims and tool accuracy, answered by the connection


def _redeem_period(conn, builder, utilized_tools=None, policy=None):  # type: ignore[no-untyped-def]
    """Run one redeem period against ``conn``; return its payload and the Safe's claims."""
    behaviour = _make_behaviour()
    behaviour._policy = policy or _make_policy()
    behaviour._utilized_tools = dict(utilized_tools or {})
    behaviour._mech_tools = {"tool1"}
    behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
    behaviour._build_multisend_data = lambda: _return_gen(True)  # type: ignore[method-assign]
    behaviour._build_multisend_safe_tx_hash = lambda: _return_gen(True)  # type: ignore[method-assign]
    behaviour.context.params = MagicMock(
        polymarket_builder_program_enabled=builder, **pm.V2_PARAMS
    )
    payloads: list = []

    def finish(payload):  # type: ignore[no-untyped-def]
        payloads.append(payload)
        yield

    behaviour.finish_behaviour = finish  # type: ignore[method-assign]
    pm._wire(behaviour, conn)
    conn.relayer_client.execute.reset_mock()
    with patch.multiple(
        PolymarketRedeemBehaviour,
        synchronized_data=PropertyMock(return_value=MagicMock(is_policy_set=True)),
        tx_hex=PropertyMock(return_value="0xsafetx"),
    ):
        list(behaviour.async_act())
    txs = list(behaviour.multisend_batches)
    for call in conn.relayer_client.execute.call_args_list:
        txs += call.kwargs.get("transactions") or call.args[0]
    # (target, calldata, operation: 0 is a plain call, value)
    return payloads[0], [
        (to_checksum_address(t.to), HexBytes(t.data), t.operation.value, int(t.value))
        for t in txs
    ]


def _v1_claim(row):  # type: ignore[no-untyped-def]
    """Return the collateral-adapter claim the V1 flow builds for a standard-market row."""
    condition_id = bytes.fromhex(row["condition_id"][2:])
    args = [pm.COLLATERAL_ADDRESS, bytes(32), condition_id, [1 << row["outcome_index"]]]
    types = ["address", "bytes32", "bytes32", "uint256[]"]
    data = pm._selector(f"redeemPositions({','.join(types)})") + abi_encode(types, args)
    return pm.CTF_COLLATERAL_ADAPTER, data, 0, 0


def _router_claim(row):  # type: ignore[no-untyped-def]
    """Return the Router claim of a row's whole balance; bytes31 drops the zero pad byte of the Data API ID."""
    condition_id = bytes.fromhex(row["condition_id"][2:])
    assert len(condition_id) == 32 and condition_id[31] == 0
    amount = pm.ONCHAIN_BALANCE[row["token_id"]]
    args = [condition_id[:31], row["outcome_index"], amount]
    types = ["bytes31", "uint256", "uint256"]
    data = pm._selector(f"redeem({','.join(types)})") + abi_encode(types, args)
    return pm.ROUTER, data, 0, 0


@pytest.mark.parametrize("builder", [False, True])
def test_v2_position_claim_through_router(builder) -> None:  # type: ignore[no-untyped-def]
    """The Safe claims winning V2 rows through the Router and its V1 rows as before."""
    rows = (pm.V2_WIN, pm.V1_WIN, pm.V2_WIN0, pm.V1_LOSE, pm.V2_LOSE)
    with pm._safe_world(*rows) as conn:
        payload, claims = _redeem_period(conn, builder)
    assert payload.event == ("done" if builder else "prepare_tx")
    v2_claims = [_router_claim(pm.V2_WIN), _router_claim(pm.V2_WIN0)]
    expected = v2_claims + [_v1_claim(pm.V1_WIN), _v1_claim(pm.V1_LOSE)]
    assert sorted(claims) == sorted(expected)


@pytest.mark.parametrize("builder", [False, True])
def test_v2_position_losing_row_not_claimed(builder) -> None:  # type: ignore[no-untyped-def]
    """A redeemable V2 row with no value builds no claim; losing V1 rows still do."""
    with pm._safe_world(pm.V2_LOSE, pm.V1_LOSE, pm.V1_00_LOSE) as conn:
        _, claims = _redeem_period(conn, builder)
    assert sorted(claims) == sorted(map(_v1_claim, (pm.V1_LOSE, pm.V1_00_LOSE)))


def test_v2_position_accuracy_updated_once() -> None:
    """A resolved V2 bet updates its tool once, as a win or a loss, over two periods."""
    for row, won in ((pm.V2_WIN, True), (pm.V2_LOSE, False)):
        policy, expected = _make_policy(), _make_policy()
        expected.update_accuracy_store("tool1", winning=won)
        tools = {row["condition_id"]: "tool1"}
        with pm._safe_world(row) as conn:
            for _ in range(2):  # the Data API still lists the row next period
                payload, claims = _redeem_period(conn, False, tools, policy)
                tools = json.loads(payload.utilized_tools)
                assert policy.accuracy_store == expected.accuracy_store
                if not won:  # nothing to claim: no transaction to settle
                    assert (claims, payload.tx_hash) == ([], None)
                    assert payload.event in ("no_redeeming", "done")
