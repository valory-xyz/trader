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

"""This module contains the response state of the mech interaction abci app."""

from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.mech_interact_abci.payloads import MechResponsePayload
from packages.valory.skills.mech_interact_abci.states.base import (
    MechInteractionRound,
    SynchronizedData,
)


class MechResponseRound(MechInteractionRound):
    """A round for collecting the responses from a Mech."""

    payload_class = MechResponsePayload
    selection_key = get_name(SynchronizedData.mech_responses)
    collection_key = get_name(SynchronizedData.participant_to_responses)
