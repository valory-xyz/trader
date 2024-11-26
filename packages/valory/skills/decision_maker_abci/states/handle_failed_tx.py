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

from packages.valory.skills.abstract_round_abci.base import VotingRound, get_name
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


class HandleFailedTxRound(VotingRound):
    """A round for updating the bets after blacklisting the sampled one."""

    payload_class = VotingPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.BLACKLIST
    negative_event = Event.NO_OP
    no_majority_event = Event.NO_MAJORITY
    collection_key = get_name(SynchronizedData.participant_to_votes)
    required_class_attributes = ()
