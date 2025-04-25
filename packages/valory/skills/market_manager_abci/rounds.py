# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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
from typing import Any, Dict, Optional, Set, Tuple, Type, cast

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
from packages.valory.skills.market_manager_abci.payloads import (
    BaseUpdateBetsPayload,
    UpdateBetsPayload,
)


class Event(Enum):
    """Event enumeration for the MarketManager demo."""

    DONE = "done"
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
    def wallet_balance(self) -> int:
        """Get the wallet balance."""
        wallet_balance = self.db.get("wallet_balance", 0)
        if wallet_balance is None:
            return 0
        return int(wallet_balance)

    @property
    def token_balance(self) -> int:
        """Get the wallet balance."""
        token_balance = self.db.get("token_balance", 0)
        if token_balance is None:
            return 0
        return int(token_balance)

    @property
    def olas_balance(self) -> int:
        """Get the wallet balance."""
        olas_balance = self.db.get("olas_balance", 0)
        if olas_balance is None:
            return 0
        return int(olas_balance)

    @property
    def sampled_bet_index(self) -> int:
        """Get the sampled bet."""
        sampled_bet_index = self.db.get("sampled_bet_index", 0)
        if sampled_bet_index is None:
            return 0
        return int(sampled_bet_index)

    @property
    def service_owner_address(self) -> Optional[str]:
        """Get the service owner address."""
        service_owner_address = self.db.get("service_owner_address", None)
        if service_owner_address is None:
            return None
        return str(service_owner_address)


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


class BaseUpdateBetsRound(CollectSameUntilThresholdRound, MarketManagerAbstractRound):
    """A round for the bets fetching & updating."""

    payload_class = BaseUpdateBetsPayload
    done_event: Enum = Event.DONE
    none_event: Enum = Event.FETCH_ERROR
    no_majority_event: Enum = Event.NO_MAJORITY
    selection_key = get_name(SynchronizedData.bets_hash)
    collection_key = get_name(SynchronizedData.participant_to_bets_hash)
    synchronized_data_class = SynchronizedData


class UpdateBetsRound(BaseUpdateBetsRound):
    """A round for the bets fetching & updating."""

    payload_class: Type[UpdateBetsPayload] = UpdateBetsPayload
    done_event: Enum = Event.DONE
    none_event: Enum = Event.FETCH_ERROR
    no_majority_event: Enum = Event.NO_MAJORITY
    selection_key: Any = (
        BaseUpdateBetsRound.selection_key,
        get_name(SynchronizedData.wallet_balance),
        get_name(SynchronizedData.token_balance),
        get_name(SynchronizedData.olas_balance),
        get_name(SynchronizedData.service_owner_address),
    )
    collection_key = get_name(SynchronizedData.participant_to_bets_hash)
    synchronized_data_class = SynchronizedData


class FinishedMarketManagerRound(DegenerateRound, ABC):
    """A round that represents MarketManager has finished"""


class FailedMarketManagerRound(DegenerateRound, ABC):
    """A round that represents that the period failed"""


class MarketManagerAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """MarketManagerAbciApp

    Initial round: UpdateBetsRound

    Initial states: {UpdateBetsRound}

    Transition states:
        0. UpdateBetsRound
            - done: 1.
            - fetch error: 2.
            - round timeout: 0.
            - no majority: 0.
        1. FinishedMarketManagerRound
        2. FailedMarketManagerRound

    Final states: {FailedMarketManagerRound, FinishedMarketManagerRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = UpdateBetsRound
    transition_function: AbciAppTransitionFunction = {
        UpdateBetsRound: {
            Event.DONE: FinishedMarketManagerRound,
            Event.FETCH_ERROR: FailedMarketManagerRound,
            Event.ROUND_TIMEOUT: UpdateBetsRound,
            Event.NO_MAJORITY: UpdateBetsRound,
        },
        FinishedMarketManagerRound: {},
        FailedMarketManagerRound: {},
    }
    cross_period_persisted_keys = frozenset({get_name(SynchronizedData.bets_hash)})
    final_states: Set[AppState] = {FinishedMarketManagerRound, FailedMarketManagerRound}
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {UpdateBetsRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedMarketManagerRound: {get_name(SynchronizedData.bets_hash)},
        FailedMarketManagerRound: set(),
    }
