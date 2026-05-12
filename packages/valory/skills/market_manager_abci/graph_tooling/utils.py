# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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
        position_data = position.get("position", {})
        position_condition_ids = position_data.get("conditionIds", [])

        if condition_id.lower() not in position_condition_ids:
            continue

        conditions = position_data.get("conditions", [])
        indexSets = position_data.get("indexSets", [])

        if not conditions or not indexSets:
            continue

        outcomes = conditions[0].get("outcomes")
        if not outcomes:
            continue

        # index set is a position in outcomes counting from 1
        outcome_index = int(indexSets[0]) - 1

        balance = int(position["balance"])
        if condition_id.lower() in position_condition_ids:  # pragma: no branch
            positions[outcomes[outcome_index]] += balance

    return positions


def get_position_lifetime_value(
    user_positions: List[Dict[str, Any]],
    condition_id: str,
) -> int:
    """Get the balance of a position."""
    for position in user_positions:
        position_condition_ids = map(
            lambda x: x.lower(), position["position"]["conditionIds"]
        )
        balance = int(position["position"]["lifetimeValue"])

        matching_positions = []

        for condition in position["position"]["conditions"]:
            if condition["id"].lower() != condition_id.lower():
                continue

            # if position is claimed, balance is 0
            balance = int(position["totalBalance"])
            if balance > 0:
                matching_positions.append(condition)

        if (
            condition_id.lower() in position_condition_ids
            and len(matching_positions) > 0
        ):
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
                    # if position is not claimed, balance is the payout
                    condition_id_to_balance[condition_id] = payout

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


@dataclass(frozen=True)
class WithdrawablePosition:
    """A safe-held position that the Omen withdrawal sweep can sell.

    Built by :func:`get_withdrawable_positions` from the join of the
    ConditionalTokens subgraph ``user_positions`` (authoritative source for
    current ERC1155 balance — authoritative because it reflects on-chain
    redemptions, unlike the immutable bet history) and the omen subgraph
    ``fpmm`` metadata (resolution state).
    """

    fpmm_address: str
    outcome_index: int
    balance: int
    condition_id: str
    index_set: int
    # ERC1155 position id from the CT subgraph (``position.id``), converted
    # from bytes32 hex to the decimal string the FE / Polystrat fills use
    # as ``token_id``. Lets us avoid an off-chain keccak derivation that
    # would need to mirror the CT contract's getCollectionId/getPositionId
    # implementation byte-for-byte.
    token_id: str


def _is_power_of_two(value: int) -> bool:
    """Return True iff ``value`` is a positive power of two."""
    return value > 0 and (value & (value - 1)) == 0


def _is_finalized_timestamp(value: Any) -> bool:
    """Return True iff a subgraph timestamp indicates a finalized answer.

    Some Omen subgraph indexers emit the string ``"0"`` (or integer
    ``0``) for an unset ``answerFinalizedTimestamp`` rather than
    ``null``. A naive ``is not None`` check would treat ``"0"`` as
    finalized and exclude truly-unfinalized OPEN positions from the
    withdrawal sweep, stranding user funds.

    Treats ``None``, ``"0"``, ``0``, negative values, and malformed
    inputs as not-finalized. Mirrors the ``parse_timestamp`` helper in
    :mod:`agent_performance_summary_abci.graph_tooling.predictions_helper`
    — kept inline to avoid an upward cross-skill dependency on the
    perf-summary package.
    """
    if value is None:
        return False
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False
    return parsed > 0


def get_withdrawable_positions(
    creator_trades: List[Dict[str, Any]],
    user_positions: List[Dict[str, Any]],
) -> List[WithdrawablePosition]:
    """Filter ``user_positions`` to the OPEN bucket (§1 classification).

    Excludes resolved markets (WINNING / LOSING / RESOLVED_PENDING — those
    are handled by ``RedeemRound`` or carry no value), markets pending
    arbitration (FROZEN), zero-balance rows, compound positions with more
    than one condition / index-set entry, and non-power-of-two index sets
    (a single-outcome position must have exactly one bit set).

    Distinct from the existing :func:`get_position_balance` helper, which
    decodes ``outcome_index`` as ``int(indexSets[0]) - 1`` (correct only
    for 2-outcome markets where the chosen outcome equals indexSet ``2``
    minus one). The N-outcome correct decoding is ``log2(indexSet)`` —
    used here.

    :param creator_trades: omen subgraph ``fpmmTrades`` for the safe,
        providing FPMM metadata (``id``, ``condition.id``,
        ``answerFinalizedTimestamp``, ``isPendingArbitration``).
    :param user_positions: ConditionalTokens subgraph ``userPositions``
        rows for the safe, providing the authoritative current ERC1155
        ``balance`` per position.
    :return: One :class:`WithdrawablePosition` per OPEN-bucket position.
    """
    fpmm_by_condition: Dict[str, Dict[str, Any]] = {}
    for trade in creator_trades:
        fpmm = trade.get("fpmm") or {}
        condition = fpmm.get("condition") or {}
        condition_id = (condition.get("id") or "").lower()
        if condition_id:
            fpmm_by_condition.setdefault(condition_id, fpmm)

    out: List[WithdrawablePosition] = []
    for row in user_positions:
        try:
            balance = int(row.get("balance", 0))
        except (TypeError, ValueError):
            continue
        if balance == 0:
            continue
        position = row.get("position") or {}
        condition_ids = position.get("conditionIds") or []
        index_sets_raw = position.get("indexSets") or []
        if len(condition_ids) != 1 or len(index_sets_raw) != 1:
            # compound position — trader agent doesn't create these
            continue
        condition_id = condition_ids[0].lower()
        try:
            index_set = int(index_sets_raw[0])
        except (TypeError, ValueError):
            continue
        if not _is_power_of_two(index_set):
            continue
        fpmm_meta: Optional[Dict[str, Any]] = fpmm_by_condition.get(condition_id)
        if fpmm_meta is None:
            # CT position with no FPMM in the safe's trade history
            continue
        if _is_finalized_timestamp(fpmm_meta.get("answerFinalizedTimestamp")):
            # resolved (WINNING / LOSING / RESOLVED_PENDING bucket)
            continue
        if fpmm_meta.get("isPendingArbitration"):
            # FROZEN
            continue
        position_id_hex = (position.get("id") or "").lower()
        if not position_id_hex:
            continue
        try:
            token_id_decimal = str(int(position_id_hex, 16))
        except ValueError:
            continue
        out.append(
            WithdrawablePosition(
                fpmm_address=fpmm_meta["id"],
                outcome_index=index_set.bit_length() - 1,
                balance=balance,
                condition_id=condition_id,
                index_set=index_set,
                token_id=token_id_decimal,
            )
        )
    return out
