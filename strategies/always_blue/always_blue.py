# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the always blue strategy."""

from typing import Dict, Any, List, Union

REQUIRED_FIELDS = frozenset()
OPTIONAL_FIELDS = frozenset({"max_bet"})
ALL_FIELDS = REQUIRED_FIELDS.union(OPTIONAL_FIELDS)
DEFAULT_MAX_BET = 8e17


def check_missing_fields(kwargs: Dict[str, Any]) -> List[str]:
    """Check for missing fields and return them, if any."""
    missing = []
    for field in REQUIRED_FIELDS:
        if kwargs.get(field, None) is None:
            missing.append(field)
    return missing


def remove_irrelevant_fields(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Remove the irrelevant fields from the given kwargs."""
    return {key: value for key, value in kwargs.items() if key in ALL_FIELDS}


def wei_to_native(wei: int) -> float:
    """Convert WEI to native token."""
    return wei / 10**18


def get_always_blue(  # pylint: disable=too-many-arguments
) -> Dict[str, Union[int, List[str]]]:
    """ALWAYS BLUE."""
    return {"bet_amount": 0, "info": "ALWAYS BLUE!", "error": "IT WAS NOT BLUE!"}


def run(*_args, **kwargs) -> Dict[str, Union[int, List[str]]]:
    """Run the strategy."""
    missing = check_missing_fields(kwargs)
    if len(missing) > 0:
        return {"error": [f"Required kwargs {missing} were not provided."]}

    kwargs = remove_irrelevant_fields(kwargs)
    return get_always_blue(**kwargs)
