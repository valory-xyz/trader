#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the tests for the calc_sell_amount_in_collateral function."""

import pytest
from packages.valory.skills.decision_maker_abci.utils.calc_sell_amount import calc_sell_amount_in_collateral

@pytest.mark.parametrize(
    "shares_to_sell_amount, market_shares_amounts, selling_outcome_index, market_fee, max_iterations, expected_result",
    [
        (1000000000000000000, [5365087150877052863, 9133122840696030310], 0, 0.01, 100, 607458876914429081),
    ],
)
def test_calc_sell_amount(shares_to_sell_amount, market_shares_amounts, selling_outcome_index, market_fee, max_iterations, expected_result):
    """This test uses the real values using presagio's interface"""
    assert calc_sell_amount_in_collateral(shares_to_sell_amount, market_shares_amounts, selling_outcome_index, market_fee, max_iterations) == expected_result