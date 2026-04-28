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

"""This module contains the PolymarketWrapCollateralRound."""

from enum import Enum
from typing import Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import BaseSynchronizedData
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketWrapCollateralPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)


class PolymarketWrapCollateralRound(TxPreparationRound):
    """A round for wrapping USDC.e → pUSD before placing a Polymarket bet."""

    payload_class = PolymarketWrapCollateralPayload
    none_event = Event.NONE

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Emit PREPARE_TX when a wrap tx was built, DONE otherwise."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)
        should_wrap = self.most_voted_payload_values[-1]
        event = Event.PREPARE_TX if should_wrap else Event.DONE

        return synced_data, event
