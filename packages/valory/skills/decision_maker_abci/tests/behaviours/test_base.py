# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2023 Valory AG
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

"""This module contains the tests for valory/decision_maker_abci's base behaviour."""

import re
from typing import Tuple

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.tests.conftest import profile_name


settings.load_profile(profile_name)
FRACTION_REMOVAL_PRECISION = 2


@composite
def remove_fraction_args(draw: st.DrawFn) -> Tuple[int, float, int]:
    """A strategy for building the values of the `test_remove_fraction_wei` with the desired constraints."""
    amount = draw(st.integers())
    fraction = draw(st.floats(min_value=0, max_value=1))
    keep_percentage = 1 - fraction
    assert 0 <= keep_percentage <= 1
    expected = int(amount * keep_percentage)
    return amount, fraction, expected


@given(remove_fraction_args())
def test_remove_fraction_wei(strategy: Tuple[int, float, int]) -> None:
    """Test the `remove_fraction_wei` function."""
    amount, fraction, expected = strategy
    assert remove_fraction_wei(amount, fraction) == expected


@given(
    amount=st.integers(),
    fraction=st.floats().filter(lambda x: x < 0 or x > 1),
)
def test_remove_fraction_wei_incorrect_fraction(amount: int, fraction: float) -> None:
    """Test the `remove_fraction_wei` function."""
    with pytest.raises(
        ValueError,
        match=re.escape(f"The given fraction {fraction!r} is not in the range [0, 1]."),
    ):
        remove_fraction_wei(amount, fraction)
