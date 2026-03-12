# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2026 Valory AG
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
import tempfile
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple, TypeVar, Union
from unittest import mock
from unittest.mock import MagicMock, PropertyMock

import pytest
from aea.configurations.base import PackageConfiguration
from aea.configurations.data_types import PublicId
from hexbytes import HexBytes
from hypothesis import given, settings
from hypothesis import strategies as st

from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import TimeoutException
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    BET_AMOUNT_FIELD,
    DecisionMakerBaseBehaviour,
    MultisendBatch,
    TradingOperation,
    USCDE_POLYGON,
    USDC_POLYGON,
    WXDAI,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader
from packages.valory.skills.decision_maker_abci.models import (
    BenchmarkingMockData,
    LiquidityInfo,
)
from packages.valory.skills.decision_maker_abci.tests.conftest import profile_name
from packages.valory.skills.market_manager_abci.behaviours.base import READ_MODE
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH

settings.load_profile(profile_name)
FRACTION_REMOVAL_PRECISION = 2
CURRENT_FILE_PATH = Path(__file__).resolve()
PACKAGE_DIR = CURRENT_FILE_PATH.parents[2]
DUMMY_STRATEGY_PATH = CURRENT_FILE_PATH.parent / "./dummy_strategy/dummy_strategy.py"

VALID_STRATEGY_FILE_EXTENSIONS = {".py", ".yaml", ".yml"}

# fmt: off
STRATEGIES_KWARGS = {"bet_kelly_fraction": 1.0, "floor_balance": int(5e17), "default_max_bet_size": int(2e18), "absolute_min_bet_size": int(1e16), "absolute_max_bet_size": int(2e18), "bet_amount_per_threshold": {"0.0": int(1e16), "0.1": int(1e16), "0.2": int(1e16), "0.3": int(1e16), "0.4": int(1e16), "0.5": int(1e16), "0.6": int(1e16), "0.7": int(1e16), "0.8": int(1e16), "0.9": (1e16), "1.0": (1e16)}}

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


def folder_to_serialized_objects(folder_path: str | Path) -> dict[str, str]:
    """Convert all files in a folder to a dict of serialized objects."""
    folder_path = Path(folder_path)
    serialized_objects: dict[str, str] = {}
    for file_path in folder_path.rglob("*"):
        if (
            not file_path.is_file()
            or file_path.suffix not in VALID_STRATEGY_FILE_EXTENSIONS
        ):
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except (
            UnicodeDecodeError,
            FileNotFoundError,
            PermissionError,
            IsADirectoryError,
        ) as e:
            raise RuntimeError(f"Failed to read {file_path}: {e}") from e
        relative_path = str(file_path.relative_to(folder_path))
        serialized_objects[relative_path] = text
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
                        "penalize_mech_time_window": 0,
                        "irrelevant_tools": [],
                        "ignored_mechs": [],
                        "deliveries_lookback_days": 30,
                        "store_path": tempfile.gettempdir(),
                    }
                }
            }
        }
        with mock.patch.object(PackageConfiguration, "check_overrides_valid"):
            super().setup_class(**kwargs)

    def setup_method(self, **kwargs: Any) -> None:
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
            behaviour.shared_state.strategies_executables.get = (  # type: ignore[method-assign]
                strategies_executables_get_mock_wrapper(  # type: ignore[assignment]
                    kwargs[strategy_key],
                    method_name,  # type: ignore[arg-type]
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
            assert result == f"{behaviour.wei_to_native(amount):6f} wxDAI"
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
        behaviour.download_strategies = lambda: (yield)  # type: ignore[assignment, method-assign]
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.execute_strategy = lambda *_, **__: mocked_result  # type: ignore[assignment, method-assign]
        gen = behaviour.get_bet_amount(
            0,
            0,
            0,
            0,
            0,
            0,
            "0x000000000000000000000000000000000000000",
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
        "trading_strategy, win_probability, confidence, selected_type_tokens_in_pool, other_tokens_in_pool, bet_fee, weighted_accuracy, token_balance, wallet_balance, expected_result, collateral_token",
        # fmt: off
        (
            # bet amount per threshold strategy
            ("bet_amount_per_threshold", 0.0, 0.1, 0.1, 0, 0, 0.0, 0, 0, int(1e16), "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"),
            ("bet_amount_per_threshold", 0.0, 0.6, 0.1, 0, 0, 0.0, 0, 0, int(1e16), "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"),
            # kelly criterion no confidence strategy
            ("kelly_criterion_no_conf", 0.75, 0.7, 6986284704175073976, 7013742221343643211, 10000000000000000, 0.90, 0, 2274727164028066772, 1582751545041709312, "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"),
            ("kelly_criterion_no_conf", 0.11, 0.51, 6986284704175073976, 7013742221343643211, 10000000000000000, 0.90, 0, 2274727164028066772, 0, "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"),
        ),
        ids=[
            "bet_amount_per_threshold_0",
            "bet_amount_per_threshold_fixed",
            "kelly_criterion_no_conf_real",
            "kelly_criterion_no_conf_zero"
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
        collateral_token: str,
    ) -> None:
        """Test the `get_bet_amount` method."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore[assignment, method-assign]
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.params.strategies_kwargs = STRATEGIES_KWARGS
        behaviour.shared_state.chatui_config.trading_strategy = trading_strategy
        behaviour.shared_state.chatui_config.max_bet_size = STRATEGIES_KWARGS["default_max_bet_size"]  # type: ignore[assignment]
        behaviour.shared_state.chatui_config.fixed_bet_size = STRATEGIES_KWARGS["absolute_min_bet_size"]  # type: ignore[assignment]
        behaviour.params.use_fallback_strategy = False
        behaviour.params.is_running_on_polymarket = (
            False  # TODO: Add tests for Polymarket
        )
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
            collateral_token,
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

    def test_market_maker_contract_address(self) -> None:
        """Test the `market_maker_contract_address` property."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.id = "0xABCDEF"
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [mock_bet]
            behaviour.synchronized_data.db.get_strict = lambda key: 0  # type: ignore[method-assign]
            result = behaviour.market_maker_contract_address
        assert result == "0xABCDEF"

    def test_investment_amount(self) -> None:
        """Test the `investment_amount` property."""
        behaviour = self.behaviour
        behaviour.synchronized_data.db.get_strict = lambda key: 1000  # type: ignore[method-assign]
        result = behaviour.investment_amount
        assert result == 1000

    def test_return_amount(self) -> None:
        """Test the `return_amount` property."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.get_vote_amount.return_value = 500  # type: ignore[method-assign]
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [mock_bet]
            db_values = {"sampled_bet_index": 0, "vote": 1}
            behaviour.synchronized_data.db.get_strict = lambda key: db_values.get(  # type: ignore[method-assign]
                key, 0
            )
            result = behaviour.return_amount  # type: ignore[method-assign]
        assert result == 500

    def test_outcome_index(self) -> None:
        """Test the `outcome_index` property."""
        behaviour = self.behaviour
        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            1 if key == "vote" else 0
        )
        result = behaviour.outcome_index
        assert result == 1

    def test_execute_strategy_no_executable(self) -> None:  # type: ignore[method-assign]
        """Test `execute_strategy` when no executable is found for the trading strategy."""
        behaviour = self.behaviour
        behaviour.shared_state.strategies_executables = {}
        result = behaviour.execute_strategy(trading_strategy="nonexistent_strategy")
        assert result == {BET_AMOUNT_FIELD: 0}

    def test_mock_data_property(self) -> None:
        """Test the `mock_data` property."""
        behaviour = self.behaviour  # type: ignore[method-assign]
        mock_data = BenchmarkingMockData(
            id="test_id", question="test?", answer="yes", p_yes=0.8
        )
        behaviour.shared_state.mock_data = mock_data
        result = behaviour.mock_data
        assert result == mock_data

    def test_mock_data_property_raises_when_none(self) -> None:
        """Test that `mock_data` property raises ValueError when mock data is None."""
        behaviour = self.behaviour
        behaviour.shared_state.mock_data = None
        with pytest.raises(
            ValueError, match="Attempted to access the mock data while being empty!"
        ):
            _ = behaviour.mock_data

    def test_acc_info_fields(self) -> None:
        """Test the `acc_info_fields` property."""
        behaviour = self.behaviour
        mock_fields = MagicMock()
        behaviour.context.acc_info_fields = mock_fields
        result = behaviour.acc_info_fields
        assert result == mock_fields

    def test_synced_timestamp(self) -> None:
        """Test the `synced_timestamp` property."""
        behaviour = self.behaviour
        mock_timestamp = MagicMock()
        mock_timestamp.timestamp.return_value = 1700000000.5
        behaviour.round_sequence.last_round_transition_timestamp = mock_timestamp  # type: ignore[misc]
        result = behaviour.synced_timestamp
        assert result == 1700000000

    def test_safe_tx_hash_getter(self) -> None:
        """Test the `safe_tx_hash` getter."""
        behaviour = self.behaviour
        assert behaviour.safe_tx_hash == ""

    def test_safe_tx_hash_setter_valid(self) -> None:
        """Test the `safe_tx_hash` setter with a valid hash."""
        behaviour = self.behaviour
        valid_hash = "0x" + "a" * 64
        assert len(valid_hash) == TX_HASH_LENGTH
        behaviour.safe_tx_hash = valid_hash
        assert behaviour.safe_tx_hash == "a" * 64  # type: ignore[misc]

    def test_safe_tx_hash_setter_invalid_length(self) -> None:
        """Test the `safe_tx_hash` setter with an invalid hash length."""
        behaviour = self.behaviour
        invalid_hash = "0x" + "a" * 10
        with pytest.raises(ValueError, match="Incorrect length"):
            behaviour.safe_tx_hash = invalid_hash

    def test_multi_send_txs(self) -> None:
        """Test the `multi_send_txs` property."""
        behaviour = self.behaviour
        batch = MultisendBatch(to="0xaddr", data=HexBytes(b"\x01\x02"))
        behaviour.multisend_batches = [batch]
        result = behaviour.multi_send_txs
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["to"] == "0xaddr"

    def test_txs_value(self) -> None:
        """Test the `txs_value` property."""
        behaviour = self.behaviour
        batch1 = MultisendBatch(to="0x1", data=HexBytes(b"\x01"), value=100)
        batch2 = MultisendBatch(to="0x2", data=HexBytes(b"\x02"), value=200)
        behaviour.multisend_batches = [batch1, batch2]
        assert behaviour.txs_value == 300

    def test_tx_hex_empty_hash(self) -> None:
        """Test the `tx_hex` property when safe_tx_hash is empty."""
        behaviour = self.behaviour
        result = behaviour.tx_hex
        assert result is None

    def test_tx_hex_with_hash(self) -> None:
        """Test the `tx_hex` property when safe_tx_hash is set."""
        behaviour = self.behaviour
        valid_hash = "0x" + "a" * 64
        behaviour.safe_tx_hash = valid_hash
        behaviour.multisend_batches = []
        behaviour.multisend_data = b""
        behaviour.params.multisend_address = "0x" + "b" * 40
        result = behaviour.tx_hex
        assert result is not None
        assert isinstance(result, str)

    def test_policy_property_raises_when_none(self) -> None:
        """Test that `policy` property raises ValueError when policy is None."""
        behaviour = self.behaviour
        behaviour._policy = None
        with pytest.raises(
            ValueError,
            match="Attempting to retrieve the policy before it has been established.",
        ):
            _ = behaviour.policy

    def test_policy_property_returns_value(self) -> None:
        """Test that `policy` property returns the policy when set."""
        behaviour = self.behaviour
        mock_policy = MagicMock()
        behaviour._policy = mock_policy
        assert behaviour.policy == mock_policy

    def test_is_first_period_true(self) -> None:
        """Test `is_first_period` property when it is the first period."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = False
        behaviour.shared_state.mock_data = None
        behaviour.synchronized_data.db.get_strict = lambda key: 0  # type: ignore[method-assign]
        result = behaviour.is_first_period
        assert result is True

    def test_is_first_period_false(self) -> None:
        """Test `is_first_period` property when it is not the first period."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = False
        behaviour.shared_state.mock_data = MagicMock()
        db_values = {"period_count": 1}
        behaviour.synchronized_data.db.get_strict = lambda key: db_values.get(key, 0)  # type: ignore[method-assign]
        result = behaviour.is_first_period
        assert result is False

    def test_usdc_to_native(self) -> None:
        """Test the `usdc_to_native` static method."""  # type: ignore[method-assign]
        result = DecisionMakerBaseBehaviour.usdc_to_native(1_000_000)
        assert result == 1.0

    def test_convert_unit_to_wei(self) -> None:
        """Test the `convert_unit_to_wei` method."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=WXDAI)]
            result = behaviour.convert_unit_to_wei(1.0)
        assert result == 10**18  # type: ignore[method-assign]

    def test_convert_unit_to_wei_usdc(self) -> None:
        """Test the `convert_unit_to_wei` method with USDC token."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=USDC_POLYGON)]
            result = behaviour.convert_unit_to_wei(1.0)
        assert result == 10**6

    def test_get_token_precision_xdai(self) -> None:
        """Test `get_token_precision` for xDAI."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=WXDAI)]
            result = behaviour.get_token_precision()
        assert result == 10**18

    def test_get_token_precision_usdc(self) -> None:
        """Test `get_token_precision` for USDC."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=USDC_POLYGON)]
            result = behaviour.get_token_precision()
        assert result == 10**6

    def test_convert_to_native_xdai(self) -> None:
        """Test `convert_to_native` for xDAI."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=WXDAI)]
            result = behaviour.convert_to_native(10**18)
        assert result == 1.0

    def test_convert_to_native_usdc(self) -> None:
        """Test `convert_to_native` for USDC."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=USDC_POLYGON)]
            result = behaviour.convert_to_native(10**6)
        assert result == 1.0

    def test_get_token_name_xdai(self) -> None:
        """Test `get_token_name` for xDAI."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=WXDAI)]
            result = behaviour.get_token_name()
        assert result == "xDAI"

    def test_get_token_name_usdc(self) -> None:
        """Test `get_token_name` for USDC."""
        behaviour = self.behaviour
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=USDC_POLYGON)]
            result = behaviour.get_token_name()
        assert result == "USDC"

    def test_get_active_sampled_bet_with_bets(self) -> None:
        """Test `get_active_sampled_bet` when bets are already loaded."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        behaviour.bets = [mock_bet]
        behaviour.synchronized_data.db.get_strict = lambda key: 0  # type: ignore[method-assign]
        result = behaviour.get_active_sampled_bet()
        assert result == mock_bet

    def test_get_active_sampled_bet_empty_bets(self) -> None:
        """Test `get_active_sampled_bet` when bets list is empty."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        behaviour.bets = []
        behaviour.synchronized_data.db.get_strict = lambda key: 0  # type: ignore[method-assign]
        with mock.patch.object(behaviour, "read_bets") as mock_read:
            # after read_bets, bets will be populated
            def set_bets() -> None:
                """Set bets."""
                behaviour.bets = [mock_bet]

            # type: ignore[method-assign]
            mock_read.side_effect = set_bets
            result = behaviour.get_active_sampled_bet()
        assert result == mock_bet

    def test_check_balance_benchmarking_mode(self) -> None:
        """Test `check_balance` in benchmarking mode."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = True
        with mock.patch.object(behaviour, "_mock_balance_check") as mock_check:  # type: ignore[method-assign]
            gen = behaviour.check_balance()
            try:
                next(gen)  # type: ignore[no-untyped-def]
            except StopIteration as e:
                assert e.value is True
            mock_check.assert_called_once()

    def test_check_balance_bad_response(self) -> None:
        """Test `check_balance` with a bad performative in the response."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = False

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            "0xsafe" if key == "safe_contract_address" else 0
        )
        behaviour.params.mech_chain_id = "gnosis"

        with mock.patch.object(
            type(behaviour),
            "collateral_token",
            new_callable=PropertyMock,
            return_value=WXDAI,  # type: ignore[no-untyped-def]
        ):
            gen = behaviour.check_balance()
            next(gen)  # enter yield from
            try:
                next(gen)
            except StopIteration as e:  # type: ignore[method-assign]
                assert e.value is False

    def test_check_balance_missing_token_or_wallet(self) -> None:
        """Test `check_balance` when token or wallet is None."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = False

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {
            "token": None,
            "wallet": None,
        }  # nosec B105

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            "0xsafe" if key == "safe_contract_address" else 0
        )
        behaviour.params.mech_chain_id = "gnosis"

        with mock.patch.object(
            type(behaviour),
            "collateral_token",
            new_callable=PropertyMock,
            return_value=WXDAI,  # type: ignore[no-untyped-def]
        ):
            gen = behaviour.check_balance()
            next(gen)
            try:
                next(gen)
            except StopIteration as e:  # type: ignore[method-assign]
                assert e.value is False

    def test_check_balance_success(self) -> None:
        """Test `check_balance` with a successful response."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = False

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {
            "token": 5000,
            "wallet": 10000,
        }  # nosec B105

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            "0xsafe" if key == "safe_contract_address" else 0
        )
        behaviour.params.mech_chain_id = "gnosis"

        with mock.patch.object(
            type(behaviour),
            "collateral_token",
            new_callable=PropertyMock,
            return_value=WXDAI,  # type: ignore[no-untyped-def]
        ):
            with mock.patch.object(behaviour, "_report_balance"):
                gen = behaviour.check_balance()
                next(gen)
                try:
                    next(gen)  # type: ignore[method-assign]
                except StopIteration as e:
                    assert e.value is True

        assert behaviour.token_balance == 5000
        assert behaviour.wallet_balance == 10000

    def test_update_bet_transaction_information(self) -> None:
        """Test `update_bet_transaction_information` method."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.queue_status.next_status.return_value = MagicMock()
        mock_bet.update_investments.return_value = True
        mock_bet.id = "test_bet"

        db_values = {"sampled_bet_index": 0, "bet_amount": 1000}
        behaviour.synchronized_data.db.get_strict = lambda key: db_values.get(key, 0)  # type: ignore[method-assign]
        mock_timestamp = MagicMock()
        mock_timestamp.timestamp.return_value = 1700000000.0
        behaviour.round_sequence.last_round_transition_timestamp = mock_timestamp  # type: ignore[misc]

        with mock.patch.object(
            type(behaviour),
            "sampled_bet",
            new_callable=PropertyMock,
            return_value=mock_bet,
        ):
            with mock.patch.object(behaviour, "store_bets"):
                with mock.patch.object(behaviour, "_update_bet_strategy"):
                    behaviour.update_bet_transaction_information()

        mock_bet.update_investments.assert_called_once_with(1000)  # type: ignore[method-assign]

    def test_update_bet_transaction_information_update_fails(self) -> None:
        """Test `update_bet_transaction_information` when update_investments returns False."""  # type: ignore[misc]
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.queue_status.next_status.return_value = MagicMock()
        mock_bet.update_investments.return_value = False
        mock_bet.id = "test_bet"

        db_values = {"sampled_bet_index": 0, "bet_amount": 1000}
        behaviour.synchronized_data.db.get_strict = lambda key: db_values.get(key, 0)  # type: ignore[method-assign]
        mock_timestamp = MagicMock()
        mock_timestamp.timestamp.return_value = 1700000000.0
        behaviour.round_sequence.last_round_transition_timestamp = mock_timestamp  # type: ignore[misc]

        with mock.patch.object(
            type(behaviour),
            "sampled_bet",
            new_callable=PropertyMock,
            return_value=mock_bet,
        ):
            with mock.patch.object(behaviour, "store_bets"):
                with mock.patch.object(behaviour, "_update_bet_strategy"):
                    behaviour.update_bet_transaction_information()

        behaviour.context.logger.error.assert_called()  # type: ignore[method-assign]

    def test_update_sell_transaction_information(self) -> None:
        """Test `update_sell_transaction_information` method."""  # type: ignore[misc]
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.queue_status.next_status.return_value = MagicMock()
        mock_bet.update_investments.return_value = True

        behaviour.synchronized_data.db.get_strict = lambda key: 0  # type: ignore[method-assign]
        mock_timestamp = MagicMock()
        mock_timestamp.timestamp.return_value = 1700000000.0
        behaviour.round_sequence.last_round_transition_timestamp = mock_timestamp  # type: ignore[misc]

        with mock.patch.object(
            type(behaviour),
            "sampled_bet",
            new_callable=PropertyMock,
            return_value=mock_bet,
        ):
            with mock.patch.object(behaviour, "store_bets"):
                behaviour.update_sell_transaction_information()

        mock_bet.update_investments.assert_called_once_with(0)

    # type: ignore[method-assign]
    def test_update_sell_transaction_information_fails(self) -> None:
        """Test `update_sell_transaction_information` when update fails."""
        behaviour = self.behaviour  # type: ignore[misc]
        mock_bet = MagicMock()
        mock_bet.queue_status.next_status.return_value = MagicMock()
        mock_bet.update_investments.return_value = False

        behaviour.synchronized_data.db.get_strict = lambda key: 0  # type: ignore[method-assign]
        mock_timestamp = MagicMock()
        mock_timestamp.timestamp.return_value = 1700000000.0
        behaviour.round_sequence.last_round_transition_timestamp = mock_timestamp  # type: ignore[misc]

        with mock.patch.object(
            type(behaviour),
            "sampled_bet",
            new_callable=PropertyMock,
            return_value=mock_bet,
        ):
            with mock.patch.object(behaviour, "store_bets"):
                behaviour.update_sell_transaction_information()

        behaviour.context.logger.error.assert_called()

    # type: ignore[method-assign]
    def test_send_message(self) -> None:
        """Test `send_message` method."""
        behaviour = self.behaviour  # type: ignore[misc]
        msg = MagicMock()
        dialogue = MagicMock()
        dialogue.dialogue_label.dialogue_reference = ("nonce_123", "")
        callback = MagicMock()

        # Use real dict for req_to_callback
        behaviour.shared_state.req_to_callback = {}

        behaviour.send_message(msg, dialogue, callback)

        behaviour.context.outbox.put_message.assert_called_once_with(message=msg)
        assert behaviour.shared_state.req_to_callback["nonce_123"] == callback
        assert behaviour.shared_state.in_flight_req is True

    def test_handle_get_strategy_no_inflight_req(self) -> None:
        """Test `_handle_get_strategy` when there is no inflight strategy request."""
        behaviour = self.behaviour
        behaviour._inflight_strategy_req = None
        message = MagicMock()
        dialogue = MagicMock()

        behaviour._handle_get_strategy(message, dialogue)
        behaviour.context.logger.error.assert_called()

    def test_handle_get_strategy_success(self) -> None:
        """Test `_handle_get_strategy` with a successful response."""
        behaviour = self.behaviour
        behaviour._inflight_strategy_req = "test_strategy"
        behaviour.shared_state.strategy_to_filehash = {"test_strategy": "some_hash"}
        behaviour.shared_state.strategies_executables = {}

        message = MagicMock()
        message.files = {
            "component.yaml": "entry_point: script.py\ncallable: run",
            "script.py": "def run(): pass",
        }

        with mock.patch.object(
            ComponentPackageLoader,
            "load",
            return_value=({}, "def run(): pass", "run"),
        ):
            behaviour._handle_get_strategy(message, MagicMock())

        assert "test_strategy" in behaviour.shared_state.strategies_executables
        assert behaviour._inflight_strategy_req is None
        assert "test_strategy" not in behaviour.shared_state.strategy_to_filehash

    def test_download_next_strategy_inflight_request(self) -> None:
        """Test `download_next_strategy` when there is already a request in flight."""
        behaviour = self.behaviour
        behaviour._inflight_strategy_req = "existing_strategy"
        behaviour.download_next_strategy()
        # Should return early without doing anything

    def test_download_next_strategy_no_pending(self) -> None:
        """Test `download_next_strategy` when no strategies are pending."""
        behaviour = self.behaviour
        behaviour._inflight_strategy_req = None
        behaviour.shared_state.strategy_to_filehash = {}
        behaviour.download_next_strategy()
        # Should return early without doing anything

    def test_download_next_strategy_success(self) -> None:
        """Test `download_next_strategy` when strategies are pending."""
        behaviour = self.behaviour
        behaviour._inflight_strategy_req = None
        behaviour.shared_state.strategy_to_filehash = {"my_strategy": "hash123"}

        with mock.patch.object(
            behaviour,
            "_build_ipfs_get_file_req",
            return_value=(MagicMock(), MagicMock()),
        ):
            with mock.patch.object(behaviour, "send_message") as mock_send:
                behaviour.download_next_strategy()

        assert behaviour._inflight_strategy_req == "my_strategy"
        mock_send.assert_called_once()

    def test_download_strategies(self) -> None:
        """Test `download_strategies` generator."""
        behaviour = self.behaviour
        call_count = 0

        behaviour.shared_state.strategy_to_filehash = {"s1": "h1"}

        def mock_download() -> None:
            """Mock download_next_strategy that removes entries."""
            nonlocal call_count
            call_count += 1
            behaviour.shared_state.strategy_to_filehash = {}

        behaviour.download_next_strategy = mock_download  # type: ignore[method-assign]
        behaviour.sleep = lambda t: (yield)  # type: ignore[assignment, method-assign]

        gen = behaviour.download_strategies()
        next(gen)  # enter the sleep yield
        try:
            next(gen)  # should stop since no more strategies
        except StopIteration:
            pass
        assert call_count == 1

    def test_update_with_values_from_chatui_max_bet(self) -> None:  # type: ignore[no-untyped-def]
        """Test `_update_with_values_from_chatui` with max_bet_size set."""
        behaviour = self.behaviour
        behaviour.shared_state.chatui_config.max_bet_size = 5000
        behaviour.shared_state.chatui_config.fixed_bet_size = None

        strategies_kwargs = {"max_bet": 1000, "bet_amount_per_threshold": {"0.5": 100}}
        result = behaviour._update_with_values_from_chatui(strategies_kwargs)
        assert result["max_bet"] == 5000
        # Original should not be modified
        assert strategies_kwargs["max_bet"] == 1000

    def test_update_with_values_from_chatui_fixed_bet(self) -> None:
        """Test `_update_with_values_from_chatui` with fixed_bet_size set."""
        behaviour = self.behaviour
        behaviour.shared_state.chatui_config.max_bet_size = None
        behaviour.shared_state.chatui_config.fixed_bet_size = 2000

        strategies_kwargs = {
            "max_bet": 1000,
            "bet_amount_per_threshold": {"0.5": 100, "0.7": 200},
        }
        result = behaviour._update_with_values_from_chatui(strategies_kwargs)
        assert result["bet_amount_per_threshold"]["0.5"] == 2000
        assert result["bet_amount_per_threshold"]["0.7"] == 2000

    def test_update_with_values_from_chatui_neither_set(self) -> None:
        """Test `_update_with_values_from_chatui` with neither value set."""
        behaviour = self.behaviour
        behaviour.shared_state.chatui_config.max_bet_size = None
        behaviour.shared_state.chatui_config.fixed_bet_size = None

        strategies_kwargs = {"max_bet": 1000, "bet_amount_per_threshold": {"0.5": 100}}
        result = behaviour._update_with_values_from_chatui(strategies_kwargs)
        assert result["max_bet"] == 1000
        assert result["bet_amount_per_threshold"]["0.5"] == 100

    def test_update_with_values_from_chatui_both_set(self) -> None:
        """Test `_update_with_values_from_chatui` with both values set."""
        behaviour = self.behaviour
        behaviour.shared_state.chatui_config.max_bet_size = 5000
        behaviour.shared_state.chatui_config.fixed_bet_size = 2000

        strategies_kwargs = {"max_bet": 1000, "bet_amount_per_threshold": {"0.5": 100}}
        result = behaviour._update_with_values_from_chatui(strategies_kwargs)
        assert result["max_bet"] == 5000
        assert result["bet_amount_per_threshold"]["0.5"] == 2000

    def test_get_decimals_for_token_usdc(self) -> None:
        """Test `_get_decimals_for_token` for USDC."""
        behaviour = self.behaviour
        assert behaviour._get_decimals_for_token(USDC_POLYGON) == 6
        assert behaviour._get_decimals_for_token(USCDE_POLYGON) == 6

    def test_get_decimals_for_token_wxdai(self) -> None:
        """Test `_get_decimals_for_token` for wxDAI."""
        behaviour = self.behaviour
        assert behaviour._get_decimals_for_token(WXDAI) == 18

    def test_default_error(self) -> None:
        """Test `default_error` method."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        behaviour.default_error("contract_id", "callable_name", response_msg)
        behaviour.context.logger.error.assert_called_once()

    def test_propagate_contract_messages_info(self) -> None:
        """Test `_propagate_contract_messages` when info message is present."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.raw_transaction.body = {"info": "Some info message"}
        result = behaviour._propagate_contract_messages(response_msg)
        assert result is True
        behaviour.context.logger.info.assert_called_with("Some info message")

    def test_propagate_contract_messages_warning(self) -> None:
        """Test `_propagate_contract_messages` when warning message is present."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.raw_transaction.body = {"warning": "Some warning"}
        result = behaviour._propagate_contract_messages(response_msg)
        assert result is True

    def test_propagate_contract_messages_error(self) -> None:
        """Test `_propagate_contract_messages` when error message is present."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.raw_transaction.body = {"error": "Some error"}
        result = behaviour._propagate_contract_messages(response_msg)
        assert result is True

    def test_propagate_contract_messages_none(self) -> None:
        """Test `_propagate_contract_messages` when no message is present."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.raw_transaction.body = {}
        result = behaviour._propagate_contract_messages(response_msg)
        assert result is False

    def test_contract_interact_success(self) -> None:
        """Test `contract_interact` generator with a successful response."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"data_key": "some_data"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.params.mech_chain_id = "gnosis"

        gen = behaviour.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore[arg-type]
            contract_address="0xaddr",
            contract_public_id=PublicId.from_str("valory/test:0.1.0"),
            contract_callable="test_method",
            data_key="data_key",
            placeholder="test_attr",
        )
        next(gen)
        try:  # type: ignore[no-untyped-def]
            next(gen)
        except StopIteration as e:
            assert e.value is True

        assert behaviour.test_attr == "some_data"  # type: ignore[attr-defined]

    def test_contract_interact_bad_performative(self) -> None:
        """Test `contract_interact` with bad response performative."""
        behaviour = self.behaviour  # type: ignore[arg-type]
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.params.mech_chain_id = "gnosis"

        gen = behaviour.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore[arg-type]
            contract_address="0xaddr",
            contract_public_id=PublicId.from_str("valory/test:0.1.0"),
            contract_callable="test_method",
            data_key="data_key",
            placeholder="test_attr",
        )
        next(gen)
        try:  # type: ignore[no-untyped-def]
            next(gen)
        except StopIteration as e:
            assert e.value is False

    def test_contract_interact_missing_data_key(self) -> None:
        """Test `contract_interact` when data_key is missing from response."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION  # type: ignore[arg-type]
        response_msg.raw_transaction.body = {"other_key": "value"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.params.mech_chain_id = "gnosis"

        gen = behaviour.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore[arg-type]
            contract_address="0xaddr",
            contract_public_id=PublicId.from_str("valory/test:0.1.0"),
            contract_callable="test_method",
            data_key="missing_key",
            placeholder="test_attr",
        )
        next(gen)
        try:  # type: ignore[no-untyped-def]
            next(gen)
        except StopIteration as e:
            assert e.value is False

    def test_contract_interact_missing_data_key_with_propagation(self) -> None:
        """Test `contract_interact` when data_key is missing but message is propagated."""
        behaviour = self.behaviour
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION  # type: ignore[arg-type]
        response_msg.raw_transaction.body = {"info": "some info"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]
        behaviour.params.mech_chain_id = "gnosis"

        gen = behaviour.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore[arg-type]
            contract_address="0xaddr",
            contract_public_id=PublicId.from_str("valory/test:0.1.0"),
            contract_callable="test_method",
            data_key="missing_key",
            placeholder="test_attr",
        )
        next(gen)
        try:  # type: ignore[no-untyped-def]
            next(gen)
        except StopIteration as e:
            assert e.value is False

    def test_mech_contract_interact(self) -> None:
        """Test `_mech_contract_interact` method."""
        behaviour = self.behaviour
        behaviour.params.mech_contract_address = "0xmech"
        behaviour.params.mech_chain_id = "gnosis"  # type: ignore[arg-type]

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"result": "data_value"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._mech_contract_interact(
            contract_callable="some_callable",
            data_key="result",
            placeholder="mech_result",
        )
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is True

    # type: ignore[no-untyped-def]
    def test_build_multisend_data_success(self) -> None:
        """Test `_build_multisend_data` with a successful response."""
        behaviour = self.behaviour
        behaviour.params.multisend_address = "0xmultisend"
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"data": "0xabcdef"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._build_multisend_data()
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is True

        assert behaviour.multisend_data == bytes.fromhex("abcdef")

    def test_build_multisend_data_bad_performative(self) -> None:
        """Test `_build_multisend_data` with bad response performative."""  # type: ignore[no-untyped-def]
        behaviour = self.behaviour
        behaviour.params.multisend_address = "0xmultisend"
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._build_multisend_data()
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is False

    def test_build_multisend_data_missing_data(self) -> None:
        """Test `_build_multisend_data` when data is missing from response."""
        behaviour = self.behaviour
        behaviour.params.multisend_address = "0xmultisend"  # type: ignore[no-untyped-def]
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._build_multisend_data()
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is False

    def test_build_multisend_safe_tx_hash_success(self) -> None:
        """Test `_build_multisend_safe_tx_hash` with success."""
        behaviour = self.behaviour
        behaviour.params.multisend_address = "0xmultisend"  # type: ignore[no-untyped-def]
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.multisend_batches = []
        behaviour.multisend_data = b""

        valid_hash = "0x" + "a" * 64
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {"tx_hash": valid_hash}

        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            "0xsafe" if key == "safe_contract_address" else 0
        )

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._build_multisend_safe_tx_hash()
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is True
        # type: ignore[method-assign]
        assert behaviour.safe_tx_hash == "a" * 64

    def test_build_multisend_safe_tx_hash_bad_performative(self) -> None:
        """Test `_build_multisend_safe_tx_hash` with bad performative."""  # type: ignore[no-untyped-def]
        behaviour = self.behaviour
        behaviour.params.multisend_address = "0xmultisend"
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.multisend_batches = []
        behaviour.multisend_data = b""

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            "0xsafe" if key == "safe_contract_address" else 0
        )

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._build_multisend_safe_tx_hash()
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is False

    # type: ignore[method-assign]
    def test_build_multisend_safe_tx_hash_invalid_hash(self) -> None:
        """Test `_build_multisend_safe_tx_hash` with invalid hash."""
        behaviour = self.behaviour
        behaviour.params.multisend_address = "0xmultisend"  # type: ignore[no-untyped-def]
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.multisend_batches = []
        behaviour.multisend_data = b""

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {"tx_hash": None}

        behaviour.synchronized_data.db.get_strict = lambda key: (  # type: ignore[method-assign]
            "0xsafe" if key == "safe_contract_address" else 0
        )

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        gen = behaviour._build_multisend_safe_tx_hash()
        next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value is False

    # type: ignore[method-assign]
    def test_wait_for_condition_with_sleep_immediate_success(self) -> None:
        """Test `wait_for_condition_with_sleep` when condition is immediately satisfied."""
        behaviour = self.behaviour
        behaviour.params.rpc_sleep_time = 1  # type: ignore[no-untyped-def]

        def condition_gen() -> Generator:
            """Condition generator that returns True immediately."""
            yield
            return True  # type: ignore[return-value]

        gen = behaviour.wait_for_condition_with_sleep(condition_gen)  # type: ignore[arg-type]
        next(gen)  # enter yield from condition_gen
        try:
            next(gen)  # condition returns True
        except StopIteration:
            pass

    def test_wait_for_condition_with_sleep_with_timeout(self) -> None:
        """Test `wait_for_condition_with_sleep` with timeout that expires."""
        behaviour = self.behaviour
        behaviour.params.rpc_sleep_time = 1
        behaviour.sleep = lambda t: (yield)  # type: ignore[assignment, method-assign]

        # type: ignore[no-untyped-def]
        def condition_gen() -> Generator:
            """Condition generator that always returns False."""
            yield
            return False  # type: ignore[return-value]

        # Mock datetime.now so the second call is past the deadline.
        # This avoids Windows low-resolution timer issues with timeout=0.0.
        start = datetime(2020, 1, 1, 0, 0, 0)
        past_deadline = start + timedelta(seconds=1)
        mock_dt = MagicMock(wraps=datetime)
        mock_dt.now.side_effect = [start, past_deadline]
        mock_dt.max = datetime.max
        with mock.patch(
            "packages.valory.skills.decision_maker_abci.behaviours.base.datetime",
            mock_dt,
        ):
            gen = behaviour.wait_for_condition_with_sleep(condition_gen, timeout=0.0)  # type: ignore[arg-type]
            next(gen)  # enter yield from condition_gen
            with pytest.raises(TimeoutException):
                next(gen)  # should timeout

    def test_wait_for_condition_with_sleep_retry(self) -> None:
        """Test `wait_for_condition_with_sleep` with retry."""
        behaviour = self.behaviour
        behaviour.params.rpc_sleep_time = 1
        behaviour.sleep = lambda t: (yield)  # type: ignore[assignment, method-assign]

        call_count = 0

        # type: ignore[no-untyped-def]
        def condition_gen() -> Generator:
            """Condition generator that fails then succeeds."""
            nonlocal call_count
            call_count += 1
            yield
            return call_count >= 2  # type: ignore[return-value]

        gen = behaviour.wait_for_condition_with_sleep(condition_gen)  # type: ignore[arg-type]
        # First attempt: enter condition_gen
        next(gen)
        # First attempt fails, sleep
        next(gen)
        # Second attempt: enter condition_gen
        next(gen)
        # Second attempt succeeds
        try:
            next(gen)
        except StopIteration:  # type: ignore[no-untyped-def]
            pass
        assert call_count == 2

    def test_wait_for_condition_with_sleep_override(self) -> None:
        """Test `wait_for_condition_with_sleep` with sleep_time_override."""
        behaviour = self.behaviour
        behaviour.params.rpc_sleep_time = 5
        sleep_times: List[int] = []

        def mock_sleep(t: int) -> Generator:
            """Mock sleep that records the time."""
            sleep_times.append(t)
            yield

        behaviour.sleep = mock_sleep  # type: ignore[assignment, method-assign]

        call_count = 0

        def condition_gen() -> Generator:
            """Condition generator that fails then succeeds."""
            nonlocal call_count
            call_count += 1
            yield
            return call_count >= 2  # type: ignore[return-value]

        gen = behaviour.wait_for_condition_with_sleep(
            condition_gen, sleep_time_override=2  # type: ignore[arg-type, no-untyped-def]
        )
        next(gen)
        next(gen)  # sleep yield
        next(gen)
        try:
            next(gen)
        except StopIteration:
            pass
        assert sleep_times == [2]  # type: ignore[no-untyped-def]

    def test_write_benchmark_results_new_file(self) -> None:
        """Test `_write_benchmark_results` creating a new file with headers."""
        behaviour = self.behaviour
        with tempfile.TemporaryDirectory() as tmpdir:
            behaviour.params.store_path = Path(tmpdir)
            behaviour.benchmarking_mode.results_filename = "results.csv"  # type: ignore[assignment]
            behaviour.benchmarking_mode.question_id_field = "qid"
            behaviour.benchmarking_mode.question_field = "question"
            behaviour.benchmarking_mode.answer_field = "answer"
            behaviour.benchmarking_mode.bet_amount_field = "bet_amount"

            mock_data = BenchmarkingMockData(
                id="test_id", question="test?", answer="yes", p_yes=0.8
            )
            behaviour.shared_state.mock_data = mock_data

            pred_response = MagicMock()
            pred_response.p_yes = 0.8
            pred_response.p_no = 0.2
            pred_response.confidence = 0.9

            behaviour._write_benchmark_results(pred_response, bet_amount=100.0)
            # type: ignore[assignment]
            results_path = Path(tmpdir) / "results.csv"
            assert results_path.exists()
            content = results_path.read_text()
            assert "qid" in content
            assert "test_id" in content

    def test_write_benchmark_results_append_to_existing(self) -> None:
        """Test `_write_benchmark_results` appending to an existing file."""
        behaviour = self.behaviour
        with tempfile.TemporaryDirectory() as tmpdir:
            behaviour.params.store_path = Path(tmpdir)
            behaviour.benchmarking_mode.results_filename = "results.csv"  # type: ignore[assignment]
            behaviour.benchmarking_mode.question_id_field = "qid"
            behaviour.benchmarking_mode.question_field = "question"
            behaviour.benchmarking_mode.answer_field = "answer"
            behaviour.benchmarking_mode.bet_amount_field = "bet_amount"

            # Create existing file
            results_path = Path(tmpdir) / "results.csv"
            results_path.write_text("existing_header\n")

            mock_data = BenchmarkingMockData(
                id="test_id2", question='test, "quoted"?', answer="no", p_yes=0.3
            )
            behaviour.shared_state.mock_data = mock_data

            pred_response = MagicMock()
            pred_response.p_yes = 0.3
            pred_response.p_no = 0.7  # type: ignore[assignment]
            pred_response.confidence = 0.8

            liquidity_info = LiquidityInfo(
                l0_start=100, l1_start=200, l0_end=150, l1_end=250
            )
            behaviour._write_benchmark_results(
                pred_response, bet_amount=50.0, liquidity_info=liquidity_info
            )

            content = results_path.read_text()
            assert "test_id2" in content
            # Should not add headers since file already exists
            assert content.startswith("existing_header\n")

    def _setup_sampled_bet_mocks(self) -> MagicMock:
        """Set up common mocks for tests that access sampled_bet-dependent properties.

        Returns a mock bet object. The caller should use this inside
        mock.patch.object contexts for market_maker_contract_address, outcome_index,
        and investment_amount properties.

        :return: a mock bet object.
        """
        mock_bet = MagicMock()
        mock_bet.id = "0xmarket"
        mock_bet.get_vote_amount.return_value = 2000
        return mock_bet

    def test_calc_token_amount_buy_success(self) -> None:
        """Test `_calc_token_amount` for a buy operation (success)."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.params.slippage = 0.01

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"amount": 900}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._calc_token_amount(
                operation=TradingOperation.BUY,
                amount_field="amount",
                amount_param_name="investment_amount",
            )
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is True

        assert behaviour.buy_amount == int(900 * 0.99)

    def test_calc_token_amount_sell_success(self) -> None:
        """Test `_calc_token_amount` for a sell operation (success)."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.params.slippage = 0.02

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"amount": 800}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._calc_token_amount(
                operation=TradingOperation.SELL,
                amount_field="amount",
                amount_param_name="return_amount",
            )
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is True

        assert behaviour.sell_amount == int(800 * 0.98)

    def test_calc_token_amount_bad_performative(self) -> None:
        """Test `_calc_token_amount` with bad response performative."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.params.slippage = 0.01

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._calc_token_amount(
                operation=TradingOperation.BUY,
                amount_field="amount",
                amount_param_name="investment_amount",
            )
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is False

    def test_calc_token_amount_missing_amount(self) -> None:
        """Test `_calc_token_amount` when amount field is missing."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.params.slippage = 0.01

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._calc_token_amount(
                operation=TradingOperation.BUY,
                amount_field="amount",
                amount_param_name="investment_amount",
            )
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is False

    def test_calc_buy_amount(self) -> None:
        """Test `_calc_buy_amount` delegates correctly."""
        behaviour = self.behaviour

        with mock.patch.object(behaviour, "_calc_token_amount") as mock_calc:
            mock_gen = MagicMock()
            mock_calc.return_value = mock_gen
            behaviour._calc_buy_amount()
            mock_calc.assert_called_once_with(
                operation=TradingOperation.BUY,
                amount_field="amount",
                amount_param_name="investment_amount",
            )

    def test_calc_sell_amount(self) -> None:
        """Test `_calc_sell_amount` delegates correctly."""
        behaviour = self.behaviour

        with mock.patch.object(behaviour, "_calc_token_amount") as mock_calc:
            mock_gen = MagicMock()
            mock_calc.return_value = mock_gen
            behaviour._calc_sell_amount()
            mock_calc.assert_called_once_with(
                operation=TradingOperation.SELL,
                amount_field="amount",
                amount_param_name="return_amount",
            )

    def test_build_token_tx_buy_success(self) -> None:
        """Test `_build_token_tx` for a buy operation (success)."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.buy_amount = 500
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {"data": "0xdeadbeef"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._build_token_tx(TradingOperation.BUY)
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is True

        assert len(behaviour.multisend_batches) == 1

    def test_build_token_tx_sell_success(self) -> None:
        """Test `_build_token_tx` for a sell operation (success)."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.sell_amount = 500
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {"data": "0xdeadbeef"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "return_amount",
            new_callable=PropertyMock,
            return_value=2000,
        ):
            gen = behaviour._build_token_tx(TradingOperation.SELL)
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is True

        assert len(behaviour.multisend_batches) == 1

    def test_build_token_tx_bad_performative(self) -> None:
        """Test `_build_token_tx` with bad response performative."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.buy_amount = 500
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._build_token_tx(TradingOperation.BUY)
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is False

    def test_build_token_tx_missing_data(self) -> None:
        """Test `_build_token_tx` when data is missing from response."""
        behaviour = self.behaviour
        behaviour.params.mech_chain_id = "gnosis"
        behaviour.buy_amount = 500
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "market_maker_contract_address",
            new_callable=PropertyMock,
            return_value="0xmarket",
        ), mock.patch.object(
            type(behaviour), "outcome_index", new_callable=PropertyMock, return_value=0
        ), mock.patch.object(
            type(behaviour),  # type: ignore[no-untyped-def]
            "investment_amount",
            new_callable=PropertyMock,
            return_value=1000,
        ):
            gen = behaviour._build_token_tx(TradingOperation.BUY)
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is False

    def test_build_buy_tx(self) -> None:
        """Test `_build_buy_tx` delegates correctly."""
        behaviour = self.behaviour

        with mock.patch.object(behaviour, "_build_token_tx") as mock_build:
            mock_gen = MagicMock()
            mock_build.return_value = mock_gen
            behaviour._build_buy_tx()
            mock_build.assert_called_once_with(TradingOperation.BUY)

    def test_build_sell_tx(self) -> None:
        """Test `_build_sell_tx` delegates correctly."""
        behaviour = self.behaviour

        with mock.patch.object(behaviour, "_build_token_tx") as mock_build:
            mock_gen = MagicMock()
            mock_build.return_value = mock_gen
            behaviour._build_sell_tx()
            mock_build.assert_called_once_with(TradingOperation.SELL)

    def test_build_approval_tx_success(self) -> None:
        """Test `build_approval_tx` with a successful response."""
        behaviour = self.behaviour
        behaviour.multisend_batches = []

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {"data": "0xabcdef0123456789"}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "collateral_token",
            new_callable=PropertyMock,
            return_value=WXDAI,
        ):
            gen = behaviour.build_approval_tx(
                amount=1000, spender="0xspender", token="0xtoken"  # nosec B106
            )  # type: ignore[no-untyped-def]
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is True

        assert len(behaviour.multisend_batches) == 1
        assert behaviour.multisend_batches[0].to == "0xtoken"

    def test_build_approval_tx_bad_performative(self) -> None:
        """Test `build_approval_tx` with bad response performative."""
        behaviour = self.behaviour

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "collateral_token",
            new_callable=PropertyMock,
            return_value=WXDAI,
        ):
            gen = behaviour.build_approval_tx(
                amount=1000, spender="0xspender", token="0xtoken"  # nosec B106
            )  # type: ignore[no-untyped-def]
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is False

    def test_build_approval_tx_missing_data(self) -> None:
        """Test `build_approval_tx` when data is missing."""
        behaviour = self.behaviour

        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.STATE
        response_msg.state.body = {}

        def mock_get_contract_api(*args: Any, **kwargs: Any) -> Generator:
            """Mock get_contract_api_response."""
            yield
            return response_msg  # type: ignore[return-value]

        behaviour.get_contract_api_response = mock_get_contract_api  # type: ignore[assignment, method-assign]

        with mock.patch.object(
            type(behaviour),
            "collateral_token",
            new_callable=PropertyMock,
            return_value=WXDAI,
        ):
            gen = behaviour.build_approval_tx(
                amount=1000, spender="0xspender", token="0xtoken"  # nosec B106
            )  # type: ignore[no-untyped-def]
            next(gen)
            try:
                next(gen)
            except StopIteration as e:
                assert e.value is False

    def test_finish_behaviour(self) -> None:
        """Test `finish_behaviour` generator."""
        behaviour = self.behaviour
        payload = MagicMock()

        behaviour.send_a2a_transaction = lambda p: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.wait_until_round_end = lambda: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        gen = behaviour.finish_behaviour(payload)
        next(gen)  # send_a2a_transaction yield
        next(gen)  # wait_until_round_end yield
        try:
            next(gen)  # should complete
        except StopIteration:
            pass

        behaviour.set_done.assert_called_once()

    def test_update_bet_strategy_success(self) -> None:
        """Test `_update_bet_strategy` with a successful update."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.id = "bet_123"
        behaviour.shared_state.chatui_config.trading_strategy = "kelly_criterion"

        behaviour._update_bet_strategy(mock_bet)

        assert mock_bet.strategy == "kelly_criterion"
        behaviour.context.logger.info.assert_called()

    def test_update_bet_strategy_exception(self) -> None:
        """Test `_update_bet_strategy` when an exception occurs."""
        behaviour = self.behaviour
        mock_bet = MagicMock()
        mock_bet.id = "bet_123"

        # Make accessing trading_strategy raise an exception
        type(behaviour.shared_state.chatui_config).trading_strategy = PropertyMock(
            side_effect=ValueError("test error")
        )

        behaviour._update_bet_strategy(mock_bet)
        behaviour.context.logger.warning.assert_called()

    def test_report_balance_xdai(self) -> None:
        """Test `_report_balance` for xDAI collateral token."""
        behaviour = self.behaviour
        behaviour.wallet_balance = 10**18
        behaviour.token_balance = 10**18
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=WXDAI)]
            behaviour.benchmarking_mode.enabled = False
            behaviour._report_balance()
        behaviour.context.logger.info.assert_called()

    def test_report_balance_usdc(self) -> None:
        """Test `_report_balance` for USDC collateral token."""
        behaviour = self.behaviour
        behaviour.wallet_balance = 10**18
        behaviour.token_balance = 10**6
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=USDC_POLYGON)]
            behaviour.benchmarking_mode.enabled = False
            behaviour._report_balance()
        behaviour.context.logger.info.assert_called()

    def test_collateral_amount_info_usdc(self) -> None:
        """Test `_collateral_amount_info` with USDC token."""
        behaviour = self.behaviour
        behaviour.benchmarking_mode.enabled = False
        with mock.patch.object(behaviour, "read_bets"):
            behaviour.bets = [MagicMock(collateralToken=USDC_POLYGON)]
            result = behaviour._collateral_amount_info(10**6)
        assert "USDC.e" in result

    def test_get_bet_amount_with_fallback_strategy(self) -> None:
        """Test `get_bet_amount` using a fallback strategy."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore[assignment, method-assign]
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.params.strategies_kwargs = deepcopy(STRATEGIES_KWARGS)
        behaviour.params.use_fallback_strategy = True
        behaviour.params.is_running_on_polymarket = False
        behaviour.shared_state.chatui_config.trading_strategy = "first_strategy"
        behaviour.shared_state.chatui_config.max_bet_size = None
        behaviour.shared_state.chatui_config.fixed_bet_size = None
        behaviour.token_balance = 10**18
        behaviour.wallet_balance = 10**18

        call_count = 0

        def mock_execute_strategy(*args: Any, **kwargs: Any) -> dict:
            """Mock execute strategy that returns 0 first time, then a value."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {BET_AMOUNT_FIELD: 0}
            return {BET_AMOUNT_FIELD: 100}

        behaviour.execute_strategy = mock_execute_strategy  # type: ignore[method-assign]
        behaviour.shared_state.strategies_executables = {
            "first_strategy": ("code1", "method1"),
            "second_strategy": ("code2", "method2"),
        }

        gen = behaviour.get_bet_amount(0.5, 0.5, 100, 100, 10, 0.8, WXDAI)
        for _ in range(2):  # type: ignore[no-untyped-def]
            next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value == 100
        assert call_count == 2

    def test_get_bet_amount_with_logging(self) -> None:
        """Test `get_bet_amount` processes strategy log levels."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore[assignment, method-assign]
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.params.strategies_kwargs = deepcopy(STRATEGIES_KWARGS)
        behaviour.params.use_fallback_strategy = False
        behaviour.params.is_running_on_polymarket = False
        behaviour.shared_state.chatui_config.trading_strategy = "test_strategy"
        behaviour.shared_state.chatui_config.max_bet_size = None
        behaviour.shared_state.chatui_config.fixed_bet_size = None
        behaviour.token_balance = 10**18
        behaviour.wallet_balance = 10**18

        behaviour.execute_strategy = lambda *_, **__: {  # type: ignore[method-assign]
            BET_AMOUNT_FIELD: 50,
            "info": ["Info log message"],
            "warning": ["Warning log message"],
            "error": ["Error log message"],
        }
        behaviour.shared_state.strategies_executables = {
            "test_strategy": ("code", "method"),
        }

        gen = behaviour.get_bet_amount(0.5, 0.5, 100, 100, 10, 0.8, WXDAI)
        for _ in range(2):
            next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value == 50

    def test_get_bet_amount_polymarket_bankroll(self) -> None:
        """Test `get_bet_amount` with polymarket bankroll calculation."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore[assignment, method-assign]
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.params.strategies_kwargs = deepcopy(STRATEGIES_KWARGS)
        behaviour.params.use_fallback_strategy = False
        behaviour.params.is_running_on_polymarket = True
        behaviour.shared_state.chatui_config.trading_strategy = "test_strategy"
        behaviour.shared_state.chatui_config.max_bet_size = None
        behaviour.shared_state.chatui_config.fixed_bet_size = None
        behaviour.token_balance = 10**18
        behaviour.wallet_balance = 10**18

        captured_kwargs = {}

        def mock_execute(*args: Any, **kwargs: Any) -> dict:
            """Capture kwargs."""
            captured_kwargs.update(kwargs)
            return {BET_AMOUNT_FIELD: 100}

        behaviour.execute_strategy = mock_execute  # type: ignore[method-assign]
        behaviour.shared_state.strategies_executables = {
            "test_strategy": ("code", "method"),
        }

        gen = behaviour.get_bet_amount(0.5, 0.5, 100, 100, 10, 0.8, WXDAI)
        for _ in range(2):
            next(gen)
        try:
            next(gen)
        except StopIteration:  # type: ignore[no-untyped-def]
            pass

        # In polymarket mode, bankroll should only be token_balance
        assert captured_kwargs["bankroll"] == 10**18

    def test_is_usdc_polygon(self) -> None:
        """Test `_is_usdc` for USDC Polygon addresses."""
        behaviour = self.behaviour
        assert behaviour._is_usdc(USDC_POLYGON) is True
        assert behaviour._is_usdc(USCDE_POLYGON) is True
        assert behaviour._is_usdc(WXDAI) is False
        assert behaviour._is_usdc("0xrandom") is False

    def test_get_bet_amount_with_none_logger_level(self) -> None:
        """Test `get_bet_amount` when a logger level attribute is None."""
        behaviour = self.behaviour
        behaviour.download_strategies = lambda: (yield)  # type: ignore[assignment, method-assign]
        behaviour.wait_for_condition_with_sleep = lambda _: (yield)  # type: ignore[assignment, method-assign, misc]
        behaviour.params.strategies_kwargs = deepcopy(STRATEGIES_KWARGS)
        behaviour.params.use_fallback_strategy = False
        behaviour.params.is_running_on_polymarket = False
        behaviour.shared_state.chatui_config.trading_strategy = "test_strategy"
        behaviour.shared_state.chatui_config.max_bet_size = None
        behaviour.shared_state.chatui_config.fixed_bet_size = None
        behaviour.token_balance = 10**18
        behaviour.wallet_balance = 10**18

        # Mock execute_strategy to return results with log messages
        behaviour.execute_strategy = lambda *_, **__: {  # type: ignore[method-assign]
            BET_AMOUNT_FIELD: 50,
            "info": ["some log"],
        }
        behaviour.shared_state.strategies_executables = {
            "test_strategy": ("code", "method"),
        }

        # Make one of the logger levels return None via delattr simulation
        original_logger = behaviour.context.logger

        class LimitedLogger:
            """Logger that is missing 'warning' attribute."""

            def __init__(self, real_logger: Any) -> None:
                """Initialize with real logger."""
                self._real = real_logger

            def __getattr__(self, name: str) -> Any:
                """Get attr, returning None for 'warning'."""
                if name == "warning":
                    return None
                return getattr(self._real, name)

        behaviour.context.logger = LimitedLogger(original_logger)  # type: ignore[assignment]

        gen = behaviour.get_bet_amount(0.5, 0.5, 100, 100, 10, 0.8, WXDAI)
        for _ in range(2):
            next(gen)
        try:
            next(gen)
        except StopIteration as e:
            assert e.value == 50
