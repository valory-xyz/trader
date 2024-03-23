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

"""This module contains the market moving bet strategy."""

import typing as t
import numpy as np
from functools import reduce
from web3.types import Wei


REQUIRED_FIELDS = frozenset(
    {
        "amounts",
        "target_p_yes",
    }
)
OPTIONAL_FIELDS = frozenset(
    {
        "max_iters",
        "verbose",
        "market_fee",
    }
)
ALL_FIELDS = REQUIRED_FIELDS.union(OPTIONAL_FIELDS)

OutcomeIndex = t.NewType("OutcomeIndex", int)


class MovingBet(t.TypedDict):
    bet_amount: Wei | None
    bet_outcome_index: OutcomeIndex | None
    error: t.List[str] | None


def get_market_moving_bet(
    amounts: tuple[Wei, Wei],
    target_p_yes: float,
    max_iters: int = 100,
    verbose: bool = False,
    market_fee: Wei = 0,
) -> MovingBet:
    """
    For FPMMs, the probability is equal to the marginal price.
    We assume that index 0 is for Yes (True) and index 1 is for No (False) outcome.

    Implements a binary search to determine the bet that will move the market's
    `p_yes` to that of the target.

    Consider a binary fixed-product market containing `x` and `y` tokens.
    A trader wishes to aquire `x` tokens by betting an amount `d0`.

    The calculation to determine the number of `x` tokens he acquires, denoted
    by `dx`, is:

    a_x * a_y = fixed_product
    na_x = a_x + d0
    na_y = a_y + d0
    na_x * na_y = new_product
    (na_x - dx) * na_y = fixed_product
    (na_x * na_y) - (dx * na_y) = fixed_product
    new_product - fixed_product = dx * na_y
    dx = (new_product - fixed_product) / na_y
    """
    if len(amounts) != 2:
        return MovingBet(
            bet_amount=None,
            bet_outcome_index=None,
            error=["Only binary markets are supported."],
        )

    # We assume that index 0 holds YES tokens and index 1 holds NO tokens.
    # However, p_yes is as follows, because the higher the probability of YES is, the less tokens are availalbe, and so more costly it is.
    current_p_yes = 1.0 - amounts[0] / sum(amounts)
    if verbose:
        print(f"{current_p_yes=:.2f}")

    fixed_product = reduce(lambda x, y: x * y, amounts, 1)
    bet_outcome_index = OutcomeIndex(0 if target_p_yes > current_p_yes else 1)

    min_bet_amount = 0
    max_bet_amount = 100 * sum(amounts)  # TODO: Set a better upper bound.

    # Binary search for the optimal bet amount
    for _ in range(max_iters):
        bet_amount = (min_bet_amount + max_bet_amount) // 2
        bet_amount_ = bet_amount * (10**18 - market_fee) / 10**18

        # Initial new amounts are old amounts + equal new amounts for each outcome
        amounts_diff = bet_amount_
        new_amounts = [amounts[i] + amounts_diff for i in range(len(amounts))]

        # Now give away tokens at `bet_outcome_index` to restore invariant
        new_product = reduce(lambda x, y: x * y, new_amounts, 1.0)
        dx = (new_product - fixed_product) / new_amounts[1 - bet_outcome_index]

        new_amounts[bet_outcome_index] -= dx
        # Check that the invariant is restored
        assert np.isclose(
            reduce(lambda x, y: x * y, new_amounts, 1.0), float(fixed_product)
        )
        new_p_yes = new_amounts[1] / sum(new_amounts)
        if verbose:
            print(
                f"{target_p_yes=:.2f}, {new_p_yes=:.2f}, {bet_outcome_index=}, {bet_amount=}"
            )
        if abs(target_p_yes - new_p_yes) < 0.01:
            break
        elif new_p_yes > target_p_yes:
            if bet_outcome_index == 0:
                max_bet_amount = bet_amount
            else:
                min_bet_amount = bet_amount
        else:
            if bet_outcome_index == 0:
                min_bet_amount = bet_amount
            else:
                max_bet_amount = bet_amount

    return MovingBet(
        bet_amount=Wei(bet_amount), bet_outcome_index=bet_outcome_index, error=None
    )


def check_missing_fields(kwargs: dict[str, t.Any]) -> list[str]:
    """Check for missing fields and return them, if any."""
    missing = []
    for field in REQUIRED_FIELDS:
        if kwargs.get(field, None) is None:
            missing.append(field)
    return missing


def remove_irrelevant_fields(kwargs: dict[str, t.Any]) -> dict[str, t.Any]:
    """Remove the irrelevant fields from the given kwargs."""
    return {key: value for key, value in kwargs.items() if key in ALL_FIELDS}


def run(*_args, **kwargs) -> MovingBet:
    """Run the strategy."""
    missing = check_missing_fields(kwargs)
    if len(missing) > 0:
        return MovingBet(
            bet_amount=None,
            bet_outcome_index=None,
            error=[f"Required kwargs {missing} were not provided."],
        )
    kwargs = remove_irrelevant_fields(kwargs)
    return get_market_moving_bet(**kwargs)
