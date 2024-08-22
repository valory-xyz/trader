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

"""Test the models.py module of the StakingAbci skill."""
from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext
from packages.valory.skills.abstract_round_abci.tests.test_models import BASE_DUMMY_PARAMS
from packages.valory.skills.staking_abci.models import SharedState, StakingParams


class TestStakingParams:
    """Test StakingParams of the StakingAbci."""

    def test_initialization(self) -> None:
        """Test initialization."""
        StakingParams(**BASE_DUMMY_PARAMS,
                      staking_contract_address="test",
                      staking_interaction_sleep_time=1,
                      mech_activity_checker_contract="test")


class TestSharedState:
    """Test SharedState of StakingAbci."""

    def test_initialization(self) -> None:
        """Test initialization."""
        SharedState(name="", skill_context=DummyContext())