# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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
    VotingRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import BetPlacementPayload
from packages.valory.skills.decision_maker_abci.states.base import Event


class PolymarketBetPlacementRound(VotingRound):
    """A round for placing a bet."""

    payload_class = BetPlacementPayload
    synchronized_data_class = BaseSynchronizedData
    done_event = Event.DONE
    negative_event = Event.INSUFFICIENT_BALANCE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(BaseSynchronizedData.participant_to_votes)
