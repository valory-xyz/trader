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

import json
from pathlib import Path

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
            # Check if allowances are already set
            allowances_path = Path(self.context.params.store_path) / "polymarket_allowances.json"
            
            try:
                with open(allowances_path, "r") as f:
                    allowances_data = json.load(f)
                    allowances_set = allowances_data.get("allowances_set", False)
                    
                    if allowances_set:
                        self.context.logger.info(
                            "Polymarket allowances already set. Skipping approval round."
                        )
                        return self.synchronized_data, Event.BENCHMARKING_DISABLED
                    else:
                        self.context.logger.info(
                            "Polymarket allowances not set. Proceeding to SET_APPROVAL."
                        )
            except FileNotFoundError:
                self.context.logger.info(
                    "No allowances file found. Proceeding to SET_APPROVAL for first time."
                )
            except Exception as e:
                self.context.logger.warning(
                    f"Error reading allowances file: {e}. Proceeding to SET_APPROVAL."
                )
            
            # If running on Polymarket and allowances not set, go to SET_APPROVAL
            return self.synchronized_data, Event.SET_APPROVAL

        # Normal flow: check if benchmarking is enabled
        res = super().end_block()
        return res
