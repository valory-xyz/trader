# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for the behaviours module of the trader_abci skill."""

# pylint: skip-file

from packages.valory.skills.abstract_round_abci.behaviours import BaseBehaviour
from packages.valory.skills.trader_abci.behaviours import TraderConsensusBehaviour


def test_behaviours_set_contains_base_behaviours() -> None:
    """Test that all elements in the behaviours set are BaseBehaviour subclasses."""
    for behaviour_cls in TraderConsensusBehaviour.behaviours:
        assert issubclass(
            behaviour_cls, BaseBehaviour
        ), f"{behaviour_cls} is not a subclass of BaseBehaviour"
