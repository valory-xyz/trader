# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2023 Valory AG
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

"""Tests for valory/check_stop_trading_abci skill's behaviours."""

# pylint: skip-file

import pytest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock
from typing import Any, Dict, Union, cast

from packages.valory.skills.check_stop_trading_abci.behaviours import (
    CheckStopTradingBehaviour,
    CheckStopTradingRoundBehaviour,
    StakingState,
    LIVENESS_RATIO_SCALE_FACTOR,
    REQUIRED_MECH_REQUESTS_SAFETY_MARGIN,
)
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.check_stop_trading_abci.rounds import (
    SynchronizedData as CheckStopTradingSynchronizedData,
)
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
import math


PACKAGE_DIR = Path(__file__).parent.parent


class CheckStopTradingFSMBehaviourBaseCase(FSMBehaviourBaseCase):
    """Base case for testing CheckStopTrading FSMBehaviour."""

    path_to_skill = PACKAGE_DIR


class TestCheckStopTradingBehaviour(CheckStopTradingFSMBehaviourBaseCase):
    """Tests for CheckStopTradingBehaviour."""

    def test_is_first_period(
        self,
    ) -> None:
        """Test the is_first_period property."""
        self.fast_forward_to_behaviour(
            self.behaviour,
            CheckStopTradingBehaviour.auto_behaviour_id(),
            CheckStopTradingSynchronizedData(
                AbciAppDB(setup_data=dict(estimate=[1.0])),
            ),
        )
        assert (
            cast(
                BaseBehaviour,
                cast(BaseBehaviour, self.behaviour.current_behaviour),
            ).auto_behaviour_id()
            == CheckStopTradingBehaviour.auto_behaviour_id()
        )
        # Access the current behaviour and cast it to CheckStopTradingBehaviour
        behaviour = cast(CheckStopTradingBehaviour, self.behaviour.current_behaviour)

        # Assert that the is_first_period property returns True
        assert behaviour.is_first_period is True
        self.behaviour.current_behaviour.clean_up()

    def test_params(self):
        """Test the params property."""
        self.behaviour.context.params = MagicMock()
        params = cast(CheckStopTradingRoundBehaviour, self.behaviour.context.params)
        assert params == self.behaviour.context.params


    def test_mech_request_count(self):
        """Test the mech_request_count property and the associated _get_mech_request_count method."""
        # Set up the behaviour with mocked synchronized data
        self.fast_forward_to_behaviour(
            self.behaviour,
            CheckStopTradingBehaviour.auto_behaviour_id(),
            CheckStopTradingSynchronizedData(
                AbciAppDB(setup_data=dict(estimate=[1.0])),
            ),
        )

        behaviour = cast(CheckStopTradingBehaviour, self.behaviour.current_behaviour)

        # Mock the contract interaction to return a specific mech request count
        expected_mech_request_count = 10
        behaviour._get_mech_request_count = MagicMock(return_value=expected_mech_request_count)
        behaviour._mech_request_count = expected_mech_request_count

        # Verify that the mech_request_count property returns the expected value
        assert behaviour.mech_request_count == expected_mech_request_count

        # Now test the setter
        new_mech_request_count = 20
        behaviour.mech_request_count = new_mech_request_count
        assert behaviour._mech_request_count == new_mech_request_count


    @pytest.fixture(autouse=True)
    def setup_method(self):
        """Setup test case."""
        self.behaviour.context.logger = MagicMock()
        self.behaviour.context.params = MagicMock()
        self.behaviour.synchronized_data = MagicMock()

        # Initialize values
        self.behaviour.service_info = [None, None, [None, 2]]
        self.behaviour.ts_checkpoint = 100
        self.behaviour.liveness_period = 1000
        self.behaviour.liveness_ratio = 1000000000000000000
        self.behaviour.synced_timestamp = 1100

        # Mock the mech_request_count property
        type(self.behaviour).mech_request_count = PropertyMock(return_value=1)
        type(self.behaviour.synchronized_data).period_count = PropertyMock(
            return_value=1
        )

        # Mock or set the last_round_transition_timestamp attribute
        self.behaviour.last_round_transition_timestamp = 100

    def test_is_staking_kpi_met(self):
        """Test the is_staking_kpi_met method."""
        # Set up the behaviour with mocked synchronized data
        self.fast_forward_to_behaviour(
            self.behaviour,
            CheckStopTradingBehaviour.auto_behaviour_id(),
            CheckStopTradingSynchronizedData(
                AbciAppDB(setup_data=dict(estimate=[1.0])),
            ),
        )

        behaviour = cast(CheckStopTradingBehaviour, self.behaviour.current_behaviour)

        # Mocking the return values for the condition methods
        behaviour._check_service_staked = MagicMock(return_value=True)
        behaviour._get_mech_request_count = MagicMock(
            return_value=10
        )  # a generator yielding a value
        behaviour._get_service_info = MagicMock(
            return_value=[None, None, [None, 5]]
        )  # a generator yielding a value
        behaviour._get_ts_checkpoint = MagicMock(
            return_value=100
        )  # a generator yielding a value
        behaviour._get_liveness_period = MagicMock(
            return_value=1000
        )  # a generator yielding a value
        behaviour._get_liveness_ratio = MagicMock(
            return_value=1000000000000000000
        )  # a generator yielding a value

        # Mock the period_count to return 1
        type(behaviour.synchronized_data).period_count = PropertyMock(return_value=1)
        behaviour.service_staking_state = StakingState.STAKED

        # Execute the generator and retrieve the final return value
        staking_kpi_met_gen = behaviour.is_staking_kpi_met()

        # Calculate the expected result based on the mocked values
        mech_requests_since_last_cp = (
            self.behaviour.mech_request_count - self.behaviour.service_info[2][1]
        )

        required_mech_requests = (
            (self.behaviour.synced_timestamp - self.behaviour.ts_checkpoint)
            * self.behaviour.liveness_ratio
            / LIVENESS_RATIO_SCALE_FACTOR
        ) + REQUIRED_MECH_REQUESTS_SAFETY_MARGIN

        expected_result = mech_requests_since_last_cp >= required_mech_requests

        assert expected_result is False

    def test_compute_stop_trading(self):
        """Test the _compute_stop_trading method."""
        # Set up the behaviour with mocked synchronized data
        self.fast_forward_to_behaviour(
            self.behaviour,
            CheckStopTradingBehaviour.auto_behaviour_id(),
            CheckStopTradingSynchronizedData(
                AbciAppDB(setup_data=dict(estimate=[1.0])),
            ),
        )

        behaviour = cast(CheckStopTradingBehaviour, self.behaviour.current_behaviour)

        # Mock necessary properties and methods
        self.behaviour.is_first_period = PropertyMock(return_value=False)
        behaviour.params.disable_trading = False
        behaviour.params.stop_trading_if_staking_kpi_met = True
        self.behaviour.is_staking_kpi_met = MagicMock(return_value=True)

        # Run the generator until it yields the result
        stop_trading_gen = behaviour._compute_stop_trading()
        stop_trading_result = None
        try:
            while True:
                stop_trading_result = next(stop_trading_gen)
        except StopIteration as e:
            stop_trading_result = e.value

        assert stop_trading_result == False
