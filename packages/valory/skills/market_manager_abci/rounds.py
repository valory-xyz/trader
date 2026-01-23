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

"""This module contains the rounds for the MarketManager ABCI application."""

from abc import ABC
from enum import Enum
from typing import Dict, Optional, Set, Tuple, Type, cast

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
    VotingRound,
    get_name,
)
from packages.valory.skills.market_manager_abci.payloads import (
    FetchMarketsRouterPayload,
    UpdateBetsPayload,
)
from packages.valory.skills.market_manager_abci.states.fetch_markets_router import (
    FetchMarketsRouterRound,
)
from packages.valory.skills.market_manager_abci.states.polymarket_fetch_market import (
    PolymarketFetchMarketRound,
)
from packages.valory.skills.market_manager_abci.states.update_bets import (
    UpdateBetsRound,
)


class Event(Enum):
    """Event enumeration for the MarketManager demo."""

    DONE = "done"
    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    FETCH_ERROR = "fetch_error"
    POLYMARKET_FETCH_MARKETS = "polymarket_fetch_markets"
    NONE = "none"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    def _get_deserialized(self, key: str) -> DeserializedCollection:
        """Strictly get a collection and return it deserialized."""
        serialized = self.db.get_strict(key)
        return CollectionRound.deserialize_collection(serialized)

    @property
    def bets_hash(self) -> str:
        """Get the most voted bets' hash."""
        return str(self.db.get_strict("bets_hash"))

    @property
    def participant_to_bets_hash(self) -> DeserializedCollection:
        """Get the participants to bets' hash."""
        return self._get_deserialized("participant_to_bets_hash")

    @property
    def is_checkpoint_reached(self) -> bool:
        """Check if the checkpoint is reached."""
        return bool(self.db.get("is_checkpoint_reached", False))

    @property
    def review_bets_for_selling(self) -> bool:
        """Get the status of the review bets for selling."""
        db_value = self.db.get("review_bets_for_selling", None)
        if not isinstance(db_value, bool):
            return False
        return bool(db_value)

    @property
    def participant_to_selection(self) -> DeserializedCollection:
        """Get the participants to selection."""
        return self._get_deserialized("participant_to_selection")


class MarketManagerAbstractRound(AbstractRound[Event], ABC):
    """Abstract round for the MarketManager skill."""

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    def _return_no_majority_event(self) -> Tuple[SynchronizedData, Event]:
        """
        Trigger the `NO_MAJORITY` event.

        :return: the new synchronized data and a `NO_MAJORITY` event
        """
        return self.synchronized_data, Event.NO_MAJORITY


class FinishedMarketManagerRound(DegenerateRound, ABC):
    """A round that represents MarketManager has finished"""


class FailedMarketManagerRound(DegenerateRound, ABC):
    """A round that represents that the period failed"""


class FinishedFetchMarketsRouterRound(DegenerateRound, ABC):
    """A round representing that fetch markets router has finished."""


class FinishedPolymarketFetchMarketRound(DegenerateRound, ABC):
    """A round representing that Polymarket fetch market has finished."""


class MarketManagerAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """MarketManagerAbciApp

    Initial round: FetchMarketsRouterRound

    Initial states: {FetchMarketsRouterRound, UpdateBetsRound}

    Transition states:
        0. FetchMarketsRouterRound
            - done: 5.
            - polymarket fetch markets: 2.
            - no majority: 0.
            - none: 0.
        1. UpdateBetsRound
            - done: 3.
            - fetch error: 4.
            - round timeout: 1.
            - no majority: 1.
        2. PolymarketFetchMarketRound
            - done: 6.
            - fetch error: 4.
            - no majority: 2.
            - round timeout: 2.
        3. FinishedMarketManagerRound
        4. FailedMarketManagerRound
        5. FinishedFetchMarketsRouterRound
        6. FinishedPolymarketFetchMarketRound

    Final states: {FailedMarketManagerRound, FinishedFetchMarketsRouterRound, FinishedMarketManagerRound, FinishedPolymarketFetchMarketRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = FetchMarketsRouterRound
    initial_states: Set[AppState] = {
        FetchMarketsRouterRound,
        UpdateBetsRound,
    }
    transition_function: AbciAppTransitionFunction = {
        FetchMarketsRouterRound: {
            Event.DONE: FinishedFetchMarketsRouterRound,  # Routes to UpdateBetsRound via composition
            Event.POLYMARKET_FETCH_MARKETS: PolymarketFetchMarketRound,  # Routes internally to PolymarketFetchMarketRound
            Event.NO_MAJORITY: FetchMarketsRouterRound,
            Event.NONE: FetchMarketsRouterRound,
        },
        UpdateBetsRound: {
            Event.DONE: FinishedMarketManagerRound,
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.ROUND_TIMEOUT: UpdateBetsRound,
            Event.NO_MAJORITY: UpdateBetsRound,
        },
        PolymarketFetchMarketRound: {
            Event.DONE: FinishedPolymarketFetchMarketRound,
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.NO_MAJORITY: PolymarketFetchMarketRound,
            Event.ROUND_TIMEOUT: PolymarketFetchMarketRound,
        },
        FinishedMarketManagerRound: {},
        FailedMarketManagerRound: {},
        FinishedFetchMarketsRouterRound: {},
        FinishedPolymarketFetchMarketRound: {},
    }
    cross_period_persisted_keys = frozenset({get_name(SynchronizedData.bets_hash)})
    final_states: Set[AppState] = {
        FinishedMarketManagerRound,
        FailedMarketManagerRound,
        FinishedPolymarketFetchMarketRound,
        FinishedFetchMarketsRouterRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {
        UpdateBetsRound: set(),
        FetchMarketsRouterRound: set(),
    }
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedMarketManagerRound: {get_name(SynchronizedData.bets_hash)},
        FailedMarketManagerRound: set(),
        FinishedFetchMarketsRouterRound: set(),
        FinishedPolymarketFetchMarketRound: set(),
    }
