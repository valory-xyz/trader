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

"""This module contains the blacklisting state of the decision-making abci app."""

from enum import Enum
from typing import Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    NONE_EVENT_ATTRIBUTE,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import HandleFailedTxPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


class HandleFailedTxRound(CollectSameUntilThresholdRound):
    """A round for updating the bets after blacklisting the sampled one."""

    payload_class = HandleFailedTxPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.BLACKLIST
    no_op_event = Event.NO_OP
    no_majority_event = Event.NO_MAJORITY
    selection_key = (
        get_name(SynchronizedData.after_bet_attempt),
        get_name(SynchronizedData.tx_submitter),
    )
    collection_key = get_name(SynchronizedData.participant_to_handle_failed_tx)
    # the none event is not required because the `HandleFailedTxPayload` payload does not allow for `None` values
    extended_requirements = tuple(
        attribute
        for attribute in CollectSameUntilThresholdRound.required_class_attributes
        if attribute != NONE_EVENT_ATTRIBUTE
    )

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        if event != self.done_event:
            return res

        if synced_data.after_bet_attempt:
            return synced_data, self.done_event

        return synced_data, self.no_op_event
