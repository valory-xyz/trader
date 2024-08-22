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

"""Tests for valory/staking_abci skill's behaviours."""

import pytest
from pathlib import Path
from typing import Any, Dict, Type, Optional, cast
from dataclasses import dataclass
from datetime import datetime
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    BaseBehaviour,
    make_degenerate_behaviour,
)
from packages.valory.skills.staking_abci.behaviours import (
    CallCheckpointBehaviour,
    StakingRoundBehaviour,
)
from packages.valory.skills.staking_abci.rounds import (
    Event,
    SynchronizedData,
    FinishedStakingRound,
    StakingState,
    CheckpointCallPreparedRound,
)
from packages.valory.skills.staking_abci.models import SharedState
from aea.exceptions import AEAActException  # type: ignore

PACKAGE_DIR = Path(__file__).parent.parent


@dataclass
class BehaviourTestCase:
    """BehaviourTestCase"""

    name: str
    initial_data: Dict[str, Any]
    event: Event
    next_behaviour_class: Optional[Type[BaseBehaviour]] = None


class BaseBehaviourTest(FSMBehaviourBaseCase):
    """Base test case."""

    path_to_skill = PACKAGE_DIR

    behaviour: StakingRoundBehaviour
    behaviour_class: Type[CallCheckpointBehaviour]
    next_behaviour_class: Type[CallCheckpointBehaviour]
    synchronized_data: SynchronizedData
    done_event = Event.DONE

    def fast_forward(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Fast-forward on initialization"""

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
        """Complete test"""
        self.behaviour.act_wrapper()
        self.mock_a2a_transaction()
        self._test_done_flag_set()
        self.end_round(done_event=event)
        assert (
            self.behaviour.current_behaviour.auto_behaviour_id()  # type: ignore
            == self.next_behaviour_class.auto_behaviour_id()
        )


class TestStackingBehaviour(BaseBehaviourTest):
    """Test cases for the stacking behaviour."""

    behaviour_class: Type[BaseBehaviour] = CallCheckpointBehaviour

    @pytest.mark.parametrize(
        "test_case",
        [
            BehaviourTestCase(
                name="successful stacking",
                initial_data={
                    # "service_staking_state": StakingState.STAKED.value,
                    "is_checkpoint_reached": True,
                    "safe_contract_address": "safe_contract_address",
                },
                event=Event.DONE,
                next_behaviour_class=make_degenerate_behaviour(
                    CheckpointCallPreparedRound
                ),
            ),
        ],
    )
    def test_run(self, test_case: BehaviourTestCase) -> None:
        """Run the behaviour tests."""
        self.next_behaviour_class = test_case.next_behaviour_class
        params = cast(SharedState, self._skill.skill_context.params)
        params.__dict__["_frozen"] = False

        # Set params using the `initial_data` mapping
        self.set_params(
            params,
            {
                "on_chain_service_id": "new_on_chain_service_id",
                # Add more mappings here if needed
            },
        )

        self.fast_forward(test_case.initial_data)

        # with pytest.raises(AEAActException, match=test_case.raises_message):
        #     self.behaviour.act_wrapper()

        self.complete(test_case.event)

    def set_params(self, params: SharedState, param_mapping: Dict[str, Any]) -> None:
        """Set parameters based on the provided mapping."""
        for param_name, param_value in param_mapping.items():
            setattr(params, param_name, param_value)
