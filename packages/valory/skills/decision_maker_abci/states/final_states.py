# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""This module contains the final states of the decision-making abci app."""

import sys
from enum import Enum
from typing import Optional, Tuple

from packages.valory.skills.abstract_round_abci.base import (
    BaseSynchronizedData,
    DegenerateRound,
)


class BenchmarkingModeDisabledRound(DegenerateRound):
    """A round representing that the benchmarking mode is disabled."""


class FinishedDecisionMakerRound(DegenerateRound):
    """A round representing that decision-making has finished."""


class FinishedDecisionRequestRound(DegenerateRound):
    """A round representing that decision request has finished."""


class FinishedWithoutRedeemingRound(DegenerateRound):
    """A round representing that decision-making has finished without redeeming."""


class FinishedWithoutDecisionRound(DegenerateRound):
    """A round representing that decision-making has finished without deciding on a bet."""


class RefillRequiredRound(DegenerateRound):
    """A round representing that a refill is required for placing a bet."""


class BenchmarkingDoneRound(DegenerateRound):
    """A round representing that the benchmarking has finished."""

    def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
        """Gracefully stop the service."""
        sys.exit(0)


class ImpossibleRound(DegenerateRound):
    """A round representing that decision-making is impossible with the given parametrization."""
