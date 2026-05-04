# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for chatui_abci behaviours."""

from typing import Any, Generator
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.chatui_abci.behaviours import ChatuiLoadBehaviour
from packages.valory.skills.chatui_abci.models import (
    ChatuiConfig,
    ChatuiParams,
    SharedState,
)


def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """No-op generator for mocking yield from calls."""
    if False:
        yield  # pragma: no cover


class TestChatuiLoadBehaviour:
    """Tests for ChatuiLoadBehaviour."""

    def test_params_property(self) -> None:
        """Params returns context.params cast to ChatuiParams."""
        behaviour = object.__new__(ChatuiLoadBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_params = MagicMock(spec=ChatuiParams)
        mock_context.params = mock_params
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ):
            assert behaviour.params is mock_params

    def test_shared_state_property(self) -> None:
        """shared_state returns context.state cast to SharedState."""
        behaviour = object.__new__(ChatuiLoadBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_state = MagicMock(spec=SharedState)
        mock_context.state = mock_state
        with patch.object(
            type(behaviour),
            "context",
            new_callable=PropertyMock,
            return_value=mock_context,
        ):
            assert behaviour.shared_state is mock_state


class TestAsyncAct:
    """Tests for ChatuiLoadBehaviour.async_act."""

    def test_async_act_happy_path(self) -> None:
        """Drives the full async_act generator to completion when config is set."""
        behaviour = object.__new__(ChatuiLoadBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_context.agent_address = "agent_0"

        mock_shared_state = MagicMock(spec=SharedState)
        mock_chatui_config = MagicMock(spec=ChatuiConfig)
        mock_shared_state.chatui_config = mock_chatui_config

        mock_set_done = MagicMock()

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
                type(behaviour),
                "shared_state",
                new_callable=PropertyMock,
                return_value=mock_shared_state,
            ),
            patch.object(behaviour, "send_a2a_transaction", _noop_gen),
            patch.object(behaviour, "wait_until_round_end", _noop_gen),
            patch.object(behaviour, "set_done", mock_set_done),
        ):
            gen = behaviour.async_act()
            with pytest.raises(StopIteration):
                next(gen)

            mock_context.logger.info.assert_called_once_with(
                f"Loaded chat UI parameters: {mock_chatui_config}"
            )
            mock_set_done.assert_called_once()

    def test_async_act_config_is_none_raises(self) -> None:
        """async_act propagates ValueError raised by chatui_config."""
        behaviour = object.__new__(ChatuiLoadBehaviour)  # type: ignore[type-abstract]
        mock_context = MagicMock()
        mock_context.agent_address = "agent_0"

        class _RaisingSharedState:
            @property
            def chatui_config(self) -> ChatuiConfig:
                raise ValueError("The chat UI config has not been set!")

        mock_shared_state = _RaisingSharedState()

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
                type(behaviour),
                "shared_state",
                new_callable=PropertyMock,
                return_value=mock_shared_state,
            ),
        ):
            gen = behaviour.async_act()
            with pytest.raises(
                ValueError, match="The chat UI config has not been set!"
            ):
                next(gen)
