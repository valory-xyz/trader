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

"""Tests for the policy key format."""

from typing import Optional, Tuple

import pytest

from packages.valory.skills.chatui_abci.tool_keys import (
    VALORY_LABEL,
    describe_tool_key,
    split_tool_key,
    tool_key,
    tool_names,
)

MECH = "0x" + "ab" * 20


@pytest.mark.parametrize(
    "identity, tool, expected",
    [
        (MECH, "prediction-online", f"{MECH}::prediction-online"),
        (MECH.upper(), "prediction-online", f"{MECH}::prediction-online"),
        (VALORY_LABEL, "prediction-online", "valory::prediction-online"),
        (None, "prediction-online", "prediction-online"),
        ("", "prediction-online", "prediction-online"),
    ],
)
def test_tool_key(identity: Optional[str], tool: str, expected: str) -> None:
    """The key joins the lowercase identity and the tool; none yields the bare tool."""
    assert tool_key(identity, tool) == expected


@pytest.mark.parametrize(
    "key, expected",
    [
        (f"{MECH}::prediction-online", (MECH, "prediction-online")),
        (f"{MECH.upper()}::prediction-online", (MECH, "prediction-online")),
        (f"{MECH}::odd::tool", (MECH, "odd::tool")),
        ("valory::prediction-online", (VALORY_LABEL, "prediction-online")),
        ("Valory::prediction-online", (VALORY_LABEL, "prediction-online")),
        ("prediction-online", (None, "prediction-online")),
        ("www.valory.xyz::tool", (None, "www.valory.xyz::tool")),
        ("odd::tool", (None, "odd::tool")),
        ("0x1234::tool", (None, "0x1234::tool")),
        ("0x" + "g" * 40 + "::tool", (None, "0x" + "g" * 40 + "::tool")),
        ("", (None, "")),
    ],
)
def test_split_tool_key(key: str, expected: Tuple[Optional[str], str]) -> None:
    """Only the Valory label or a 20-byte hex address counts as an identity."""
    assert split_tool_key(key) == expected


@pytest.mark.parametrize("identity", [MECH, VALORY_LABEL, None])
def test_tool_key_round_trips(identity: Optional[str]) -> None:
    """Splitting a built key gives back its parts."""
    assert split_tool_key(tool_key(identity, "a::b")) == (identity, "a::b")


def test_describe_tool_key() -> None:
    """Keys render as ``tool @ identity`` and bare tools as themselves."""
    assert describe_tool_key(tool_key(MECH, "tool")) == f"tool @ {MECH}"
    assert describe_tool_key(tool_key(VALORY_LABEL, "tool")) == "tool @ valory"
    assert describe_tool_key("tool") == "tool"


def test_tool_names_collapse_identities_and_keep_bare_names_whole() -> None:
    """Names are distinct across identities; a bare name with ``::`` stays whole."""
    keys = {
        tool_key(VALORY_LABEL, "prediction-online"),
        tool_key(MECH, "prediction-online"),
        tool_key(MECH, "prediction-offline"),
        "odd::tool",
    }
    assert tool_names(keys) == {"prediction-online", "prediction-offline", "odd::tool"}


def test_tool_names_of_nothing_is_nothing() -> None:
    """An empty universe stays empty."""
    assert tool_names([]) == set()
