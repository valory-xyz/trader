# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains the test for rounds for the MarketManager ABCI application."""

import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Hashable,
    List,
    Mapping,
    Optional,
    Union,
)
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    BaseTxPayload,
    get_name,
)
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import (
    Event,
    FailedMarketManagerRound,
    FinishedMarketManagerRound,
    MarketManagerAbciApp,
    SynchronizedData,
    UpdateBetsRound,
)


@pytest.fixture
def abci_app() -> MarketManagerAbciApp:
    """Fixture for MarketManagerAbciApp."""
    # Create mocks for the required parameters
    synchronized_data = MagicMock()
    logger = MagicMock()
    context = MagicMock()

    # Instantiate MarketManagerAbciApp with the required arguments
    return MarketManagerAbciApp(
        synchronized_data=synchronized_data, logger=logger, context=context
    )


DUMMY_BETS_HASH = "dummy_bets_hash"
DUMMY_PARTICIPANT_TO_BETS_HASH = json.dumps(
    {
        "agent_0": "bet_1",
        "agent_1": "bet_2",
        "agent_2": "bet_3",
    }
)


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_payloads(
    data: Optional[str],
) -> Mapping[str, BaseTxPayload]:
    """Get payloads."""
    return {
        participant: UpdateBetsPayload(participant, data)
        for participant in get_participants()
    }


@dataclass
class RoundTestCase:
    """RoundTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    payloads: Mapping[str, BaseTxPayload]
    final_data: Dict[str, Hashable]
    event: Event
    most_voted_payload: Any
    synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


MAX_PARTICIPANTS: int = 4


class BaseMarketManagerRoundTestClass(BaseCollectSameUntilThresholdRoundTest):
    """Base test class for MarketManager rounds."""

    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event
    round_class = UpdateBetsRound

    def run_test(self, test_case: RoundTestCase) -> None:
        """Run the test"""

        # Set initial data
        self.synchronized_data.update(
            self._synchronized_data_class, **test_case.initial_data
        )

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
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
        )


class TestUpdateBetsRound(BaseMarketManagerRoundTestClass):
    """Tests for UpdateBetsRound."""

    round_class = UpdateBetsRound
    synchronized_data: SynchronizedData
    _synchronized_data_class = SynchronizedData
    _event_class = Event

    @pytest.mark.parametrize(
        "test_case",
        (
            RoundTestCase(
                name="Happy path",
                initial_data={},
                payloads=get_payloads(
                    data=DUMMY_BETS_HASH,
                ),
                final_data={
                    "bets_hash": DUMMY_BETS_HASH,
                    "participant_to_bets_hash": DUMMY_PARTICIPANT_TO_BETS_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_BETS_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.bets_hash,
                ],
            ),
            RoundTestCase(
                name="Fetch error",
                initial_data={},
                payloads=get_payloads(
                    data=None,
                ),
                final_data={},
                event=Event.FETCH_ERROR,
                most_voted_payload=None,
                synchronized_data_attr_checks=[],
            ),
        ),
    )
    def test_run(self, test_case: RoundTestCase) -> None:
        """Run tests."""

        self.run_test(test_case)

    def test_return_no_majority_event(self) -> None:
        """Test the _return_no_majority_event method."""
        # Mock synchronized data and create an instance of the round
        synchronized_data = MagicMock(spec=SynchronizedData)
        update_bets_round = UpdateBetsRound(
            synchronized_data=synchronized_data, context=MagicMock()
        )

        # Call the method and check the results
        result = update_bets_round._return_no_majority_event()
        assert result == (synchronized_data, Event.NO_MAJORITY)


class TestFinishedMarketManagerRound:
    """Tests for FinishedMarketManagerRound."""

    def test_finished_market_manager_round_initialization(self) -> None:
        """Test the initialization of FinishedMarketManagerRound."""
        round_ = FinishedMarketManagerRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedMarketManagerRound)


class TestFailedMarketManagerRound:
    """Tests for FailedMarketManagerRound."""

    def test_failed_market_manager_round_initialization(self) -> None:
        """Test the initialization of FailedMarketManagerRound."""
        round_ = FailedMarketManagerRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FailedMarketManagerRound)


def test_market_manager_abci_app_initialization(abci_app: MarketManagerAbciApp) -> None:
    """Test the initialization of MarketManagerAbciApp."""
    assert abci_app.initial_round_cls is UpdateBetsRound
    assert abci_app.final_states == {
        FinishedMarketManagerRound,
        FailedMarketManagerRound,
    }
    assert abci_app.transition_function == {
        UpdateBetsRound: {
            Event.DONE: FinishedMarketManagerRound,
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.ROUND_TIMEOUT: UpdateBetsRound,
            Event.NO_MAJORITY: UpdateBetsRound,
        },
        FinishedMarketManagerRound: {},
        FailedMarketManagerRound: {},
    }
    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
    assert abci_app.db_pre_conditions == {UpdateBetsRound: set()}
    assert abci_app.db_post_conditions == {
        FinishedMarketManagerRound: {get_name(SynchronizedData.bets_hash)},
        FailedMarketManagerRound: set(),
    }


# Mock serialized collections for different keys
DUMMY_PARTICIPANT_TO_BETS_HASH = json.dumps(
    {
        "agent_0": {"sender": "agent_0", "data": "bet_1"},
        "agent_1": {"sender": "agent_1", "data": "bet_2"},
    }
)
DUMMY_BETS_HASH = json.dumps({"bets_hash": "dummy_bets_hash"})

DUMMY_SERIALIZED_PARTICIPANT_TO_BETS_HASH = json.dumps(DUMMY_PARTICIPANT_TO_BETS_HASH)
DUMMY_SERIALIZED_BETS_HASH = json.dumps(DUMMY_BETS_HASH)


@pytest.mark.parametrize(
    "key,serialized_data,expected_result,property_to_check",
    [
        (
            "participant_to_bets_hash",
            DUMMY_SERIALIZED_PARTICIPANT_TO_BETS_HASH,
            json.loads(DUMMY_PARTICIPANT_TO_BETS_HASH),
            "participant_to_bets_hash",
        ),
        (
            "bets_hash",
            DUMMY_SERIALIZED_BETS_HASH,
            json.loads(DUMMY_BETS_HASH),
            "bets_hash",
        ),
    ],
)
@patch(
    "packages.valory.skills.market_manager_abci.rounds.CollectionRound.deserialize_collection"
)
def test_synchronized_data_get_deserialized(
    mock_deserialize_collection: MagicMock,
    key: str,
    serialized_data: str,
    expected_result: Mapping[str, Any],
    property_to_check: str,
) -> None:
    """Test the _get_deserialized method and properties in SynchronizedData."""
    # Mock the db.get_strict to return the serialized data
    mock_db = mock.MagicMock()
    mock_db.get_strict.return_value = serialized_data

    # Initialize SynchronizedData with the mocked db
    synchronized_data = SynchronizedData(db=mock_db)

    # Mock the deserialize_collection function to return the expected deserialized result
    mock_deserialize_collection.return_value = expected_result

    deserialized_data: Union[str, Mapping[str, BaseTxPayload]]
    if property_to_check == "participant_to_bets_hash":
        deserialized_data = synchronized_data.participant_to_bets_hash
    else:
        deserialized_data = synchronized_data.bets_hash

    # Ensure that get_strict is called with the correct key
    mock_db.get_strict.assert_called_once_with(key)

    # Ensure that deserialize_collection is called with the correct serialized data only for collection fields
    if property_to_check == "participant_to_bets_hash":
        mock_deserialize_collection.assert_called_once_with(serialized_data)
        assert deserialized_data == expected_result


def test_synchronized_data_initialization() -> None:
    """Test the initialization and attributes of SynchronizedData."""
    setup_data = {"test": ["test"]}
    synchronized_data = SynchronizedData(db=AbciAppDB(setup_data=setup_data))

    assert synchronized_data.db._data == {0: {"test": ["test"]}}
