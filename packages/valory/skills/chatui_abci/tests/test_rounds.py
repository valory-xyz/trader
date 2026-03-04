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

"""Tests for the rounds module of the chatui_abci skill."""

import json
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.chatui_abci.rounds import (
    ChatuiAbciApp,
    ChatuiLoadRound,
    Event,
    FinishedChatuiLoadRound,
    SynchronizedData,
)


class TestSynchronizedData:
    """Tests for the SynchronizedData class."""

    def test_available_mech_tools(self) -> None:
        """Test available_mech_tools returns a set of tool names."""
        tools = ["prediction-online", "prediction-offline"]
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"available_mech_tools": [json.dumps(tools)]})
        )
        assert data.available_mech_tools == set(tools)

    def test_available_mech_tools_empty(self) -> None:
        """Test available_mech_tools returns an empty set when no tools."""
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"available_mech_tools": [json.dumps([])]})
        )
        assert data.available_mech_tools == set()

    def test_available_mech_tools_single(self) -> None:
        """Test available_mech_tools with a single tool."""
        data = SynchronizedData(
            db=AbciAppDB(
                setup_data={"available_mech_tools": [json.dumps(["tool-a"])]}
            )
        )
        assert data.available_mech_tools == {"tool-a"}


class TestEvent:
    """Tests for the Event enum."""

    def test_event_values(self) -> None:
        """Test that all event values are correct."""
        assert Event.DONE.value == "done"
        assert Event.NONE.value == "none"
        assert Event.ROUND_TIMEOUT.value == "round_timeout"
        assert Event.NO_MAJORITY.value == "no_majority"

    def test_event_members(self) -> None:
        """Test that all expected members exist."""
        assert len(Event) == 4


class TestChatuiLoadRound:
    """Tests for the ChatuiLoadRound class."""

    def test_class_attributes(self) -> None:
        """Test that class-level attributes are set correctly."""
        assert ChatuiLoadRound.done_event == Event.DONE
        assert ChatuiLoadRound.negative_event == Event.DONE
        assert ChatuiLoadRound.none_event == Event.NONE
        assert ChatuiLoadRound.no_majority_event == Event.NO_MAJORITY

    def test_payload_class(self) -> None:
        """Test that the payload class is ChatuiPayload."""
        from packages.valory.skills.chatui_abci.payloads import ChatuiPayload

        assert ChatuiLoadRound.payload_class is ChatuiPayload

    def test_synchronized_data_class(self) -> None:
        """Test that the synchronized data class is SynchronizedData."""
        assert ChatuiLoadRound.synchronized_data_class is SynchronizedData


class TestFinishedChatuiLoadRound:
    """Tests for the FinishedChatuiLoadRound class."""

    def test_initialization(self) -> None:
        """Test that FinishedChatuiLoadRound can be instantiated."""
        round_ = FinishedChatuiLoadRound(
            synchronized_data=MagicMock(), context=MagicMock()
        )
        assert isinstance(round_, FinishedChatuiLoadRound)


@pytest.fixture
def abci_app() -> ChatuiAbciApp:
    """Create a ChatuiAbciApp instance for testing."""
    return ChatuiAbciApp(
        synchronized_data=MagicMock(), logger=MagicMock(), context=MagicMock()
    )


def test_abci_app_initialization(abci_app: ChatuiAbciApp) -> None:
    """Test ChatuiAbciApp class attributes and configuration."""
    assert abci_app.initial_round_cls is ChatuiLoadRound
    assert abci_app.final_states == {FinishedChatuiLoadRound}
    assert abci_app.event_to_timeout == {Event.ROUND_TIMEOUT: 30.0}
    assert abci_app.db_pre_conditions == {ChatuiLoadRound: set()}
    assert abci_app.db_post_conditions == {FinishedChatuiLoadRound: set()}


def test_abci_app_transition_function(abci_app: ChatuiAbciApp) -> None:
    """Test ChatuiAbciApp transition function is properly defined."""
    tf = abci_app.transition_function
    assert ChatuiLoadRound in tf
    assert FinishedChatuiLoadRound in tf
    assert tf[ChatuiLoadRound][Event.DONE] == FinishedChatuiLoadRound
    assert tf[ChatuiLoadRound][Event.NONE] == ChatuiLoadRound
    assert tf[ChatuiLoadRound][Event.ROUND_TIMEOUT] == ChatuiLoadRound
    assert tf[ChatuiLoadRound][Event.NO_MAJORITY] == ChatuiLoadRound
    assert tf[FinishedChatuiLoadRound] == {}
