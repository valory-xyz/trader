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

"""This module contains the sampling state of the decision-making abci app."""
from enum import Enum
from typing import Optional, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData, get_name
from packages.valory.skills.decision_maker_abci.payloads import (
    BetPlacementPayload,
    MultisigTxPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class BetPlacementRound(TxPreparationRound):
    """A round for placing a bet."""

    payload_class: Type[MultisigTxPayload] = BetPlacementPayload
    none_event = Event.INSUFFICIENT_BALANCE
    selection_key = TxPreparationRound.selection_key + (
        get_name(SynchronizedData.wallet_balance),
        get_name(SynchronizedData.token_balance),
        get_name(SynchronizedData.most_voted_tx_hash),
    )

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        
        # Safely get indices using selection_key
        wallet_balance_idx = self.selection_key.index(get_name(SynchronizedData.wallet_balance))
        token_balance_idx = self.selection_key.index(get_name(SynchronizedData.token_balance))
        
        wallet_balance = self.most_voted_payload_values[wallet_balance_idx]
        token_balance = self.most_voted_payload_values[token_balance_idx]
        
        synced_data = synced_data.update(wallet_balance=wallet_balance, token_balance=token_balance)

        if event == Event.DONE and not cast(SynchronizedData, synced_data).most_voted_tx_hash:
            event = Event.CALC_BUY_AMOUNT_FAILED

        return synced_data, event
