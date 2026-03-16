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
from typing import Any, Generator
from unittest.mock import MagicMock, PropertyMock, mock_open, patch

import pytest

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

    def test_is_checkpoint_reached_true(self) -> None:
        """Is_checkpoint_reached is True when next_checkpoint <= synced_timestamp."""
        b = self._make()
        b._next_checkpoint = 100
        mock_rs = MagicMock()
        mock_rs.last_round_transition_timestamp.timestamp.return_value = 200.0
        with patch.object(
            type(b),
            "round_sequence",
            new_callable=PropertyMock,
            return_value=mock_rs,
        ):
            assert b.is_checkpoint_reached is True

    def test_is_checkpoint_reached_false(self) -> None:
        """Is_checkpoint_reached is False when next_checkpoint > synced_timestamp."""
        b = self._make()
        b._next_checkpoint = 300
        mock_rs = MagicMock()
        mock_rs.last_round_transition_timestamp.timestamp.return_value = 200.0
        with patch.object(
            type(b),
            "round_sequence",
            new_callable=PropertyMock,
            return_value=mock_rs,
        ):
            assert b.is_checkpoint_reached is False

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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "sleep", _noop_gen):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "sleep", _noop_gen):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "get_contract_api_response", _return_gen(response_msg)):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "get_contract_api_response", _return_gen(response_msg)):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "get_contract_api_response", _return_gen(response_msg)):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "contract_interact", _return_gen(True)):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "contract_interact", _return_gen(True)):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "_staking_contract_interact", _return_gen(True)):
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

    def test_get_liveness_ratio_v2(self) -> None:
        """_get_liveness_ratio uses mech_activity_checker when use_v2 is True."""
        b = self._make()
        mock_ctx = MagicMock()
        mock_ctx.params.mech_activity_checker_contract = "0xNonNull"  # != NULL_ADDRESS

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            b, "_mech_activity_checker_contract_interact", _return_gen(True)
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "_staking_contract_interact", _return_gen(True)):
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
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "_staking_contract_interact", _return_gen(True)):
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
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "_staking_contract_interact", _return_gen(True)):
            gen = b._get_agent_ids()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


# ---------------------------------------------------------------------------
# CallCheckpointBehaviour
# ---------------------------------------------------------------------------


class TestCallCheckpointBehaviourInit:
    """Tests for CallCheckpointBehaviour.__init__."""

    def test_init(self) -> None:
        """__init__ sets default attributes."""
        mock_params = MagicMock()
        mock_params.store_path = Path("/tmp")  # nosec B108
        with patch.object(
            StakingInteractBaseBehaviour, "__init__", return_value=None
        ), patch.object(
            CallCheckpointBehaviour,
            "params",
            new_callable=PropertyMock,
            return_value=mock_params,
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
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch("builtins.open", side_effect=FileNotFoundError):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()

    def test_permission_error(self) -> None:
        """Test that PermissionError returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch("builtins.open", side_effect=PermissionError):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()

    def test_os_error(self) -> None:
        """Test that OSError returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch("builtins.open", side_effect=OSError):
            result = b.read_stored_timestamp()
        assert result is None
        mock_ctx.logger.error.assert_called_once()

    def test_parse_error(self) -> None:
        """Non-integer content returns None and logs error."""
        b = self._make()
        mock_ctx = MagicMock()
        m = mock_open(read_data="not_a_number\n")
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch("builtins.open", m):
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
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch("builtins.open", m):
            result = b.store_timestamp()
        assert result == 0
        mock_ctx.logger.error.assert_called_once()

    def test_open_error(self) -> None:
        """Error opening file returns 0 and logs error."""
        b = self._make()
        b._checkpoint_ts = 1700000000
        mock_ctx = MagicMock()
        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch("builtins.open", side_effect=PermissionError):
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ), patch.object(
            b, "contract_interact", _return_gen(True)
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(b, "wait_for_condition_with_sleep", _noop_gen), patch(
            "packages.valory.skills.staking_abci.behaviours.hash_payload_to_hex",
            return_value="0xresult",
        ) as mock_hash:
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

        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ), patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=MagicMock()
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
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
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ), patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "read_stored_timestamp", return_value=50
        ), patch.object(
            b, "store_timestamp", return_value=10
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
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ), patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "store_timestamp", return_value=10
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
        with patch.object(
            type(b),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync,
        ), patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "store_timestamp", return_value=0
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

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            type(b),
            "behaviour_id",
            new_callable=PropertyMock,
            return_value="test",
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "check_new_epoch", _return_gen(False)
        ), patch.object(
            b, "send_a2a_transaction", _noop_gen
        ), patch.object(
            b, "wait_until_round_end", _noop_gen
        ), patch.object(
            b, "set_done", mock_set_done
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)
        mock_set_done.assert_called_once()

    def test_staked_checkpoint_reached(self) -> None:
        """Staked service with checkpoint reached prepares safe tx."""
        b = self._make()
        b._service_staking_state = StakingState.STAKED
        b._next_checkpoint = 100
        mock_ctx = MagicMock()
        mock_ctx.agent_address = "agent_0"
        mock_ctx.params.on_chain_service_id = 1
        mock_rs = MagicMock()
        mock_rs.last_round_transition_timestamp.timestamp.return_value = 200.0

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            type(b),
            "behaviour_id",
            new_callable=PropertyMock,
            return_value="test",
        ), patch.object(
            type(b),
            "round_sequence",
            new_callable=PropertyMock,
            return_value=mock_rs,
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "_prepare_safe_tx", _return_gen("0xtxhex")
        ), patch.object(
            b, "check_new_epoch", _return_gen(True)
        ), patch.object(
            b, "send_a2a_transaction", _noop_gen
        ), patch.object(
            b, "wait_until_round_end", _noop_gen
        ), patch.object(
            b, "set_done", MagicMock()
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)

    def test_staked_checkpoint_not_reached(self) -> None:
        """Staked service without checkpoint reached skips safe tx."""
        b = self._make()
        b._service_staking_state = StakingState.STAKED
        b._next_checkpoint = 300
        mock_ctx = MagicMock()
        mock_ctx.agent_address = "agent_0"
        mock_ctx.params.on_chain_service_id = 1
        mock_rs = MagicMock()
        mock_rs.last_round_transition_timestamp.timestamp.return_value = 200.0

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            type(b),
            "behaviour_id",
            new_callable=PropertyMock,
            return_value="test",
        ), patch.object(
            type(b),
            "round_sequence",
            new_callable=PropertyMock,
            return_value=mock_rs,
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "check_new_epoch", _return_gen(False)
        ), patch.object(
            b, "send_a2a_transaction", _noop_gen
        ), patch.object(
            b, "wait_until_round_end", _noop_gen
        ), patch.object(
            b, "set_done", MagicMock()
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)

    def test_evicted(self) -> None:
        """Evicted service logs critical message."""
        b = self._make()
        b._service_staking_state = StakingState.EVICTED
        mock_ctx = MagicMock()
        mock_ctx.agent_address = "agent_0"
        mock_ctx.params.on_chain_service_id = 1

        with patch.object(
            type(b), "context", new_callable=PropertyMock, return_value=mock_ctx
        ), patch.object(
            type(b),
            "behaviour_id",
            new_callable=PropertyMock,
            return_value="test",
        ), patch.object(
            b, "wait_for_condition_with_sleep", _noop_gen
        ), patch.object(
            b, "check_new_epoch", _return_gen(False)
        ), patch.object(
            b, "send_a2a_transaction", _noop_gen
        ), patch.object(
            b, "wait_until_round_end", _noop_gen
        ), patch.object(
            b, "set_done", MagicMock()
        ):
            gen = b.async_act()
            with pytest.raises(StopIteration):
                next(gen)
        mock_ctx.logger.critical.assert_called_once_with("Service has been evicted!")
