# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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
from typing import Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketPostSetApprovalPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


class PolymarketPostSetApprovalRound(CollectSameUntilThresholdRound):
    """A round for post setting approval."""

    payload_class = PolymarketPostSetApprovalPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key = (get_name(SynchronizedData.participant_to_selection),)
    collection_key = get_name(SynchronizedData.participant_to_selection)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        # If consensus was reached but not all approvals were set, trigger APPROVAL_FAILED
        if event == Event.DONE:
            # Get the consensus vote from the most_voted_payload
            most_voted_payload = self.most_voted_payload
            if most_voted_payload in ("partial", "no", "error"):
                self.context.logger.warning(
                    f"Approvals not fully set (vote: {most_voted_payload}). Routing back to SET_APPROVAL."
                )
                return synced_data, Event.APPROVAL_FAILED

        return res
