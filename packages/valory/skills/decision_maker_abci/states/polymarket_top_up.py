# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""This module contains the Polymarket (CLOB v2) DepositWallet top-up round."""

from enum import Enum
from typing import Optional, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.decision_maker_abci.payloads import (
    MultisigTxPayload,
    PolymarketTopUpPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class PolymarketTopUpRound(TxPreparationRound):
    """Funds the DepositWallet from the Safe just before a CLOB match.

    Three terminal outcomes, selected from the payload's trailing ``event``:
      - A pUSD transfer Safe→DW must settle → ``Event.PREPARE_TX`` (routes
        through ``tx_settlement_multiplexer`` and back to
        ``PolymarketBetPlacementRound`` once mined).
      - The DW already holds enough pUSD → ``Event.DONE`` (no tx settles;
        straight to ``PolymarketBetPlacementRound``).
      - The Safe cannot fund the buy → ``Event.INSUFFICIENT_BALANCE``
        (``RefillRequiredRound``).

    The DepositWallet address is not carried in the payload: the bet-placement
    and sweep rounds resolve the funder from the persisted store.
    """

    payload_class: Type[MultisigTxPayload] = PolymarketTopUpPayload
    selection_key: Tuple[str, ...] = TxPreparationRound.selection_key
    none_event = Event.INSUFFICIENT_BALANCE

    # fsm-specs: returns(DONE, PREPARE_TX, INSUFFICIENT_BALANCE)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Emit the payload-carried event and persist the DepositWallet address."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        if event == self.no_majority_event:
            return res

        # PolymarketTopUpPayload trailing field: event(-1).
        actual_event = Event(self.most_voted_payload_values[-1])
        return synced_data, actual_event
