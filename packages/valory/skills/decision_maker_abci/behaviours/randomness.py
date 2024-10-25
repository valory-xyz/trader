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

"""This module contains the behaviour of the skill which is responsible for gathering randomness."""

from packages.valory.skills.abstract_round_abci.common import (
    RandomnessBehaviour as RandomnessBehaviourBase,
)
from packages.valory.skills.decision_maker_abci.states.randomness import (
    BenchmarkingRandomnessRound,
    RandomnessRound,
)
from packages.valory.skills.transaction_settlement_abci.payloads import (
    RandomnessPayload,
)


class RandomnessBehaviour(RandomnessBehaviourBase):
    """Retrieve randomness."""

    matching_round = RandomnessRound
    payload_class = RandomnessPayload


class BenchmarkingRandomnessBehaviour(RandomnessBehaviour):
    """Retrieve randomness in benchmarking mode."""

    matching_round = BenchmarkingRandomnessRound
