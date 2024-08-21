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
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    BET_AMOUNT_FIELD,
    DecisionMakerBaseBehaviour,
    WXDAI,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.states.base import SynchronizedData
from packages.valory.skills.decision_maker_abci.tests.conftest import profile_name


settings.load_profile(profile_name)
FRACTION_REMOVAL_PRECISION = 2
CURRENT_FILE_PATH = Path(__file__).resolve()
PACKAGE_DIR = CURRENT_FILE_PATH.parents[2]


@st.composite
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


@given(amount=st.integers(), fraction=st.floats().filter(lambda x: x < 0 or x > 1))
def test_remove_fraction_wei_incorrect_fraction(amount: int, fraction: float) -> None:
    """Test the `remove_fraction_wei` function."""
    with pytest.raises(
        ValueError,
        match=re.escape(f"The given fraction {fraction!r} is not in the range [0, 1]."),
    ):
        remove_fraction_wei(amount, fraction)


@st.composite
def strategy_executables(
    draw: st.DrawFn,
) -> Tuple[str, Dict[str, Tuple[str, str]], Optional[Tuple[str, str]]]:
    """A strategy for building valid availability window data."""
    strategy_name = draw(st.text())
    expected_result = draw(st.tuples(st.text(), st.text()))
    negative_case = draw(st.booleans())

    if negative_case:
        return strategy_name, {}, None

    return strategy_name, {strategy_name: expected_result}, expected_result


class TestDecisionMakerBaseBehaviour(FSMBehaviourBaseCase):
    """Test `DecisionMakerBaseBehaviour`."""

    path_to_skill = PACKAGE_DIR

    def ffw(self, behaviour_cls: Any, db_items: Optional[Dict] = None) -> None:
        """Fast-forward to the given behaviour."""
        if db_items is None:
            db_items = {}

        self.fast_forward_to_behaviour(
            behaviour=self.behaviour,
            behaviour_id=behaviour_cls.auto_behaviour_id(),
            synchronized_data=SynchronizedData(
                AbciAppDB(setup_data=AbciAppDB.data_to_lists(db_items))
            ),
        )

    @given(strategy_executables())
    def test_strategy_exec(
        self, strategy: Tuple[str, Dict[str, Tuple[str, str]], Optional[str]]
    ) -> None:
        """Test the `strategy_exec` method."""
        strategy_name, strategies_executables, expected_result = strategy
        # use `BlacklistingBehaviour` because it overrides the `DecisionMakerBaseBehaviour`.
        self.ffw(BlacklistingBehaviour)
        behaviour = cast(BlacklistingBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == BlacklistingBehaviour.auto_behaviour_id()
        behaviour.shared_state.strategies_executables = strategies_executables
        res = behaviour.strategy_exec(strategy_name)
        assert res == expected_result

    @pytest.mark.parametrize(
        "strategy_path", (Path("dummy_strategy/dummy_strategy.py"),)
    )
    @pytest.mark.parametrize(
        "args, kwargs, method_name, expected_result",
        (
            ((), {}, "", {BET_AMOUNT_FIELD: 0}),
            ((), {"unexpected_field": "test"}, "", {BET_AMOUNT_FIELD: 0}),
            ((), {"trading_strategy": None}, "", {BET_AMOUNT_FIELD: 0}),
            (
                (),
                {"trading_strategy": "non_existing_strategy"},
                "",
                {BET_AMOUNT_FIELD: 0},
            ),
            (
                (),
                {"trading_strategy": "test"},
                "non_existing_method",
                {BET_AMOUNT_FIELD: 0},
            ),
            ((), {"trading_strategy": "test"}, "dummy", "dummy"),
        ),
    )
    def test_execute_strategy(
        self,
        strategy_path: str,
        args: tuple,
        kwargs: dict,
        method_name: str,
        expected_result: int,
    ) -> None:
        """Test the `execute_strategy` method."""
        # use `BlacklistingBehaviour` because it overrides the `DecisionMakerBaseBehaviour`.
        self.ffw(BlacklistingBehaviour)
        behaviour = cast(BlacklistingBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == BlacklistingBehaviour.auto_behaviour_id()
        current_dir = CURRENT_FILE_PATH.parent
        with open(current_dir / strategy_path) as dummy_strategy:
            behaviour.shared_state.strategies_executables["test"] = (
                dummy_strategy.read(),
                method_name,
            )

        res = behaviour.execute_strategy(*args, **kwargs)
        assert res == expected_result

    @given(st.integers())
    def test_wei_to_native(self, wei: int) -> None:
        """Test the `wei_to_native` method."""
        result = DecisionMakerBaseBehaviour.wei_to_native(wei)
        assert isinstance(result, float)
        assert result == wei / 10**18

    @given(st.integers(), st.booleans(), st.booleans())
    def test_collateral_amount_info(
        self, amount: int, benchmarking_mode_enabled: bool, is_wxdai: bool
    ) -> None:
        """Test the `collateral_amount_info` method."""
        # use `BlacklistingBehaviour` because it overrides the `DecisionMakerBaseBehaviour`.
        self.ffw(BlacklistingBehaviour, {"sampled_bet_index": 0})
        behaviour = cast(BlacklistingBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == BlacklistingBehaviour.auto_behaviour_id()

        behaviour.benchmarking_mode.enabled = benchmarking_mode_enabled
        with mock.patch.object(behaviour, "read_bets"):
            collateral_token = WXDAI if is_wxdai else "unknown"
            behaviour.bets = [(mock.MagicMock(collateralToken=collateral_token))]
            result = behaviour._collateral_amount_info(amount)

        if benchmarking_mode_enabled or is_wxdai:
            assert result == f"{behaviour.wei_to_native(amount)} wxDAI"
        else:
            assert (
                result
                == f"{amount} WEI of the collateral token with address {collateral_token}"
            )

    @given(st.integers(), st.integers())
    def test_mock_balance_check(
        self, collateral_balance: int, native_balance: int
    ) -> None:
        """Test the `_mock_balance_check` method."""
        # use `BlacklistingBehaviour` because it overrides the `DecisionMakerBaseBehaviour`.
        self.ffw(BlacklistingBehaviour)
        behaviour = cast(BlacklistingBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == BlacklistingBehaviour.auto_behaviour_id()

        behaviour.benchmarking_mode.collateral_balance = collateral_balance
        behaviour.benchmarking_mode.native_balance = native_balance
        with mock.patch.object(behaviour, "_report_balance") as mock_report_balance:
            behaviour._mock_balance_check()
            mock_report_balance.assert_called_once()
        assert behaviour.token_balance == collateral_balance
        assert behaviour.wallet_balance == native_balance

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
    def test_get_bet_amount(self, mocked_result: int, expected_result: int) -> None:
        """Test the `get_bet_amount` method."""
        # use `BlacklistingBehaviour` because it overrides the `DecisionMakerBaseBehaviour`.
        self.ffw(BlacklistingBehaviour)
        behaviour = cast(BlacklistingBehaviour, self.behaviour.current_behaviour)
        assert behaviour.behaviour_id == BlacklistingBehaviour.auto_behaviour_id()
        behaviour.download_strategies = lambda: (yield)  # type: ignore
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore
        behaviour.execute_strategy = lambda *_, **__: mocked_result  # type: ignore
        gen = behaviour.get_bet_amount(0, 0, 0, 0, 0, 0)
        for _ in range(2):
            # `download_strategies` and `wait_for_condition_with_sleep` mock calls
            next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value == expected_result
        else:
            raise AssertionError("Expected `StopIteration` exception!")
