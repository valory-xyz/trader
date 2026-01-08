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

"""This module contains a state of the decision-making abci app which checks if the benchmarking mode is enabled."""

from packages.valory.skills.abstract_round_abci.base import VotingRound, get_name
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from enum import Enum
from typing import Optional, Tuple
from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
)


class CheckBenchmarkingModeRound(VotingRound):
    """A round for checking whether the benchmarking mode is enabled."""

    payload_class = VotingPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.BENCHMARKING_ENABLED
    negative_event = Event.BENCHMARKING_DISABLED
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    set_approval_event = Event.SET_APPROVAL
    collection_key = get_name(SynchronizedData.participant_to_votes)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        if self.context.params.is_running_on_polymarket:
            # If running on Polymarket, skip benchmarking check and go directly to Polymarket flow
            self.context.logger.info(
                "Running on Polymarket..."
            )
            return self.synchronized_data, Event.SET_APPROVAL

        # Normal flow: check if benchmarking is enabled
        res = super().end_block()
        return res
