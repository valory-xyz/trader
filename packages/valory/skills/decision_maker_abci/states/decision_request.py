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

"""This module contains the decision requesting state of the decision-making abci app."""

from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    TxPreparationRound,
)


class DecisionRequestRound(TxPreparationRound):
    """A round in which the agents prepare a tx to initiate a request to a mech to determine the answer to a bet."""

    none_event = Event.SLOTS_UNSUPPORTED_ERROR
