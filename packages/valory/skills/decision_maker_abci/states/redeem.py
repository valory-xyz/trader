# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the redeem state of the decision-making abci app."""

from enum import Enum
from typing import Optional, Tuple, Type

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    MultisigTxPayload,
    RedeemPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class RedeemRound(TxPreparationRound):
    """A round in which the agents prepare a tx to redeem the winnings."""

    payload_class: Type[MultisigTxPayload] = RedeemPayload
    selection_key = TxPreparationRound.selection_key + (
        get_name(SynchronizedData.policy),
        get_name(SynchronizedData.utilized_tools),
        get_name(SynchronizedData.redeemed_condition_ids),
        get_name(SynchronizedData.payout_so_far),
    )
    none_event = Event.NO_REDEEMING

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if (
            res is None
            and self.block_confirmations == self.synchronized_data.period_count == 0
        ):
            # necessary for always setting the persisted keys and not raise an exception when the first period ends
            # this also protects us in case a round timeout is raised
            update = {
                db_key: self.synchronized_data.db.get(db_key, None)
                for db_key in RedeemRound.selection_key
            }
            self.synchronized_data.db.update(**update)
            self.block_confirmations = 1

        return res
