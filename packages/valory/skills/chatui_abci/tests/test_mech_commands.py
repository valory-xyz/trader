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

"""Tests for reading the typed mech commands."""

from typing import List, Optional

import pytest

from packages.valory.skills.chatui_abci.mech_commands import (
    Command,
    Verb,
    addresses_in,
    normalise,
    parse_command,
)

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
    assert parse_command(text) == Command(Verb.ACCEPT, MECH, "0.01 xdai")


@pytest.mark.parametrize(
    "text, verb",
    [
        (f"remove {MECH}", Verb.REMOVE),
        (f"Remove {CHECKSUMMED}.", Verb.REMOVE),
        (f"PIN   {MECH}", Verb.PIN),
        (f"pin {CHECKSUMMED}!", Verb.PIN),
        (f"unpin {MECH}", Verb.UNPIN),
        (f" Unpin {CHECKSUMMED} ; ", Verb.UNPIN),
    ],
)
def test_remove_pin_and_unpin_read_the_lowercase_address(text: str, verb: Verb) -> None:
    """The address is compared lowercase, so a checksummed one names the same mech."""
    assert parse_command(text) == Command(verb, MECH)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "yes",
        "I accept",
        f"{MECH}",
        f"please remove {MECH}",
        f"remove {MECH} now",
        f"remove {MECH} {OTHER}",
        f"remove {MECH[:-1]}",
        f"remove {MECH}0",
        f"pin {MECH[2:]}",
        f"delete {MECH}",
        f"accept 0.01 xDAI per request for {MECH}",
        f"I accept per request for {MECH}",
        f"I accept 0.01 xDAI for {MECH}",
        f"I accept 0.01 xDAI per request for {MECH} and {OTHER}",
        f"I accept 0.01 xDAI per request for {MECH}, thanks",
    ],
)
def test_anything_else_is_not_a_command(text: str) -> None:
    """Only the whole message spelling a command counts; nothing is guessed."""
    assert parse_command(text) is None


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
