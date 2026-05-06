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

"""Omen withdrawal round (defensive stub).

POST /api/v1/withdrawal is rejected with 501 on Omenstrat (D27), so this
round is unreachable in normal operation. It exists for FSM symmetry across
services and as a sane failure mode if the on-disk flag is set on Omen.

TODO: implement real Omen position discovery + sell mechanism (FPMM `sell`).
"""

from packages.valory.skills.abstract_round_abci.base import (
    CollectSameUntilThresholdRound,
    get_name,
)
from packages.valory.skills.decision_maker_abci.payloads import WithdrawalPayload
from packages.valory.skills.decision_maker_abci.states.base import (
    Event,
    SynchronizedData,
)


class OmenWithdrawRound(CollectSameUntilThresholdRound):
    """Stub Omen withdrawal round."""

    payload_class = WithdrawalPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.WITHDRAWAL_DONE
    none_event = Event.NONE
    no_majority_event = Event.NO_MAJORITY
    selection_key = (get_name(SynchronizedData.participant_to_selection),)
    collection_key = get_name(SynchronizedData.participant_to_selection)
