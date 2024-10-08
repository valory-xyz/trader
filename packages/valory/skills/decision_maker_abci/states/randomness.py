# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains the randomness state of the decision-making abci app."""

from typing import Any

from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.transaction_settlement_abci.rounds import (
    RandomnessTransactionSubmissionRound,
)


class RandomnessRound(RandomnessTransactionSubmissionRound):
    """A round for gathering randomness."""

    done_event: Any = Event.DONE
    no_majority_event: Any = Event.NO_MAJORITY


class BenchmarkingRandomnessRound(RandomnessRound):
    """A round for gathering randomness in benchmarking mode."""
