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

"""This module contains the sampling state of the decision-making abci app."""

from enum import Enum
from typing import Any, Optional, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import SamplingPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import UpdateBetsRound


class SamplingRound(UpdateBetsRound):
    """A round for sampling a bet."""

    payload_class: Type[UpdateBetsPayload] = SamplingPayload
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key: Any = (
        UpdateBetsRound.selection_key,
        get_name(SynchronizedData.sampled_bet_index),
        get_name(SynchronizedData.benchmarking_finished),
        get_name(SynchronizedData.simulated_day),
    )

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        if synced_data.benchmarking_finished:
            self.context.logger.info(
                "No more markets to bet. The benchmarking has finished!"
            )
            return synced_data, Event.BENCHMARKING_FINISHED

        if synced_data.simulated_day:
            self.context.logger.info(
                "Entering the sampling Round for a new simulated day"
            )
            # re-enter the SamplingRound
            return synced_data, Event.NEW_SIMULATED_RESAMPLE
        if event == Event.DONE and self.context.benchmarking_mode.enabled:
            return synced_data, Event.BENCHMARKING_ENABLED
        return res
