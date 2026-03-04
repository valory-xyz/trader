# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""This module contains the tests for rounds of TxSettlementMultiplexerAbciApp."""

import json
from typing import Dict, Set
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    DegenerateRound,
    NONE_EVENT_ATTRIBUTE,
    VotingRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    PolymarketRedeemRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_set_approval import (
    PolymarketSetApprovalRound,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_swap import (
    PolymarketSwapUsdcRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.mech_interact_abci.states.purchase_subscription import (
    MechPurchaseSubscriptionRound,
)
from packages.valory.skills.mech_interact_abci.states.request import MechRequestRound
from packages.valory.skills.staking_abci.rounds import CallCheckpointRound
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    ChecksPassedRound,
    Event,
    FailedMultiplexerRound,
    FinishedBetPlacementTxRound,
    FinishedMechRequestTxRound,
    FinishedPolymarketSwapTxRound,
    FinishedRedeemingTxRound,
    FinishedSellOutcomeTokensTxRound,
    FinishedSetApprovalTxRound,
    FinishedStakingTxRound,
    FinishedSubscriptionTxRound,
    PostTxSettlementRound,
    PreTxSettlementRound,
    TxSettlementMultiplexerAbciApp,
)


# =============================================================================
# Tests for Event enum
# =============================================================================


class TestEvent:
    """Tests for the Event enum."""

    def test_event_values(self) -> None:
        """Test that all Event enum values are as expected."""
        expected = {
            "CHECKS_PASSED": "checks_passed",
            "REFILL_REQUIRED": "refill_required",
            "MECH_REQUESTING_DONE": "mech_requesting_done",
            "BET_PLACEMENT_DONE": "bet_placement_done",
            "SELL_OUTCOME_TOKENS_DONE": "sell_outcome_tokens_done",
            "REDEEMING_DONE": "redeeming_done",
            "STAKING_DONE": "staking_done",
            "SUBSCRIPTION_DONE": "subscription_done",
            "SET_APPROVAL_DONE": "set_approval_done",
            "ROUND_TIMEOUT": "round_timeout",
            "UNRECOGNIZED": "unrecognized",
            "NO_MAJORITY": "no_majority",
            "SWAP_DONE": "swap_done",
        }
        for name, value in expected.items():
            assert Event[name].value == value

    def test_event_count(self) -> None:
        """Test that the Event enum has exactly 13 members."""
        assert len(Event) == 13

    def test_all_event_members(self) -> None:
        """Test that all expected Event members exist."""
        expected_members = {
            Event.CHECKS_PASSED,
            Event.REFILL_REQUIRED,
            Event.MECH_REQUESTING_DONE,
            Event.BET_PLACEMENT_DONE,
            Event.SELL_OUTCOME_TOKENS_DONE,
            Event.REDEEMING_DONE,
            Event.STAKING_DONE,
            Event.SUBSCRIPTION_DONE,
            Event.SET_APPROVAL_DONE,
            Event.ROUND_TIMEOUT,
            Event.UNRECOGNIZED,
            Event.NO_MAJORITY,
            Event.SWAP_DONE,
        }
        assert set(Event) == expected_members


# =============================================================================
# Tests for PreTxSettlementRound
# =============================================================================


class TestPreTxSettlementRound:
    """Tests for the PreTxSettlementRound class."""

    def test_is_voting_round_subclass(self) -> None:
        """Test that PreTxSettlementRound is a subclass of VotingRound."""
        assert issubclass(PreTxSettlementRound, VotingRound)

    def test_payload_class(self) -> None:
        """Test that payload_class is VotingPayload."""
        assert PreTxSettlementRound.payload_class is VotingPayload

    def test_synchronized_data_class(self) -> None:
        """Test that synchronized_data_class is SynchronizedData."""
        assert PreTxSettlementRound.synchronized_data_class is SynchronizedData

    def test_done_event(self) -> None:
        """Test that done_event is Event.CHECKS_PASSED."""
        assert PreTxSettlementRound.done_event == Event.CHECKS_PASSED

    def test_none_event(self) -> None:
        """Test that none_event is Event.REFILL_REQUIRED."""
        assert PreTxSettlementRound.none_event == Event.REFILL_REQUIRED

    def test_negative_event(self) -> None:
        """Test that negative_event is Event.REFILL_REQUIRED."""
        assert PreTxSettlementRound.negative_event == Event.REFILL_REQUIRED

    def test_no_majority_event(self) -> None:
        """Test that no_majority_event is Event.NO_MAJORITY."""
        assert PreTxSettlementRound.no_majority_event == Event.NO_MAJORITY

    def test_extended_requirements_filters_none_event(self) -> None:
        """Test that extended_requirements filters out NONE_EVENT_ATTRIBUTE."""
        expected = tuple(
            attr
            for attr in VotingRound.required_class_attributes
            if attr != NONE_EVENT_ATTRIBUTE
        )
        assert PreTxSettlementRound.extended_requirements == expected

    def test_none_event_attribute_not_in_extended_requirements(self) -> None:
        """Test that NONE_EVENT_ATTRIBUTE is not in extended_requirements."""
        assert NONE_EVENT_ATTRIBUTE not in PreTxSettlementRound.extended_requirements

    def test_initialization(self) -> None:
        """Test that PreTxSettlementRound can be instantiated."""
        round_ = PreTxSettlementRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, PreTxSettlementRound)
        assert isinstance(round_, VotingRound)


# =============================================================================
# Tests for PostTxSettlementRound
# =============================================================================


class TestPostTxSettlementRound:
    """Tests for the PostTxSettlementRound class."""

    def test_extended_requirements_empty(self) -> None:
        """Test that extended_requirements is an empty tuple."""
        assert PostTxSettlementRound.extended_requirements == ()

    def test_synchronized_data_class(self) -> None:
        """Test that synchronized_data_class is SynchronizedData."""
        assert PostTxSettlementRound.synchronized_data_class is SynchronizedData

    def test_initialization(self) -> None:
        """Test that PostTxSettlementRound can be instantiated."""
        round_ = PostTxSettlementRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, PostTxSettlementRound)


class TestPostTxSettlementRoundEndBlock:
    """Tests for PostTxSettlementRound.end_block method."""

    def _create_round(self) -> PostTxSettlementRound:
        """Create a PostTxSettlementRound instance for testing."""
        round_ = PostTxSettlementRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        return round_

    def test_mech_requesting_done(self) -> None:
        """Test end_block with MechRequestRound submitter returns MECH_REQUESTING_DONE and updates policy."""
        round_ = self._create_round()
        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "serialized_policy"

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = MechRequestRound.auto_round_id()
            mock_synced.policy = mock_policy
            mock_synced.mech_tool = "prediction-online"
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.MECH_REQUESTING_DONE
        assert synced_data is mock_synced
        mock_policy.tool_used.assert_called_once_with("prediction-online")
        mock_policy.serialize.assert_called_once()
        round_.synchronized_data.update.assert_called_once_with(  # type: ignore[attr-defined]
            policy="serialized_policy"  # type: ignore[attr-defined]
        )

    def test_bet_placement_done_with_valid_tx_hash(self) -> None:
        """Test end_block with BetPlacementRound submitter and valid tx hash updates utilized_tools."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = BetPlacementRound.auto_round_id()
            mock_synced.utilized_tools = {"existing_hash": "existing_tool"}
            mock_synced.final_tx_hash = "0xabc123"
            mock_synced.mech_tool = "prediction-online"
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.BET_PLACEMENT_DONE
        assert synced_data is mock_synced

        # Check that utilized_tools was updated via synchronized_data.update
        expected_tools = json.dumps(
            {"0xabc123": "prediction-online", "existing_hash": "existing_tool"},
            sort_keys=True,
        )
        round_.synchronized_data.update.assert_called_once_with(  # type: ignore[attr-defined]
            utilized_tools=expected_tools  # type: ignore[attr-defined]
        )

    def test_bet_placement_done_with_none_tx_hash(self) -> None:
        """Test end_block with BetPlacementRound submitter and None tx hash logs warning and returns early."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = BetPlacementRound.auto_round_id()
            mock_synced.utilized_tools = {}
            mock_synced.final_tx_hash = None
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.BET_PLACEMENT_DONE
        assert synced_data is mock_synced
        round_.context.logger.warning.assert_called_once()
        # Ensure update was NOT called because we returned early
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_sell_outcome_tokens_done_with_valid_tx_hash(self) -> None:
        """Test end_block with SellOutcomeTokensRound submitter and valid tx hash updates utilized_tools."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = SellOutcomeTokensRound.auto_round_id()
            mock_synced.utilized_tools = {}
            mock_synced.final_tx_hash = "0xdef456"
            mock_synced.mech_tool = "prediction-offline"
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.SELL_OUTCOME_TOKENS_DONE

        expected_tools = json.dumps({"0xdef456": "prediction-offline"}, sort_keys=True)
        round_.synchronized_data.update.assert_called_once_with(  # type: ignore[attr-defined]
            utilized_tools=expected_tools  # type: ignore[attr-defined]
        )

    def test_sell_outcome_tokens_done_with_none_tx_hash(self) -> None:
        """Test end_block with SellOutcomeTokensRound submitter and None tx hash logs warning."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = SellOutcomeTokensRound.auto_round_id()
            mock_synced.utilized_tools = {"pre": "tool"}
            mock_synced.final_tx_hash = None
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.SELL_OUTCOME_TOKENS_DONE
        round_.context.logger.warning.assert_called_once()
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_redeeming_done_from_redeem_round(self) -> None:
        """Test end_block with RedeemRound submitter returns REDEEMING_DONE."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = RedeemRound.auto_round_id()
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.REDEEMING_DONE
        assert synced_data is mock_synced
        # No update should be called for REDEEMING_DONE
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_redeeming_done_from_polymarket_redeem_round(self) -> None:
        """Test end_block with PolymarketRedeemRound submitter returns REDEEMING_DONE."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = PolymarketRedeemRound.auto_round_id()
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.REDEEMING_DONE
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_staking_done(self) -> None:
        """Test end_block with CallCheckpointRound submitter returns STAKING_DONE."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = CallCheckpointRound.auto_round_id()
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.STAKING_DONE
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_subscription_done(self) -> None:
        """Test end_block with MechPurchaseSubscriptionRound submitter returns SUBSCRIPTION_DONE."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = MechPurchaseSubscriptionRound.auto_round_id()
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.SUBSCRIPTION_DONE
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_set_approval_done(self) -> None:
        """Test end_block with PolymarketSetApprovalRound submitter returns SET_APPROVAL_DONE."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = PolymarketSetApprovalRound.auto_round_id()
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.SET_APPROVAL_DONE
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_swap_done(self) -> None:
        """Test end_block with PolymarketSwapUsdcRound submitter returns SWAP_DONE."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = PolymarketSwapUsdcRound.auto_round_id()
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.SWAP_DONE
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_unrecognized_submitter(self) -> None:
        """Test end_block with unknown submitter returns UNRECOGNIZED."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = "unknown_round_id"
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        synced_data, event = result
        assert event == Event.UNRECOGNIZED
        assert synced_data is mock_synced
        round_.synchronized_data.update.assert_not_called()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_mech_requesting_done_policy_serialize_value(self) -> None:
        """Test that the serialized policy value is passed correctly to update."""
        round_ = self._create_round()
        mock_policy = MagicMock()
        serialized = '{"tool_counts": {"prediction-online": 5}}'
        mock_policy.serialize.return_value = serialized

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = MechRequestRound.auto_round_id()
            mock_synced.policy = mock_policy
            mock_synced.mech_tool = "prediction-online"
            MockSyncData.return_value = mock_synced

            round_.end_block()

        round_.synchronized_data.update.assert_called_once_with(policy=serialized)  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_bet_placement_done_utilized_tools_merges_with_existing(self) -> None:
        """Test that new tools are merged with existing utilized_tools."""
        round_ = self._create_round()
        existing_tools = {"0xold": "old-tool", "0xother": "other-tool"}

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = BetPlacementRound.auto_round_id()
            mock_synced.utilized_tools = existing_tools.copy()
            mock_synced.final_tx_hash = "0xnew"
            mock_synced.mech_tool = "new-tool"
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == Event.BET_PLACEMENT_DONE

        expected_merged = existing_tools.copy()
        expected_merged["0xnew"] = "new-tool"
        expected_tools_json = json.dumps(expected_merged, sort_keys=True)
        round_.synchronized_data.update.assert_called_once_with(  # type: ignore[attr-defined]
            utilized_tools=expected_tools_json  # type: ignore[attr-defined]
        )

    @pytest.mark.parametrize(
        "submitter_round_cls,expected_event",
        [
            (MechRequestRound, Event.MECH_REQUESTING_DONE),
            (BetPlacementRound, Event.BET_PLACEMENT_DONE),
            (SellOutcomeTokensRound, Event.SELL_OUTCOME_TOKENS_DONE),
            (RedeemRound, Event.REDEEMING_DONE),
            (PolymarketRedeemRound, Event.REDEEMING_DONE),
            (CallCheckpointRound, Event.STAKING_DONE),
            (MechPurchaseSubscriptionRound, Event.SUBSCRIPTION_DONE),
            (PolymarketSetApprovalRound, Event.SET_APPROVAL_DONE),
            (PolymarketSwapUsdcRound, Event.SWAP_DONE),
        ],
    )
    def test_submitter_to_event_mapping(
        self, submitter_round_cls: type, expected_event: Event
    ) -> None:
        """Test the complete submitter-to-event mapping parametrically."""
        round_ = self._create_round()

        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = submitter_round_cls.auto_round_id()  # type: ignore[attr-defined]
            # Provide attributes needed for MECH_REQUESTING_DONE path  # type: ignore[attr-defined]
            mock_synced.policy = MagicMock()
            mock_synced.policy.serialize.return_value = "serialized"
            mock_synced.mech_tool = "test-tool"
            # Provide attributes needed for BET_PLACEMENT_DONE / SELL_OUTCOME_TOKENS_DONE path
            mock_synced.utilized_tools = {}
            mock_synced.final_tx_hash = "0xhash"
            MockSyncData.return_value = mock_synced

            result = round_.end_block()

        assert result is not None
        _, event = result
        assert event == expected_event

    def test_synced_data_constructed_from_db(self) -> None:
        """Test that SynchronizedData is constructed using self.synchronized_data.db."""
        round_ = self._create_round()
        mock_db = MagicMock()
        round_.synchronized_data.db = mock_db  # type: ignore[misc]
        # type: ignore[misc]
        with patch(
            "packages.valory.skills.tx_settlement_multiplexer_abci.rounds.SynchronizedData"
        ) as MockSyncData:
            mock_synced = MagicMock()
            mock_synced.tx_submitter = "unknown"
            MockSyncData.return_value = mock_synced

            round_.end_block()

        MockSyncData.assert_called_once_with(mock_db)


# =============================================================================
# Tests for DegenerateRound subclasses
# =============================================================================


class TestDegenerateRounds:
    """Tests for all DegenerateRound subclasses."""

    @pytest.mark.parametrize(
        "round_cls",
        [
            ChecksPassedRound,
            FinishedMechRequestTxRound,
            FinishedBetPlacementTxRound,
            FinishedSellOutcomeTokensTxRound,
            FinishedRedeemingTxRound,
            FinishedStakingTxRound,
            FinishedSubscriptionTxRound,
            FinishedSetApprovalTxRound,
            FailedMultiplexerRound,
            FinishedPolymarketSwapTxRound,
        ],
    )
    def test_is_degenerate_round_subclass(self, round_cls: type) -> None:
        """Test that all final round classes are DegenerateRound subclasses."""
        assert issubclass(round_cls, DegenerateRound)

    @pytest.mark.parametrize(
        "round_cls",
        [
            ChecksPassedRound,
            FinishedMechRequestTxRound,
            FinishedBetPlacementTxRound,
            FinishedSellOutcomeTokensTxRound,
            FinishedRedeemingTxRound,
            FinishedStakingTxRound,
            FinishedSubscriptionTxRound,
            FinishedSetApprovalTxRound,
            FailedMultiplexerRound,
            FinishedPolymarketSwapTxRound,
        ],
    )
    def test_initialization(self, round_cls: type) -> None:
        """Test that all DegenerateRound subclasses can be instantiated."""
        round_ = round_cls(synchronized_data=MagicMock(), context=MagicMock())
        assert isinstance(round_, round_cls)
        assert isinstance(round_, DegenerateRound)


# =============================================================================
# Tests for TxSettlementMultiplexerAbciApp
# =============================================================================


@pytest.fixture
def abci_app() -> TxSettlementMultiplexerAbciApp:
    """Fixture for TxSettlementMultiplexerAbciApp."""
    synchronized_data = MagicMock()
    logger = MagicMock()
    context = MagicMock()

    return TxSettlementMultiplexerAbciApp(
        synchronized_data=synchronized_data, logger=logger, context=context
    )


class TestTxSettlementMultiplexerAbciApp:
    """Tests for TxSettlementMultiplexerAbciApp."""

    def test_initial_round_cls(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test that the initial round class is PreTxSettlementRound."""
        assert abci_app.initial_round_cls is PreTxSettlementRound

    def test_initial_states(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test the set of initial states."""
        assert TxSettlementMultiplexerAbciApp.initial_states == {
            PreTxSettlementRound,
            PostTxSettlementRound,
        }

    def test_transition_function(
        self, abci_app: TxSettlementMultiplexerAbciApp
    ) -> None:
        """Test the full transition function mapping."""
        expected = {
            PreTxSettlementRound: {
                Event.CHECKS_PASSED: ChecksPassedRound,
                Event.REFILL_REQUIRED: PreTxSettlementRound,
                Event.NO_MAJORITY: PreTxSettlementRound,
                Event.ROUND_TIMEOUT: PreTxSettlementRound,
            },
            PostTxSettlementRound: {
                Event.MECH_REQUESTING_DONE: FinishedMechRequestTxRound,
                Event.BET_PLACEMENT_DONE: FinishedBetPlacementTxRound,
                Event.SELL_OUTCOME_TOKENS_DONE: FinishedSellOutcomeTokensTxRound,
                Event.REDEEMING_DONE: FinishedRedeemingTxRound,
                Event.SWAP_DONE: FinishedPolymarketSwapTxRound,
                Event.STAKING_DONE: FinishedStakingTxRound,
                Event.SUBSCRIPTION_DONE: FinishedSubscriptionTxRound,
                Event.SET_APPROVAL_DONE: FinishedSetApprovalTxRound,
                Event.ROUND_TIMEOUT: PostTxSettlementRound,
                Event.UNRECOGNIZED: FailedMultiplexerRound,
            },
            ChecksPassedRound: {},
            FinishedMechRequestTxRound: {},
            FinishedBetPlacementTxRound: {},
            FinishedSellOutcomeTokensTxRound: {},
            FinishedSubscriptionTxRound: {},
            FinishedSetApprovalTxRound: {},
            FinishedRedeemingTxRound: {},
            FinishedPolymarketSwapTxRound: {},
            FinishedStakingTxRound: {},
            FailedMultiplexerRound: {},
        }
        assert abci_app.transition_function == expected

    def test_final_states(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test the set of final states."""
        expected_final: Set[type] = {
            ChecksPassedRound,
            FinishedMechRequestTxRound,
            FinishedBetPlacementTxRound,
            FinishedSellOutcomeTokensTxRound,
            FinishedRedeemingTxRound,
            FinishedPolymarketSwapTxRound,
            FinishedStakingTxRound,
            FinishedSubscriptionTxRound,
            FinishedSetApprovalTxRound,
            FailedMultiplexerRound,
        }
        assert abci_app.final_states == expected_final

    def test_event_to_timeout(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test the event-to-timeout mapping."""
        assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}

    def test_db_pre_conditions(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test the database pre-conditions."""
        expected: Dict[type, Set[str]] = {
            PreTxSettlementRound: {get_name(SynchronizedData.tx_submitter)},
            PostTxSettlementRound: {get_name(SynchronizedData.tx_submitter)},
        }
        assert abci_app.db_pre_conditions == expected

    def test_db_post_conditions(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test the database post-conditions."""
        expected: Dict[type, Set[str]] = {
            ChecksPassedRound: set(),
            FinishedMechRequestTxRound: set(),
            FinishedBetPlacementTxRound: set(),
            FinishedSellOutcomeTokensTxRound: set(),
            FinishedRedeemingTxRound: set(),
            FinishedPolymarketSwapTxRound: set(),
            FinishedStakingTxRound: set(),
            FailedMultiplexerRound: set(),
            FinishedSubscriptionTxRound: set(),
            FinishedSetApprovalTxRound: set(),
        }
        assert abci_app.db_post_conditions == expected

    def test_final_states_count(self, abci_app: TxSettlementMultiplexerAbciApp) -> None:
        """Test that there are exactly 10 final states."""
        assert len(abci_app.final_states) == 10

    def test_degenerate_rounds_have_empty_transitions(
        self, abci_app: TxSettlementMultiplexerAbciApp
    ) -> None:
        """Test that all final (degenerate) rounds have empty transition functions."""
        for state in abci_app.final_states:
            assert abci_app.transition_function[state] == {}

    def test_pre_tx_settlement_self_loops(
        self, abci_app: TxSettlementMultiplexerAbciApp
    ) -> None:
        """Test that PreTxSettlementRound has self-loop transitions for error events."""
        pre_transitions = abci_app.transition_function[PreTxSettlementRound]
        assert pre_transitions[Event.REFILL_REQUIRED] is PreTxSettlementRound
        assert pre_transitions[Event.NO_MAJORITY] is PreTxSettlementRound
        assert pre_transitions[Event.ROUND_TIMEOUT] is PreTxSettlementRound

    def test_post_tx_settlement_self_loop_on_timeout(
        self, abci_app: TxSettlementMultiplexerAbciApp
    ) -> None:
        """Test that PostTxSettlementRound self-loops on ROUND_TIMEOUT."""
        post_transitions = abci_app.transition_function[PostTxSettlementRound]
        assert post_transitions[Event.ROUND_TIMEOUT] is PostTxSettlementRound
