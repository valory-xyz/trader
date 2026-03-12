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

"""This package contains the tests for Decision Maker"""

import datetime
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
from unittest import mock
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)

DUMMY_DECISION_HASH = "dummy_decision_hash"
DUMMY_PARTICIPANT_TO_DECISION_HASH = json.dumps(
    {
        "agent_0": "decision_1",
        "agent_1": "decision_2",
        "agent_2": "decision_3",
    }
)
DUMMY_BETS_HASH = "dummy_bets_hash"  # Added a dummy bets hash


def get_participants() -> FrozenSet[str]:
    """Participants."""
    return frozenset([f"agent_{i}" for i in range(4)])


def get_payloads(
    vote: Optional[int],
    confidence: Optional[float],
    bet_amount: Optional[int],
    next_mock_data_row: Optional[int],
    is_profitable: Optional[bool],
    bets_hash: str,
    policy: str,
    should_be_sold: bool,
) -> Mapping[str, DecisionReceivePayload]:
    """Get payloads."""
    return {
        participant: DecisionReceivePayload(
            sender=participant,
            vote=vote,
            confidence=confidence,
            bet_amount=bet_amount,
            next_mock_data_row=next_mock_data_row,
            is_profitable=is_profitable,
            bets_hash=bets_hash,
            policy=policy,
            decision_received_timestamp=int(
                datetime.datetime.now(datetime.timezone.utc).timestamp()
            ),
            should_be_sold=should_be_sold,
        )
        for participant in get_participants()
    }


@dataclass
class RoundTestCase:
    """RoundTestCase for DecisionReceiveRound."""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, DecisionReceivePayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


class TestDecisionReceiveRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for DecisionReceiveRound."""

    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    vote=1,
                    confidence=80.0,
                    bet_amount=100,
                    next_mock_data_row=1,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={
                    "decision_hash": DUMMY_DECISION_HASH,
                    "participant_to_decision_hash": DUMMY_PARTICIPANT_TO_DECISION_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_DECISION_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.decision_hash,
                ],
            ),
            RoundTestCase(
                name="Should be sold decision",
                initial_data={"should_be_sold": True},
                payloads=get_payloads(
                    vote=1,
                    confidence=80.0,
                    bet_amount=100,
                    next_mock_data_row=1,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=True,
                ),
                final_data={
                    "decision_hash": DUMMY_DECISION_HASH,
                    "participant_to_decision_hash": DUMMY_PARTICIPANT_TO_DECISION_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_DECISION_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.decision_hash,
                ],
            ),
            RoundTestCase(
                name="Unprofitable decision",
                initial_data={"is_profitable": False},
                payloads=get_payloads(
                    vote=0,
                    confidence=50.0,
                    bet_amount=50,
                    next_mock_data_row=2,
                    is_profitable=False,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={
                    "decision_hash": DUMMY_DECISION_HASH,
                    "participant_to_decision_hash": DUMMY_PARTICIPANT_TO_DECISION_HASH,
                },
                event=Event.UNPROFITABLE,
                most_voted_payload=DUMMY_DECISION_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.decision_hash,
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    vote=None,
                    confidence=None,
                    bet_amount=None,
                    next_mock_data_row=None,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Tie event",
                initial_data={},
                payloads=get_payloads(
                    vote=None,
                    confidence=None,
                    bet_amount=None,
                    next_mock_data_row=None,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={},
                event=Event.TIE,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Mechanism response error",
                initial_data={"mocking_mode": True},
                payloads=get_payloads(
                    vote=None,
                    confidence=None,
                    bet_amount=None,
                    next_mock_data_row=None,
                    is_profitable=True,
                    policy="",
                    bets_hash=DUMMY_BETS_HASH,  # Added bets_hash
                    should_be_sold=False,
                ),
                final_data={},
                event=Event.MECH_RESPONSE_ERROR,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test."""
        self.synchronized_data.update(SynchronizedData, **test_case.initial_data)

        test_round = DecisionReceiveRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._test_round(
            test_round=test_round,
            round_payloads=test_case.payloads,  # type: ignore[arg-type]
            synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                **test_case.final_data
            ),
            synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
            most_voted_payload=test_case.most_voted_payload,
            exit_event=test_case.event,
        )


class TestDecisionReceiveRoundEndBlock:
    """Direct unit tests for DecisionReceiveRound.end_block covering all branches."""

    def _make_round(
        self,
        review_bets_for_selling: bool = False,
        is_running_on_polymarket: bool = False,
    ) -> DecisionReceiveRound:
        """Create a DecisionReceiveRound with mocked dependencies."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.review_bets_for_selling = review_bets_for_selling
        mock_context = MagicMock()
        mock_context.params.is_running_on_polymarket = is_running_on_polymarket
        return DecisionReceiveRound(
            synchronized_data=mock_synced_data, context=mock_context
        )

    def test_synchronized_data_property(self) -> None:
        """Test that synchronized_data property returns a cast SynchronizedData."""
        round_instance = self._make_round()
        result = round_instance.synchronized_data
        assert result is not None

    def test_review_bets_for_selling_mode_property(self) -> None:
        """Test the review_bets_for_selling_mode property."""
        round_instance = self._make_round(review_bets_for_selling=True)
        assert round_instance.review_bets_for_selling_mode is True

        round_instance = self._make_round(review_bets_for_selling=False)
        assert round_instance.review_bets_for_selling_mode is False

    def test_payload_method(self) -> None:
        """Test the payload method creates a DecisionReceivePayload."""
        round_instance = self._make_round()
        payload_values = (
            "bets_hash_val",
            True,
            1,
            0.9,
            100,
            1,
            "policy_val",
            1234567890,
            False,
        )
        result = round_instance.payload(payload_values)
        assert isinstance(result, DecisionReceivePayload)

    def test_end_block_returns_none_when_super_returns_none(self) -> None:
        """Test end_block returns None when parent returns None."""
        round_instance = self._make_round()
        with patch.object(
            CollectSameUntilThresholdRound, "end_block", return_value=None
        ):
            result = round_instance.end_block()
        assert result is None

    def test_end_block_non_done_event(self) -> None:
        """Test end_block passes through non-DONE events like NO_MAJORITY."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        round_instance = self._make_round()
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.NO_MAJORITY),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.NO_MAJORITY

    def test_end_block_done_vote_none_returns_tie(self) -> None:
        """Test end_block returns TIE when event is DONE but vote is None."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.vote = None
        # update() must return a synced_data where vote is still None
        updated_synced_data = MagicMock(spec=SynchronizedData)
        updated_synced_data.vote = None
        mock_synced_data.update.return_value = updated_synced_data
        round_instance = self._make_round()
        mock_payload_values = (
            "bets_hash",
            True,
            None,
            0.9,
            100,
            1,
            "policy",
            1234567890,
            False,
        )
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                DecisionReceiveRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=mock_payload_values,
            ):
                result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.TIE

    def test_end_block_done_review_selling_should_be_sold(self) -> None:
        """Test end_block returns DONE_SELL when in review selling mode and should_be_sold is True."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.vote = 1
        mock_synced_data.is_profitable = True
        updated_synced_data = MagicMock(spec=SynchronizedData)
        updated_synced_data.vote = 1
        updated_synced_data.is_profitable = True
        updated_synced_data.should_be_sold = True
        mock_synced_data.update.return_value = updated_synced_data
        round_instance = self._make_round(review_bets_for_selling=True)
        # Make synchronized_data.should_be_sold True (for `self.synchronized_data.should_be_sold`)
        round_instance.synchronized_data.should_be_sold = True  # type: ignore[misc]
        mock_payload_values = (  # type: ignore[misc]
            "bets_hash",
            True,
            1,
            0.9,
            100,
            1,
            "policy",
            1234567890,
            True,
        )
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                DecisionReceiveRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=mock_payload_values,
            ):
                result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.DONE_SELL

    def test_end_block_done_review_selling_should_not_be_sold(self) -> None:
        """Test end_block returns DONE_NO_SELL when in review selling mode and should_be_sold is False."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.vote = 1
        mock_synced_data.is_profitable = True
        updated_synced_data = MagicMock(spec=SynchronizedData)
        updated_synced_data.vote = 1
        updated_synced_data.is_profitable = True
        updated_synced_data.should_be_sold = False
        mock_synced_data.update.return_value = updated_synced_data
        round_instance = self._make_round(review_bets_for_selling=True)
        round_instance.synchronized_data.should_be_sold = False  # type: ignore[misc]
        mock_payload_values = (  # type: ignore[misc]
            "bets_hash",
            True,
            1,
            0.9,
            100,
            1,
            "policy",
            1234567890,
            False,
        )
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                DecisionReceiveRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=mock_payload_values,
            ):
                result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.DONE_NO_SELL

    def test_end_block_done_not_profitable(self) -> None:
        """Test end_block returns UNPROFITABLE when event is DONE but not profitable."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.vote = 1
        mock_synced_data.is_profitable = False
        updated_synced_data = MagicMock(spec=SynchronizedData)
        updated_synced_data.vote = 1
        updated_synced_data.is_profitable = False
        updated_synced_data.should_be_sold = False
        mock_synced_data.update.return_value = updated_synced_data
        round_instance = self._make_round(review_bets_for_selling=False)
        mock_payload_values = (
            "bets_hash",
            False,
            1,
            0.9,
            100,
            1,
            "policy",
            1234567890,
            False,
        )
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                DecisionReceiveRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=mock_payload_values,
            ):
                result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.UNPROFITABLE

    def test_end_block_done_profitable_polymarket(self) -> None:
        """Test end_block returns POLYMARKET_DONE when profitable and running on polymarket."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.vote = 1
        mock_synced_data.is_profitable = True
        updated_synced_data = MagicMock(spec=SynchronizedData)
        updated_synced_data.vote = 1
        updated_synced_data.is_profitable = True
        updated_synced_data.should_be_sold = False
        mock_synced_data.update.return_value = updated_synced_data
        round_instance = self._make_round(
            review_bets_for_selling=False,
            is_running_on_polymarket=True,
        )
        mock_payload_values = (
            "bets_hash",
            True,
            1,
            0.9,
            100,
            1,
            "policy",
            1234567890,
            False,
        )
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                DecisionReceiveRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=mock_payload_values,
            ):
                result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.POLYMARKET_DONE

    def test_end_block_done_profitable_not_polymarket(self) -> None:
        """Test end_block returns DONE when profitable and not running on polymarket."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.vote = 1
        mock_synced_data.is_profitable = True
        updated_synced_data = MagicMock(spec=SynchronizedData)
        updated_synced_data.vote = 1
        updated_synced_data.is_profitable = True
        updated_synced_data.should_be_sold = False
        mock_synced_data.update.return_value = updated_synced_data
        round_instance = self._make_round(
            review_bets_for_selling=False,
            is_running_on_polymarket=False,
        )
        mock_payload_values = (
            "bets_hash",
            True,
            1,
            0.9,
            100,
            1,
            "policy",
            1234567890,
            False,
        )
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            with patch.object(
                DecisionReceiveRound,
                "most_voted_payload_values",
                new_callable=PropertyMock,
                return_value=mock_payload_values,
            ):
                result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_end_block_mech_response_error(self) -> None:
        """Test end_block passes through MECH_RESPONSE_ERROR event."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        round_instance = self._make_round()
        with patch.object(
            CollectSameUntilThresholdRound,
            "end_block",
            return_value=(mock_synced_data, Event.MECH_RESPONSE_ERROR),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.MECH_RESPONSE_ERROR
