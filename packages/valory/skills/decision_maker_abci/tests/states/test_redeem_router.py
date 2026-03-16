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

"""Tests for the redeem_router state of decision_maker_abci."""

from unittest.mock import MagicMock, patch

from packages.valory.skills.abstract_round_abci.base import VotingRound
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.redeem_router import (
    RedeemRouterRound,
)


class TestRedeemRouterRound:
    """Tests for the RedeemRouterRound class."""

    def test_initialization(self) -> None:
        """Test that the round is properly initialized."""
        round_instance = RedeemRouterRound(MagicMock(), MagicMock())
        assert round_instance.done_event == Event.DONE
        assert round_instance.none_event == Event.NONE
        assert round_instance.negative_event == Event.NONE
        assert round_instance.no_majority_event == Event.NO_MAJORITY

    def test_inherits_from_voting_round(self) -> None:
        """Test that it inherits from VotingRound."""
        assert issubclass(RedeemRouterRound, VotingRound)

    def test_end_block_returns_none_when_super_returns_none(self) -> None:
        """Test end_block returns None when the parent returns None."""
        mock_context = MagicMock()
        mock_synced_data = MagicMock(spec=SynchronizedData)
        round_instance = RedeemRouterRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        with patch.object(VotingRound, "end_block", return_value=None):
            result = round_instance.end_block()
        assert result is None

    def test_end_block_polymarket_returns_polymarket_done(self) -> None:
        """Test end_block returns POLYMARKET_DONE when running on Polymarket."""
        mock_context = MagicMock()
        mock_context.params.is_running_on_polymarket = True
        mock_synced_data = MagicMock(spec=SynchronizedData)
        round_instance = RedeemRouterRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        with patch.object(
            VotingRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.POLYMARKET_DONE

    def test_end_block_non_polymarket_returns_done(self) -> None:
        """Test end_block returns DONE when not running on Polymarket."""
        mock_context = MagicMock()
        mock_context.params.is_running_on_polymarket = False
        mock_synced_data = MagicMock(spec=SynchronizedData)
        round_instance = RedeemRouterRound(
            synchronized_data=mock_synced_data, context=mock_context
        )
        with patch.object(
            VotingRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.DONE
