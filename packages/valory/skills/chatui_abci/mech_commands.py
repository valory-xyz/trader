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

"""Read what a chat message asks of a mech: the typed accept line, or the model's mech intent checked against the chat."""

import re
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Set, Tuple

from packages.valory.skills.chatui_abci.prompts import MechIntent

ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")
TRAILING_PUNCTUATION = ".,;:!?"
_ADDRESS = r"(?P<address>0x[0-9a-f]{40})"
ACCEPT_PATTERN = re.compile(rf"i accept (?P<price>.+) per request for {_ADDRESS}")
REMOVE_PATTERN = re.compile(rf"remove {_ADDRESS}")
UNDO_MESSAGE = "undo"


@dataclass(frozen=True)
class Accept:
    """A typed accept: the lowercase address and the normalised price text."""

    address: str
    price_text: str


def normalise(text: str) -> str:
    """Lowercase, with runs of whitespace collapsed to one space and the ends stripped."""
    return " ".join(text.lower().split())


def addresses_in(text: str) -> List[str]:
    """The distinct mech addresses named in the text, lowercase, in order."""
    return list(dict.fromkeys(match.lower() for match in ADDRESS_PATTERN.findall(text)))


def parse_accept(text: str) -> Optional[Accept]:
    """The accept the whole message spells, ignoring case, spacing and trailing punctuation, or `None`."""
    message = normalise(text).rstrip(TRAILING_PUNCTUATION).rstrip()
    accept = ACCEPT_PATTERN.fullmatch(message)
    if accept is None:
        return None
    return Accept(accept["address"], accept["price"].strip())


def parse_remove(text: str) -> Optional[str]:
    """The address a whole-message `remove <address>` names, or `None`."""
    message = normalise(text).rstrip(TRAILING_PUNCTUATION).rstrip()
    remove = REMOVE_PATTERN.fullmatch(message)
    return remove["address"] if remove is not None else None


def parse_undo(text: str) -> bool:
    """Whether the whole message is a typed `undo`."""
    return normalise(text).rstrip(TRAILING_PUNCTUATION).rstrip() == UNDO_MESSAGE


def _named_address(value: Any, message: str) -> Optional[str]:
    """The address, when the user's message names it."""
    if not isinstance(value, str):
        return None
    address = value.strip().lower()
    return address if address in addresses_in(message) else None


def _listed_address(value: Any, last_list: Sequence[str]) -> Optional[str]:
    """The address at a 1-based position of the last list shown."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= len(last_list):
        return None
    return last_list[value - 1]


def resolve_intent(
    reply: Any,
    message: str,
    last_shown: Optional[str],
    last_list: Sequence[str],
    last_removed: Optional[str] = None,
) -> Tuple[MechIntent, Optional[str]]:
    """The mech intent the model returned and the one mech it refers to, checked against the chat.

    :param reply: the `mech_intent` of the model's reply, decoded from JSON.
    :param message: the user's message.
    :param last_shown: the address of the last report shown, if any.
    :param last_list: the addresses of the last numbered list shown, in order.
    :param last_removed: the address the reply before this message removed, if
        any; an undo refers only to it, and an address must agree with it.
    :return: the intent, `NONE` for any reply that is not a known intent, and
        the mech, or `None` unless every reference given names the same mech.

    """
    if not isinstance(reply, dict):
        return MechIntent.NONE, None
    try:
        intent = MechIntent(reply.get("intent"))
    except (ValueError, TypeError):
        return MechIntent.NONE, None
    named: Set[Optional[str]] = set()
    if reply.get("address") not in (None, ""):
        named.add(_named_address(reply["address"], message))
    if intent is MechIntent.UNDO:
        named.add(last_removed)
    else:
        if reply.get("last_shown") is True:
            named.add(last_shown)
        if reply.get("position") not in (None, 0, False):
            named.add(_listed_address(reply["position"], last_list))
    return intent, named.pop() if len(named) == 1 else None
