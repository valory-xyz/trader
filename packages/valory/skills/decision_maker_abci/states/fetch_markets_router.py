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

"""This module contains the fetch markets router state of the decision-making abci app."""

from enum import Enum
from typing import Optional, Tuple, cast

from packages.valory.skills.abstract_round_abci.base import VotingRound, get_name
from packages.valory.skills.decision_maker_abci.payloads import FetchMarketsRouterPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


class FetchMarketsRouterRound(VotingRound):
    """A round for switching between Omen and Polymarket market fetching rounds."""

    payload_class = FetchMarketsRouterPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    negative_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_selection)

    @property
    def params(self):
        from packages.valory.skills.decision_maker_abci.models import (
            DecisionMakerParams,
        )

        """Return the shared state."""
        return cast(DecisionMakerParams, self.context.params)

    def end_block(self) -> Optional[Tuple[SynchronizedData, Enum]]:
        """Process the end of the block."""
        res = super().end_block()

        if res is None:
            return None
        synchronized_data, event = res

        if self.params.is_running_on_polymarket:
            event = Event.POLYMARKET_FETCH_MARKETS
        else:
            event = Event.DONE

        return synchronized_data, event
