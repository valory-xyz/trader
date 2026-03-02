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

from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
    PolymarketPostSetApprovalPayload,
    PolymarketRedeemPayload,
    PolymarketSetApprovalPayload,
    PolymarketSwapPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import Event, SynchronizedData
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


def _make_round(round_cls):
    """Instantiate a round with mocked synchronized_data and context."""
    synced_data = MagicMock(spec=SynchronizedData)
    context = MagicMock()
    return round_cls(synchronized_data=synced_data, context=context)


def _mock_super_end_block_none(round_instance):
    """Patch the CollectSameUntilThresholdRound.end_block to return None."""
    with patch.object(type(round_instance).__mro__[1], "end_block", return_value=None):
        pass


# ---------------------------------------------------------------------------
# PolymarketBetPlacementRound
# ---------------------------------------------------------------------------


class TestPolymarketBetPlacementRound:
    """Tests for PolymarketBetPlacementRound.end_block."""

    def test_payload_class(self) -> None:
        """Payload class is PolymarketBetPlacementPayload."""
        assert PolymarketBetPlacementRound.payload_class is PolymarketBetPlacementPayload

    def test_none_event_is_insufficient_balance(self) -> None:
        """none_event defaults to INSUFFICIENT_BALANCE."""
        assert PolymarketBetPlacementRound.none_event == Event.INSUFFICIENT_BALANCE

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = _make_round(PolymarketBetPlacementRound)
        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_end_block_updates_cached_orders_when_present(self) -> None:
        """Updates synced_data with cached_signed_orders when not None."""
        round_ = _make_round(PolymarketBetPlacementRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)
        updated_synced_data = MagicMock(spec=SynchronizedData)
        synced_data_mock.update.return_value = updated_synced_data

        cached_orders = json.dumps({"tok1": '{"salt": "1"}'})
        # most_voted_payload_values[-2] = event, [-1] = cached_orders
        mvpv = (
            "tx_submitter", "tx_hash", "False",
            Event.BET_PLACEMENT_DONE.value, cached_orders
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(type(round_), "most_voted_payload_values",
                          new_callable=PropertyMock, return_value=mvpv):
            result = round_.end_block()

        assert result is not None
        synced_data_mock.update.assert_called_once()
        updated, event = result
        assert event == Event.BET_PLACEMENT_DONE
        assert updated is updated_synced_data

    def test_end_block_no_cached_orders_returns_event(self) -> None:
        """Does not call update when cached_orders is None."""
        round_ = _make_round(PolymarketBetPlacementRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        mvpv = (
            "tx_submitter", "tx_hash", "False",
            Event.BET_PLACEMENT_FAILED.value, None
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(type(round_), "most_voted_payload_values",
                          new_callable=PropertyMock, return_value=mvpv):
            result = round_.end_block()

        assert result is not None
        synced_data_mock.update.assert_not_called()
        _, event = result
        assert event == Event.BET_PLACEMENT_FAILED

    def test_end_block_bet_placement_impossible_event(self) -> None:
        """Returns BET_PLACEMENT_IMPOSSIBLE event correctly."""
        round_ = _make_round(PolymarketBetPlacementRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        mvpv = (
            "tx_submitter", "tx_hash", "False",
            Event.BET_PLACEMENT_IMPOSSIBLE.value, None
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(type(round_), "most_voted_payload_values",
                          new_callable=PropertyMock, return_value=mvpv):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.BET_PLACEMENT_IMPOSSIBLE

    def test_end_block_insufficient_balance_event(self) -> None:
        """Returns INSUFFICIENT_BALANCE event correctly."""
        round_ = _make_round(PolymarketBetPlacementRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        mvpv = (
            "tx_submitter", "tx_hash", "False",
            Event.INSUFFICIENT_BALANCE.value, None
        )

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(type(round_), "most_voted_payload_values",
                          new_callable=PropertyMock, return_value=mvpv):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.INSUFFICIENT_BALANCE


# ---------------------------------------------------------------------------
# PolymarketSetApprovalRound
# ---------------------------------------------------------------------------


class TestPolymarketSetApprovalRound:
    """Tests for PolymarketSetApprovalRound.end_block."""

    def test_payload_class(self) -> None:
        """Payload class is PolymarketSetApprovalPayload."""
        assert PolymarketSetApprovalRound.payload_class is PolymarketSetApprovalPayload

    def test_none_event_is_none(self) -> None:
        """none_event is Event.NONE."""
        assert PolymarketSetApprovalRound.none_event == Event.NONE

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = _make_round(PolymarketSetApprovalRound)
        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_builder_program_enabled_returns_done(self) -> None:
        """Returns Event.DONE when polymarket_builder_program_enabled=True."""
        round_ = _make_round(PolymarketSetApprovalRound)
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
        round_ = _make_round(PolymarketSetApprovalRound)
        round_.context.params.polymarket_builder_program_enabled = False
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.PREPARE_TX

    def test_builder_enabled_logs_info(self) -> None:
        """Logs info when builder program is enabled."""
        round_ = _make_round(PolymarketSetApprovalRound)
        round_.context.params.polymarket_builder_program_enabled = True

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(MagicMock(), Event.DONE)):
            round_.end_block()

        round_.context.logger.info.assert_called()

    def test_builder_disabled_logs_info(self) -> None:
        """Logs info when builder program is disabled."""
        round_ = _make_round(PolymarketSetApprovalRound)
        round_.context.params.polymarket_builder_program_enabled = False

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(MagicMock(), Event.DONE)):
            round_.end_block()

        round_.context.logger.info.assert_called()


# ---------------------------------------------------------------------------
# PolymarketPostSetApprovalRound
# ---------------------------------------------------------------------------


class TestPolymarketPostSetApprovalRound:
    """Tests for PolymarketPostSetApprovalRound.end_block."""

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
        round_ = _make_round(PolymarketPostSetApprovalRound)
        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_end_block_approval_failed_when_vote_false(self) -> None:
        """Returns APPROVAL_FAILED when consensus vote is False."""
        from unittest.mock import PropertyMock

        round_ = _make_round(PolymarketPostSetApprovalRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        # most_voted_payload is a read-only property, patch it at the class level
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(
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
        from unittest.mock import PropertyMock

        round_ = _make_round(PolymarketPostSetApprovalRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        # most_voted_payload is a read-only property, patch it at the class level
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(
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
        round_ = _make_round(PolymarketPostSetApprovalRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        # NO_MAJORITY bypasses most_voted_payload check so no need to patch it
        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.NO_MAJORITY)):
            result = round_.end_block()

        assert result == (synced_data_mock, Event.NO_MAJORITY)

    def test_end_block_passes_through_none_event(self) -> None:
        """Passes through NONE event unchanged (most_voted_payload not checked)."""
        round_ = _make_round(PolymarketPostSetApprovalRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)

        # NONE event bypasses most_voted_payload check
        parent_cls = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.NONE)):
            result = round_.end_block()

        assert result == (synced_data_mock, Event.NONE)


# ---------------------------------------------------------------------------
# PolymarketSwapUsdcRound
# ---------------------------------------------------------------------------


class TestPolymarketSwapUsdcRound:
    """Tests for PolymarketSwapUsdcRound.end_block."""

    def test_payload_class(self) -> None:
        """Payload class is PolymarketSwapPayload."""
        assert PolymarketSwapUsdcRound.payload_class is PolymarketSwapPayload

    def test_none_event_is_none(self) -> None:
        """none_event is Event.NONE."""
        assert PolymarketSwapUsdcRound.none_event == Event.NONE

    def test_end_block_returns_none_when_parent_returns_none(self) -> None:
        """Returns None when super().end_block() returns None."""
        round_ = _make_round(PolymarketSwapUsdcRound)
        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()
        assert result is None

    def test_end_block_returns_prepare_tx_when_should_swap_true(self) -> None:
        """Returns PREPARE_TX when most_voted_payload_values[-1] is True."""
        round_ = _make_round(PolymarketSwapUsdcRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)
        mvpv = ("tx_submitter", "tx_hash", "False", True)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(type(round_), "most_voted_payload_values",
                          new_callable=PropertyMock, return_value=mvpv):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.PREPARE_TX

    def test_end_block_returns_done_when_should_swap_false(self) -> None:
        """Returns DONE when most_voted_payload_values[-1] is False."""
        round_ = _make_round(PolymarketSwapUsdcRound)
        synced_data_mock = MagicMock(spec=SynchronizedData)
        mvpv = ("tx_submitter", "tx_hash", "False", False)

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=(synced_data_mock, Event.DONE)), \
             patch.object(type(round_), "most_voted_payload_values",
                          new_callable=PropertyMock, return_value=mvpv):
            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.DONE


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
        """Returns tuple of None when all non-mech_tools values are None."""
        round_ = _make_round(PolymarketRedeemRound)
        # Build a payload where all fields except mech_tools are None
        # The payload values tuple order: tx_submitter, tx_hash, mocking_mode, mech_tools, policy,
        #   utilized_tools, redeemed_condition_ids, payout_so_far, event
        none_values = (None, None, None, "[]", None, None, None, None, None)

        parent_prop = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.most_voted_payload_values"
        with patch(parent_prop, new_callable=PropertyMock, return_value=none_values):
            result = round_.most_voted_payload_values
        # When all non-mech fields are None, should return (None,) * len(selection_key)
        assert all(v is None for v in result)

    def test_most_voted_payload_values_raises_if_mech_tools_none(self) -> None:
        """Raises ValueError when mech_tools is None."""
        round_ = _make_round(PolymarketRedeemRound)
        # mech_tools is position 3 in the tuple (None here)
        none_mech_tools_values = (None, None, None, None, None, None, None, None, None)

        parent_prop = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.most_voted_payload_values"
        with patch(parent_prop, new_callable=PropertyMock, return_value=none_mech_tools_values):
            with pytest.raises(ValueError, match="mech_tools"):
                _ = round_.most_voted_payload_values

    def test_most_voted_payload_values_returns_original_when_not_all_none(self) -> None:
        """Returns original values when not all non-mech_tools fields are None."""
        round_ = _make_round(PolymarketRedeemRound)
        # Non-null values
        original_values = (
            "tx_sub", "tx_hash", True, "[]", "policy_str",
            '{"tool": "x"}', '["cid"]', 100, Event.DONE.value
        )

        parent_prop = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.most_voted_payload_values"
        with patch(parent_prop, new_callable=PropertyMock, return_value=original_values):
            result = round_.most_voted_payload_values

        assert result == original_values

    def test_end_block_returns_none_when_parent_returns_none_period_0(self) -> None:
        """Initializes db when period=0 and block_confirmations=0 (None from parent)."""
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 0
        round_.synchronized_data.period_count = 0

        # Set up db.get to return None
        round_.synchronized_data.db = MagicMock()
        round_.synchronized_data.db.get.return_value = None
        round_.synchronized_data.db.update = MagicMock()

        parent_cls = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(parent_cls, return_value=None):
            result = round_.end_block()

        # Should have called db.update to initialise keys
        round_.synchronized_data.db.update.assert_called_once()
        assert round_.block_confirmations == 1
        assert result is None

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
        """Updates mech_tools and returns (updated_data, event) on non-NO_MAJORITY."""
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 1
        round_.synchronized_data.period_count = 0

        synced_data_mock = MagicMock(spec=SynchronizedData)
        updated_data_mock = MagicMock(spec=SynchronizedData)
        synced_data_mock.update.return_value = updated_data_mock

        original_values = (
            "tx_sub", "tx_hash", False, '["tool"]', "policy",
            '{}', '[]', 0, Event.DONE.value
        )
        payload_count_mock = MagicMock()
        payload_count_mock.most_common.return_value = [(original_values, 3)]

        redeem_prop = "packages.valory.skills.decision_maker_abci.states.polymarket_redeem.PolymarketRedeemRound.most_voted_payload_values"
        parent_eb = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        pvc_prop = "packages.valory.skills.abstract_round_abci.base.CollectSameUntilThresholdRound.payload_values_count"
        with patch(redeem_prop, new_callable=PropertyMock, return_value=original_values), \
             patch(parent_eb, return_value=(synced_data_mock, Event.DONE)), \
             patch(pvc_prop, new_callable=PropertyMock, return_value=payload_count_mock):
            result = round_.end_block()

        assert result is not None
        result_data, result_event = result
        assert result_data is updated_data_mock
        assert result_event == Event.DONE

    def test_end_block_no_majority_returns_as_is(self) -> None:
        """Returns original result for NO_MAJORITY event (no mech_tools update)."""
        round_ = _make_round(PolymarketRedeemRound)
        round_.block_confirmations = 1
        round_.synchronized_data.period_count = 0

        synced_data_mock = MagicMock(spec=SynchronizedData)

        end_values = (
            "tx_sub", "tx_hash", False, '["tool"]', "policy",
            '{}', '[]', 0, Event.NO_REDEEMING.value
        )

        redeem_prop = "packages.valory.skills.decision_maker_abci.states.polymarket_redeem.PolymarketRedeemRound.most_voted_payload_values"
        parent_eb = "packages.valory.skills.decision_maker_abci.states.base.TxPreparationRound.end_block"
        with patch(redeem_prop, new_callable=PropertyMock, return_value=end_values), \
             patch(parent_eb, return_value=(synced_data_mock, Event.NO_MAJORITY)):
            result = round_.end_block()

        # NO_MAJORITY equals no_majority_event, so return res as-is
        assert result == (synced_data_mock, Event.NO_MAJORITY)


# ---------------------------------------------------------------------------
# Polymarket state classes - basic attribute checks
# ---------------------------------------------------------------------------


class TestPolymarketRoundAttributes:
    """Tests for basic attribute and class structure of Polymarket rounds."""

    def test_bet_placement_round_is_tx_preparation(self) -> None:
        """PolymarketBetPlacementRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )
        assert issubclass(PolymarketBetPlacementRound, TxPreparationRound)

    def test_set_approval_round_is_tx_preparation(self) -> None:
        """PolymarketSetApprovalRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )
        assert issubclass(PolymarketSetApprovalRound, TxPreparationRound)

    def test_post_set_approval_round_is_collect_same(self) -> None:
        """PolymarketPostSetApprovalRound extends CollectSameUntilThresholdRound."""
        from packages.valory.skills.abstract_round_abci.base import (
            CollectSameUntilThresholdRound,
        )
        assert issubclass(PolymarketPostSetApprovalRound, CollectSameUntilThresholdRound)

    def test_swap_round_is_tx_preparation(self) -> None:
        """PolymarketSwapUsdcRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )
        assert issubclass(PolymarketSwapUsdcRound, TxPreparationRound)

    def test_redeem_round_is_tx_preparation(self) -> None:
        """PolymarketRedeemRound extends TxPreparationRound."""
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )
        assert issubclass(PolymarketRedeemRound, TxPreparationRound)

    def test_redeem_round_selection_key_includes_extra_fields(self) -> None:
        """PolymarketRedeemRound.selection_key includes extra Polymarket-specific fields."""
        from packages.valory.skills.abstract_round_abci.base import get_name
        from packages.valory.skills.decision_maker_abci.states.base import (
            TxPreparationRound,
        )

        # The redeem round has extra fields beyond the base TxPreparationRound
        assert len(PolymarketRedeemRound.selection_key) > len(
            TxPreparationRound.selection_key
        )
