# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for the Polymarket fetch market behaviour."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.market_manager_abci.behaviours.polymarket_fetch_market import (
    EXTREME_PRICE_THRESHOLD,
    POLYMARKET_CATEGORY_KEYWORDS,
    PUSD_POLYGON,
    PolymarketFetchMarketBehaviour,
    USDC_DECIMALS,
    USDC_E_POLYGON,
    ZERO_ADDRESS,
    _polymarket_dry_run_enabled,
)
from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """A generator that yields once and returns None."""
    yield
    return None


def _return_gen(value: Any) -> Any:
    """Return a generator factory that yields once and returns the given value."""

    def gen(*args: Any, **kwargs: Any) -> Generator:  # type: ignore[no-untyped-def]
        yield
        return value

    return gen


def _make_behaviour(**overrides: Any) -> PolymarketFetchMarketBehaviour:
    """Create a PolymarketFetchMarketBehaviour instance using object.__new__."""
    behaviour = object.__new__(PolymarketFetchMarketBehaviour)  # type: ignore[type-abstract]
    behaviour._context = MagicMock()
    behaviour.bets = []
    behaviour.multi_bets_filepath = "/tmp/multi_bets.json"  # type: ignore[type-abstract]  # nosec B108
    behaviour.bets_filepath = "/tmp/bets.json"  # nosec B108
    behaviour._call_failed = False
    behaviour._fetch_status = FetchStatus.NONE
    behaviour._creators_iterator = iter([])
    behaviour._current_market = ""
    behaviour._current_creators = []
    # Apply overrides
    for key, val in overrides.items():
        setattr(behaviour, key, val)
    return behaviour


def _make_bet(**overrides: Any) -> Bet:
    """Create a Bet instance with sensible defaults."""
    defaults: Dict[str, Any] = dict(
        id="bet1",
        market="polymarket",
        title="Test?",
        collateralToken="0xtoken",
        creator="0xcreator",
        fee=0,
        openingTimestamp=9999999999,
        outcomeSlotCount=2,
        outcomeTokenAmounts=[100, 200],
        outcomeTokenMarginalPrices=[0.5, 0.5],
        outcomes=["Yes", "No"],
        scaledLiquidityMeasure=10.0,
    )
    defaults.update(overrides)
    return Bet(**defaults)


def _exhaust_gen(gen: Generator) -> Any:
    """Exhaust a generator, sending None on each yield, and return the final value."""
    result = None
    try:
        next(gen)
        while True:
            gen.send(None)
    except StopIteration as exc:
        result = exc.value
    return result


def _make_valid_market(**overrides: Any) -> Dict[str, Any]:
    """Create a valid market dict for _fetch_markets_from_polymarket processing."""
    defaults: Dict[str, Any] = dict(
        id="market1",
        question="Will Tesla stock go up?",
        conditionId="0xcondition123",
        outcomes=json.dumps(["Yes", "No"]),
        outcomePrices=json.dumps(["0.6", "0.4"]),
        clobTokenIds=json.dumps(["token1", "token2"]),
        endDate="2030-01-01T00:00:00Z",
        liquidity="1000.0",
        closed=False,
        submitted_by="0xsubmitter",
        category_valid=True,
    )
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Tests for module-level constants
# ===========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_usdc_e_polygon(self) -> None:
        """USDC.e is kept as wrap source address."""
        assert USDC_E_POLYGON == "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    def test_pusd_polygon(self) -> None:
        """Check pUSD is the v2 collateral."""
        assert PUSD_POLYGON == "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"

    def test_zero_address(self) -> None:
        """Test ZERO_ADDRESS constant."""
        assert ZERO_ADDRESS == "0x0000000000000000000000000000000000000000"

    def test_usdc_decimals(self) -> None:
        """Test USDC_DECIMALS constant."""
        assert USDC_DECIMALS == 10**6

    def test_extreme_price_threshold(self) -> None:
        """Test EXTREME_PRICE_THRESHOLD constant."""
        assert EXTREME_PRICE_THRESHOLD == 0.99

    def test_polymarket_category_keywords_is_dict(self) -> None:
        """Test POLYMARKET_CATEGORY_KEYWORDS is a non-empty dict."""
        assert isinstance(POLYMARKET_CATEGORY_KEYWORDS, dict)
        assert len(POLYMARKET_CATEGORY_KEYWORDS) > 0

    def test_polymarket_category_keywords_values_are_lists(self) -> None:
        """Test that each category has a non-empty list of string keywords."""
        for category, keywords in POLYMARKET_CATEGORY_KEYWORDS.items():
            assert isinstance(keywords, list), f"{category} value is not a list"
            assert len(keywords) > 0, f"{category} has empty keyword list"
            for kw in keywords:
                assert isinstance(kw, str), f"Keyword {kw} in {category} is not str"


# ===========================================================================
# Tests for _requeue_all_bets
# ===========================================================================


class TestRequeueAllBets:
    """Tests for _requeue_all_bets."""

    def test_requeue_all_bets_empty(self) -> None:
        """Test _requeue_all_bets with no bets."""
        behaviour = _make_behaviour()
        behaviour._requeue_all_bets()
        assert behaviour.bets == []

    def test_requeue_all_bets_moves_to_fresh(self) -> None:
        """Test _requeue_all_bets moves all non-expired bets to FRESH."""
        bet1 = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)
        bet2 = _make_bet(id="b2", queue_status=QueueStatus.TO_PROCESS)
        behaviour = _make_behaviour(bets=[bet1, bet2])
        behaviour._requeue_all_bets()
        assert bet1.queue_status == QueueStatus.FRESH
        assert bet2.queue_status == QueueStatus.FRESH

    def test_requeue_all_bets_expired_stays(self) -> None:
        """Test _requeue_all_bets doesn't change EXPIRED bets (move_to_fresh returns self)."""
        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.EXPIRED
        behaviour = _make_behaviour(bets=[bet])
        behaviour._requeue_all_bets()
        # EXPIRED.move_to_fresh() returns EXPIRED per the QueueStatus implementation
        assert bet.queue_status == QueueStatus.EXPIRED


# ===========================================================================
# Tests for _requeue_bets_for_selling
# ===========================================================================


class TestRequeueBetsForSelling:
    """Tests for _requeue_bets_for_selling."""

    def _setup_behaviour(self, bets: List[Bet]) -> PolymarketFetchMarketBehaviour:
        """Set up a behaviour with mocked params for selling tests."""
        behaviour = _make_behaviour(bets=bets)
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 3600
        type(behaviour).synced_time = PropertyMock(return_value=5000000000)  # type: ignore[method-assign]
        return behaviour

    def test_requeue_bets_for_selling_no_bets(self) -> None:  # type: ignore[method-assign]
        """Test _requeue_bets_for_selling with empty list."""
        behaviour = self._setup_behaviour([])
        behaviour._requeue_bets_for_selling()
        assert behaviour.bets == []

    def test_requeue_bet_eligible_for_selling(self) -> None:
        """Test a bet that meets all selling conditions is requeued."""
        bet = _make_bet(
            id="b1",
            openingTimestamp=4999999800,  # is_ready_to_sell will check current_ts > (opening - margin) + DAY_IN_SECONDS
            queue_status=QueueStatus.PROCESSED,
        )
        bet.investments = {"Yes": [100], "No": []}
        bet.last_processed_sell_check = 0

        behaviour = self._setup_behaviour([bet])

        # Mock is_ready_to_sell directly
        bet.is_ready_to_sell = MagicMock(return_value=True)  # type: ignore[method-assign]

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.FRESH  # type: ignore[method-assign]

    def test_not_ready_to_sell(self) -> None:
        """Test a bet that is not ready to sell is NOT requeued."""
        bet = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)
        bet.investments = {"Yes": [100], "No": []}
        bet.last_processed_sell_check = 0
        bet.is_ready_to_sell = MagicMock(return_value=False)  # type: ignore[method-assign]

        behaviour = self._setup_behaviour([bet])
        behaviour._requeue_bets_for_selling()  # type: ignore[method-assign]
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_expired_bet_not_requeued(self) -> None:
        """Test an expired bet is NOT requeued."""
        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.EXPIRED
        bet.investments = {"Yes": [100], "No": []}
        bet.last_processed_sell_check = 0
        bet.is_ready_to_sell = MagicMock(return_value=True)  # type: ignore[method-assign]

        behaviour = self._setup_behaviour([bet])
        behaviour._requeue_bets_for_selling()  # type: ignore[method-assign]
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_zero_invested_amount_not_requeued(self) -> None:
        """Test a bet with zero invested amount is NOT requeued."""
        bet = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)
        bet.investments = {"Yes": [], "No": []}
        bet.last_processed_sell_check = 0
        bet.is_ready_to_sell = MagicMock(return_value=True)  # type: ignore[method-assign]

        behaviour = self._setup_behaviour([bet])
        behaviour._requeue_bets_for_selling()  # type: ignore[method-assign]
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_recent_sell_check_not_requeued(self) -> None:
        """Test a bet with recent sell check is NOT requeued."""
        bet = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)
        bet.investments = {"Yes": [100], "No": []}
        # last_processed_sell_check is recent (within sell_check_interval)
        bet.last_processed_sell_check = (
            5000000000 - 100
        )  # 100 seconds ago, less than 3600
        bet.is_ready_to_sell = MagicMock(return_value=True)  # type: ignore[method-assign]

        behaviour = self._setup_behaviour([bet])
        behaviour._requeue_bets_for_selling()  # type: ignore[method-assign]
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_last_processed_sell_check_is_zero(self) -> None:
        """Test bet with last_processed_sell_check == 0 (falsy) is requeued."""
        bet = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)
        bet.investments = {"Yes": [100], "No": []}
        bet.last_processed_sell_check = 0
        bet.is_ready_to_sell = MagicMock(return_value=True)  # type: ignore[method-assign]

        behaviour = self._setup_behaviour([bet])
        behaviour._requeue_bets_for_selling()  # type: ignore[method-assign]
        assert bet.queue_status == QueueStatus.FRESH


# ===========================================================================
# Tests for _blacklist_expired_bets
# ===========================================================================


class TestBlacklistExpiredBets:
    """Tests for _blacklist_expired_bets."""

    def _setup(self, bets: List[Bet]) -> PolymarketFetchMarketBehaviour:
        """Set up a behaviour for blacklist tests."""
        behaviour = _make_behaviour(bets=bets)
        behaviour.context.params.opening_margin = 1000
        type(behaviour).synced_time = PropertyMock(return_value=5000000000)  # type: ignore[method-assign]
        return behaviour

    def test_blacklist_expired_opening_margin(self) -> None:  # type: ignore[method-assign]
        """Test bet is blacklisted when synced_time >= openingTimestamp - opening_margin."""
        bet = _make_bet(id="b1", openingTimestamp=5000000500)  # within margin
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED
        assert bet.outcomes is None

    def test_not_blacklisted_when_far_future(self) -> None:
        """Test bet is NOT blacklisted when well within margin."""
        bet = _make_bet(id="b1", openingTimestamp=9999999999)
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status != QueueStatus.EXPIRED

    def test_blacklist_extreme_price_high(self) -> None:
        """Test bet is blacklisted when any price >= EXTREME_PRICE_THRESHOLD."""
        bet = _make_bet(
            id="b1",
            openingTimestamp=9999999999,
            outcomeTokenMarginalPrices=[0.99, 0.01],
        )
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_blacklist_extreme_price_second_outcome(self) -> None:
        """Test bet is blacklisted when second outcome price is extreme."""
        bet = _make_bet(
            id="b1",
            openingTimestamp=9999999999,
            outcomeTokenMarginalPrices=[0.01, 0.995],
        )
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_not_blacklisted_normal_prices(self) -> None:
        """Test bet is NOT blacklisted with normal prices."""
        bet = _make_bet(
            id="b1",
            openingTimestamp=9999999999,
            outcomeTokenMarginalPrices=[0.5, 0.5],
        )
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status != QueueStatus.EXPIRED

    def test_not_blacklisted_non_binary(self) -> None:
        """Test non-binary market (len != 2) skips extreme price check."""
        bet = _make_bet(
            id="b1",
            openingTimestamp=9999999999,
            outcomeSlotCount=3,
            outcomes=["A", "B", "C"],
            outcomeTokenAmounts=[100, 100, 100],
            outcomeTokenMarginalPrices=[0.99, 0.005, 0.005],
        )
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status != QueueStatus.EXPIRED

    def test_blacklist_empty_bets(self) -> None:
        """Test blacklisting with no bets does nothing."""
        behaviour = self._setup([])
        behaviour._blacklist_expired_bets()
        assert behaviour.bets == []

    def test_opening_margin_expired_takes_precedence_over_extreme_price(self) -> None:
        """Test that opening margin expiration hits `continue` before extreme price check."""
        bet = _make_bet(
            id="b1",
            openingTimestamp=5000000500,  # within margin
            outcomeTokenMarginalPrices=[0.99, 0.01],  # also extreme
        )
        behaviour = self._setup([bet])
        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED


# ===========================================================================
# Tests for _validate_market_category (static)
# ===========================================================================


class TestValidateMarketCategory:
    """Tests for _validate_market_category."""

    def test_valid_technology_match(self) -> None:
        """Test matching a technology keyword."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "Will AI take over jobs?", "technology"
            )
            is True
        )

    def test_valid_politics_match(self) -> None:
        """Test matching a politics keyword."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "Will Biden win the election?", "politics"
            )
            is True
        )

    def test_no_match(self) -> None:
        """Test when title doesn't contain any category keywords."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "Will it rain tomorrow?", "technology"
            )
            is False
        )

    def test_invalid_category(self) -> None:
        """Test with a category that doesn't exist in POLYMARKET_CATEGORY_KEYWORDS."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "Some question", "nonexistent_category"
            )
            is False
        )

    def test_non_string_title(self) -> None:
        """Test with a non-string title."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                123, "technology"  # type: ignore[arg-type]
            )
            is False
        )

    def test_none_title(self) -> None:
        """Test with None title."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                None, "technology"  # type: ignore[arg-type]
            )
            is False
        )

    def test_case_insensitive_match(self) -> None:
        """Test that matching is case-insensitive."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "APPLE is dominating the market", "technology"
            )
            is True
        )

    def test_word_boundary_match(self) -> None:
        """Test that keywords use word boundaries."""
        # "ai" should match as a whole word
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "Will AI become sentient?", "technology"
            )
            is True
        )

    def test_partial_word_no_match(self) -> None:
        """Test that partial word matches do not count."""
        # "ai" should not match inside "chair"
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category(
                "Will the chair break?", "technology"
            )
            is False
        )

    def test_empty_title(self) -> None:
        """Test with empty title."""
        assert (
            PolymarketFetchMarketBehaviour._validate_market_category("", "technology")
            is False
        )


# ===========================================================================
# Tests for _validate_markets_by_category
# ===========================================================================


class TestValidateMarketsByCategory:
    """Tests for _validate_markets_by_category."""

    def test_validates_markets_correctly(self) -> None:
        """Test that markets are validated and marked correctly."""
        behaviour = _make_behaviour()
        markets_by_category = {
            "technology": [
                {"question": "Will AI improve?"},
                {"question": "Will cats fly?"},
            ]
        }
        result = behaviour._validate_markets_by_category(markets_by_category)
        assert result["technology"][0]["category_valid"] is True
        assert result["technology"][1]["category_valid"] is False

    def test_empty_categories(self) -> None:
        """Test with empty input."""
        behaviour = _make_behaviour()
        result = behaviour._validate_markets_by_category({})
        assert result == {}

    def test_multiple_categories(self) -> None:
        """Test with multiple categories."""
        behaviour = _make_behaviour()
        markets_by_category = {
            "technology": [{"question": "Will Google expand?"}],
            "politics": [{"question": "Will Trump win?"}],
        }
        result = behaviour._validate_markets_by_category(markets_by_category)
        assert result["technology"][0]["category_valid"] is True
        assert result["politics"][0]["category_valid"] is True

    def test_missing_question_key(self) -> None:
        """Test a market without a question key."""
        behaviour = _make_behaviour()
        markets_by_category = {"technology": [{"title": "no question key"}]}
        result = behaviour._validate_markets_by_category(markets_by_category)
        # question defaults to "" via .get
        assert result["technology"][0]["category_valid"] is False

    def test_logger_called(self) -> None:
        """Test that logger is called with summary info."""
        behaviour = _make_behaviour()
        markets_by_category = {
            "technology": [{"question": "Will AI improve?"}],
        }
        behaviour._validate_markets_by_category(markets_by_category)
        assert behaviour.context.logger.info.called


# ===========================================================================
# Tests for _deduplicate_markets
# ===========================================================================


class TestDeduplicateMarkets:
    """Tests for _deduplicate_markets."""

    def test_no_duplicates(self) -> None:
        """Test deduplication when there are no duplicates."""
        behaviour = _make_behaviour()
        markets = {
            "technology": [{"id": "m1", "category_valid": True}],
            "politics": [{"id": "m2", "category_valid": True}],
        }
        result = behaviour._deduplicate_markets(markets)
        total = sum(len(v) for v in result.values())
        assert total == 2

    def test_duplicate_prefers_valid(self) -> None:
        """Test deduplication prefers category-valid markets."""
        behaviour = _make_behaviour()
        markets = {
            "technology": [{"id": "m1", "category_valid": False}],
            "politics": [{"id": "m1", "category_valid": True}],
        }
        result = behaviour._deduplicate_markets(markets)
        total = sum(len(v) for v in result.values())
        assert total == 1
        # The surviving market should be in politics (where it's valid)
        assert "politics" in result
        assert result["politics"][0]["category_valid"] is True

    def test_duplicate_all_invalid_keeps_first(self) -> None:
        """Test deduplication with all-invalid duplicates keeps first occurrence."""
        behaviour = _make_behaviour()
        markets = {
            "technology": [{"id": "m1", "category_valid": False}],
            "politics": [{"id": "m1", "category_valid": False}],
        }
        result = behaviour._deduplicate_markets(markets)
        total = sum(len(v) for v in result.values())
        assert total == 1

    def test_market_without_id_skipped(self) -> None:
        """Test that markets without an id are skipped."""
        behaviour = _make_behaviour()
        markets = {
            "technology": [{"category_valid": True}],  # no id
        }
        result = behaviour._deduplicate_markets(markets)
        total = sum(len(v) for v in result.values())
        assert total == 0

    def test_empty_input(self) -> None:
        """Test with empty input."""
        behaviour = _make_behaviour()
        result = behaviour._deduplicate_markets({})
        assert result == {}


# ===========================================================================
# Tests for review_bets_for_selling property
# ===========================================================================


class TestReviewBetsForSelling:
    """Tests for review_bets_for_selling property."""

    def test_delegates_to_synchronized_data(self) -> None:
        """Test that review_bets_for_selling delegates to synchronized_data."""
        behaviour = _make_behaviour()
        mock_synced = MagicMock()
        mock_synced.review_bets_for_selling = True
        type(behaviour).synchronized_data = PropertyMock(return_value=mock_synced)  # type: ignore[method-assign]
        assert behaviour.review_bets_for_selling is True

    def test_returns_false(self) -> None:  # type: ignore[method-assign]
        """Test that review_bets_for_selling returns False when synced data says False."""
        behaviour = _make_behaviour()
        mock_synced = MagicMock()
        mock_synced.review_bets_for_selling = False
        type(behaviour).synchronized_data = PropertyMock(return_value=mock_synced)  # type: ignore[method-assign]
        assert behaviour.review_bets_for_selling is False


# type: ignore[method-assign]
# ===========================================================================
# Tests for setup
# ===========================================================================


class TestSetup:
    """Tests for setup."""

    def _setup_behaviour(self) -> PolymarketFetchMarketBehaviour:
        """Create a behaviour with mocked dependencies for setup."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        behaviour._requeue_all_bets = MagicMock()  # type: ignore[method-assign]
        behaviour._blacklist_expired_bets = MagicMock()  # type: ignore[method-assign]
        mock_synced = MagicMock()  # type: ignore[method-assign]
        type(behaviour).synchronized_data = PropertyMock(return_value=mock_synced)  # type: ignore[method-assign]
        return behaviour  # type: ignore[method-assign]

    def test_setup_reads_bets(self) -> None:  # type: ignore[method-assign]
        """Test that setup calls read_bets."""
        behaviour = self._setup_behaviour()
        behaviour.synchronized_data.is_checkpoint_reached = False  # type: ignore[misc]
        behaviour.params.use_multi_bets_mode = False
        behaviour.setup()
        behaviour.read_bets.assert_called_once()  # type: ignore[attr-defined, misc]

    def test_setup_requeues_on_checkpoint_multi_mode(self) -> None:
        """Test that setup requeues all bets when checkpoint is reached in multi-bets mode."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.synchronized_data.is_checkpoint_reached = True  # type: ignore[misc]
        behaviour.params.use_multi_bets_mode = True
        behaviour.setup()
        behaviour._requeue_all_bets.assert_called_once()  # type: ignore[attr-defined, misc]

    def test_setup_does_not_requeue_when_not_checkpoint(self) -> None:
        """Test that setup does NOT requeue when checkpoint is not reached."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.synchronized_data.is_checkpoint_reached = False  # type: ignore[misc]
        behaviour.params.use_multi_bets_mode = True
        behaviour.setup()
        behaviour._requeue_all_bets.assert_not_called()  # type: ignore[attr-defined, misc]

    def test_setup_does_not_requeue_when_not_multi_mode(self) -> None:
        """Test that setup does NOT requeue when not in multi-bets mode."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.synchronized_data.is_checkpoint_reached = True  # type: ignore[misc]
        behaviour.params.use_multi_bets_mode = False
        behaviour.setup()
        behaviour._requeue_all_bets.assert_not_called()  # type: ignore[attr-defined, misc]

    def test_setup_blacklists_expired_when_bets_exist(self) -> None:
        """Test that setup blacklists expired bets when bets are not empty."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.synchronized_data.is_checkpoint_reached = False  # type: ignore[misc]
        behaviour.params.use_multi_bets_mode = False
        behaviour.bets = [_make_bet()]
        behaviour.setup()  # type: ignore[misc]
        behaviour._blacklist_expired_bets.assert_called_once()  # type: ignore[attr-defined]

    def test_setup_does_not_blacklist_when_no_bets(self) -> None:
        """Test that setup does NOT blacklist when bets are empty."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.synchronized_data.is_checkpoint_reached = False  # type: ignore[misc]
        behaviour.params.use_multi_bets_mode = False
        behaviour.bets = []
        behaviour.setup()  # type: ignore[misc]
        behaviour._blacklist_expired_bets.assert_not_called()  # type: ignore[attr-defined]


# ===========================================================================  # type: ignore[attr-defined]
# Tests for get_bet_idx
# ===========================================================================


class TestGetBetIdx:
    """Tests for get_bet_idx."""

    def test_found(self) -> None:
        """Test finding a bet by id."""
        bet1 = _make_bet(id="b1")
        bet2 = _make_bet(id="b2")
        behaviour = _make_behaviour(bets=[bet1, bet2])
        assert behaviour.get_bet_idx("b2") == 1

    def test_not_found(self) -> None:
        """Test returning None when bet is not found."""
        bet1 = _make_bet(id="b1")
        behaviour = _make_behaviour(bets=[bet1])
        assert behaviour.get_bet_idx("nonexistent") is None

    def test_empty_bets(self) -> None:
        """Test with empty bets list."""
        behaviour = _make_behaviour()
        assert behaviour.get_bet_idx("anything") is None


# ===========================================================================
# Tests for _process_chunk
# ===========================================================================


class TestProcessChunk:
    """Tests for _process_chunk."""

    def test_none_chunk(self) -> None:
        """Test that None chunk is a no-op."""
        behaviour = _make_behaviour()
        behaviour._current_market = "polymarket"
        behaviour._process_chunk(None)
        assert behaviour.bets == []

    def test_new_bet_added(self) -> None:
        """Test that a new bet is appended."""
        behaviour = _make_behaviour()
        behaviour._current_market = "polymarket"
        raw_bet = dict(
            id="b1",
            title="Test?",
            collateralToken="0xtoken",
            creator="0xcreator",
            fee=0,
            openingTimestamp=9999999999,
            outcomeSlotCount=2,
            outcomeTokenAmounts=[100, 200],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            outcomes=["Yes", "No"],
            scaledLiquidityMeasure=10.0,
        )
        behaviour._process_chunk([raw_bet])
        assert len(behaviour.bets) == 1
        assert behaviour.bets[0].id == "b1"

    def test_existing_bet_updated(self) -> None:
        """Test that an existing bet gets its market info updated."""
        existing_bet = _make_bet(
            id="b1",
            scaledLiquidityMeasure=5.0,
        )
        behaviour = _make_behaviour(bets=[existing_bet])
        behaviour._current_market = "polymarket"
        raw_bet = dict(
            id="b1",
            title="Test?",
            collateralToken="0xtoken",
            creator="0xcreator",
            fee=0,
            openingTimestamp=9999999999,
            outcomeSlotCount=2,
            outcomeTokenAmounts=[300, 400],
            outcomeTokenMarginalPrices=[0.6, 0.4],
            outcomes=["Yes", "No"],
            scaledLiquidityMeasure=20.0,
        )
        behaviour._process_chunk([raw_bet])
        assert len(behaviour.bets) == 1
        assert behaviour.bets[0].scaledLiquidityMeasure == 20.0

    def test_existing_bet_with_empty_market_gets_backfilled(self) -> None:
        """Test that an existing bet with empty market gets backfilled."""
        existing_bet = _make_bet(id="b1", market="")
        behaviour = _make_behaviour(bets=[existing_bet])
        behaviour._current_market = "polymarket_client"
        raw_bet = dict(
            id="b1",
            title="Test?",
            collateralToken="0xtoken",
            creator="0xcreator",
            fee=0,
            openingTimestamp=9999999999,
            outcomeSlotCount=2,
            outcomeTokenAmounts=[300, 400],
            outcomeTokenMarginalPrices=[0.6, 0.4],
            outcomes=["Yes", "No"],
            scaledLiquidityMeasure=20.0,
        )
        behaviour._process_chunk([raw_bet])
        assert behaviour.bets[0].market == "polymarket_client"


# ===========================================================================
# Tests for _validate_trade
# ===========================================================================


class TestValidateTrade:
    """Tests for _validate_trade."""

    def test_valid_trade(self) -> None:
        """Test a fully valid trade."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": 0,
            "side": "BUY",
            "size": "10.0",
            "price": "0.5",
        }
        assert behaviour._validate_trade(trade) is True

    def test_valid_trade_sell(self) -> None:
        """Test a valid SELL trade."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": 1,
            "side": "SELL",
            "size": "5.0",
            "price": "0.3",
        }
        assert behaviour._validate_trade(trade) is True

    def test_missing_condition_id(self) -> None:
        """Test trade missing conditionId."""
        behaviour = _make_behaviour()
        trade = {"outcomeIndex": 0, "side": "BUY", "size": "10.0", "price": "0.5"}
        assert behaviour._validate_trade(trade) is False

    def test_missing_outcome_index(self) -> None:
        """Test trade missing outcomeIndex."""
        behaviour = _make_behaviour()
        trade = {"conditionId": "0xcond", "side": "BUY", "size": "10.0", "price": "0.5"}
        assert behaviour._validate_trade(trade) is False

    def test_invalid_side(self) -> None:
        """Test trade with invalid side."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": 0,
            "side": "HOLD",
            "size": "10.0",
            "price": "0.5",
        }
        assert behaviour._validate_trade(trade) is False

    def test_missing_size(self) -> None:
        """Test trade missing size."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": 0,
            "side": "BUY",
            "price": "0.5",
        }
        assert behaviour._validate_trade(trade) is False

    def test_missing_price(self) -> None:
        """Test trade missing price."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": 0,
            "side": "BUY",
            "size": "10.0",
        }
        assert behaviour._validate_trade(trade) is False

    def test_none_condition_id(self) -> None:
        """Test trade with explicit None conditionId."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": None,
            "outcomeIndex": 0,
            "side": "BUY",
            "size": "10.0",
            "price": "0.5",
        }
        assert behaviour._validate_trade(trade) is False

    def test_none_outcome_index(self) -> None:
        """Test trade with explicit None outcomeIndex."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": None,
            "side": "BUY",
            "size": "10.0",
            "price": "0.5",
        }
        assert behaviour._validate_trade(trade) is False

    def test_none_size_and_price(self) -> None:
        """Test trade with None size and price (both None)."""
        behaviour = _make_behaviour()
        trade = {
            "conditionId": "0xcond",
            "outcomeIndex": 0,
            "side": "BUY",
            "size": None,
            "price": None,
        }
        assert behaviour._validate_trade(trade) is False


# ===========================================================================
# Tests for _calculate_trade_usdc_amount
# ===========================================================================


class TestCalculateTradeUsdcAmount:
    """Tests for _calculate_trade_usdc_amount."""

    def test_valid_calculation(self) -> None:
        """Test valid float multiplication."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount("10.0", "0.5")
        assert result == 5.0

    def test_integer_strings(self) -> None:
        """Test with integer string values."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount("100", "2")
        assert result == 200.0

    def test_invalid_size(self) -> None:
        """Test with non-numeric size."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount("abc", "0.5")
        assert result is None

    def test_invalid_price(self) -> None:
        """Test with non-numeric price."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount("10.0", "xyz")
        assert result is None

    def test_none_size(self) -> None:
        """Test with None size."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount(None, "0.5")
        assert result is None

    def test_none_price(self) -> None:
        """Test with None price."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount("10.0", None)
        assert result is None


# ===========================================================================
# Tests for _process_and_group_trades
# ===========================================================================


class TestProcessAndGroupTrades:
    """Tests for _process_and_group_trades."""

    def test_groups_correctly(self) -> None:
        """Test correct grouping by condition_id and outcome_index."""
        behaviour = _make_behaviour()
        trades = [
            {
                "conditionId": "c1",
                "outcomeIndex": 0,
                "side": "BUY",
                "size": "10",
                "price": "0.5",
            },
            {
                "conditionId": "c1",
                "outcomeIndex": 1,
                "side": "SELL",
                "size": "5",
                "price": "0.3",
            },
            {
                "conditionId": "c2",
                "outcomeIndex": 0,
                "side": "BUY",
                "size": "20",
                "price": "0.7",
            },
        ]
        result = behaviour._process_and_group_trades(trades)
        assert "c1" in result
        assert 0 in result["c1"]
        assert 1 in result["c1"]
        assert "c2" in result
        assert len(result["c1"][0]) == 1
        assert result["c1"][0][0]["usdc_amount"] == 5.0
        assert result["c1"][1][0]["usdc_amount"] == 1.5
        assert result["c2"][0][0]["usdc_amount"] == 14.0

    def test_invalid_trade_skipped(self) -> None:
        """Test invalid trades are skipped."""
        behaviour = _make_behaviour()
        trades = [
            {
                "conditionId": "c1",
                "side": "BUY",
                "size": "10",
                "price": "0.5",
            },  # missing outcomeIndex
        ]
        result = behaviour._process_and_group_trades(trades)
        assert len(result) == 0

    def test_bad_amount_skipped(self) -> None:
        """Test trades with unconvertible amounts are skipped."""
        behaviour = _make_behaviour()
        trades = [
            {
                "conditionId": "c1",
                "outcomeIndex": 0,
                "side": "BUY",
                "size": "abc",
                "price": "0.5",
            },
        ]
        result = behaviour._process_and_group_trades(trades)
        assert len(result) == 0

    def test_empty_trades(self) -> None:
        """Test with empty trades list."""
        behaviour = _make_behaviour()
        result = behaviour._process_and_group_trades([])
        assert len(result) == 0


# ===========================================================================
# Tests for _should_skip_bet
# ===========================================================================


class TestShouldSkipBet:
    """Tests for _should_skip_bet."""

    def test_expired_bet_skipped(self) -> None:
        """Test expired bet is skipped."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.EXPIRED
        assert behaviour._should_skip_bet(bet) is True

    def test_no_condition_id_skipped(self) -> None:
        """Test bet without condition_id is skipped."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = None
        assert behaviour._should_skip_bet(bet) is True

    def test_valid_bet_not_skipped(self) -> None:
        """Test a valid bet is NOT skipped."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        assert behaviour._should_skip_bet(bet) is False


# ===========================================================================
# Tests for _convert_usdc_to_base_units
# ===========================================================================


class TestConvertUsdcToBaseUnits:
    """Tests for _convert_usdc_to_base_units."""

    def test_valid_conversion(self) -> None:
        """Test valid conversion."""
        behaviour = _make_behaviour()
        result = behaviour._convert_usdc_to_base_units(1.5)
        assert result == int(1.5 * USDC_DECIMALS)

    def test_zero(self) -> None:
        """Test zero conversion."""
        behaviour = _make_behaviour()
        result = behaviour._convert_usdc_to_base_units(0.0)
        assert result == 0

    def test_invalid_input(self) -> None:
        """Test with invalid input that causes TypeError."""
        behaviour = _make_behaviour()
        result = behaviour._convert_usdc_to_base_units("not_a_number")  # type: ignore[arg-type]
        # float * int should still work for strings, but int() of result might fail
        # Actually "not_a_number" * USDC_DECIMALS will raise TypeError
        assert result is None


# ===========================================================================
# Tests for _calculate_outcome_investment
# ===========================================================================


class TestCalculateOutcomeInvestment:
    """Tests for _calculate_outcome_investment."""

    def test_sum_buy_trades(self) -> None:
        """Test summing only BUY trades."""
        behaviour = _make_behaviour()
        trades = [
            {"side": "BUY", "usdc_amount": 10.0},
            {"side": "BUY", "usdc_amount": 20.0},
            {"side": "SELL", "usdc_amount": 5.0},
        ]
        result = behaviour._calculate_outcome_investment(trades)
        assert result == 30.0

    def test_no_buy_trades(self) -> None:
        """Test with no BUY trades."""
        behaviour = _make_behaviour()
        trades = [
            {"side": "SELL", "usdc_amount": 5.0},
        ]
        result = behaviour._calculate_outcome_investment(trades)
        assert result == 0.0

    def test_empty_trade_list(self) -> None:
        """Test with empty trade list."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_outcome_investment([])
        assert result == 0.0


# ===========================================================================
# Tests for _replace_with_existing_investments_if_empty
# ===========================================================================


class TestReplaceWithExistingInvestmentsIfEmpty:
    """Tests for _replace_with_existing_investments_if_empty."""

    def test_replaces_when_empty(self) -> None:
        """Test replacement when new investments are empty."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.investments = {"Yes": [], "No": []}
        existing = {"Yes": [100], "No": [200]}
        behaviour._replace_with_existing_investments_if_empty(bet, existing)
        assert bet.investments == existing

    def test_does_not_replace_when_has_yes(self) -> None:
        """Test no replacement when bet has yes investments."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.investments = {"Yes": [50], "No": []}
        existing = {"Yes": [100], "No": [200]}
        behaviour._replace_with_existing_investments_if_empty(bet, existing)
        assert bet.investments == {"Yes": [50], "No": []}

    def test_does_not_replace_when_has_no(self) -> None:
        """Test no replacement when bet has no investments."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.investments = {"Yes": [], "No": [50]}
        existing = {"Yes": [100], "No": [200]}
        behaviour._replace_with_existing_investments_if_empty(bet, existing)
        assert bet.investments == {"Yes": [], "No": [50]}


# ===========================================================================
# Tests for _update_single_bet_investments
# ===========================================================================


class TestUpdateSingleBetInvestments:
    """Tests for _update_single_bet_investments."""

    def test_no_condition_id(self) -> None:
        """Test when bet has no condition_id."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = None
        bet.investments = {"Yes": [100], "No": [200]}
        behaviour._update_single_bet_investments(bet, {})
        # Should retain existing investments since new ones are empty
        assert bet.investments == {"Yes": [100], "No": [200]}

    def test_no_matching_trades(self) -> None:
        """Test when there are no matching trades for the bet."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xmissing"
        bet.investments = {"Yes": [100], "No": []}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xother": {0: [{"side": "BUY", "usdc_amount": 10.0}]}
        }
        behaviour._update_single_bet_investments(bet, trades_map)
        assert bet.investments == {"Yes": [100], "No": []}

    def test_bet_with_no_outcomes(self) -> None:
        """Test when bet outcomes is None, the method logs and calls replace fallback."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [100], "No": [200]}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {0: [{"side": "BUY", "usdc_amount": 10.0}]}
        }
        # Set outcomes to None after construction so existing_investments is captured
        # before reset_investments is called. We must mock reset_investments and
        # _replace_with_existing_investments_if_empty to avoid the ValueError.
        bet.outcomes = None
        bet.processed_timestamp = sys.maxsize
        bet.queue_status = QueueStatus.EXPIRED

        # Mock the methods that would fail when outcomes is None
        behaviour._replace_with_existing_investments_if_empty = MagicMock()  # type: ignore[method-assign]

        behaviour._update_single_bet_investments(bet, trades_map)
        # Verify the warning was logged and replace fallback was called  # type: ignore[method-assign]
        behaviour.context.logger.warning.assert_called()
        behaviour._replace_with_existing_investments_if_empty.assert_called_once()  # type: ignore[attr-defined]

    def test_outcome_index_out_of_bounds(self) -> None:
        """Test when outcome_index is out of bounds."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [100], "No": []}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {5: [{"side": "BUY", "usdc_amount": 10.0}]}  # out of bounds
        }
        behaviour._update_single_bet_investments(bet, trades_map)
        # Should retain existing investments since new are empty
        assert bet.investments == {"Yes": [100], "No": []}

    def test_negative_outcome_index(self) -> None:
        """Test when outcome_index is negative."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [100], "No": []}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {-1: [{"side": "BUY", "usdc_amount": 10.0}]}
        }
        behaviour._update_single_bet_investments(bet, trades_map)
        assert bet.investments == {"Yes": [100], "No": []}

    def test_successful_update(self) -> None:
        """Test a successful investment update."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [100], "No": []}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {
                0: [
                    {"side": "BUY", "usdc_amount": 10.0},
                    {"side": "BUY", "usdc_amount": 5.0},
                    {"side": "SELL", "usdc_amount": 3.0},
                ],
            }
        }
        behaviour._update_single_bet_investments(bet, trades_map)
        # Total BUY = 15.0 USDC -> 15_000_000 base units
        assert len(bet.investments["Yes"]) == 1
        assert bet.investments["Yes"][0] == int(15.0 * USDC_DECIMALS)

    def test_zero_investment_not_appended(self) -> None:
        """Test that zero total investment is not appended."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [100], "No": []}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {
                0: [
                    {"side": "SELL", "usdc_amount": 10.0},  # only SELL trades
                ],
            }
        }
        behaviour._update_single_bet_investments(bet, trades_map)
        # Total BUY = 0, so nothing appended, new investments are empty
        # Should retain existing
        assert bet.investments == {"Yes": [100], "No": []}

    def test_convert_usdc_fails_continues(self) -> None:
        """Test that when _convert_usdc_to_base_units returns None, we continue."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [100], "No": []}

        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {
                0: [{"side": "BUY", "usdc_amount": 10.0}],
            }
        }

        with patch.object(behaviour, "_convert_usdc_to_base_units", return_value=None):
            behaviour._update_single_bet_investments(bet, trades_map)

        # Conversion failed, no new investments appended, should retain existing
        assert bet.investments == {"Yes": [100], "No": []}


# ===========================================================================
# Tests for _update_all_bets_investments
# ===========================================================================


class TestUpdateAllBetsInvestments:
    """Tests for _update_all_bets_investments."""

    def test_skips_and_updates(self) -> None:
        """Test that skip and update logic works together."""
        behaviour = _make_behaviour()
        bet1 = _make_bet(id="b1")
        bet1.queue_status = QueueStatus.EXPIRED  # should be skipped
        bet2 = _make_bet(id="b2")
        bet2.condition_id = "0xcond2"
        behaviour.bets = [bet1, bet2]

        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond2": {
                0: [{"side": "BUY", "usdc_amount": 10.0}],
            }
        }
        behaviour._update_all_bets_investments(trades_map)
        # bet2 should have been updated
        assert len(bet2.investments["Yes"]) == 1

    def test_empty_bets_list(self) -> None:
        """Test with empty bets list."""
        behaviour = _make_behaviour()
        behaviour._update_all_bets_investments({})
        assert behaviour.bets == []


# ===========================================================================
# Tests for _bet_freshness_check_and_update
# ===========================================================================


class TestBetFreshnessCheckAndUpdate:
    """Tests for _bet_freshness_check_and_update."""

    def test_single_bets_mode_fresh_to_process(self) -> None:
        """Test single-bets mode moves FRESH to TO_PROCESS."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = False
        bet = _make_bet(id="b1", queue_status=QueueStatus.FRESH)
        behaviour.bets = [bet]
        behaviour._bet_freshness_check_and_update()
        assert bet.queue_status == QueueStatus.TO_PROCESS

    def test_single_bets_mode_non_fresh_stays(self) -> None:
        """Test single-bets mode does not change non-FRESH bets."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = False
        bet = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)
        behaviour.bets = [bet]
        behaviour._bet_freshness_check_and_update()
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_multi_bets_mode_all_fresh_moves_to_process(self) -> None:
        """Test multi-bets mode moves all to process when all non-expired are FRESH."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = True
        bet1 = _make_bet(id="b1", queue_status=QueueStatus.FRESH)
        bet2 = _make_bet(id="b2")
        bet2.queue_status = QueueStatus.EXPIRED  # expired is excluded from check
        behaviour.bets = [bet1, bet2]
        behaviour._bet_freshness_check_and_update()
        assert bet1.queue_status == QueueStatus.TO_PROCESS
        # EXPIRED.move_to_process() returns self
        assert bet2.queue_status == QueueStatus.EXPIRED

    def test_multi_bets_mode_not_all_fresh_no_change(self) -> None:
        """Test multi-bets mode does NOT change when not all non-expired are FRESH."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = True
        bet1 = _make_bet(id="b1", queue_status=QueueStatus.FRESH)
        bet2 = _make_bet(id="b2", queue_status=QueueStatus.PROCESSED)
        behaviour.bets = [bet1, bet2]
        behaviour._bet_freshness_check_and_update()
        assert bet1.queue_status == QueueStatus.FRESH
        assert bet2.queue_status == QueueStatus.PROCESSED

    def test_single_bets_mode_returns_early(self) -> None:
        """Test single-bets mode returns after processing without checking multi mode."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = False
        bet1 = _make_bet(id="b1", queue_status=QueueStatus.FRESH)
        bet2 = _make_bet(id="b2", queue_status=QueueStatus.PROCESSED)
        behaviour.bets = [bet1, bet2]
        behaviour._bet_freshness_check_and_update()
        assert bet1.queue_status == QueueStatus.TO_PROCESS
        assert bet2.queue_status == QueueStatus.PROCESSED


# ===========================================================================
# Tests for _fetch_markets_from_polymarket (generator)
# ===========================================================================


class TestFetchMarketsFromPolymarket:
    """Tests for _fetch_markets_from_polymarket."""

    def _setup_behaviour(self) -> PolymarketFetchMarketBehaviour:
        """Set up a behaviour with mocked params."""
        behaviour = _make_behaviour()
        behaviour.context.params.store_path = Path("/tmp")  # nosec B108
        behaviour.send_polymarket_connection_request = MagicMock()  # type: ignore[method-assign]
        return behaviour

    def test_response_none_returns_none(self) -> None:  # type: ignore[method-assign]
        """Test that None response returns None."""
        behaviour = self._setup_behaviour()
        behaviour.send_polymarket_connection_request = _return_gen(None)  # type: ignore[method-assign]
        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type]
        assert result is None  # type: ignore[method-assign]

    def test_response_error_dict_returns_none(self) -> None:  # type: ignore[arg-type]
        """Test that error dict response returns None."""
        behaviour = self._setup_behaviour()
        behaviour.send_polymarket_connection_request = _return_gen({"error": "failed"})  # type: ignore[method-assign]
        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type]
        assert result is None  # type: ignore[method-assign]

    def test_successful_fetch_with_valid_markets(self) -> None:  # type: ignore[arg-type]
        """Test successful fetch with valid markets."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market()
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["id"] == "market1"
        # Polymarket v2: per-bet collateralToken is intentionally blank — the
        # protocol invariant lives in `params.polymarket_collateral_address`.
        assert result[0]["collateralToken"] == ""

    def test_market_missing_outcomes(self) -> None:
        """Test market with empty outcomes is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(outcomes=json.dumps([]))
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_market_mismatched_lengths(self) -> None:
        """Test market with mismatched lengths is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(
            outcomes=json.dumps(["Yes", "No"]),
            outcomePrices=json.dumps(["0.5"]),
        )
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_market_missing_end_date(self) -> None:
        """Test market missing endDate is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(endDate="")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_market_negative_liquidity(self) -> None:
        """Test market with negative liquidity is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(liquidity="-100")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_market_invalid_price_range(self) -> None:
        """Test market with invalid prices is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(outcomePrices=json.dumps(["1.5", "0.4"]))
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_market_missing_condition_id(self) -> None:
        """Test market missing conditionId is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(conditionId="")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_market_missing_question(self) -> None:
        """Test market missing question is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(question="")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_closed_market_blacklisted(self) -> None:
        """Test closed market gets blacklisted (outcomes=None, queue=EXPIRED)."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(closed=True)
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["outcomes"] is None
        assert result[0]["queue_status"] == QueueStatus.EXPIRED

    def test_invalid_category_market_blacklisted(self) -> None:
        """Test market that fails category validation gets blacklisted."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(
            question="Will cats fly?",  # not matching technology keywords
            category_valid=False,
        )
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        # _validate_markets_by_category will set category_valid based on actual check
        # "cats fly" doesn't match technology keywords, so it will be invalid

    def test_market_without_submitted_by_uses_zero_address(self) -> None:
        """Test that markets without submitted_by use ZERO_ADDRESS."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market()
        del market["submitted_by"]
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        assert result[0]["creator"] == ZERO_ADDRESS

    def test_json_decode_error_skips_market(self) -> None:
        """Test that JSON decode error in outcomes is handled."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(outcomes="not valid json {")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_unexpected_exception_skips_market(self) -> None:
        """Test that unexpected exceptions are caught and market is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market()
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        # Patch _validate_markets_by_category to return data that causes an unexpected error
        # We'll mock date_parser.isoparse to raise an unexpected error  # type: ignore[method-assign]
        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.polymarket_fetch_market.date_parser"
        ) as mock_parser:
            mock_parser.isoparse.side_effect = RuntimeError("unexpected")
            gen = behaviour._fetch_markets_from_polymarket()
            result = _exhaust_gen(gen)  # type: ignore[arg-type]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_multiple_categories(self) -> None:
        """Test processing markets from multiple categories."""
        behaviour = self._setup_behaviour()
        market1 = _make_valid_market(id="m1", question="Will Tesla stock go up?")
        market2 = _make_valid_market(id="m2", question="Will Trump win the election?")
        response = {
            "technology": [market1],
            "politics": [market2],
        }
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 2  # type: ignore[arg-type]

    def test_valid_market_has_correct_bet_dict_structure(self) -> None:
        """Test that a valid market produces a correctly structured bet_dict."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(
            id="m1",
            question="Will Tesla stock go up?",
            conditionId="0xcond",
            submitted_by="0xsubmitter",
        )
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        bet_dict = result[0]
        assert bet_dict["id"] == "m1"
        assert bet_dict["title"] == "Will Tesla stock go up?"
        assert bet_dict["category"] == "technology"
        assert bet_dict["condition_id"] == "0xcond"
        assert bet_dict["collateralToken"] == ""
        assert bet_dict["creator"] == "0xsubmitter"
        assert bet_dict["fee"] == 0
        assert bet_dict["market_spread"] is None
        assert bet_dict["outcomeSlotCount"] == 2
        assert bet_dict["investments"] == {}
        assert bet_dict["position_liquidity"] == 0
        assert bet_dict["potential_net_profit"] == 0
        assert isinstance(bet_dict["outcome_token_ids"], dict)

    def test_valid_market_reads_spread(self) -> None:
        """Test that spread from the Gamma API response is included in bet_dict."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(spread="0.04")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        bet_dict = result[0]
        assert bet_dict["market_spread"] == 0.04

    def test_valid_market_invalid_spread_ignored(self) -> None:
        """Test that an invalid spread value results in None."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(spread="not_a_number")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        bet_dict = result[0]
        assert bet_dict["market_spread"] is None

    def test_valid_market_out_of_range_spread_ignored(self) -> None:
        """Test that an out-of-range spread value (> 1) results in None."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(spread="2.0")
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        bet_dict = result[0]
        assert bet_dict["market_spread"] is None

    def test_market_negative_price(self) -> None:
        """Test market with negative price is skipped."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market(outcomePrices=json.dumps(["-0.1", "0.5"]))
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_skipped_markets_logged_in_summary(self) -> None:
        """Test that category summary is logged when markets are skipped."""
        behaviour = self._setup_behaviour()
        # One valid, one invalid (missing conditionId)
        market1 = _make_valid_market(id="m1", question="Will AI improve?")
        market2 = _make_valid_market(id="m2", conditionId="")
        response = {"technology": [market1, market2]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        # Verify logger was called with category skip info
        log_calls = [str(c) for c in behaviour.context.logger.info.call_args_list]
        assert any("skipped" in call.lower() for call in log_calls)

    def test_market_without_id_uses_unknown(self) -> None:
        """Test market without id field uses 'unknown'."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market()
        del market["id"]
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        # The market should still be processed, just with id="unknown"
        assert result is not None  # type: ignore[arg-type]
        if len(result) > 0:
            assert result[0]["id"] == "unknown"

    def test_first_five_bets_logged(self) -> None:
        """Test that debug logging happens for first 5 bets."""
        behaviour = self._setup_behaviour()
        markets = [
            _make_valid_market(
                id=f"m{i}",
                question="Will Tesla stock go up?",
            )
            for i in range(6)
        ]
        response = {"technology": markets}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 6  # type: ignore[arg-type]
        # First 5 should trigger the debug log
        info_calls = [str(c) for c in behaviour.context.logger.info.call_args_list]
        creating_calls = [c for c in info_calls if "Creating bet_dict" in c]
        assert len(creating_calls) == 5


# ===========================================================================
# Tests for _update_bets (generator)
# ===========================================================================


class TestUpdateBets:
    """Tests for _update_bets."""

    def test_fetch_returns_none_clears_bets(self) -> None:
        """Test that failed fetch clears bets."""
        behaviour = _make_behaviour()
        behaviour.bets = [_make_bet()]
        behaviour._fetch_markets_from_polymarket = _return_gen(None)  # type: ignore[method-assign]
        behaviour._blacklist_expired_bets = MagicMock()  # type: ignore[method-assign]
        type(behaviour).synced_time = PropertyMock(return_value=5000)  # type: ignore[method-assign]
        # type: ignore[method-assign]
        gen = behaviour._update_bets()  # type: ignore[method-assign]
        _exhaust_gen(gen)  # type: ignore[method-assign]

        assert behaviour.bets == []
        behaviour._blacklist_expired_bets.assert_not_called()  # type: ignore[attr-defined]

    def test_successful_update(self) -> None:
        """Test successful bet update."""
        behaviour = _make_behaviour()
        behaviour._current_market = "polymarket"
        bet_data = [
            dict(
                id="b1",
                title="Test?",
                collateralToken="0xtoken",
                creator="0xcreator",
                fee=0,
                openingTimestamp=9999999999,
                outcomeSlotCount=2,
                outcomeTokenAmounts=[100, 200],
                outcomeTokenMarginalPrices=[0.5, 0.5],
                outcomes=["Yes", "No"],
                scaledLiquidityMeasure=10.0,
            )
        ]
        behaviour._fetch_markets_from_polymarket = _return_gen(bet_data)  # type: ignore[method-assign]
        behaviour._blacklist_expired_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.context.params.opening_margin = 1000
        behaviour.context.params.disabled_polymarket_tags = []
        type(behaviour).synced_time = PropertyMock(return_value=5000)  # type: ignore[method-assign]
        # type: ignore[method-assign]
        gen = behaviour._update_bets()
        _exhaust_gen(gen)  # type: ignore[method-assign]

        assert len(behaviour.bets) == 1
        behaviour._blacklist_expired_bets.assert_called_once()  # type: ignore[attr-defined]


# ===========================================================================
# Tests for poly_tags flowing from market dict to Bet object
# ===========================================================================


class TestPolyTagsFlowThrough:
    """poly_tags must flow from the /events market dict onto the Bet object.

    The disabled-tag policy filter lives in decision_maker_abci's sampling
    behaviour; the data contract at this layer is that each Bet carries the
    tags the connection attached, so the sampling filter has data to match.
    """

    def _setup_behaviour(self) -> PolymarketFetchMarketBehaviour:
        behaviour = _make_behaviour()
        behaviour.context.params.store_path = Path("/tmp")  # nosec B108
        behaviour.send_polymarket_connection_request = MagicMock()  # type: ignore[method-assign]
        return behaviour

    def test_bet_dict_carries_poly_tags_from_market(self) -> None:
        """Bet dicts built from markets include poly_tags from _poly_tags."""
        behaviour = self._setup_behaviour()
        market = _make_valid_market()
        market["_poly_tags"] = ["politics", "elections"]
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type]
        assert result is not None
        assert len(result) == 1
        assert result[0]["poly_tags"] == ["politics", "elections"]


# ===========================================================================
# Tests for _fetch_polymarket_trades (generator)
# ===========================================================================


class TestFetchPolymarketTrades:
    """Tests for _fetch_polymarket_trades."""

    def test_successful_fetch(self) -> None:
        """Test successful trades fetch."""
        behaviour = _make_behaviour()
        trades_data = [
            {
                "conditionId": "c1",
                "outcomeIndex": 0,
                "side": "BUY",
                "size": "10",
                "price": "0.5",
            }
        ]
        behaviour.send_polymarket_connection_request = _return_gen(trades_data)  # type: ignore[method-assign]

        gen = behaviour._fetch_polymarket_trades()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result == trades_data

    # type: ignore[arg-type]
    def test_none_response(self) -> None:
        """Test None response returns None."""
        behaviour = _make_behaviour()
        behaviour.send_polymarket_connection_request = _return_gen(None)  # type: ignore[method-assign]

        gen = behaviour._fetch_polymarket_trades()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is None

    # type: ignore[arg-type]
    def test_error_response(self) -> None:
        """Test error dict response returns None."""
        behaviour = _make_behaviour()
        behaviour.send_polymarket_connection_request = _return_gen({"error": "oops"})  # type: ignore[method-assign]

        gen = behaviour._fetch_polymarket_trades()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is None


# type: ignore[arg-type]

# ===========================================================================
# Tests for update_bets_investments (generator)
# ===========================================================================


class TestUpdateBetsInvestments:
    """Tests for update_bets_investments."""

    def test_trades_none_returns_early(self) -> None:
        """Test that None trades causes early return."""
        behaviour = _make_behaviour()
        behaviour._fetch_polymarket_trades = _return_gen(None)  # type: ignore[method-assign]
        behaviour._process_and_group_trades = MagicMock()  # type: ignore[method-assign]

        gen = behaviour.update_bets_investments()  # type: ignore[method-assign]
        _exhaust_gen(gen)  # type: ignore[method-assign]

        behaviour._process_and_group_trades.assert_not_called()  # type: ignore[attr-defined]

    def test_successful_update(self) -> None:
        """Test successful investment update flow."""
        behaviour = _make_behaviour()
        trades_data = [
            {
                "conditionId": "c1",
                "outcomeIndex": 0,
                "side": "BUY",
                "size": "10",
                "price": "0.5",
            }
        ]
        behaviour._fetch_polymarket_trades = _return_gen(trades_data)  # type: ignore[method-assign]
        behaviour._process_and_group_trades = MagicMock(return_value={"c1": {0: []}})  # type: ignore[method-assign]
        behaviour._update_all_bets_investments = MagicMock()  # type: ignore[method-assign]
        # type: ignore[method-assign]
        gen = behaviour.update_bets_investments()  # type: ignore[method-assign]
        _exhaust_gen(gen)  # type: ignore[method-assign]

        behaviour._process_and_group_trades.assert_called_once_with(trades_data)  # type: ignore[attr-defined]
        behaviour._update_all_bets_investments.assert_called_once()  # type: ignore[attr-defined]


# ===========================================================================
# Tests for async_act (generator)
# ===========================================================================


class TestAsyncAct:
    """Tests for async_act."""

    def _setup_behaviour(self) -> PolymarketFetchMarketBehaviour:
        """Set up a fully mocked behaviour for async_act."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = False
        type(behaviour).behaviour_id = PropertyMock(return_value="test_behaviour")

        # Mock context.benchmark_tool
        mock_benchmark = MagicMock()
        mock_benchmark.measure.return_value.local.return_value.__enter__ = MagicMock(
            return_value=None
        )
        mock_benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_benchmark.measure.return_value.consensus.return_value.__enter__ = (
            MagicMock(return_value=None)
        )
        mock_benchmark.measure.return_value.consensus.return_value.__exit__ = MagicMock(
            return_value=False
        )
        behaviour.context.benchmark_tool = mock_benchmark

        # Mock generator methods
        behaviour._update_bets = _noop_gen  # type: ignore[method-assign]
        behaviour.update_bets_investments = _noop_gen  # type: ignore[method-assign]
        behaviour._requeue_bets_for_selling = MagicMock()  # type: ignore[method-assign]
        behaviour._bet_freshness_check_and_update = MagicMock()  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.hash_stored_bets = MagicMock(return_value="hash123")  # type: ignore[method-assign]
        behaviour.send_a2a_transaction = _noop_gen  # type: ignore[method-assign]
        behaviour.wait_until_round_end = _noop_gen  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.context.agent_address = "agent_addr"  # type: ignore[method-assign]
        # type: ignore[method-assign]
        mock_synced = MagicMock()  # type: ignore[method-assign]
        mock_synced.review_bets_for_selling = False
        type(behaviour).synchronized_data = PropertyMock(return_value=mock_synced)  # type: ignore[method-assign]

        return behaviour

    # type: ignore[method-assign]
    def test_async_act_full_lifecycle(self) -> None:
        """Test async_act goes through full lifecycle."""
        behaviour = self._setup_behaviour()
        behaviour.bets = [_make_bet()]

        gen = behaviour.async_act()
        _exhaust_gen(gen)

        behaviour.store_bets.assert_called_once()  # type: ignore[attr-defined]
        behaviour.hash_stored_bets.assert_called_once()  # type: ignore[attr-defined]
        behaviour.set_done.assert_called_once()  # type: ignore[attr-defined]

    # type: ignore[attr-defined]
    def test_async_act_with_review_selling(self) -> None:  # type: ignore[attr-defined]
        """Test async_act calls requeue for selling when review flag is set."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.bets = [_make_bet()]
        behaviour.synchronized_data.review_bets_for_selling = True  # type: ignore[misc]

        gen = behaviour.async_act()
        _exhaust_gen(gen)  # type: ignore[misc]

        behaviour._requeue_bets_for_selling.assert_called_once()  # type: ignore[attr-defined]

    def test_async_act_without_review_selling(self) -> None:
        """Test async_act does NOT call requeue for selling when review flag is not set."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.bets = [_make_bet()]
        behaviour.synchronized_data.review_bets_for_selling = False  # type: ignore[misc]

        gen = behaviour.async_act()
        _exhaust_gen(gen)  # type: ignore[misc]

        behaviour._requeue_bets_for_selling.assert_not_called()  # type: ignore[attr-defined]

    def test_async_act_freshness_check_when_bets_exist(self) -> None:
        """Test async_act calls freshness check when bets exist."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.bets = [_make_bet()]

        gen = behaviour.async_act()
        _exhaust_gen(gen)

        behaviour._bet_freshness_check_and_update.assert_called_once()  # type: ignore[attr-defined]

    def test_async_act_no_freshness_check_when_no_bets(self) -> None:
        """Test async_act does NOT call freshness check when no bets."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.bets = []

        gen = behaviour.async_act()
        _exhaust_gen(gen)

        behaviour._bet_freshness_check_and_update.assert_not_called()  # type: ignore[attr-defined]

    def test_async_act_no_bets_hash_is_none(self) -> None:
        """Test async_act sets bets_hash to None when no bets."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        behaviour.bets = []

        gen = behaviour.async_act()
        _exhaust_gen(gen)

        behaviour.hash_stored_bets.assert_not_called()  # type: ignore[attr-defined]

    def test_async_act_calls_store_bets(self) -> None:
        """Test async_act stores bets."""  # type: ignore[attr-defined]
        behaviour = self._setup_behaviour()
        gen = behaviour.async_act()
        _exhaust_gen(gen)
        behaviour.store_bets.assert_called_once()  # type: ignore[attr-defined]


# ===========================================================================  # type: ignore[attr-defined]
# Tests for matching_round class attribute
# ===========================================================================


# ===========================================================================
# Edge case and integration-like tests
# ===========================================================================


class TestEdgeCases:
    """Additional edge-case tests for higher coverage."""

    def test_process_chunk_multiple_new_bets(self) -> None:
        """Test _process_chunk with multiple new bets."""
        behaviour = _make_behaviour()
        behaviour._current_market = "polymarket"
        raw_bets = [
            dict(
                id=f"b{i}",
                title="Q?",
                collateralToken="0xtoken",
                creator="0xcreator",
                fee=0,
                openingTimestamp=9999999999,
                outcomeSlotCount=2,
                outcomeTokenAmounts=[100, 200],
                outcomeTokenMarginalPrices=[0.5, 0.5],
                outcomes=["Yes", "No"],
                scaledLiquidityMeasure=10.0,
            )
            for i in range(5)
        ]
        behaviour._process_chunk(raw_bets)
        assert len(behaviour.bets) == 5

    def test_blacklist_expired_bets_exactly_at_margin_boundary(self) -> None:
        """Test blacklisting at exact boundary: synced_time == openingTimestamp - opening_margin."""
        behaviour = _make_behaviour()
        behaviour.context.params.opening_margin = 1000
        type(behaviour).synced_time = PropertyMock(return_value=5000)  # type: ignore[method-assign]
        # openingTimestamp - opening_margin == 6000 - 1000 == 5000 == synced_time -> should blacklist
        bet = _make_bet(id="b1", openingTimestamp=6000)
        behaviour.bets = [bet]  # type: ignore[method-assign]
        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_validate_trade_empty_dict(self) -> None:
        """Test _validate_trade with empty dict."""
        behaviour = _make_behaviour()
        assert behaviour._validate_trade({}) is False

    def test_calculate_trade_usdc_amount_both_valid_zero(self) -> None:
        """Test _calculate_trade_usdc_amount with zero values."""
        behaviour = _make_behaviour()
        result = behaviour._calculate_trade_usdc_amount("0", "0")
        assert result == 0.0

    def test_update_single_bet_investments_multiple_outcomes(self) -> None:
        """Test updating investments for multiple outcome indices."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1")
        bet.condition_id = "0xcond"
        bet.investments = {"Yes": [], "No": []}
        trades_map: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            "0xcond": {
                0: [{"side": "BUY", "usdc_amount": 10.0}],
                1: [{"side": "BUY", "usdc_amount": 5.0}],
            }
        }
        behaviour._update_single_bet_investments(bet, trades_map)
        assert len(bet.investments["Yes"]) == 1
        assert len(bet.investments["No"]) == 1
        assert bet.investments["Yes"][0] == int(10.0 * USDC_DECIMALS)
        assert bet.investments["No"][0] == int(5.0 * USDC_DECIMALS)

    def test_deduplicate_single_market_no_dedup_needed(self) -> None:
        """Test deduplicate with single market per category."""
        behaviour = _make_behaviour()
        markets = {
            "technology": [{"id": "m1", "category_valid": True}],
        }
        result = behaviour._deduplicate_markets(markets)
        assert len(result["technology"]) == 1

    def test_validate_market_category_all_categories(self) -> None:
        """Test _validate_market_category against all categories with matching keywords."""
        test_cases = {
            "business": "The company announced a merger",
            "politics": "The election results are in",
            "science": "NASA launched a new rocket",
            "technology": "AI is transforming the world",
            "health": "The vaccine rollout continues",
            "entertainment": "The movie broke box office records",
            "weather": "A hurricane is approaching",
            "finance": "The stock market crashed today",
            "international": "The war in Ukraine continues",
        }
        for category, title in test_cases.items():
            assert PolymarketFetchMarketBehaviour._validate_market_category(
                title, category
            ), f"Expected match for category={category}, title={title}"

    def test_process_and_group_trades_condition_id_none_after_validate(self) -> None:
        """Test edge case where condition_id is None after validate (second guard)."""
        behaviour = _make_behaviour()
        # A trade that passes _validate_trade but has None conditionId on .get()
        trade = {
            "outcomeIndex": 0,
            "side": "BUY",
            "size": "10",
            "price": "0.5",
        }
        # Force _validate_trade to return True so we reach the second check
        with patch.object(behaviour, "_validate_trade", return_value=True):
            result = behaviour._process_and_group_trades([trade])
        # conditionId is None via .get(), so trade should be skipped
        assert len(result) == 0

    def test_requeue_bets_for_selling_multiple_conditions(self) -> None:
        """Test _requeue_bets_for_selling with various bet conditions."""
        behaviour = _make_behaviour()
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 3600
        type(behaviour).synced_time = PropertyMock(return_value=5000000000)  # type: ignore[method-assign]

        # Bet that meets all conditions
        bet1 = _make_bet(id="b1", queue_status=QueueStatus.PROCESSED)  # type: ignore[method-assign]
        bet1.investments = {"Yes": [100], "No": []}
        bet1.last_processed_sell_check = 0
        bet1.is_ready_to_sell = MagicMock(return_value=True)  # type: ignore[method-assign]

        # Bet that is not ready to sell
        bet2 = _make_bet(id="b2", queue_status=QueueStatus.PROCESSED)  # type: ignore[method-assign]
        bet2.investments = {"Yes": [100], "No": []}
        bet2.last_processed_sell_check = 0
        bet2.is_ready_to_sell = MagicMock(return_value=False)  # type: ignore[method-assign]

        behaviour.bets = [bet1, bet2]
        behaviour._requeue_bets_for_selling()  # type: ignore[method-assign]

        assert bet1.queue_status == QueueStatus.FRESH
        assert bet2.queue_status == QueueStatus.PROCESSED

    def test_fetch_markets_type_error_in_market(self) -> None:
        """Test that TypeError in market processing is caught."""
        behaviour = _make_behaviour()
        behaviour.context.params.store_path = Path("/tmp")  # nosec B108

        market = _make_valid_market(
            outcomes=json.dumps(["Yes", "No"]),
            outcomePrices=json.dumps(["0.5", "0.5"]),
            clobTokenIds=json.dumps(["t1", "t2"]),
            liquidity="not_a_number_that_causes_issues",
        )
        # liquidity="not_a_number_that_causes_issues" will fail float conversion
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_extreme_price_at_boundary(self) -> None:
        """Test extreme price exactly at threshold (0.99)."""
        behaviour = _make_behaviour()
        behaviour.context.params.opening_margin = 1000
        type(behaviour).synced_time = PropertyMock(return_value=5000)  # type: ignore[method-assign]

        bet = _make_bet(
            id="b1",  # type: ignore[method-assign]
            openingTimestamp=9999999999,
            outcomeTokenMarginalPrices=[0.99, 0.01],
        )
        behaviour.bets = [bet]
        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_extreme_price_just_below_threshold(self) -> None:
        """Test price just below threshold is NOT blacklisted."""
        behaviour = _make_behaviour()
        behaviour.context.params.opening_margin = 1000
        type(behaviour).synced_time = PropertyMock(return_value=5000)  # type: ignore[method-assign]

        bet = _make_bet(
            id="b1",  # type: ignore[method-assign]
            openingTimestamp=9999999999,
            outcomeTokenMarginalPrices=[0.989, 0.011],
        )
        behaviour.bets = [bet]
        behaviour._blacklist_expired_bets()
        assert bet.queue_status != QueueStatus.EXPIRED

    def test_should_skip_bet_with_condition_id_not_expired(self) -> None:
        """Test _should_skip_bet returns False for valid bet."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="b1", queue_status=QueueStatus.TO_PROCESS)
        bet.condition_id = "0xcond"
        assert behaviour._should_skip_bet(bet) is False

    def test_multi_bets_mode_all_expired_is_vacuously_true(self) -> None:
        """Test multi-bets mode with all bets expired (vacuously all_bets_fresh)."""
        behaviour = _make_behaviour()
        behaviour.context.params.use_multi_bets_mode = True
        bet1 = _make_bet(id="b1")
        bet1.queue_status = QueueStatus.EXPIRED
        behaviour.bets = [bet1]
        behaviour._bet_freshness_check_and_update()
        # all() on empty iterable returns True, so all expired bets cause move_to_process
        # EXPIRED.move_to_process() returns self
        assert bet1.queue_status == QueueStatus.EXPIRED

    def test_convert_usdc_large_value(self) -> None:
        """Test _convert_usdc_to_base_units with a large value."""
        behaviour = _make_behaviour()
        result = behaviour._convert_usdc_to_base_units(999999999.99)
        assert result == int(999999999.99 * USDC_DECIMALS)

    def test_process_chunk_empty_list(self) -> None:
        """Test _process_chunk with empty list."""
        behaviour = _make_behaviour()
        behaviour._current_market = "polymarket"
        behaviour._process_chunk([])
        assert behaviour.bets == []

    def test_fetch_markets_valid_market_is_valid_true(self) -> None:
        """Test that a valid categorized, not-closed market has correct flags."""
        behaviour = _make_behaviour()
        behaviour.context.params.store_path = Path("/tmp")  # nosec B108

        market = _make_valid_market(
            question="Will Google release new AI?",
            closed=False,
        )
        response = {"technology": [market]}
        behaviour.send_polymarket_connection_request = _return_gen(response)  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 1  # type: ignore[arg-type]
        bet = result[0]
        assert bet["outcomes"] is not None  # valid market has outcomes
        assert bet["queue_status"] == QueueStatus.FRESH
        assert bet["processed_timestamp"] == 0

    def test_fetch_markets_no_categories(self) -> None:
        """Test fetching with empty response dict."""
        behaviour = _make_behaviour()
        behaviour.context.params.store_path = Path("/tmp")  # nosec B108
        behaviour.send_polymarket_connection_request = _return_gen({})  # type: ignore[method-assign]

        gen = behaviour._fetch_markets_from_polymarket()
        result = _exhaust_gen(gen)  # type: ignore[arg-type, method-assign]

        assert result is not None
        assert len(result) == 0  # type: ignore[arg-type]

    def test_get_bet_idx_first_element(self) -> None:
        """Test get_bet_idx returns 0 for first element."""
        bet = _make_bet(id="b1")
        behaviour = _make_behaviour(bets=[bet])
        assert behaviour.get_bet_idx("b1") == 0


class TestPolymarketDryRunGate:
    """Gate-strictness for the POLYMARKET_DRY_RUN_HARDCODE env var.

    Must match the sibling gate in ``sampling._polymarket_dry_run_enabled``
    so both sides activate together. See the companion tests in
    ``decision_maker_abci/tests/behaviours/test_sampling.py``.
    """

    def test_unset_is_disabled(self) -> None:
        """Gate must be off when the env var is unset."""
        env = {
            k: v for k, v in os.environ.items() if k != "POLYMARKET_DRY_RUN_HARDCODE"
        }
        with patch.dict(os.environ, env, clear=True):
            assert _polymarket_dry_run_enabled() is False

    def test_empty_string_is_disabled(self) -> None:
        """Empty string must not activate the gate."""
        with patch.dict(os.environ, {"POLYMARKET_DRY_RUN_HARDCODE": ""}):
            assert _polymarket_dry_run_enabled() is False

    def test_zero_string_is_disabled(self) -> None:
        """'0' must not activate the gate (main concern of the review)."""
        with patch.dict(os.environ, {"POLYMARKET_DRY_RUN_HARDCODE": "0"}):
            assert _polymarket_dry_run_enabled() is False

    def test_false_string_is_disabled(self) -> None:
        """'false' must not activate the gate."""
        with patch.dict(os.environ, {"POLYMARKET_DRY_RUN_HARDCODE": "false"}):
            assert _polymarket_dry_run_enabled() is False

    def test_one_string_enables(self) -> None:
        """'1' must activate the gate."""
        with patch.dict(os.environ, {"POLYMARKET_DRY_RUN_HARDCODE": "1"}):
            assert _polymarket_dry_run_enabled() is True

    def test_true_string_enables_case_insensitive(self) -> None:
        """'TRUE' / 'True' must activate the gate (case-insensitive)."""
        for value in ("true", "True", "TRUE"):
            with patch.dict(os.environ, {"POLYMARKET_DRY_RUN_HARDCODE": value}):
                assert _polymarket_dry_run_enabled() is True, f"failed for {value!r}"
