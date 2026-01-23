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

"""This module contains the base functionality for the rounds of the MarketManager ABCI app."""

from abc import ABC
from enum import Enum
from typing import Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbstractRound,
    BaseSynchronizedData,
    CollectionRound,
    DeserializedCollection,
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
