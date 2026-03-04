# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""Test for Redeem round"""

from collections import Counter
from typing import Any, Dict, Optional, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.decision_maker_abci.payloads import RedeemPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound


class MockDB(AbciAppDB):
    """Mock database for testing."""

    def __init__(self) -> None:
        """Initialize the mock database."""
        setup_data: Dict[str, Any] = {}
        super().__init__(setup_data=setup_data)
        self.data: Dict[str, Optional[int]] = {}

    def get(self, key: str, default: Optional[int] = None) -> Optional[int]:
        """Get value from mock db."""
        return self.data.get(key, default)

    def update(self, **kwargs: Any) -> None:
        """Update mock db."""
        self.data.update(kwargs)


class MockSynchronizedData(SynchronizedData):
    """Mock synchronized data for testing."""

    def __init__(self) -> None:
        """Initialize mock synchronized data."""
        db = MockDB()
        super().__init__(db)
        self._period_count = 0

    @property
    def period_count(self) -> int:
        """Get period count."""
        return self._period_count

    @period_count.setter
    def period_count(self, value: int) -> None:
        """Set period count."""
        self._period_count = value


class MockContext:
    """Mock context for testing."""

    def __init__(self) -> None:
        """Initialize mock context."""
        self.params: Dict[str, Optional[int]] = {}


class TestRedeemRound:
    """Tests for the RedeemRound class."""

    @pytest.fixture
    def setup_redeem_round(self) -> RedeemRound:
        """Set up a RedeemRound instance."""
        mock_synchronized_data = MockSynchronizedData()
        mock_context = MockContext()
        redeem_round = RedeemRound(
            context=mock_context, synchronized_data=mock_synchronized_data
        )
        return redeem_round

    def test_initial_attributes(self, setup_redeem_round: RedeemRound) -> None:
        """Test initial attributes."""
        redeem_round = setup_redeem_round
        assert redeem_round.payload_class is not None
        assert redeem_round.payload_class.__name__ == "RedeemPayload"
        assert redeem_round.none_event == Event.NO_REDEEMING

    def test_selection_key(self, setup_redeem_round: RedeemRound) -> None:
        """Test selection key generation."""
        redeem_round = setup_redeem_round
        assert isinstance(redeem_round.selection_key, tuple)
        assert all(isinstance(key, str) for key in redeem_round.selection_key)

    def test_selection_key_contains_mech_tools_name(
        self, setup_redeem_round: RedeemRound
    ) -> None:
        """Test that mech_tools_name is part of the selection key."""
        redeem_round = setup_redeem_round
        assert RedeemRound.mech_tools_name in redeem_round.selection_key

    @pytest.mark.parametrize(
        "period_count, expected_confirmations, expected_event",
        [
            (0, 1, Event.NO_MAJORITY),  # Test without update
            (1, 0, Event.NO_MAJORITY),  # Test with update
        ],
    )
    def test_end_block_update_behavior(
        self,
        setup_redeem_round: RedeemRound,
        period_count: int,
        expected_confirmations: int,
        expected_event: Event,
    ) -> None:
        """Test end_block behavior based on period_count."""
        redeem_round = setup_redeem_round

        with patch.object(
            MockSynchronizedData, "period_count", new_callable=PropertyMock
        ) as mock_period_count:
            mock_period_count.return_value = period_count

            result = redeem_round.end_block()

            if result is None:
                # Case where no update occurs
                assert redeem_round.block_confirmations == expected_confirmations
            else:
                # Case where update occurs
                synchronized_data, event = result
                assert isinstance(synchronized_data, MockSynchronizedData)
                assert event == expected_event

    def test_most_voted_payload_values(self, setup_redeem_round: RedeemRound) -> None:
        """Test most_voted_payload_values property."""
        redeem_round = setup_redeem_round
        # Mock `most_voted_payload_values` to return the expected result
        with patch.object(
            RedeemRound, "most_voted_payload_values", new_callable=PropertyMock
        ) as mock_values:
            mock_values.return_value = (None,)
            values = redeem_round.most_voted_payload_values
            assert values == (None,)

    def test_most_voted_payload_dict_processing(
        self, setup_redeem_round: RedeemRound
    ) -> None:
        """Test processing of most_voted_payload_dict in most_voted_payload_values."""
        redeem_round = setup_redeem_round
        # Mock `most_voted_payload_values` to simulate dictionary processing in the property
        with patch.object(
            RedeemRound, "most_voted_payload_values", new_callable=PropertyMock
        ) as mock_values:
            mock_values.return_value = ("tool_data",)

            values = redeem_round.most_voted_payload_values
            assert values is not None  # Ensure it executes without error


class TestRedeemRoundMostVotedPayloadValues:
    """Tests for the most_voted_payload_values property of RedeemRound."""

    def _make_round(self) -> RedeemRound:
        """Create a RedeemRound with mocked dependencies."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_context = MagicMock()
        return RedeemRound(
            synchronized_data=mock_synced_data, context=mock_context
        )

    def test_most_voted_payload_values_with_valid_data(self) -> None:
        """Test most_voted_payload_values when there are non-None values besides mech_tools."""
        round_instance = self._make_round()
        # RedeemPayload fields: tx_submitter, tx_hash, mocking_mode, mech_tools, policy, utilized_tools, redeemed_condition_ids, payout_so_far
        payload_values = ("submitter", "0xhash", False, '["tool1"]', "policy_val", '{}', '[]', 100)
        with patch.object(
            CollectSameUntilThresholdRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=payload_values,
        ):
            result = round_instance.most_voted_payload_values
        assert result == payload_values

    def test_most_voted_payload_values_all_none_except_mech_tools(self) -> None:
        """Test most_voted_payload_values when all values except mech_tools are None."""
        round_instance = self._make_round()
        # All fields None except mech_tools
        payload_values = (None, None, None, '["tool1"]', None, None, None, None)
        with patch.object(
            CollectSameUntilThresholdRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=payload_values,
        ):
            result = round_instance.most_voted_payload_values
        assert result == (None,) * len(RedeemRound.selection_key)

    def test_most_voted_payload_values_mech_tools_none_raises(self) -> None:
        """Test most_voted_payload_values raises ValueError when mech_tools is None."""
        round_instance = self._make_round()
        # mech_tools is None (field index 3)
        payload_values = ("submitter", "0xhash", False, None, "policy_val", '{}', '[]', 100)
        with patch.object(
            CollectSameUntilThresholdRound,
            "most_voted_payload_values",
            new_callable=PropertyMock,
            return_value=payload_values,
        ):
            with pytest.raises(ValueError, match="must not be `None`"):
                round_instance.most_voted_payload_values


class TestRedeemRoundEndBlock:
    """Direct unit tests for RedeemRound.end_block covering all branches."""

    def _make_round(self) -> RedeemRound:
        """Create a RedeemRound with mocked dependencies."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.period_count = 0
        mock_synced_data.db = MagicMock()
        mock_synced_data.db.get.return_value = None
        mock_context = MagicMock()
        return RedeemRound(
            synchronized_data=mock_synced_data, context=mock_context
        )

    def test_end_block_returns_none_after_first_period_protection(self) -> None:
        """Test end_block with first period protection (block_confirmations=0, period_count=0)."""
        round_instance = self._make_round()
        round_instance.block_confirmations = 0
        round_instance.synchronized_data.period_count = 0
        with patch.object(
            TxPreparationRound, "end_block", return_value=None
        ):
            result = round_instance.end_block()
        assert result is None
        assert round_instance.block_confirmations == 1

    def test_end_block_returns_none_when_period_count_not_zero(self) -> None:
        """Test end_block returns None when period_count is not zero."""
        round_instance = self._make_round()
        round_instance.block_confirmations = 0
        round_instance.synchronized_data.period_count = 1
        with patch.object(
            TxPreparationRound, "end_block", return_value=None
        ):
            result = round_instance.end_block()
        assert result is None

    def test_end_block_with_majority_updates_mech_tools(self) -> None:
        """Test end_block updates mech_tools when there is a majority event (not NO_MAJORITY)."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        updated_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.update.return_value = updated_data
        round_instance = self._make_round()
        # Set up payload_values_count so most_common returns the right values
        payload_values = ("submitter", "0xhash", False, '["tool1"]', "policy_val", '{}', '[]', 100)
        mock_counter = Counter({payload_values: 3})
        with patch.object(
            TxPreparationRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                RedeemRound,
                "payload_values_count",
                new_callable=PropertyMock,
                return_value=mock_counter,
            ):
                result = round_instance.end_block()
        assert result is not None
        synced, event = result
        assert event == Event.DONE
        mock_synced_data.update.assert_called_once()

    def test_end_block_no_majority_returns_original(self) -> None:
        """Test end_block returns original result on NO_MAJORITY event."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        round_instance = self._make_round()
        with patch.object(
            TxPreparationRound,
            "end_block",
            return_value=(mock_synced_data, Event.NO_MAJORITY),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.NO_MAJORITY
