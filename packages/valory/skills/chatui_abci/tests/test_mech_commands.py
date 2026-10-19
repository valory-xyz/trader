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
    resolve_intent,
)
from packages.valory.skills.chatui_abci.prompts import MechIntent

MECH = "0x" + "b0" * 20
CHECKSUMMED = "0x" + "B0" * 20
OTHER = "0x" + "e0" * 20


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
            {"intent": "approve", "address": MECH, "last_shown": False},
            f"use {MECH}",
            None,
            MECH,
        ),
        ({"intent": "pin", "address": "", "last_shown": True}, "pin it", MECH, MECH),
    ],
    ids=[
        "checksummed_address_in_message",
        "padded_address_in_message",
        "last_shown",
        "last_shown_and_address_agree",
        "unused_last_shown_false",
        "empty_address_beside_last_shown",
    ],
)
def test_a_reference_the_chat_can_place_resolves(
    reply: Any, message: str, last_shown: Optional[str], expected: str
) -> None:
    """An address from the message or the mech whose report was just shown."""
    intent, mech = resolve_intent(reply, message, last_shown)
    assert intent is MechIntent(reply["intent"])
    assert mech == expected


@pytest.mark.parametrize(
    "reply, message, last_shown",
    [
        ({"intent": "approve"}, "let's use it", MECH),
        ({"intent": "approve", "address": None, "last_shown": None}, "yes", MECH),
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
        ({"intent": "ask", "position": 1}, "the first one", MECH),
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
        "position_is_not_a_reference",
    ],
)
def test_a_reference_the_chat_cannot_place_resolves_to_no_mech(
    reply: Any, message: str, last_shown: Optional[str]
) -> None:
    """The intent stands, but no mech is taken that the user or the chat did not show."""
    intent, mech = resolve_intent(reply, message, last_shown)
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
        {"intent": "list"},
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
        "list_intent",
    ],
)
def test_a_reply_without_a_known_intent_is_none(reply: Any) -> None:
    """Nothing in the mech flow runs on a reply that is not one of the intents."""
    intent, mech = resolve_intent(reply, f"use {MECH}", MECH)
    assert intent is MechIntent.NONE
    assert mech is None
