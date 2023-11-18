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

"""This module contains the tests for valory/decision_maker_abci's behaviours."""

from packages.valory.skills.decision_maker_abci.tests.conftest import profile_name
from packages.valory.skills.decision_maker_abci.behaviours.base import calculate_kelly_bet_amount

from hypothesis import given, settings
from hypothesis import strategies as st


settings.load_profile(profile_name)


@given(
    x=st.integers(min_value=100, max_value=100000),
    y=st.integers(min_value=100, max_value=100000),
    p=st.floats(min_value=0.6, max_value=1.0),
    c=st.floats(min_value=0.6, max_value=1.0),
    b=st.floats(min_value=0.5, max_value=2.0),
    f=st.floats(min_value=0.98, max_value=0.99),
)
def test_calculate_kelly_bet_amount(
    x: int, y: int, p: float, c: float, b: int, f: float
    ):
    assert calculate_kelly_bet_amount(x, y, p, c, b, f) >= -10