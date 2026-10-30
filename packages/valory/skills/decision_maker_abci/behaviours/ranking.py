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

"""This module contains the behaviours that request and store a ranking of the candidate markets."""

import json
import logging
from dataclasses import asdict
from typing import Any, Dict, Generator, List, Optional, Tuple
from uuid import uuid4

from packages.valory.skills.chatui_abci.tool_keys import tool_names
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.sampling import (
    RANKING_MAX_AGE,
    SamplingBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import RankingRequestPayload
from packages.valory.skills.decision_maker_abci.states.base import RANKING_TOOL
from packages.valory.skills.decision_maker_abci.states.ranking import (
    RankingReceiveRound,
    RankingRequestRound,
)
from packages.valory.skills.market_manager_abci.bets import (
    BINARY_N_SLOTS,
    Bet,
    QueueStatus,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.mech_interact_abci.states.base import MechMetadata
from packages.valory.skills.mech_interact_abci.utils import loads_bounded

RANKING_MAX_MARKETS = 100
RANKING_MIN_MARKETS = 10
# requests one list may take; the markets past them follow today's order
RANKING_MAX_REQUESTS = 3
LIST_MAX_MARKETS = RANKING_MAX_REQUESTS * RANKING_MAX_MARKETS

# Takes the pool logs of the ranking round, so only Sampling prints them.
QUIET_LOGGER = logging.getLogger(f"{__name__}.quiet")
QUIET_LOGGER.disabled = True


class RankingRequestBehaviour(SamplingBehaviour):
    """A behaviour that requests a ranking of the candidate markets when a list or its queued part is due."""

    matching_round = RankingRequestRound  # type: ignore[assignment]

    @property
    def pool_logger(self) -> Any:
        """Get the logger of the pool and per-pick checks."""
        return QUIET_LOGGER

    def _has_room_to_trade(self, bet: Bet) -> bool:
        """Whether a bet can still be won: no side above ranking_max_price and, on Polymarket, a stored book the book check accepts."""
        if max(bet.outcomeTokenMarginalPrices) > self.params.ranking_max_price:
            return False
        bid, ask = bet.best_bid, bet.best_ask
        if not self.params.is_running_on_polymarket or (bid is None and ask is None):
            return True

        def level(price: Optional[float]) -> List[Dict[str, Any]]:
            return [] if price is None or not 0 < price < 1 else [{"price": price}]

        # the first outcome's book, then the second as its complement, rounded
        # as the CLOB prints prices so a spread at the band's edge compares alike
        sides = (
            (level(ask), level(bid)),
            (
                level(None if bid is None else round(1 - bid, 4)),
                level(None if ask is None else round(1 - ask, 4)),
            ),
        )
        lo, hi = self.params.polymarket_spread_min, self.params.polymarket_spread_max
        return any(
            self._side_rejection(asks, bids, lo, hi) is None for asks, bids in sides
        )

    def _ranking_batch(self) -> Tuple[List[Bet], int]:
        """Get the markets to rank in today's order and the list's stamp; no markets when no request is due."""
        # unset until the first redeem round reaches consensus
        tools = self.synchronized_data.db.get("available_mech_tools", None)
        if not (
            self.params.enable_market_ranking
            and self.synchronized_data.is_marketplace_v2
            and tools
            and RANKING_TOOL in tool_names(json.loads(tools))
            and self.params.slot_count == BINARY_N_SLOTS
        ):
            return [], 0

        now = self.synced_timestamp
        available, _ = self._processable_bets(now)
        # The untried markets Sampling could pick and its book check would
        # pass; a market with a failed book check follows today's order, as on
        # the list.
        eligible = [
            bet
            for bet in self._drop_disabled_tags(available)
            if bet.queue_status == QueueStatus.TO_PROCESS
            and not bet.invested_amount
            and not bet.processed_timestamp
            and self._pick_filter_reason(bet) is None
            and self._has_room_to_trade(bet)
        ]
        # One market per Polymarket event, none from an event with a live
        # position: the rungs of one event are one question.
        events = {
            bet.poly_event_id
            for bet in self.bets
            if bet.has_investments and not bet.queue_status.is_expired()
        }
        candidates = []
        for bet in self._sort_by_priority_logic(eligible):
            if bet.poly_event_id is None or bet.poly_event_id not in events:
                events.add(bet.poly_event_id)
                candidates.append(bet)
        latest = max((bet.ranked_at for bet in self.bets), default=0)
        if now - latest >= RANKING_MAX_AGE:
            return (
                (candidates[:LIST_MAX_MARKETS], now)
                if len(candidates) >= RANKING_MIN_MARKETS
                else ([], 0)
            )
        # Markets a renewal could not fit in its request go next, on the same
        # list. The queue is sent once: a market that misses it (prices or book
        # changed) counts as never ranked and waits for a renewal.
        queued = [bet for bet in candidates if latest > 0 and bet.ranked_at == -latest]
        missed = [bet for bet in self.bets if latest > 0 and bet.ranked_at == -latest]
        for bet in missed:
            bet.ranked_at = 0
        if queued:
            return queued, latest
        if missed:
            self.store_bets()
        # A used-up list renews only with never-ranked markets, so markets
        # whose books keep failing cannot bring a ranking every cooldown.
        never_ranked = sum(bet.ranked_at <= 0 for bet in candidates)
        # the list counts as used up on the whole pool, not only on the
        # markets that represent their event in this batch
        if self._ranked_list(eligible) or never_ranked < RANKING_MIN_MARKETS:
            return [], 0
        # never-ranked markets go first: past the cap they would stay unranked
        # and an unscored list would bring the same requests every period
        never_first = sorted(candidates, key=lambda bet: bet.ranked_at > 0)
        return never_first[:LIST_MAX_MARKETS], now

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            agent = self.context.agent_address
            candidates, stamp = self._ranking_batch()
            batch = candidates[:RANKING_MAX_MARKETS]
            payload = RankingRequestPayload(agent, None, None, None, None)
            if batch:
                # The stamp is stored before the request, so a lost answer
                # cannot bring another ranking before the list expires.
                for bet in batch:
                    bet.ranked_at, bet.research_score = stamp, None
                # the rest is queued for the next request of the same list
                for bet in candidates[RANKING_MAX_MARKETS:]:
                    bet.ranked_at, bet.research_score = -stamp, None
                self.store_bets()
                markets = [
                    {
                        "id": bet.id,
                        "title": bet.title,
                        "close_time": bet.openingTimestamp,
                    }
                    for bet in batch
                ]
                prompt = json.dumps({"markets": markets})
                metadata = MechMetadata(prompt, RANKING_TOOL, str(uuid4()))
                self.shared_state.mech_timed_out = False
                self.context.logger.info(
                    f"[RANKING] requesting a ranking of {len(batch)} markets "
                    f"({len(candidates) - len(batch)} queued for the next request)."
                )
                payload = RankingRequestPayload(
                    agent,
                    self.hash_stored_bets(),
                    json.dumps([asdict(metadata)], sort_keys=True),
                    RANKING_TOOL,
                    None,
                )
        yield from self.finish_behaviour(payload)


class RankingReceiveBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour that stores the scores of a ranking answer, or passes a prediction answer on."""

    matching_round = RankingReceiveRound

    def _store_scores(self) -> None:
        """Store the valid scores of the answer on the markets of the latest list."""
        try:
            response = self.synchronized_data.mech_responses[0].result
            ranking = list(loads_bounded(response)["ranking"])  # type: ignore[arg-type]
        except (IndexError, KeyError, TypeError, ValueError):
            ranking = []
        scores: Dict[str, Any] = {}
        for entry in ranking:
            # a malformed entry is skipped; the first of repeated ids is kept
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                scores.setdefault(entry["id"], entry.get("score"))

        self.read_bets()
        latest = max((bet.ranked_at for bet in self.bets), default=0)
        listed = [bet for bet in self.bets if latest and bet.ranked_at == latest]
        stored = 0
        for bet in listed:
            score = scores.get(bet.id)
            if (
                isinstance(score, (int, float))
                and not isinstance(score, bool)
                and 0 <= score <= 1
            ):
                bet.research_score = float(score)
                stored += 1
        self.store_bets()
        # a list sent in several requests counts the scores of all of them
        unscored = sum(bet.research_score is None for bet in listed)
        self.context.logger.info(
            f"[RANKING] stored={stored} unscored={unscored} "
            f"answer_entries={len(scores)}"
        )

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            bets_hash = None
            if self.synchronized_data.is_ranking_period:
                self._store_scores()
                bets_hash = self.hash_stored_bets()
            payload = UpdateBetsPayload(self.context.agent_address, bets_hash)
        yield from self.finish_behaviour(payload)
