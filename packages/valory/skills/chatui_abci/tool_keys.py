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

"""The keys the decision maker's tool policy is indexed by.

A key is ``<identity>::<tool>``. The identity is ``VALORY_LABEL`` for the mechs
in ``valid_mechs`` and the lowercase address of any other mech. A key without an
identity is a bare tool name, as written before keys carried one and in the
benchmarking mode.
"""

from typing import Iterable, Optional, Set, Tuple

MECH_TOOL_SEPARATOR = "::"
VALORY_LABEL = "valory"
ADDRESS_HEX_LENGTH = 40


def _is_address(value: str) -> bool:
    """Check whether the given value is a ``0x``-prefixed 20-byte hex address."""
    if len(value) != len("0x") + ADDRESS_HEX_LENGTH or value[:2].lower() != "0x":
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def tool_key(identity: Optional[str], tool: str) -> str:
    """Build the key of a tool served under the given identity.

    :param identity: ``VALORY_LABEL`` or a mech address; ``None`` for no mech.
    :param tool: the tool's name.
    :return: the key.
    """
    if not identity:
        return tool
    return f"{identity.lower()}{MECH_TOOL_SEPARATOR}{tool}"


def split_tool_key(key: str) -> Tuple[Optional[str], str]:
    """Split a key into its identity and tool name.

    :param key: a key as built by :func:`tool_key`.
    :return: the lowercase identity, or ``None`` for a bare tool name, and the tool.
    """
    identity, sep, tool = key.partition(MECH_TOOL_SEPARATOR)
    if sep and (identity.lower() == VALORY_LABEL or _is_address(identity)):
        return identity.lower(), tool
    return None, key


def describe_tool_key(key: str) -> str:
    """Render a key for humans, e.g., ``prediction-online @ valory``."""
    identity, tool = split_tool_key(key)
    if identity is None:
        return tool
    return f"{tool} @ {identity}"


def tool_names(keys: Iterable[str]) -> Set[str]:
    """Get the distinct tool names behind the given keys."""
    return {split_tool_key(key)[1] for key in keys}
