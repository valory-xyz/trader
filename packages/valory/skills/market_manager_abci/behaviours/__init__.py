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

"""This module contains the behaviours for the MarketManager ABCI application."""

from typing import Set, Type

from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.market_manager_abci.behaviours.base import (
    BetsManagerBehaviour,
    MULTI_BETS_FILENAME,
    READ_MODE,
    WRITE_MODE,
)
from packages.valory.skills.market_manager_abci.behaviours.fetch_markets_router import (
    FetchMarketsRouterBehaviour,
)
from packages.valory.skills.market_manager_abci.behaviours.polymarket_fetch_market import (
    PolymarketFetchMarketBehaviour,
)
from packages.valory.skills.market_manager_abci.behaviours.update_bets import (
    UpdateBetsBehaviour,
)
from packages.valory.skills.market_manager_abci.rounds import MarketManagerAbciApp


class MarketManagerRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the MarketManager behaviour."""

    initial_behaviour_cls = FetchMarketsRouterBehaviour
    abci_app_cls = MarketManagerAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {
        FetchMarketsRouterBehaviour,  # type: ignore
        UpdateBetsBehaviour,  # type: ignore
        PolymarketFetchMarketBehaviour,  # type: ignore
    }


__all__ = [
    "BetsManagerBehaviour",
    "FetchMarketsRouterBehaviour",
    "MarketManagerRoundBehaviour",
    "PolymarketFetchMarketBehaviour",
    "UpdateBetsBehaviour",
    "MULTI_BETS_FILENAME",
    "READ_MODE",
    "WRITE_MODE",
]
