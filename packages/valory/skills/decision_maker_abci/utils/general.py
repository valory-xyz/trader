# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""This module contains general utils for the decision maker skill."""

import json
import logging
import re
from contextlib import contextmanager
from typing import Any, Generator, Union


@contextmanager
def suppress_logs(level: int = logging.CRITICAL) -> Generator:
    """Context manager to suppress the logs for a specific code block."""
    previous_level = logging.root.manager.disable
    logging.disable(level)
    try:
        yield
    finally:
        logging.disable(previous_level)


# Deeper than any manifest or response a mech publishes.
MAX_JSON_DEPTH = 100

# A string left unclosed runs to the end of the text, as the parser reads it.
_JSON_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?', re.DOTALL)
_JSON_BRACKETS = re.compile(r"[\[\]{}]")


def json_depth_exceeds(
    text: Union[str, bytes], max_depth: int = MAX_JSON_DEPTH
) -> bool:
    """Whether arrays and objects in `text` nest deeper than `max_depth`.

    Brackets inside JSON strings are not counted. Bytes are read as latin-1,
    which maps every byte to one character and keeps ASCII brackets in place.

    :param text: the JSON document.
    :param max_depth: the deepest nesting allowed.
    :return: True when some bracket opens deeper than `max_depth`.
    """
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("latin-1")
    depth = 0
    for bracket in _JSON_BRACKETS.finditer(_JSON_STRING.sub("", text)):
        if bracket.group() in "[{":
            depth += 1
            if depth > max_depth:
                return True
        else:
            depth -= 1
    return False


def loads_bounded(text: Union[str, bytes]) -> Any:
    """`json.loads`, refusing documents nested deeper than `MAX_JSON_DEPTH`.

    :param text: the JSON document.
    :return: the parsed value.
    :raises ValueError: when the document nests deeper than `MAX_JSON_DEPTH`.
    """
    if json_depth_exceeds(text):
        raise ValueError(f"JSON nested deeper than {MAX_JSON_DEPTH} levels")
    return json.loads(text)
