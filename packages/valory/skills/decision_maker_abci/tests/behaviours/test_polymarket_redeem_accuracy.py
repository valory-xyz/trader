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

"""Tests proving PREDICT-769: local accuracy store not updated for Polystrat.

Level 3 - the accuracy store is never updated at redemption time:
  ``PolymarketRedeemBehaviour`` fetches redeemable positions (positions whose
  market resolved with a win for the agent) but never calls
  ``policy.update_accuracy_store(tool, winning=True)``.  This means the
  e-greedy policy learns nothing from Polymarket bets and tool selection
  stays permanently uninformed.

These tests prove the bug by asserting:
  a) the behaviour exposes a ``_update_policy_for_redeemable_positions`` method
     that encapsulates the accuracy-store update logic, and
  b) that method actually updates the policy ``accuracy_store`` for every
     redeemable position whose ``conditionId`` is recorded in ``utilized_tools``.

On the *original* code the method did not exist at all, causing an
``AttributeError`` (tests a + b), and even when the method was mentioned in
the TODO the update was never performed.
"""

from unittest.mock import MagicMock

from packages.valory.skills.decision_maker_abci.behaviours.polymarket_reedem import (
    PolymarketRedeemBehaviour,
)
from packages.valory.skills.decision_maker_abci.policy import (
    AccuracyInfo,
    EGreedyPolicy,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONDITION_ID_KNOWN = "0xaaaa"
CONDITION_ID_UNKNOWN = "0xbbbb"
MECH_TOOL = "prediction-offline"
INITIAL_ACCURACY = 0.6
INITIAL_REQUESTS = 10

# curPrice is 1.0 for a winning resolved token, 0.0 for a losing one.
REDEEMABLE_POSITIONS_WINNING = [
    {
        "conditionId": CONDITION_ID_KNOWN,
        "outcomeIndex": 0,
        "outcome": "Yes",
        "size": 100.0,
        "negativeRisk": False,
        "curPrice": 1.0,
    }
]
REDEEMABLE_POSITIONS_LOSING = [
    {
        "conditionId": CONDITION_ID_KNOWN,
        "outcomeIndex": 0,
        "outcome": "Yes",
        "size": 100.0,
        "negativeRisk": False,
        "curPrice": 0.0,
    }
]
# Alias used by tests that don't care about win/loss direction.
REDEEMABLE_POSITIONS = REDEEMABLE_POSITIONS_WINNING


def _make_policy(tool: str = MECH_TOOL) -> EGreedyPolicy:
    """Return a policy with one tool in the accuracy store."""
    return EGreedyPolicy(
        eps=0.25,
        consecutive_failures_threshold=2,
        quarantine_duration=10800,
        accuracy_store={
            tool: AccuracyInfo(
                accuracy=INITIAL_ACCURACY, pending=1, requests=INITIAL_REQUESTS
            )
        },
    )


def _make_behaviour() -> PolymarketRedeemBehaviour:
    """Return a PolymarketRedeemBehaviour with just the minimum attributes.

    :return: a partially constructed PolymarketRedeemBehaviour instance.
    """
    behaviour = object.__new__(PolymarketRedeemBehaviour)

    # policy / utilized_tools are accessed as properties on the parent class;
    # we assign them directly to the instance's __dict__ to bypass the
    # property descriptor for testing purposes.
    behaviour.__dict__["_policy"] = _make_policy()
    behaviour.__dict__["_utilized_tools"] = {CONDITION_ID_KNOWN: MECH_TOOL}

    # context is a read-only property on BaseBehaviour that returns self._context;
    # inject _context directly to bypass the descriptor.
    logger = MagicMock()
    context = MagicMock()
    context.logger = logger
    behaviour.__dict__["_context"] = context

    return behaviour  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Level 3a: method must exist
# ---------------------------------------------------------------------------


class TestUpdatePolicyMethodExists:
    """The method _update_policy_for_redeemable_positions must exist.

    On the original code it did not; the TODO comment acknowledged this gap
    but no implementation was provided.
    """

    def test_method_exists_on_behaviour(self) -> None:
        """Behaviour must have _update_policy_for_redeemable_positions.

        Without this method there is simply no code path that can update the
        accuracy store for Polymarket bets.  On the original code this assertion
        raises AttributeError, proving the bug.
        """
        assert hasattr(
            PolymarketRedeemBehaviour, "_update_policy_for_redeemable_positions"
        ), (
            "PolymarketRedeemBehaviour is missing '_update_policy_for_redeemable_positions'. "
            "The accuracy store is therefore never updated for Polystrat (PREDICT-769)."
        )

    def test_method_is_callable(self) -> None:
        """The method must be callable (not e.g. a property or class variable)."""
        method = getattr(
            PolymarketRedeemBehaviour, "_update_policy_for_redeemable_positions", None
        )
        assert callable(
            method
        ), "_update_policy_for_redeemable_positions exists but is not callable."


# ---------------------------------------------------------------------------
# Level 3b: method must update accuracy_store for known tools
# ---------------------------------------------------------------------------


class TestUpdatePolicyForRedeemablePositions:
    """_update_policy_for_redeemable_positions must call policy.update_accuracy_store for every settled position whose conditionId appears in utilized_tools.

    ``redeemable=True`` from the Polymarket API includes BOTH winning and losing
    settled positions.  ``curPrice`` is 1.0 for winning outcome tokens and 0.0
    for losing ones once the market resolves.  The method must pass the correct
    ``winning`` value to ``update_accuracy_store`` in both cases.
    """

    def test_accuracy_store_updated_for_known_condition_id(self) -> None:
        """When a redeemable position's conditionId is in utilized_tools the policy's accuracy store must be updated (requests incremented, accuracy recalculated).

        On the original code the method did not exist, so this would raise
        AttributeError and the accuracy store was never mutated.
        """
        behaviour = _make_behaviour()
        initial_requests = behaviour._policy.accuracy_store[MECH_TOOL].requests  # type: ignore[union-attr]

        behaviour._update_policy_for_redeemable_positions(REDEEMABLE_POSITIONS_WINNING)  # type: ignore[attr-defined]

        final_requests = behaviour._policy.accuracy_store[MECH_TOOL].requests  # type: ignore[union-attr]
        assert final_requests == initial_requests + 1, (
            f"accuracy_store[{MECH_TOOL!r}].requests was not incremented. "
            "update_accuracy_store was never called for this position."
        )

    def test_accuracy_updated_as_winning_when_cur_price_is_one(self) -> None:
        """curPrice=1.0 means the token won; accuracy must increase."""
        behaviour = _make_behaviour()
        behaviour._policy.accuracy_store[MECH_TOOL] = AccuracyInfo(  # type: ignore[union-attr]
            accuracy=0.5, pending=1, requests=10
        )

        behaviour._update_policy_for_redeemable_positions(REDEEMABLE_POSITIONS_WINNING)  # type: ignore[attr-defined]

        new_acc = behaviour._policy.accuracy_store[MECH_TOOL].accuracy  # type: ignore[union-attr]
        # 5 correct out of 10 before; adding 1 correct → 6/11 ≈ 0.545 > 0.5
        assert new_acc > 0.5, (
            "Accuracy did not increase after a winning redemption. "
            "update_accuracy_store was likely not called with winning=True."
        )

    def test_accuracy_updated_as_losing_when_cur_price_is_zero(self) -> None:
        """curPrice=0.0 means the token lost; accuracy must decrease."""
        behaviour = _make_behaviour()
        behaviour._policy.accuracy_store[MECH_TOOL] = AccuracyInfo(  # type: ignore[union-attr]
            accuracy=0.5, pending=1, requests=10
        )

        behaviour._update_policy_for_redeemable_positions(REDEEMABLE_POSITIONS_LOSING)  # type: ignore[attr-defined]

        new_acc = behaviour._policy.accuracy_store[MECH_TOOL].accuracy  # type: ignore[union-attr]
        # 5 correct out of 10 before; adding 1 incorrect → 5/11 ≈ 0.454 < 0.5
        assert new_acc < 0.5, (
            "Accuracy did not decrease after a losing redemption. "
            "update_accuracy_store was likely not called with winning=False."
        )

    def test_missing_cur_price_is_skipped_gracefully(self) -> None:
        """A position without a curPrice field must be skipped without raising."""
        behaviour = _make_behaviour()
        initial_requests = behaviour._policy.accuracy_store[MECH_TOOL].requests  # type: ignore[union-attr]
        position_no_price = [
            {
                "conditionId": CONDITION_ID_KNOWN,
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 10.0,
            }
        ]

        behaviour._update_policy_for_redeemable_positions(position_no_price)  # type: ignore[attr-defined]

        assert behaviour._policy.accuracy_store[MECH_TOOL].requests == initial_requests, (  # type: ignore[union-attr]
            "accuracy_store was modified despite curPrice being absent."
        )

    def test_pending_decremented(self) -> None:
        """update_accuracy_store decrements pending; verify it is called."""
        behaviour = _make_behaviour()
        initial_pending = behaviour._policy.accuracy_store[MECH_TOOL].pending  # type: ignore[union-attr]

        behaviour._update_policy_for_redeemable_positions(REDEEMABLE_POSITIONS)  # type: ignore[attr-defined]

        final_pending = behaviour._policy.accuracy_store[MECH_TOOL].pending  # type: ignore[union-attr]
        assert (
            final_pending == initial_pending - 1
        ), "pending was not decremented; update_accuracy_store was not called."

    def test_unknown_condition_id_is_skipped_gracefully(self) -> None:
        """If a redeemable position's conditionId is NOT in utilized_tools (bet placed before the fix, or tool info lost) the method must not raise and must not modify the policy."""
        behaviour = _make_behaviour()
        behaviour._utilized_tools = {}  # no known tools  # type: ignore[attr-defined]
        initial_requests = behaviour._policy.accuracy_store[MECH_TOOL].requests  # type: ignore[union-attr]

        # Must not raise even though the conditionId is missing from utilized_tools.
        behaviour._update_policy_for_redeemable_positions(REDEEMABLE_POSITIONS)  # type: ignore[attr-defined]

        assert behaviour._policy.accuracy_store[MECH_TOOL].requests == initial_requests, (  # type: ignore[union-attr]
            "accuracy_store was modified for a position with no corresponding tool entry."
        )

    def test_empty_positions_list_is_a_noop(self) -> None:
        """Calling the method with an empty list must not change the policy."""
        behaviour = _make_behaviour()
        initial_requests = behaviour._policy.accuracy_store[MECH_TOOL].requests  # type: ignore[union-attr]

        behaviour._update_policy_for_redeemable_positions([])  # type: ignore[attr-defined]

        assert behaviour._policy.accuracy_store[MECH_TOOL].requests == initial_requests  # type: ignore[union-attr]

    def test_multiple_positions_each_update_their_tool(self) -> None:
        """Multiple redeemable positions update the accuracy store once per position."""
        tool_a = "prediction-offline"
        tool_b = "prediction-online"
        policy = EGreedyPolicy(
            eps=0.25,
            consecutive_failures_threshold=2,
            quarantine_duration=10800,
            accuracy_store={
                tool_a: AccuracyInfo(accuracy=0.6, pending=2, requests=10),
                tool_b: AccuracyInfo(accuracy=0.7, pending=2, requests=10),
            },
        )

        behaviour = object.__new__(PolymarketRedeemBehaviour)  # type: ignore[arg-type]
        behaviour.__dict__["_policy"] = policy
        behaviour.__dict__["_utilized_tools"] = {
            "0xaaa": tool_a,
            "0xbbb": tool_b,
        }
        context = MagicMock()
        context.logger = MagicMock()
        behaviour.__dict__["_context"] = context

        positions = [
            {
                "conditionId": "0xaaa",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 10.0,
                "negativeRisk": False,
                "curPrice": 1.0,
            },
            {
                "conditionId": "0xbbb",
                "outcomeIndex": 0,
                "outcome": "Yes",
                "size": 20.0,
                "negativeRisk": False,
                "curPrice": 1.0,
            },
        ]

        behaviour._update_policy_for_redeemable_positions(positions)  # type: ignore[attr-defined]

        assert policy.accuracy_store[tool_a].requests == 11, "tool_a not updated"
        assert policy.accuracy_store[tool_b].requests == 11, "tool_b not updated"
