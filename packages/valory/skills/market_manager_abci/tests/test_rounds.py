import pytest
from unittest import mock
from typing import Dict, Any, Callable, Set
from packages.valory.skills.market_manager_abci.rounds import (
    UpdateBetsRound,
    FinishedMarketManagerRound,
    FailedMarketManagerRound,
    SynchronizedData,
    MarketManagerAbciApp,
    Event
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    CollectionRound,
    DegenerateRound,
    DeserializedCollection,
    get_name,
)

    
    

@pytest.fixture
def synchronized_data():
    """Fixture to provide a mocked SynchronizedData instance."""
    db = {
        "participant_to_bets_hash": {},
        "bets_hash": "initial_hash"
    }
    return MockSynchronizedData(db)

@pytest.fixture
def abci_app():
    """Fixture to get the ABCI app with necessary parameters."""
    synchronized_data = mock.MagicMock()
    logger = mock.MagicMock()
    context = mock.MagicMock()
    return MarketManagerAbciApp(synchronized_data=synchronized_data, logger=logger, context=context)

class BaseMarketManagerRoundTestClass:
    """Base test class for MarketManager rounds."""

    synchronized_data: SynchronizedData
    round_class = UpdateBetsRound
    synchronized_data= SynchronizedData
    _event_class = Event

    def setup_method(self):
        """Setup method to initialize synchronized_data"""
        self.synchronized_data= SynchronizedData(db=dict())

    def _complete_run(self, test_func: Callable[[], None]) -> None:
        """Complete the run of the test."""
        test_func()

    def _test_round(
        self,
        test_round: UpdateBetsRound,
        round_payloads: list,
        synchronized_data_update_fn: Callable[[SynchronizedData, Any], None],
        synchronized_data_attr_checks: Dict[str, Any],
        most_voted_payload: UpdateBetsPayload,
        exit_event: Event,
    ) -> None:
        """Test the round processing."""
        for payload in round_payloads:
            test_round.process_payload(payload)

        synchronized_data_update_fn(self.synchronized_data, most_voted_payload)

        for attr, expected_value in synchronized_data_attr_checks.items():
            assert getattr(self.synchronized_data, attr) == expected_value

        assert test_round.event == exit_event

    def run_test(self, test_case: Dict[str, Any], **kwargs: Any) -> None:
        """Run the test using the provided test case."""
        self.synchronized_data.update(**test_case["initial_data"])

        test_round = self.round_class(
            synchronized_data=self.synchronized_data, context=mock.MagicMock()
        )

        self._complete_run(
            self._test_round(
                test_round=test_round,
                round_payloads=test_case["payloads"],
                synchronized_data_update_fn=lambda sync_data, _: sync_data.update(
                    **test_case["final_data"]
                ),
                synchronized_data_attr_checks=test_case["synchronized_data_attr_checks"],
                most_voted_payload=test_case["most_voted_payload"],
                exit_event=test_case["event"],
            )
        )

 

class TestUpdateBetsRound(BaseMarketManagerRoundTestClass):
    """Test UpdateBetsRound execution."""

    def test_update_bets_round_execution(self):
        """Test the execution of UpdateBetsRound."""
        test_case = {
            "initial_data": {"participant_to_bets_hash": {}, "bets_hash": "initial_hash"},
            "payloads": [UpdateBetsPayload("agent_0", "dummy_payload")],
            "final_data": {"participant_to_bets_hash": {"agent_0": "new_bets"}, "bets_hash": "new_hash"},
            "synchronized_data_attr_checks": {"bets_hash": "new_hash"},
            "most_voted_payload": UpdateBetsPayload("agent_0", "dummy_payload"),
            "event": Event.DONE
        }
        self.run_test(test_case)

class TestUpdateBetsRoundFetchError(BaseMarketManagerRoundTestClass):
    """Test UpdateBetsRound fetch error handling."""

    def test_update_bets_round_fetch_error(self):
        """Test the UpdateBetsRound when a fetch error occurs."""
        test_case = {
            "initial_data": {"participant_to_bets_hash": {}, "bets_hash": "initial_hash"},
            "payloads": [],
            "final_data": {"participant_to_bets_hash": {}, "bets_hash": "initial_hash"},
            "synchronized_data_attr_checks": {"bets_hash": "initial_hash"},
            "most_voted_payload": None,
            "event": Event.FETCH_ERROR
        }
        self.run_test(test_case)

class TestMarketManagerAppTransitions:
    """Test the transitions in MarketManagerAbciApp."""

    def test_update_bets_round_transition(self, abci_app):
        """Test the transitions from UpdateBetsRound."""
        current_state = UpdateBetsRound
        event = Event.DONE
        next_state = abci_app.transition_function[current_state][event]
        assert next_state == FinishedMarketManagerRound

        event = Event.FETCH_ERROR
        next_state = abci_app.transition_function[current_state][event]
        assert next_state == FailedMarketManagerRound

        event = Event.ROUND_TIMEOUT
        next_state = abci_app.transition_function[current_state][event]
        assert next_state == UpdateBetsRound

        event = Event.NO_MAJORITY
        next_state = abci_app.transition_function[current_state][event]
        assert next_state == UpdateBetsRound

    def test_final_states(self, abci_app):
        """Test that final states are correctly configured."""
        assert abci_app.final_states == {FinishedMarketManagerRound, FailedMarketManagerRound}

    def test_event_to_timeout(self, abci_app):
        """Test the event to timeout mapping."""
        assert abci_app.event_to_timeout == {
            Event.ROUND_TIMEOUT: 30.0,
        }

    def test_db_pre_conditions(self, abci_app):
        """Test the db_pre_conditions configuration."""
        assert abci_app.db_pre_conditions == {UpdateBetsRound: set()}

    def test_db_post_conditions(self, abci_app):
        """Test the db_post_conditions configuration."""
        assert abci_app.db_post_conditions == {
            FinishedMarketManagerRound: {get_name(SynchronizedData.bets_hash)},
            FailedMarketManagerRound: set(),
        }
    
    

