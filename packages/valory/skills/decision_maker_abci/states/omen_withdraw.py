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

"""This module contains the Omen withdrawal sweep round."""

from enum import Enum
from typing import Optional, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.decision_maker_abci.payloads import (
    MultisigTxPayload,
    OmenWithdrawalPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class OmenWithdrawRound(TxPreparationRound):
    """Builds and submits the Omen withdrawal sweep multisend.

    Two terminal outcomes (mirror ``PolymarketRedeemRound``):
      - All agents agreed on a sweep multisend → ``Event.PREPARE_TX``
        (routes through ``tx_settlement_multiplexer`` to
        ``PostOmenWithdrawRound`` after settlement).
      - All agents agreed nothing was sellable → ``Event.WITHDRAWAL_DONE``
        (short-circuits straight to ``WithdrawalIdleRound``; no tx settles,
        so ``PostOmenWithdrawRound`` does not run this cycle).

    The branch is selected from the payload's trailing ``event`` field by
    the ``end_block`` override below.
    """

    payload_class: Type[MultisigTxPayload] = OmenWithdrawalPayload
    selection_key: Tuple[str, ...] = TxPreparationRound.selection_key
    none_event = Event.WITHDRAWAL_DONE

    # This needs to be mentioned for static checkers
    # Event.PREPARE_TX
    # Event.WITHDRAWAL_DONE

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Switch the emitted event to the one carried in the payload."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        if event == self.no_majority_event:
            return res

        actual_event = Event(self.most_voted_payload_values[-1])
        return synced_data, actual_event
