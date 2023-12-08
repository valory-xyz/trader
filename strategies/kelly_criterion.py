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

"""This module contains the kelly criterion strategy."""

from typing import Dict, Any, List, Union

REQUIRED_FIELDS = frozenset(
    {
        # the fraction of the calculated kelly bet amount to use for placing the bet
        "bet_kelly_fraction",
        "bankroll",
        "win_probability",
        "confidence",
        "selected_type_tokens_in_pool",
        "other_tokens_in_pool",
        "bet_fee",
        "floor_balance",
    }
)
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


def calculate_kelly_bet_amount(
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
    if denominator == 0:
        return 0
    kelly_bet_amount = numerator / denominator
    return int(kelly_bet_amount)


def wei_to_native(wei: int) -> float:
    """Convert WEI to native token."""
    return wei / 10**18


def get_bet_amount_kelly(  # pylint: disable=too-many-arguments
    bet_kelly_fraction: float,
    bankroll: int,
    win_probability: float,
    confidence: float,
    selected_type_tokens_in_pool: int,
    other_tokens_in_pool: int,
    bet_fee: int,
    floor_balance: int,
    max_bet: int = DEFAULT_MAX_BET,
) -> Dict[str, Union[int, List[str]]]:
    """Calculate the Kelly bet amount."""
    # keep `floor_balance` xDAI in the bankroll
    bankroll_adj = bankroll - floor_balance
    bankroll_adj = min(bankroll_adj, max_bet)
    bankroll_adj_xdai = wei_to_native(bankroll_adj)
    info = [f"Adjusted bankroll: {bankroll_adj_xdai} xDAI."]
    error = []
    if bankroll_adj <= 0:
        error.append(
            f"Bankroll ({bankroll_adj}) is less than the floor balance ({floor_balance})."
        )
        error.append("Set bet amount to 0.")
        error.append("Top up safe with DAI or wait for redeeming.")
        return {"bet_amount": 0, "info": info, "error": error}

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
        return {"bet_amount": 0, "info": info, "error": error}

    info.append(f"Kelly bet amount: {wei_to_native(kelly_bet_amount)} xDAI")
    info.append(f"Bet kelly fraction: {bet_kelly_fraction}")
    adj_kelly_bet_amount = int(kelly_bet_amount * bet_kelly_fraction)
    info.append(
        f"Adjusted Kelly bet amount: {wei_to_native(adj_kelly_bet_amount)} xDAI"
    )
    return {"bet_amount": adj_kelly_bet_amount, "info": info, "error": error}


def run(*_args, **kwargs) -> Dict[str, Union[int, List[str]]]:
    """Run the strategy."""
    missing = check_missing_fields(kwargs)
    if len(missing) > 0:
        return {"error": [f"Required kwargs {missing} were not provided."]}

    kwargs = remove_irrelevant_fields(kwargs)
    return get_bet_amount_kelly(**kwargs)
