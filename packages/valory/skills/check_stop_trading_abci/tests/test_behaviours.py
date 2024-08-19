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

"""Tests for valory/check_stop_trading_abci skill's behaviours."""

# pylint: skip-file

import pytest
from pathlib import Path
from typing import Any, Dict, Type, Optional, cast
from dataclasses import dataclass
from datetime import datetime
from packages.valory.skills.check_stop_trading_abci.behaviours import (
    CheckStopTradingBehaviour,
    CheckStopTradingRoundBehaviour,
)
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    BaseBehaviour,
    make_degenerate_behaviour,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    Event,
    SynchronizedData,
    FinishedCheckStopTradingRound,
)
from packages.valory.skills.staking_abci.rounds import StakingState

PACKAGE_DIR = Path(__file__).parent.parent


@dataclass
class BehaviourTestCase:
    """Behaviour test case structure."""

    name: str
    initial_data: Dict[str, Any]
    event: Event
    next_behaviour_class: Optional[Type[BaseBehaviour]] = None


class BaseBehaviourTest(FSMBehaviourBaseCase):
    """Base test case."""

    path_to_skill = Path(__file__).parent.parent

    behaviour: CheckStopTradingRoundBehaviour
    behaviour_class: Type[CheckStopTradingBehaviour]
    next_behaviour_class: Type[CheckStopTradingBehaviour]
    synchronized_data: SynchronizedData
    done_event = Event.DONE

    def fast_forward(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Fast-forward to behavior."""
        data = data if data is not None else {}
        self.fast_forward_to_behaviour(
            self.behaviour,  # type: ignore
            self.behaviour_class.auto_behaviour_id(),
            SynchronizedData(AbciAppDB(setup_data=AbciAppDB.data_to_lists(data))),
        )
        self.skill.skill_context.state.round_sequence._last_round_transition_timestamp = (
            datetime.now()
        )

        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.behaviour_class.auto_behaviour_id()
        )

    def complete(self, event: Event) -> None:
        """Complete the behavior execution."""
        self.behaviour.act_wrapper()
        self.mock_a2a_transaction()
        self._test_done_flag_set()
        self.end_round(done_event=event)
        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.next_behaviour_class.auto_behaviour_id()
        )


class TestCheckStopTradingBehaviour(BaseBehaviourTest):
    """Test the CheckStopTradingBehaviour."""

    behaviour_class: Type[BaseBehaviour] = CheckStopTradingBehaviour
    next_behaviour_class: Type[BaseBehaviour] = make_degenerate_behaviour(
        FinishedCheckStopTradingRound
    )

    @pytest.mark.parametrize(
        "test_case",
        [
            # Existing happy path test
            BehaviourTestCase(
                name="happy path",
                event=Event.DONE,
                initial_data={},
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            # Test for staking KPI met
            BehaviourTestCase(
                name="staking KPI met",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": StakingState.STAKED.value,  # Convert to int or use .name for string
                    "mech_request_count": 10,
                    "mech_request_count_on_last_checkpoint": 5,
                    "liveness_period": 100,
                    "liveness_ratio": 200,
                    "ts_checkpoint": 1000,
                    "synced_timestamp": 1100,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            # Test for initial period
            BehaviourTestCase(
                name="initial period",
                event=Event.DONE,
                initial_data={
                    "period_count": 0,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            # Test for disable trading
            BehaviourTestCase(
                name="disable trading",
                event=Event.DONE,
                initial_data={
                    "disable_trading": True,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            # Test for staking KPI not met
            BehaviourTestCase(
                name="staking KPI not met",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": [
                        StakingState.UNSTAKED.value
                    ],  # or StakingState.STAKED.value
                    "mech_request_count": [5],
                    "mech_request_count_on_last_checkpoint": [5],
                    "liveness_period": [100],
                    "liveness_ratio": [200],
                    "ts_checkpoint": [1000],
                    "synced_timestamp": [1100],
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            BehaviourTestCase(
                name="edge case for KPI calculation",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": StakingState.STAKED.value,
                    "mech_request_count": 20,
                    "mech_request_count_on_last_checkpoint": 10,
                    "liveness_period": 100,
                    "liveness_ratio": 200,
                    "ts_checkpoint": 1000,
                    "synced_timestamp": 1200,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            BehaviourTestCase(
                name="boundary conditions",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": StakingState.STAKED.value,
                    "mech_request_count": 0,
                    "mech_request_count_on_last_checkpoint": 0,
                    "liveness_period": 0,
                    "liveness_ratio": 0,
                    "ts_checkpoint": 0,
                    "synced_timestamp": 0,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            BehaviourTestCase(
                name="incorrect data types",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": "not_a_valid_state",
                    "mech_request_count": "invalid_type",
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            BehaviourTestCase(
                name="parameter missing",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": StakingState.STAKED.value,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
            BehaviourTestCase(
                name="non-staked service",
                event=Event.DONE,
                initial_data={
                    "service_staking_state": StakingState.EVICTED.value,
                },
                next_behaviour_class=make_degenerate_behaviour(
                    FinishedCheckStopTradingRound
                ),
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase) -> None:
        self.fast_forward(test_case.initial_data)
        self.complete(test_case.event)
