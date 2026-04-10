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

"""Tests for PostBetUpdateBehaviour.

This behaviour is the post-tx-settlement hook for Omen `BetPlacementRound`
and `SellOutcomeTokensRound`. It runs the local-state bookkeeping that the
legacy design used to do as a side effect of `RedeemBehaviour.async_act`,
which is no longer reachable post-bet under the always-redeem-first FSM
restructure. The behaviour reads `tx_submitter` from synchronized data and
dispatches to either `update_bet_transaction_information` or
`update_sell_transaction_information` accordingly, then submits a payload
to advance the round.
"""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.post_bet_update import (
    PostBetUpdateBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PostBetUpdatePayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)


def _make_behaviour() -> PostBetUpdateBehaviour:
    """Return a PostBetUpdateBehaviour with mocked dependencies."""
    behaviour = object.__new__(PostBetUpdateBehaviour)
    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context
    return behaviour


def _exhaust(gen) -> None:  # type: ignore[no-untyped-def]
    """Exhaust a generator, ignoring StopIteration."""
    try:
        while True:
            next(gen)
    except StopIteration:
        pass


class TestPostBetUpdateBehaviour:
    """Tests for PostBetUpdateBehaviour."""

    def test_async_act_with_bet_placement_calls_update_bet(self) -> None:
        """When tx_submitter is BetPlacementRound, async_act should call update_bet_transaction_information and emit a PostBetUpdatePayload."""
        behaviour = _make_behaviour()

        payloads_sent: list = []
        update_bet_calls = MagicMock()
        update_sell_calls = MagicMock()

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = update_bet_calls  # type: ignore[method-assign]
        behaviour.update_sell_transaction_information = update_sell_calls  # type: ignore[method-assign]

        mock_synced = MagicMock()
        mock_synced.tx_submitter = BetPlacementRound.auto_round_id()
        mock_synced.did_transact = True

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _exhaust(behaviour.async_act())

        update_bet_calls.assert_called_once_with()
        update_sell_calls.assert_not_called()
        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, PostBetUpdatePayload)
        assert payload.sender == "test_agent"
        assert payload.vote is True

    def test_async_act_with_sell_outcome_calls_update_sell(self) -> None:
        """When tx_submitter is SellOutcomeTokensRound, async_act should call update_sell_transaction_information and emit a PostBetUpdatePayload."""
        behaviour = _make_behaviour()

        payloads_sent: list = []
        update_bet_calls = MagicMock()
        update_sell_calls = MagicMock()

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = update_bet_calls  # type: ignore[method-assign]
        behaviour.update_sell_transaction_information = update_sell_calls  # type: ignore[method-assign]

        mock_synced = MagicMock()
        mock_synced.tx_submitter = SellOutcomeTokensRound.auto_round_id()
        mock_synced.did_transact = True

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _exhaust(behaviour.async_act())

        update_sell_calls.assert_called_once_with()
        update_bet_calls.assert_not_called()
        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PostBetUpdatePayload)

    def test_async_act_with_unknown_submitter_skips_bookkeeping(self) -> None:
        """When tx_submitter is some other round (defensive), async_act should not call either bookkeeping helper but still emit a payload to advance the round."""
        behaviour = _make_behaviour()

        payloads_sent: list = []
        update_bet_calls = MagicMock()
        update_sell_calls = MagicMock()

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = update_bet_calls  # type: ignore[method-assign]
        behaviour.update_sell_transaction_information = update_sell_calls  # type: ignore[method-assign]

        mock_synced = MagicMock()
        mock_synced.tx_submitter = "some_other_round"
        mock_synced.did_transact = True

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _exhaust(behaviour.async_act())

        update_bet_calls.assert_not_called()
        update_sell_calls.assert_not_called()
        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PostBetUpdatePayload)

    def test_async_act_skips_bookkeeping_when_did_not_transact(self) -> None:
        """When did_transact is False (e.g., a tendermint replay or restart that lands in PostBetUpdateRound without a fresh successful tx in the current period), async_act must not re-mutate the bet's queue_status / processed_timestamp / invested_amount based on stale tx_submitter state. It should still emit a payload so the FSM round can advance."""
        behaviour = _make_behaviour()

        payloads_sent: list = []
        update_bet_calls = MagicMock()
        update_sell_calls = MagicMock()

        def mock_finish(payload):  # type: ignore[no-untyped-def]
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish  # type: ignore[method-assign]
        behaviour.update_bet_transaction_information = update_bet_calls  # type: ignore[method-assign]
        behaviour.update_sell_transaction_information = update_sell_calls  # type: ignore[method-assign]

        mock_synced = MagicMock()
        # tx_submitter looks legitimate but did_transact is False — this is
        # the stale-state scenario we are guarding against.
        mock_synced.tx_submitter = BetPlacementRound.auto_round_id()
        mock_synced.did_transact = False

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = mock_synced
            _exhaust(behaviour.async_act())

        update_bet_calls.assert_not_called()
        update_sell_calls.assert_not_called()
        assert len(payloads_sent) == 1
        assert isinstance(payloads_sent[0], PostBetUpdatePayload)
