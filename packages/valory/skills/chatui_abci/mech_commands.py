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


def _named_address(
    value: Any, message: str, last_shown: Optional[str]
) -> Optional[str]:
    """The address, when the user's message names it or it is the last mech shown."""
    if not isinstance(value, str):
        return None
    address = value.strip().lower()
    if address in addresses_in(message) or address == last_shown:
        return address
    return None


def _listed_address(value: Any, last_list: Sequence[str]) -> Optional[str]:
    """The address at a 1-based position of the last list shown."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 1 <= value <= len(last_list):
        return None
    return last_list[value - 1]


def resolve_intent(
    reply: Any, message: str, last_shown: Optional[str], last_list: Sequence[str]
) -> Tuple[MechIntent, Optional[str]]:
    """The mech intent the model returned and the one mech it refers to, checked against the chat.

    :param reply: the `mech_intent` of the model's reply, decoded from JSON.
    :param message: the user's message.
    :param last_shown: the address of the last report shown, if any.
    :param last_list: the addresses of the last numbered list shown, in order.
    :return: the intent, `NONE` for any reply that is not a known intent, and
        the mech, or `None` unless every reference given names the same mech.

    An address counts only when the message names it or it is the last mech
    shown, and a position only when it is on the last list, so the mech is
    always one the user or the chat has put in front of the model.
    """
    if not isinstance(reply, dict):
        return MechIntent.NONE, None
    try:
        intent = MechIntent(reply.get("intent"))
    except (ValueError, TypeError):
        return MechIntent.NONE, None
    named: Set[Optional[str]] = set()
    if reply.get("address") is not None:
        named.add(_named_address(reply["address"], message, last_shown))
    if reply.get("position") is not None:
        named.add(_listed_address(reply["position"], last_list))
    return intent, named.pop() if len(named) == 1 else None
