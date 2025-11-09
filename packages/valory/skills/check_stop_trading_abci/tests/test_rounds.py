# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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

"""This package contains the tests for the CheckStopTradingAbciApp."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    Type,
)
from unittest.mock import MagicMock, Mock

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    CollectionRound,
    VotingRound,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseVotingRoundTest,
)
from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
    CheckStopTradingRound,
    Event,
    FinishedCheckStopTradingRound,
    FinishedWithReviewBetsRound,
    FinishedWithSkipTradingRound,
    SynchronizedData,
)


DUMMY_PAYLOAD_DATA = {"example_key": "example_value"}


@pytest.fixture
def abci_app() -> CheckStopTradingAbciApp:
    """Fixture for CheckStopTradingAbciApp."""
    synchronized_data = Mock()
    logger = Mock()
    context = Mock()

    return CheckStopTradingAbciApp(
        synchronized_data=synchronized_data, logger=logger, context=context
    )


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_participant_to_votes(
    participants: FrozenSet[str], vote: bool, review_bets_for_selling: bool
) -> Dict[str, CheckStopTradingPayload]:
    """participant_to_votes"""

    return {
        participant: CheckStopTradingPayload(
            sender=participant,
            vote=vote,
            review_bets_for_selling=review_bets_for_selling,
        )
        for participant in participants
    }


def get_participant_to_votes_serialized(
    participants: FrozenSet[str], vote: bool, review_bets_for_selling: bool
) -> Dict[str, Dict[str, Any]]:
    """participant_to_votes"""

    return CollectionRound.serialize_collection(
        get_participant_to_votes(participants, vote, review_bets_for_selling)
    )


def get_payloads(
    payload_cls: Type[CheckStopTradingPayload],
    data: Optional[str],
) -> Mapping[str, CheckStopTradingPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data is not None)
        for participant in get_participants()
    }


def get_dummy_check_stop_trading_payload_serialized() -> str:
    """Dummy payload serialization"""
    return json.dumps(DUMMY_PAYLOAD_DATA, sort_keys=True)


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, CheckStopTradingPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BaseCheckStopTradingRoundTest(BaseVotingRoundTest):
    """Base Test Class for CheckStopTradingRound"""

    test_class: Type[VotingRound]
    test_payload: Type[CheckStopTradingPayload]

    def _test_voting_round(
        self,
        vote: bool,
        expected_event: Any,
        threshold_check: Callable,
        should_review_bets: bool = False,
    ) -> None:
        """Helper method to test voting rounds with positive or negative votes."""

        test_round = self.test_class(
            synchronized_data=self.synchronized_data, context=MagicMock()
        )
        test_round.context.params.review_period_seconds = 60 * 60 * 24  # 1 day

        if should_review_bets:
            test_round.context.params.enable_position_review = True
            test_round.context.state.round_sequence.last_round_transition_timestamp = (
                datetime.now() - timedelta(seconds=10)
            )
            test_round.context.params.review_period_seconds = 10

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=get_participant_to_votes(
                    self.participants,
                    vote=vote,
                    review_bets_for_selling=should_review_bets,
                ),
                synchronized_data_update_fn=lambda _synchronized_data, _: _synchronized_data.update(
                    participant_to_votes=get_participant_to_votes_serialized(
                        self.participants,
                        vote=vote,
                        review_bets_for_selling=should_review_bets,
                    ),
                    review_bets_for_selling=should_review_bets,
                ),
                synchronized_data_attr_checks=[
                    lambda _synchronized_data: _synchronized_data.participant_to_votes.keys()
                ]
                if vote
                else [],
                exit_event=expected_event,
                threshold_check=threshold_check,
            )
        )

    def test_positive_votes(self) -> None:
        """Test ValidateRound for positive votes."""
        self._test_voting_round(
            vote=True,
            expected_event=self._event_class.SKIP_TRADING,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
        )

    def test_review_bets(self) -> None:
        """Test ValidateRound for review bets."""
        self._test_voting_round(
            vote=True,
            expected_event=self._event_class.REVIEW_BETS,
            threshold_check=lambda x: x.positive_vote_threshold_reached,
            should_review_bets=True,
        )

    def test_negative_votes(self) -> None:
        """Test ValidateRound for negative votes."""
        self._test_voting_round(
            vote=False,
            expected_event=self._event_class.DONE,
            threshold_check=lambda x: x.negative_vote_threshold_reached,
        )


class TestCheckStopTradingRound(BaseCheckStopTradingRoundTest):
    """Tests for CheckStopTradingRound."""

    test_class = CheckStopTradingRound
    _event_class = Event
    _synchronized_data_class = SynchronizedData

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.SKIP_TRADING,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_check_stop_trading_payload_serialized())
                    )
                ],
            ),
            RoundTestCase(
                name="Review bets for selling",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.REVIEW_BETS,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[
                    lambda sync_data: sync_data.db.get(
                        get_name(SynchronizedData.participant_to_votes)
                    )
                    == CollectionRound.deserialize_collection(
                        json.loads(get_dummy_check_stop_trading_payload_serialized())
                    )
                ],
            ),
            RoundTestCase(
                name="No majority",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=CheckStopTradingPayload,
                    data=get_dummy_check_stop_trading_payload_serialized(),
                ),
                final_data={},
                event=Event.NO_MAJORITY,
                most_voted_payload=get_dummy_check_stop_trading_payload_serialized(),
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""
        if test_case.event == Event.SKIP_TRADING:
            self.test_positive_votes()
        elif test_case.event == Event.REVIEW_BETS:
            self.test_review_bets()
        elif test_case.event == Event.NO_MAJORITY:
            self.test_negative_votes()

    """Tests for FinishedCheckStopTradingRound."""

    def test_finished_check_stop_trading_round_initialization(self) -> None:
        """Test the initialization of FinishedCheckStopTradingRound."""
        round_ = FinishedCheckStopTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedCheckStopTradingRound)


class TestFinishedWithSkipTradingRound:
    """Tests for FinishedWithSkipTradingRound."""

    def test_finished_with_skip_trading_round_initialization(self) -> None:
        """Test the initialization of FinishedWithSkipTradingRound."""
        round_ = FinishedWithSkipTradingRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedWithSkipTradingRound)


def test_abci_app_initialization(abci_app: CheckStopTradingAbciApp) -> None:
    """Test the initialization of CheckStopTradingAbciApp."""
    assert abci_app.initial_round_cls is CheckStopTradingRound
    assert abci_app.final_states == {
        FinishedCheckStopTradingRound,
        FinishedWithSkipTradingRound,
        FinishedWithReviewBetsRound,
    }
    assert abci_app.transition_function == {
        CheckStopTradingRound: {
            Event.DONE: FinishedCheckStopTradingRound,
            Event.REVIEW_BETS: FinishedWithReviewBetsRound,
            Event.NONE: CheckStopTradingRound,
            Event.ROUND_TIMEOUT: CheckStopTradingRound,
            Event.NO_MAJORITY: CheckStopTradingRound,
            Event.SKIP_TRADING: FinishedWithSkipTradingRound,
        },
        FinishedCheckStopTradingRound: {},
        FinishedWithSkipTradingRound: {},
        FinishedWithReviewBetsRound: {},
    }
    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
    assert abci_app.db_pre_conditions == {CheckStopTradingRound: set()}
    assert abci_app.db_post_conditions == {
        FinishedCheckStopTradingRound: set(),
        FinishedWithSkipTradingRound: set(),
        FinishedWithReviewBetsRound: set(),
    }


def test_synchronized_data_initialization() -> None:
    """Test the initialization and attributes of SynchronizedData."""
    data = SynchronizedData(db=AbciAppDB(setup_data={"test": ["test"]}))
    assert data.db._data == {0: {"test": ["test"]}}
