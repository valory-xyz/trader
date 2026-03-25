# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Fixed bet sizing strategy."""

from typing import Any, Dict, List


REQUIRED_FIELDS = frozenset({"bankroll", "floor_balance", "p_yes"})
OPTIONAL_FIELDS = frozenset({"bet_amount", "min_bet", "max_bet", "token_decimals"})


def run(**kwargs: Any) -> Dict[str, Any]:
    """Return a fixed bet amount. Side = higher-probability side.

    :param kwargs: strategy parameters.
    :return: dict with bet_amount, vote, info, error.
    """
    info: List[str] = []
    error: List[str] = []

    missing = [f for f in REQUIRED_FIELDS if kwargs.get(f) is None]
    if missing:
        return {
            "bet_amount": 0,
            "vote": None,
            "error": [f"Missing required fields: {missing}"],
        }

    bankroll: int = kwargs["bankroll"]
    floor_balance: int = kwargs["floor_balance"]
    p_yes: float = kwargs["p_yes"]
    p_no: float = 1.0 - p_yes

    # Side selection: pick the higher-probability side
    if p_yes == p_no:
        return {
            "bet_amount": 0,
            "vote": None,
            "info": ["Tie — no bet"],
            "error": error,
        }
    vote = int(p_no > p_yes)  # 0=YES, 1=NO

    if bankroll <= floor_balance:
        info.append("Bankroll below floor")
        return {"bet_amount": 0, "vote": vote, "info": info, "error": error}

    bet_amount: int = kwargs.get("bet_amount", kwargs.get("min_bet", 0))
    if bet_amount <= 0:
        info.append("No bet_amount configured")
        return {"bet_amount": 0, "vote": vote, "info": info, "error": error}

    max_bet: int = kwargs.get("max_bet", bet_amount)
    bet_amount = min(bet_amount, max_bet, bankroll - floor_balance)

    info.append(f"Fixed bet: {bet_amount}")
    return {
        "bet_amount": int(bet_amount),
        "vote": vote,
        "info": info,
        "error": error,
    }
