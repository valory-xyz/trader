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

"""Utils for graph interactions."""
import time
from enum import Enum
from typing import Any, Dict, List


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
) -> int:
    """Get the balance of a position."""
    for position in user_positions:
        position_condition_ids = position["position"]["conditionIds"]
        balance = int(position["balance"])
        if condition_id.lower() in position_condition_ids:
            return balance

    return 0


def get_condition_id_to_payout(
    creator_trades: List[Dict[str, Any]],
    user_positions: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Get the condition id to payout."""
    condition_id_to_payout = {}
    for fpmm_trade in creator_trades:
        outcome_index = int(fpmm_trade["outcomeIndex"])
        fpmm = fpmm_trade["fpmm"]
        answer_finalized_timestamp = fpmm["answerFinalizedTimestamp"]
        is_pending_arbitration = fpmm["isPendingArbitration"]
        opening_timestamp = fpmm["openingTimestamp"]
        market_status = MarketState.CLOSED
        if fpmm["currentAnswer"] is None and time.time() >= float(opening_timestamp):
            market_status = MarketState.PENDING
        elif fpmm["currentAnswer"] is None:
            market_status = MarketState.OPEN
        elif is_pending_arbitration:
            market_status = MarketState.ARBITRATING
        elif time.time() < float(answer_finalized_timestamp):
            market_status = MarketState.FINALIZING

        if market_status == MarketState.CLOSED:
            current_answer = int(fpmm["currentAnswer"], 16)  # type: ignore
            # we have the correct answer, and we haven't redeemed yet
            if outcome_index == current_answer:
                condition_id = fpmm_trade["fpmm"]["condition"]["id"]
                payout = get_position_balance(user_positions, condition_id)
                if payout > 0:
                    condition_id_to_payout[condition_id] = payout

    return condition_id_to_payout
