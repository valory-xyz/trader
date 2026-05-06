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

"""Tests for the withdrawal rounds and behaviours in decision_maker_abci."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
    DegenerateRound,
)
from packages.valory.skills.chatui_abci.models import (
    WITHDRAWAL_STATE_COMPLETE,
    WITHDRAWAL_STATE_ERRORED,
    WITHDRAWAL_STATE_SELLING,
)
from packages.valory.skills.decision_maker_abci.behaviours.omen_withdraw import (
    OmenWithdrawBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_withdraw import (
    PolymarketWithdrawBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.round_behaviour import (
    AgentDecisionMakerRoundBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import WithdrawalPayload
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.omen_withdraw import (
    OmenWithdrawRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_withdraw import (
    PolymarketWithdrawRound,
)
from packages.valory.skills.decision_maker_abci.states.withdrawal_idle import (
    WithdrawalIdleRound,
)

# ---------------------------------------------------------------------------
# Round structural tests
# ---------------------------------------------------------------------------


class TestRoundClasses:
    """The new round classes must inherit from the right framework types."""

    def test_polymarket_withdraw_inherits_collect_same_until_threshold(self) -> None:
        """PolymarketWithdrawRound is a CollectSameUntilThresholdRound subclass."""
        assert issubclass(PolymarketWithdrawRound, CollectSameUntilThresholdRound)

    def test_omen_withdraw_inherits_collect_same_until_threshold(self) -> None:
        """OmenWithdrawRound is a CollectSameUntilThresholdRound subclass."""
        assert issubclass(OmenWithdrawRound, CollectSameUntilThresholdRound)

    def test_withdrawal_idle_is_degenerate(self) -> None:
        """WithdrawalIdleRound is a DegenerateRound subclass (terminal halt)."""
        assert issubclass(WithdrawalIdleRound, DegenerateRound)

    def test_polymarket_withdraw_uses_withdrawal_payload(self) -> None:
        """PolymarketWithdrawRound posts WithdrawalPayload values."""
        assert PolymarketWithdrawRound.payload_class is WithdrawalPayload

    def test_omen_withdraw_uses_withdrawal_payload(self) -> None:
        """OmenWithdrawRound posts WithdrawalPayload values."""
        assert OmenWithdrawRound.payload_class is WithdrawalPayload

    def test_polymarket_withdraw_done_event(self) -> None:
        """PolymarketWithdrawRound emits WITHDRAWAL_DONE on consensus."""
        assert PolymarketWithdrawRound.done_event == Event.WITHDRAWAL_DONE

    def test_omen_withdraw_done_event(self) -> None:
        """OmenWithdrawRound emits WITHDRAWAL_DONE on consensus."""
        assert OmenWithdrawRound.done_event == Event.WITHDRAWAL_DONE


# ---------------------------------------------------------------------------
# AbciApp wiring
# ---------------------------------------------------------------------------


class TestAbciAppWithdrawalWiring:
    """The DecisionMakerAbciApp must wire the new rounds correctly."""

    def test_polymarket_withdraw_routes_to_idle_on_done(self) -> None:
        """WITHDRAWAL_DONE from PolymarketWithdrawRound enters WithdrawalIdleRound."""
        tx = DecisionMakerAbciApp.transition_function
        assert tx[PolymarketWithdrawRound][Event.WITHDRAWAL_DONE] is WithdrawalIdleRound

    def test_polymarket_withdraw_routes_to_idle_on_round_timeout(self) -> None:
        """WITHDRAWAL_ROUND_TIMEOUT from PolymarketWithdrawRound → WithdrawalIdleRound."""
        tx = DecisionMakerAbciApp.transition_function
        assert (
            tx[PolymarketWithdrawRound][Event.WITHDRAWAL_ROUND_TIMEOUT]
            is WithdrawalIdleRound
        )

    def test_omen_withdraw_routes_to_idle_on_done(self) -> None:
        """WITHDRAWAL_DONE from OmenWithdrawRound enters WithdrawalIdleRound."""
        tx = DecisionMakerAbciApp.transition_function
        assert tx[OmenWithdrawRound][Event.WITHDRAWAL_DONE] is WithdrawalIdleRound

    def test_omen_withdraw_routes_to_idle_on_round_timeout(self) -> None:
        """WITHDRAWAL_ROUND_TIMEOUT from OmenWithdrawRound → WithdrawalIdleRound."""
        tx = DecisionMakerAbciApp.transition_function
        assert (
            tx[OmenWithdrawRound][Event.WITHDRAWAL_ROUND_TIMEOUT] is WithdrawalIdleRound
        )

    def test_withdraw_rounds_use_dedicated_timeout_event(self) -> None:
        """Withdraw rounds emit WITHDRAWAL_ROUND_TIMEOUT, not the generic 30s ROUND_TIMEOUT.

        Sharing ROUND_TIMEOUT would mean the global 30s timer applies to a
        sweep that may legitimately take minutes; the dedicated event lets
        operators tune `withdrawal_round_timeout` independently.
        """
        tx = DecisionMakerAbciApp.transition_function
        assert Event.ROUND_TIMEOUT not in tx[PolymarketWithdrawRound]
        assert Event.ROUND_TIMEOUT not in tx[OmenWithdrawRound]

    def test_withdrawal_round_timeout_default_in_event_to_timeout(self) -> None:
        """The new event has a default seconds value in the AbciApp's timeout map."""
        assert Event.WITHDRAWAL_ROUND_TIMEOUT in DecisionMakerAbciApp.event_to_timeout
        assert DecisionMakerAbciApp.event_to_timeout[Event.WITHDRAWAL_ROUND_TIMEOUT] > 0

    def test_idle_round_has_no_outgoing_transitions(self) -> None:
        """WithdrawalIdleRound is terminal — empty transition map (DegenerateRound)."""
        tx = DecisionMakerAbciApp.transition_function
        assert tx[WithdrawalIdleRound] == {}

    def test_idle_round_in_final_states(self) -> None:
        """WithdrawalIdleRound is registered as a final state of the AbciApp."""
        assert WithdrawalIdleRound in DecisionMakerAbciApp.final_states

    def test_withdraw_rounds_in_initial_states(self) -> None:
        """Both withdraw rounds are initial states (entered cross-skill from the gate)."""
        assert PolymarketWithdrawRound in DecisionMakerAbciApp.initial_states
        assert OmenWithdrawRound in DecisionMakerAbciApp.initial_states

    def test_withdraw_rounds_have_empty_db_pre_conditions(self) -> None:
        """Cross-skill entry needs no pre-existing DB keys for either withdraw round."""
        pre = DecisionMakerAbciApp.db_pre_conditions
        assert pre[PolymarketWithdrawRound] == set()
        assert pre[OmenWithdrawRound] == set()

    def test_idle_round_has_empty_db_post_conditions(self) -> None:
        """WithdrawalIdleRound is terminal with no DB-key post-conditions."""
        post = DecisionMakerAbciApp.db_post_conditions
        assert WithdrawalIdleRound in post
        assert post[WithdrawalIdleRound] == set()


# ---------------------------------------------------------------------------
# Round behaviour registration
# ---------------------------------------------------------------------------


class TestRoundBehaviourRegistration:
    """The new behaviours must be registered with the round behaviour."""

    def test_polymarket_withdraw_behaviour_registered(self) -> None:
        """PolymarketWithdrawBehaviour appears in the registered behaviour set."""
        assert (
            PolymarketWithdrawBehaviour in AgentDecisionMakerRoundBehaviour.behaviours
        )

    def test_omen_withdraw_behaviour_registered(self) -> None:
        """OmenWithdrawBehaviour appears in the registered behaviour set."""
        assert OmenWithdrawBehaviour in AgentDecisionMakerRoundBehaviour.behaviours

    def test_polymarket_withdraw_behaviour_matches_polymarket_withdraw_round(
        self,
    ) -> None:
        """PolymarketWithdrawBehaviour.matching_round is PolymarketWithdrawRound."""
        assert PolymarketWithdrawBehaviour.matching_round is PolymarketWithdrawRound

    def test_omen_withdraw_behaviour_matches_omen_withdraw_round(self) -> None:
        """OmenWithdrawBehaviour.matching_round is OmenWithdrawRound."""
        assert OmenWithdrawBehaviour.matching_round is OmenWithdrawRound


# ---------------------------------------------------------------------------
# Behaviour async_act stubs
# ---------------------------------------------------------------------------


class _TestablePolymarketWithdraw(PolymarketWithdrawBehaviour):
    """Shadows read-only AEA properties for testing."""

    context = None  # type: ignore[assignment]


class _TestableOmenWithdraw(OmenWithdrawBehaviour):
    """Shadows read-only AEA properties for testing."""

    context = None  # type: ignore[assignment]


CHATUI_PARAM_STORE = "chatui_param_store.json"

# Distinct fixtures for the per-position retry-loop tests.
TOK_A = "0xa1"
TOK_B = "0xb2"
TOK_C = "0xc3"


def _seed_store(store_path: Path, **overrides: Any) -> Path:
    """Drop a chatui_param_store.json into ``store_path`` with minimal fields."""
    base = {
        "withdrawal_mode": True,
        "withdrawal_state": "armed",
        "withdrawal_fills": [],
        "withdrawal_errors": [],
    }
    base.update(overrides)
    f = store_path / CHATUI_PARAM_STORE
    f.write_text(json.dumps(base))
    return f


def _read_store(store_path: Path) -> Dict[str, Any]:
    """Load the JSON store at ``store_path/CHATUI_PARAM_STORE``."""
    with open(store_path / CHATUI_PARAM_STORE, "r") as fh:
        return json.load(fh)


def _make_position(
    token_id: str = TOK_A,
    size: float = 100.0,
    redeemable: bool = False,
    neg_risk: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mimic the Polymarket data-API positions schema."""
    p = {
        "asset": token_id,
        "size": size,
        "redeemable": redeemable,
        "negativeRisk": neg_risk,
        "conditionId": f"cond_{token_id}",
    }
    if extra:
        p.update(extra)
    return p


def _make_behaviour(
    tmp_path: Path,
    backoff: Optional[List[int]] = None,
) -> "_TestablePolymarketWithdraw":
    """Build a behaviour with mocked context / params and a tmp store path."""
    if backoff is None:
        backoff = [10, 30, 60]
    behaviour = object.__new__(_TestablePolymarketWithdraw)
    behaviour.context = MagicMock()  # type: ignore[assignment]
    behaviour.context.agent_address = "agent_x"
    behaviour.context.params.store_path = tmp_path
    behaviour.context.params.withdrawal_max_fak_attempts = len(backoff)
    behaviour.context.params.withdrawal_fak_backoff_s = backoff
    return behaviour


def _wire_helpers(
    behaviour: "_TestablePolymarketWithdraw",
    captured_payload: Dict[str, Any],
    captured_sleep: List[int],
) -> None:
    """Stub finish_behaviour + sleep so async_act can be exhausted in-process."""

    def fake_finish(payload: WithdrawalPayload):  # type: ignore[no-untyped-def]
        captured_payload["payload"] = payload
        yield

    def fake_sleep(s):  # type: ignore[no-untyped-def]
        captured_sleep.append(s)
        yield

    behaviour.finish_behaviour = fake_finish  # type: ignore[method-assign]
    behaviour.sleep = fake_sleep  # type: ignore[method-assign]


def _make_request_router(
    *,
    refresh_responses: Optional[List[Optional[Dict[str, Any]]]] = None,
    fetch_responses: Optional[List[Any]] = None,
    sell_responses: Optional[List[Optional[Dict[str, Any]]]] = None,
):  # type: ignore[no-untyped-def]
    """Build a fake send_polymarket_connection_request that pops by request_type.

    Each kw list is a queue: the request handler pops the head per call. ``None``
    in a queue means "the connection returned None" (timeout / dispatch failure).
    """
    refresh = list(refresh_responses or [])
    fetch = list(fetch_responses or [])
    sell = list(sell_responses or [])
    sent_payloads: List[Dict[str, Any]] = []

    def _router(payload: Dict[str, Any]):  # type: ignore[no-untyped-def]
        sent_payloads.append(payload)
        rt = payload.get("request_type")
        if rt == RequestType.REFRESH_BALANCE_ALLOWANCE.value:
            return refresh.pop(0) if refresh else None
        if rt == RequestType.FETCH_ALL_POSITIONS.value:
            return fetch.pop(0) if fetch else None
        if rt == RequestType.SELL_POSITION.value:
            return sell.pop(0) if sell else None
        raise AssertionError(f"unexpected request_type: {rt}")

    def gen_router(payload: Dict[str, Any]):  # type: ignore[no-untyped-def]
        yield
        return _router(payload)

    return gen_router, sent_payloads


class TestPolymarketWithdrawBehaviourSellLoop:
    """Phase-3 tests for the real PolymarketWithdrawBehaviour."""

    def test_empty_positions_completes_without_records(self, tmp_path: Path) -> None:
        """Refresh OK + zero unredeemable positions → state goes complete, no records."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[[]],  # empty list of positions
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert store["withdrawal_fills"] == []
        assert store["withdrawal_errors"] == []
        assert isinstance(captured_payload["payload"], WithdrawalPayload)
        # No backoffs needed.
        assert captured_sleep == []

    def test_filters_out_redeemable_and_zero_size(self, tmp_path: Path) -> None:
        """Redeemable positions and dust (<=0) are dropped; only the real ones sell."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [
            _make_position(TOK_A, size=100.0, redeemable=False),
            _make_position(TOK_B, size=50.0, redeemable=True),  # dropped
            _make_position(TOK_C, size=0.0, redeemable=False),  # dropped (dust)
        ]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 100.0,
            "filled_usdc": 43.0,
            "fill_price": 0.43,
            "raw": {},
            "signed_order_json": None,
        }
        router, sent = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        # Only one SELL was issued — for TOK_A.
        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        assert len(sell_payloads) == 1
        assert sell_payloads[0]["params"]["token_id"] == TOK_A

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        assert store["withdrawal_fills"][0]["token_id"] == TOK_A
        assert store["withdrawal_fills"][0]["shares_sold"] == 100.0
        assert store["withdrawal_errors"] == []

    def test_drops_position_missing_asset(self, tmp_path: Path) -> None:
        """A position without an ``asset`` field cannot be sold; record an error."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [
            _make_position(TOK_A, size=100.0),
            {"size": 50.0, "redeemable": False},  # missing asset
        ]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 100.0,
            "filled_usdc": 43.0,
            "fill_price": 0.43,
            "raw": {},
            "signed_order_json": None,
        }
        router, sent = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        # The malformed entry got recorded as an error; the well-formed one filled.
        assert len(store["withdrawal_fills"]) == 1
        assert len(store["withdrawal_errors"]) == 1
        assert "malformed" in store["withdrawal_errors"][0]["reason"].lower()
        # Final state is errored because there's at least one error record.
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED

    def test_single_position_full_fill_first_attempt(self, tmp_path: Path) -> None:
        """One position, one FAK call, one fill record, state complete."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 100.0,
            "filled_usdc": 43.0,
            "fill_price": 0.43,
            "raw": {},
            "signed_order_json": "abc",
        }
        router, sent = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        # Only one sell was needed.
        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        assert len(sell_payloads) == 1
        # No backoff was ever invoked.
        assert captured_sleep == []

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        fill = store["withdrawal_fills"][0]
        assert fill["token_id"] == TOK_A
        assert fill["shares_sold"] == 100.0
        assert fill["fill_price"] == pytest.approx(0.43)
        assert store["withdrawal_errors"] == []

    def test_partial_fills_aggregated_volume_weighted(self, tmp_path: Path) -> None:
        """Three FAK attempts, partial each time, completing the residual.

        One fill record with volume-weighted price is emitted; partial fills
        are NOT recorded individually (per §4.1).
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        # 60 @ 0.40 + 30 @ 0.50 + 10 @ 0.60 = 100 shares total, $50 total
        # → vw price = 50 / 100 = 0.50
        sell_responses = [
            {
                "order_id": "o-1",
                "status": "matched",
                "filled_shares": 60.0,
                "filled_usdc": 24.0,
                "fill_price": 0.40,
                "raw": {},
                "signed_order_json": "s1",
            },
            {
                "order_id": "o-2",
                "status": "matched",
                "filled_shares": 30.0,
                "filled_usdc": 15.0,
                "fill_price": 0.50,
                "raw": {},
                "signed_order_json": "s2",
            },
            {
                "order_id": "o-3",
                "status": "matched",
                "filled_shares": 10.0,
                "filled_usdc": 6.0,
                "fill_price": 0.60,
                "raw": {},
                "signed_order_json": "s3",
            },
        ]
        router, sent = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=sell_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        # Three sells, each with the residual amount.
        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        assert [p["params"]["amount"] for p in sell_payloads] == [100.0, 40.0, 10.0]

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        fill = store["withdrawal_fills"][0]
        assert fill["shares_sold"] == 100.0
        # Volume-weighted average: $45 / 100 shares = 0.45.
        assert fill["fill_price"] == pytest.approx(0.45)
        assert store["withdrawal_errors"] == []

    def test_signed_order_cache_invalidated_after_partial_fill(
        self, tmp_path: Path
    ) -> None:
        """Any non-zero filled_shares drops the cached signed order on the next attempt.

        Rationale: residual changes, so the next sign needs a fresh amount.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        # Attempt 1: partial fill 60 → cache cleared
        # Attempt 2: error (no fill) → cache populated for retry
        # Attempt 3: complete the residual
        sell_responses: List[Optional[Dict[str, Any]]] = [
            {
                "order_id": "o-1",
                "status": "matched",
                "filled_shares": 60.0,
                "filled_usdc": 24.0,
                "fill_price": 0.40,
                "raw": {},
                "signed_order_json": "s-from-attempt-1",
            },
            {
                "error": "transient backend",
                "signed_order_json": "s-from-attempt-2",
            },
            {
                "order_id": "o-3",
                "status": "matched",
                "filled_shares": 40.0,
                "filled_usdc": 20.0,
                "fill_price": 0.50,
                "raw": {},
                "signed_order_json": "s-from-attempt-3",
            },
        ]
        router, sent = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=sell_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        # Attempt 1: no cache provided.
        assert "cached_signed_order_json" not in sell_payloads[0]["params"]
        # Attempt 2: cache should be CLEARED (not "s-from-attempt-1") because
        # of the partial fill in attempt 1.
        assert "cached_signed_order_json" not in sell_payloads[1]["params"]
        # Attempt 3: error in attempt 2 carries cache forward, so cache IS sent.
        assert (
            sell_payloads[2]["params"].get("cached_signed_order_json")
            == "s-from-attempt-2"
        )

    def test_residual_after_max_attempts_records_error(self, tmp_path: Path) -> None:
        """Three failed FAKs (no fill) → one error record with full residual."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        # Three tries, all return zero-filled (status "live", not an SDK error).
        zero_resp = {
            "order_id": "live-1",
            "status": "live",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
            "signed_order_json": "s",
        }
        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=[zero_resp, zero_resp, zero_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1
        err = store["withdrawal_errors"][0]
        assert err["token_id"] == TOK_A
        assert err["shares_remaining"] == 100.0
        assert "no liquidity" in err["reason"].lower()
        # Two backoff sleeps between three attempts.
        assert captured_sleep == [1, 1]

    def test_partial_then_stuck_records_error_with_residual_only(
        self, tmp_path: Path
    ) -> None:
        """Partial filled, then stuck — one error record with the residual share count.

        Per §4.1: partials are NOT split between fills + errors. The on-chain
        record (via get_trades) is the audit trail for what filled.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        sell_responses = [
            {
                "order_id": "o-1",
                "status": "matched",
                "filled_shares": 40.0,
                "filled_usdc": 16.0,
                "fill_price": 0.40,
                "raw": {},
                "signed_order_json": "s1",
            },
            {
                "order_id": "live-2",
                "status": "live",
                "filled_shares": 0.0,
                "filled_usdc": 0.0,
                "fill_price": 0.0,
                "raw": {},
                "signed_order_json": "s2",
            },
            {
                "order_id": "live-3",
                "status": "live",
                "filled_shares": 0.0,
                "filled_usdc": 0.0,
                "fill_price": 0.0,
                "raw": {},
                "signed_order_json": "s3",
            },
        ]
        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=sell_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        # No fill records (partial-then-stuck does NOT show in fills).
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1
        err = store["withdrawal_errors"][0]
        assert err["token_id"] == TOK_A
        # Residual = 100 - 40 = 60.
        assert err["shares_remaining"] == 60.0

    def test_top_level_positions_failure_records_top_level_error(
        self, tmp_path: Path
    ) -> None:
        """Refresh OK but positions API fails 3x → one top-level error, state errored."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        # All three fetch attempts return an error dict.
        err = {"error": "502 bad gateway"}
        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[err, err, err],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1
        rec = store["withdrawal_errors"][0]
        assert rec["token_id"] == ""  # top-level error sentinel
        assert "fetch_positions" in rec["reason"].lower()

    def test_top_level_allowance_failure_short_circuits(self, tmp_path: Path) -> None:
        """Refresh fails 3x → state errored, fetch_positions never called."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        err = {"error": "backend down"}
        router, sent = _make_request_router(
            refresh_responses=[err, err, err],
            fetch_responses=[],  # never reached
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        # No fetch_positions request was issued.
        assert all(
            p["request_type"] != RequestType.FETCH_ALL_POSITIONS.value for p in sent
        )

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert len(store["withdrawal_errors"]) == 1
        rec = store["withdrawal_errors"][0]
        assert rec["token_id"] == ""
        assert "refresh" in rec["reason"].lower()

    def test_only_malformed_positions_yields_errored_state(
        self, tmp_path: Path
    ) -> None:
        """All input positions malformed → no sellables, errors recorded, state errored."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [{"size": 50.0, "redeemable": False}]  # missing asset
        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1

    def test_filter_drops_position_with_non_numeric_size(self, tmp_path: Path) -> None:
        """Position with a non-numeric ``size`` field is recorded as a malformed error."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [
            {"asset": TOK_A, "size": "not-a-number", "redeemable": False},
        ]
        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert any(
            "non-numeric size" in e["reason"] for e in store["withdrawal_errors"]
        )

    def test_fetch_positions_none_response_treated_as_error(
        self, tmp_path: Path
    ) -> None:
        """Connection returning ``None`` from FETCH_ALL_POSITIONS → top-level error."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[None, None, None],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert any(
            "fetch_positions" in e["reason"].lower() for e in store["withdrawal_errors"]
        )

    def test_refresh_none_response_treated_as_error(self, tmp_path: Path) -> None:
        """Connection returning ``None`` from REFRESH_BALANCE_ALLOWANCE → error."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        router, _ = _make_request_router(
            refresh_responses=[None, None, None],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert any("refresh" in e["reason"].lower() for e in store["withdrawal_errors"])

    def test_stuck_reason_distinguishes_sdk_error(self, tmp_path: Path) -> None:
        """When the last attempt errored, the stuck reason quotes the SDK message."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        # All three attempts return errors — final SDK error message dominates.
        err_responses: List[Optional[Dict[str, Any]]] = [
            {"error": "rate limited"},
            {"error": "rate limited"},
            {"error": "circuit broken"},
        ]
        router, _ = _make_request_router(
            refresh_responses=[{"updated": True}],
            fetch_responses=[positions],
            sell_responses=err_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        err = store["withdrawal_errors"][0]
        assert "sdk error" in err["reason"].lower()
        assert "circuit broken" in err["reason"]

    def test_read_store_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        """A missing chatui store file returns ``{}`` from ``_read_store``."""
        # Don't seed — file does not exist.
        behaviour = _make_behaviour(tmp_path)
        assert behaviour._read_store() == {}

    def test_read_store_returns_empty_on_invalid_json(self, tmp_path: Path) -> None:
        """Garbage in the chatui store file returns ``{}`` (no crash)."""
        (tmp_path / CHATUI_PARAM_STORE).write_text("not-json{{")
        behaviour = _make_behaviour(tmp_path)
        assert behaviour._read_store() == {}

    def test_write_store_logs_on_oserror(self, tmp_path: Path) -> None:
        """``_write_store`` swallows OSError and emits an error log."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        # Point store_path at something we can't write — a non-existent dir.
        behaviour.context.params.store_path = tmp_path / "nonexistent-dir"
        behaviour._write_store({"x": 1})
        # Logger was called with an error.
        assert behaviour.context.logger.error.called
        msg = str(behaviour.context.logger.error.call_args).lower()
        assert "withdrawal" in msg and "store" in msg

    def test_state_transitions_to_selling_at_entry(self, tmp_path: Path) -> None:
        """Behaviour must persist ``selling`` to disk before doing any work."""
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        observed_states: List[str] = []

        def gen_router(payload: Dict[str, Any]):  # type: ignore[no-untyped-def]
            yield
            # Snapshot the on-disk state at the moment of the first request.
            observed_states.append(_read_store(tmp_path)["withdrawal_state"])
            if payload["request_type"] == RequestType.REFRESH_BALANCE_ALLOWANCE.value:
                return {"updated": True}
            return []

        behaviour.send_polymarket_connection_request = gen_router  # type: ignore[method-assign]

        list(behaviour.async_act())

        assert observed_states[0] == WITHDRAWAL_STATE_SELLING


class TestOmenWithdrawBehaviourStub:
    """Tests for the defensive Omen stub behaviour."""

    def test_async_act_logs_warning_and_finishes(self) -> None:
        """The Omen stub must emit a WARNING and post a WithdrawalPayload."""
        behaviour = object.__new__(_TestableOmenWithdraw)
        behaviour.context = MagicMock()  # type: ignore[assignment]
        behaviour.context.agent_address = "agent_y"

        captured_payload: Dict[str, Any] = {}

        def fake_finish(payload: WithdrawalPayload):  # type: ignore[no-untyped-def]
            captured_payload["payload"] = payload
            yield

        behaviour.finish_behaviour = fake_finish  # type: ignore[method-assign]
        list(behaviour.async_act())

        behaviour.context.logger.warning.assert_called_once()
        msg = str(behaviour.context.logger.warning.call_args).lower()
        assert "omen" in msg and "halt" in msg
        assert isinstance(captured_payload["payload"], WithdrawalPayload)


# ---------------------------------------------------------------------------
# Cross-skill composition
# ---------------------------------------------------------------------------


class TestComposition:
    """The trader_abci composition must wire the gate to the new rounds."""

    def test_withdrawal_polymarket_routes_to_polymarket_withdraw_round(
        self,
    ) -> None:
        """FinishedWithWithdrawalPolymarketRound enters PolymarketWithdrawRound."""
        from packages.valory.skills.check_stop_trading_abci.rounds import (
            FinishedWithWithdrawalPolymarketRound,
        )
        from packages.valory.skills.trader_abci.composition import (
            abci_app_transition_mapping,
        )

        assert (
            abci_app_transition_mapping[FinishedWithWithdrawalPolymarketRound]
            is PolymarketWithdrawRound
        )

    def test_withdrawal_omen_routes_to_omen_withdraw_round(self) -> None:
        """FinishedWithWithdrawalOmenRound enters OmenWithdrawRound."""
        from packages.valory.skills.check_stop_trading_abci.rounds import (
            FinishedWithWithdrawalOmenRound,
        )
        from packages.valory.skills.trader_abci.composition import (
            abci_app_transition_mapping,
        )

        assert (
            abci_app_transition_mapping[FinishedWithWithdrawalOmenRound]
            is OmenWithdrawRound
        )
