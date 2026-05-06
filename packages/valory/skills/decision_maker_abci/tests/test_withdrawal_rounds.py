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
from typing import Any, Callable, Dict, Generator, List, Optional
from unittest.mock import MagicMock

import pytest

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import (
    BaseTxPayload,
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
        """Verify PolymarketWithdrawRound subclasses CollectSameUntilThresholdRound."""
        assert issubclass(PolymarketWithdrawRound, CollectSameUntilThresholdRound)

    def test_omen_withdraw_inherits_collect_same_until_threshold(self) -> None:
        """Verify OmenWithdrawRound subclasses CollectSameUntilThresholdRound."""
        assert issubclass(OmenWithdrawRound, CollectSameUntilThresholdRound)

    def test_withdrawal_idle_is_degenerate(self) -> None:
        """Verify WithdrawalIdleRound subclasses DegenerateRound (terminal halt)."""
        assert issubclass(WithdrawalIdleRound, DegenerateRound)

    def test_polymarket_withdraw_uses_withdrawal_payload(self) -> None:
        """Verify PolymarketWithdrawRound posts WithdrawalPayload values."""
        assert PolymarketWithdrawRound.payload_class is WithdrawalPayload

    def test_omen_withdraw_uses_withdrawal_payload(self) -> None:
        """Verify OmenWithdrawRound posts WithdrawalPayload values."""
        assert OmenWithdrawRound.payload_class is WithdrawalPayload

    def test_polymarket_withdraw_done_event(self) -> None:
        """Verify PolymarketWithdrawRound emits WITHDRAWAL_DONE on consensus."""
        assert PolymarketWithdrawRound.done_event == Event.WITHDRAWAL_DONE

    def test_omen_withdraw_done_event(self) -> None:
        """Verify OmenWithdrawRound emits WITHDRAWAL_DONE on consensus."""
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
        """Verify WithdrawalIdleRound is terminal — empty transition map."""
        tx = DecisionMakerAbciApp.transition_function
        assert tx[WithdrawalIdleRound] == {}

    def test_idle_round_in_final_states(self) -> None:
        """Verify WithdrawalIdleRound is registered as a final state of the AbciApp."""
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
        """Verify WithdrawalIdleRound is terminal with no DB-key post-conditions."""
        post = DecisionMakerAbciApp.db_post_conditions
        assert WithdrawalIdleRound in post
        assert post[WithdrawalIdleRound] == set()


# ---------------------------------------------------------------------------
# Round behaviour registration
# ---------------------------------------------------------------------------


class TestRoundBehaviourRegistration:
    """The new behaviours must be registered with the round behaviour."""

    def test_polymarket_withdraw_behaviour_registered(self) -> None:
        """Ensure PolymarketWithdrawBehaviour is in the registered behaviour set."""
        assert (
            PolymarketWithdrawBehaviour in AgentDecisionMakerRoundBehaviour.behaviours
        )

    def test_omen_withdraw_behaviour_registered(self) -> None:
        """Ensure OmenWithdrawBehaviour is in the registered behaviour set."""
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

    context: Any = None  # type: ignore[assignment]


class _TestableOmenWithdraw(OmenWithdrawBehaviour):
    """Shadows read-only AEA properties for testing."""

    context: Any = None  # type: ignore[assignment]


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
    """Stub finish_behaviour + sleep so async_act can be exhausted in-process.

    :param behaviour: the testable behaviour instance to patch in place.
    :param captured_payload: mutable dict the fake finish writes the payload into.
    :param captured_sleep: mutable list the fake sleep appends backoff seconds to.
    """

    def fake_finish(payload: BaseTxPayload) -> Generator[Any, None, None]:
        captured_payload["payload"] = payload
        yield

    def fake_sleep(s: float) -> Generator[Any, None, None]:
        captured_sleep.append(int(s))
        yield

    behaviour.finish_behaviour = fake_finish  # type: ignore[method-assign,assignment]
    behaviour.sleep = fake_sleep  # type: ignore[method-assign,assignment]


def _make_request_router(
    *,
    fetch_responses: Optional[List[Any]] = None,
    sell_responses: Optional[List[Any]] = None,
) -> "tuple[Callable[[Dict[str, Any]], Generator[None, None, Any]], List[Dict[str, Any]]]":  # noqa: E501
    """Build a fake send_polymarket_connection_request that pops by request_type.

    Each kw list is a queue: the request handler pops the head per call. ``None``
    in a queue means "the connection returned None" (timeout / dispatch failure).

    :param fetch_responses: queue of FETCH_ALL_POSITIONS responses.
    :param sell_responses: queue of SELL_POSITION responses.
    :return: a `(router_fn, sent_payloads_list)` tuple.
    """
    fetch = list(fetch_responses or [])
    sell = list(sell_responses or [])
    sent_payloads: List[Dict[str, Any]] = []

    def _router(payload: Dict[str, Any]) -> Any:
        sent_payloads.append(payload)
        rt = payload.get("request_type")
        if rt == RequestType.FETCH_ALL_POSITIONS.value:
            return fetch.pop(0) if fetch else None
        if rt == RequestType.SELL_POSITION.value:
            return sell.pop(0) if sell else None
        raise AssertionError(f"unexpected request_type: {rt}")

    def gen_router(payload: Dict[str, Any]) -> Generator[None, None, Any]:
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
            fetch_responses=[[]],  # empty list of positions
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert store["withdrawal_fills"] == []
        assert store["withdrawal_errors"] == []
        assert isinstance(captured_payload["payload"], WithdrawalPayload)
        # No backoffs needed.
        assert captured_sleep == []

    def test_pre_existing_errors_dont_taint_clean_sweep(self, tmp_path: Path) -> None:
        """Stale errors from a prior sweep must not flip a clean sweep to errored.

        When the agent re-enters the withdraw round automatically (because
        flag stays True after an ``errored`` sweep), prior fills/errors
        persist on disk. The behaviour should reset those at session start
        so the end-of-sweep state reflects only this session's outcome.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        # Seed with pre-existing errors and fills from a "prior" sweep.
        _seed_store(
            tmp_path,
            withdrawal_fills=[
                {"token_id": "old-x", "shares_sold": 1.0, "fill_price": 0.5, "ts": 1}
            ],
            withdrawal_errors=[
                {"token_id": "old-y", "shares_remaining": 2.0, "reason": "old", "ts": 2}
            ],
        )
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        # This sweep: one position, fills cleanly, no errors added.
        positions = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.4,
            "raw": {},
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        # Final state reflects THIS sweep — no errors → complete.
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        # Stale fills/errors from the prior sweep are gone.
        assert all(f["token_id"] != "old-x" for f in store["withdrawal_fills"])
        assert all(e["token_id"] != "old-y" for e in store["withdrawal_errors"])
        # This sweep's fill is recorded.
        assert len(store["withdrawal_fills"]) == 1
        assert store["withdrawal_fills"][0]["token_id"] == TOK_A
        assert store["withdrawal_errors"] == []

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
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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

    def test_sub_one_percent_residual_treated_as_dust(self, tmp_path: Path) -> None:
        """Tiny float residuals from a near-full FAK match → recorded as complete.

        Verified against a live partial fill on Polygon mainnet: a 9.6956
        position filled at 9.69 (residual 0.0056) made the next FAK attempt
        round its maker/taker amounts to zero, which the CLOB rejects with
        ``invalid amounts, maker and taker amount must be higher than 0``.
        At <0.01 shares of any realistic CTF price the residual is sub-cent
        of stuck value; treat the position as fully sold and record one fill.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=9.6956)]
        # First attempt fills 9.69; residual = 0.0056 (well under 1% but
        # well over the previous 1e-6 dust epsilon).
        first_attempt: Dict[str, Any] = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 9.69,
            "filled_usdc": 0.39729,
            "fill_price": 0.041,
            "raw": {},
            "signed_order_json": "s",
        }
        router, sent = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[first_attempt],  # NO second attempt should occur
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Only one SELL was issued — the dust residual short-circuited the loop.
        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        assert len(sell_payloads) == 1

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        assert store["withdrawal_errors"] == []
        fill = store["withdrawal_fills"][0]
        assert fill["shares_sold"] == 9.69
        assert fill["fill_price"] == pytest.approx(0.041)

    def test_partial_fills_aggregated_volume_weighted(self, tmp_path: Path) -> None:
        """Three FAK attempts, partial each time, completing the residual.

        One fill record with volume-weighted price is emitted; partial fills
        are NOT recorded individually (per §4.1).

        :param tmp_path: pytest-supplied tmp directory used as the store path.
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
            fetch_responses=[positions],
            sell_responses=sell_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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

    def test_no_cached_signed_order_is_ever_forwarded(self, tmp_path: Path) -> None:
        """No SELL_POSITION request carries a ``cached_signed_order_json`` param.

        The behaviour deliberately re-signs every retry: the CLOB rejects
        resubmissions of an already-acknowledged signed order with
        ``order ... is invalid. Duplicated.``, so caching is actively
        harmful for FAK kills.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        # Three error responses force three sell attempts.
        err_responses: List[Optional[Dict[str, Any]]] = [
            {"error": "transient 1"},
            {"error": "transient 2"},
            {"error": "transient 3"},
        ]
        router, sent = _make_request_router(
            fetch_responses=[positions],
            sell_responses=err_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        assert len(sell_payloads) == 3
        for payload in sell_payloads:
            assert "cached_signed_order_json" not in payload["params"]

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
            fetch_responses=[positions],
            sell_responses=[zero_resp, zero_resp, zero_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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

        :param tmp_path: pytest-supplied tmp directory used as the store path.
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
            fetch_responses=[positions],
            sell_responses=sell_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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
            fetch_responses=[err, err, err],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1
        rec = store["withdrawal_errors"][0]
        assert rec["token_id"] == ""  # top-level error sentinel
        assert "fetch_positions" in rec["reason"].lower()

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
            fetch_responses=[positions],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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
            fetch_responses=[positions],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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
            fetch_responses=[None, None, None],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert any(
            "fetch_positions" in e["reason"].lower() for e in store["withdrawal_errors"]
        )

    def test_sell_none_response_treated_as_error(self, tmp_path: Path) -> None:
        """Connection returning ``None`` from SELL_POSITION → per-position error.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[None, None, None],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert any(
            e["token_id"] == TOK_A and "no response" in e["reason"]
            for e in store["withdrawal_errors"]
        )

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
            fetch_responses=[positions],
            sell_responses=err_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

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

        def gen_router(payload: Dict[str, Any]) -> Generator[None, None, Any]:
            yield
            # Snapshot the on-disk state at the moment of the first request.
            observed_states.append(_read_store(tmp_path)["withdrawal_state"])
            if payload["request_type"] == RequestType.FETCH_ALL_POSITIONS.value:
                return []  # empty positions → behaviour completes cleanly
            raise AssertionError(f"unexpected request_type: {payload['request_type']}")

        behaviour.send_polymarket_connection_request = gen_router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        assert observed_states[0] == WITHDRAWAL_STATE_SELLING

    def test_in_flight_response_defers_no_fill_records_deferred_error(
        self, tmp_path: Path
    ) -> None:
        """``status=in_flight`` from the connection breaks the FAK loop early.

        Connection signals ``in_flight`` when the post_order ``delayed`` poll
        cap is exhausted with the order still LIVE on the CLOB. The behaviour
        must NOT retry within this sweep — the order is in-flight, retrying
        with the full residual would race the in-flight match. Instead,
        record a deferred error and break out so the next sweep cycle picks
        up the actual residual once the order resolves.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=2.4381)]
        in_flight_resp = {
            "order_id": "0xpending",
            "status": "in_flight",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        # Provide three sell responses, but only ONE should be consumed
        # because in_flight breaks the FAK loop after the first attempt.
        router, sent_payloads = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[in_flight_resp, in_flight_resp, in_flight_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Only one sell request — no FAK retry triggered.
        sell_payloads = [
            p
            for p in sent_payloads
            if p.get("request_type") == RequestType.SELL_POSITION.value
        ]
        assert len(sell_payloads) == 1

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1
        err = store["withdrawal_errors"][0]
        assert err["token_id"] == TOK_A
        assert err["shares_remaining"] == 2.4381
        assert "in-flight" in err["reason"].lower()
        # No inter-attempt sleep — loop broke out before scheduling one.
        assert captured_sleep == []

    def test_in_flight_position_does_not_block_other_positions(
        self, tmp_path: Path
    ) -> None:
        """In-flight on one position must not abort the sweep for the rest.

        Three positions in order: A (matched), B (in_flight), C (matched).
        Expected: two fills (A, C) + one deferred error (B), state errored.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [
            _make_position(TOK_A, size=10.0),
            _make_position(TOK_B, size=5.0),
            _make_position(TOK_C, size=2.0),
        ]
        sell_responses = [
            {
                "order_id": "o-A",
                "status": "matched",
                "filled_shares": 10.0,
                "filled_usdc": 4.0,
                "fill_price": 0.40,
                "raw": {},
            },
            {
                "order_id": "0xpending-B",
                "status": "in_flight",
                "filled_shares": 0.0,
                "filled_usdc": 0.0,
                "fill_price": 0.0,
                "raw": {},
            },
            {
                "order_id": "o-C",
                "status": "matched",
                "filled_shares": 2.0,
                "filled_usdc": 1.6,
                "fill_price": 0.80,
                "raw": {},
            },
        ]
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=sell_responses,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        fill_token_ids = {f["token_id"] for f in store["withdrawal_fills"]}
        assert fill_token_ids == {TOK_A, TOK_C}
        assert len(store["withdrawal_errors"]) == 1
        assert store["withdrawal_errors"][0]["token_id"] == TOK_B
        assert "in-flight" in store["withdrawal_errors"][0]["reason"].lower()

    def test_sweep_with_only_in_flight_ends_errored(self, tmp_path: Path) -> None:
        """A sweep where every position ends in-flight is still ``errored``.

        ``errored`` is the conservative end-state: it prevents the boot-time
        auto-clear from firing on operator restart, so the agent stays in
        withdrawal mode until the next cycle resolves the in-flight orders.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=3.0)]
        in_flight_resp = {
            "order_id": "0xpending",
            "status": "in_flight",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[in_flight_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1


class TestOmenWithdrawBehaviourStub:
    """Tests for the defensive Omen stub behaviour."""

    def test_async_act_logs_warning_and_finishes(self) -> None:
        """The Omen stub must emit a WARNING and post a WithdrawalPayload."""
        behaviour = object.__new__(_TestableOmenWithdraw)
        behaviour.context = MagicMock()  # type: ignore[assignment]
        behaviour.context.agent_address = "agent_y"

        captured_payload: Dict[str, Any] = {}

        def fake_finish(payload: BaseTxPayload) -> Generator[Any, None, None]:
            captured_payload["payload"] = payload
            yield

        behaviour.finish_behaviour = fake_finish  # type: ignore[method-assign,assignment]
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
        """Verify FinishedWithWithdrawalPolymarketRound enters PolymarketWithdrawRound."""
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
        """Verify FinishedWithWithdrawalOmenRound enters OmenWithdrawRound."""
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

    def test_withdrawal_idle_routes_to_reset_and_pause(self) -> None:
        """Verify WithdrawalIdleRound exits to ResetAndPauseRound.

        DegenerateRound terminals MUST be mapped to an entry round of another
        sub-app in a composed AbciApp; otherwise the framework calls
        ``end_block`` on the bare base class and crashes the agent. Mapping
        to ResetAndPauseRound matches the pattern used by other halt-like
        terminals (``FinishedStakingRound``, ``RefillRequiredRound``,
        ``BenchmarkingDoneRound``).

        After the pause, ``FinishedResetAndPauseRound`` cycles back through
        FetchPerformanceDataRound → ... → CheckStopTradingRound, where the
        withdrawal gate decides whether to re-divert (errored: yes; complete
        or unflagged: no).
        """
        from packages.valory.skills.reset_pause_abci.rounds import ResetAndPauseRound
        from packages.valory.skills.trader_abci.composition import (
            abci_app_transition_mapping,
        )

        assert abci_app_transition_mapping[WithdrawalIdleRound] is ResetAndPauseRound
