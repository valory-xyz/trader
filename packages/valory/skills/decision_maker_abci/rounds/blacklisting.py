# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the blacklisting state of the decision-making abci app."""

from packages.valory.skills.decision_maker_abci.rounds.base import Event
from packages.valory.skills.market_manager_abci.rounds import (
    UpdateBetsRound as BaseUpdateBetsRound,
)


class BlacklistingRound(BaseUpdateBetsRound):
    """A round for updating the bets after blacklisting the sampled one."""

    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
