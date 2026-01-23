# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""This module contains the Polymarket fetch market round for the MarketManager ABCI app."""

from enum import Enum

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.states.base import (
    Event,
    MarketManagerAbstractRound,
    SynchronizedData,
)


class PolymarketFetchMarketRound(CollectSameUntilThresholdRound, MarketManagerAbstractRound):
    """A round for fetching and updating bets from Polymarket."""

    payload_class = UpdateBetsPayload
    done_event: Enum = Event.DONE
    none_event: Enum = Event.FETCH_ERROR
    no_majority_event: Enum = Event.NO_MAJORITY
    selection_key = get_name(SynchronizedData.bets_hash)
    collection_key = get_name(SynchronizedData.participant_to_bets_hash)
    synchronized_data_class = SynchronizedData
