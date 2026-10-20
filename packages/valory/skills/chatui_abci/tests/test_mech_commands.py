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

"""Tests for reading the typed accept line and checking the model's mech intent."""

from typing import Any, List, Optional

import pytest

from packages.valory.skills.chatui_abci.mech_commands import (
    Accept,
    addresses_in,
    normalise,
    parse_accept,
    parse_undo,
    resolve_intent,
)
from packages.valory.skills.chatui_abci.prompts import MechIntent

MECH = "0x" + "b0" * 20
CHECKSUMMED = "0x" + "B0" * 20
OTHER = "0x" + "e0" * 20
LISTED = "0x" + "a0" * 20
LAST_LIST = [LISTED, OTHER]


@pytest.mark.parametrize(
    "text",
    [
        f"I accept 0.01 xDAI per request for {MECH}",
        f"i accept 0.01 xdai per request for {CHECKSUMMED}",
        f"  I  ACCEPT 0.01   xDAI per\trequest\nfor {MECH}  ",
        f"I accept 0.01 xDAI per request for {MECH}.",
        f"I accept 0.01 xDAI per request for {MECH} !?",
    ],
)
def test_an_accept_reads_the_address_and_the_normalised_price(text: str) -> None:
    """Case, spacing, checksum and trailing punctuation do not matter."""
    assert parse_accept(text) == Accept(MECH, "0.01 xdai")


@pytest.mark.parametrize(
    "text",
    [
        "",
        "yes",
        "I accept",
        f"{MECH}",
        f"remove {MECH}",
        f"pin {MECH}",
        "list approved",
        f"accept 0.01 xDAI per request for {MECH}",
        f"I accept per request for {MECH}",
        f"I accept 0.01 xDAI for {MECH}",
        f"I accept 0.01 xDAI per request for {MECH[:-1]}",
        f"I accept 0.01 xDAI per request for {MECH}0",
        f"I accept 0.01 xDAI per request for {MECH} and {OTHER}",
        f"I accept 0.01 xDAI per request for {MECH}, thanks",
    ],
)
def test_anything_else_is_not_an_accept(text: str) -> None:
    """Only the whole message spelling the accept line counts; nothing is guessed."""
    assert parse_accept(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        (f"compare {CHECKSUMMED} with {OTHER} and {MECH}", [MECH, OTHER]),
        (f"what is {OTHER}?", [OTHER]),
        ("no address here 0x1234", []),
        ("", []),
    ],
)
def test_addresses_in_are_distinct_lowercase_and_in_order(
    text: str, expected: List[str]
) -> None:
    """The same mech named twice in different case counts once."""
    assert addresses_in(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [("  0.01   xDAI ", "0.01 xdai"), ("0.01\txDAI", "0.01 xdai"), ("", "")],
)
def test_normalise(text: str, expected: Optional[str]) -> None:
    """Lowercase with single spaces, so two renderings of one price compare equal."""
    assert normalise(text) == expected


@pytest.mark.parametrize(
    "reply, message, last_shown, expected",
    [
        ({"intent": "ask", "address": CHECKSUMMED}, f"about {MECH}?", None, MECH),
        ({"intent": "ask", "address": f" {MECH} "}, f"about {MECH}?", None, MECH),
        ({"intent": "approve", "last_shown": True}, "let's use it", MECH, MECH),
        (
            {"intent": "approve", "address": MECH, "last_shown": True},
            f"use {MECH}",
            MECH,
            MECH,
        ),
        (
            {"intent": "approve", "address": MECH, "last_shown": False, "position": 0},
            f"use {MECH}",
            None,
            MECH,
        ),
        (
            {"intent": "ask", "address": "", "position": 1},
            "the first one",
            None,
            LISTED,
        ),
        ({"intent": "pin", "position": 2}, "pin the second one", None, OTHER),
        ({"intent": "ask", "position": 1}, "the first one", MECH, LISTED),
        (
            {"intent": "ask", "address": LISTED, "position": 1},
            f"the first one, {LISTED}",
            None,
            LISTED,
        ),
    ],
    ids=[
        "checksummed_address_in_message",
        "padded_address_in_message",
        "last_shown",
        "last_shown_and_address_agree",
        "unused_fields_filled_with_false_and_zero",
        "empty_address_beside_a_position",
        "position",
        "position_over_last_shown",
        "address_and_position_agree",
    ],
)
def test_a_reference_the_chat_can_place_resolves(
    reply: Any, message: str, last_shown: Optional[str], expected: str
) -> None:
    """An address from the message or the last report, or a position on the last list."""
    intent, mech = resolve_intent(reply, message, last_shown, LAST_LIST)
    assert intent is MechIntent(reply["intent"])
    assert mech == expected


@pytest.mark.parametrize(
    "reply, message, last_shown",
    [
        ({"intent": "approve"}, "let's use it", MECH),
        ({"intent": "approve", "address": None, "position": None}, "yes", MECH),
        ({"intent": "approve", "last_shown": True}, "let's use it", None),
        ({"intent": "approve", "address": MECH}, "let's use it", MECH),
        ({"intent": "approve", "address": OTHER}, f"use {MECH}", MECH),
        ({"intent": "approve", "last_shown": "yes"}, "yes", MECH),
        ({"intent": "approve", "last_shown": False}, "yes", MECH),
        (
            {"intent": "approve", "address": MECH, "last_shown": True},
            f"use {MECH}",
            OTHER,
        ),
        ({"intent": "approve", "address": 5}, "use it", MECH),
        ({"intent": "ask", "position": 0}, "the zeroth one", None),
        ({"intent": "ask", "position": 3}, "the third one", None),
        ({"intent": "ask", "position": -1}, "the last one", None),
        ({"intent": "ask", "position": True}, "the first one", None),
        ({"intent": "ask", "position": 1.0}, "the first one", None),
        ({"intent": "ask", "position": "1"}, "the first one", None),
        (
            {"intent": "ask", "address": MECH, "position": 1},
            f"the first one, {MECH}",
            None,
        ),
        ({"intent": "ask", "address": OTHER, "position": 1}, "the first one", None),
    ],
    ids=[
        "no_reference",
        "null_references",
        "last_shown_with_nothing_shown",
        "shown_address_not_in_message",
        "address_not_in_message",
        "last_shown_not_a_bool",
        "last_shown_false",
        "last_shown_and_address_disagree",
        "address_not_a_string",
        "position_zero",
        "position_past_the_end",
        "position_negative",
        "position_bool",
        "position_float",
        "position_string",
        "address_and_position_disagree",
        "one_reference_unplaceable",
    ],
)
def test_a_reference_the_chat_cannot_place_resolves_to_no_mech(
    reply: Any, message: str, last_shown: Optional[str]
) -> None:
    """The intent stands, but no mech is taken that the user or the chat did not show."""
    intent, mech = resolve_intent(reply, message, last_shown, LAST_LIST)
    assert intent is MechIntent(reply["intent"])
    assert mech is None


@pytest.mark.parametrize(
    "reply",
    [
        None,
        "approve",
        [{"intent": "approve", "address": MECH}],
        {},
        {"address": MECH},
        {"intent": None, "address": MECH},
        {"intent": "APPROVE", "address": MECH},
        {"intent": "delete", "address": MECH},
        {"intent": ["approve"], "address": MECH},
    ],
    ids=[
        "null",
        "string",
        "list",
        "empty",
        "missing_intent",
        "null_intent",
        "wrong_case",
        "unknown_intent",
        "unhashable_intent",
    ],
)
def test_a_reply_without_a_known_intent_is_none(reply: Any) -> None:
    """Nothing in the mech flow runs on a reply that is not one of the intents."""
    intent, mech = resolve_intent(reply, f"use {MECH}", MECH, LAST_LIST)
    assert intent is MechIntent.NONE
    assert mech is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("undo", True),
        ("  Undo. ", True),
        ("UNDO!", True),
        ("undo that", False),
        ("please undo", False),
        ("undone", False),
        ("", False),
    ],
)
def test_parse_undo_reads_only_a_whole_message_undo(text: str, expected: bool) -> None:
    """Only a message that is the word alone is a typed undo."""
    assert parse_undo(text) is expected


@pytest.mark.parametrize(
    "reply, message, expected",
    [
        ({"intent": "undo"}, "put it back", MECH),
        ({"intent": "undo", "address": MECH}, f"put back {MECH}", MECH),
        ({"intent": "undo", "address": OTHER}, f"put back {OTHER}", None),
        ({"intent": "undo", "position": 2}, "put back the second one", None),
        (
            {"intent": "undo", "address": MECH, "position": 2},
            f"put back the second one, {MECH}",
            None,
        ),
    ],
    ids=[
        "no_reference",
        "the_removed_mech_by_address",
        "another_mech_by_address",
        "another_mech_by_position",
        "references_disagree",
    ],
)
def test_an_undo_refers_to_the_mech_just_removed(
    reply: Any, message: str, expected: Optional[str]
) -> None:
    """An undo takes the removed mech, and any other reference must agree with it."""
    intent, mech = resolve_intent(reply, message, None, LAST_LIST, MECH)
    assert intent is MechIntent.UNDO
    assert mech == expected


def test_an_undo_with_nothing_removed_has_no_mech() -> None:
    """Without a removal, an undo has no mech, even one the message names."""
    reply = {"intent": "undo", "address": MECH}
    assert resolve_intent(reply, f"put back {MECH}", None, LAST_LIST) == (
        MechIntent.UNDO,
        None,
    )
