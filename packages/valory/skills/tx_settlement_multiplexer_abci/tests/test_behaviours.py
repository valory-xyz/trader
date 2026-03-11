# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""Tests for tx_settlement_multiplexer_abci behaviours."""

from typing import Any, Generator
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import RedeemingProgress
from packages.valory.skills.tx_settlement_multiplexer_abci.behaviours import (
    PostTxSettlementBehaviour,
    PostTxSettlementFullBehaviour,
    PreTxSettlementBehaviour,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.models import (
    TxSettlementMultiplexerParams,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    PostTxSettlementRound,
    PreTxSettlementRound,
    TxSettlementMultiplexerAbciApp,
)

# ---------------------------------------------------------------------------
# Generator helpers
# ---------------------------------------------------------------------------


def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """No-op generator for mocking yield from calls."""
    if False:
        yield  # pragma: no cover


def _return_gen(value: Any):  # type: ignore
    """Create a factory returning a generator that immediately returns a value."""

    def gen(*args: Any, **kwargs: Any) -> Generator:
        """Generator returning value."""
        return value
        yield  # pragma: no cover  # unreachable, makes it a generator

    return gen


# ---------------------------------------------------------------------------
# PostTxSettlementFullBehaviour (the AbstractRoundBehaviour composite)
# ---------------------------------------------------------------------------


class TestPostTxSettlementFullBehaviour:
    """Tests for PostTxSettlementFullBehaviour attributes."""

    def test_initial_behaviour_cls(self) -> None:
        """Initial_behaviour_cls is PostTxSettlementBehaviour."""
        assert (
            PostTxSettlementFullBehaviour.initial_behaviour_cls
            is PostTxSettlementBehaviour
        )

    def test_abci_app_cls(self) -> None:
        """Abci_app_cls is TxSettlementMultiplexerAbciApp."""
        assert (
            PostTxSettlementFullBehaviour.abci_app_cls is TxSettlementMultiplexerAbciApp  # type: ignore[misc]
        )

    def test_behaviours_set(self) -> None:
        """Behaviours set contains PreTxSettlementBehaviour and PostTxSettlementBehaviour."""
        assert PostTxSettlementFullBehaviour.behaviours == {
            PreTxSettlementBehaviour,
            PostTxSettlementBehaviour,
        }

    def test_inherits_abstract_round_behaviour(self) -> None:
        """Test that PostTxSettlementFullBehaviour extends AbstractRoundBehaviour."""
        assert issubclass(PostTxSettlementFullBehaviour, AbstractRoundBehaviour)


# ---------------------------------------------------------------------------
# PreTxSettlementBehaviour
# ---------------------------------------------------------------------------


class TestPreTxSettlementBehaviourAttributes:
    """Tests for PreTxSettlementBehaviour class attributes and properties."""

    def test_matching_round(self) -> None:
        """Matching_round is PreTxSettlementRound."""
        assert PreTxSettlementBehaviour.matching_round is PreTxSettlementRound

    def test_params_property(self) -> None:
        """Params returns context.params cast to TxSettlementMultiplexerParams."""
        behaviour = object.__new__(PreTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_params = MagicMock(spec=TxSettlementMultiplexerParams)
        mock_context.params = mock_params
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ):
            assert behaviour.params is mock_params


class TestGetBalance:
    """Tests for PreTxSettlementBehaviour._get_balance."""

    VALID_ADDR = "0x0000000000000000000000000000000000000001"

    def _make_behaviour(self) -> PreTxSettlementBehaviour:
        """Create a PreTxSettlementBehaviour bypassing __init__."""
        return object.__new__(PreTxSettlementBehaviour)  # type: ignore[type-abstract]

    def test_get_balance_success(self) -> None:
        """Returns the integer balance when response is valid."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.mech_chain_id = "gnosis"

        mock_response = MagicMock()
        mock_response.state.body = {"get_balance_result": "5000"}

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "get_ledger_api_response",
            _return_gen(mock_response),
        ):
            gen = behaviour._get_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value == 5000

    def test_get_balance_zero(self) -> None:
        """Returns 0 when balance is '0'."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.mech_chain_id = "gnosis"

        mock_response = MagicMock()
        mock_response.state.body = {"get_balance_result": "0"}

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "get_ledger_api_response",
            _return_gen(mock_response),
        ):
            gen = behaviour._get_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value == 0

    def test_get_balance_key_error(self) -> None:
        """Returns None when response body does not contain key."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.mech_chain_id = "gnosis"

        mock_response = MagicMock()
        mock_response.state.body = {}

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "get_ledger_api_response",
            _return_gen(mock_response),
        ):
            gen = behaviour._get_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is None
            mock_context.logger.error.assert_called_once()

    def test_get_balance_value_error(self) -> None:
        """Returns None when balance cannot be converted to int."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.mech_chain_id = "gnosis"

        mock_response = MagicMock()
        mock_response.state.body = {"get_balance_result": "not_a_number"}

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "get_ledger_api_response",
            _return_gen(mock_response),
        ):
            gen = behaviour._get_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is None
            mock_context.logger.error.assert_called_once()

    def test_get_balance_type_error(self) -> None:
        """Returns None when response.state.body is not subscriptable."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.mech_chain_id = "gnosis"

        mock_response = MagicMock()
        # Make .state.body raise TypeError on subscript
        mock_response.state.body.__getitem__ = MagicMock(side_effect=TypeError)

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "get_ledger_api_response",
            _return_gen(mock_response),
        ):
            gen = behaviour._get_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is None
            mock_context.logger.error.assert_called_once()

    def test_get_balance_aea_enforce_error(self) -> None:
        """Returns None when AEAEnforceError is raised from body access."""
        from aea.exceptions import AEAEnforceError

        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.mech_chain_id = "gnosis"

        mock_response = MagicMock()
        mock_response.state.body.__getitem__ = MagicMock(
            side_effect=AEAEnforceError("test")
        )

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "get_ledger_api_response",
            _return_gen(mock_response),
        ):
            gen = behaviour._get_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is None
            mock_context.logger.error.assert_called_once()


class TestCheckBalance:
    """Tests for PreTxSettlementBehaviour._check_balance."""

    VALID_ADDR = "0x0000000000000000000000000000000000000001"

    def _make_behaviour(self) -> PreTxSettlementBehaviour:
        """Create a PreTxSettlementBehaviour bypassing __init__."""
        return object.__new__(PreTxSettlementBehaviour)  # type: ignore[type-abstract]

    def test_balance_above_threshold(self) -> None:
        """Returns False (no refill) when balance >= threshold."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.agent_balance_threshold = 1000
        mock_context.params.mech_chain_id = "gnosis"

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "_get_balance",
            _return_gen(5000),
        ):
            gen = behaviour._check_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_balance_equal_threshold(self) -> None:
        """Returns False (no refill) when balance == threshold."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.agent_balance_threshold = 1000
        mock_context.params.mech_chain_id = "gnosis"

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "_get_balance",
            _return_gen(1000),
        ):
            gen = behaviour._check_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_balance_below_threshold(self) -> None:
        """Returns True (refill required) when balance < threshold."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.agent_balance_threshold = 5000
        mock_context.params.mech_chain_id = "gnosis"

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "_get_balance",
            _return_gen(100),
        ):
            gen = behaviour._check_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True
            mock_context.logger.warning.assert_called_once()

    def test_retries_on_none_balance(self) -> None:
        """Retries _get_balance when it returns None, then succeeds."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.params.agent_balance_threshold = 1000
        mock_context.params.mech_chain_id = "gnosis"

        # Return None first, then a valid balance
        call_count = 0

        def _get_balance_with_retry(*args: Any, **kwargs: Any) -> Generator:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            return 5000  # type: ignore[return-value]
            yield  # pragma: no cover

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            behaviour,
            "_get_balance",
            _get_balance_with_retry,
        ):
            gen = behaviour._check_balance(self.VALID_ADDR)
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False
            assert call_count == 2


class TestRefillRequired:
    """Tests for PreTxSettlementBehaviour._refill_required."""

    def _make_behaviour(self) -> PreTxSettlementBehaviour:
        """Create a PreTxSettlementBehaviour bypassing __init__."""
        return object.__new__(PreTxSettlementBehaviour)  # type: ignore[type-abstract]

    def test_no_participants(self) -> None:
        """Returns False when there are no participants."""
        behaviour = self._make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.all_participants = frozenset()

        with patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ):
            gen = behaviour._refill_required()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_all_agents_have_sufficient_balance(self) -> None:
        """Returns False when all agents have enough balance."""
        behaviour = self._make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.all_participants = frozenset(
            {
                "0x0000000000000000000000000000000000000001",
                "0x0000000000000000000000000000000000000002",
            }
        )

        with patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ), patch.object(
            behaviour,
            "_check_balance",
            _return_gen(False),
        ):
            gen = behaviour._refill_required()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is False

    def test_one_agent_needs_refill(self) -> None:
        """Returns True when at least one agent needs refill."""
        behaviour = self._make_behaviour()
        mock_sync_data = MagicMock()
        agents = [
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000002",
        ]
        mock_sync_data.all_participants = frozenset(agents)

        # First agent is fine, second needs refill
        call_count = 0

        def _check_balance_varying(*args: Any, **kwargs: Any) -> Generator:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False  # type: ignore[return-value]
            return True  # type: ignore[return-value]
            yield  # pragma: no cover

        with patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ), patch.object(
            behaviour,
            "_check_balance",
            _check_balance_varying,
        ):
            gen = behaviour._refill_required()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True

    def test_all_agents_need_refill(self) -> None:
        """Returns True when all agents need refill."""
        behaviour = self._make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.all_participants = frozenset(
            {
                "0x0000000000000000000000000000000000000001",
            }
        )

        with patch.object(
            type(behaviour),
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_sync_data,
        ), patch.object(
            behaviour,
            "_check_balance",
            _return_gen(True),
        ):
            gen = behaviour._refill_required()
            with pytest.raises(StopIteration) as exc_info:
                next(gen)
            assert exc_info.value.value is True


class TestPreTxSettlementAsyncAct:
    """Tests for PreTxSettlementBehaviour.async_act."""

    def _make_behaviour(self) -> PreTxSettlementBehaviour:
        """Create a PreTxSettlementBehaviour bypassing __init__."""
        return object.__new__(PreTxSettlementBehaviour)  # type: ignore[type-abstract]

    def test_async_act_no_refill(self) -> None:
        """When no refill is required, sends True payload and completes."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.agent_address = "agent_0"
        mock_context.params.refill_check_interval = 30
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
            return_value="test_pre_tx",
        ), patch.object(
            behaviour, "_refill_required", _return_gen(False)
        ), patch.object(
            behaviour, "send_a2a_transaction", _noop_gen
        ), patch.object(
            behaviour, "wait_until_round_end", _noop_gen
        ), patch.object(
            behaviour, "set_done", mock_set_done
        ), patch.object(
            behaviour, "sleep", _noop_gen
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)
            mock_set_done.assert_called_once()

    def test_async_act_refill_required(self) -> None:
        """When refill is required, sleeps then sends False payload and completes."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_context.agent_address = "agent_0"
        mock_context.params.refill_check_interval = 30
        mock_set_done = MagicMock()
        sleep_called = False

        def _mock_sleep(*args: Any, **kwargs: Any) -> Generator:
            nonlocal sleep_called
            sleep_called = True
            return None
            yield  # pragma: no cover

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "behaviour_id",
            new_callable=PropertyMock,
            return_value="test_pre_tx",
        ), patch.object(
            behaviour, "_refill_required", _return_gen(True)
        ), patch.object(
            behaviour, "send_a2a_transaction", _noop_gen
        ), patch.object(
            behaviour, "wait_until_round_end", _noop_gen
        ), patch.object(
            behaviour, "set_done", mock_set_done
        ), patch.object(
            behaviour, "sleep", _mock_sleep
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)
            mock_set_done.assert_called_once()
            assert sleep_called


# ---------------------------------------------------------------------------
# PostTxSettlementBehaviour
# ---------------------------------------------------------------------------


class TestPostTxSettlementBehaviourAttributes:
    """Tests for PostTxSettlementBehaviour class attributes and properties."""

    def test_matching_round(self) -> None:
        """Matching_round is PostTxSettlementRound."""
        assert PostTxSettlementBehaviour.matching_round is PostTxSettlementRound

    def test_synchronized_data_property(self) -> None:
        """Synchronized_data wraps super().synchronized_data.db in SynchronizedData."""
        from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
            SynchronizedData,
        )

        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_db = MagicMock()
        mock_super_sync_data = MagicMock()
        mock_super_sync_data.db = mock_db

        with patch.object(
            BaseBehaviour,
            "synchronized_data",
            new_callable=PropertyMock,
            return_value=mock_super_sync_data,
        ):
            result = behaviour.synchronized_data
            assert isinstance(result, SynchronizedData)


class TestRedeemingProgressProperty:
    """Tests for PostTxSettlementBehaviour.redeeming_progress property."""

    def test_getter(self) -> None:
        """Getter returns shared_state.redeeming_progress."""
        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_progress = RedeemingProgress()
        mock_shared_state = MagicMock()
        mock_shared_state.redeeming_progress = mock_progress

        with patch.object(
            type(behaviour),
            "shared_state",
            new_callable=PropertyMock,
            return_value=mock_shared_state,
        ):
            assert behaviour.redeeming_progress is mock_progress

    def test_setter(self) -> None:
        """Setter assigns to shared_state.redeeming_progress."""
        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_shared_state = MagicMock()
        new_progress = RedeemingProgress()

        with patch.object(
            type(behaviour),
            "shared_state",
            new_callable=PropertyMock,
            return_value=mock_shared_state,
        ):
            behaviour.redeeming_progress = new_progress
            assert mock_shared_state.redeeming_progress is new_progress


class TestOnRedeemRoundTxSettled:
    """Tests for PostTxSettlementBehaviour._on_redeem_round_tx_settled."""

    def test_resets_progress_and_preserves_claimed_ids(self) -> None:
        """Resets redeeming progress and preserves claimed + claiming ids."""
        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()

        # Set up redeeming progress with existing claimed and claiming ids
        progress = RedeemingProgress()
        progress.claimed_condition_ids = ["cond_1", "cond_2"]
        progress.claiming_condition_ids = ["cond_3", "cond_4"]

        mock_shared_state = MagicMock()
        mock_shared_state.redeeming_progress = progress

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "shared_state",
            new_callable=PropertyMock,
            return_value=mock_shared_state,
        ):
            behaviour._on_redeem_round_tx_settled()

            # Verify the new progress has the combined claimed ids
            new_progress = mock_shared_state.redeeming_progress
            assert isinstance(new_progress, RedeemingProgress)
            assert new_progress.claimed_condition_ids == [
                "cond_1",
                "cond_2",
                "cond_3",
                "cond_4",
            ]
            # claiming_condition_ids should be reset (empty)
            assert new_progress.claiming_condition_ids == []
            mock_context.logger.info.assert_called()

    def test_empty_ids(self) -> None:
        """Works correctly when both claimed and claiming ids are empty."""
        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()

        progress = RedeemingProgress()
        progress.claimed_condition_ids = []
        progress.claiming_condition_ids = []

        mock_shared_state = MagicMock()
        mock_shared_state.redeeming_progress = progress

        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ), patch.object(
            type(behaviour),
            "shared_state",
            new_callable=PropertyMock,
            return_value=mock_shared_state,
        ):
            behaviour._on_redeem_round_tx_settled()

            new_progress = mock_shared_state.redeeming_progress
            assert isinstance(new_progress, RedeemingProgress)
            assert new_progress.claimed_condition_ids == []
            assert new_progress.claiming_condition_ids == []


class TestOnTxSettled:
    """Tests for PostTxSettlementBehaviour._on_tx_settled."""

    def _make_behaviour(self) -> PostTxSettlementBehaviour:
        """Create a PostTxSettlementBehaviour bypassing __init__."""
        return object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]

    def test_known_handler_called(self) -> None:
        """When handler exists for tx_submitter, it is called."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_sync_data = MagicMock()
        mock_sync_data.tx_submitter = "redeem_round"

        mock_handler = MagicMock()

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
            behaviour,
            "_on_redeem_round_tx_settled",
            mock_handler,
        ):
            behaviour._on_tx_settled()
            mock_handler.assert_called_once()

    def test_unknown_handler_logs_info(self) -> None:
        """When no handler exists for tx_submitter, logs info."""
        behaviour = self._make_behaviour()
        mock_context = MagicMock()
        mock_sync_data = MagicMock()
        mock_sync_data.tx_submitter = "unknown_submitter"

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
        ):
            behaviour._on_tx_settled()
            mock_context.logger.info.assert_called_once_with(
                "No post tx settlement handler exists for unknown_submitter txs."
            )


class TestPostTxSettlementAsyncAct:
    """Tests for PostTxSettlementBehaviour.async_act."""

    def test_async_act(self) -> None:
        """Drives the full async_act generator to completion."""
        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_sync_data = MagicMock()
        mock_sync_data.tx_submitter = "some_submitter"
        mock_set_done = MagicMock()
        mock_on_tx_settled = MagicMock()

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
            behaviour, "_on_tx_settled", mock_on_tx_settled
        ), patch.object(
            behaviour, "wait_until_round_end", _noop_gen
        ), patch.object(
            behaviour, "set_done", mock_set_done
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)
            mock_context.logger.info.assert_called()
            mock_on_tx_settled.assert_called_once()
            mock_set_done.assert_called_once()

    def test_async_act_with_redeem_round(self) -> None:
        """Async_act correctly calls the redeem_round handler end-to-end."""
        behaviour = object.__new__(PostTxSettlementBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_sync_data = MagicMock()
        mock_sync_data.tx_submitter = "redeem_round"
        mock_set_done = MagicMock()

        # Set up redeeming progress
        progress = RedeemingProgress()
        progress.claimed_condition_ids = ["id1"]
        progress.claiming_condition_ids = ["id2"]

        mock_shared_state = MagicMock()
        mock_shared_state.redeeming_progress = progress

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
            type(behaviour),
            "shared_state",
            new_callable=PropertyMock,
            return_value=mock_shared_state,
        ), patch.object(
            behaviour, "wait_until_round_end", _noop_gen
        ), patch.object(
            behaviour, "set_done", mock_set_done
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)
            mock_set_done.assert_called_once()
            # Verify the redeeming handler was executed
            new_progress = mock_shared_state.redeeming_progress
            assert isinstance(new_progress, RedeemingProgress)
            assert "id1" in new_progress.claimed_condition_ids
            assert "id2" in new_progress.claimed_condition_ids
