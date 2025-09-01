# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the round for preparing a sell from called from sampling."""

from enum import Enum
from typing import Any, Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import PrepareSellPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.decision_maker_abci.states.sampling import UpdateBetsRound


IGNORED = "ignored"


class PrepareSellRound(CollectSameUntilThresholdRound):
    """A round for preparing a sell from called from sampling."""

    payload_class = PrepareSellPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key: Tuple[str, ...] = (
        UpdateBetsRound.selection_key,
        get_name(SynchronizedData.vote),
    )
    collection_key = get_name(SynchronizedData.participant_to_decision)

    def payload(self, payload_values: Tuple[Any, ...]) -> PrepareSellPayload:
        """Get the payload."""
        return PrepareSellPayload(IGNORED, *payload_values)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        if event == Event.DONE:
            payload = self.payload(self.most_voted_payload_values)
            synced_data = cast(
                SynchronizedData,
                synced_data.update(
                    vote=payload.vote,
                    bet_amount=payload.bet_amount,
                ),
            )

        return synced_data, event
