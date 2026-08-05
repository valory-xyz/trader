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

"""This module contains the Polymarket (CLOB v2) DepositWallet sweep round."""

from enum import Enum
from typing import Optional, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.decision_maker_abci.payloads import (
    MultisigTxPayload,
    PolymarketSweepPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class PolymarketSweepRound(TxPreparationRound):
    """Sweeps the DepositWallet back to the Safe after a CLOB match.

    The sweep is relayed through the wildcard proxy (idempotent — "transfer
    whatever's there"), so nothing settles on-chain here. A successful sweep
    (including the no-op empty-DW case) emits ``Event.DONE`` →
    ``FinishedPolymarketBetPlacementRound``; a failed sweep emits
    ``Event.NONE`` and loops the round, leaving the funds in the DW until the
    next pass.
    """

    payload_class: Type[MultisigTxPayload] = PolymarketSweepPayload
    selection_key: Tuple[str, ...] = TxPreparationRound.selection_key
    none_event = Event.NONE

    # fsm-specs: returns(DONE, NONE)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Switch the emitted event to the one carried in the payload."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        if event == self.no_majority_event:
            return res

        # PolymarketSweepPayload trailing field: event(-1).
        actual_event = Event(self.most_voted_payload_values[-1])
        return synced_data, actual_event
