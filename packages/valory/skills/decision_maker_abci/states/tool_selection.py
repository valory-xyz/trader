# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This module contains the tool selection state of the decision-making abci app."""

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import ToolSelectionPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


class ToolSelectionRound(CollectSameUntilThresholdRound):
    """A round for selecting a Mech tool."""

    payload_class = ToolSelectionPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key = (
        get_name(SynchronizedData.available_mech_tools),
        get_name(SynchronizedData.policy),
        get_name(SynchronizedData.utilized_tools),
        get_name(SynchronizedData.mech_tool),
    )
    collection_key = get_name(SynchronizedData.participant_to_selection)
