# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""This module contains the decision receiving state of the decision-making abci app."""

from enum import Enum
from typing import Any, Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.market_manager_abci.rounds import UpdateBetsRound


IGNORED = "ignored"


class DecisionReceiveRound(CollectSameUntilThresholdRound):
    """A round in which the agents decide on the bet's answer."""

    payload_class = DecisionReceivePayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.MECH_RESPONSE_ERROR
    no_majority_event = Event.NO_MAJORITY
    selection_key: Any = (
        UpdateBetsRound.selection_key,
        get_name(SynchronizedData.is_profitable),
        get_name(SynchronizedData.vote),
        get_name(SynchronizedData.confidence),
        get_name(SynchronizedData.bet_amount),
        get_name(SynchronizedData.next_mock_data_row),
        get_name(SynchronizedData.policy),
        get_name(SynchronizedData.should_be_sold),
    )
    collection_key = get_name(SynchronizedData.participant_to_decision)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Get the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def review_bets_for_selling_mode(self) -> bool:
        """Get the review bets for selling mode."""
        return self.synchronized_data.review_bets_for_selling

    def payload(self, payload_values: Tuple[Any, ...]) -> DecisionReceivePayload:
        """Get the payload."""
        return DecisionReceivePayload(IGNORED, *payload_values)

    def end_block(self) -> Optional[Tuple[SynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        if event == Event.DONE:
            payload = self.payload(self.most_voted_payload_values)
            decision_receive_timestamp = payload.decision_received_timestamp

            synced_data = cast(
                SynchronizedData,
                synced_data.update(
                    decision_receive_timestamp=decision_receive_timestamp,
                    should_be_sold=payload.should_be_sold,
                ),
            )

        if event == Event.DONE and synced_data.vote is None:
            return synced_data, Event.TIE

        self.context.logger.info(f"Vote: {synced_data.should_be_sold=}")
        if event == Event.DONE and self.review_bets_for_selling_mode:
            if self.synchronized_data.should_be_sold:
                self.context.logger.debug(
                    f"Should be sold. {synced_data.should_be_sold=}"
                )
                return synced_data, Event.DONE_SELL
            else:
                return synced_data, Event.DONE_NO_SELL

        if event == Event.DONE and not synced_data.is_profitable:
            return synced_data, Event.UNPROFITABLE

        return synced_data, event
