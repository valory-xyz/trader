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
from typing import Any, Dict, Tuple, cast
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.chatui_abci.payloads import ChatuiPayload
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

    def test_available_mech_tools_keeps_the_policy_keys(self) -> None:
        """The property returns the decision maker's keys untouched."""
        mech_a = "0x" + "a" * 40
        keys = [f"{mech_a}::prediction-online", "legacy-tool"]
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"available_mech_tools": [json.dumps(keys)]})
        )
        assert data.available_mech_tools == set(keys)

    def test_available_mech_tools_empty(self) -> None:
        """Test available_mech_tools returns an empty set when no tools."""
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"available_mech_tools": [json.dumps([])]})
        )
        assert data.available_mech_tools == set()

    def test_available_mech_tools_single(self) -> None:
        """Test available_mech_tools with a single tool."""
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"available_mech_tools": [json.dumps(["tool-a"])]})
        )
        assert data.available_mech_tools == {"tool-a"}

    def test_available_valid_mechs_lowercased(self) -> None:
        """Mech addresses are lowercased when read out of synced data."""
        mechs_info = [
            {"address": "0xABC", "relevant_tools": ["t1"]},
            {"address": "0xdef", "relevant_tools": ["t2"]},
        ]
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"mechs_info": [json.dumps(mechs_info)]})
        )
        assert data.available_valid_mechs == {"0xabc", "0xdef"}

    def test_available_valid_mechs_missing_key(self) -> None:
        """Absent mechs_info yields an empty set (early-boot case)."""
        data = SynchronizedData(db=AbciAppDB(setup_data={}))
        assert data.available_valid_mechs == set()

    def test_available_valid_mechs_malformed_json(self) -> None:
        """Malformed db payload yields an empty set rather than raising."""
        data = SynchronizedData(db=AbciAppDB(setup_data={"mechs_info": ["not-json"]}))
        assert data.available_valid_mechs == set()

    @pytest.mark.parametrize("raw", ["5", '{"address": "0xabc"}', "null"])
    def test_mechs_info_that_is_not_a_list_reads_as_none(self, raw: str) -> None:
        """A db payload of the wrong shape yields no mechs rather than raising."""
        data = SynchronizedData(db=AbciAppDB(setup_data={"mechs_info": [raw]}))
        assert data.available_valid_mechs == set()
        assert data.mech_payment_types == {}

    def test_mech_payment_types_by_lowercase_address(self) -> None:
        """Each discovered mech's payment type, lowercase; mechs without one are left out."""
        mechs_info = [
            {"address": "0xABC", "payment_type": "0xBA69"},
            {"address": "0xdef", "payment_type": ""},
            {"address": "0x123"},
            {"payment_type": "0xba69"},
        ]
        data = SynchronizedData(
            db=AbciAppDB(setup_data={"mechs_info": [json.dumps(mechs_info)]})
        )
        assert data.mech_payment_types == {"0xabc": "0xba69"}

    @pytest.mark.parametrize(
        "setup, loaded",
        [
            ({}, False),
            ({"mechs_info": [None]}, False),
            ({"mechs_info": ["not-json"]}, False),
            ({"mechs_info": [json.dumps({"address": "0xabc"})]}, False),
            ({"mechs_info": [json.dumps([])]}, True),
            ({"mechs_info": [json.dumps([{"address": "0xabc"}])]}, True),
        ],
        ids=[
            "missing",
            "none",
            "unparseable",
            "not_a_list",
            "written_empty",
            "written",
        ],
    )
    def test_mechs_info_loaded_only_once_written_this_period(
        self, setup: Dict[str, Any], loaded: bool
    ) -> None:
        """A missing key is a period not discovered yet; an empty list written is a discovery that found none."""
        data = SynchronizedData(db=AbciAppDB(setup_data=setup))
        assert data.mechs_info_loaded is loaded


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
    assert tf[ChatuiLoadRound][Event.FAIL] == ChatuiLoadRound
    assert tf[ChatuiLoadRound][Event.NONE] == ChatuiLoadRound
    assert tf[ChatuiLoadRound][Event.ROUND_TIMEOUT] == ChatuiLoadRound
    assert tf[ChatuiLoadRound][Event.NO_MAJORITY] == ChatuiLoadRound
    assert tf[FinishedChatuiLoadRound] == {}


def test_chatui_load_round_negative_event_distinct_from_done() -> None:
    """A rejected-vote outcome must produce a different event than success.

    If `negative_event` and `done_event` ever collapse to the same value,
    a `vote=False` payload would silently route to the success terminal —
    the round would advance instead of retrying or failing.
    """
    assert ChatuiLoadRound.negative_event != ChatuiLoadRound.done_event
    assert ChatuiLoadRound.negative_event is Event.FAIL


class TestChatuiLoadRoundEndBlock:
    """end_block must publish selected_mechs into synced data on a positive vote.

    Otherwise mech-interact's MechInformationRound reads a stale pin
    written one FSM iteration ago by ToolSelectionRound, which deadlocks
    when the stale value points at offline mechs (pinned_mechs_offline →
    FSM loops back without ever reaching ToolSelectionRound to refresh).
    """

    @staticmethod
    def _build_round(payload: ChatuiPayload) -> ChatuiLoadRound:
        """Build a ChatuiLoadRound seeded with a single payload at threshold."""
        sender = payload.sender
        # AbciAppDB lookups use the raw values (not JSON-encoded) for the
        # participant set; consensus_threshold is read by VotingRound as an int.
        db = AbciAppDB(
            setup_data={
                "all_participants": [[sender]],
                "consensus_threshold": [1],
            }
        )
        sync_data = SynchronizedData(db=db)
        round_ = ChatuiLoadRound(synchronized_data=sync_data, context=MagicMock())
        round_.collection = {sender: payload}
        return round_

    def test_publishes_pin_when_positive_threshold_reached(self) -> None:
        """A vote=True payload carrying a JSON pin must surface in synced data."""
        payload = ChatuiPayload(
            sender="agent-1",
            vote=True,
            selected_mechs=json.dumps(["0xabc", "0xdef"]),
        )
        round_ = self._build_round(payload)

        result = round_.end_block()

        assert result is not None
        new_sync, event = result
        assert event is Event.DONE
        # mech_interact_abci's SynchronizedData.selected_mechs reads this key
        # via db.get("selected_mechs", ...) — see UPGRADING.md.
        raw = new_sync.db.get("selected_mechs", None)
        assert raw is not None
        assert json.loads(raw) == ["0xabc", "0xdef"]

    def test_publishes_approved_mechs_when_positive_threshold_reached(self) -> None:
        """The accepted rates reach the key mech-interact bounds approved mechs by."""
        payload = ChatuiPayload(
            sender="agent-1", vote=True, approved_mechs=json.dumps({"0xabc": 10000})
        )
        new_sync, _ = cast(Tuple[Any, Any], self._build_round(payload).end_block())
        assert json.loads(new_sync.db.get("approved_mechs", None)) == {"0xabc": 10000}
        assert json.loads(new_sync.db.get("selected_mechs", None)) == []

    def test_publishes_empty_approvals_when_payload_unset(self) -> None:
        """Without approvals an explicit empty object is written, so removals take effect."""
        payload = ChatuiPayload(sender="agent-1", vote=True)
        new_sync, _ = cast(Tuple[Any, Any], self._build_round(payload).end_block())
        assert json.loads(new_sync.db.get("approved_mechs", None)) == {}

    def test_publishes_empty_pin_when_payload_unset(self) -> None:
        """A None selected_mechs payload must publish an explicit empty list.

        Empty-string or absent values would let a downstream JSON decode
        fall through to mech-interact's "[]" default, but writing it
        explicitly here keeps each FSM iteration deterministic regardless
        of whether the consumer set a pin.
        """
        payload = ChatuiPayload(
            sender="agent-1",
            vote=True,
            selected_mechs=None,
        )
        round_ = self._build_round(payload)

        result = round_.end_block()

        assert result is not None
        new_sync, event = result
        assert event is Event.DONE
        raw = new_sync.db.get("selected_mechs", None)
        assert raw == "[]"

    def test_negative_vote_does_not_publish_pin(self) -> None:
        """A failing vote must not touch selected_mechs in synced data."""
        payload = ChatuiPayload(
            sender="agent-1",
            vote=False,
            selected_mechs=json.dumps(["0xabc"]),
        )
        round_ = self._build_round(payload)

        result = round_.end_block()

        assert result is not None
        _, event = result
        assert event is Event.FAIL
