#!/usr/bin/env python3
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


"""This module contains the sell outcome token state of the decision-making abci app."""

from enum import Enum
from typing import Any, Optional, Tuple, Type, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import SellOutcomeTokensPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
    TxPreparationRound,
)
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)


class SellOutcomeTokensRound(TxPreparationRound):
    """A round for selling a token."""

    payload_class: Type[SellOutcomeTokensPayload] = SellOutcomeTokensPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY

    # we are updating the vote to opposite as this round receives vote to be sold
    selection_key: Any = (
        *DecisionReceiveRound.selection_key,
        get_name(SynchronizedData.vote),
    )
    collection_key = get_name(SynchronizedData.participant_to_selection)

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()
        if res is None:
            return None

        synced_data, event = cast(Tuple[SynchronizedData, Enum], res)

        if event == Event.DONE and not synced_data.most_voted_tx_hash:
            event = Event.CALC_SELL_AMOUNT_FAILED

        return synced_data, event
