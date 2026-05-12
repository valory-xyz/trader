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
from unittest.mock import MagicMock, PropertyMock, patch

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
from packages.valory.skills.decision_maker_abci.payloads import (
    OmenWithdrawalPayload,
    WithdrawalPayload,
)
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

    def test_omen_withdraw_uses_omen_withdrawal_payload(self) -> None:
        """Verify OmenWithdrawRound (Safe-multisend submitter) posts ``OmenWithdrawalPayload``."""
        assert OmenWithdrawRound.payload_class is OmenWithdrawalPayload

    def test_polymarket_withdraw_done_event(self) -> None:
        """Verify PolymarketWithdrawRound emits WITHDRAWAL_DONE on consensus."""
        assert PolymarketWithdrawRound.done_event == Event.WITHDRAWAL_DONE

    def test_omen_withdraw_none_event_is_withdrawal_done(self) -> None:
        """The ``none_event`` is the short-circuit terminal — no-op safe halt."""
        assert OmenWithdrawRound.none_event == Event.WITHDRAWAL_DONE


class TestOmenWithdrawRoundEventSwitch:
    """``OmenWithdrawRound.end_block`` reads the payload's ``event`` field.

    The framework's ``TxPreparationRound`` would emit ``Event.DONE`` on
    consensus, but withdrawal needs to dispatch between two branches:
      - PREPARE_TX (tx_hash set, route to tx settlement)
      - WITHDRAWAL_DONE (short-circuit, no tx settles)

    Verified here by stubbing the framework parts ``super().end_block``
    needs (synchronized_data, payload_values_count) so we can exercise
    the override branches directly without spinning up an FSM.
    """

    @staticmethod
    def _build_round(payload_values: tuple) -> OmenWithdrawRound:
        """Construct an ``OmenWithdrawRound`` instance with stubbed framework state."""
        round_ = object.__new__(OmenWithdrawRound)
        sync = MagicMock()
        # `most_voted_payload_values` reads `consensus_threshold` as an int.
        sync.consensus_threshold = 1
        round_._synchronized_data = sync
        round_._previous_round_payload_class = OmenWithdrawalPayload  # noqa: SLF001
        round_._allow_rejoin_payloads = False  # noqa: SLF001
        fake_payload = MagicMock()
        fake_payload.values = payload_values
        round_.collection = {"agent_0": fake_payload}
        round_.block_confirmations = 0
        return round_

    @staticmethod
    def _patch_super_end_block(monkeypatch: Any, event_to_return: Any) -> None:
        """Force ``CollectSameUntilThresholdRound.end_block`` to a fixed return."""

        def fake_end_block(self: Any) -> Any:
            return (self._synchronized_data, event_to_return)  # noqa: SLF001

        monkeypatch.setattr(CollectSameUntilThresholdRound, "end_block", fake_end_block)

    def test_payload_event_prepare_tx_emits_prepare_tx(self, monkeypatch: Any) -> None:
        """Payload `event=PREPARE_TX` -> emits Event.PREPARE_TX (route to settlement)."""
        round_ = self._build_round(
            payload_values=(
                "OmenWithdrawRound",
                "0x" + "ab" * 32,
                False,
                Event.PREPARE_TX.value,
            )
        )
        self._patch_super_end_block(monkeypatch, Event.DONE)

        result = round_.end_block()

        assert result is not None
        _, emitted = result
        assert emitted == Event.PREPARE_TX

    def test_payload_event_withdrawal_done_emits_withdrawal_done(
        self, monkeypatch: Any
    ) -> None:
        """Payload `event=WITHDRAWAL_DONE` -> short-circuits straight to idle."""
        round_ = self._build_round(
            payload_values=(None, None, None, Event.WITHDRAWAL_DONE.value)
        )
        self._patch_super_end_block(monkeypatch, Event.DONE)

        result = round_.end_block()

        assert result is not None
        _, emitted = result
        assert emitted == Event.WITHDRAWAL_DONE

    def test_no_majority_passes_through_untouched(self, monkeypatch: Any) -> None:
        """On NO_MAJORITY the override returns the super result unchanged."""
        round_ = self._build_round(payload_values=(None, None, None, None))
        self._patch_super_end_block(monkeypatch, Event.NO_MAJORITY)

        result = round_.end_block()

        assert result is not None
        _, emitted = result
        assert emitted == Event.NO_MAJORITY

    def test_super_none_short_circuits(self, monkeypatch: Any) -> None:
        """If super().end_block returns None, the override returns None."""
        round_ = self._build_round(payload_values=(None, None, None, None))

        def fake_end_block(self: Any) -> Any:
            return None

        monkeypatch.setattr(CollectSameUntilThresholdRound, "end_block", fake_end_block)

        assert round_.end_block() is None


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

    def test_post_omen_withdraw_routes_to_idle_on_round_timeout(self) -> None:
        """WITHDRAWAL_ROUND_TIMEOUT from PostOmenWithdrawRound → WithdrawalIdleRound.

        Receipt parsing is deterministic — retrying won't unblock a real
        bug. Mirror the upstream OmenWithdrawRound escape so a persistent
        receipt-side timeout doesn't strand the agent in the round.
        """
        from packages.valory.skills.decision_maker_abci.states.post_omen_withdraw import (
            PostOmenWithdrawRound,
        )

        tx = DecisionMakerAbciApp.transition_function
        assert (
            tx[PostOmenWithdrawRound][Event.WITHDRAWAL_ROUND_TIMEOUT]
            is WithdrawalIdleRound
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

        # ``_finish`` re-fetches positions for the locked-funds snapshot —
        # stub it out so the FETCH_ALL_POSITIONS count isolates the retry
        # helper rather than mixing in the post-sweep snapshot fetch.
        def fake_snapshot() -> Generator[Any, None, None]:
            yield

        behaviour._snapshot_locked_funds = fake_snapshot  # type: ignore[method-assign,assignment]

        # All three fetch attempts return an error dict.
        err = {"error": "502 bad gateway"}
        router, sent = _make_request_router(
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
        # The top-level retry must run ``max_attempts`` attempts (== 3 with
        # the default backoff=[1, 1]) and sleep once per inter-attempt gap
        # (== 2 sleeps). Pinned to catch a regression to ``enumerate(backoff)``
        # which silently drops one attempt.
        sent_fetches = [
            p
            for p in sent
            if p.get("request_type") == RequestType.FETCH_ALL_POSITIONS.value
        ]
        assert len(sent_fetches) == 3
        assert captured_sleep == [1, 1]

    @pytest.mark.parametrize("max_attempts", [2, 3, 4])
    def test_top_level_retry_attempts_match_max_attempts(
        self, tmp_path: Path, max_attempts: int
    ) -> None:
        """Top-level retry must run exactly ``max_attempts`` attempts.

        Mirrors the per-position retry's contract — same
        ``withdrawal_max_fak_attempts`` knob, same call count. Falsifiable:
        reverting the loop to ``enumerate(backoff)`` drops one attempt and
        fails every parametrized case.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        :param max_attempts: total FAK attempts to drive through the helper.
        """
        _seed_store(tmp_path)
        backoff = [1] * (max_attempts - 1)
        behaviour = _make_behaviour(
            tmp_path, backoff=backoff, max_attempts=max_attempts
        )
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        def fake_snapshot() -> Generator[Any, None, None]:
            yield

        behaviour._snapshot_locked_funds = fake_snapshot  # type: ignore[method-assign,assignment]

        err = {"error": "boom"}
        router, sent = _make_request_router(
            fetch_responses=[err] * max_attempts,
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        sent_fetches = [
            p
            for p in sent
            if p.get("request_type") == RequestType.FETCH_ALL_POSITIONS.value
        ]
        assert len(sent_fetches) == max_attempts
        assert len(captured_sleep) == max_attempts - 1

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        assert len(store["withdrawal_errors"]) == 1
        assert store["withdrawal_errors"][0]["token_id"] == ""

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

    def test_poll_empty_then_terminal_keeps_polling(self, tmp_path: Path) -> None:
        """Falsy GET_ORDER body (not-yet-indexed) must not short-circuit.

        Shortly after ``post_order`` the data API can return an empty
        body before the order is indexed. The poll loop must treat that
        as "keep polling" — not as an error, not as a terminal status —
        so a subsequent terminal match still records the fill.

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
        terminal_match = {
            "id": "0xpending",
            "status": "ORDER_STATUS_MATCHED",
            "size_matched": "10000000",
            "original_size": "10000000",
            "price": "0.50",
        }
        # First GET_ORDER returns an empty (falsy) body — not yet indexed;
        # second poll returns terminal match. Loop must reach the match.
        router, _ = _make_request_router(
            fetch_responses=[positions],
            sell_responses=[delayed_resp],
            get_order_responses=[{}, terminal_match],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_COMPLETE
        assert len(store["withdrawal_fills"]) == 1
        assert store["withdrawal_fills"][0]["shares_sold"] == pytest.approx(10.0)
        assert store["withdrawal_errors"] == []

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

    # --- locked-funds snapshot ----------------------------------------------

    def test_finish_snapshots_locked_funds_on_clean_complete(
        self, tmp_path: Path
    ) -> None:
        """Clean sweep terminal state triggers a fresh locked-funds snapshot.

        Sweep sells one position cleanly, then ``_finish()`` re-fetches
        positions (returning two unredeemable leftovers) and sums
        ``initialValue`` (cost basis) across them to update
        ``funds_locked_in_markets``. Cost basis matches the formula
        used by the normal performance-summary round, avoiding a
        non-monotonic jump on the FE when the next normal round
        overwrites this value.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions_initial = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.40,
            "raw": {},
        }
        # Post-sweep snapshot: two locked positions remain.
        positions_post_sweep = [
            {
                "asset": TOK_B,
                "size": 20.0,
                "initialValue": "10.0",
                "redeemable": False,
            },
            {
                "asset": TOK_C,
                "size": 5.0,
                "initialValue": "4.0",
                "redeemable": False,
            },
        ]
        router, _ = _make_request_router(
            fetch_responses=[positions_initial, positions_post_sweep],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # initialValue 10.0 + 4.0 = 14.0
        behaviour.context.state.update_funds_locked_in_markets.assert_called_once_with(
            14.0
        )

    def test_finish_snapshot_excludes_redeemable_positions(
        self, tmp_path: Path
    ) -> None:
        """Redeemable positions don't contribute to locked-value sum.

        Redeemable positions are settled and waiting for redemption —
        their value isn't ``locked``. Only unredeemable positions count.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions_initial = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.40,
            "raw": {},
        }
        positions_post_sweep = [
            {  # included
                "asset": TOK_B,
                "size": 20.0,
                "initialValue": "10.0",
                "redeemable": False,
            },
            {  # excluded — redeemable
                "asset": TOK_C,
                "size": 100.0,
                "initialValue": "100.0",
                "redeemable": True,
            },
        ]
        router, _ = _make_request_router(
            fetch_responses=[positions_initial, positions_post_sweep],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Only TOK_B contributes: 10.0. TOK_C is redeemable.
        behaviour.context.state.update_funds_locked_in_markets.assert_called_once_with(
            10.0
        )

    def test_finish_snapshot_handles_missing_initial_value(
        self, tmp_path: Path
    ) -> None:
        """A missing or null ``initialValue`` contributes 0 to the sum.

        Defensive against partial position records returned by the data
        API; the snapshot must not crash on missing cost-basis data.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions_initial = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.40,
            "raw": {},
        }
        positions_post_sweep = [
            {
                "asset": TOK_B,
                "size": 20.0,
                "initialValue": "10.0",
                "redeemable": False,
            },
            {  # missing initialValue
                "asset": TOK_C,
                "size": 100.0,
                "redeemable": False,
            },
            {  # null initialValue
                "asset": "0xd1",
                "size": 50.0,
                "initialValue": None,
                "redeemable": False,
            },
        ]
        router, _ = _make_request_router(
            fetch_responses=[positions_initial, positions_post_sweep],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Only TOK_B contributes a known cost basis: 10.0.
        behaviour.context.state.update_funds_locked_in_markets.assert_called_once_with(
            10.0
        )

    def test_finish_snapshot_handles_unparseable_value(self, tmp_path: Path) -> None:
        """Unparseable ``initialValue`` skips the snapshot without stalling FSM.

        ``float("N/A")`` raises ``ValueError`` mid-sum. Without the
        broad except in ``_snapshot_locked_funds`` this would escape
        ``_finish`` and block ``finish_behaviour(payload)`` from
        emitting → FSM stall. The fix is best-effort: log + skip,
        then continue to payload emission.

        Falsifiable against a regression that drops the broad except.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions_initial = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.40,
            "raw": {},
        }
        positions_post_sweep = [
            {
                "asset": TOK_B,
                "size": 20.0,
                "initialValue": "N/A",  # unparseable
                "redeemable": False,
            },
        ]
        router, _ = _make_request_router(
            fetch_responses=[positions_initial, positions_post_sweep],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Update was NOT called (whole compute skipped on unparseable value).
        behaviour.context.state.update_funds_locked_in_markets.assert_not_called()
        # Compute/write warning was logged.
        warnings = [
            str(call.args[0])
            for call in behaviour.context.logger.warning.call_args_list
        ]
        assert any(
            "compute/write failed" in w for w in warnings
        ), f"expected 'compute/write failed' warning; got: {warnings}"
        # Critically: payload still emitted — FSM did not stall.
        assert "payload" in captured_payload

    def test_finish_snapshot_zero_positions_records_zero(self, tmp_path: Path) -> None:
        """Empty post-sweep positions list records ``funds_locked_in_markets=0.0``.

        After a clean sweep that closed every unredeemable position,
        the operator should see locked funds drop to zero immediately.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions_initial = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.40,
            "raw": {},
        }
        # Post-sweep: nothing left.
        router, _ = _make_request_router(
            fetch_responses=[positions_initial, []],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        behaviour.context.state.update_funds_locked_in_markets.assert_called_once_with(
            0.0
        )

    def test_finish_snapshot_on_fetch_failure_logs_and_skips(
        self, tmp_path: Path
    ) -> None:
        """Post-sweep fetch failure logs warning, doesn't update perf summary.

        The snapshot is best-effort: a transient API issue must NOT
        propagate out of ``_finish()`` (which would prevent payload
        emission and stall the FSM). Instead, log + skip; performance
        summary keeps its previous value, refreshed on next normal round.

        Falsifiable against a regression that propagates the fetch
        error and crashes ``_finish()``.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        positions_initial = [_make_position(TOK_A, size=10.0)]
        sell_resp = {
            "order_id": "o-1",
            "status": "matched",
            "filled_shares": 10.0,
            "filled_usdc": 4.0,
            "fill_price": 0.40,
            "raw": {},
        }
        # Post-sweep fetch returns the connection-error envelope.
        fetch_error = {"error": "Polymarket API timeout"}
        router, _ = _make_request_router(
            fetch_responses=[positions_initial, fetch_error],
            sell_responses=[sell_resp],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Update was NOT called.
        behaviour.context.state.update_funds_locked_in_markets.assert_not_called()
        # Warning was logged.
        warnings = [
            str(call.args[0])
            for call in behaviour.context.logger.warning.call_args_list
        ]
        assert any(
            "skipping locked-funds snapshot" in w for w in warnings
        ), f"expected 'skipping locked-funds snapshot' warning; got: {warnings}"

    def test_finish_snapshot_on_initial_fetch_failure_path(
        self, tmp_path: Path
    ) -> None:
        """Top-level fetch failure path also runs the snapshot, also skips cleanly.

        The very first ``_request_fetch_positions`` (at the top of
        ``async_act``) fails with retries exhausted → the behaviour
        records a top-level error and routes to ``_finish()``. The
        snapshot's own fetch is also likely to fail in this scenario,
        so it must skip cleanly without crashing the consensus payload.

        :param tmp_path: pytest-supplied tmp directory used as the store path.
        """
        _seed_store(tmp_path)
        behaviour = _make_behaviour(tmp_path, backoff=[1])
        captured_payload: Dict[str, Any] = {}
        captured_sleep: List[int] = []
        _wire_helpers(behaviour, captured_payload, captured_sleep)

        # Both fetches return an error (top-level + snapshot).
        # The first fetch retry loop runs (max_attempts=2); the snapshot
        # is one more fetch on top of that.
        fetch_error = {"error": "Polymarket API timeout"}
        router, _ = _make_request_router(
            fetch_responses=[fetch_error, fetch_error, fetch_error],
            sell_responses=[],
        )
        behaviour.send_polymarket_connection_request = router  # type: ignore[method-assign,assignment]

        list(behaviour.async_act())

        # Snapshot's own fetch fails → update NOT called, no crash.
        behaviour.context.state.update_funds_locked_in_markets.assert_not_called()
        # Sweep ended ``errored`` because positions fetch failed.
        store = _read_store(tmp_path)
        assert store["withdrawal_state"] == WITHDRAWAL_STATE_ERRORED
        # Consensus payload was still emitted via the regular finish flow.
        assert "payload" in captured_payload


class TestOmenWithdrawBehaviourSurface:
    """Surface tests for the real Omen sweep behaviour.

    Heavier end-to-end coverage of ``async_act`` lives next to the
    contract / subgraph / round wiring tests; this class only sanity-checks
    that the stub has been replaced with the multi-step pipeline and that
    the module-level helpers behave per spec §6.3.
    """

    def test_module_exports_inflate_for_slippage(self) -> None:
        """``inflate_for_slippage`` (§6.3 ceiling-direction helper) is exposed."""
        from packages.valory.skills.decision_maker_abci.behaviours.omen_withdraw import (
            inflate_for_slippage,
        )

        # Round-up invariant: even tiny slippage strictly exceeds N_estimate
        # (the ``+1`` guards against integer floor under-shoot).
        assert inflate_for_slippage(100, 0.01) == 102
        # Zero amount with non-zero slippage still rounds up via the +1.
        assert inflate_for_slippage(0, 0.5) == 1
        # Asymmetry vs the buy-side helper: inflation strictly exceeds the
        # input, while the buy-side ``remove_fraction_wei`` strictly shrinks.
        assert inflate_for_slippage(1_000_000, 0.05) > 1_000_000

    def test_inflate_for_slippage_rejects_out_of_range(self) -> None:
        """Verify slippage must live in [0, 1] (closed interval)."""
        from packages.valory.skills.decision_maker_abci.behaviours.omen_withdraw import (
            inflate_for_slippage,
        )

        with pytest.raises(ValueError):
            inflate_for_slippage(100, -0.01)
        with pytest.raises(ValueError):
            inflate_for_slippage(100, 1.01)


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


# ---------------------------------------------------------------------------
# PostOmenWithdrawBehaviour._snapshot_funds_locked (cross-skill hook)
# ---------------------------------------------------------------------------


class TestOmenWithdrawSizingLoopDiagnostics:
    """The sizing loop has three distinct failure modes that pre-fix all
    surfaced as ``returnAmount could not be sized...``. The split ensures
    each failure mode self-attributes with an operator-actionable reason,
    and that the halve-to-zero path doesn't depend on the post-loop guard
    (which would silently drop if a future refactor removed that guard).
    """

    fpmm = "0x9371158c040dc04AdeC99E03f82CDa9C0D804af7"
    condition = "0x" + "a1" * 32

    def _make_behaviour(self) -> Any:
        """Build a bare OmenWithdrawBehaviour with stubbed context + store."""
        from packages.valory.skills.decision_maker_abci.behaviours.omen_withdraw import (
            OmenWithdrawBehaviour,
        )

        behaviour = object.__new__(OmenWithdrawBehaviour)
        mock_context = MagicMock()
        mock_context.logger = MagicMock()
        mock_context.params.withdrawal_slippage = 0.01
        mock_context.params.withdrawal_return_buffer = 0.05
        mock_context.params.dust_epsilon_wxdai = 10**15
        behaviour._context = mock_context  # type: ignore[attr-defined]
        store = MagicMock()
        behaviour._store_cache = store  # type: ignore[attr-defined]
        return behaviour

    def _position(self) -> Any:
        """Build a representative WithdrawablePosition."""
        from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
            WithdrawablePosition,
        )

        return WithdrawablePosition(
            fpmm_address=self.fpmm,
            outcome_index=0,
            balance=10**18,
            condition_id=self.condition,
            index_set=1,
            token_id="123",
        )

    @staticmethod
    def _drive(gen: Generator) -> Any:
        try:
            while True:
                next(gen)
        except StopIteration as exc:
            return exc.value

    @staticmethod
    def _stub_pool_balances(behaviour: Any, balances: List[int]) -> None:
        """Stub ``_read_pool_balances`` to return the given balances."""

        def fake_read(_position: Any) -> Generator[None, None, Optional[List[int]]]:
            return list(balances)
            yield  # pragma: no cover

        behaviour._read_pool_balances = fake_read  # type: ignore[assignment]

    @staticmethod
    def _stub_calc_sell_amount(
        behaviour: Any, side_effect: Callable[..., Any]
    ) -> None:
        """Stub ``_calc_sell_amount_static`` with the given side-effect callable."""

        def fake_calc(
            fpmm_address: str, return_amount: int, outcome_index: int
        ) -> Generator[None, None, Optional[int]]:
            return side_effect(return_amount)
            yield  # pragma: no cover

        behaviour._calc_sell_amount_static = fake_calc  # type: ignore[assignment]

    def test_calc_sell_amount_revert_records_distinct_error(self) -> None:
        """``n_estimate is None`` from the first call -> 'calcSellAmount reverted'."""
        behaviour = self._make_behaviour()
        # Pool balanced so notional clears dust threshold.
        self._stub_pool_balances(behaviour, [10**20, 10**20])
        self._stub_calc_sell_amount(behaviour, lambda ra: None)

        result = self._drive(behaviour._size_and_build_position(self._position()))

        assert result is None
        recorded = behaviour._store_cache.record_error.call_args_list
        assert len(recorded) == 1
        reason = recorded[0].args[1]
        assert "calcSellAmount reverted" in reason

    def test_halve_to_zero_records_pool_depth_error(self) -> None:
        """``return_amount`` halved to 0 -> distinct 'pool too thin' error.

        The pre-fix path used ``break`` and depended on the post-loop
        guard at L327. With explicit self-record, the failure mode is
        named operator-actionably and the post-loop guard becomes a
        true defensive-only check.

        Forcing halve-to-zero under the production constants requires
        a tiny ``return_amount`` start (so ≤5 halvings reach 0) — set
        ``dust_epsilon_wxdai = 0`` and use a small balance to bypass
        the dust gate.
        """
        from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
            WithdrawablePosition,
        )

        behaviour = self._make_behaviour()
        behaviour.context.params.dust_epsilon_wxdai = 0
        # Tiny balance: notional ≈ 16, return_amount ≈ 15 → halves
        # 15 → 7 → 3 → 1 → 0 (reaches zero at iteration 4).
        position = WithdrawablePosition(
            fpmm_address=self.fpmm,
            outcome_index=0,
            balance=32,
            condition_id=self.condition,
            index_set=1,
            token_id="123",
        )
        self._stub_pool_balances(behaviour, [10**20, 10**20])
        # n_estimate always above headroom_cap → loop keeps halving.
        self._stub_calc_sell_amount(behaviour, lambda ra: 10**30)

        result = self._drive(behaviour._size_and_build_position(position))

        assert result is None
        recorded = behaviour._store_cache.record_error.call_args_list
        # One error recorded for the halve-to-zero exit.
        assert len(recorded) == 1
        reason = recorded[0].args[1]
        assert "halved to zero" in reason
        assert "pool too thin" in reason

    def test_max_attempts_exhausted_records_slippage_error(self) -> None:
        """5 iterations with ``n_estimate > headroom`` AND ``return_amount > 0``.

        Triggers the ``for/else`` clause — distinct from halve-to-zero
        — and emits the slippage-actionable diagnostic.
        """
        behaviour = self._make_behaviour()
        self._stub_pool_balances(behaviour, [10**20, 10**20])

        # n_estimate above headroom_cap; return_amount stays > 0 because
        # we start at a huge value and 5 halvings still leaves room.
        # headroom_cap ≈ balance / (1 + 0.01) ≈ 0.99e18
        # Start: return_amount = notional*(1 - buffer)
        # With pool 50/50 and balance 1e18: notional ≈ 0.5e18,
        # return_amount ≈ 0.475e18 -> halves down through ~0.029e18 after
        # 4 halvings, > 0. With n_estimate >> headroom_cap each time, the
        # loop runs all 5 iterations.
        self._stub_calc_sell_amount(behaviour, lambda ra: 10**30)

        # Override balance to give headroom big enough that 5 halvings
        # of return_amount don't reach zero.
        position = self._position()
        from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
            WithdrawablePosition,
        )

        # 5 halvings of ~0.475e18 lands at ~0.0148e18 > 0. With a much
        # larger pool, headroom stays positive — but we need a path where
        # the loop completes naturally without halving to 0. Increase the
        # balance scale so the initial return_amount can survive 5 halves.
        position = WithdrawablePosition(
            fpmm_address=position.fpmm_address,
            outcome_index=position.outcome_index,
            balance=10**24,  # 1e6 wxDAI position
            condition_id=position.condition_id,
            index_set=position.index_set,
            token_id=position.token_id,
        )

        result = self._drive(behaviour._size_and_build_position(position))

        assert result is None
        recorded = behaviour._store_cache.record_error.call_args_list
        assert len(recorded) == 1
        reason = recorded[0].args[1]
        assert "attempts exhausted" in reason
        assert "withdrawal_slippage" in reason


class TestPostOmenWithdrawParseSellEventsFilter:
    """Tests for the planned-FPMM allowlist filter in ``_parse_sell_events``.

    Without the filter, an FPMMSell event emitted by a non-target FPMM
    (cross-contract hook, fee distributor, future integration) in the
    same receipt as a real sweep would silently land in the operator
    audit trail. The post-settlement behaviour filters decoded events
    against the planned-FPMM set persisted by ``OmenWithdrawBehaviour``.
    """

    @staticmethod
    def _make_behaviour(planned: Optional[List[str]] = None) -> Any:
        """Build a bare PostOmenWithdrawBehaviour with stubbed store + context."""
        from packages.valory.skills.decision_maker_abci.behaviours.post_omen_withdraw import (
            PostOmenWithdrawBehaviour,
        )

        behaviour = object.__new__(PostOmenWithdrawBehaviour)
        mock_context = MagicMock()
        mock_context.logger = MagicMock()
        behaviour._context = mock_context  # type: ignore[attr-defined]

        store = MagicMock()
        store.planned_fpmms.return_value = list(planned) if planned else []
        behaviour._store_cache = store  # type: ignore[attr-defined]
        return behaviour

    @staticmethod
    def _stub_contract_response(behaviour: Any, events: List[Dict[str, Any]]) -> None:
        """Stub ``get_contract_api_response`` to return the given events."""
        from packages.valory.protocols.contract_api import ContractApiMessage

        response = MagicMock()
        response.performative = ContractApiMessage.Performative.STATE
        response.state.body = {"events": events}

        def fake_call(**_kwargs: Any) -> Generator[None, None, Any]:
            return response
            yield  # pragma: no cover

        behaviour.get_contract_api_response = fake_call  # type: ignore[assignment]
        params_mock = MagicMock()
        params_mock.mech_chain_id = "gnosis"
        synced_mock = MagicMock()
        synced_mock.final_tx_hash = "0xabc"
        # ``params`` and ``synchronized_data`` are read-only properties on
        # the base behaviours — patch via type() so direct assignment works.
        type(behaviour).params = PropertyMock(  # type: ignore[misc]
            return_value=params_mock
        )
        type(behaviour).synchronized_data = PropertyMock(  # type: ignore[misc]
            return_value=synced_mock
        )

    @staticmethod
    def _drive(gen: Generator) -> Any:
        try:
            while True:
                next(gen)
        except StopIteration as exc:
            return exc.value

    def test_events_from_planned_fpmms_kept(self) -> None:
        """Events whose ``fpmm`` is in the allowlist pass through."""
        good_fpmm = "0xAAA0000000000000000000000000000000000000"
        behaviour = self._make_behaviour(planned=[good_fpmm])
        self._stub_contract_response(
            behaviour,
            [
                {
                    "seller": "0xseller",
                    "fpmm": good_fpmm,
                    "outcome_index": 0,
                    "return_amount": 42,
                    "fee_amount": 0,
                    "outcome_tokens_sold": 100,
                }
            ],
        )

        result = self._drive(behaviour._parse_sell_events({"logs": []}))

        assert result is not None and len(result) == 1
        assert result[0]["fpmm"] == good_fpmm

    def test_events_from_unplanned_fpmm_dropped(self) -> None:
        """Events from FPMMs not in the allowlist are filtered out + warned."""
        good_fpmm = "0xAAA0000000000000000000000000000000000000"
        rogue_fpmm = "0xDEAD000000000000000000000000000000000000"
        behaviour = self._make_behaviour(planned=[good_fpmm])
        self._stub_contract_response(
            behaviour,
            [
                {
                    "seller": "0xs1",
                    "fpmm": good_fpmm,
                    "outcome_index": 0,
                    "return_amount": 42,
                    "fee_amount": 0,
                    "outcome_tokens_sold": 100,
                },
                {
                    "seller": "0xs2",
                    "fpmm": rogue_fpmm,
                    "outcome_index": 1,
                    "return_amount": 99,
                    "fee_amount": 0,
                    "outcome_tokens_sold": 50,
                },
            ],
        )

        result = self._drive(behaviour._parse_sell_events({"logs": []}))

        assert result is not None and len(result) == 1
        assert result[0]["fpmm"] == good_fpmm
        # The drop fires a warning naming the rogue address.
        warnings = [
            str(call.args) for call in behaviour.context.logger.warning.call_args_list
        ]
        assert any(rogue_fpmm in w for w in warnings), warnings

    def test_filter_is_case_insensitive(self) -> None:
        """Checksum vs lower-case address mismatch does not drop a real fill."""
        # Allowlist stored lower-cased (record_planned_fpmms normalises);
        # event arrives checksum-cased (to_checksum_address output).
        planned_lower = "0xaaa0000000000000000000000000000000000000"
        event_checksum = "0xAAA0000000000000000000000000000000000000"
        behaviour = self._make_behaviour(planned=[planned_lower])
        self._stub_contract_response(
            behaviour,
            [
                {
                    "seller": "0xs",
                    "fpmm": event_checksum,
                    "outcome_index": 0,
                    "return_amount": 1,
                    "fee_amount": 0,
                    "outcome_tokens_sold": 1,
                }
            ],
        )

        result = self._drive(behaviour._parse_sell_events({"logs": []}))
        assert result is not None and len(result) == 1

    def test_missing_allowlist_falls_through_with_warning(self) -> None:
        """No persisted allowlist -> events returned unfiltered + warning logged.

        Backwards compatibility: a legacy session that ran before the
        planning step recorded its FPMMs shouldn't lose its fills.
        """
        behaviour = self._make_behaviour(planned=None)
        any_fpmm = "0xAAA0000000000000000000000000000000000000"
        self._stub_contract_response(
            behaviour,
            [
                {
                    "seller": "0xs",
                    "fpmm": any_fpmm,
                    "outcome_index": 0,
                    "return_amount": 1,
                    "fee_amount": 0,
                    "outcome_tokens_sold": 1,
                }
            ],
        )

        result = self._drive(behaviour._parse_sell_events({"logs": []}))

        assert result is not None and len(result) == 1
        warnings = [
            str(call.args) for call in behaviour.context.logger.warning.call_args_list
        ]
        assert any("allowlist" in w for w in warnings), warnings


class TestPostOmenWithdrawSnapshotFundsLocked:
    """Tests for the cross-skill funds_locked snapshot hook.

    The hook fetches the bet history, runs the per-position formula, and
    writes the result into the shared agent_performance_summary state.
    Failure is non-fatal — exceptions get caught and logged, leaving the
    next normal perf-summary round to catch up.
    """

    @staticmethod
    def _make_behaviour() -> Any:
        """Build a bare PostOmenWithdrawBehaviour with stubbed context."""
        # Local import — module-level import would pollute the test
        # collection if the omen_withdraw module fails to import.
        from packages.valory.skills.decision_maker_abci.behaviours.post_omen_withdraw import (
            PostOmenWithdrawBehaviour,
        )

        behaviour = object.__new__(PostOmenWithdrawBehaviour)
        mock_context = MagicMock()
        mock_context.logger = MagicMock()
        behaviour._context = mock_context  # type: ignore[attr-defined]
        return behaviour

    def test_writes_snapshot_to_shared_state(self) -> None:
        """A successful fetch + compute writes the rounded value via the setter."""
        behaviour = self._make_behaviour()
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSAFE"

        # Fixture: one open buy of 2.5 wxDAI; remaining_cost = 2.5.
        condition_id = "0x" + "a1" * 32
        trader_agent = {
            "bets": [
                {
                    "id": "b1",
                    "amount": str(int(2.5 * 10**18)),
                    "outcomeTokenAmount": str(5 * 10**18),
                    "outcomeIndex": 0,
                    "blockTimestamp": "1000",
                    "fixedProductMarketMaker": {
                        "id": "0xa1",
                        "currentAnswer": None,
                        "conditionIds": [condition_id],
                    },
                }
            ]
        }

        def fake_fetch(_safe: str) -> Generator[Any, None, dict]:
            return trader_agent
            yield  # pragma: no cover — generator-shape preservation

        def fake_held(_safe: str) -> Generator[Any, None, set]:
            return {(condition_id.lower(), 0)}
            yield  # pragma: no cover

        with (
            patch.object(
                type(behaviour),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_synced,
            ),
            patch.object(
                behaviour,
                "_fetch_trader_agent_performance",
                side_effect=fake_fetch,
            ),
            patch.object(
                behaviour,
                "_fetch_ct_held_position_keys",
                side_effect=fake_held,
            ),
        ):
            list(behaviour._snapshot_funds_locked())

        behaviour.context.state.update_funds_locked_in_markets.assert_called_once_with(
            2.5
        )

    def test_empty_trader_agent_skips_write(self) -> None:
        """No bets -> no write; behaviour still completes."""
        behaviour = self._make_behaviour()
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSAFE"

        def fake_fetch(_safe: str) -> Generator[Any, None, Optional[dict]]:
            return None
            yield  # pragma: no cover

        with (
            patch.object(
                type(behaviour),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_synced,
            ),
            patch.object(
                behaviour,
                "_fetch_trader_agent_performance",
                side_effect=fake_fetch,
            ),
        ):
            list(behaviour._snapshot_funds_locked())

        behaviour.context.state.update_funds_locked_in_markets.assert_not_called()
        # Defensive warning is logged.
        assert behaviour.context.logger.warning.called

    def test_empty_bets_skips_write_on_indexer_lag(self) -> None:
        """``trader_agent`` returned but ``bets=[]`` -> skip, don't write 0.0.

        ``_snapshot_funds_locked`` only runs after a sweep settled, so
        the safe definitively has on-chain history. An empty ``bets``
        array from a successful fetch is indexer lag — falling through
        to ``compute_funds_locked_from_bets([])`` would write a phantom
        ``0.0`` to ``funds_locked_in_markets``, showing the user "all
        funds recovered" until the next normal perf-summary round.
        """
        behaviour = self._make_behaviour()
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSAFE"

        def fake_fetch(_safe: str) -> Generator[Any, None, Optional[dict]]:
            return {"bets": [], "totalBets": "0"}
            yield  # pragma: no cover

        with (
            patch.object(
                type(behaviour),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_synced,
            ),
            patch.object(
                behaviour,
                "_fetch_trader_agent_performance",
                side_effect=fake_fetch,
            ),
        ):
            list(behaviour._snapshot_funds_locked())

        behaviour.context.state.update_funds_locked_in_markets.assert_not_called()
        # Specific warning mentions indexer lag.
        warnings = [
            call.args[0] for call in behaviour.context.logger.warning.call_args_list
        ]
        assert any("indexer lag" in w for w in warnings), warnings

    def test_fetch_failure_caught_and_logged(self) -> None:
        """Subgraph fetch raising is non-fatal — log + continue."""
        behaviour = self._make_behaviour()
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSAFE"

        def fake_fetch(_safe: str) -> Generator[Any, None, dict]:
            raise RuntimeError("subgraph down")
            yield  # pragma: no cover

        with (
            patch.object(
                type(behaviour),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_synced,
            ),
            patch.object(
                behaviour,
                "_fetch_trader_agent_performance",
                side_effect=fake_fetch,
            ),
        ):
            # No exception escapes.
            list(behaviour._snapshot_funds_locked())

        behaviour.context.state.update_funds_locked_in_markets.assert_not_called()
        assert behaviour.context.logger.warning.called

    def test_ct_fetch_returns_none_writes_ungated_sum(self) -> None:
        """CT fetcher error -> ``None`` -> snapshot writes the un-gated sum.

        Guards against the regression where the fetcher returned
        ``set()`` on error and a transient CT-subgraph hiccup wrote a
        phantom ``0.0`` to ``funds_locked_in_markets``. With the fix,
        the snapshot falls back to the un-gated FIFO sum (matching the
        pre-Phase-3B behaviour) instead of collapsing every position
        out.
        """
        behaviour = self._make_behaviour()
        mock_synced = MagicMock()
        mock_synced.safe_contract_address = "0xSAFE"

        condition_id = "0x" + "a1" * 32
        trader_agent = {
            "bets": [
                {
                    "id": "b1",
                    "amount": str(int(2.5 * 10**18)),
                    "outcomeTokenAmount": str(5 * 10**18),
                    "outcomeIndex": 0,
                    "blockTimestamp": "1000",
                    "fixedProductMarketMaker": {
                        "id": "0xa1",
                        "currentAnswer": None,
                        "conditionIds": [condition_id],
                    },
                }
            ]
        }

        def fake_fetch(_safe: str) -> Generator[Any, None, dict]:
            return trader_agent
            yield  # pragma: no cover

        def fake_held(_safe: str) -> Generator[Any, None, Optional[set]]:
            return None
            yield  # pragma: no cover

        with (
            patch.object(
                type(behaviour),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_synced,
            ),
            patch.object(
                behaviour,
                "_fetch_trader_agent_performance",
                side_effect=fake_fetch,
            ),
            patch.object(
                behaviour,
                "_fetch_ct_held_position_keys",
                side_effect=fake_held,
            ),
        ):
            list(behaviour._snapshot_funds_locked())

        behaviour.context.state.update_funds_locked_in_markets.assert_called_once_with(
            2.5
        )
