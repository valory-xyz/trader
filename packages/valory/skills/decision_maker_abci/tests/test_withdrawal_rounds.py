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
    CTF_DECIMAL_FACTOR,
    PolymarketWithdrawBehaviour,
    TERMINAL_STATUS_MAP,
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
    max_attempts: Optional[int] = None,
) -> "_TestablePolymarketWithdraw":
    """Build a behaviour with mocked context / params and a tmp store path.

    The schedule contract is ``len(backoff) == max_attempts - 1`` (one sleep
    per inter-attempt gap). When ``max_attempts`` is omitted it's derived as
    ``len(backoff) + 1``, matching the production validation.

    :param tmp_path: pytest-supplied tmp directory used as the store path.
    :param backoff: inter-attempt sleep schedule.
    :param max_attempts: total FAK attempts; defaults to ``len(backoff) + 1``.
    :return: a fresh testable behaviour instance.
    """
    if backoff is None:
        backoff = [10, 30]
    if max_attempts is None:
        max_attempts = len(backoff) + 1
    behaviour = object.__new__(_TestablePolymarketWithdraw)
    behaviour.context = MagicMock()  # type: ignore[assignment]
    behaviour.context.agent_address = "agent_x"
    behaviour.context.params.store_path = tmp_path
    behaviour.context.params.withdrawal_max_fak_attempts = max_attempts
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
    get_order_responses: Optional[List[Any]] = None,
) -> "tuple[Callable[[Dict[str, Any]], Generator[None, None, Any]], List[Dict[str, Any]]]":  # noqa: E501
    """Build a fake send_polymarket_connection_request that pops by request_type.

    Each kw list is a queue: the request handler pops the head per call. ``None``
    in a queue means "the connection returned None" (timeout / dispatch failure).

    :param fetch_responses: queue of FETCH_ALL_POSITIONS responses.
    :param sell_responses: queue of SELL_POSITION responses.
    :param get_order_responses: queue of GET_ORDER responses (for cooperative
        poll loops driven by the behaviour after a ``delayed`` sell response).
    :return: a `(router_fn, sent_payloads_list)` tuple.
    """
    fetch = list(fetch_responses or [])
    sell = list(sell_responses or [])
    get_order = list(get_order_responses or [])
    sent_payloads: List[Dict[str, Any]] = []

    def _router(payload: Dict[str, Any]) -> Any:
        sent_payloads.append(payload)
        rt = payload.get("request_type")
        if rt == RequestType.FETCH_ALL_POSITIONS.value:
            return fetch.pop(0) if fetch else None
        if rt == RequestType.SELL_POSITION.value:
            return sell.pop(0) if sell else None
        if rt == RequestType.GET_ORDER.value:
            return get_order.pop(0) if get_order else None
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
                {
                    "token_id": "old-x",
                    "shares_sold": 1.0,
                    "fill_price": 0.5,
                    "ts": 1,
                }  # nosec B105
            ],
            withdrawal_errors=[
                {
                    "token_id": "old-y",
                    "shares_remaining": 2.0,
                    "reason": "old",
                    "ts": 2,
                }  # nosec B105
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

    @pytest.mark.parametrize(
        "size,expected_outcome",
        [
            (0.009, "filtered"),  # below DUST_EPSILON=0.01 → drop
            (0.01, "filtered"),  # exactly at boundary, `<=` includes
            (0.011, "kept"),  # just above boundary → sell
        ],
    )
    def test_filter_sellable_dust_boundary(
        self, tmp_path: Path, size: float, expected_outcome: str
    ) -> None:
        """``DUST_EPSILON=0.01`` boundary check on the position filter.

        Falsifiable against a flipped comparator (`<` vs `<=`) or a moved
        threshold value: the ``0.01`` case would change buckets.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        :param size: the position size to filter.
        :param expected_outcome: ``"filtered"`` or ``"kept"``.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path)
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=size)]
        # The sell response is only consumed if the position passes the filter.
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": size,
            "filled_usdc": size * 0.5,
            "fill_price": 0.5,
            "raw": {},
        }
        router, sent = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        if expected_outcome == "filtered":
            assert len(sell_payloads) == 0
        else:
            assert len(sell_payloads) == 1

    @pytest.mark.parametrize(
        "residual_after_partial,expected_outcome",
        [
            (0.005, "success"),  # well below dust → success path
            (0.015, "retry"),  # well above dust → continue to next attempt
        ],
    )
    def test_residual_dust_boundary(
        self,
        tmp_path: Path,
        residual_after_partial: float,
        expected_outcome: str,
    ) -> None:
        """``DUST_EPSILON=0.01`` boundary check on the per-position success path.

        The first sell fills `(size - residual_after_partial)` shares; the
        success-path check ``residual <= DUST_EPSILON`` decides whether to
        record the fill or continue to a second FAK attempt. Tested with
        values clearly above and below the threshold rather than exactly
        at it, since ``size - filled`` is subject to float drift (e.g.
        ``1.0 - 0.99 = 0.010000000000000009``) which makes the exact-0.01
        boundary case unreliable to reproduce in a black-box behaviour test.
        Falsifiable against a flipped comparator at obviously-above /
        obviously-below values.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        :param residual_after_partial: the residual the test contrives.
        :param expected_outcome: ``"success"`` or ``"retry"``.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        size = 1.0
        partial_filled = size - residual_after_partial
        partial_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": partial_filled,
            "filled_usdc": partial_filled * 0.5,
            "fill_price": 0.5,
            "raw": {},
        }
        # Second response only consumed on retry path.
        no_match = {
            "order_id": "o-2",
            "status": "unmatched",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        positions = [_make_position(TOK_A, size=size)]
        router, sent = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[partial_resp, no_match],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        sell_payloads = [p for p in sent if p["request_type"] == "sell_position"]
        if expected_outcome == "success":
            # Success path → only one SELL, no retry.
            assert len(sell_payloads) == 1
            store = _read_store(tmp_path)
            assert len(store["withdrawal_fills"]) == 1
        else:
            # Retry path → two SELLs (initial + retry).
            assert len(sell_payloads) == 2

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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        # 60 @ 0.40 + 30 @ 0.50 + 10 @ 0.60 = 100 shares total, $45 total
        # → vw price = 45 / 100 = 0.45
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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

    def test_partial_then_stuck_records_fill_and_residual_error(
        self, tmp_path: Path
    ) -> None:
        """Partial filled then stuck — one fill row AND one residual error row.

        Per Issue #2 (`_flush_position_records`), every per-position exit path
        emits the accumulated partial fill (when ``total_filled > 0``) plus
        the residual as an error. The on-chain record (via ``get_trades``)
        remains the authoritative audit trail; the fill row makes the
        operator-facing summary symmetric with on-chain reality.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        # Both rows present: 40-share fill, 60-share residual error.
        assert len(store["withdrawal_fills"]) == 1
        fill = store["withdrawal_fills"][0]
        assert fill["token_id"] == TOK_A
        assert fill["shares_sold"] == pytest.approx(40.0)
        assert fill["fill_price"] == pytest.approx(0.40)
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
        """Cooperative poll exhaustion records in-flight error; no FAK retry.

        Connection returns ``delayed`` immediately on post_order; behaviour
        drives the cooperative GET_ORDER poll loop. When every poll returns
        a non-terminal LIVE status the loop exhausts and records a deferred
        in-flight error. The behaviour must NOT FAK-retry within this sweep
        — retrying with the full residual would race the in-flight match.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=2.4381)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        # Provide three sell responses but only one should be consumed:
        # the cooperative poll exhausts → in-flight error → no FAK retry.
        live_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "2438100",
            "price": "0.043",
        }
        # The poll schedule has 6 backoffs; every one returns LIVE.
        router, sent_payloads = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp, delayed_resp, delayed_resp],
            get_order_responses=[live_get_order] * 6,
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
        # No FAK inter-attempt sleep — the only sleeps were the cooperative
        # poll schedule (6 entries summing to 122s).
        assert captured_sleep == [2, 5, 10, 15, 30, 60]

    def test_in_flight_position_does_not_block_other_positions(
        self, tmp_path: Path
    ) -> None:
        """In-flight on one position must not abort the sweep for the rest.

        Three positions in order: A (matched), B (delayed-then-poll-exhausts),
        C (matched). Expected: two fills (A, C) + one deferred error (B),
        state errored.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
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
                "status": "delayed",
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
        live_get_order = {
            "id": "0xpending-B",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "5000000",
            "price": "0.50",
        }
        # Position B's delayed sell triggers 6 GET_ORDER calls (all LIVE).
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=sell_responses,
            get_order_responses=[live_get_order] * 6,
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
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=3.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        live_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "3000000",
            "price": "0.50",
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[live_get_order] * 6,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1

    @pytest.mark.parametrize(
        "raw_status,expected_norm",
        [
            ("ORDER_STATUS_MATCHED", "matched"),
            ("ORDER_STATUS_CANCELED", "canceled"),
            ("ORDER_STATUS_INVALID", "invalid"),
            ("ORDER_STATUS_CANCELED_MARKET_RESOLVED", "market_resolved"),
        ],
    )
    def test_fill_from_terminal_maps_known_statuses(
        self, tmp_path: Path, raw_status: str, expected_norm: str
    ) -> None:
        """Each known terminal ``ORDER_STATUS_*`` maps to its normalized name.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        :param raw_status: raw ``ORDER_STATUS_*`` value from get_order.
        :param expected_norm: the expected normalized ``status`` field value.
        """
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        order = {
            "id": "0xpending",
            "status": raw_status,
            "size_matched": "20400000",
            "original_size": "20400000",
            "price": "0.043",
        }

        result = behaviour._fill_from_terminal_get_order(order, "0xpending")

        assert result["status"] == expected_norm

    def test_fill_from_terminal_unknown_status_falls_back_to_unmatched(
        self, tmp_path: Path
    ) -> None:
        """An unmapped ``ORDER_STATUS_*`` falls back to ``unmatched`` + warning.

        Defensive against SDK contract changes: a new terminal status
        introduced upstream gets the retryable-bucket treatment without
        crashing the sweep, and a warning is logged so the new value can
        be added to the map deliberately.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_FUTURE_NEW_VALUE",
            "size_matched": "0",
            "original_size": "20400000",
            "price": "0.043",
        }

        result = behaviour._fill_from_terminal_get_order(order, "0xpending")

        assert result["status"] == "unmatched"
        # Warning logged about the unknown status.
        warnings = [
            str(call.args[0])
            for call in behaviour.context.logger.warning.call_args_list
        ]
        assert any(
            "ORDER_STATUS_FUTURE_NEW_VALUE" in w and "unrecognized" in w.lower()
            for w in warnings
        )

    @pytest.mark.parametrize(
        "raw_status",
        ["ORDER_STATUS_INVALID", "ORDER_STATUS_CANCELED_MARKET_RESOLVED"],
    )
    def test_permanent_failure_short_circuits_retry_loop(
        self, tmp_path: Path, raw_status: str
    ) -> None:
        """``invalid`` and ``market_resolved`` terminal statuses bail the FAK loop.

        Retrying these is mathematically guaranteed to fail (signer mismatch
        will reproduce; market_resolved means liquidity is permanently gone).
        After exactly one SELL_POSITION attempt the loop must short-circuit
        with a deferred error and skip remaining FAK retries.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        :param raw_status: the permanent-failure raw status to mock.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=5.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        terminal_resp = {
            "id": "0xpending",
            "status": raw_status,
            "size_matched": "0",
            "original_size": "5000000",
            "price": "0.50",
        }
        # Provide three sell responses but only the first should be consumed.
        router, sent_payloads = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp, delayed_resp, delayed_resp],
            get_order_responses=[terminal_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Exactly one SELL_POSITION — short-circuit prevented further retries.
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
        assert err["shares_remaining"] == 5.0
        # Reason text cites the permanent terminal status.
        expected_norm = TERMINAL_STATUS_MAP[raw_status]
        assert expected_norm in err["reason"]

    def test_empty_post_order_response_records_sdk_error_not_no_liquidity(
        self, tmp_path: Path
    ) -> None:
        """Connection's empty-post_order error surfaces as ``sdk error:`` reason.

        Falsifies a regression to the old ``return resp, None`` shape: that
        would surface every iteration as a no-fill, exhaust the FAK retry
        schedule, and record ``"no liquidity after FAK attempts"`` —
        masking a real protocol-layer bug as a market condition.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=10.0)]
        # Connection-side error envelope, the same shape _sell_position
        # now returns when post_order yields a falsy response.
        error_envelope = {"error": "post_order returned empty response"}
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[error_envelope, error_envelope],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert len(store["withdrawal_errors"]) == 1
        reason = store["withdrawal_errors"][0]["reason"]
        assert reason.startswith("sdk error:")
        assert "no liquidity" not in reason.lower()

    def test_poll_all_errors_records_api_unreachable_reason(
        self, tmp_path: Path
    ) -> None:
        """Every GET_ORDER errors → distinct "API unreachable" error reason.

        Distinguishes a sustained polymarket API outage from a genuine
        in-flight match. Without this, the operator can't tell from the
        error trail whether to wait for the in-flight match to resolve
        (transient deferral) or escalate (API actually down).

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=10.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        # Every poll returns an error envelope (connection-layer error).
        error_envelope = {"error": "Unauthorized"}
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[error_envelope] * 6,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert len(store["withdrawal_errors"]) == 1
        reason = store["withdrawal_errors"][0]["reason"].lower()
        # Distinct from in_flight reason: cites API unreachable.
        assert "polymarket api unreachable" in reason
        assert "in-flight" not in reason

    def test_poll_partial_errors_then_terminal_records_fill(
        self, tmp_path: Path
    ) -> None:
        """Mixed errors + a successful terminal poll → fill recorded normally.

        Regression guard against the temptation to early-bail on a few
        consecutive errors. A 4th poll that matches must record the fill,
        not get short-circuited.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=20.4)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        error_envelope = {"error": "transient"}
        terminal_match = {
            "id": "0xpending",
            "status": "ORDER_STATUS_MATCHED",
            "size_matched": "20400000",
            "original_size": "20400000",
            "price": "0.043",
        }
        # 3 errors then a terminal match. Loop must NOT short-circuit
        # before the success poll.
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[
                error_envelope,
                error_envelope,
                error_envelope,
                terminal_match,
            ],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        assert store["withdrawal_fills"][0]["shares_sold"] == pytest.approx(20.4)
        assert store["withdrawal_errors"] == []

    def test_poll_partial_errors_then_exhaustion_returns_in_flight(
        self, tmp_path: Path
    ) -> None:
        """Some polls error, others LIVE → exhaustion → in-flight reason.

        Regression guard: the "all errored" reason must only fire when
        EVERY poll erred. A single successful poll (LIVE or otherwise)
        means the connection is reachable; exhaustion-with-LIVE is the
        in-flight defer path.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=10.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        error_envelope = {"error": "transient"}
        live_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "10000000",
            "price": "0.50",
        }
        # 2 errors, 4 LIVE — never reaches terminal but at least one poll
        # succeeded. Must surface as in-flight defer, not API unreachable.
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[
                error_envelope,
                error_envelope,
                live_get_order,
                live_get_order,
                live_get_order,
                live_get_order,
            ],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert len(store["withdrawal_errors"]) == 1
        reason = store["withdrawal_errors"][0]["reason"].lower()
        assert "in-flight" in reason
        assert "polymarket api unreachable" not in reason

    def test_in_flight_after_partial_emits_fill_then_error(
        self, tmp_path: Path
    ) -> None:
        """Partial fill followed by in-flight defer must emit BOTH rows.

        Concrete scenario: 100-share position; attempt 1 fills 60
        synchronously (residual=40); attempt 2 returns delayed → poll
        exhausts → in_flight defer for the 40-share residual. The 60-share
        partial must appear in ``withdrawal_fills`` (not silently dropped),
        and the 40-share residual must appear in ``withdrawal_errors``.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        partial_fill = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 60.0,
            "filled_usdc": 24.0,
            "fill_price": 0.40,
            "raw": {},
        }
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        live_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "40000000",
            "price": "0.40",
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[partial_fill, delayed_resp],
            get_order_responses=[live_get_order] * 6,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        # Both rows must exist for this position.
        fills_for_a = [f for f in store["withdrawal_fills"] if f["token_id"] == TOK_A]
        errors_for_a = [e for e in store["withdrawal_errors"] if e["token_id"] == TOK_A]
        assert len(fills_for_a) == 1
        assert fills_for_a[0]["shares_sold"] == pytest.approx(60.0)
        assert fills_for_a[0]["fill_price"] == pytest.approx(0.40)
        assert len(errors_for_a) == 1
        assert errors_for_a[0]["shares_remaining"] == pytest.approx(40.0)
        assert "in-flight" in errors_for_a[0]["reason"].lower()
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED

    def test_retry_exhaustion_after_partial_emits_fill_then_error(
        self, tmp_path: Path
    ) -> None:
        """Partial fill followed by exhausted retries must also emit BOTH rows.

        Same root concern as the in-flight case: the loop exit at retry
        exhaustion previously dropped accumulated partial fills. With the
        ``_flush_position_records`` helper at every exit, the audit trail
        is symmetric.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=100.0)]
        partial_fill = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 60.0,
            "filled_usdc": 24.0,
            "fill_price": 0.40,
            "raw": {},
        }
        no_match = {
            "order_id": "o-2",
            "status": "unmatched",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        # 2 attempts: first partial, second no-match → exhaustion.
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[partial_fill, no_match],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        fills_for_a = [f for f in store["withdrawal_fills"] if f["token_id"] == TOK_A]
        errors_for_a = [e for e in store["withdrawal_errors"] if e["token_id"] == TOK_A]
        assert len(fills_for_a) == 1
        assert fills_for_a[0]["shares_sold"] == pytest.approx(60.0)
        assert len(errors_for_a) == 1
        assert errors_for_a[0]["shares_remaining"] == pytest.approx(40.0)

    def test_in_flight_with_zero_prior_fills_records_error_only(
        self, tmp_path: Path
    ) -> None:
        """No spurious empty-fill rows when in-flight fires with no prior fill.

        Regression guard for the helper: ``total_filled == 0`` must yield
        ZERO fill rows, not a phantom 0-share row.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=10.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        live_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "10000000",
            "price": "0.50",
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[live_get_order] * 6,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        # Exactly one error row, NO fill rows.
        assert store["withdrawal_fills"] == []
        assert len(store["withdrawal_errors"]) == 1

    def test_decimal_factor_constant_value(self) -> None:
        """``CTF_DECIMAL_FACTOR`` must remain 10**6 (6-decimal fixed-point).

        Regression guard against accidentally changing the scaling, which
        would silently inflate or deflate every fill record.
        """
        assert CTF_DECIMAL_FACTOR == 10**6

    def test_size_matched_valid_int_string_parses_correctly(
        self, tmp_path: Path
    ) -> None:
        """Regression: a valid 6-decimal fixed-point integer string parses cleanly.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_MATCHED",
            "size_matched": "20400000",
            "original_size": "20400000",
            "price": "0.043",
        }

        result = behaviour._fill_from_terminal_get_order(order, "0xpending")

        assert "error" not in result
        assert result["filled_shares"] == pytest.approx(20.4)
        assert result["fill_price"] == pytest.approx(0.043)

    @pytest.mark.parametrize(
        "size_matched_value,reason_token",
        [
            ("20.4", "size_matched"),
            ("garbage", "size_matched"),
            ("12.0e3", "size_matched"),
        ],
    )
    def test_size_matched_unparseable_records_sdk_error(
        self,
        tmp_path: Path,
        size_matched_value: str,
        reason_token: str,
    ) -> None:
        """Non-conforming ``size_matched`` records SDK error; sweep continues.

        Without the parse-safety wrap, a single SDK contract change would
        ``ValueError`` out of the sweep generator and skip every remaining
        position. The fix records the parse failure as an error row and
        the sweep continues to the next position.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        :param size_matched_value: the malformed size_matched string to inject.
        :param reason_token: substring that must appear in the recorded reason.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        # Two positions so we can verify the second is reached after the
        # first hits the parse failure.
        positions = [
            _make_position(TOK_A, size=10.0),
            _make_position(TOK_B, size=5.0),
        ]
        delayed_resp = {
            "order_id": "0xpending-A",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        malformed_terminal = {
            "id": "0xpending-A",
            "status": "ORDER_STATUS_MATCHED",
            "size_matched": size_matched_value,
            "original_size": "10000000",
            "price": "0.5",
        }
        sync_match_b = {
            "order_id": "o-B",
            "status": "matched",
            "filled_shares": 5.0,
            "filled_usdc": 2.5,
            "fill_price": 0.5,
            "raw": {},
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp, sync_match_b],
            get_order_responses=[malformed_terminal],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        # Position A errored due to parse failure; position B succeeded.
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        fill_token_ids = {f["token_id"] for f in store["withdrawal_fills"]}
        assert fill_token_ids == {TOK_B}
        error_rows = [e for e in store["withdrawal_errors"] if e["token_id"] == TOK_A]
        assert len(error_rows) == 1
        assert reason_token in error_rows[0]["reason"]
        assert "sdk error" in error_rows[0]["reason"].lower()

    def test_price_unparseable_records_sdk_error(self, tmp_path: Path) -> None:
        """Non-conforming ``price`` records SDK error without crashing the sweep.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=10.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        malformed_terminal = {
            "id": "0xpending",
            "status": "ORDER_STATUS_MATCHED",
            "size_matched": "10000000",
            "original_size": "10000000",
            "price": "abc",
        }
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[malformed_terminal],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert len(store["withdrawal_errors"]) == 1
        assert "price" in store["withdrawal_errors"][0]["reason"]

    def test_canceled_status_does_not_short_circuit(self, tmp_path: Path) -> None:
        """``ORDER_STATUS_CANCELED`` stays in the retryable bucket.

        Without production data we cannot distinguish FAK kills from
        external cancels; treating it as retryable matches today's behaviour
        and avoids regressions on FAK-kill recovery paths.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=5.0)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        canceled_terminal = {
            "id": "0xpending",
            "status": "ORDER_STATUS_CANCELED",
            "size_matched": "0",
            "original_size": "5000000",
            "price": "0",
        }
        # Two attempts: first delayed→canceled (retryable), second also
        # delayed→canceled. Loop runs to exhaustion.
        router, sent_payloads = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp, delayed_resp],
            get_order_responses=[canceled_terminal, canceled_terminal],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        sell_payloads = [
            p
            for p in sent_payloads
            if p.get("request_type") == RequestType.SELL_POSITION.value
        ]
        # Both attempts ran — no short-circuit.
        assert len(sell_payloads) == 2

    def test_delayed_response_drives_cooperative_poll_loop_to_match(
        self, tmp_path: Path
    ) -> None:
        """``status=delayed`` triggers behaviour-side cooperative poll until matched.

        Position posts ``delayed``; the behaviour issues GET_ORDER calls with
        cooperative sleeps. After two LIVE polls the third returns
        ``ORDER_STATUS_MATCHED``; the resulting fill is recorded as if the
        sell had been synchronous.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1, 1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions = [_make_position(TOK_A, size=20.4)]
        delayed_resp = {
            "order_id": "0xpending",
            "status": "delayed",
            "filled_shares": 0.0,
            "filled_usdc": 0.0,
            "fill_price": 0.0,
            "raw": {},
        }
        live_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_LIVE",
            "size_matched": "0",
            "original_size": "20400000",
            "price": "0.043",
        }
        terminal_get_order = {
            "id": "0xpending",
            "status": "ORDER_STATUS_MATCHED",
            "size_matched": "20400000",
            "original_size": "20400000",
            "price": "0.043",
        }
        router, sent_payloads = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[live_get_order, live_get_order, terminal_get_order],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Three GET_ORDER requests issued; SELL_POSITION called exactly once.
        get_order_payloads = [
            p
            for p in sent_payloads
            if p.get("request_type") == RequestType.GET_ORDER.value
        ]
        sell_payloads = [
            p
            for p in sent_payloads
            if p.get("request_type") == RequestType.SELL_POSITION.value
        ]
        assert len(get_order_payloads) == 3
        assert len(sell_payloads) == 1

        # Cooperative sleeps from the poll schedule were observed.
        # First three entries of DELAYED_ORDER_POLL_BACKOFFS_S = (2, 5, 10).
        assert captured_sleep[:3] == [2, 5, 10]

        # Fill recorded; sweep ends complete (no errors).
        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        fill = store["withdrawal_fills"][0]
        assert fill["token_id"] == TOK_A
        assert fill["shares_sold"] == pytest.approx(20.4)
        assert fill["fill_price"] == pytest.approx(0.043)
        assert store["withdrawal_errors"] == []


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
