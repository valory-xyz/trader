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

"""Test the models.py module of the CheckStopTrading skill."""

from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext
from packages.valory.skills.abstract_round_abci.tests.test_models import BASE_DUMMY_PARAMS
from packages.valory.skills.check_stop_trading_abci.models import SharedState, CheckStopTradingParams


class TestCheckStopTradingParams:
    """Test CheckStopTradingParams of CheckStopTrading."""

    def test_initialization(self) -> None:
        """ Test initialization."""

        CheckStopTradingParams(disable_trading=True,
                               stop_trading_if_staking_kpi_met=True,
                               staking_contract_address="",
                               staking_interaction_sleep_time=1,
                               mech_activity_checker_contract="",
                               **BASE_DUMMY_PARAMS,
                               )


class TestSharedState:
    """Test SharedState of CheckStopTrading."""

    def test_initialization(self) -> None:
        """Test initialization."""
        SharedState(name="", skill_context=DummyContext())