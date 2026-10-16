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

"""Read the typed mech commands; the chat acts on a mech only through these."""

import enum
import re
from dataclasses import dataclass
from typing import List, Optional

ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")
TRAILING_PUNCTUATION = ".,;:!?"
_ADDRESS = r"(?P<address>0x[0-9a-f]{40})"
ACCEPT_PATTERN = re.compile(rf"i accept (?P<price>.+) per request for {_ADDRESS}")
VERB_PATTERN = re.compile(rf"(?P<verb>remove|pin|unpin) {_ADDRESS}")
LIST_PATTERN = re.compile(r"list approved(?: mechs)?")


class Verb(enum.Enum):
    """What a command does to the mech it names."""

    ACCEPT = "accept"
    REMOVE = "remove"
    PIN = "pin"
    UNPIN = "unpin"
    LIST = "list"


@dataclass(frozen=True)
class Command:
    """A typed command: the verb, the lowercase address (empty for a list) and, for an accept, the normalised price text."""

    verb: Verb
    address: str
    price_text: Optional[str] = None


def normalise(text: str) -> str:
    """Lowercase, with runs of whitespace collapsed to one space and the ends stripped."""
    return " ".join(text.lower().split())


def addresses_in(text: str) -> List[str]:
    """The distinct mech addresses named in the text, lowercase, in order."""
    return list(dict.fromkeys(match.lower() for match in ADDRESS_PATTERN.findall(text)))


def parse_command(text: str) -> Optional[Command]:
    """The command the whole message spells, ignoring case, spacing and trailing punctuation, or `None`."""
    message = normalise(text).rstrip(TRAILING_PUNCTUATION).rstrip()
    accept = ACCEPT_PATTERN.fullmatch(message)
    if accept is not None:
        return Command(Verb.ACCEPT, accept["address"], accept["price"].strip())
    if LIST_PATTERN.fullmatch(message) is not None:
        return Command(Verb.LIST, "")
    verb = VERB_PATTERN.fullmatch(message)
    if verb is not None:
        return Command(Verb(verb["verb"]), verb["address"])
    return None
