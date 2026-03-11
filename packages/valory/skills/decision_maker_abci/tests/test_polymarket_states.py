# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""Tests for Polymarket-specific round states of the decision-making ABCI app."""

import json
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
    PolymarketPostSetApprovalPayload,
    PolymarketRedeemPayload,
    PolymarketSetApprovalPayload,
    PolymarketSwapPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_post_set_approval import (
    PolymarketPostSetApprovalRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    IGNORED,
    MECH_TOOLS_FIELD,
    PolymarketRedeemRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_set_approval import (
    PolymarketSetApprovalRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_swap import (
    PolymarketSwapUsdcRound,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_round(round_cls):  # type: ignore[no-untyped-def]
    """Instantiate a round with mocked synchronized_data and context."""
    synced_data = MagicMock(spec=SynchronizedData)
    context = MagicMock()
    return round_cls(synchronized_data=synced_data, context=context)


def _mock_super_end_block_none(round_instance):  # type: ignore[no-untyped-def]
    """Patch the CollectSameUntilThresholdRound.end_block to return None."""
    with patch.object(type(round_instance).__mro__[1], "end_block", return_value=None):  # type: ignore[arg-type]
        pass


# ---------------------------------------------------------------------------
# PolymarketBetPlacementRound
# ---------------------------------------------------------------------------


class TestPolymarketBetPlacementRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for PolymarketBetPlacementRound.end_block."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def test_payload_class(self) -> None:
        """Payload class is PolymarketBetPlacementPayload."""
        assert (
            PolymarketBetPlacementRound.payload_class is PolymarketBetPlacementPayload
        )

    def test_none_event_is_insufficient_balance(self) -> None:
        """none_event defaults to INSUFFICIENT_BALANCE."""
        assert PolymarketBetPlacementRound.none_event == Event.INSUFFICIENT_BALANCE

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = PolymarketBetPlacementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_end_block_updates_cached_orders_when_present(self) -> None:
        """Updates synced_data with cached_signed_orders when not None.

        The key business invariant: the round must persist the cached signed
        orders to synchronized data so other agents can retry the same order.
        """
        round_ = PolymarketBetPlacementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)
        updated_synced_data = MagicMock(spec=SynchronizedData)
        synced_data_mock.update.return_value = updated_synced_data

        cached_orders = json.dumps({"tok1": '{"salt": "1"}'})
        # most_voted_payload_values[-3] = event, [-2] = cached_orders, [-1] = utilized_tools
        mvpv = (
            "tx_submitter",
            "tx_hash",
            "False",
            Event.BET_PLACEMENT_DONE.value,
            cached_orders,
            None,
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        updated, event = result
        assert event == Event.BET_PLACEMENT_DONE
        assert updated is updated_synced_data
        # The cached orders MUST be stored under the correct key
        synced_data_mock.update.assert_called_once()
        call_kwargs = synced_data_mock.update.call_args[1]
        assert call_kwargs["cached_signed_orders"] == cached_orders

    def test_end_block_no_cached_orders_returns_event(self) -> None:
        """Does not call update when cached_orders is None."""
        round_ = PolymarketBetPlacementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        mvpv = (
            "tx_submitter",
            "tx_hash",
            "False",
            Event.BET_PLACEMENT_FAILED.value,
            None,
            None,
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        synced_data_mock.update.assert_not_called()
        _, event = result
        assert event == Event.BET_PLACEMENT_FAILED

    def test_end_block_bet_placement_impossible_event(self) -> None:
        """Returns BET_PLACEMENT_IMPOSSIBLE event correctly."""
        round_ = PolymarketBetPlacementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        mvpv = (
            "tx_submitter",
            "tx_hash",
            "False",
            Event.BET_PLACEMENT_IMPOSSIBLE.value,
            None,
            None,
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.BET_PLACEMENT_IMPOSSIBLE

    def test_end_block_insufficient_balance_event(self) -> None:
        """Returns INSUFFICIENT_BALANCE event correctly."""
        round_ = PolymarketBetPlacementRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        mvpv = (
            "tx_submitter",
            "tx_hash",
            "False",
            Event.INSUFFICIENT_BALANCE.value,
            None,
            None,
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.INSUFFICIENT_BALANCE


# ---------------------------------------------------------------------------
# PolymarketSetApprovalRound
# ---------------------------------------------------------------------------


class TestPolymarketSetApprovalRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for PolymarketSetApprovalRound.end_block."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def test_payload_class(self) -> None:
        """Payload class is PolymarketSetApprovalPayload."""
        assert PolymarketSetApprovalRound.payload_class is PolymarketSetApprovalPayload

    def test_none_event_is_none(self) -> None:
        """none_event is Event.NONE."""
        assert PolymarketSetApprovalRound.none_event == Event.NONE

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = PolymarketSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_builder_program_enabled_returns_done(self) -> None:
        """Returns Event.DONE when polymarket_builder_program_enabled=True."""
        round_ = PolymarketSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        round_.context.params.polymarket_builder_program_enabled = True
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_builder_program_disabled_returns_prepare_tx(self) -> None:
        """Returns Event.PREPARE_TX when polymarket_builder_program_enabled=False."""
        round_ = PolymarketSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        round_.context.params.polymarket_builder_program_enabled = False
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.PREPARE_TX

    def test_builder_enabled_passes_through_synced_data(self) -> None:
        """The synced_data from parent is returned unchanged when builder is enabled."""
        round_ = PolymarketSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        round_.context.params.polymarket_builder_program_enabled = True
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)):
            result = round_.end_block()

        # Event overridden to DONE; synced_data must be the same object from parent
        assert result[0] is synced_data_mock  # type: ignore[index]
        assert result[1] == Event.DONE  # type: ignore[index]

    def test_builder_disabled_passes_through_synced_data(self) -> None:
        """The synced_data from parent is returned unchanged when builder is disabled."""
        round_ = PolymarketSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        round_.context.params.polymarket_builder_program_enabled = False
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)):
            result = round_.end_block()

        # Event overridden to PREPARE_TX; synced_data must be the same object from parent
        assert result[0] is synced_data_mock  # type: ignore[index]
        assert result[1] == Event.PREPARE_TX  # type: ignore[index]


# ---------------------------------------------------------------------------
# PolymarketPostSetApprovalRound
# ---------------------------------------------------------------------------


class TestPolymarketPostSetApprovalRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for PolymarketPostSetApprovalRound.end_block."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def test_payload_class(self) -> None:
        """Payload class is PolymarketPostSetApprovalPayload."""
        assert (
            PolymarketPostSetApprovalRound.payload_class
            is PolymarketPostSetApprovalPayload
        )

    def test_done_event(self) -> None:
        """done_event is Event.DONE."""
        assert PolymarketPostSetApprovalRound.done_event == Event.DONE

    def test_none_event_is_none(self) -> None:
        """none_event is Event.NONE."""
        assert PolymarketPostSetApprovalRound.none_event == Event.NONE

    def test_no_majority_event(self) -> None:
        """no_majority_event is Event.NO_MAJORITY."""
        assert PolymarketPostSetApprovalRound.no_majority_event == Event.NO_MAJORITY

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_end_block_approval_failed_when_vote_false(self) -> None:
        """Returns APPROVAL_FAILED when consensus vote is False."""
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        # most_voted_payload is a read-only property, patch it at the class level
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload",
            new_callable=PropertyMock,
            return_value=False,
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.APPROVAL_FAILED
        round_.context.logger.warning.assert_called_once()

    def test_end_block_done_when_vote_true(self) -> None:
        """Passes through (synced_data, DONE) when consensus vote is True."""
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        # most_voted_payload is a read-only property, patch it at the class level
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload",
            new_callable=PropertyMock,
            return_value=True,
        ):
            result = round_.end_block()

        # Should pass through the original result from super
        assert result == (synced_data_mock, Event.DONE)

    def test_end_block_passes_through_no_majority(self) -> None:
        """Passes through NO_MAJORITY event unchanged (most_voted_payload not checked)."""
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        # NO_MAJORITY bypasses most_voted_payload check so no need to patch it
        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.NO_MAJORITY)):
            result = round_.end_block()

        assert result == (synced_data_mock, Event.NO_MAJORITY)

    def test_end_block_passes_through_none_event(self) -> None:
        """Passes through NONE event unchanged (most_voted_payload not checked)."""
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        # NONE event bypasses most_voted_payload check
        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.NONE)):
            result = round_.end_block()

        assert result == (synced_data_mock, Event.NONE)

    def test_integer_zero_vote_is_not_approval_failed(self) -> None:
        """Integer 0 is not identical to False — must NOT trigger APPROVAL_FAILED.

        The check is `most_voted_payload is False` (identity), not `== False`
        (equality). The integer 0 compares equal to False but is not identical.
        Routing 0 to APPROVAL_FAILED would incorrectly retry the set-approval flow.
        """
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload",
            new_callable=PropertyMock,
            return_value=0,  # 0 == False but 0 is not False
        ):
            result = round_.end_block()

        assert result == (synced_data_mock, Event.DONE)

    def test_none_vote_is_not_approval_failed(self) -> None:
        """None is not identical to False — must NOT trigger APPROVAL_FAILED.

        None is falsy but `None is False` is False. Routing None to
        APPROVAL_FAILED would incorrectly retry the set-approval flow.
        """
        round_ = PolymarketPostSetApprovalRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload",
            new_callable=PropertyMock,
            return_value=None,
        ):
            result = round_.end_block()

        assert result == (synced_data_mock, Event.DONE)


# ---------------------------------------------------------------------------
# PolymarketSwapUsdcRound
# ---------------------------------------------------------------------------


class TestPolymarketSwapUsdcRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for PolymarketSwapUsdcRound.end_block."""

    _synchronized_data_class = SynchronizedData
    _event_class = Event

    def test_payload_class(self) -> None:
        """Payload class is PolymarketSwapPayload."""
        assert PolymarketSwapUsdcRound.payload_class is PolymarketSwapPayload

    def test_none_event_is_none(self) -> None:
        """none_event is Event.NONE."""
        assert PolymarketSwapUsdcRound.none_event == Event.NONE

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = PolymarketSwapUsdcRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_end_block_returns_prepare_tx_when_should_swap_true(self) -> None:
        """Returns PREPARE_TX when most_voted_payload_values[-1] is True."""
        round_ = PolymarketSwapUsdcRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)
        mvpv = ("tx_submitter", "tx_hash", "False", True)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.PREPARE_TX

    def test_end_block_returns_done_when_should_swap_false(self) -> None:
        """Returns DONE when most_voted_payload_values[-1] is False."""
        round_ = PolymarketSwapUsdcRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)
        mvpv = ("tx_submitter", "tx_hash", "False", False)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_none_should_swap_returns_done(self) -> None:
        """A None should_swap (falsy) routes to Event.DONE, not Event.PREPARE_TX.

        The branch is `Event.PREPARE_TX if should_swap else Event.DONE`. None is
        falsy so the result must be DONE, not PREPARE_TX.
        """
        round_ = PolymarketSwapUsdcRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)
        mvpv = ("tx_submitter", "tx_hash", "False", None)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_swap_synced_data_passed_through(self) -> None:
        """The synced_data object from the parent is returned unchanged.

        The round only overwrites the event; the synchronized data must be
        the exact same object so no state is lost between rounds.
        """
        round_ = PolymarketSwapUsdcRound(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        synced_data_mock = MagicMock(spec=SynchronizedData)
        mvpv = ("tx_submitter", "tx_hash", "False", True)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            parent_cls, return_value=(synced_data_mock, Event.DONE)
        ), patch.object(
            type(round_),
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=mvpv,
        ):
            result = round_.end_block()

        assert result is not None
        assert result[0] is synced_data_mock


# ---------------------------------------------------------------------------
# PolymarketRedeemRound
# ---------------------------------------------------------------------------


class TestPolymarketRedeemRound:
    """Tests for PolymarketRedeemRound."""

    def test_payload_class(self) -> None:
        """Payload class is PolymarketRedeemPayload."""
        assert PolymarketRedeemRound.payload_class is PolymarketRedeemPayload

    def test_none_event_is_no_redeeming(self) -> None:
        """none_event is Event.NO_REDEEMING."""
        assert PolymarketRedeemRound.none_event == Event.NO_REDEEMING

    def test_ignored_constant(self) -> None:
        """IGNORED constant is 'ignored'."""
        assert IGNORED == "ignored"

    def test_mech_tools_field_constant(self) -> None:
        """MECH_TOOLS_FIELD constant is 'mech_tools'."""
        assert MECH_TOOLS_FIELD == "mech_tools"

    def test_most_voted_payload_values_returns_none_tuple_when_all_none(self) -> None:
        """Returns (None,) * len(selection_key) when all non-mech_tools values are None.

        This triggers the none_event path in the base round — the length must
        exactly match selection_key so that downstream unpacking works correctly.
        """
        round_ = _make_round(PolymarketRedeemRound)
        # All fields are None except mech_tools (index 3) which must be non-None
        # Payload value order: tx_submitter, tx_hash, mocking_mode, mech_tools, policy,
        #   utilized_tools, redeemed_condition_ids, payout_so_far, event
        none_values = (None, None, None, "[]", None, None, None, None, None)

        parent_prop = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.most_voted_payload_values"
        with patch(parent_prop, new_callable=PropertyMock, return_value=none_values):
            result = round_.most_voted_payload_values

        # Must be all-None AND the correct length for downstream code
        assert all(v is None for v in result)
        assert len(result) == len(PolymarketRedeemRound.selection_key)

    def test_most_voted_payload_values_raises_if_mech_tools_none(self) -> None:
        """Raises ValueError when mech_tools is None."""
        round_ = _make_round(PolymarketRedeemRound)
        # mech_tools is position 3 in the tuple (None here)
        none_mech_tools_values = (None, None, None, None, None, None, None, None, None)

        parent_prop = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.most_voted_payload_values"
        with patch(
            parent_prop, new_callable=PropertyMock, return_value=none_mech_tools_values
        ):
            with pytest.raises(ValueError, match="mech_tools"):
                _ = round_.most_voted_payload_values

    def test_most_voted_payload_values_returns_original_when_not_all_none(self) -> None:
        """Returns original values when not all non-mech_tools fields are None."""
        round_ = _make_round(PolymarketRedeemRound)
        # Non-null values
        original_values = (
            "tx_sub",
            "tx_hash",
            True,
            "[]",
            "policy_str",
            '{"tool": "x"}',
            '["cid"]',
            100,
            Event.DONE.value,
        )

        parent_prop = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.most_voted_payload_values"
        with patch(
            parent_prop, new_callable=PropertyMock, return_value=original_values
        ):
            result = round_.most_voted_payload_values

        assert result == original_values

    def test_end_block_returns_none_when_parent_returns_none_period_0(self) -> None:
        """Initializes db when period=0 and block_confirmations=0 (None from parent).

        The round must pre-populate every key in its selection_key so the first
        period transition never raises a missing-key error.
        """
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 0
        round_.synchronized_data.period_count = 0

        round_.synchronized_data.db = MagicMock()
        round_.synchronized_data.db.get.return_value = None
        round_.synchronized_data.db.update = MagicMock()

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()

        round_.synchronized_data.db.update.assert_called_once()
        assert round_.block_confirmations == 1
        assert result is None
        # Every key in the round's selection_key must appear in the db.update call
        update_kwargs = round_.synchronized_data.db.update.call_args[1]
        for key in PolymarketRedeemRound.selection_key:
            assert key in update_kwargs, f"Missing key in db.update: {key}"

    def test_end_block_returns_none_when_period_nonzero(self) -> None:
        """Returns None without db.update when period > 0."""
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 0
        round_.synchronized_data.period_count = 1  # non-zero

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()

        assert result is None

    def test_end_block_returns_none_when_block_confirmations_nonzero(self) -> None:
        """Returns None without db.update when block_confirmations > 0."""
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 1  # non-zero
        round_.synchronized_data.period_count = 0

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()

        assert result is None

    def test_end_block_success_non_no_majority(self) -> None:
        """Updates mech_tools and returns (updated_data, event) on non-NO_MAJORITY.

        Key invariant: the mech_tools value from the winning payload must be
        written into synchronized data under the correct field name so that the
        next round can read the available tools.
        """
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 1
        round_.synchronized_data.period_count = 0

        synced_data_mock = MagicMock(spec=SynchronizedData)
        updated_data_mock = MagicMock(spec=SynchronizedData)
        synced_data_mock.update.return_value = updated_data_mock

        # mech_tools (index 3) = '["tool_a"]' — this must end up in synced data
        original_values = (
            "tx_sub",
            "tx_hash",
            False,
            '["tool_a"]',
            "policy",
            "{}",
            "[]",
            0,
            Event.DONE.value,
        )
        payload_count_mock = MagicMock()
        payload_count_mock.most_common.return_value = [(original_values, 3)]

        redeem_prop = "packages.valory.skills.decision_maker_abci.states.polymarket_redeem.PolymarketRedeemRound.most_voted_payload_values"
        parent_eb = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        pvc_prop = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.payload_values_count"
        with patch(
            redeem_prop, new_callable=PropertyMock, return_value=original_values
        ), patch(parent_eb, return_value=(synced_data_mock, Event.DONE)), patch(
            pvc_prop, new_callable=PropertyMock, return_value=payload_count_mock
        ):
            result = round_.end_block()

        assert result is not None
        result_data, result_event = result
        assert result_data is updated_data_mock
        assert result_event == Event.DONE

        # The mech_tools value from the winning payload must be stored correctly
        synced_data_mock.update.assert_called_once()
        update_kwargs = synced_data_mock.update.call_args[1]
        mech_tools_key = PolymarketRedeemRound.mech_tools_name
        assert mech_tools_key in update_kwargs, "mech_tools not written to synced data"
        assert update_kwargs[mech_tools_key] == '["tool_a"]'

    def test_end_block_no_majority_returns_as_is(self) -> None:
        """Returns original result for NO_MAJORITY event (no mech_tools update)."""
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 1
        round_.synchronized_data.period_count = 0

        synced_data_mock = MagicMock(spec=SynchronizedData)

        end_values = (
            "tx_sub",
            "tx_hash",
            False,
            '["tool"]',
            "policy",
            "{}",
            "[]",
            0,
            Event.NO_REDEEMING.value,
        )

        redeem_prop = "packages.valory.skills.decision_maker_abci.states.polymarket_redeem.PolymarketRedeemRound.most_voted_payload_values"
        parent_eb = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(
            redeem_prop, new_callable=PropertyMock, return_value=end_values
        ), patch(parent_eb, return_value=(synced_data_mock, Event.NO_MAJORITY)):
            result = round_.end_block()

        # NO_MAJORITY equals no_majority_event, so return res as-is
        assert result == (synced_data_mock, Event.NO_MAJORITY)

    def test_actual_event_comes_from_payload_not_parent(self) -> None:
        """The result event is taken from the payload's last field, not the parent's event.

        The parent round may return DONE, but the payload-encoded event (e.g.
        PREPARE_TX) must win. This guards against a regression where the parent
        event leaks through and bypasses the per-payload event logic.
        """
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 1
        round_.synchronized_data.period_count = 0

        synced_data_mock = MagicMock(spec=SynchronizedData)
        updated_data_mock = MagicMock(spec=SynchronizedData)
        synced_data_mock.update.return_value = updated_data_mock

        # Payload encodes PREPARE_TX; parent returns DONE — payload must win
        original_values = (
            "tx_sub",
            "tx_hash",
            False,
            '["tool"]',
            "policy",
            "{}",
            "[]",
            0,
            Event.PREPARE_TX.value,
        )
        payload_count_mock = MagicMock()
        payload_count_mock.most_common.return_value = [(original_values, 3)]

        redeem_prop = "packages.valory.skills.decision_maker_abci.states.polymarket_redeem.PolymarketRedeemRound.most_voted_payload_values"
        parent_eb = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        pvc_prop = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.payload_values_count"
        with patch(
            redeem_prop, new_callable=PropertyMock, return_value=original_values
        ), patch(parent_eb, return_value=(synced_data_mock, Event.DONE)), patch(
            pvc_prop, new_callable=PropertyMock, return_value=payload_count_mock
        ):
            result = round_.end_block()

        assert result is not None
        _, result_event = result
        assert (
            result_event == Event.PREPARE_TX
        )  # payload-encoded event overrides parent


# ---------------------------------------------------------------------------
# Polymarket state classes - basic attribute checks
# ---------------------------------------------------------------------------


class TestPolymarketRoundAttributes:
    """Tests for basic attribute and class structure of Polymarket rounds."""

    def test_bet_placement_round_is_tx_preparation(self) -> None:
        """Test that PolymarketBetPlacementRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )

        assert issubclass(PolymarketBetPlacementRound, TxPreparationRound)

    def test_set_approval_round_is_tx_preparation(self) -> None:
        """Test that PolymarketSetApprovalRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )

        assert issubclass(PolymarketSetApprovalRound, TxPreparationRound)

    def test_post_set_approval_round_is_collect_same(self) -> None:
        """Test that PolymarketPostSetApprovalRound extends CollectSameUntilThresholdRound."""
        from packages.valory.skills.abstract_round_abci.base import (
            CollectSameUntilThresholdRound,
        )

        assert issubclass(
            PolymarketPostSetApprovalRound, CollectSameUntilThresholdRound
        )

    def test_swap_round_is_tx_preparation(self) -> None:
        """Test that PolymarketSwapUsdcRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )

        assert issubclass(PolymarketSwapUsdcRound, TxPreparationRound)

    def test_redeem_round_is_tx_preparation(self) -> None:
        """Test that PolymarketRedeemRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )

        assert issubclass(PolymarketRedeemRound, TxPreparationRound)

    def test_redeem_round_selection_key_includes_extra_fields(self) -> None:
        """PolymarketRedeemRound.selection_key includes extra Polymarket-specific fields."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )

        # The redeem round has extra fields beyond the base TxPreparationRound
        assert len(PolymarketRedeemRound.selection_key) > len(
            TxPreparationRound.selection_key
        )
