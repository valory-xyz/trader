import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, List, Mapping, Optional
from unittest import mock
from unittest.mock import MagicMock

import pytest
from packages.valory.skills.abstract_round_abci.base import (
    AbciAppDB,
    get_name,
)

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.test_tools.rounds import (
    BaseCollectSameUntilThresholdRoundTest,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import (
    Event,
    SynchronizedData,
    UpdateBetsRound,
    FinishedMarketManagerRound,
    FailedMarketManagerRound,
    MarketManagerAbciApp
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
        synchronized_data=synchronized_data,
        logger=logger,
        context=context
    )

DUMMY_BETS_HASH = "dummy_bets_hash"
DUMMY_PARTICIPANT_TO_BETS_HASH = json.dumps({
    "agent_0": "bet_1",
    "agent_1": "bet_2",
    "agent_2": "bet_3",
})


def get_participants() -> FrozenSet[str]:
    """Participants"""
    return frozenset([f"agent_{i}" for i in range(MAX_PARTICIPANTS)])


def get_payloads(
    payload_cls: BaseTxPayload,
    data: Optional[str],
) -> Mapping[str, BaseTxPayload]:
    """Get payloads."""
    return {
        participant: payload_cls(participant, data)
        for participant in get_participants()
    }


def get_dummy_update_bets_payload_serialized() -> str:
    """Dummy update bets payload"""
    return json.dumps(
        {
            "bets_hash": DUMMY_BETS_HASH,
        },
        sort_keys=True,
    )


def get_dummy_update_bets_payload_error_serialized() -> str:
    """Dummy update bets payload error"""
    return json.dumps({"error": True}, sort_keys=True)


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

    def run_test(self, test_case: RoundTestCase, **kwargs: Any) -> None:
        """Run the test"""

        # Set initial data
        self.synchronized_data.update(**test_case.initial_data)

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
                    payload_cls=UpdateBetsPayload,
                    data=DUMMY_BETS_HASH,
                ),
                final_data={
                    "bets_hash": DUMMY_BETS_HASH,
                },
                event=Event.DONE,
                most_voted_payload=DUMMY_BETS_HASH,
                synchronized_data_attr_checks=[
                    lambda synchronized_data: synchronized_data.bets_hash == DUMMY_BETS_HASH,
                ],
            ),
            RoundTestCase(
                name="Fetch error",
                initial_data={},
                payloads=get_payloads(
                    payload_cls=UpdateBetsPayload,
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

def test_synchronized_data_initialization() -> None:
    """Test the initialization and attributes of SynchronizedData."""
    data = SynchronizedData(db=AbciAppDB(setup_data={"test": ["test"]}))
    assert data.db._data == {0: {"test": ["test"]}}
