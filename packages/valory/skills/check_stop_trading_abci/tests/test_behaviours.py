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

import json
import logging
from pathlib import Path
from typing import Any, Generator, Optional
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.activity_goal import (
    record_trade,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AGENT_PERFORMANCE_SUMMARY_FILE,
)
from packages.valory.skills.chatui_abci.models import CHATUI_PARAM_STORE
from packages.valory.skills.check_stop_trading_abci.behaviours import (
    CheckStopTradingBehaviour,
    StopTradingResult,
)
from packages.valory.skills.check_stop_trading_abci.models import CheckStopTradingParams
from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
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


class TestCheckStopTradingBehaviour:
    """Tests for CheckStopTradingBehaviour."""

    def test_init(self) -> None:
        """Test __init__ sets _staking_kpi_request_count to 0."""
        with patch.object(StakingInteractBaseBehaviour, "__init__", return_value=None):
            b = CheckStopTradingBehaviour()
        assert b._staking_kpi_request_count == 0

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
        """When disable_trading is True, stop is True and signals are reset."""
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
            result = exc_info.value.value
            assert result.stop is True
            assert result.staking_kpi_met is False
            assert result.activity_target_met is False
            assert result.target == 0
            assert result.completed == 0

    def test_not_disabled_no_kpi_check(self) -> None:
        """When stop_trading_if_staking_kpi_met is False, never stop, but report signals."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = False
        mock_context.params.stop_trading_if_staking_kpi_met = False
        behaviour._service_staking_state = StakingState.UNSTAKED
        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            # activity target met, but the stop switch is off
            patch.object(
                behaviour, "_compute_activity_status", _return_gen((True, True, 8, 9))
            ),
        ):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            result = exc_info.value.value
            assert result.stop is False
            assert result.staking_kpi_met is True
            assert result.activity_target_met is True
            assert result.target == 8
            assert result.completed == 9

    def test_kpi_check_met(self) -> None:
        """When the switch is on and the activity target is met, stop is True."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = False
        mock_context.params.stop_trading_if_staking_kpi_met = True
        behaviour._service_staking_state = StakingState.UNSTAKED
        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(
                behaviour, "_compute_activity_status", _return_gen((True, True, 8, 8))
            ),
        ):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            result = exc_info.value.value
            assert result.stop is True
            assert result.activity_target_met is True

    def test_kpi_check_not_met(self) -> None:
        """When the switch is on but the activity target is not met, stop is False.

        Models the new regime: on-chain KPI met (farming) but the off-chain
        activity target not yet reached, so the agent keeps trading.
        """
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.params.disable_trading = False
        mock_context.params.stop_trading_if_staking_kpi_met = True
        behaviour._service_staking_state = StakingState.UNSTAKED
        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(
                behaviour, "_compute_activity_status", _return_gen((True, False, 8, 3))
            ),
        ):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            result = exc_info.value.value
            assert result.stop is False
            assert result.staking_kpi_met is True
            assert result.activity_target_met is False


PERIOD_START = 1000
NOW = 1010


class TestActivityGoalGate:
    """The stop vote needs both the staking side and the activity goal met."""

    @staticmethod
    def _run(  # pylint: disable=too-many-arguments
        store_path: Path,
        *,
        completed: int,
        new_regime: bool = True,
        staked: bool = True,
        trades: int = 0,
        default_goal: int = 8,
        stored_goal: Any = None,
        store_content: Optional[str] = None,
        disable_trading: bool = False,
    ) -> StopTradingResult:
        """Drive ``_compute_stop_trading`` over a real store directory.

        In the new regime the staking side is met at 8 mech requests; in the
        old regime it is met at the derived requirement of 11.

        :param store_path: the store directory.
        :param completed: mech requests made this epoch.
        :param new_regime: whether the staking contract is new-regime.
        :param staked: whether the service is staked.
        :param trades: trades placed this epoch before the evaluation.
        :param default_goal: the ``default_activity_goal`` param.
        :param stored_goal: the goal written to the chat store, if any.
        :param store_content: raw chat store content, overriding ``stored_goal``.
        :param disable_trading: the ``disable_trading`` param.
        :return: the evaluation result.
        """
        for i in range(trades):
            record_trade(store_path, PERIOD_START + i, f"bet_{i}")
        if store_content is not None:
            (store_path / CHATUI_PARAM_STORE).write_text(store_content)
        elif stored_goal is not None:
            (store_path / CHATUI_PARAM_STORE).write_text(
                json.dumps({"activity_goal": stored_goal})
            )

        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        behaviour.service_staking_state = (
            StakingState.STAKED if staked else StakingState.UNSTAKED
        )
        behaviour.staking_kpi_request_count = completed
        behaviour.service_info = [None, None, [None, 0]]  # type: ignore[assignment]
        behaviour.ts_checkpoint = PERIOD_START
        behaviour.liveness_period = 10
        behaviour.liveness_ratio = 10**18

        mock_context = MagicMock()
        mock_context.logger = logging.getLogger("check_stop_trading_test")
        params = mock_context.params
        params.disable_trading = disable_trading
        params.stop_trading_if_staking_kpi_met = True
        params.activity_target = 8
        params.default_activity_goal = default_goal
        params.store_path = store_path

        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(
                type(behaviour),
                "synced_timestamp",
                new_callable=PropertyMock,
                return_value=NOW,
            ),
            patch.object(behaviour, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(behaviour, "_is_new_staking_regime", _return_gen(new_regime)),
        ):
            gen = behaviour._compute_stop_trading()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
        return exc_info.value.value

    @staticmethod
    def _block(store_path: Path) -> Any:
        """Return the ``activity_goal`` block written to the summary."""
        with open(store_path / AGENT_PERFORMANCE_SUMMARY_FILE, "r") as f:
            return json.load(f)["activity_goal"]

    @pytest.mark.parametrize("new_regime", [True, False], ids=["new", "old"])
    @pytest.mark.parametrize("staking_side_met", [True, False])
    @pytest.mark.parametrize("goal_met", [True, False])
    def test_vote_matrix(
        self,
        tmp_path: Path,
        new_regime: bool,
        staking_side_met: bool,
        goal_met: bool,
    ) -> None:
        """Only the staking side and the goal together put the agent in standby."""
        required = 8 if new_regime else 11
        result = self._run(
            tmp_path,
            completed=required if staking_side_met else 3,
            new_regime=new_regime,
            trades=8 if goal_met else 7,
        )

        assert result.stop is (staking_side_met and goal_met)
        # The payload's staking-side fields keep their meaning.
        assert result.activity_target_met is staking_side_met
        assert self._block(tmp_path)["is_met"] is goal_met

    def test_disable_trading_stops_without_writing_block(self, tmp_path: Path) -> None:
        """Disabled trading stops at once and publishes nothing."""
        result = self._run(tmp_path, completed=0, disable_trading=True)

        assert result.stop is True
        assert not (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).exists()

    def test_unstaked_never_stops_and_writes_no_block(self, tmp_path: Path) -> None:
        """Without an epoch there is nothing to count against."""
        result = self._run(tmp_path, completed=100, staked=False, trades=100)

        assert result.stop is False
        assert not (tmp_path / AGENT_PERFORMANCE_SUMMARY_FILE).exists()

    def test_trades_before_period_start_do_not_count(self, tmp_path: Path) -> None:
        """Trades from the previous epoch are not progress."""
        record_trade(tmp_path, PERIOD_START - 1, "old")

        result = self._run(tmp_path, completed=8, default_goal=1)

        assert result.stop is False
        assert self._block(tmp_path)["progress"] == 0

    def test_writes_block(self, tmp_path: Path) -> None:
        """Each staked evaluation publishes the full block."""
        self._run(tmp_path, completed=8, trades=3)

        assert self._block(tmp_path) == {
            "unit": "trades",
            "target": 8,
            "progress": 3,
            "is_met": False,
            "period_start": PERIOD_START,
            "updated_at": NOW,
            "last_met_at": None,
        }

    def test_stored_goal_overrides_default(self, tmp_path: Path) -> None:
        """The user's goal replaces the default."""
        result = self._run(tmp_path, completed=8, trades=8, stored_goal=10)

        assert result.stop is False
        assert self._block(tmp_path)["target"] == 10

    def test_lowered_goal_stops_on_same_evaluation(self, tmp_path: Path) -> None:
        """A goal lowered to or below progress stops on the next evaluation."""
        result = self._run(tmp_path, completed=8, trades=3, stored_goal=3)

        assert result.stop is True
        assert self._block(tmp_path)["last_met_at"] == NOW

    @pytest.mark.parametrize(
        "store_content",
        [
            json.dumps({"activity_goal": None}),
            json.dumps({"activity_goal": True}),
            json.dumps({"activity_goal": 2.0}),
            json.dumps({"activity_goal": -1}),
            json.dumps({"activity_goal": "3"}),
            json.dumps({"trading_strategy": "kelly_criterion"}),
            json.dumps(["not", "a", "dict"]),
            "{not json",
        ],
        ids=[
            "null",
            "bool",
            "float",
            "negative",
            "string",
            "absent",
            "not_a_dict",
            "corrupt",
        ],
    )
    def test_unusable_stored_goal_falls_back_to_default(
        self, tmp_path: Path, store_content: str
    ) -> None:
        """Anything but a valid stored goal uses the param default."""
        self._run(tmp_path, completed=8, default_goal=5, store_content=store_content)

        assert self._block(tmp_path)["target"] == 5

    def test_missing_store_falls_back_to_default(self, tmp_path: Path) -> None:
        """No chat store at all uses the param default."""
        self._run(tmp_path, completed=8, default_goal=5)

        assert self._block(tmp_path)["target"] == 5

    @pytest.mark.parametrize(
        "stored_goal, source",
        [(None, "default_activity_goal"), (2, CHATUI_PARAM_STORE)],
    )
    def test_logs_goal_line(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        stored_goal: Optional[int],
        source: str,
    ) -> None:
        """One INFO line carries everything needed to diagnose a standby."""
        with caplog.at_level(logging.INFO, logger="check_stop_trading_test"):
            self._run(
                tmp_path, completed=8, trades=2, default_goal=8, stored_goal=stored_goal
            )

        lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert len(lines) == 1
        target = 8 if stored_goal is None else stored_goal
        goal_met = stored_goal is not None
        assert lines[0] == (
            f"Activity goal: target={target} (from {source}, "
            f"default_activity_goal=8), progress=2, period_start={PERIOD_START}, "
            f"goal_met={goal_met}, activity_target_met=True, stop_trading={goal_met}"
        )


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

        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(
                type(behaviour),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_sync_data,
            ),
            patch.object(behaviour, "contract_interact", _return_gen(True)),
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


class TestRequiredMechRequests:
    """Tests for CheckStopTradingBehaviour._required_mech_requests."""

    def test_pure_arithmetic(self) -> None:
        """The requirement is the livenessRatio-derived value plus the safety margin."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        with patch.object(
            type(behaviour),
            "synced_timestamp",
            new_callable=PropertyMock,
            return_value=1010,
        ):
            # ceil(max(10, 1010-1000) * 10^18 / 10^18) + 1 = 10 + 1 = 11
            assert (
                behaviour._required_mech_requests(
                    last_ts_checkpoint=1000,
                    liveness_period=10,
                    liveness_ratio=10**18,
                )
                == 11
            )


class TestComputeActivityStatus:
    """Tests for CheckStopTradingBehaviour._compute_activity_status."""

    def _make_behaviour(self) -> CheckStopTradingBehaviour:
        """Create a behaviour instance with pre-set state attributes."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        return behaviour

    def test_not_staked(self) -> None:
        """When service is not staked, returns the all-zero / all-false tuple."""
        behaviour = self._make_behaviour()
        behaviour.service_staking_state = StakingState.UNSTAKED
        mock_context = MagicMock()
        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(behaviour, "wait_for_condition_with_sleep", _noop_gen),
        ):
            gen = behaviour._compute_activity_status()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value == (False, False, 0, 0)

    def _staked_status(self, new_regime: bool, activity_target: int) -> tuple:
        """Drive _compute_activity_status for a staked service in the given regime."""
        behaviour = self._make_behaviour()
        behaviour.service_staking_state = StakingState.STAKED
        behaviour.staking_kpi_request_count = 8
        behaviour.service_info = [None, None, [None, 5]]  # type: ignore[assignment]
        behaviour.ts_checkpoint = 1000
        behaviour.liveness_period = 10
        behaviour.liveness_ratio = 10**18
        mock_context = MagicMock()
        mock_context.params.activity_target = activity_target

        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(
                type(behaviour),
                "synced_timestamp",
                new_callable=PropertyMock,
                return_value=1010,
            ),
            patch.object(behaviour, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(behaviour, "_is_new_staking_regime", _return_gen(new_regime)),
        ):
            gen = behaviour._compute_activity_status()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            return exc_info.value.value

    def test_old_regime_tracks_on_chain_requirement(self) -> None:
        """Old regime: target is the derived requirement and activity == KPI."""
        # completed = 8 - 5 = 3; required = ceil(max(10,10)) + 1 = 11
        staking_kpi_met, activity_target_met, target, completed = self._staked_status(
            new_regime=False, activity_target=8
        )
        assert completed == 3
        assert target == 11  # the derived on-chain requirement
        assert staking_kpi_met is False  # 3 >= 11
        assert activity_target_met is False  # mirrors the on-chain KPI

    def test_new_regime_tracks_off_chain_target(self) -> None:
        """New regime: target is the off-chain config value, independent of the KPI."""
        # completed = 8 - 5 = 3; off-chain target = 8 ⇒ not met
        staking_kpi_met, activity_target_met, target, completed = self._staked_status(
            new_regime=True, activity_target=8
        )
        assert completed == 3
        assert target == 8  # the off-chain configured target
        assert activity_target_met is False  # 3 >= 8 is False
        # on-chain KPI is still computed independently (3 >= 11 is False here)
        assert staking_kpi_met is False

    def test_new_regime_target_met(self) -> None:
        """New regime: activity target met once completed reaches the off-chain target."""
        # completed = 8 - 5 = 3; lower the target to 2 ⇒ met
        staking_kpi_met, activity_target_met, target, completed = self._staked_status(
            new_regime=True, activity_target=2
        )
        assert completed == 3
        assert target == 2
        assert activity_target_met is True  # 3 >= 2


class TestAsyncAct:
    """Tests for CheckStopTradingBehaviour.async_act."""

    def test_async_act(self) -> None:
        """Drives async_act to completion and asserts the emitted payload fields."""
        behaviour = object.__new__(CheckStopTradingBehaviour)
        behaviour._staking_kpi_request_count = 0
        mock_context = MagicMock()
        mock_context.agent_address = "agent_0"
        mock_set_done = MagicMock()

        sent_payloads = []

        def _capture_send(payload: Any, *args: Any, **kwargs: Any) -> Generator:
            """Capture the payload handed to send_a2a_transaction."""
            sent_payloads.append(payload)
            if False:
                yield  # pragma: no cover

        with (
            patch.object(
                type(behaviour),
                "context",
                new_callable=PropertyMock,
                return_value=mock_context,
            ),
            patch.object(
                type(behaviour),
                "behaviour_id",
                new_callable=PropertyMock,
                return_value="test_behaviour",
            ),
            patch.object(
                behaviour,
                "_compute_stop_trading",
                _return_gen(
                    StopTradingResult(
                        stop=True,
                        staking_kpi_met=True,
                        activity_target_met=False,
                        target=8,
                        completed=9,
                    )
                ),
            ),
            patch.object(behaviour, "send_a2a_transaction", _capture_send),
            patch.object(behaviour, "wait_until_round_end", _noop_gen),
            patch.object(behaviour, "set_done", mock_set_done),
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)
            mock_set_done.assert_called_once()

        # the StopTradingResult fields must be threaded into the payload verbatim
        # and onto the right kwargs (a swapped kwarg would otherwise pass).
        assert len(sent_payloads) == 1
        payload = sent_payloads[0]
        assert isinstance(payload, CheckStopTradingPayload)
        assert payload.sender == "agent_0"
        assert payload.vote is True
        assert payload.is_staking_kpi_met is True
        assert payload.is_activity_target_met is False
        assert payload.activity_target == 8
        assert payload.activity_completed == 9
