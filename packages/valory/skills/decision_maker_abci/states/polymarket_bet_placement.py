# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""This module contains the polymarket bet placement state of the decision-making abci app."""

from enum import Enum
from typing import Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class PolymarketBetPlacementRound(TxPreparationRound):
    """A round for placing a bet."""

    payload_class = PolymarketBetPlacementPayload
    none_event = Event.INSUFFICIENT_BALANCE

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        # For static checking
        # Event.BET_PLACEMENT_DONE, Event.BET_PLACEMENT_FAILED, Event.INSUFFICIENT_BALANCE, Event.BET_PLACEMENT_IMPOSSIBLE

        # Extract event, cached_signed_orders, utilized_tools, and policy from payload
        # Payload: sender(0), tx_submitter(1), tx_hash(2), mocking_mode(3), event(4), cached_signed_orders(5), utilized_tools(6), policy(7)
        event = Event(self.most_voted_payload_values[-4])
        cached_orders = self.most_voted_payload_values[-3]
        utilized_tools_update = self.most_voted_payload_values[-2]
        policy_update = self.most_voted_payload_values[-1]

        # Persist cached orders to synchronized data
        if cached_orders is not None:
            synced_data = cast(
                SynchronizedData,
                synced_data.update(
                    synchronized_data_class=self.synchronized_data_class,
                    **{"cached_signed_orders": cached_orders},
                ),
            )

        # Persist the conditionId→tool mapping so the redeem behaviour can later
        # call policy.update_accuracy_store for each winning position.
        if utilized_tools_update is not None:
            synced_data = cast(
                SynchronizedData,
                synced_data.update(
                    synchronized_data_class=self.synchronized_data_class,
                    **{"utilized_tools": utilized_tools_update},
                ),
            )

        # Persist the updated policy (with incremented pending) from bet placement.
        if policy_update is not None:
            synced_data = cast(
                SynchronizedData,
                synced_data.update(
                    synchronized_data_class=self.synchronized_data_class,
                    **{"policy": policy_update},
                ),
            )

        return synced_data, event
