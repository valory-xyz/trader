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

"""Tests for staking_abci behaviours."""

from pathlib import Path
from typing import Any, Generator, Tuple
from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import pytest

from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)
from packages.valory.contracts.staking_token.contract import StakingTokenContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    BaseBehaviour,
    TimeoutException,
)
from packages.valory.skills.staking_abci.behaviours import (
    CHECKPOINT_FILENAME,
    CallCheckpointBehaviour,
    NULL_ADDRESS,
    StakingInteractBaseBehaviour,
    is_checkpoint_due,
    should_send_checkpoint,
)
from packages.valory.skills.staking_abci.models import StakingParams
from packages.valory.skills.staking_abci.rounds import (
    CallCheckpointRound,
    StakingState,
    SynchronizedData,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


class _ConcreteStakingBehaviour(StakingInteractBaseBehaviour):
    """Concrete subclass for testing the abstract StakingInteractBaseBehaviour."""

    matching_round = CallCheckpointRound

    def async_act(self):  # type: ignore
        """No-op implementation of abstract method."""
        yield  # pragma: no cover


def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """No-op generator for mocking yield from calls."""
    if False:
        yield  # pragma: no cover


def _return_gen(value: Any):  # type: ignore
    """Create a factory returning a generator that immediately returns a value."""

    def gen(*args: Any, **kwargs: Any) -> Generator:
        """Generator returning value."""
        return value
        yield  # pragma: no cover

    return gen


# ---------------------------------------------------------------------------
# Checkpoint rules
# ---------------------------------------------------------------------------


class TestIsCheckpointDue:
    """Tests for is_checkpoint_due."""

    @pytest.mark.parametrize(
        "next_ts, ts_checkpoint, liveness_period, synced_ts, expected",
        [
            # getter equals tsCheckpoint + livenessPeriod: due only once reached
            (1100, 1000, 100, 1099, False),
            (1100, 1000, 100, 1100, True),
            (1100, 1000, 100, 1101, True),
            # pending rebaseline: getter returns block.timestamp, due immediately
            (1050, 1000, 100, 1049, True),
            (1050, 1000, 100, 1050, True),
            (1200, 1000, 100, 1100, True),
        ],
    )
    def test_is_checkpoint_due(
        self,
        next_ts: int,
        ts_checkpoint: int,
        liveness_period: int,
        synced_ts: int,
        expected: bool,
    ) -> None:
        """A checkpoint is due on a rebaseline signal or once the next timestamp is reached."""
        assert (
            is_checkpoint_due(next_ts, ts_checkpoint, liveness_period, synced_ts)
            is expected
        )


class TestShouldSendCheckpoint:
    """Tests for should_send_checkpoint."""

    @pytest.mark.parametrize(
        "due, rebaseline_signal, available_rewards, expected",
        [
            (False, False, 1, False),
            (False, True, 1, False),
            (True, False, 0, False),
            (True, False, 1, True),
            (True, True, 0, True),
            (True, True, 1, True),
        ],
    )
    def test_should_send_checkpoint(
        self,
        due: bool,
        rebaseline_signal: bool,
        available_rewards: int,
        expected: bool,
    ) -> None:
        """A due checkpoint is skipped only on an empty reserve without a rebaseline."""
        assert (
            should_send_checkpoint(due, rebaseline_signal, available_rewards)
            is expected
        )


# ---------------------------------------------------------------------------
# StakingInteractBaseBehaviour
# ---------------------------------------------------------------------------


class TestStakingInteractBaseBehaviourInit:
    """Tests for StakingInteractBaseBehaviour.__init__."""

    def test_init(self) -> None:
        """__init__ sets default state attributes."""
        with patch.object(BaseBehaviour, "__init__", return_value=None):
            b = _ConcreteStakingBehaviour()
        assert b._service_staking_state == StakingState.UNSTAKED
        assert b._checkpoint_ts == 0
        assert b._agent_ids == "[]"


class TestStakingInteractProperties:
    """Tests for StakingInteractBaseBehaviour property accessors."""

    def _make(self) -> StakingInteractBaseBehaviour:
        """Create a bare instance."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        b._service_staking_state = StakingState.UNSTAKED  # type: ignore[type-abstract]
        b._checkpoint_ts = 0
        b._agent_ids = "[]"
        return b

    def test_params_property(self) -> None:
        """Params returns context.params."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_params = MagicMock(spec=StakingParams)
        mock_ctx.params = mock_params
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.params is mock_params

    def test_use_v2_true(self) -> None:
        """Use_v2 is True when mech_activity_checker_contract is not NULL_ADDRESS."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = "0xSomeAddress"
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.use_v2 is True

    def test_use_v2_false(self) -> None:
        """Use_v2 is False when mech_activity_checker_contract is NULL_ADDRESS."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = NULL_ADDRESS
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.use_v2 is False

    def test_synced_timestamp(self) -> None:
        """Synced_timestamp returns int from round_sequence."""
        b = self._make()
        mock_rs = MagicMock()
        mock_rs.last_round_transition_timestamp.timestamp.return_value = 1700000000.5
        with patch.object(
            type(b),
            "round_sequence",
            new_callable=PropertyMock,
            return_value=mock_rs,
        ):
            assert b.synced_timestamp == 1700000000

    def test_synced_timestamp_falls_back_to_local_clock(self) -> None:
        """Synced_timestamp falls back to the local clock before any transition."""
        b = self._make()
        mock_rs = MagicMock()
        type(mock_rs).last_round_transition_timestamp = PropertyMock(
            side_effect=ValueError("no transition has been completed yet")
        )
        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b),
                "round_sequence",
                new_callable=PropertyMock,
                return_value=mock_rs,
            ),
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch(
                "packages.valory.skills.staking_abci.behaviours.datetime"
            ) as mock_datetime,
        ):
            mock_datetime.now.return_value.timestamp.return_value = 1700000000.5
            assert b.synced_timestamp == 1700000000

        mock_ctx.logger.warning.assert_called_once()

    def test_staking_contract_address(self) -> None:
        """Staking_contract_address delegates to params."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.staking_contract_address = "0xStaking"
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.staking_contract_address == "0xStaking"

    def test_mech_activity_checker_contract(self) -> None:
        """Mech_activity_checker_contract delegates to params."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = "0xMechChecker"
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.mech_activity_checker_contract == "0xMechChecker"

    def test_service_staking_state_getter(self) -> None:
        """Service_staking_state returns the internal state."""
        b = self._make()
        assert b.service_staking_state == StakingState.UNSTAKED

    def test_service_staking_state_setter_enum(self) -> None:
        """Service_staking_state setter accepts StakingState enum."""
        b = self._make()
        b.service_staking_state = StakingState.STAKED
        assert b.service_staking_state == StakingState.STAKED

    def test_service_staking_state_setter_int(self) -> None:
        """Service_staking_state setter converts int to StakingState."""
        b = self._make()
        b.service_staking_state = 2  # EVICTED
        assert b.service_staking_state == StakingState.EVICTED

    def test_next_checkpoint_getter_setter(self) -> None:
        """Next_checkpoint getter/setter round-trip."""
        b = self._make()
        b.next_checkpoint = 42
        assert b.next_checkpoint == 42

    def test_available_rewards_getter_setter(self) -> None:
        """Available_rewards getter/setter round-trip."""
        b = self._make()
        b.available_rewards = 7
        assert b.available_rewards == 7

    def test_ts_checkpoint_getter_setter(self) -> None:
        """Ts_checkpoint getter/setter round-trip."""
        b = self._make()
        b.ts_checkpoint = 999
        assert b.ts_checkpoint == 999

    def test_liveness_period_getter_setter(self) -> None:
        """Liveness_period getter/setter round-trip."""
        b = self._make()
        b.liveness_period = 100
        assert b.liveness_period == 100

    def test_liveness_ratio_getter_setter(self) -> None:
        """Liveness_ratio getter/setter round-trip."""
        b = self._make()
        b.liveness_ratio = 10**18
        assert b.liveness_ratio == 10**18

    def test_service_info_getter_setter(self) -> None:
        """Service_info getter/setter round-trip."""
        b = self._make()
        info = (1, 2, (3, 4))
        b.service_info = info  # type: ignore
        assert b.service_info == info

    def test_agent_ids_getter_setter(self) -> None:
        """Agent_ids setter serializes list to JSON string."""
        b = self._make()
        b.agent_ids = [1, 2, 3]  # type: ignore
        assert b.agent_ids == "[1, 2, 3]"


# ---------------------------------------------------------------------------
# wait_for_condition_with_sleep
# ---------------------------------------------------------------------------


class TestWaitForConditionWithSleep:
    """Tests for wait_for_condition_with_sleep."""

    def _make(self) -> StakingInteractBaseBehaviour:
        """Create a behaviour with mocked context."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        b._service_staking_state = StakingState.UNSTAKED  # type: ignore[type-abstract]
        b._checkpoint_ts = 0
        b._agent_ids = "[]"
        return b

    def test_immediate_success(self) -> None:
        """Condition satisfied on first call breaks immediately."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.staking_interaction_sleep_time = 1

        def condition() -> Generator[None, None, bool]:
            return True
            yield  # pragma: no cover

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            gen = b.wait_for_condition_with_sleep(condition)
            with pytest.raises(StopIteration):
                next(gen)

    def test_retries_until_success(self) -> None:
        """Condition retried until it returns True."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.staking_interaction_sleep_time = 0

        call_count = 0

        def condition() -> Generator[None, None, bool]:
            nonlocal call_count
            call_count += 1
            return call_count >= 2
            yield  # pragma: no cover

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "sleep", _noop_gen),
        ):
            gen = b.wait_for_condition_with_sleep(condition)
            with pytest.raises(StopIteration):
                next(gen)
        assert call_count == 2

    def test_timeout_raises(self) -> None:
        """Test that TimeoutException is raised when deadline is exceeded."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.staking_interaction_sleep_time = 0

        def condition() -> Generator[None, None, bool]:
            return False
            yield  # pragma: no cover

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "sleep", _noop_gen),
        ):
            gen = b.wait_for_condition_with_sleep(condition, timeout=0)
            with pytest.raises(TimeoutException):
                # Drive the generator past the first iteration
                while True:
                    next(gen)


# ---------------------------------------------------------------------------
# default_error
# ---------------------------------------------------------------------------


class TestDefaultError:
    """Tests for default_error."""

    def test_logs_error(self) -> None:
        """Default_error logs an error message."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            b.default_error("contract_id", "callable_name", "response_msg")  # type: ignore[arg-type]
        mock_ctx.logger.error.assert_called_once()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# contract_interact
# ---------------------------------------------------------------------------


class TestContractInteract:
    """Tests for contract_interact."""

    def _make(self) -> StakingInteractBaseBehaviour:
        """Create a behaviour."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        return b  # type: ignore[type-abstract]

    def test_success(self) -> None:
        """Successful interaction sets placeholder attribute."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_chain_id = "1"
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"data_key": "result_value"}

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "get_contract_api_response", _return_gen(response_msg)),
        ):
            gen = b.contract_interact(
                contract_address="0x1",
                contract_public_id=MagicMock(),
                contract_callable="fn",
                data_key="data_key",
                placeholder="my_result",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True
        assert b.my_result == "result_value"  # type: ignore[attr-defined]

    def test_wrong_performative(self) -> None:
        """Wrong performative returns False."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_chain_id = "1"
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "get_contract_api_response", _return_gen(response_msg)),
        ):
            gen = b.contract_interact(
                contract_address="0x1",
                contract_public_id=MagicMock(),
                contract_callable="fn",
                data_key="data_key",
                placeholder="my_result",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_missing_data_key(self) -> None:
        """Missing data_key in body returns False."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_chain_id = "1"
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"other_key": "value"}

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "get_contract_api_response", _return_gen(response_msg)),
        ):
            gen = b.contract_interact(
                contract_address="0x1",
                contract_public_id=MagicMock(),
                contract_callable="fn",
                data_key="data_key",
                placeholder="my_result",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False


# ---------------------------------------------------------------------------
# _staking_contract_interact / _mech_activity_checker_contract_interact
# ---------------------------------------------------------------------------


class TestStakingContractInteract:
    """Tests for _staking_contract_interact."""

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_delegates_to_contract_interact(self, use_v2: bool) -> None:
        """Delegates to contract_interact with correct contract type."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.staking_contract_address = "0xStaking"
        mock_ctx.params.mech_activity_checker_contract = (
            "0xNonNull" if use_v2 else NULL_ADDRESS
        )

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "contract_interact", _return_gen(True)),
        ):
            gen = b._staking_contract_interact(
                contract_callable="test_fn",
                placeholder="test_placeholder",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


class TestMechActivityCheckerContractInteract:
    """Tests for _mech_activity_checker_contract_interact."""

    def test_delegates_to_contract_interact(self) -> None:
        """Delegates to contract_interact with MechActivityContract."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.mech_activity_checker_contract = "0xMechChecker"

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "contract_interact", _return_gen(True)),
        ):
            gen = b._mech_activity_checker_contract_interact(
                contract_callable="test_fn",
                placeholder="test_placeholder",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


# ---------------------------------------------------------------------------
# _check_service_staked
# ---------------------------------------------------------------------------


class TestCheckServiceStaked:
    """Tests for _check_service_staked."""

    def test_no_service_id(self) -> None:
        """No on_chain_service_id returns True (assumes unstaked)."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = None

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            gen = b._check_service_staked()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_with_service_id(self) -> None:
        """With on_chain_service_id, delegates to _staking_contract_interact."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = 42

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_staking_contract_interact", _return_gen(True)),
        ):
            gen = b._check_service_staked()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


# ---------------------------------------------------------------------------
# _get_* methods
# ---------------------------------------------------------------------------


class TestGetMethods:
    """Tests for _get_next_checkpoint, _get_ts_checkpoint, _get_liveness_period, _get_liveness_ratio."""

    def _make(self) -> StakingInteractBaseBehaviour:
        """Create a behaviour."""
        return object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]

    # type: ignore[type-abstract]
    def test_get_next_checkpoint(self) -> None:
        """_get_next_checkpoint delegates to _staking_contract_interact."""
        b = self._make()
        with patch.object(b, "_staking_contract_interact", _return_gen(True)):
            gen = b._get_next_checkpoint()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_get_ts_checkpoint(self) -> None:
        """_get_ts_checkpoint delegates to _staking_contract_interact."""
        b = self._make()
        with patch.object(b, "_staking_contract_interact", _return_gen(True)):
            gen = b._get_ts_checkpoint()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_get_liveness_period(self) -> None:
        """_get_liveness_period delegates to _staking_contract_interact."""
        b = self._make()
        with patch.object(b, "_staking_contract_interact", _return_gen(True)):
            gen = b._get_liveness_period()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_get_available_rewards(self) -> None:
        """_get_available_rewards reads available_rewards from the staking contract."""
        b = self._make()
        mock_interact = MagicMock(side_effect=_return_gen(True))
        with patch.object(b, "_staking_contract_interact", mock_interact):
            gen = b._get_available_rewards()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True
        mock_interact.assert_called_once_with(
            contract_callable="available_rewards", placeholder="available_rewards"
        )

    def test_get_liveness_ratio_v2(self) -> None:
        """_get_liveness_ratio uses mech_activity_checker when use_v2 is True."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = "0xNonNull"  # != NULL_ADDRESS

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(
                b, "_mech_activity_checker_contract_interact", _return_gen(True)
            ),
        ):
            gen = b._get_liveness_ratio()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_get_liveness_ratio_v1(self) -> None:
        """_get_liveness_ratio uses staking contract when use_v2 is False."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = NULL_ADDRESS

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_staking_contract_interact", _return_gen(True)),
        ):
            gen = b._get_liveness_ratio()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


# ---------------------------------------------------------------------------
# ensure_service_id / _get_service_info / _get_agent_ids
# ---------------------------------------------------------------------------


class TestEnsureServiceId:
    """Tests for ensure_service_id."""

    def test_none_returns_false(self) -> None:
        """Returns False when on_chain_service_id is None."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = None
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.ensure_service_id() is False

    def test_set_returns_true(self) -> None:
        """Returns True when on_chain_service_id is set."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = 42
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.ensure_service_id() is True


class TestGetServiceInfo:
    """Tests for _get_service_info."""

    def test_no_service_id_returns_true(self) -> None:
        """Returns True immediately when service_id is None."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = None
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            gen = b._get_service_info()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_with_service_id(self) -> None:
        """Delegates to _staking_contract_interact with service_id."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = 42
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_staking_contract_interact", _return_gen(True)),
        ):
            gen = b._get_service_info()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


class TestGetAgentIds:
    """Tests for _get_agent_ids."""

    def test_no_service_id_returns_true(self) -> None:
        """Returns True immediately when service_id is None."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = None
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            gen = b._get_agent_ids()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_with_service_id(self) -> None:
        """Delegates to _staking_contract_interact."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()  # type: ignore[type-abstract]
        mock_ctx.params.on_chain_service_id = 42
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_staking_contract_interact", _return_gen(True)),
        ):
            gen = b._get_agent_ids()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


# ---------------------------------------------------------------------------
# Staking-regime detection seam
# ---------------------------------------------------------------------------


def _gen_set(obj: Any, attr: str, value: Any):  # type: ignore
    """Factory: a generator that sets ``obj.attr = value`` and returns True."""

    def gen(*args: Any, **kwargs: Any) -> Generator[None, None, bool]:
        """Set the attribute then return True."""
        setattr(obj, attr, value)
        return True
        yield  # pragma: no cover

    return gen


def _fake_wait(condition_gen: Any, timeout: Any = None) -> Generator:
    """Stand-in for ``wait_for_condition_with_sleep`` that runs the condition once."""
    yield from condition_gen()


class TestReadOptionalContractValue:
    """Tests for _read_optional_contract_value."""

    def _make(self) -> StakingInteractBaseBehaviour:
        """Create a behaviour."""
        return object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]

    @pytest.mark.parametrize("value", ["0.2.0", None])
    def test_resolved_value_is_success(self, value: Any) -> None:
        """A RAW_TRANSACTION response sets the placeholder (even when data is None)."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_chain_id = "1"
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.RAW_TRANSACTION
        response_msg.raw_transaction.body = {"data": value}

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "get_contract_api_response", _return_gen(response_msg)),
        ):
            gen = b._read_optional_contract_value(
                contract_address="0x1",
                contract_public_id=MagicMock(),
                contract_callable="fn",
                placeholder="my_result",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True
        assert b.my_result == value  # type: ignore[attr-defined]

    def test_error_performative_returns_false(self) -> None:
        """A non-RAW_TRANSACTION (error) performative returns False so caller retries."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_chain_id = "1"
        response_msg = MagicMock()
        response_msg.performative = ContractApiMessage.Performative.ERROR

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "get_contract_api_response", _return_gen(response_msg)),
        ):
            gen = b._read_optional_contract_value(
                contract_address="0x1",
                contract_public_id=MagicMock(),
                contract_callable="fn",
                placeholder="my_result",
            )
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False


class TestGetActivityCheckerAndVersion:
    """Tests for _get_activity_checker and _get_checker_version."""

    def test_get_activity_checker_delegates(self) -> None:
        """_get_activity_checker delegates to _read_optional_contract_value."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        mock_ctx = MagicMock()
        mock_ctx.params.staking_contract_address = "0xStaking"
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_read_optional_contract_value", _return_gen(True)),
        ):
            gen = b._get_activity_checker()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_get_checker_version_delegates(self) -> None:
        """_get_checker_version delegates to _read_optional_contract_value."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        with patch.object(b, "_read_optional_contract_value", _return_gen(True)):
            gen = b._get_checker_version("0xChecker")
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


class TestIsNewStakingRegime:
    """Tests for _is_new_staking_regime (the detection seam)."""

    def _make(self, cached: Any = None) -> StakingInteractBaseBehaviour:
        """Create a behaviour with a shared-state cache field."""
        b = object.__new__(_ConcreteStakingBehaviour)  # type: ignore[type-abstract]
        b._activity_checker_address = None
        b._checker_version = None
        return b

    def _ctx(self, cached: Any = None) -> MagicMock:
        """Build a context whose ``state`` carries the cache field."""
        from types import SimpleNamespace

        mock_ctx = MagicMock()
        mock_ctx.state = SimpleNamespace(staking_regime_is_new=cached)
        return mock_ctx

    def test_cache_hit_skips_reads(self) -> None:
        """A populated shared-state cache is returned without any contract read."""
        b = self._make()
        mock_ctx = self._ctx(cached=True)
        get_checker = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_get_activity_checker", get_checker),
        ):
            gen = b._is_new_staking_regime()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True
        get_checker.assert_not_called()

    def test_cache_hit_false_skips_reads(self) -> None:
        """A cached ``False`` is a hit too (not just ``True``) — no read happens.

        The guard is ``cached is not None``, so a prior OLD verdict must be
        honoured without re-reading; only ``None`` (never computed) triggers a
        read.
        """
        b = self._make()
        mock_ctx = self._ctx(cached=False)
        get_checker = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "_get_activity_checker", get_checker),
        ):
            gen = b._is_new_staking_regime()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False
        get_checker.assert_not_called()

    def test_version_match_is_new_and_caches(self) -> None:
        """VERSION == '0.2.0' ⇒ new regime; verdict cached on shared state."""
        b = self._make()
        mock_ctx = self._ctx()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _fake_wait),
            patch.object(
                b,
                "_get_activity_checker",
                _gen_set(b, "activity_checker_address", "0xChecker"),
            ),
            patch.object(
                b,
                "_get_checker_version",
                _gen_set(b, "checker_version", "0.2.0"),
            ),
        ):
            gen = b._is_new_staking_regime()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True
        assert mock_ctx.state.staking_regime_is_new is True

    def test_unexpected_version_is_old(self) -> None:
        """An unexpected VERSION (e.g. '0.3.0') ⇒ old regime (conservative)."""
        b = self._make()
        mock_ctx = self._ctx()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _fake_wait),
            patch.object(
                b,
                "_get_activity_checker",
                _gen_set(b, "activity_checker_address", "0xChecker"),
            ),
            patch.object(
                b,
                "_get_checker_version",
                _gen_set(b, "checker_version", "0.3.0"),
            ),
        ):
            gen = b._is_new_staking_regime()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False
        assert mock_ctx.state.staking_regime_is_new is False

    def test_absent_version_is_old(self) -> None:
        """A genuinely absent VERSION (data=None) ⇒ old regime (fail-safe)."""
        b = self._make()
        mock_ctx = self._ctx()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _fake_wait),
            patch.object(
                b,
                "_get_activity_checker",
                _gen_set(b, "activity_checker_address", "0xChecker"),
            ),
            patch.object(
                b,
                "_get_checker_version",
                _gen_set(b, "checker_version", None),
            ),
        ):
            gen = b._is_new_staking_regime()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False
        assert mock_ctx.state.staking_regime_is_new is False

    @pytest.mark.parametrize("checker", [None, NULL_ADDRESS])
    def test_no_activity_checker_is_old_without_version_read(
        self, checker: Any
    ) -> None:
        """No activity checker (None / NULL) ⇒ old, and VERSION is never read."""
        b = self._make()
        mock_ctx = self._ctx()
        version_read = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _fake_wait),
            patch.object(
                b,
                "_get_activity_checker",
                _gen_set(b, "activity_checker_address", checker),
            ),
            patch.object(b, "_get_checker_version", version_read),
        ):
            gen = b._is_new_staking_regime()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False
        version_read.assert_not_called()
        assert mock_ctx.state.staking_regime_is_new is False


# ---------------------------------------------------------------------------
# CallCheckpointBehaviour
# ---------------------------------------------------------------------------


class TestCallCheckpointBehaviourInit:
    """Tests for CallCheckpointBehaviour.__init__."""

    def test_init(self) -> None:
        """__init__ sets default attributes."""
        mock_params = MagicMock()
        mock_params.store_path = Path("/tmp")  # nosec B108
        with (
            patch.object(StakingInteractBaseBehaviour, "__init__", return_value=None),
            patch.object(
                CallCheckpointBehaviour,
                "params",
                new_callable=PropertyMock,
                return_value=mock_params,
            ),
        ):
            b = CallCheckpointBehaviour()
        assert b._service_staking_state == StakingState.UNSTAKED
        assert b._next_checkpoint == 0
        assert b._checkpoint_data == b""
        assert b._safe_tx_hash == ""
        assert (
            b._checkpoint_filepath == Path("/tmp") / CHECKPOINT_FILENAME  # nosec B108
        )


class TestCallCheckpointBehaviourProperties:
    """Tests for CallCheckpointBehaviour properties."""

    def _make(self) -> CallCheckpointBehaviour:
        """Create a bare instance."""
        b = object.__new__(CallCheckpointBehaviour)
        b._service_staking_state = StakingState.UNSTAKED
        b._next_checkpoint = 0
        b._checkpoint_data = b""
        b._safe_tx_hash = ""
        b._checkpoint_ts = 0
        b._agent_ids = "[]"
        return b

    def test_params_property(self) -> None:
        """Params returns context.params."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_params = MagicMock(spec=StakingParams)
        mock_ctx.params = mock_params
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            assert b.params is mock_params

    def test_synchronized_data(self) -> None:
        """Synchronized_data wraps super().synchronized_data.db."""
        b = self._make()
        mock_sync = MagicMock()
        with patch.object(
            BaseBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ):
            result = b.synchronized_data
            assert isinstance(result, SynchronizedData)

    def test_is_first_period_true(self) -> None:
        """Is_first_period is True when period_count is 0."""
        b = self._make()
        mock_sync = MagicMock()
        mock_sync.period_count = 0
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ):
            assert b.is_first_period is True

    def test_is_first_period_false(self) -> None:
        """Is_first_period is False when period_count > 0."""
        b = self._make()
        mock_sync = MagicMock()
        mock_sync.period_count = 5
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ):
            assert b.is_first_period is False

    def test_new_checkpoint_detected_no_previous(self) -> None:
        """New_checkpoint_detected is False when previous_checkpoint is 0 (falsy)."""
        b = self._make()
        b._checkpoint_ts = 100
        mock_sync = MagicMock()
        mock_sync.previous_checkpoint = 0
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ):
            assert b.new_checkpoint_detected is False

    def test_new_checkpoint_detected_same(self) -> None:
        """New_checkpoint_detected is False when previous == current."""
        b = self._make()
        b._checkpoint_ts = 100
        mock_sync = MagicMock()
        mock_sync.previous_checkpoint = 100
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ):
            assert b.new_checkpoint_detected is False

    def test_new_checkpoint_detected_different(self) -> None:
        """New_checkpoint_detected is True when previous != current and is truthy."""
        b = self._make()
        b._checkpoint_ts = 200
        mock_sync = MagicMock()
        mock_sync.previous_checkpoint = 100
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ):
            assert b.new_checkpoint_detected is True

    def test_checkpoint_data_getter_setter(self) -> None:
        """Checkpoint_data getter/setter round-trip."""
        b = self._make()
        b.checkpoint_data = b"\x01\x02"
        assert b.checkpoint_data == b"\x01\x02"

    def test_safe_tx_hash_getter(self) -> None:
        """Safe_tx_hash getter returns internal value."""
        b = self._make()
        assert b.safe_tx_hash == ""

    def test_safe_tx_hash_setter_valid(self) -> None:
        """Safe_tx_hash setter strips first 2 chars (0x prefix)."""
        b = self._make()
        valid_hash = "0x" + "a" * (TX_HASH_LENGTH - 2)
        b.safe_tx_hash = valid_hash
        assert b.safe_tx_hash == "a" * (TX_HASH_LENGTH - 2)

    def test_safe_tx_hash_setter_invalid_length(self) -> None:
        """Safe_tx_hash setter raises ValueError for wrong length."""
        b = self._make()
        with pytest.raises(ValueError, match="Incorrect length"):
            b.safe_tx_hash = "0xshort"


# ---------------------------------------------------------------------------
# read_stored_timestamp / store_timestamp
# ---------------------------------------------------------------------------


class TestReadStoredTimestamp:
    """Tests for CallCheckpointBehaviour.read_stored_timestamp."""

    def _make(self) -> CallCheckpointBehaviour:
        """Create a bare instance with mocked context."""
        b = object.__new__(CallCheckpointBehaviour)
        b._checkpoint_filepath = Path("/tmp/checkpoint.txt")  # nosec B108
        return b

    def test_success(self) -> None:
        """Valid file with integer returns that integer."""
        b = self._make()
        m = mock_open(read_data="1700000000\n")
        with patch("builtins.open", m):
            result = b.read_stored_timestamp()
        assert result == 1700000000

    def test_file_not_found(self) -> None:
        """Test that FileNotFoundError returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch("builtins.open", side_effect=FileNotFoundError),
        ):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()

    def test_permission_error(self) -> None:
        """Test that PermissionError returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch("builtins.open", side_effect=PermissionError),
        ):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()

    def test_os_error(self) -> None:
        """Test that OSError returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch("builtins.open", side_effect=OSError),
        ):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()

    def test_parse_error(self) -> None:
        """Non-integer content returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        m = mock_open(read_data="not_a_number\n")
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch("builtins.open", m),
        ):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()


class TestStoreTimestamp:
    """Tests for CallCheckpointBehaviour.store_timestamp."""

    def _make(self) -> CallCheckpointBehaviour:
        """Create a bare instance."""
        b = object.__new__(CallCheckpointBehaviour)
        b._checkpoint_filepath = Path("/tmp/checkpoint.txt")  # nosec B108
        b._checkpoint_ts = 0
        return b

    def test_zero_timestamp(self) -> None:
        """Ts_checkpoint == 0 logs warning and returns 0."""
        b = self._make()
        mock_ctx = MagicMock()
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ):
            result = b.store_timestamp()
        assert result == 0
        mock_ctx.logger.warning.assert_called_once()

    def test_success(self) -> None:
        """Successful write returns number of chars written."""
        b = self._make()
        b._checkpoint_ts = 1700000000
        m = mock_open()
        m.return_value.write.return_value = 10
        with patch("builtins.open", m):
            result = b.store_timestamp()
        assert result == 10

    def test_write_io_error(self) -> None:
        """Test that IOError during write returns 0 and logs error."""
        b = self._make()
        b._checkpoint_ts = 1700000000
        mock_ctx = MagicMock()
        m = mock_open()
        m.return_value.write.side_effect = IOError("write failed")
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch("builtins.open", m),
        ):
            result = b.store_timestamp()
        assert result == 0
        mock_ctx.logger.error.assert_called_once()

    def test_open_error(self) -> None:
        """Error opening file returns 0 and logs error."""
        b = self._make()
        b._checkpoint_ts = 1700000000
        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch("builtins.open", side_effect=PermissionError),
        ):
            result = b.store_timestamp()
        assert result == 0
        mock_ctx.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _build_checkpoint_tx / _get_safe_tx_hash / _prepare_safe_tx
# ---------------------------------------------------------------------------


class TestBuildCheckpointTx:
    """Tests for _build_checkpoint_tx."""

    def test_delegates(self) -> None:
        """Delegates to _staking_contract_interact."""
        b = object.__new__(CallCheckpointBehaviour)
        with patch.object(b, "_staking_contract_interact", _return_gen(True)):
            gen = b._build_checkpoint_tx()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


class TestGetSafeTxHash:
    """Tests for _get_safe_tx_hash."""

    def test_delegates(self) -> None:
        """Delegates to contract_interact."""
        b = object.__new__(CallCheckpointBehaviour)
        b._checkpoint_data = b"\x00"
        mock_ctx = MagicMock()
        mock_ctx.params.staking_contract_address = "0xStaking"
        mock_sync = MagicMock()
        mock_sync.safe_contract_address = "0xSafe"

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(
                type(b),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_sync,
            ),
            patch.object(b, "contract_interact", _return_gen(True)),
        ):
            gen = b._get_safe_tx_hash()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


class TestPrepareSafeTx:
    """Tests for _prepare_safe_tx."""

    def test_returns_hex(self) -> None:
        """Returns hex from hash_payload_to_hex after building and hashing."""
        b = object.__new__(CallCheckpointBehaviour)
        b._safe_tx_hash = "a" * 64
        b._checkpoint_data = b"\x00"
        mock_ctx = MagicMock()
        mock_ctx.params.staking_contract_address = "0xStaking"

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch(
                "packages.valory.skills.staking_abci.behaviours.hash_payload_to_hex",
                return_value="0xresult",
            ) as mock_hash,
        ):
            gen = b._prepare_safe_tx()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value == "0xresult"
            mock_hash.assert_called_once()


# ---------------------------------------------------------------------------
# check_new_epoch
# ---------------------------------------------------------------------------


class TestCheckNewEpoch:
    """Tests for check_new_epoch."""

    def _make(self) -> CallCheckpointBehaviour:
        """Create a behaviour with defaults."""
        b = object.__new__(CallCheckpointBehaviour)
        b._checkpoint_ts = 100
        b._checkpoint_filepath = Path("/tmp/checkpoint.txt")  # nosec B108
        b._next_checkpoint = 0
        b._service_staking_state = StakingState.STAKED
        b._agent_ids = "[]"
        return b

    def test_no_change(self) -> None:
        """No new epoch when not first period and no new checkpoint."""
        b = self._make()
        mock_sync = MagicMock()
        mock_sync.period_count = 5
        mock_sync.previous_checkpoint = 100  # same as ts_checkpoint

        with (
            patch.object(
                type(b),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_sync,
            ),
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=MagicMock()
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
        ):
            gen = b.check_new_epoch()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_first_period_stored_invalidated(self) -> None:
        """First period with different stored timestamp detects change."""
        b = self._make()
        mock_sync = MagicMock()
        mock_sync.period_count = 0
        mock_sync.previous_checkpoint = 0  # falsy, no new_checkpoint_detected

        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_sync,
            ),
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(b, "read_stored_timestamp", return_value=50),
            patch.object(b, "store_timestamp", return_value=10),
        ):
            gen = b.check_new_epoch()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            # stored_timestamp (50) != ts_checkpoint (100) → invalidated
            assert exc_info.value.value is True

    def test_new_checkpoint_detected(self) -> None:
        """New checkpoint detected triggers store and returns True."""
        b = self._make()
        b._checkpoint_ts = 200
        mock_sync = MagicMock()
        mock_sync.period_count = 5
        mock_sync.previous_checkpoint = 100  # != 200 and truthy

        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_sync,
            ),
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(b, "store_timestamp", return_value=10),
        ):
            gen = b.check_new_epoch()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_store_timestamp_failure(self) -> None:
        """When store_timestamp returns 0, success log is not called."""
        b = self._make()
        b._checkpoint_ts = 200
        mock_sync = MagicMock()
        mock_sync.period_count = 5
        mock_sync.previous_checkpoint = 100  # != 200

        mock_ctx = MagicMock()
        with (
            patch.object(
                type(b),
                "synchronized_data",
                new_callable=PropertyMock,
                return_value=mock_sync,
            ),
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(b, "store_timestamp", return_value=0),
        ):
            gen = b.check_new_epoch()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


# ---------------------------------------------------------------------------
# async_act
# ---------------------------------------------------------------------------


class TestAsyncAct:
    """Tests for CallCheckpointBehaviour.async_act."""

    def _make(self) -> CallCheckpointBehaviour:
        """Create a behaviour with defaults."""
        b = object.__new__(CallCheckpointBehaviour)
        b._service_staking_state = StakingState.UNSTAKED
        b._next_checkpoint = 0
        b._checkpoint_data = b""
        b._safe_tx_hash = ""
        b._checkpoint_ts = 0
        b._agent_ids = "[]"
        return b

    def test_unstaked(self) -> None:
        """Unstaked service does not prepare safe tx."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.agent_address = "agent_0"
        mock_ctx.params.on_chain_service_id = 1
        mock_set_done = MagicMock()

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(
                type(b),
                "behaviour_id",
                new_callable=PropertyMock,
                return_value="test",
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(b, "check_new_epoch", _return_gen(False)),
            patch.object(b, "send_a2a_transaction", _noop_gen),
            patch.object(b, "wait_until_round_end", _noop_gen),
            patch.object(b, "set_done", mock_set_done),
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)
        mock_set_done.assert_called_once()

    @pytest.mark.parametrize(
        "should_call, expected_tx_hex", [(True, "0xtxhex"), (False, None)]
    )
    def test_staked_sends_checkpoint_only_when_it_should(
        self, should_call: bool, expected_tx_hex: Any
    ) -> None:
        """A staked service prepares the checkpoint tx only when it should be called."""
        b = self._make()
        b._service_staking_state = StakingState.STAKED
        mock_ctx = MagicMock()
        mock_ctx.agent_address = "agent_0"
        mock_ctx.params.on_chain_service_id = 1
        mock_prepare = MagicMock(side_effect=_return_gen("0xtxhex"))

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(
                type(b),
                "behaviour_id",
                new_callable=PropertyMock,
                return_value="test",
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(b, "_should_call_checkpoint", _return_gen(should_call)),
            patch.object(b, "_prepare_safe_tx", mock_prepare),
            patch.object(b, "check_new_epoch", _return_gen(False)),
            patch(
                "packages.valory.skills.staking_abci.behaviours.CallCheckpointPayload"
            ) as mock_payload,
            patch.object(b, "send_a2a_transaction", _noop_gen),
            patch.object(b, "wait_until_round_end", _noop_gen),
            patch.object(b, "set_done", MagicMock()),
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)
        assert mock_prepare.called is should_call
        assert mock_payload.call_args.args[2] == expected_tx_hex

    def test_evicted(self) -> None:
        """Evicted service logs critical message."""
        b = self._make()
        b._service_staking_state = StakingState.EVICTED
        mock_ctx = MagicMock()
        mock_ctx.agent_address = "agent_0"
        mock_ctx.params.on_chain_service_id = 1

        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(
                type(b),
                "behaviour_id",
                new_callable=PropertyMock,
                return_value="test",
            ),
            patch.object(b, "wait_for_condition_with_sleep", _noop_gen),
            patch.object(b, "check_new_epoch", _return_gen(False)),
            patch.object(b, "send_a2a_transaction", _noop_gen),
            patch.object(b, "wait_until_round_end", _noop_gen),
            patch.object(b, "set_done", MagicMock()),
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)
        mock_ctx.logger.critical.assert_called_once_with("Service has been evicted!")


# ---------------------------------------------------------------------------
# _should_call_checkpoint
# ---------------------------------------------------------------------------


class TestShouldCallCheckpoint:
    """Tests for CallCheckpointBehaviour._should_call_checkpoint."""

    SKIP_LOG = (
        "Skipping the checkpoint: the staking contract has no available "
        "rewards and no rebaseline is pending."
    )

    def _run(
        self,
        next_ts: int,
        available_rewards: int,
        synced_ts: int = 1100,
        use_v2: bool = True,
        ts_checkpoints: Tuple[int, ...] = (1000,),
    ) -> Any:
        """Run _should_call_checkpoint over successive ``tsCheckpoint`` reads."""
        b = object.__new__(CallCheckpointBehaviour)
        b._available_rewards = 0
        reads = {
            "get_next_checkpoint_ts": next_ts,
            "get_liveness_period": 100,
            "available_rewards": available_rewards,
        }
        ts_reads = list(ts_checkpoints)
        called = []

        def fake_contract_interact(
            contract_public_id: Any, contract_callable: str, placeholder: str, **_: Any
        ) -> Generator[None, None, bool]:
            """Record the read and set the placeholder."""
            called.append((contract_public_id, contract_callable))
            if contract_callable == "ts_checkpoint":
                value = ts_reads.pop(0) if len(ts_reads) > 1 else ts_reads[0]
            else:
                value = reads[contract_callable]
            setattr(b, placeholder, value)
            return True
            yield  # pragma: no cover

        def run_condition(condition_gen: Any, **_: Any) -> Generator:
            """Run the condition once."""
            result = yield from condition_gen()
            assert result is True

        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = (
            "0xNonNull" if use_v2 else NULL_ADDRESS
        )
        mock_rs = MagicMock()
        mock_rs.last_round_transition_timestamp.timestamp.return_value = float(
            synced_ts
        )
        with (
            patch.object(
                type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
            ),
            patch.object(
                type(b),
                "round_sequence",
                new_callable=PropertyMock,
                return_value=mock_rs,
            ),
            patch.object(b, "contract_interact", fake_contract_interact),
            patch.object(b, "wait_for_condition_with_sleep", run_condition),
        ):
            gen = b._should_call_checkpoint()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)

        expected_contract = (
            StakingTokenContract if use_v2 else ServiceStakingTokenContract
        ).contract_id
        assert {contract_id for contract_id, _ in called} == {expected_contract}
        return exc_info.value.value, [callable_ for _, callable_ in called], mock_ctx

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_not_due(self, use_v2: bool) -> None:
        """Before the next checkpoint and without a rebaseline, nothing is sent."""
        result, called, _ = self._run(
            next_ts=1100, available_rewards=1, synced_ts=1099, use_v2=use_v2
        )
        assert result is False
        assert "available_rewards" not in called

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_reached_with_rewards(self, use_v2: bool) -> None:
        """A reached checkpoint is sent when the reserve has rewards."""
        result, called, mock_ctx = self._run(
            next_ts=1100, available_rewards=1, use_v2=use_v2
        )
        assert result is True
        assert called[-1] == "available_rewards"
        mock_ctx.logger.info.assert_not_called()

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_reached_with_empty_reserve_is_skipped(self, use_v2: bool) -> None:
        """A reached checkpoint is skipped when the reserve is empty."""
        result, _, mock_ctx = self._run(
            next_ts=1100, available_rewards=0, use_v2=use_v2
        )
        assert result is False
        mock_ctx.logger.info.assert_called_once_with(self.SKIP_LOG)

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_rebaseline_pending_is_sent_before_reached(self, use_v2: bool) -> None:
        """A pending rebaseline is sent before its timestamp is reached, even on an empty reserve."""
        result, called, mock_ctx = self._run(
            next_ts=1060, available_rewards=0, synced_ts=1050, use_v2=use_v2
        )
        assert result is True
        assert "available_rewards" not in called
        mock_ctx.logger.info.assert_not_called()

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_concurrent_checkpoint_is_not_read_as_rebaseline(
        self, use_v2: bool
    ) -> None:
        """A checkpoint by another party between the reads is re-read, not taken for a rebaseline."""
        result, called, mock_ctx = self._run(
            next_ts=1150,
            available_rewards=0,
            synced_ts=1060,
            use_v2=use_v2,
            ts_checkpoints=(1000, 1050),
        )
        assert result is False
        assert called.count("ts_checkpoint") == 2
        assert "available_rewards" not in called
        mock_ctx.logger.info.assert_not_called()

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_concurrent_checkpoint_then_reached_with_rewards_is_sent(
        self, use_v2: bool
    ) -> None:
        """After a concurrent checkpoint is re-read, a reached checkpoint with rewards is still sent."""
        result, called, mock_ctx = self._run(
            next_ts=1150,
            available_rewards=1,
            synced_ts=1150,
            use_v2=use_v2,
            ts_checkpoints=(1000, 1050),
        )
        assert result is True
        assert called.count("ts_checkpoint") == 2
        assert called[-1] == "available_rewards"
        mock_ctx.logger.info.assert_not_called()

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_rebaseline_with_rewards_is_sent_without_reading_rewards(
        self, use_v2: bool
    ) -> None:
        """A real rebaseline is sent after one re-read, without reading availableRewards."""
        result, called, mock_ctx = self._run(
            next_ts=1060, available_rewards=1, synced_ts=1050, use_v2=use_v2
        )
        assert result is True
        assert called.count("ts_checkpoint") == 2
        assert "available_rewards" not in called
        mock_ctx.logger.info.assert_not_called()

    @pytest.mark.parametrize("use_v2", [True, False])
    def test_ts_checkpoint_read_once_without_rebaseline_signal(
        self, use_v2: bool
    ) -> None:
        """Without a rebaseline signal, tsCheckpoint is not re-read."""
        _, called, _ = self._run(next_ts=1100, available_rewards=1, use_v2=use_v2)
        assert called.count("ts_checkpoint") == 1
