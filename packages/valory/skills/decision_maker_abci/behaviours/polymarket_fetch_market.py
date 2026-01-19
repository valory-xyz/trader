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

"""This module contains the behaviour for fetching markets from Polymarket."""

import json
from typing import Any, Dict, Generator, List, Optional

from dateutil import parser as date_parser

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.states.polymarket_fetch_market import (
    PolymarketFetchMarketRound,
)
from packages.valory.skills.market_manager_abci.bets import Bet
from packages.valory.skills.market_manager_abci.behaviours import (
    BetsManagerBehaviour,
    MULTI_BETS_FILENAME,
    USCDE_POLYGON,
    ZERO_ADDRESS,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    MAX_LOG_SIZE,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload


class PolymarketFetchMarketBehaviour(BetsManagerBehaviour, QueryingBehaviour):
    """Behaviour that fetches and updates the bets from Polymarket."""

    matching_round = PolymarketFetchMarketRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `PolymarketFetchMarketBehaviour`."""
        super().__init__(**kwargs)

    def _requeue_all_bets(self) -> None:
        """Requeue all bets."""
        for bet in self.bets:
            bet.queue_status = bet.queue_status.move_to_fresh()

    def _requeue_bets_for_selling(self) -> None:
        """Requeue sell bets."""
        for bet in self.bets:
            time_since_last_sell_check = (
                self.synced_time - bet.last_processed_sell_check
            )
            if (
                bet.is_ready_to_sell(self.synced_time, self.params.opening_margin)
                and not bet.queue_status.is_expired()
                and bet.invested_amount > 0
                and (
                    not bet.last_processed_sell_check
                    or time_since_last_sell_check > self.params.sell_check_interval
                )
            ):
                self.context.logger.info(
                    f"Requeueing bet {bet.id!r} for selling, with invested amount: {bet.invested_amount!r}."
                )
                bet.queue_status = bet.queue_status.move_to_fresh()

    def _blacklist_expired_bets(self) -> None:
        """Blacklist bets that are older than the opening margin."""
        for bet in self.bets:
            if self.synced_time >= bet.openingTimestamp - self.params.opening_margin:
                bet.blacklist_forever()

    def review_bets_for_selling(self) -> bool:
        """Review bets for selling."""
        return self.synchronized_data.review_bets_for_selling

    def setup(self) -> None:
        """Set up the behaviour."""
        # Read the bets from the agent's data dir as JSON, if they exist
        self.read_bets()

        self.context.logger.info(
            f"Check point is reached: {self.synchronized_data.is_checkpoint_reached=}"
        )

        # fetch checkpoint status and if reached requeue all bets
        if (
            self.synchronized_data.is_checkpoint_reached
            and self.params.use_multi_bets_mode
        ):
            self._requeue_all_bets()

        # blacklist bets that are older than the opening margin
        # if trader ran after a long time
        # helps in resetting the queue number to 0
        if self.bets:
            self._blacklist_expired_bets()

    def get_bet_idx(self, bet_id: str) -> Optional[int]:
        """Get the index of the bet with the given id, if it exists, otherwise `None`."""
        return next((i for i, bet in enumerate(self.bets) if bet.id == bet_id), None)

    def _process_chunk(self, chunk: Optional[List[Dict[str, Any]]]) -> None:
        """Process a chunk of bets."""
        if chunk is None:
            return

        for raw_bet in chunk:
            bet = Bet(**raw_bet, market=self._current_market)
            index = self.get_bet_idx(bet.id)
            if index is None:
                self.bets.append(bet)
            else:
                self.bets[index].update_market_info(bet)

    def _fetch_markets_from_polymarket(self) -> Generator:
        """Fetch the markets from Polymarket using category-based filtering."""
        # Prepare payload data for FETCH_MARKETS request
        polymarket_fetch_markets_payload = {
            "request_type": RequestType.FETCH_MARKETS.value,
            "params": {},
        }
        
        response = yield from self.send_polymarket_connection_request(
            polymarket_fetch_markets_payload
        )
        
        if response is None:
            self.context.logger.error("Failed to fetch markets from Polymarket")
            return []
        
        self.context.logger.info(f"Received markets from Polymarket: {len(response)} categories")
        
        # Process all markets from all categories
        all_bets = []
        for category, markets in response.items():
            self.context.logger.info(f"Processing {len(markets)} markets from category: {category}")
            
            for market in markets:
                # Parse JSON fields from response
                outcomes = json.loads(market.get("outcomes", "[]"))
                outcome_prices = json.loads(market.get("outcomePrices", "[]"))
                clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))
                
                end_date = market.get("endDate", "")
                opening_timestamp = (
                    int(date_parser.isoparse(end_date).timestamp()) if end_date else 0
                )
                
                # Calculate outcomeTokenAmounts from liquidity and prices
                liquidity = float(market.get("liquidity", "0"))
                outcome_token_amounts = [
                    int(liquidity * float(price) * 10**6) for price in outcome_prices
                ]
                
                # Create outcome_token_ids mapping
                outcome_token_ids_map = {
                    outcome: token_id for outcome, token_id in zip(outcomes, clob_token_ids)
                }
                
                bet_dict = {
                    "id": market.get("id"),
                    "condition_id": market.get("conditionId"),
                    "title": market.get("question"),
                    "collateralToken": USCDE_POLYGON,  # Polymarket uses USDC.e on Polygon
                    "creator": market.get("submitted_by", ZERO_ADDRESS),
                    "fee": 0,  # Polymarket fee is typically 0 or handled differently
                    "openingTimestamp": opening_timestamp,
                    "outcomeSlotCount": len(outcomes),
                    "outcomeTokenAmounts": outcome_token_amounts,
                    "outcomeTokenMarginalPrices": [float(price) for price in outcome_prices],
                    "outcomes": outcomes,
                    "scaledLiquidityMeasure": liquidity,
                    "processed_timestamp": 0,
                    "position_liquidity": 0,
                    "potential_net_profit": 0,
                    "investments": {},
                    "outcome_token_ids": outcome_token_ids_map,
                }
                all_bets.append(bet_dict)
        
        self.context.logger.info(f"Constructed {len(all_bets)} bet_dicts from all categories")
        return all_bets

    def _update_bets(self) -> Generator:
        """Fetch the questions from all the prediction markets and update the local copy of the bets."""
        # Deleting all current markets
        with open(self.context.params.store_path / MULTI_BETS_FILENAME, "w") as f:
            f.write("")

        # Fetch markets from Polymarket
        bets_market_chunk = yield from self._fetch_markets_from_polymarket()
        self._process_chunk(bets_market_chunk)

        # truncate the bets, otherwise logs get too big
        bets_str = str(self.bets)[:MAX_LOG_SIZE]
        self.context.logger.info(f"Updated bets: {bets_str}")

    def _bet_freshness_check_and_update(self) -> None:
        """Check the freshness of the bets."""
        # single-bets mode case - mark any market with a `FRESH` status as processable
        if not self.params.use_multi_bets_mode:
            for bet in self.bets:
                if bet.queue_status.is_fresh():
                    bet.queue_status = bet.queue_status.move_to_process()
            return

        # multi-bets mode case - mark markets as processable only if all the unexpired ones have a `FRESH` status
        # this will happen if the agent just started or the checkpoint has just been reached
        all_bets_fresh = all(
            bet.queue_status.is_fresh()
            for bet in self.bets
            if not bet.queue_status.is_expired()
        )

        if all_bets_fresh:
            for bet in self.bets:
                bet.queue_status = bet.queue_status.move_to_process()

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Update the bets list with new bets or update existing ones
            yield from self._update_bets()

            if self.review_bets_for_selling():
                self._requeue_bets_for_selling()

            # if trader is run after a long time, there is a possibility that
            # all bets are fresh and this should be updated to DAY_0_FRESH
            if self.bets:
                self._bet_freshness_check_and_update()

            # Store the bets to the agent's data dir as JSON
            self.store_bets()

            bets_hash = self.hash_stored_bets() if self.bets else None
            payload = UpdateBetsPayload(self.context.agent_address, bets_hash)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()
