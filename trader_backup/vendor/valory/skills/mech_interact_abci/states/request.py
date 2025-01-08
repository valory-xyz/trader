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

"""This module contains the request state of the mech interaction abci app."""

from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.mech_interact_abci.payloads import MechRequestPayload
from packages.valory.skills.mech_interact_abci.states.base import (
    Event,
    MechInteractionRound,
    SynchronizedData,
)


class MechRequestRound(MechInteractionRound):
    """A round for performing requests to a Mech."""

    payload_class = MechRequestPayload

    selection_key = (
        get_name(SynchronizedData.tx_submitter),
        get_name(SynchronizedData.most_voted_tx_hash),
        get_name(SynchronizedData.mech_price),
        get_name(SynchronizedData.chain_id),
        get_name(SynchronizedData.mech_requests),
        get_name(SynchronizedData.mech_responses),
    )
    collection_key = get_name(SynchronizedData.participant_to_requests)
    none_event = Event.SKIP_REQUEST
