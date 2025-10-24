# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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

import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, Union
from unittest import mock
from unittest.mock import MagicMock

import pytest
from aea.configurations.base import PackageConfiguration
from hypothesis import given, settings
from hypothesis import strategies as st

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
from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader
from packages.valory.skills.decision_maker_abci.tests.conftest import profile_name
from packages.valory.skills.market_manager_abci.behaviours import READ_MODE


settings.load_profile(profile_name)
FRACTION_REMOVAL_PRECISION = 2
CURRENT_FILE_PATH = Path(__file__).resolve()
PACKAGE_DIR = CURRENT_FILE_PATH.parents[2]
DUMMY_STRATEGY_PATH = CURRENT_FILE_PATH.parent / "./dummy_strategy/dummy_strategy.py"

# fmt: off
STRATEGIES_KWARGS = {"bet_kelly_fraction": 1.0, "floor_balance": int(5e18), "bet_amount_per_threshold": {"0.0": 0, "0.1": 0, "0.2": 0, "0.3": 0, "0.4": 0, "0.5": 0, "0.6": int(6e16), "0.7": int(9e16), "0.8": int(1e17), "0.9": int(1e18), "1.0": int(1e19)}}

STRATEGY_TO_FILEPATH = {"bet_amount_per_threshold": "packages/valory/customs/bet_amount_per_threshold", "kelly_criterion_no_conf": "packages/valory/customs/kelly_criterion_no_conf"}
# fmt: on

DefaultValueType = TypeVar("DefaultValueType")
ExecutablesMockReturnType = Union[Tuple[str, str], DefaultValueType]


def strategies_executables_get_mock_wrapper(
    mock_strategy_name: str,
    mock_method_name: str,
) -> Callable[[str, Any], ExecutablesMockReturnType]:
    """Wrapper to mock the strategies executables dict's `get` method."""

    def strategies_executables_get_mock(
        strategy_name: str, default: DefaultValueType
    ) -> ExecutablesMockReturnType:
        """Mock the strategies executables dict's `get` method."""
        with open(DUMMY_STRATEGY_PATH, READ_MODE) as strategy_file:
            dummy_strategy = strategy_file.read()
        return (
            (dummy_strategy, mock_method_name)
            if strategy_name == mock_strategy_name
            else default
        )

    return strategies_executables_get_mock


def folder_to_serialized_objects(folder_path: str) -> dict[str, str]:
    """Convert all files in a folder to a dict of serialized objects."""
    serialized_objects: dict[str, str] = {}

    for root, _, files in os.walk(folder_path):
        for file in files:
            full_path = os.path.join(root, file)
            relative_path = os.path.relpath(full_path, folder_path)
            with open(full_path, "r", encoding="utf-8") as f:
                serialized_objects[relative_path] = f.read()

    return serialized_objects


def get_strategy_executables() -> Dict[str, Tuple[str, str]]:
    """Load strategy executables from their respective folders."""

    strategy_hm = {}
    for strategy_name, folder_path in STRATEGY_TO_FILEPATH.items():
        _, strategy_exec, callable_method = ComponentPackageLoader.load(
            folder_to_serialized_objects(folder_path)
        )
        strategy_hm[strategy_name] = (
            strategy_exec,
            callable_method,
        )
    return strategy_hm


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

    behaviour: BlacklistingBehaviour
    path_to_skill = PACKAGE_DIR

    @classmethod
    def setup_class(cls, **kwargs: Any) -> None:
        """Set up the class."""
        kwargs["config_overrides"] = {
            "models": {
                "params": {
                    "args": {
                        "use_acn_for_delivers": True,
                    }
                }
            }
        }
        with mock.patch.object(PackageConfiguration, "check_overrides_valid"):
            super().setup_class(**kwargs)

    def setup(self, **kwargs: Any) -> None:
        """Setup."""
        self.round_sequence_mock = MagicMock()
        context_mock = MagicMock(params=MagicMock())
        context_mock.state.round_sequence = self.round_sequence_mock
        context_mock.state.round_sequence.syncing_up = False
        context_mock.state.synchronized_data.db.get_strict = lambda _: 0
        self.round_sequence_mock.block_stall_deadline_expired = False
        self.behaviour = BlacklistingBehaviour(name="", skill_context=context_mock)
        self.benchmark_dir = MagicMock()

    @given(strategy_executables())
    def test_strategy_exec(
        self,
        strategy: Tuple[str, Dict[str, Tuple[str, str]], Optional[str]],
    ) -> None:
        """Test the `strategy_exec` method."""
        strategy_name, strategies_executables, expected_result = strategy
        self.behaviour.shared_state.strategies_executables = strategies_executables
        res = self.behaviour.strategy_exec(strategy_name)
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
        behaviour = self.behaviour
        strategy_key = "trading_strategy"
        if strategy_key in kwargs:
            behaviour.shared_state.strategies_executables.get = (  # type: ignore
                strategies_executables_get_mock_wrapper(
                    kwargs[strategy_key],
                    method_name,  # type: ignore
                )
            )

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
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = benchmarking_mode_enabled
        with mock.patch.object(behaviour, "read_bets"):
            collateral_token = WXDAI if is_wxdai else "unknown"
            behaviour.bets = [mock.MagicMock(collateralToken=collateral_token)]
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
        behaviour = self.behaviour
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
    def test_get_bet_amount(
        self,
        mocked_result: int,
        expected_result: int,
    ) -> None:
        """Test the `get_bet_amount` method."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore
        behaviour.execute_strategy = lambda *_, **__: mocked_result  # type: ignore
        gen = behaviour.get_bet_amount(
            0,
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

    @pytest.mark.parametrize(
        "trading_strategy, win_probability, confidence, selected_type_tokens_in_pool, other_tokens_in_pool, bet_fee, weighted_accuracy, token_balance, wallet_balance, expected_result",
        # fmt: off
        (
            # bet amount per threshold strategy
            ("bet_amount_per_threshold", 0.0, 0.1, 0.1, 0, 0, 0.0, 0, 0, 0),
            ("bet_amount_per_threshold", 0.0, 0.6, 0.1, 0, 0, 0.0, 0, 0, int(6e16)),
            ("bet_amount_per_threshold", 0.0, 0.8, 0.1, 0, 0, 0.0, 0, 0, int(1e17)),
            ("bet_amount_per_threshold", 0.0, 0.9, 0.1, 0, 0, 0.0, 0, 0, int(1e18)),
            # kelly criterion no confidence strategy
            ("kelly_criterion_no_conf", 0.85, 0.0, 100, 200, int(1e15), 0.75, int(5e19), 0, 243),
            ("kelly_criterion_no_conf", 0.80, 0.0, 150, 100, int(5e14), 0.90, int(7.5e19), int(1e19), 37_241_555_003),
            ("kelly_criterion_no_conf", 0.95, 0.0, 150, 100, int(5e14), 0.90, int(7.5e19), int(1e19), 1_139_999_999_999_998_976),
            ("kelly_criterion_no_conf", 0.20, 0.0, 150, 100, int(5e14), 0.90, int(7.5e19), int(1e19), 0),

        ),
        ids=[
            "bet_amount_per_threshold_0",
            "bet_amount_per_threshold_high",
            "bet_amount_per_threshold_higher",
            "bet_amount_per_threshold_very_high",
            "kelly_criterion_no_conf_low",
            "kelly_criterion_no_conf_medium",
            "kelly_criterion_no_conf_high",
            "kelly_criterion_no_conf_zero",
        ],
        # fmt: on
    )
    def test_bet_amount_based_on_strategy(
        self,
        trading_strategy: str,
        win_probability: float,
        confidence: float,
        selected_type_tokens_in_pool: int,
        other_tokens_in_pool: int,
        bet_fee: int,
        weighted_accuracy: float,
        token_balance: int,
        wallet_balance: int,
        expected_result: int,
    ) -> None:
        """Test the `get_bet_amount` method."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore
        behaviour.params.strategies_kwargs = STRATEGIES_KWARGS
        behaviour.shared_state.chatui_config.trading_strategy = trading_strategy
        behaviour.params.use_fallback_strategy = False
        behaviour.shared_state.strategies_executables = get_strategy_executables()
        behaviour.token_balance = token_balance
        behaviour.wallet_balance = wallet_balance

        get_bet_amount_generator = behaviour.get_bet_amount(
            win_probability,
            confidence,
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            bet_fee,
            weighted_accuracy,
        )
        for _ in range(2):
            # `download_strategies` and `wait_for_condition_with_sleep` mock calls
            next(get_bet_amount_generator)
        try:
            next(get_bet_amount_generator)
        except StopIteration as e:
            assert int(e.value) == int(expected_result)
        else:
            raise AssertionError("Expected `StopIteration` exception!")
