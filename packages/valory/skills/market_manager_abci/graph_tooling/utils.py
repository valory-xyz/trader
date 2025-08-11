# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""Utils for graph interactions."""
import time
from collections import defaultdict
from enum import Enum
from typing import Any, Dict, List, Tuple


INVALID_MARKET_ANSWER = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
)


class MarketState(Enum):
    """Market state"""

    OPEN = 1
    PENDING = 2
    FINALIZING = 3
    ARBITRATING = 4
    CLOSED = 5

    def __str__(self) -> str:
        """Prints the market status."""
        return self.name.capitalize()


def get_position_balance(
    user_positions: List[Dict[str, Any]],
    condition_id: str,
) -> Dict[str, int]:
    """Get the balance of a position."""
    positions: Dict[str, int] = defaultdict(int)

    for position in user_positions:
        position_condition_ids = position["position"]["conditionIds"]
        outcomes = position["position"]["conditions"][0]["outcomes"]
        indexSets = position["position"]["indexSets"]

        # index set is a position in outcomes counting from 1
        outcome_index = int(indexSets[0]) - 1

        balance = int(position["balance"])
        if condition_id.lower() in position_condition_ids:
            positions[outcomes[outcome_index]] += balance

    return positions


def get_position_lifetime_value(
    user_positions: List[Dict[str, Any]],
    condition_id: str,
) -> int:
    """Get the balance of a position."""
    for position in user_positions:
        position_condition_ids = position["position"]["conditionIds"]
        balance = int(position["position"]["lifetimeValue"])
        if condition_id.lower() in position_condition_ids:
            return balance

    return 0


def next_status(
    fpmm: Dict[str, Any],
    opening_timestamp: str,
    answer_finalized_timestamp: str,
    is_pending_arbitration: bool,
) -> MarketState:
    """Get the next market status."""
    if fpmm["currentAnswer"] is None:
        if opening_timestamp is not None and time.time() >= float(opening_timestamp):
            return MarketState.PENDING
        return MarketState.OPEN

    if is_pending_arbitration:
        return MarketState.ARBITRATING

    if time.time() < float(answer_finalized_timestamp):
        return MarketState.FINALIZING

    return MarketState.CLOSED


def get_bet_id_to_balance(
    creator_trades: List[Dict[str, Any]],
    user_positions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """Get the bet id to balance."""
    bet_id_to_balance: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for fpmm_trade in creator_trades:
        fpmm = fpmm_trade["fpmm"]
        bet_id = fpmm["id"]
        condition_id = fpmm["condition"]["id"]
        balance = get_position_balance(user_positions, condition_id)
        bet_id_to_balance[bet_id] = balance
    return bet_id_to_balance


def get_condition_id_to_balances(
    creator_trades: List[Dict[str, Any]],
    user_positions: List[Dict[str, Any]],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Get the condition id to balances."""
    condition_id_to_payout = {}
    condition_id_to_balance = {}
    for fpmm_trade in creator_trades:
        outcome_index = int(fpmm_trade["outcomeIndex"])
        fpmm = fpmm_trade["fpmm"]
        answer_finalized_timestamp = fpmm["answerFinalizedTimestamp"]
        is_pending_arbitration = fpmm["isPendingArbitration"]
        opening_timestamp = fpmm["openingTimestamp"]
        market_status = next_status(
            fpmm, opening_timestamp, answer_finalized_timestamp, is_pending_arbitration
        )

        if market_status == MarketState.CLOSED:
            current_answer = int(fpmm["currentAnswer"], 16)  # type: ignore
            # we have the correct answer, or the market was invalid
            if (
                outcome_index == current_answer
                or current_answer == INVALID_MARKET_ANSWER
            ):
                condition_id = fpmm_trade["fpmm"]["condition"]["id"]
                balance = get_position_balance(user_positions, condition_id)
                condition_id_to_balance[condition_id] = balance[str(outcome_index)]
                # get the payout for this condition
                payout = get_position_lifetime_value(user_positions, condition_id)
                if payout > 0 and balance[str(outcome_index)] == 0:
                    condition_id_to_payout[condition_id] = payout

    return condition_id_to_payout, condition_id_to_balance


def filter_claimed_conditions(
    payouts: Dict[str, int], claimed_condition_ids: List[str]
) -> Dict[str, int]:
    """Filter out the claimed payouts."""
    claimed_condition_ids = [
        condition_id.lower() for condition_id in claimed_condition_ids
    ]
    # filter out the claimed payouts, in a case-insensitive way
    return {
        condition_id: payout
        for condition_id, payout in payouts.items()
        if condition_id.lower() not in claimed_condition_ids
    }
