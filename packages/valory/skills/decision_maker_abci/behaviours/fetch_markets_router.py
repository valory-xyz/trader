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

"""This module contains the fetch markets router behaviour of the decision-making abci app."""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import FetchMarketsRouterPayload
from packages.valory.skills.decision_maker_abci.states.fetch_markets_router import (
    FetchMarketsRouterRound,
)


class FetchMarketsRouterBehaviour(DecisionMakerBaseBehaviour):
    """FetchMarketsRouterBehaviour."""

    matching_round = FetchMarketsRouterRound

    def async_act(self) -> Generator:
        """Do the action."""

        payload = FetchMarketsRouterPayload(sender=self.context.agent_address, vote=True)

        yield from self.finish_behaviour(payload)
