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

"""This module contains the rounds for the check stop trading ABCI application."""

from abc import ABC
from enum import Enum
from typing import Dict, Optional, Set, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import (
    AbciApp,
    AbciAppTransitionFunction,
    AbstractRound,
    AppState,
    BaseSynchronizedData,
    CollectionRound,
    DegenerateRound,
    DeserializedCollection,
    VotingRound,
    get_name,
)
from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
)


class Event(Enum):
    """Event enumeration for the check stop trading skill."""

    DONE = "done"
    NONE = "none"
    ROUND_TIMEOUT = "round_timeout"
    NO_MAJORITY = "no_majority"
    SKIP_TRADING = "skip_trading"
    REVIEW_BETS = "review_bets"


class SynchronizedData(BaseSynchronizedData):
    """Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    def _get_deserialized(self, key: str) -> DeserializedCollection:
        """Strictly get a collection and return it deserialized."""
        serialized = self.db.get_strict(key)
        return CollectionRound.deserialize_collection(serialized)

    @property
    def last_review_timestamp(self) -> int:
        """Get the last review timestamp."""
        return cast(int, self.db.get("last_review_timestamp", 0))

    @property
    def is_staking_kpi_met(self) -> bool:
        """Get the status of the staking kpi."""
        return bool(self.db.get("is_staking_kpi_met", False))

    @property
    def review_bets_for_selling(self) -> bool:
        """Get the status of the review bets for selling."""
        db_value = self.db.get("review_bets_for_selling", None)
        if not isinstance(db_value, bool):
            return False
        return bool(db_value)


class CheckStopTradingRound(VotingRound):
    """A round for checking stop trading conditions."""

    payload_class = CheckStopTradingPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.SKIP_TRADING
    negative_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key = get_name(SynchronizedData.review_bets_for_selling)
    collection_key = get_name(SynchronizedData.participant_to_votes)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(
            self.context.state.round_sequence.last_round_transition_timestamp.timestamp()
        )

    def should_review_bets(self, is_staking_kpi_met: bool) -> bool:
        """Check if the bets should be reviewed."""
        if not is_staking_kpi_met:
            self.context.logger.info("Staking kpi is not yet met")
            return False

        if not self.context.params.enable_position_review:
            self.context.logger.info("Position review is disabled")
            return False

        last_review = self.synchronized_data.last_review_timestamp

        return (
            self.synced_timestamp - last_review
            > self.context.params.review_period_seconds
        )

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()

        if res is None:
            return None

        is_staking_kpi_met = self.positive_vote_threshold_reached
        self.synchronized_data.update(is_staking_kpi_met=is_staking_kpi_met)

        if self.should_review_bets(is_staking_kpi_met):
            self.context.logger.info(
                "Updating synchronized data to review bets for selling"
            )
            self.synchronized_data.update(review_bets_for_selling=True)
            return self.synchronized_data, Event.REVIEW_BETS

        self.synchronized_data.update(review_bets_for_selling=False)

        return res


class FinishedCheckStopTradingRound(DegenerateRound, ABC):
    """A round that represents check stop trading has finished."""


class FinishedWithSkipTradingRound(DegenerateRound, ABC):
    """A round that represents check stop trading has finished with skip trading."""


class FinishedWithReviewBetsRound(DegenerateRound, ABC):
    """A round that represents check stop trading has finished with review bets."""


class CheckStopTradingAbciApp(AbciApp[Event]):  # pylint: disable=too-few-public-methods
    """CheckStopTradingAbciApp

    Initial round: CheckStopTradingRound

    Initial states: {CheckStopTradingRound}

    Transition states:
        0. CheckStopTradingRound
            - done: 1.
            - none: 0.
            - round timeout: 0.
            - no majority: 0.
            - skip trading: 2.
            - review bets: 3.
        1. FinishedCheckStopTradingRound
        2. FinishedWithSkipTradingRound
        3. FinishedWithReviewBetsRound

    Final states: {FinishedCheckStopTradingRound, FinishedWithReviewBetsRound, FinishedWithSkipTradingRound}

    Timeouts:
        round timeout: 30.0
    """

    initial_round_cls: Type[AbstractRound] = CheckStopTradingRound
    transition_function: AbciAppTransitionFunction = {
        CheckStopTradingRound: {
            Event.DONE: FinishedCheckStopTradingRound,
            Event.NONE: CheckStopTradingRound,
            Event.ROUND_TIMEOUT: CheckStopTradingRound,
            Event.NO_MAJORITY: CheckStopTradingRound,
            Event.SKIP_TRADING: FinishedWithSkipTradingRound,
            Event.REVIEW_BETS: FinishedWithReviewBetsRound,
        },
        FinishedCheckStopTradingRound: {},
        FinishedWithSkipTradingRound: {},
        FinishedWithReviewBetsRound: {},
    }
    final_states: Set[AppState] = {
        FinishedCheckStopTradingRound,
        FinishedWithSkipTradingRound,
        FinishedWithReviewBetsRound,
    }
    event_to_timeout: Dict[Event, float] = {
        Event.ROUND_TIMEOUT: 30.0,
    }
    db_pre_conditions: Dict[AppState, Set[str]] = {CheckStopTradingRound: set()}
    db_post_conditions: Dict[AppState, Set[str]] = {
        FinishedCheckStopTradingRound: set(),
        FinishedWithSkipTradingRound: set(),
        FinishedWithReviewBetsRound: set(),
    }
