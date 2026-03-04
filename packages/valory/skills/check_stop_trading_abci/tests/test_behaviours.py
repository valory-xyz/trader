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

"""Tests for check_stop_trading_abci behaviours."""

from typing import Any, Generator
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.check_stop_trading_abci.behaviours import (
    CheckStopTradingBehaviour,
    CheckStopTradingRoundBehaviour,
    LIVENESS_RATIO_SCALE_FACTOR,
    REQUIRED_MECH_REQUESTS_SAFETY_MARGIN,
)
from packages.valory.skills.check_stop_trading_abci.models import CheckStopTradingParams
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
    CheckStopTradingRound,
)
from packages.valory.skills.staking_abci.behaviours import StakingInteractBaseBehaviour
from packages.valory.skills.staking_abci.rounds import StakingState


def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """No-op generator for mocking yield from calls."""
    if False:
        yield  # pragma: no cover


def _return_gen(value: Any):  # type: ignore
    """Create a factory that returns a generator immediately returning a value."""

    def gen(*args: Any, **kwargs: Any) -> Generator:
        """Generator that returns value."""
        return value
        yield  # pragma: no cover  # unreachable, makes it a generator

    return gen


class TestCheckStopTradingRoundBehaviour:
    """Tests for CheckStopTradingRoundBehaviour attributes."""

    def test_initial_behaviour_cls(self) -> None:
        """Initial_behaviour_cls is CheckStopTradingBehaviour."""
        assert (
            CheckStopTradingRoundBehaviour.initial_behaviour_cls
            is CheckStopTradingBehaviour
        )

    def test_abci_app_cls(self) -> None:
        """Abci_app_cls is CheckStopTradingAbciApp."""
        assert CheckStopTradingRoundBehaviour.abci_app_cls is CheckStopTradingAbciApp  # type: ignore[misc]

    def test_behaviours_set(self) -> None:
        """Behaviours set contains only CheckStopTradingBehaviour."""
        assert CheckStopTradingRoundBehaviour.behaviours == {CheckStopTradingBehaviour}


class TestCheckStopTradingBehaviour:
    """Tests for CheckStopTradingBehaviour."""

    def test_matching_round(self) -> None:
        """Matching_round is CheckStopTradingRound."""
        assert CheckStopTradingBehaviour.matching_round is CheckStopTradingRound

    def test_init(self) -> None:
        """Test __init__ sets _staking_kpi_request_count to 0."""
        with patch.object(StakingInteractBaseBehaviour, "__init__", return_value=None):
            b = CheckStopTradingBehaviour()
        assert b._staking_kpi_request_count == 0

    def test_staking_kpi_request_count_property(self) -> None:
        """Test getter and setter for staking_kpi_request_count."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0

        assert behaviour.staking_kpi_request_count == 0

        behaviour.staking_kpi_request_count = 42
        assert behaviour.staking_kpi_request_count == 42

    def test_is_first_period_true(self) -> None:
        """Is_first_period returns True when period_count is 0."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        mock_sync_data = MagicMock()
        mock_sync_data.period_count = 0
        with patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ):
            assert behaviour.is_first_period is True

    def test_is_first_period_false(self) -> None:
        """Is_first_period returns False when period_count > 0."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        mock_sync_data = MagicMock()
        mock_sync_data.period_count = 5
        with patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ):
            assert behaviour.is_first_period is False

    def test_params_property(self) -> None:
        """Params returns context.params cast to CheckStopTradingParams."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        mock_context = MagicMock()
        mock_params = MagicMock(spec=CheckStopTradingParams)
        mock_context.params = mock_params
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ):
            assert behaviour.params is mock_params


class TestComputeStopTrading:
    """Tests for CheckStopTradingBehaviour._compute_stop_trading."""

    def test_disabled(self) -> None:
        """When disable_trading is True, returns True."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = True
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_not_disabled_no_kpi_check(self) -> None:
        """When both disable and kpi check are False, returns False."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = False
        mock_context.params.stop_trading_if_staking_kpi_met = False
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_kpi_check_met(self) -> None:
        """When stop_trading_if_staking_kpi_met=True and KPI met, returns True."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = False
        mock_context.params.stop_trading_if_staking_kpi_met = True
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(behaviour, "is_staking_kpi_met", _return_gen(True)):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_kpi_check_not_met(self) -> None:
        """When stop_trading_if_staking_kpi_met=True and KPI not met, returns False."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = False
        mock_context.params.stop_trading_if_staking_kpi_met = True
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(behaviour, "is_staking_kpi_met", _return_gen(False)):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False


class TestGetStakingKpiRequestCount:
    """Tests for CheckStopTradingBehaviour._get_staking_kpi_request_count."""

    def _run(self, use_marketplace: bool) -> None:
        """Run the generator with the given marketplace flag."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.use_mech_marketplace = use_marketplace
        mock_context.params.staking_kpi_mech_count_request_address = "0xAddr"
        mock_sync_data = MagicMock()
        mock_sync_data.safe_contract_address = "0xSafe"

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ), patch.object(
            behaviour, "contract_interact", _return_gen(True)
        ):
            gen = behaviour._get_staking_kpi_request_count()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_with_marketplace(self) -> None:
        """When use_mech_marketplace=True, uses AgentMech contract."""
        self._run(use_marketplace=True)

    def test_without_marketplace(self) -> None:
        """When use_mech_marketplace=False, uses Mech contract."""
        self._run(use_marketplace=False)


class TestIsStakingKpiMet:
    """Tests for CheckStopTradingBehaviour.is_staking_kpi_met."""

    def _make_behaviour(self) -> CheckStopTradingBehaviour:
        """Create a behaviour instance with pre-set state attributes."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        return behaviour

    def test_not_staked(self) -> None:
        """When service is not staked, returns False."""
        behaviour = self._make_behaviour()
        behaviour.service_staking_state = StakingState.UNSTAKED
        mock_context = MagicMock()

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(behaviour, "wait_for_condition_with_sleep", _noop_gen):
            gen = behaviour.is_staking_kpi_met()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_staked_kpi_met(self) -> None:
        """When staked and enough mech requests, returns True."""
        behaviour = self._make_behaviour()
        behaviour.service_staking_state = StakingState.STAKED
        behaviour.staking_kpi_request_count = 100
        # service_info index 2,1 holds the mech_request_count_on_last_checkpoint
        behaviour.ts_checkpoint = 1000
        behaviour.liveness_period = 10
        behaviour.liveness_ratio = 10**18  # 1 request per second
        mock_context = MagicMock()

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "synced_timestamp",
            new_callable=PropertyMock,
            return_value=1010,
        ), patch.object(
            behaviour, "wait_for_condition_with_sleep", _noop_gen
        ):
            gen = behaviour.is_staking_kpi_met()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            # mech_requests_since_last_cp = 100 - 5 = 95
            # required = ceil(max(10, 10) * 10^18 / 10^18) + 1 = 11
            # 95 >= 11 → True
            assert exc_info.value.value is True

    def test_staked_kpi_not_met(self) -> None:
        """When staked but not enough mech requests, returns False."""
        behaviour = self._make_behaviour()
        behaviour.service_staking_state = StakingState.STAKED
        behaviour.staking_kpi_request_count = 6
        behaviour.service_info = [None, None, [None, 5]]  # type: ignore[assignment]
        behaviour.ts_checkpoint = 1000
        behaviour.liveness_period = 10
        behaviour.liveness_ratio = 10**18
        mock_context = MagicMock()

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "synced_timestamp",
            new_callable=PropertyMock,
            return_value=1010,
        ), patch.object(
            behaviour, "wait_for_condition_with_sleep", _noop_gen
        ):
            gen = behaviour.is_staking_kpi_met()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            # mech_requests_since_last_cp = 6 - 5 = 1
            # required = ceil(max(10, 10) * 10^18 / 10^18) + 1 = 11
            # 1 >= 11 → False
            assert exc_info.value.value is False


class TestAsyncAct:
    """Tests for CheckStopTradingBehaviour.async_act."""

    def test_async_act(self) -> None:
        """Drives the full async_act generator to completion."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.agent_address = "agent_0"
        mock_set_done = MagicMock()

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "behaviour_id",
            new_callable=PropertyMock,
            return_value="test_behaviour",
        ), patch.object(
            behaviour, "_compute_stop_trading", _return_gen(True)
        ), patch.object(
            behaviour, "send_a2a_transaction", _noop_gen
        ), patch.object(
            behaviour, "wait_until_round_end", _noop_gen
        ), patch.object(
            behaviour, "set_done", mock_set_done
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)
            mock_set_done.assert_called_once()


class TestConstants:
    """Tests for module-level constants."""

    def test_liveness_ratio_scale_factor(self) -> None:
        """LIVENESS_RATIO_SCALE_FACTOR is 10^18."""
        assert LIVENESS_RATIO_SCALE_FACTOR == 10**18

    def test_safety_margin(self) -> None:
        """REQUIRED_MECH_REQUESTS_SAFETY_MARGIN is 1."""
        assert REQUIRED_MECH_REQUESTS_SAFETY_MARGIN == 1
