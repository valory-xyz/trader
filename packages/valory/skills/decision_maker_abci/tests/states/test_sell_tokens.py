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

"""This package contains the tests for Decision Maker"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)

DUMMY_SELL_HASH = "dummy_sell_hash"
DUMMY_PARTICIPANT_TO_SELL_HASH = json.dumps(
    {
        "agent_0": "sell_1",
        "agent_1": "sell_2",
        "agent_2": "sell_3",
    }
)


def get_participants() -> FrozenSet[str]:
    """Participants."""
    return frozenset([f"agent_{i}" for i in range(4)])


def get_payloads(
    tx_submitter: str,
    tx_hash: str,
    mocking_mode: bool,
    vote: int,
    sell_amount: Optional[int],
) -> Mapping[str, Any]:  # Replace Any with SellOutcomeTokensPayload if available
    """Get payloads."""
    # Replace with actual payload class and fields if available
    return {
        participant: mock.MagicMock(
            sender=participant,
            tx_submitter=tx_submitter,
            tx_hash=tx_hash,
            mocking_mode=mocking_mode,
            vote=vote,
            sell_amount=sell_amount,
        )
        for participant in get_participants()
    }


@dataclass
class RoundTestCase:
    """RoundTestCase for SellOutcomeTokensRound."""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[
        str, Any
    ]  # Replace Any with SellOutcomeTokensPayload if available
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


class TestSellOutcomeTokensRound(BaseCollectSameUntilThresholdRoundTest):
    """Tests for SellOutcomeTokensRound."""

    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={
                    "vote": 0,
                },
                payloads=get_payloads(
                    tx_submitter="tx_submitter",
                    tx_hash="tx_hash",
                    mocking_mode=False,
                    vote=0,
                    sell_amount=100,
                ),
                final_data={
                    "vote": 1,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_SELL_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.vote,
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    tx_submitter="tx_submitter",
                    tx_hash="tx_hash",
                    mocking_mode=False,
                    vote=1,
                    sell_amount=None,
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            RoundTestCase(
                name="Calculation failed",
                initial_data={},
                payloads=get_payloads(
                    tx_submitter="tx_submitter",
                    tx_hash="tx_hash",
                    mocking_mode=False,
                    vote=1,
                    sell_amount=None,
                ),
                final_data={},
                event=Event.CALC_SELL_AMOUNT_FAILED,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
            # Add more cases as needed
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        self.run_test(test_case)

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test."""
        self.synchronized_data.update(SynchronizedData, **test_case.initial_data)

        test_round = SellOutcomeTokensRound(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._test_round(
            test_round=test_round,
            round_payloads=test_case.payloads,
            synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                **test_case.final_data
            ),
            synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
            most_voted_payload=test_case.most_voted_payload,
            exit_event=test_case.event,
        )


class TestSellOutcomeTokensRoundEndBlock:
    """Direct unit tests for SellOutcomeTokensRound.end_block covering all branches."""

    def _make_round(self) -> SellOutcomeTokensRound:
        """Create a SellOutcomeTokensRound with mocked dependencies."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_context = MagicMock()
        return SellOutcomeTokensRound(
            synchronized_data=mock_synced_data, context=mock_context
        )

    def test_end_block_returns_none_when_super_returns_none(self) -> None:
        """Test end_block returns None when parent returns None."""
        round_instance = self._make_round()
        with patch.object(TxPreparationRound, "end_block", return_value=None):
            result = round_instance.end_block()
        assert result is None

    def test_end_block_done_with_tx_hash(self) -> None:
        """Test end_block returns DONE when tx_hash is present."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.most_voted_tx_hash = "0xvalidhash"
        round_instance = self._make_round()
        with patch.object(
            TxPreparationRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.DONE

    def test_end_block_done_without_tx_hash(self) -> None:
        """Test end_block returns CALC_SELL_AMOUNT_FAILED when tx_hash is missing."""
        mock_synced_data = MagicMock(spec=SynchronizedData)
        mock_synced_data.most_voted_tx_hash = None
        round_instance = self._make_round()
        with patch.object(
            TxPreparationRound,
            "end_block",
            return_value=(mock_synced_data, Event.DONE),
        ):
            result = round_instance.end_block()
        assert result is not None
        _, event = result
        assert event == Event.CALC_SELL_AMOUNT_FAILED

    def test_end_block_non_done_event_passes_through(self) -> None:
        """Test end_block passes through non-DONE events unchanged."""
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
