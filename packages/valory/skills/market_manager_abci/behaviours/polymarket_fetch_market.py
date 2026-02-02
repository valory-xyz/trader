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

"""This module contains the Polymarket fetch market behaviour for the MarketManager ABCI app."""

import json
import sys
from typing import Any, Dict, Generator, List, Optional

from dateutil import parser as date_parser

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.market_manager_abci.behaviours.base import (
    BetsManagerBehaviour,
)
from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    MAX_LOG_SIZE,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.states.polymarket_fetch_market import (
    PolymarketFetchMarketRound,
)


USCDE_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
# Threshold for extreme outcome prices indicating resolved/over markets
EXTREME_PRICE_THRESHOLD = 0.99

# Polymarket category keywords for validation
# fmt: off
POLYMARKET_CATEGORY_KEYWORDS = {
    "business": [
        "business", "corp", "corporate", "merger", "acquisition", "startup", "ceo", "cfo",
        "layoff", "hiring", "strike", "labor union", "trade union", "bankruptcy", "ipo",
        "company", "brand", "retail", "supply chain", "logistics", "management", "industry",
        "commercial", "monopoly", "antitrust", "executive", "stellantis", "byd", "tesla",
        "revenue", "profit",
    ],
    "politics": [
        "politics", "political", "election", "vote", "poll", "ballot", "democrat", "republican",
        "congress", "senate", "parliament", "president", "prime minister", "biden", "trump",
        "harris", "campaign", "legislation", "bill", "law", "supreme court", "governor", "mayor",
        "tory", "labour", "party", "impeachment", "regulatory", "uscis", "federal court",
    ],
    "science": [
        "science", "physics", "chemistry", "biology", "astronomy", "nasa", "space", "rocket",
        "spacex", "laboratory", "experiment", "discovery", "research", "scientist", "nobel prize",
        "atom", "molecule", "dna", "genetics", "telescope", "quantum", "fusion", "superconductor",
        "study", "peer-reviewed", "comet", "asteroid",
    ],
    "technology": [
        "technology", "tech", "ai", "artificial intelligence", "gpt", "llm", "software", "hardware",
        "app", "google", "apple", "microsoft", "meta", "server", "cloud", "algorithm", "robot",
        "cyber", "silicon", "chip", "semiconductor", "nvidia", "virtual reality", "metaverse",
        "device", "smartphone", "adobe", "semrush",
    ],
    "health": [
        "health", "medicine", "medical", "doctor", "hospital", "virus", "disease", "cancer",
        "vaccine", "drug", "pharmaceutical", "fda", "covid", "pandemic", "therapy", "surgery",
        "mental health", "diet", "nutrition", "obesity", "who", "treatment",
    ],
    "travel": [
        "travel", "tourism", "airline", "flight", "airport", "plane", "boeing", "airbus",
        "hotel", "resort", "visa", "passport", "destination", "cruise", "vacation", "booking",
        "airbnb", "expedia", "trip", "passenger", "transportation", "tour", "bus", "ntsb",
    ],
    "entertainment": [
        "entertainment", "movie", "film", "cinema", "hollywood", "actor", "actress", "netflix",
        "disney", "hbo", "box office", "oscar", "tv", "series", "streaming", "show", "theater",
        "gambling", "betting", "poker", "casino", "lottery",
    ],
    "weather": [
        "weather", "forecast", "hurricane", "storm", "tornado", "temperature", "rain", "snow",
        "heatwave", "drought", "flood", "meteorology", "climate", "monsoon", "el nino", "tropical",
        "depression", "dissipate", "noaa",
    ],
    "finance": [
        "finance", "financial", "stock", "share", "market", "wall street", "sp500", "nasdaq",
        "dow jones", "trade", "investor", "dividend", "portfolio", "hedge fund", "equity", "bond",
        "earnings", "bloomberg", "etf", "short", "long", "robinhood", "close",
    ],
    "international": [
        "international", "global", "war", "conflict", "ukraine", "russia", "israel", "gaza",
        "china", "un", "united nations", "nato", "treaty", "diplomacy", "foreign", "border",
        "geopolitics", "summit", "sanction", "ambassador", "territory",
    ],
}
# fmt: on


class PolymarketFetchMarketBehaviour(BetsManagerBehaviour, QueryingBehaviour):
    """Behaviour that fetches and updates the bets from Polymarket."""

    matching_round = PolymarketFetchMarketRound

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
        """Blacklist bets that are older than the opening margin or have resolved/over outcome prices."""
        for bet in self.bets:
            if self.synced_time >= bet.openingTimestamp - self.params.opening_margin:
                bet.blacklist_forever()
                continue
            # Blacklist binary markets with extreme outcome prices (>= 0.99) indicating resolved/over markets
            if len(bet.outcomeTokenMarginalPrices) == 2:
                if any(
                    float(price) >= EXTREME_PRICE_THRESHOLD
                    for price in bet.outcomeTokenMarginalPrices
                ):
                    bet.blacklist_forever()

    @staticmethod
    def _validate_market_category(market_title: str, category: str) -> bool:
        """
        Validate that a market title matches its assigned category keywords.

        :param market_title: The market question/title
        :param category: The assigned category
        :return: True if market matches category keywords, False otherwise
        """
        import re

        if (
            not isinstance(market_title, str)
            or category not in POLYMARKET_CATEGORY_KEYWORDS
        ):
            return False

        title_lower = market_title.lower()
        keywords = POLYMARKET_CATEGORY_KEYWORDS[category]

        # Check if any keyword matches
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, title_lower):
                return True

        return False

    def _validate_markets_by_category(
        self, markets_by_category: Dict[str, List[Dict]]
    ) -> Dict[str, List[Dict]]:
        """
        Validate markets against their assigned category keywords and mark them.

        :param markets_by_category: Dictionary mapping category to list of markets
        :return: Dictionary with all markets marked with 'category_valid' flag
        """
        marked_markets_by_category = {}
        total_validated = 0
        total_invalid = 0

        for category, markets in markets_by_category.items():
            marked_markets = []
            valid_count = 0
            invalid_count = 0

            for market in markets:
                market_title = market.get("question", "")
                is_valid = self._validate_market_category(market_title, category)

                # Add validation flag to market
                market["category_valid"] = is_valid
                marked_markets.append(market)

                if is_valid:
                    valid_count += 1
                else:
                    invalid_count += 1

            marked_markets_by_category[category] = marked_markets
            total_validated += valid_count
            total_invalid += invalid_count

            self.context.logger.info(
                f"Category '{category}': {valid_count}/{len(markets)} validated "
                f"({invalid_count} failed)"
            )

        self.context.logger.info(
            f"Total validated: {total_validated} markets, {total_invalid} failed validation"
        )

        return marked_markets_by_category

    def _deduplicate_markets(
        self, markets_by_category: Dict[str, List[Dict]]
    ) -> Dict[str, List[Dict]]:
        """
        Remove duplicate markets across categories, preferring category-valid ones.

        :param markets_by_category: Dictionary with all markets (valid and invalid)
        :return: Dictionary with deduplicated markets per category
        """
        # Track all occurrences of each market across categories
        market_occurrences: Dict[str, List[tuple[str, Dict[str, Any]]]] = (
            {}
        )  # market_id -> [(category, market_dict), ...]

        for category, markets in markets_by_category.items():
            for market in markets:
                market_id = market.get("id")
                if market_id:
                    if market_id not in market_occurrences:
                        market_occurrences[market_id] = []
                    market_occurrences[market_id].append((category, market))

        # Deduplicate: prefer category-valid markets, then first occurrence
        deduplicated_by_category: Dict[str, List[Dict[str, Any]]] = {}
        selected_markets = {}  # market_id -> (category, market_dict)
        duplicate_count = 0

        for market_id, occurrences in market_occurrences.items():
            if len(occurrences) == 1:
                # No duplicate - keep it
                category, market = occurrences[0]
                selected_markets[market_id] = (category, market)
            else:
                # Duplicate found - prefer category-valid markets
                duplicate_count += len(occurrences) - 1
                # Try to find a valid one first
                valid_occurrence = next(
                    (
                        (cat, mkt)
                        for cat, mkt in occurrences
                        if mkt.get("category_valid", False)
                    ),
                    None,
                )
                if valid_occurrence:
                    category, market = valid_occurrence
                else:
                    # All invalid, just keep first
                    category, market = occurrences[0]
                selected_markets[market_id] = (category, market)

        # Organize back by category
        for _market_id, (category, market) in selected_markets.items():
            if category not in deduplicated_by_category:
                deduplicated_by_category[category] = []
            deduplicated_by_category[category].append(market)

        self.context.logger.info(
            f"After deduplication: {len(selected_markets)} unique markets "
            f"({duplicate_count} duplicates removed) across {len(deduplicated_by_category)} categories"
        )

        return deduplicated_by_category

    @property
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

    def _fetch_markets_from_polymarket(self) -> Generator[None, None, Optional[List]]:
        """Fetch the markets from Polymarket using category-based filtering."""
        # Prepare payload data for FETCH_MARKETS request
        cache_file_path = str(self.params.store_path / "polymarket.json")
        polymarket_fetch_markets_payload = {
            "request_type": RequestType.FETCH_MARKETS.value,
            "params": {
                "cache_file_path": cache_file_path,
            },
        }

        response = yield from self.send_polymarket_connection_request(
            polymarket_fetch_markets_payload
        )

        if response is None:
            self.context.logger.error(
                "Failed to fetch markets from Polymarket - API call failed"
            )
            return None

        self.context.logger.info(
            f"Received markets from Polymarket: {len(response)} categories"
        )

        # Validate markets against category keywords (marks each with 'category_valid' flag)
        marked_markets_by_category = self._validate_markets_by_category(response)

        # Deduplicate ALL markets across categories (preferring valid ones)
        deduplicated_by_category = self._deduplicate_markets(marked_markets_by_category)

        # Process all markets from all categories
        all_bets: List[Dict[str, Any]] = []
        total_markets = 0
        total_skipped = 0
        blacklisted_count = 0

        for category, markets in deduplicated_by_category.items():
            category_count = len(markets)
            total_markets += category_count
            self.context.logger.info(
                f"Processing {category_count} markets from category: {category}"
            )
            skipped_in_category = 0

            for market in markets:
                market_id = market.get("id", "unknown")
                is_category_valid = market.get("category_valid", False)

                try:
                    # Parse JSON fields from response
                    outcomes = json.loads(market.get("outcomes", "[]"))
                    outcome_prices = json.loads(market.get("outcomePrices", "[]"))
                    clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))

                    # Validate that we have the required data
                    if not outcomes or not outcome_prices or not clob_token_ids:
                        raise ValueError(
                            "Missing required fields (outcomes, prices, or token IDs)"
                        )

                    if len(outcomes) != len(outcome_prices) or len(outcomes) != len(
                        clob_token_ids
                    ):
                        raise ValueError(
                            f"Mismatched lengths - outcomes: {len(outcomes)}, "
                            f"prices: {len(outcome_prices)}, token_ids: {len(clob_token_ids)}"
                        )

                    # Parse end_date and opening_timestamp
                    end_date = market.get("endDate", "")
                    if not end_date:
                        raise ValueError("Missing endDate")

                    opening_timestamp = int(date_parser.isoparse(end_date).timestamp())

                    # Parse liquidity and validate
                    liquidity = float(market.get("liquidity", "0"))
                    if liquidity < 0:
                        raise ValueError(f"Negative liquidity: {liquidity}")

                    # Parse and validate outcome prices
                    parsed_prices = [float(price) for price in outcome_prices]
                    if any(price < 0 or price > 1 for price in parsed_prices):
                        raise ValueError(f"Invalid price range: {parsed_prices}")

                    # Calculate outcome token amounts
                    outcome_token_amounts = [
                        int(liquidity * price * 10**6) for price in parsed_prices
                    ]

                    # Create outcome_token_ids mapping
                    outcome_token_ids_map = {
                        outcome: token_id
                        for outcome, token_id in zip(outcomes, clob_token_ids)
                    }

                    # Validate required fields
                    if not market.get("conditionId"):
                        raise ValueError("Missing conditionId")

                    if not market.get("question"):
                        raise ValueError("Missing question")

                    bet_dict = {
                        "id": market_id,
                        "title": market.get("question"),
                        "category": category,
                        "condition_id": market.get("conditionId"),
                        "collateralToken": USCDE_POLYGON,  # Polymarket uses USDC.e on Polygon
                        "creator": market.get("submitted_by", ZERO_ADDRESS),
                        "fee": 0,  # Polymarket fee is typically 0 or handled differently
                        "openingTimestamp": opening_timestamp,
                        "outcomeSlotCount": len(outcomes),
                        "outcomeTokenAmounts": outcome_token_amounts,
                        "outcomeTokenMarginalPrices": parsed_prices,
                        "outcomes": (
                            None if not is_category_valid else outcomes
                        ),  # None = blacklist
                        "scaledLiquidityMeasure": liquidity,
                        "processed_timestamp": (
                            sys.maxsize if not is_category_valid else 0
                        ),
                        "position_liquidity": 0,
                        "potential_net_profit": 0,
                        "queue_status": (
                            QueueStatus.EXPIRED
                            if not is_category_valid
                            else QueueStatus.FRESH
                        ),
                        "investments": {},
                        "outcome_token_ids": outcome_token_ids_map,
                    }

                    # Debug: Log category for first few bets
                    if len(all_bets) < 5:
                        self.context.logger.info(
                            f"Creating bet_dict for market {market_id}: category={category}, "
                            f"is_valid={is_category_valid}"
                        )

                    all_bets.append(bet_dict)

                    # Track blacklisted markets
                    if not is_category_valid:
                        blacklisted_count += 1

                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    self.context.logger.warning(
                        f"Skipping market {market_id}: Invalid or missing required fields - {e}"
                    )
                    skipped_in_category += 1
                    continue
                except Exception as e:
                    self.context.logger.error(
                        f"Unexpected error processing market {market_id}: {e}",
                        exc_info=True,
                    )
                    skipped_in_category += 1
                    continue

            # Log summary for this category
            processed_in_category = category_count - skipped_in_category
            if skipped_in_category > 0:
                self.context.logger.info(
                    f"Category '{category}': Processed {processed_in_category}/{category_count} markets "
                    f"({skipped_in_category} skipped due to invalid data)"
                )
            total_skipped += skipped_in_category

        # Log overall summary
        self.context.logger.info(
            f"Constructed {len(all_bets)} bet_dicts from {total_markets} total markets "
            f"({total_skipped} skipped, {blacklisted_count} blacklisted due to category validation)"
        )

        return all_bets

    def _update_bets(self) -> Generator:
        """Fetch the questions from all the prediction markets and update the local copy of the bets."""
        # Fetch markets from Polymarket
        bets_market_chunk = yield from self._fetch_markets_from_polymarket()

        # If fetch failed, clear bets to trigger FETCH_ERROR event
        if bets_market_chunk is None:
            self.context.logger.error(
                "Market fetch failed, clearing bets to trigger error event"
            )
            self.bets = []
            return

        self._process_chunk(bets_market_chunk)
        self._blacklist_expired_bets()

        # truncate the bets, otherwise logs get too big
        bets_str = str(self.bets)[:MAX_LOG_SIZE]
        self.context.logger.info(f"Updated bets: {bets_str}")

    def update_bets_investments(self) -> Generator:
        """Update the investments of the bets from Polymarket positions."""
        self.context.logger.info("Updating bets investments from Polymarket positions.")
        
        # Fetch all positions (not just redeemable ones) to track all investments
        polymarket_positions_payload = {
            "request_type": RequestType.FETCH_ALL_POSITIONS.value,
        }
        
        positions = yield from self.send_polymarket_connection_request(
            polymarket_positions_payload
        )
        
        if positions is None:
            self.context.logger.warning("Failed to fetch positions from Polymarket")
            return
        
        self.context.logger.debug(f"Fetched {len(positions)} positions from Polymarket")
        
        # Group positions by condition_id
        positions_by_condition: Dict[str, List[Dict[str, Any]]] = {}
        for position in positions:
            condition_id = position.get("conditionId")
            if condition_id:
                if condition_id not in positions_by_condition:
                    positions_by_condition[condition_id] = []
                positions_by_condition[condition_id].append(position)
        
        # Update investments for each bet
        for bet in self.bets:
            if bet.queue_status.is_expired():
                self.context.logger.debug(f"Bet {bet.id} is expired, skipping investment update")
                continue
            
            if bet.condition_id is None:
                self.context.logger.debug(f"Bet {bet.id} has no condition_id, skipping")
                continue
            
            # Reset investments first
            bet.reset_investments()
            
            # Find positions for this bet's condition_id
            matching_positions = positions_by_condition.get(bet.condition_id, [])
            
            if not matching_positions:
                self.context.logger.debug(
                    f"No positions found for bet {bet.id} with condition_id {bet.condition_id}"
                )
                continue
            
            # Update investments for each position
            for position in matching_positions:
                outcome_index = position.get("outcomeIndex")
                initial_value = position.get("initialValue")
                
                if outcome_index is None or initial_value is None:
                    self.context.logger.warning(
                        f"Position missing outcomeIndex or initialValue: {position}"
                    )
                    continue
                
                # Convert initialValue to investment amount in base units
                try:
                    # Convert initialValue from human-readable USDC to base units integer
                    initial_value_float = float(initial_value)
                    investment_amount = int(initial_value_float * 10**6)
                except (ValueError, TypeError) as e:
                    self.context.logger.warning(
                        f"Could not convert position initialValue to investment amount: {initial_value}, error: {e}"
                    )
                    continue
                
                # Validate outcome_index is within bounds
                if bet.outcomes is None:
                    self.context.logger.warning(
                        f"Bet {bet.id} has no outcomes list, cannot map outcome_index {outcome_index}"
                    )
                    continue
                
                if outcome_index < 0 or outcome_index >= len(bet.outcomes):
                    self.context.logger.warning(
                        f"Outcome index {outcome_index} out of bounds for bet {bet.id} "
                        f"with {len(bet.outcomes)} outcomes"
                    )
                    continue
                
                # Append investment amount - append_investment_amount internally calls get_outcome()
                bet.append_investment_amount(outcome_index, investment_amount)
                self.context.logger.debug(
                    f"Updated bet {bet.id}: outcome_index={outcome_index}, "
                    f"amount={investment_amount}, investments={bet.investments}"
                )
        
        self.context.logger.info("Finished updating bets investments from Polymarket positions")

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
            # Update investments from existing positions to prevent duplicate bets
            yield from self.update_bets_investments()

            if self.review_bets_for_selling:
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
