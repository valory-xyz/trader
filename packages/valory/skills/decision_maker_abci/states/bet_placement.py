# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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
from typing import Optional, Tuple, Type

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.decision_maker_abci.payloads import (
    BetPlacementPayload,
    MultisigTxPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    TxPreparationRound,
)


class BetPlacementRound(TxPreparationRound):
    """A round for placing a bet."""

    payload_class: Type[MultisigTxPayload] = BetPlacementPayload

    none_event = Event.INSUFFICIENT_BALANCE

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        update = super().end_block()
        if update is None:
            return None

        sync_data, event = update
        wallet_balance = self.most_voted_payload_values[-2]
        token_balance = self.most_voted_payload_values[-1]
        sync_data = sync_data.update(
            wallet_balance=wallet_balance, token_balance=token_balance
        )
        return sync_data, event
