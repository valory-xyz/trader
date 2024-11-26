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

"""This module contains a state of the decision-making abci app which checks if the benchmarking mode is enabled."""

from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)


class CheckBenchmarkingModeRound(HandleFailedTxRound):
    """A round for checking whether the benchmarking mode is enabled."""

    done_event = Event.BENCHMARKING_ENABLED
    negative_event = Event.BENCHMARKING_DISABLED
    none_event = Event.NONE
    required_class_attributes = ()
