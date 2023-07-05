# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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
    get_name,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload


class Event(Enum):
    """Event enumeration for the MarketManager demo."""

    DONE = "done"
    NONE = "none"
    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    FETCH_ERROR = "fetch_error"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    def _get_deserialized(self, key: str) -> DeserializedCollection:
        """Strictly get a collection and return it deserialized."""
        serialized = self.db.get_strict(key)
        return CollectionRound.deserialize_collection(serialized)

    @property
    def fetch_succeeded(self) -> bool:
        """Get the most voted bets."""
        return bool(self.db.get_strict("fetch_succeeded"))

    @property
    def bets_hash(self) -> str:
        """Get the most voted bets."""
        return str(self.db.get_strict("bets_hash"))

    @property
    def participant_to_bets(self) -> DeserializedCollection:
        """Get the participants to bets."""
        return self._get_deserialized("participant_to_bets")


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


class UpdateBetsRound(CollectSameUntilThresholdRound, MarketManagerAbstractRound):
    """A round for the bets fetching & updating."""

    payload_class = UpdateBetsPayload
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key = (
        get_name(SynchronizedData.fetch_succeeded),
        get_name(SynchronizedData.bets_hash),
    )
    collection_key = get_name(SynchronizedData.participant_to_bets)
    synchronized_data_class = SynchronizedData

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Event], res)
        if event == self.done_event and not synced_data.fetch_succeeded:
            event = Event.FETCH_ERROR
        return synced_data, event


class FinishedMarketManagerRound(DegenerateRound, ABC):
    """A round that represents MarketManager has finished"""


class FailedMarketManagerRound(DegenerateRound, ABC):
    """A round that represents that the period failed"""


class MarketManagerAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """MarketManagerAbciApp"""

    initial_round_cls: Type[AbstractRound] = UpdateBetsRound
    transition_function: AbciAppTransitionFunction = {
        UpdateBetsRound: {
            Event.DONE: FinishedMarketManagerRound,
            Event.NONE: FailedMarketManagerRound,  # cannot occur as the payload's fields do not accept `None` values
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.ROUND_TIMEOUT: UpdateBetsRound,
            Event.NO_MAJORITY: UpdateBetsRound,
        },
        FinishedMarketManagerRound: {},
        FailedMarketManagerRound: {},
    }
    cross_period_persisted_keys = frozenset()
    final_states: Set[AppState] = {FinishedMarketManagerRound, FailedMarketManagerRound}
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {UpdateBetsRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedMarketManagerRound: set(),
        FailedMarketManagerRound: set(),
    }
