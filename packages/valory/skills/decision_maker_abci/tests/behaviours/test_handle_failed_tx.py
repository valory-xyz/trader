# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for HandleFailedTxBehaviour."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.handle_failed_tx import (
    HandleFailedTxBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import HandleFailedTxPayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.mech_interact_abci.states.request import MechRequestRound

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a HandleFailedTxBehaviour with mocked dependencies."""
    behaviour = object.__new__(HandleFailedTxBehaviour)  # type: ignore[no-untyped-def]
    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context
    return behaviour


def _run_async_act(behaviour, tx_submitter):  # type: ignore[no-untyped-def]
    """Drive async_act to completion and return the payload."""
    payloads_sent = []  # type: ignore[no-untyped-def]

    def mock_finish(payload) -> None:  # type: ignore[no-untyped-def, misc]
        payloads_sent.append(payload)
        yield  # type: ignore[no-untyped-def]

    behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]

    with patch.object(
        type(behaviour), "synchronized_data", new_callable=PropertyMock
    ) as mock_sd:
        sd = MagicMock()
        sd.tx_submitter = tx_submitter
        mock_sd.return_value = sd

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = MagicMock()

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

    assert len(payloads_sent) == 1
    return payloads_sent[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHandleFailedTxBehaviour:
    """Tests for HandleFailedTxBehaviour.async_act."""

    def test_matching_round(self) -> None:
        """matching_round should be HandleFailedTxRound."""
        assert HandleFailedTxBehaviour.matching_round == HandleFailedTxRound

    def test_mech_timeout_sets_flags(self) -> None:
        """When tx_submitter is MechRequestRound, mech_timed_out and after_bet_attempt should be True."""
        behaviour = _make_behaviour()
        mech_submitter = MechRequestRound.auto_round_id()
        payload = _run_async_act(behaviour, mech_submitter)

        assert isinstance(payload, HandleFailedTxPayload)
        assert payload.vote is True  # after_bet_attempt

    def test_bet_placement_sets_after_bet_attempt(self) -> None:
        """When tx_submitter is BetPlacementRound, after_bet_attempt should be True."""
        behaviour = _make_behaviour()
        bet_submitter = BetPlacementRound.auto_round_id()
        payload = _run_async_act(behaviour, bet_submitter)

        assert isinstance(payload, HandleFailedTxPayload)
        assert payload.vote is True

    def test_sell_outcome_sets_after_bet_attempt(self) -> None:
        """When tx_submitter is SellOutcomeTokensRound, after_bet_attempt should be True."""
        behaviour = _make_behaviour()
        sell_submitter = SellOutcomeTokensRound.auto_round_id()
        payload = _run_async_act(behaviour, sell_submitter)

        assert isinstance(payload, HandleFailedTxPayload)
        assert payload.vote is True

    def test_other_submitter_sets_after_bet_attempt_false(self) -> None:
        """When tx_submitter is not a known round, after_bet_attempt should be False."""
        behaviour = _make_behaviour()
        payload = _run_async_act(behaviour, "some_other_round")

        assert isinstance(payload, HandleFailedTxPayload)
        assert payload.vote is False

    def test_payload_has_handle_failed_tx_submitter(self) -> None:
        """The payload's tx_submitter should be HandleFailedTxRound.auto_round_id()."""
        behaviour = _make_behaviour()
        payload = _run_async_act(behaviour, "some_round")

        assert payload.tx_submitter == HandleFailedTxRound.auto_round_id()
