# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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

"""This module contains the tests for valory/decision_maker_abci's base behaviour."""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    BET_AMOUNT_FIELD,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData
from packages.valory.skills.decision_maker_abci.tests.conftest import profile_name


settings.load_profile(profile_name)
FRACTION_REMOVAL_PRECISION = 2
PACKAGE_DIR = Path(__file__).parents[2]


@composite
def remove_fraction_args(draw: st.DrawFn) -> Tuple[int, float, int]:
    """A strategy for building the values of the `test_remove_fraction_wei` with the desired constraints."""
    amount = draw(st.integers())
    fraction = draw(st.floats(min_value=0, max_value=1))
    keep_percentage = 1 - fraction
    assert 0 <= keep_percentage <= 1
    expected = int(amount * keep_percentage)
    return amount, fraction, expected


@given(remove_fraction_args())
def test_remove_fraction_wei(strategy: Tuple[int, float, int]) -> None:
    """Test the `remove_fraction_wei` function."""
    amount, fraction, expected = strategy
    assert remove_fraction_wei(amount, fraction) == expected


@given(
    amount=st.integers(),
    fraction=st.floats().filter(lambda x: x < 0 or x > 1),
)
def test_remove_fraction_wei_incorrect_fraction(amount: int, fraction: float) -> None:
    """Test the `remove_fraction_wei` function."""
    with pytest.raises(
        ValueError,
        match=re.escape(f"The given fraction {fraction!r} is not in the range [0, 1]."),
    ):
        remove_fraction_wei(amount, fraction)


class TestDecisionMakerBaseBehaviour(FSMBehaviourBaseCase):
    """Test `DecisionMakerBaseBehaviour`."""

    path_to_skill = PACKAGE_DIR

    def ffw(
        self,
        behaviour_cls: Any,
        db_items: Optional[Dict] = None,
    ) -> None:
        """Fast-forward to the given behaviour."""
        if db_items is None:
            db_items = {}

        self.fast_forward_to_behaviour(
            behaviour=self.behaviour,
            behaviour_id=behaviour_cls.auto_behaviour_id(),
            synchronized_data=SynchronizedData(
                AbciAppDB(
                    setup_data=AbciAppDB.data_to_lists(db_items),
                )
            ),
        )

    @pytest.mark.parametrize(
        "mocked_result, expected_result",
        (
            ({}, 0),
            ({"not the correct field": 80}, 0),
            ({BET_AMOUNT_FIELD: 0}, 0),
            ({BET_AMOUNT_FIELD: -10}, -10),
            ({BET_AMOUNT_FIELD: 10}, 10),
            ({BET_AMOUNT_FIELD: 23456}, 23456),
        ),
    )
    def test_get_bet_amount(
        self,
        mocked_result: int,
        expected_result: int,
    ) -> None:
        """Test the `get_bet_amount` method."""
        # use `BlacklistingBehaviour` because it overrides the `DecisionMakerBaseBehaviour`.
        self.ffw(BlacklistingBehaviour)
        behaviour = cast(BlacklistingBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == BlacklistingBehaviour.auto_behaviour_id()
        behaviour.download_strategies = lambda: (yield)  # type: ignore
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore
        behaviour.execute_strategy = lambda *_, **__: mocked_result  # type: ignore
        gen = behaviour.get_bet_amount(
            0,
            0,
            0,
            0,
            0,
        )
        for _ in range(2):
            # `download_strategies` and `wait_for_condition_with_sleep` mock calls
            next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value == expected_result
        else:
            raise AssertionError("Expected `StopIteration` exception!")
