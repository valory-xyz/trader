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

"""This module contains the redeem state of the decision-making abci app."""

from enum import Enum
from typing import Any, Optional, Tuple, Type, cast

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


IGNORED = "ignored"
MECH_TOOLS_FIELD = "mech_tools"


class RedeemRound(TxPreparationRound):
    """A round in which the agents prepare a tx to redeem the winnings."""

    payload_class: Type[MultisigTxPayload] = RedeemPayload
    mech_tools_name = get_name(SynchronizedData.available_mech_tools)
    selection_key = TxPreparationRound.selection_key + (
        mech_tools_name,
        get_name(SynchronizedData.policy),
        get_name(SynchronizedData.utilized_tools),
        get_name(SynchronizedData.redeemed_condition_ids),
        get_name(SynchronizedData.payout_so_far),
    )
    none_event = Event.NO_REDEEMING

    @property
    def most_voted_payload_values(
        self,
    ) -> Tuple[Any, ...]:
        """Get the most voted payload values in such a way to create a custom none event that ignores the mech tools."""
        most_voted_payload_values = super().most_voted_payload_values
        # sender does not matter for the init as the `data` property used below to obtain the dictionary ignores it
        most_voted_payload = RedeemPayload(IGNORED, *most_voted_payload_values)
        most_voted_payload_dict = most_voted_payload.data
        mech_tools = most_voted_payload_dict.pop(MECH_TOOLS_FIELD, None)
        if mech_tools is None:
            raise ValueError(f"`{MECH_TOOLS_FIELD}` must not be `None`")
        if all(val is None for val in most_voted_payload_dict.values()):
            return (None,) * len(self.selection_key)
        return most_voted_payload_values

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

        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        # also update the mech tools if there is a majority, because the overridden property does not include it
        if event != self.no_majority_event:
            most_voted_payload_values = self.payload_values_count.most_common()[0][0]
            # sender does not matter for the init as the `data` property used below to obtain the dictionary ignores it
            most_voted_payload = RedeemPayload(IGNORED, *most_voted_payload_values)
            mech_tools_update = most_voted_payload.mech_tools
            updated_data = synced_data.update(
                self.synchronized_data_class,
                **{self.mech_tools_name: mech_tools_update},
            )
            return updated_data, event

        return res
