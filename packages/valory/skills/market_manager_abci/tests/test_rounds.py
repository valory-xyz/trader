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
    FetchMarketsRouterRound,
    FinishedMarketManagerRound,
    FinishedPolymarketFetchMarketRound,
    MarketManagerAbciApp,
    MarketManagerAbstractRound,
    PolymarketFetchMarketRound,
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
    assert abci_app.initial_round_cls is FetchMarketsRouterRound
    assert abci_app.final_states == {
        FinishedMarketManagerRound,
        FailedMarketManagerRound,
        FinishedPolymarketFetchMarketRound,
    }

    assert abci_app.transition_function == {
        FetchMarketsRouterRound: {
            Event.DONE: UpdateBetsRound,
            Event.NONE: FetchMarketsRouterRound,
            Event.NO_MAJORITY: FetchMarketsRouterRound,
            Event.POLYMARKET_FETCH_MARKETS: PolymarketFetchMarketRound,
        },
        PolymarketFetchMarketRound: {
            Event.DONE: FinishedPolymarketFetchMarketRound,
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.NO_MAJORITY: PolymarketFetchMarketRound,
            Event.ROUND_TIMEOUT: PolymarketFetchMarketRound,
        },
        UpdateBetsRound: {
            Event.DONE: FinishedMarketManagerRound,
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.NO_MAJORITY: UpdateBetsRound,
            Event.ROUND_TIMEOUT: UpdateBetsRound,
        },
        FinishedMarketManagerRound: {},
        FailedMarketManagerRound: {},
        FinishedPolymarketFetchMarketRound: {},
    }

    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
    assert abci_app.db_pre_conditions == {
        FetchMarketsRouterRound: set(),
        UpdateBetsRound: set(),
    }
    assert abci_app.db_post_conditions == {
        FinishedMarketManagerRound: {get_name(SynchronizedData.bets_hash)},
        FailedMarketManagerRound: set(),
        FinishedPolymarketFetchMarketRound: set(),
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


class TestSynchronizedDataProperties:
    """Tests for SynchronizedData property coverage in rounds.py."""

    def test_is_checkpoint_reached_default(self) -> None:
        """Test is_checkpoint_reached returns False when not set."""
        mock_db = MagicMock()
        mock_db.get.return_value = False
        synchronized_data = SynchronizedData(db=mock_db)
        assert synchronized_data.is_checkpoint_reached is False
        mock_db.get.assert_called_with("is_checkpoint_reached", False)

    def test_is_checkpoint_reached_true(self) -> None:
        """Test is_checkpoint_reached returns True when set."""
        mock_db = MagicMock()
        mock_db.get.return_value = True
        synchronized_data = SynchronizedData(db=mock_db)
        assert synchronized_data.is_checkpoint_reached is True

    def test_review_bets_for_selling_none(self) -> None:
        """Test review_bets_for_selling returns False when db value is None."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        synchronized_data = SynchronizedData(db=mock_db)
        assert synchronized_data.review_bets_for_selling is False

    def test_review_bets_for_selling_true(self) -> None:
        """Test review_bets_for_selling returns True when db value is True."""
        mock_db = MagicMock()
        mock_db.get.return_value = True
        synchronized_data = SynchronizedData(db=mock_db)
        assert synchronized_data.review_bets_for_selling is True

    def test_review_bets_for_selling_non_bool(self) -> None:
        """Test review_bets_for_selling returns False when db value is not bool."""
        mock_db = MagicMock()
        mock_db.get.return_value = "some_string"
        synchronized_data = SynchronizedData(db=mock_db)
        assert synchronized_data.review_bets_for_selling is False

    def test_review_bets_for_selling_false(self) -> None:
        """Test review_bets_for_selling returns False when db value is False."""
        mock_db = MagicMock()
        mock_db.get.return_value = False
        synchronized_data = SynchronizedData(db=mock_db)
        assert synchronized_data.review_bets_for_selling is False

    @patch(
        "packages.valory.skills.market_manager_abci.rounds.CollectionRound.deserialize_collection"
    )
    def test_participant_to_selection(
        self, mock_deserialize: MagicMock
    ) -> None:
        """Test participant_to_selection property calls _get_deserialized."""
        mock_db = MagicMock()
        mock_db.get_strict.return_value = '{"agent_0": "selection_0"}'
        expected = {"agent_0": "selection_0"}
        mock_deserialize.return_value = expected
        synchronized_data = SynchronizedData(db=mock_db)
        result = synchronized_data.participant_to_selection
        mock_db.get_strict.assert_called_once_with("participant_to_selection")
        mock_deserialize.assert_called_once_with('{"agent_0": "selection_0"}')
        assert result == expected


class _ConcreteMarketManagerRound(MarketManagerAbstractRound):
    """Concrete subclass of MarketManagerAbstractRound from rounds.py for testing."""

    payload_class = UpdateBetsPayload
    synchronized_data_class = SynchronizedData

    def end_block(self):  # type: ignore
        """End block stub."""
        return None

    def check_payload(self, payload):  # type: ignore
        """Check payload stub."""
        return None

    def process_payload(self, payload):  # type: ignore
        """Process payload stub."""
        return None


class TestMarketManagerAbstractRound:
    """Tests for MarketManagerAbstractRound in rounds.py."""

    def test_synchronized_data_property(self) -> None:
        """Test that the synchronized_data property returns a SynchronizedData instance."""
        mock_sync_data = MagicMock(spec=SynchronizedData)
        round_instance = _ConcreteMarketManagerRound(
            synchronized_data=mock_sync_data, context=MagicMock()
        )
        result = round_instance.synchronized_data
        assert result is mock_sync_data

    def test_return_no_majority_event(self) -> None:
        """Test the _return_no_majority_event method."""
        mock_sync_data = MagicMock(spec=SynchronizedData)
        round_instance = _ConcreteMarketManagerRound(
            synchronized_data=mock_sync_data, context=MagicMock()
        )
        result = round_instance._return_no_majority_event()
        assert result == (mock_sync_data, Event.NO_MAJORITY)


# ============================================================================
# Tests for states/base.py SynchronizedData (covers lines 53-54, 64, 69, 74-77, 82)
# ============================================================================
from packages.valory.skills.market_manager_abci.states.base import (
    SynchronizedData as BaseSynchronizedData_States,
)
from packages.valory.skills.market_manager_abci.states.base import (
    MarketManagerAbstractRound as BaseMarketManagerAbstractRound,
)


class TestStatesBaseSynchronizedData:
    """Tests for SynchronizedData from states/base.py."""

    @patch(
        "packages.valory.skills.market_manager_abci.states.base.CollectionRound.deserialize_collection"
    )
    def test_get_deserialized(self, mock_deserialize: MagicMock) -> None:
        """Test _get_deserialized calls db.get_strict and deserialize_collection."""
        mock_db = MagicMock()
        mock_db.get_strict.return_value = '{"key": "value"}'
        expected = {"key": "value"}
        mock_deserialize.return_value = expected
        sd = BaseSynchronizedData_States(db=mock_db)
        result = sd._get_deserialized("some_key")
        mock_db.get_strict.assert_called_once_with("some_key")
        mock_deserialize.assert_called_once_with('{"key": "value"}')
        assert result == expected

    def test_bets_hash(self) -> None:
        """Test bets_hash property."""
        mock_db = MagicMock()
        mock_db.get_strict.return_value = "test_hash"
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.bets_hash == "test_hash"
        mock_db.get_strict.assert_called_once_with("bets_hash")

    @patch(
        "packages.valory.skills.market_manager_abci.states.base.CollectionRound.deserialize_collection"
    )
    def test_participant_to_bets_hash(
        self, mock_deserialize: MagicMock
    ) -> None:
        """Test participant_to_bets_hash property."""
        mock_db = MagicMock()
        mock_db.get_strict.return_value = '{"a": "b"}'
        expected = {"a": "b"}
        mock_deserialize.return_value = expected
        sd = BaseSynchronizedData_States(db=mock_db)
        result = sd.participant_to_bets_hash
        mock_db.get_strict.assert_called_once_with("participant_to_bets_hash")
        assert result == expected

    def test_is_checkpoint_reached_default(self) -> None:
        """Test is_checkpoint_reached returns False by default."""
        mock_db = MagicMock()
        mock_db.get.return_value = False
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.is_checkpoint_reached is False

    def test_is_checkpoint_reached_true(self) -> None:
        """Test is_checkpoint_reached returns True when set."""
        mock_db = MagicMock()
        mock_db.get.return_value = True
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.is_checkpoint_reached is True

    def test_review_bets_for_selling_none(self) -> None:
        """Test review_bets_for_selling returns False when None."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.review_bets_for_selling is False

    def test_review_bets_for_selling_true(self) -> None:
        """Test review_bets_for_selling returns True when True."""
        mock_db = MagicMock()
        mock_db.get.return_value = True
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.review_bets_for_selling is True

    def test_review_bets_for_selling_non_bool(self) -> None:
        """Test review_bets_for_selling returns False for non-bool value."""
        mock_db = MagicMock()
        mock_db.get.return_value = 42
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.review_bets_for_selling is False

    def test_review_bets_for_selling_false(self) -> None:
        """Test review_bets_for_selling returns False when False."""
        mock_db = MagicMock()
        mock_db.get.return_value = False
        sd = BaseSynchronizedData_States(db=mock_db)
        assert sd.review_bets_for_selling is False

    @patch(
        "packages.valory.skills.market_manager_abci.states.base.CollectionRound.deserialize_collection"
    )
    def test_participant_to_selection(
        self, mock_deserialize: MagicMock
    ) -> None:
        """Test participant_to_selection property."""
        mock_db = MagicMock()
        mock_db.get_strict.return_value = '{"agent_0": "sel"}'
        expected = {"agent_0": "sel"}
        mock_deserialize.return_value = expected
        sd = BaseSynchronizedData_States(db=mock_db)
        result = sd.participant_to_selection
        mock_db.get_strict.assert_called_once_with("participant_to_selection")
        assert result == expected


class TestStatesBaseMarketManagerAbstractRound:
    """Tests for MarketManagerAbstractRound from states/base.py."""

    def test_synchronized_data_property(self) -> None:
        """Test the synchronized_data property returns cast SynchronizedData."""
        mock_sync_data = MagicMock(spec=BaseSynchronizedData_States)
        # UpdateBetsRound inherits from MarketManagerAbstractRound
        round_instance = UpdateBetsRound(
            synchronized_data=mock_sync_data, context=MagicMock()
        )
        result = round_instance.synchronized_data
        assert result is mock_sync_data

    def test_return_no_majority_event(self) -> None:
        """Test _return_no_majority_event returns data and NO_MAJORITY."""
        mock_sync_data = MagicMock(spec=BaseSynchronizedData_States)
        round_instance = UpdateBetsRound(
            synchronized_data=mock_sync_data, context=MagicMock()
        )
        data, event = round_instance._return_no_majority_event()
        assert data is mock_sync_data
        assert event == Event.NO_MAJORITY


# ============================================================================
# Tests for states/fetch_markets_router.py FetchMarketsRouterRound.end_block
# ============================================================================


class TestFetchMarketsRouterRoundEndBlock:
    """Tests for FetchMarketsRouterRound.end_block."""

    def test_end_block_super_returns_none(self) -> None:
        """Test end_block returns None when super().end_block() returns None."""
        mock_sync_data = MagicMock(spec=SynchronizedData)
        mock_context = MagicMock()
        round_instance = FetchMarketsRouterRound(
            synchronized_data=mock_sync_data, context=mock_context
        )
        with patch(
            "packages.valory.skills.abstract_round_abci.base.VotingRound.end_block",
            return_value=None,
        ):
            result = round_instance.end_block()
        assert result is None

    def test_end_block_polymarket(self) -> None:
        """Test end_block returns POLYMARKET_FETCH_MARKETS when is_running_on_polymarket is True."""
        mock_sync_data = MagicMock(spec=SynchronizedData)
        mock_context = MagicMock()
        mock_context.params.is_running_on_polymarket = True
        round_instance = FetchMarketsRouterRound(
            synchronized_data=mock_sync_data, context=mock_context
        )
        super_result = (MagicMock(spec=SynchronizedData), Event.DONE)
        with patch(
            "packages.valory.skills.abstract_round_abci.base.VotingRound.end_block",
            return_value=super_result,
        ):
            result = round_instance.end_block()
        assert result is not None
        returned_data, returned_event = result
        assert returned_event == Event.POLYMARKET_FETCH_MARKETS

    def test_end_block_not_polymarket(self) -> None:
        """Test end_block returns DONE when is_running_on_polymarket is False."""
        mock_sync_data = MagicMock(spec=SynchronizedData)
        mock_context = MagicMock()
        mock_context.params.is_running_on_polymarket = False
        round_instance = FetchMarketsRouterRound(
            synchronized_data=mock_sync_data, context=mock_context
        )
        super_result = (MagicMock(spec=SynchronizedData), Event.DONE)
        with patch(
            "packages.valory.skills.abstract_round_abci.base.VotingRound.end_block",
            return_value=super_result,
        ):
            result = round_instance.end_block()
        assert result is not None
        returned_data, returned_event = result
        assert returned_event == Event.DONE


# ============================================================================
# Tests for states/final_states.py
# ============================================================================
from packages.valory.skills.market_manager_abci.states.final_states import (
    FailedMarketManagerRound as FinalFailedMarketManagerRound,
)
from packages.valory.skills.market_manager_abci.states.final_states import (
    FinishedMarketManagerRound as FinalFinishedMarketManagerRound,
)
from packages.valory.skills.market_manager_abci.states.final_states import (
    FinishedPolymarketFetchMarketRound as FinalFinishedPolymarketFetchMarketRound,
)


class TestFinalStates:
    """Tests for states/final_states.py classes."""

    def test_finished_market_manager_round_exists(self) -> None:
        """Test that FinishedMarketManagerRound exists and is a DegenerateRound subclass."""
        from packages.valory.skills.abstract_round_abci.base import DegenerateRound

        assert issubclass(FinalFinishedMarketManagerRound, DegenerateRound)

    def test_failed_market_manager_round_exists(self) -> None:
        """Test that FailedMarketManagerRound exists and is a DegenerateRound subclass."""
        from packages.valory.skills.abstract_round_abci.base import DegenerateRound

        assert issubclass(FinalFailedMarketManagerRound, DegenerateRound)

    def test_finished_polymarket_fetch_market_round_exists(self) -> None:
        """Test that FinishedPolymarketFetchMarketRound exists and is a DegenerateRound subclass."""
        from packages.valory.skills.abstract_round_abci.base import DegenerateRound

        assert issubclass(FinalFinishedPolymarketFetchMarketRound, DegenerateRound)

    def test_finished_market_manager_round_initialization(self) -> None:
        """Test FinishedMarketManagerRound can be instantiated."""
        round_ = FinalFinishedMarketManagerRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinalFinishedMarketManagerRound)

    def test_failed_market_manager_round_initialization(self) -> None:
        """Test FailedMarketManagerRound can be instantiated."""
        round_ = FinalFailedMarketManagerRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinalFailedMarketManagerRound)

    def test_finished_polymarket_fetch_market_round_initialization(self) -> None:
        """Test FinishedPolymarketFetchMarketRound can be instantiated."""
        round_ = FinalFinishedPolymarketFetchMarketRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinalFinishedPolymarketFetchMarketRound)
