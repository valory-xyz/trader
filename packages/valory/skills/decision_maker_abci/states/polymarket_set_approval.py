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

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketSetApprovalPayload,
)
from enum import Enum
from typing import Optional, Tuple, cast

from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)

class PolymarketSetApprovalRound(TxPreparationRound):
    """A round for setting approval."""

    payload_class = PolymarketSetApprovalPayload
    none_event = Event.NONE

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        # Check if builder program is enabled
        if self.context.params.polymarket_builder_program_enabled:
            # Builder program enabled: go directly to PostSetApprovalRound
            self.context.logger.info(
                "Polymarket builder program enabled - transitioning to PostSetApprovalRound"
            )
            event = Event.DONE
        else:
            # Builder program disabled: use OA framework for transaction settlement
            self.context.logger.info(
                "Polymarket builder program disabled - using OA framework for tx settlement"
            )
            event = Event.PREPARE_TX

        return synced_data, event