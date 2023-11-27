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

"""This module contains the helper functions for the kelly strategy."""


def wei_to_native(wei: int) -> float:
    """Convert WEI to native token."""
    return wei / 10**18


def get_max_bet_amount(a: int, x: int, y: int, f: float) -> tuple[int, str]:
    """Get max bet amount based on available shares."""
    if x**2 * f**2 + 2 * x * y * f**2 + y**2 * f**2 == 0:
        error = (
            "Could not recalculate. "
            "Either bankroll is 0 or pool token amount is distributed such as "
            "x**2*f**2 + 2*x*y*f**2 + y**2*f**2 == 0:\n"
            f"Available tokens: {a}\n"
            f"Pool token amounts: {x}, {y}\n"
            f"Fee, fee fraction f: {1-f}, {f}"
        )
        return 0, error

    pre_root = -2 * x**2 + a * x - 2 * x * y
    sqrt = (
        4 * x**4
        + 8 * x**3 * y
        + a**2 * x**2
        + 4 * x**2 * y**2
        + 2 * a**2 * x * y
        + a**2 * y**2
    )
    numerator = y * (pre_root + sqrt**0.5 + a * y)
    denominator = f * (x**2 + 2 * x * y + y**2)
    new_bet_amount = numerator / denominator
    return int(new_bet_amount), ""


def calculate_kelly_bet_amount(  # pylint: disable=too-many-arguments
    x: int, y: int, p: float, c: float, b: int, f: float
) -> int:
    """Calculate the Kelly bet amount."""
    if b == 0:
        return 0
    numerator = (
        -4 * x**2 * y
        + b * y**2 * p * c * f
        + 2 * b * x * y * p * c * f
        + b * x**2 * p * c * f
        - 2 * b * y**2 * f
        - 2 * b * x * y * f
        + (
            (
                4 * x**2 * y
                - b * y**2 * p * c * f
                - 2 * b * x * y * p * c * f
                - b * x**2 * p * c * f
                + 2 * b * y**2 * f
                + 2 * b * x * y * f
            )
            ** 2
            - (
                4
                * (x**2 * f - y**2 * f)
                * (
                    -4 * b * x * y**2 * p * c
                    - 4 * b * x**2 * y * p * c
                    + 4 * b * x * y**2
                )
            )
        )
        ** (1 / 2)
    )
    denominator = 2 * (x**2 * f - y**2 * f)
    kelly_bet_amount = numerator / denominator
    return int(kelly_bet_amount)


def get_bet_amount_kelly(  # pylint: disable=too-many-arguments
    bet_kelly_fraction: float,
    bankroll: int,
    win_probability: float,
    confidence: float,
    selected_type_tokens_in_pool: int,
    other_tokens_in_pool: int,
    bet_fee: int,
) -> tuple[int, list[str], list[str]]:
    """Calculate the Kelly bet amount."""
    # keep `floor_balance` xDAI in the bankroll
    floor_balance = 500000000000000000
    bankroll_adj = bankroll - floor_balance
    bankroll_adj_xdai = wei_to_native(bankroll_adj)
    info = [f"Adjusted bankroll: {bankroll_adj_xdai} xDAI."]
    error = []
    if bankroll_adj <= 0:
        error.append(
            f"Bankroll ({bankroll_adj}) is less than the floor balance ({floor_balance})."
        )
        error.append("Set bet amount to 0.")
        error.append("Top up safe with DAI or wait for redeeming.")
        return 0, info, error

    fee_fraction = 1 - wei_to_native(bet_fee)
    info.append(f"Fee fraction: {fee_fraction}")
    kelly_bet_amount = calculate_kelly_bet_amount(
        selected_type_tokens_in_pool,
        other_tokens_in_pool,
        win_probability,
        confidence,
        bankroll_adj,
        fee_fraction,
    )
    if kelly_bet_amount < 0:
        info.append(
            f"Invalid value for kelly bet amount: {kelly_bet_amount}\nSet bet amount to 0."
        )
        return 0, info, error

    info.append(f"Kelly bet amount: {wei_to_native(kelly_bet_amount)} xDAI")
    info.append(f"Bet kelly fraction: {bet_kelly_fraction}")
    adj_kelly_bet_amount = int(kelly_bet_amount * bet_kelly_fraction)
    info.append(
        f"Adjusted Kelly bet amount: {wei_to_native(adj_kelly_bet_amount)} xDAI"
    )
    return adj_kelly_bet_amount, info, error
