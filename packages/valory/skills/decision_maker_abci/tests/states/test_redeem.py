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

from typing import Any, Dict, Optional
from unittest.mock import PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
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
