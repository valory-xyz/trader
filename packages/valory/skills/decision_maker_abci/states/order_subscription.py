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

"""This module contains the decision receiving state of the decision-making abci app."""

from enum import Enum
from typing import Optional, Tuple, Type

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    MultisigTxPayload,
    SubscriptionPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class SubscriptionRound(TxPreparationRound):
    """A round in which the agents prepare a tx to initiate a request to a mech to determine the answer to a bet."""

    payload_class: Type[MultisigTxPayload] = SubscriptionPayload
    selection_key = TxPreparationRound.selection_key + (
        get_name(SynchronizedData.agreement_id),
    )
    none_event = Event.NO_SUBSCRIPTION

    NO_TX_PAYLOAD = "no_tx"
    ERROR_PAYLOAD = "error"

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        if self.threshold_reached:
            tx_hash = self.most_voted_payload_values[1]
            if tx_hash == self.ERROR_PAYLOAD:
                return self.synchronized_data, Event.SUBSCRIPTION_ERROR

            if tx_hash == self.NO_TX_PAYLOAD:
                return self.synchronized_data, Event.NO_SUBSCRIPTION

            if self.context.benchmarking_mode.enabled:
                return self.synchronized_data, Event.MOCK_TX

        update = super().end_block()
        if update is None:
            return None

        sync_data, event = update
        agreement_id = self.most_voted_payload_values[3]
        wallet_balance = self.most_voted_payload_values[4]
        sync_data = sync_data.update(
            agreement_id=agreement_id, wallet_balance=wallet_balance
        )
        return sync_data, event
