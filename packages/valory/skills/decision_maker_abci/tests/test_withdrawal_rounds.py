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

"""Tests for the withdrawal rounds and stub behaviours in decision_maker_abci."""

from unittest.mock import MagicMock

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
    DegenerateRound,
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
        """ROUND_TIMEOUT from PolymarketWithdrawRound enters WithdrawalIdleRound (D26)."""
        tx = DecisionMakerAbciApp.transition_function
        assert tx[PolymarketWithdrawRound][Event.ROUND_TIMEOUT] is WithdrawalIdleRound

    def test_omen_withdraw_routes_to_idle_on_done(self) -> None:
        """WITHDRAWAL_DONE from OmenWithdrawRound enters WithdrawalIdleRound."""
        tx = DecisionMakerAbciApp.transition_function
        assert tx[OmenWithdrawRound][Event.WITHDRAWAL_DONE] is WithdrawalIdleRound

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


class TestPolymarketWithdrawBehaviourStub:
    """Tests for the phase-1 Polymarket stub behaviour."""

    def test_async_act_logs_and_finishes_with_payload(self) -> None:
        """Phase-1 stub must log an info line and post a WithdrawalPayload."""
        behaviour = object.__new__(_TestablePolymarketWithdraw)
        behaviour.context = MagicMock()  # type: ignore[assignment]
        behaviour.context.agent_address = "agent_x"

        captured_payload = {}

        def fake_finish(payload: WithdrawalPayload):  # type: ignore[no-untyped-def]
            captured_payload["payload"] = payload
            yield

        behaviour.finish_behaviour = fake_finish  # type: ignore[method-assign]
        list(behaviour.async_act())  # exhaust the generator

        behaviour.context.logger.info.assert_called_once()
        assert "phase-1" in str(behaviour.context.logger.info.call_args).lower()
        assert isinstance(captured_payload["payload"], WithdrawalPayload)
        assert captured_payload["payload"].sender == "agent_x"


class TestOmenWithdrawBehaviourStub:
    """Tests for the defensive Omen stub behaviour."""

    def test_async_act_logs_warning_and_finishes(self) -> None:
        """The Omen stub must emit a WARNING and post a WithdrawalPayload."""
        behaviour = object.__new__(_TestableOmenWithdraw)
        behaviour.context = MagicMock()  # type: ignore[assignment]
        behaviour.context.agent_address = "agent_y"

        captured_payload = {}

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
