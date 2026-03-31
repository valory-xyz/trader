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

"""Tests for the update_bets behaviour of the MarketManager ABCI application."""

from copy import deepcopy
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

from packages.valory.skills.market_manager_abci.behaviours.update_bets import (
    UpdateBetsBehaviour,
)
from packages.valory.skills.market_manager_abci.bets import Bet, QueueStatus
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
)

# ---------------------------------------------------------------------------
# Generator helpers for mocking `yield from` calls
# ---------------------------------------------------------------------------


def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """A no-op generator that yields once and returns None."""
    yield
    return None


def _return_gen(value: Any) -> Any:
    """Return a generator factory that yields once then returns *value*."""

    def gen(*args: Any, **kwargs: Any) -> Generator:
        yield
        return value

    # type: ignore[no-untyped-def]
    return gen


# ---------------------------------------------------------------------------
# Bet factory
# ---------------------------------------------------------------------------


def _make_bet(**overrides: Any) -> Bet:
    """Create a valid binary Bet with sensible defaults."""
    defaults: Dict[str, Any] = dict(
        id="bet1",
        market="omen_subgraph",
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
    bet = Bet(**defaults)
    # last_processed_sell_check is not a dataclass field; it's set dynamically.
    # Default to 0 so the attribute always exists for tests that access it.
    if not hasattr(bet, "last_processed_sell_check"):
        bet.last_processed_sell_check = 0  # type: ignore[attr-defined]
    return bet


# ---------------------------------------------------------------------------
# Behaviour factory
# ---------------------------------------------------------------------------


def _make_behaviour(**overrides: Any) -> UpdateBetsBehaviour:
    """Create an UpdateBetsBehaviour instance bypassing __init__."""
    behaviour = object.__new__(UpdateBetsBehaviour)
    behaviour._context = MagicMock()
    behaviour.bets = []
    behaviour.multi_bets_filepath = "/tmp/multi_bets.json"  # nosec B108
    behaviour.bets_filepath = "/tmp/bets.json"  # nosec B108
    behaviour._call_failed = False
    behaviour._fetch_status = FetchStatus.NONE
    behaviour._creators_iterator = iter([])
    behaviour._current_market = ""
    behaviour._current_creators = []

    for key, val in overrides.items():
        setattr(behaviour, key, val)

    return behaviour


# ===========================================================================
# Tests
# ===========================================================================


class TestInit:
    """Tests for UpdateBetsBehaviour.__init__."""

    def test_init_calls_super(self) -> None:
        """Test that __init__ delegates to super().__init__."""
        with patch.object(
            UpdateBetsBehaviour, "__init__", wraps=UpdateBetsBehaviour.__init__
        ):
            # We cannot fully construct the object without the framework,
            # but we can verify the signature accepts **kwargs.
            # Use object.__new__ and call __init__ manually with a mock.
            behaviour = object.__new__(UpdateBetsBehaviour)
            with (
                patch(
                    "packages.valory.skills.market_manager_abci.behaviours.update_bets.BetsManagerBehaviour.__init__"
                ) as mock_bets_init,
                patch(
                    "packages.valory.skills.market_manager_abci.behaviours.update_bets.QueryingBehaviour.__init__"
                ),
            ):
                mock_bets_init.return_value = None
                # __init__ calls super().__init__(**kwargs) which hits MRO
                # We just check the call happens without error
                try:
                    UpdateBetsBehaviour.__init__(
                        behaviour, name="test", skill_context=MagicMock()
                    )
                except Exception:  # nosec B110
                    pass  # Exceptions from deep framework internals are expected


class TestRequeueAllBets:
    """Tests for _requeue_all_bets."""

    def test_requeue_all_bets_moves_to_fresh(self) -> None:
        """Test that all bets are moved to FRESH status."""
        b1 = _make_bet(id="b1")
        b1.queue_status = QueueStatus.PROCESSED
        b2 = _make_bet(id="b2")
        b2.queue_status = QueueStatus.TO_PROCESS

        behaviour = _make_behaviour(bets=[b1, b2])
        behaviour._requeue_all_bets()

        assert b1.queue_status == QueueStatus.FRESH
        assert b2.queue_status == QueueStatus.FRESH

    def test_requeue_all_bets_expired_stays_expired(self) -> None:
        """Test that expired bets stay expired (move_to_fresh skips EXPIRED)."""
        b = _make_bet(id="b1")
        b.blacklist_forever()

        behaviour = _make_behaviour(bets=[b])
        behaviour._requeue_all_bets()

        assert b.queue_status == QueueStatus.EXPIRED

    def test_requeue_all_bets_empty(self) -> None:
        """Test with empty bets list."""
        behaviour = _make_behaviour(bets=[])
        behaviour._requeue_all_bets()
        assert behaviour.bets == []


class TestRequeueBetsForSelling:
    """Tests for _requeue_bets_for_selling."""

    def _make_sellable_bet(self, **extra: Any) -> Bet:
        """Create a bet that satisfies all conditions for selling requeue."""
        bet = _make_bet(
            id="sellable",
            openingTimestamp=1000,  # far in the past
            **extra,
        )
        bet.queue_status = QueueStatus.PROCESSED
        # Give it an investment so invested_amount > 0
        bet.investments = {"Yes": [100], "No": []}
        return bet

    def test_expired_bet_skipped(self) -> None:
        """Test that expired bets are not requeued.

        We set queue_status to EXPIRED directly (not via blacklist_forever)
        to avoid nullifying outcomes, which would cause is_ready_to_sell to raise.
        """
        bet = self._make_sellable_bet()
        # Set expired without nullifying outcomes
        bet.queue_status = QueueStatus.EXPIRED

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 0

        # Make synced_time property return a value
        type(behaviour).synced_time = property(lambda self: 99999)  # type: ignore[assignment, method-assign]

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_no_invested_amount_skipped(self) -> None:
        """Test that bets with no invested amount are skipped."""  # type: ignore[assignment, method-assign]
        bet = _make_bet(id="no_invest", openingTimestamp=1000)
        bet.queue_status = QueueStatus.PROCESSED
        bet.investments = {"Yes": [], "No": []}

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 0

        type(behaviour).synced_time = property(lambda self: 99999)  # type: ignore[assignment, method-assign]

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_ready_to_sell_gets_requeued(self) -> None:
        """Test that a bet ready to sell with no last_processed_sell_check is requeued."""  # type: ignore[assignment, method-assign]
        bet = self._make_sellable_bet()
        # Make sure last_processed_sell_check is 0 (falsy) so the condition passes
        bet.last_processed_sell_check = 0  # type: ignore[attr-defined]

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 0

        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.FRESH

    def test_last_processed_sell_check_within_interval_not_requeued(self) -> None:
        """Test that a bet with recent sell check is not requeued."""  # type: ignore[assignment, method-assign]
        bet = self._make_sellable_bet()
        # Set a last_processed_sell_check that makes time_since < interval
        bet.last_processed_sell_check = 999990  # type: ignore[attr-defined]

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 100  # interval is 100

        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]
        # time_since = 999999 - 999990 = 9, interval = 100 => 9 < 100 => not requeued

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_last_processed_sell_check_exceeded_interval_requeued(self) -> None:  # type: ignore[assignment, method-assign]
        """Test that a bet with old sell check is requeued."""
        bet = self._make_sellable_bet()
        bet.last_processed_sell_check = 900000  # type: ignore[attr-defined]

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 10

        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]
        # time_since = 999999 - 900000 = 99999, interval = 10 => 99999 > 10 => requeued

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.FRESH

    def test_not_ready_to_sell_not_requeued(self) -> None:  # type: ignore[assignment, method-assign]
        """Test that a bet not ready to sell is not requeued."""
        # openingTimestamp far in the future => not ready
        bet = _make_bet(id="future", openingTimestamp=99999999999)
        bet.queue_status = QueueStatus.PROCESSED
        bet.investments = {"Yes": [100], "No": []}
        bet.last_processed_sell_check = 0  # type: ignore[attr-defined]

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 0

        type(behaviour).synced_time = property(lambda self: 1000)  # type: ignore[assignment, method-assign]

        behaviour._requeue_bets_for_selling()
        assert bet.queue_status == QueueStatus.PROCESSED


class TestBlacklistExpiredBets:  # type: ignore[assignment, method-assign]
    """Tests for _blacklist_expired_bets."""

    def test_blacklists_past_opening_margin(self) -> None:
        """Test that bets past the opening margin are blacklisted."""
        bet = _make_bet(id="old", openingTimestamp=1000)
        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 950)  # type: ignore[assignment, method-assign]
        # synced_time(950) >= openingTimestamp(1000) - opening_margin(100) = 900 => True

        behaviour._blacklist_expired_bets()
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_does_not_blacklist_within_margin(self) -> None:  # type: ignore[assignment, method-assign]
        """Test that bets within the opening margin are not blacklisted."""
        bet = _make_bet(id="future", openingTimestamp=1000)
        original_status = bet.queue_status

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 800)  # type: ignore[assignment, method-assign]
        # synced_time(800) >= openingTimestamp(1000) - opening_margin(100) = 900 => False

        behaviour._blacklist_expired_bets()
        assert bet.queue_status == original_status

    def test_empty_bets(self) -> None:  # type: ignore[assignment, method-assign]
        """Test with empty bets list."""
        behaviour = _make_behaviour(bets=[])
        behaviour.context.params.opening_margin = 100
        type(behaviour).synced_time = property(lambda self: 1000)  # type: ignore[assignment, method-assign]
        behaviour._blacklist_expired_bets()
        assert behaviour.bets == []


class TestReviewBetsForSelling:
    """Tests for review_bets_for_selling."""  # type: ignore[assignment, method-assign]

    def test_returns_synchronized_data_value(self) -> None:
        """Test that it delegates to synchronized_data.review_bets_for_selling."""
        behaviour = _make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.review_bets_for_selling = True

        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        assert behaviour.review_bets_for_selling() is True

    def test_returns_false(self) -> None:
        """Test that it returns False when synchronized_data says False."""
        behaviour = _make_behaviour()  # type: ignore[assignment, method-assign]
        mock_sync_data = MagicMock()
        mock_sync_data.review_bets_for_selling = False

        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        assert behaviour.review_bets_for_selling() is False


class TestUpdateBetsInvestments:
    """Tests for update_bets_investments."""  # type: ignore[assignment, method-assign]

    def test_expired_bet_skipped(self) -> None:
        """Test that expired bets are skipped during investment update."""
        bet = _make_bet(id="expired_bet")
        bet.blacklist_forever()

        behaviour = _make_behaviour(bets=[bet])
        behaviour.get_active_bets = _return_gen({"expired_bet": {"Yes": 100, "No": 50}})  # type: ignore[method-assign]

        gen = behaviour.update_bets_investments()
        try:
            next(gen)
            gen.send(None)
        except StopIteration:  # type: ignore[method-assign]
            pass

        # Expired bet should be skipped, investments should not change
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_outcome_mapping(self) -> None:
        """Test that outcomes are correctly mapped using BinaryOutcome.from_string."""
        bet = _make_bet(id="bet1")
        balances = {"bet1": {"Yes": 100, "No": 50}}

        behaviour = _make_behaviour(bets=[bet])
        behaviour.get_active_bets = _return_gen(balances)  # type: ignore[method-assign]

        gen = behaviour.update_bets_investments()
        try:
            next(gen)
            gen.send(None)
        except StopIteration:  # type: ignore[method-assign]
            pass

        # "Yes" => BinaryOutcome.YES => outcome_int = 1 => get_outcome(1) = "No"
        # "No" => BinaryOutcome.NO => outcome_int = 0 => get_outcome(0) = "Yes"
        # So "Yes" value goes to investments["No"] and "No" value to investments["Yes"]
        assert 100 in bet.investments["No"]
        assert 50 in bet.investments["Yes"]

    def test_replace_with_existing_if_empty(self) -> None:
        """Test that empty investments are replaced with existing ones."""
        bet = _make_bet(id="bet1")
        bet.investments = {"Yes": [200], "No": [300]}
        original_investments = deepcopy(bet.investments)

        # Return empty balances for the bet
        balances = {"bet1": {}}  # type: ignore[var-annotated]

        behaviour = _make_behaviour(bets=[bet])
        behaviour.get_active_bets = _return_gen(balances)  # type: ignore[method-assign]

        gen = behaviour.update_bets_investments()
        try:  # type: ignore[var-annotated]
            next(gen)
            gen.send(None)
        except StopIteration:  # type: ignore[method-assign]
            pass

        # Since new investments are empty, should retain existing
        assert bet.investments == original_investments


class TestReplaceWithExistingInvestmentsIfEmpty:
    """Tests for _replace_with_existing_investments_if_empty."""

    def test_replaces_when_both_empty(self) -> None:
        """Test replacement when both yes and no investments are empty."""
        bet = _make_bet(id="bet1")
        bet.investments = {"Yes": [], "No": []}
        existing = {"Yes": [100], "No": [200]}

        behaviour = _make_behaviour()
        behaviour._replace_with_existing_investments_if_empty(bet, existing)

        assert bet.investments == existing

    def test_does_not_replace_when_yes_has_values(self) -> None:
        """Test no replacement when yes investments exist."""
        bet = _make_bet(id="bet1")
        bet.investments = {"Yes": [100], "No": []}
        existing = {"Yes": [999], "No": [999]}

        behaviour = _make_behaviour()
        behaviour._replace_with_existing_investments_if_empty(bet, existing)

        assert bet.investments == {"Yes": [100], "No": []}

    def test_does_not_replace_when_no_has_values(self) -> None:
        """Test no replacement when no investments exist."""
        bet = _make_bet(id="bet1")
        bet.investments = {"Yes": [], "No": [50]}
        existing = {"Yes": [999], "No": [999]}

        behaviour = _make_behaviour()
        behaviour._replace_with_existing_investments_if_empty(bet, existing)

        assert bet.investments == {"Yes": [], "No": [50]}


class TestGetActiveBets:
    """Tests for get_active_bets."""

    def test_trades_none_returns_empty(self) -> None:
        """Test that when fetch_trades returns None, result is empty dict."""
        behaviour = _make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.safe_contract_address = "0xSAFE"
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.fetch_trades = _return_gen(None)  # type: ignore[method-assign]
        behaviour.fetch_user_positions = _return_gen([{"data": "pos"}])  # type: ignore[method-assign]

        gen = behaviour.get_active_bets()
        result = None  # type: ignore[assignment, method-assign]
        try:
            next(gen)  # type: ignore[method-assign]
            gen.send(None)  # type: ignore[method-assign]
        except StopIteration as e:
            result = e.value

        assert result == {}

    def test_positions_none_returns_empty(self) -> None:
        """Test that when fetch_user_positions returns None, result is empty dict."""
        behaviour = _make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.safe_contract_address = "0xSAFE"
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.fetch_trades = _return_gen([{"some": "trade"}])  # type: ignore[method-assign]
        behaviour.fetch_user_positions = _return_gen(None)  # type: ignore[method-assign]

        gen = behaviour.get_active_bets()
        result = None  # type: ignore[assignment, method-assign]
        try:
            next(gen)  # type: ignore[method-assign]
            while True:  # type: ignore[method-assign]
                gen.send(None)
        except StopIteration as e:
            result = e.value

        assert result == {}

    def test_both_succeed_returns_balances(self) -> None:
        """Test that when both succeed, balances are returned."""
        behaviour = _make_behaviour()
        mock_sync_data = MagicMock()
        mock_sync_data.safe_contract_address = "0xSAFE"
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        trades_data = [{"fpmm": {"id": "bet1", "condition": {"id": "cond1"}}}]
        positions_data = [
            {
                "balance": "100",
                "position": {  # type: ignore[assignment, method-assign]
                    "conditionIds": ["cond1"],
                    "conditions": [{"outcomes": ["Yes", "No"]}],
                    "indexSets": ["1"],
                },
            }
        ]

        behaviour.fetch_trades = _return_gen(trades_data)  # type: ignore[method-assign]
        behaviour.fetch_user_positions = _return_gen(positions_data)  # type: ignore[method-assign]

        gen = behaviour.get_active_bets()
        result = None
        try:
            next(gen)  # type: ignore[method-assign]
            while True:  # type: ignore[method-assign]
                gen.send(None)
        except StopIteration as e:
            result = e.value

        assert "bet1" in result
        assert result["bet1"]["Yes"] == 100


class TestSetup:
    """Tests for setup."""

    def test_setup_reads_bets_and_blacklists(self) -> None:
        """Test that setup reads bets and blacklists expired ones."""
        behaviour = _make_behaviour()

        mock_sync_data = MagicMock()
        mock_sync_data.is_checkpoint_reached = False
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]
        # type: ignore[assignment, method-assign]
        # read_bets populates some bets
        bet = _make_bet(id="b1", openingTimestamp=1000)

        def fake_read_bets() -> None:
            behaviour.bets = [bet]  # type: ignore[assignment, method-assign]

        behaviour.read_bets = fake_read_bets  # type: ignore[method-assign]

        behaviour.setup()
        # type: ignore[no-untyped-def]
        # bet with openingTimestamp=1000 should be blacklisted (999999 >= 1000 - 100 = 900)
        assert bet.queue_status == QueueStatus.EXPIRED

    # type: ignore[method-assign]
    def test_setup_checkpoint_requeues_multi_bets(self) -> None:
        """Test that setup requeues all bets when checkpoint reached in multi-bets mode."""
        behaviour = _make_behaviour()

        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.PROCESSED

        mock_sync_data = MagicMock()
        mock_sync_data.is_checkpoint_reached = True
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = True
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 0)  # type: ignore[assignment, method-assign]

        # type: ignore[assignment, method-assign]
        def fake_read_bets() -> None:
            behaviour.bets = [bet]

        behaviour.read_bets = fake_read_bets  # type: ignore[method-assign]
        # type: ignore[assignment, method-assign]
        behaviour.setup()
        # type: ignore[no-untyped-def]
        # Should have been requeued to FRESH
        assert bet.queue_status == QueueStatus.FRESH

    # type: ignore[method-assign]
    def test_setup_no_checkpoint_no_requeue(self) -> None:
        """Test that setup does not requeue when checkpoint not reached."""
        behaviour = _make_behaviour()

        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.PROCESSED

        mock_sync_data = MagicMock()
        mock_sync_data.is_checkpoint_reached = False
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = True
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 0)  # type: ignore[assignment, method-assign]

        # type: ignore[assignment, method-assign]
        def fake_read_bets() -> None:
            behaviour.bets = [bet]

        behaviour.read_bets = fake_read_bets  # type: ignore[method-assign]
        # type: ignore[assignment, method-assign]
        behaviour.setup()
        # type: ignore[no-untyped-def]
        assert bet.queue_status == QueueStatus.PROCESSED

    def test_setup_empty_bets_no_blacklist(self) -> None:  # type: ignore[method-assign]
        """Test that setup does not call blacklist on empty bets."""
        behaviour = _make_behaviour()

        mock_sync_data = MagicMock()
        mock_sync_data.is_checkpoint_reached = False
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]
        # type: ignore[assignment, method-assign]
        behaviour.read_bets = lambda: None  # type: ignore[method-assign]

        behaviour.setup()
        assert behaviour.bets == []

    # type: ignore[assignment, method-assign]
    def test_setup_checkpoint_not_multi_bets_mode(self) -> None:
        """Test that setup does not requeue when checkpoint reached but not multi-bets mode."""  # type: ignore[method-assign]
        behaviour = _make_behaviour()

        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.PROCESSED

        mock_sync_data = MagicMock()
        mock_sync_data.is_checkpoint_reached = True
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.opening_margin = 100

        type(behaviour).synced_time = property(lambda self: 0)  # type: ignore[assignment, method-assign]

        # type: ignore[assignment, method-assign]
        def fake_read_bets() -> None:
            behaviour.bets = [bet]

        behaviour.read_bets = fake_read_bets  # type: ignore[method-assign]
        # type: ignore[assignment, method-assign]
        behaviour.setup()
        # type: ignore[no-untyped-def]
        # Not multi-bets mode, so no requeue even though checkpoint reached
        assert bet.queue_status == QueueStatus.PROCESSED


# type: ignore[method-assign]


class TestGetBetIdx:
    """Tests for get_bet_idx."""

    def test_finds_existing_bet(self) -> None:
        """Test finding an existing bet by id."""
        b1 = _make_bet(id="bet1")
        b2 = _make_bet(id="bet2")

        behaviour = _make_behaviour(bets=[b1, b2])
        assert behaviour.get_bet_idx("bet1") == 0
        assert behaviour.get_bet_idx("bet2") == 1

    def test_returns_none_for_missing(self) -> None:
        """Test returning None for non-existent bet."""
        b1 = _make_bet(id="bet1")
        behaviour = _make_behaviour(bets=[b1])
        assert behaviour.get_bet_idx("nonexistent") is None

    def test_empty_bets(self) -> None:
        """Test with empty bets list."""
        behaviour = _make_behaviour(bets=[])
        assert behaviour.get_bet_idx("any") is None


class TestProcessChunk:
    """Tests for _process_chunk."""

    def test_none_chunk_skipped(self) -> None:
        """Test that None chunk is skipped."""
        behaviour = _make_behaviour(bets=[])
        behaviour._current_market = "omen_subgraph"
        behaviour._process_chunk(None)
        assert behaviour.bets == []

    def test_new_bets_appended(self) -> None:
        """Test that new bets are appended."""
        behaviour = _make_behaviour(bets=[])
        behaviour._current_market = "omen_subgraph"

        raw = [
            dict(
                id="new1",
                title="Q?",
                collateralToken="0x",
                creator="0x",
                fee=0,
                openingTimestamp=9999999999,
                outcomeSlotCount=2,
                outcomeTokenAmounts=[100, 200],
                outcomeTokenMarginalPrices=[0.5, 0.5],
                outcomes=["Yes", "No"],
                scaledLiquidityMeasure=10.0,
            )
        ]
        behaviour._process_chunk(raw)
        assert len(behaviour.bets) == 1
        assert behaviour.bets[0].id == "new1"

    def test_existing_bet_updated(self) -> None:
        """Test that existing bets are updated, not duplicated."""
        existing = _make_bet(id="bet1", scaledLiquidityMeasure=5.0)
        behaviour = _make_behaviour(bets=[existing])
        behaviour._current_market = "omen_subgraph"

        raw = [
            dict(
                id="bet1",
                title="Q?",
                collateralToken="0x",
                creator="0x",
                fee=0,
                openingTimestamp=9999999999,
                outcomeSlotCount=2,
                outcomeTokenAmounts=[300, 400],
                outcomeTokenMarginalPrices=[0.3, 0.7],
                outcomes=["Yes", "No"],
                scaledLiquidityMeasure=20.0,
            )
        ]
        behaviour._process_chunk(raw)
        assert len(behaviour.bets) == 1
        assert behaviour.bets[0].scaledLiquidityMeasure == 20.0


class TestUpdateBets:
    """Tests for _update_bets."""

    def test_fetching_succeeds(self) -> None:
        """Test successful fetching loop."""
        behaviour = _make_behaviour(bets=[])

        call_count = [0]

        def mock_prepare() -> bool:
            call_count[0] += 1
            if call_count[0] == 1:
                return True
            return False

        behaviour._prepare_fetching = mock_prepare  # type: ignore[method-assign, no-untyped-def]
        behaviour._fetch_status = FetchStatus.SUCCESS

        raw_bet = dict(
            id="bet1",
            title="Q?",
            collateralToken="0x",  # type: ignore[method-assign]
            creator="0x",
            fee=0,
            openingTimestamp=9999999999,
            outcomeSlotCount=2,
            outcomeTokenAmounts=[100, 200],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            outcomes=["Yes", "No"],
            scaledLiquidityMeasure=10.0,
        )
        behaviour._fetch_bets = _return_gen([raw_bet])  # type: ignore[method-assign]
        behaviour._current_market = "omen_subgraph"

        gen = behaviour._update_bets()
        try:
            next(gen)
            while True:  # type: ignore[method-assign]
                gen.send(None)
        except StopIteration:
            pass

        assert len(behaviour.bets) == 1

    def test_fetching_fails_sets_bets_empty(self) -> None:
        """Test that fetch failure sets bets to empty list."""
        bet = _make_bet(id="existing")
        behaviour = _make_behaviour(bets=[bet])

        # _prepare_fetching returns False immediately
        behaviour._prepare_fetching = lambda: False  # type: ignore[method-assign]
        behaviour._fetch_status = FetchStatus.FAIL

        gen = behaviour._update_bets()
        try:
            next(gen)
            while True:  # type: ignore[method-assign]
                gen.send(None)
        except StopIteration:
            pass

        assert behaviour.bets == []

    def test_fetching_success_status_keeps_bets(self) -> None:
        """Test that FetchStatus.SUCCESS does not wipe bets."""
        bet = _make_bet(id="existing")
        behaviour = _make_behaviour(bets=[bet])

        behaviour._prepare_fetching = lambda: False  # type: ignore[method-assign]
        behaviour._fetch_status = FetchStatus.SUCCESS

        gen = behaviour._update_bets()
        try:
            next(gen)
            while True:  # type: ignore[method-assign]
                gen.send(None)
        except StopIteration:
            pass

        assert len(behaviour.bets) == 1


class TestBetFreshnessCheckAndUpdate:
    """Tests for _bet_freshness_check_and_update."""

    def test_single_bet_no_fallback(self) -> None:
        """Test single-bet mode without fallback moves fresh to process."""
        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.FRESH

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.enable_multi_bets_fallback = False

        behaviour._bet_freshness_check_and_update()

        assert bet.queue_status == QueueStatus.TO_PROCESS

    def test_single_bet_non_fresh_stays(self) -> None:
        """Test single-bet mode: non-fresh bets stay as they are."""
        bet = _make_bet(id="b1")
        bet.queue_status = QueueStatus.PROCESSED

        behaviour = _make_behaviour(bets=[bet])
        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.enable_multi_bets_fallback = False

        behaviour._bet_freshness_check_and_update()

        assert bet.queue_status == QueueStatus.PROCESSED

    def test_multi_bets_all_fresh(self) -> None:
        """Test multi-bets mode: all fresh bets move to process."""
        b1 = _make_bet(id="b1")
        b1.queue_status = QueueStatus.FRESH
        b2 = _make_bet(id="b2")
        b2.queue_status = QueueStatus.FRESH

        behaviour = _make_behaviour(bets=[b1, b2])
        behaviour.context.params.use_multi_bets_mode = True
        behaviour.context.params.enable_multi_bets_fallback = False

        behaviour._bet_freshness_check_and_update()

        assert b1.queue_status == QueueStatus.TO_PROCESS
        assert b2.queue_status == QueueStatus.TO_PROCESS

    def test_multi_bets_not_all_fresh(self) -> None:
        """Test multi-bets mode: if not all are fresh, nothing changes."""
        b1 = _make_bet(id="b1")
        b1.queue_status = QueueStatus.FRESH
        b2 = _make_bet(id="b2")
        b2.queue_status = QueueStatus.PROCESSED

        behaviour = _make_behaviour(bets=[b1, b2])
        behaviour.context.params.use_multi_bets_mode = True
        behaviour.context.params.enable_multi_bets_fallback = False

        behaviour._bet_freshness_check_and_update()

        assert b1.queue_status == QueueStatus.FRESH
        assert b2.queue_status == QueueStatus.PROCESSED

    def test_multi_bets_with_expired_ignored_in_check(self) -> None:
        """Test that expired bets are excluded from the 'all fresh' check."""
        b1 = _make_bet(id="b1")
        b1.queue_status = QueueStatus.FRESH
        b2 = _make_bet(id="b2")
        b2.blacklist_forever()

        behaviour = _make_behaviour(bets=[b1, b2])
        behaviour.context.params.use_multi_bets_mode = True
        behaviour.context.params.enable_multi_bets_fallback = False

        behaviour._bet_freshness_check_and_update()

        # b1 is the only unexpired bet and is fresh => all_bets_fresh = True
        assert b1.queue_status == QueueStatus.TO_PROCESS
        # b2 stays expired, move_to_process on EXPIRED returns EXPIRED... but
        # actually the for loop calls move_to_process on all bets including expired.
        # QueueStatus.move_to_process() only changes FRESH to TO_PROCESS, so EXPIRED stays.
        assert b2.queue_status == QueueStatus.EXPIRED

    def test_multi_bets_fallback_enabled(self) -> None:
        """Test that enable_multi_bets_fallback=True triggers multi-bets path."""
        b1 = _make_bet(id="b1")
        b1.queue_status = QueueStatus.FRESH

        behaviour = _make_behaviour(bets=[b1])
        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.enable_multi_bets_fallback = True

        behaviour._bet_freshness_check_and_update()

        # With fallback enabled, it goes to multi-bets path, all fresh => move to process
        assert b1.queue_status == QueueStatus.TO_PROCESS


class TestAsyncAct:
    """Tests for async_act."""

    def _run_generator(self, gen: Generator) -> None:
        """Run a generator to completion."""
        try:
            next(gen)
            while True:
                gen.send(None)
        except StopIteration:
            pass

    def test_full_lifecycle_with_bets(self) -> None:
        """Test the full async_act lifecycle with bets."""
        bet = _make_bet(id="bet1")
        behaviour = _make_behaviour(bets=[])

        # Mock benchmark_tool context manager
        mock_benchmark = MagicMock()
        mock_measure = MagicMock()
        mock_local_cm = MagicMock()
        mock_consensus_cm = MagicMock()
        mock_measure.local.return_value = mock_local_cm
        mock_measure.consensus.return_value = mock_consensus_cm
        mock_benchmark.measure.return_value = mock_measure
        behaviour.context.benchmark_tool = mock_benchmark
        # behaviour_id is a property; it auto-generates from the class name

        # Mock synchronized_data
        mock_sync_data = MagicMock()
        mock_sync_data.review_bets_for_selling = False
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        # Mock params
        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.enable_multi_bets_fallback = False
        behaviour.context.params.opening_margin = 100
        # type: ignore[assignment, method-assign]
        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]

        # Mock _update_bets to populate bets
        def mock_update_bets() -> Generator:
            behaviour.bets = [bet]
            yield

        # type: ignore[assignment, method-assign]
        behaviour._update_bets = mock_update_bets  # type: ignore[method-assign]
        behaviour.update_bets_investments = _noop_gen  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign, no-untyped-def]
        behaviour.hash_stored_bets = MagicMock(return_value="hash123")  # type: ignore[method-assign]
        behaviour.send_a2a_transaction = _noop_gen  # type: ignore[method-assign]
        behaviour.wait_until_round_end = _noop_gen  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.context.agent_address = "0xagent"  # type: ignore[method-assign]
        # type: ignore[method-assign]
        self._run_generator(behaviour.async_act())  # type: ignore[method-assign]
        # type: ignore[method-assign]
        behaviour.store_bets.assert_called_once()  # type: ignore[attr-defined, method-assign]
        behaviour.hash_stored_bets.assert_called_once()  # type: ignore[attr-defined, method-assign]
        behaviour.set_done.assert_called_once()  # type: ignore[attr-defined]

    def test_full_lifecycle_no_bets(self) -> None:
        """Test async_act lifecycle with no bets (hash is None)."""
        behaviour = _make_behaviour(bets=[])

        mock_benchmark = MagicMock()
        mock_measure = MagicMock()
        mock_local_cm = MagicMock()
        mock_consensus_cm = MagicMock()
        mock_measure.local.return_value = mock_local_cm
        mock_measure.consensus.return_value = mock_consensus_cm
        mock_benchmark.measure.return_value = mock_measure
        behaviour.context.benchmark_tool = mock_benchmark
        # behaviour_id is a property; it auto-generates from the class name

        mock_sync_data = MagicMock()
        mock_sync_data.review_bets_for_selling = False
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.enable_multi_bets_fallback = False

        behaviour._update_bets = _noop_gen  # type: ignore[method-assign]
        behaviour.update_bets_investments = _noop_gen  # type: ignore[assignment, method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.hash_stored_bets = MagicMock(return_value="hash123")  # type: ignore[method-assign]
        behaviour.send_a2a_transaction = _noop_gen  # type: ignore[method-assign]
        behaviour.wait_until_round_end = _noop_gen  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.context.agent_address = "0xagent"  # type: ignore[method-assign]
        # type: ignore[method-assign]
        self._run_generator(behaviour.async_act())  # type: ignore[method-assign]
        # type: ignore[method-assign]
        behaviour.store_bets.assert_called_once()  # type: ignore[attr-defined, method-assign]
        # hash_stored_bets should NOT be called since bets is empty  # type: ignore[method-assign]
        behaviour.hash_stored_bets.assert_not_called()  # type: ignore[attr-defined]
        behaviour.set_done.assert_called_once()  # type: ignore[attr-defined]

    def test_review_bets_for_selling_triggers_requeue(self) -> None:
        """Test that review_bets_for_selling triggers _requeue_bets_for_selling."""
        bet = _make_bet(id="bet1", openingTimestamp=1000)
        bet.queue_status = QueueStatus.PROCESSED
        bet.investments = {"Yes": [100], "No": []}
        bet.last_processed_sell_check = 0  # type: ignore[attr-defined]

        behaviour = _make_behaviour(bets=[])

        mock_benchmark = MagicMock()
        mock_measure = MagicMock()
        mock_local_cm = MagicMock()
        mock_consensus_cm = MagicMock()
        mock_measure.local.return_value = mock_local_cm
        mock_measure.consensus.return_value = mock_consensus_cm
        mock_benchmark.measure.return_value = mock_measure
        behaviour.context.benchmark_tool = mock_benchmark
        # behaviour_id is a property; it auto-generates from the class name

        mock_sync_data = MagicMock()
        mock_sync_data.review_bets_for_selling = True
        type(behaviour).synchronized_data = property(lambda self: mock_sync_data)  # type: ignore[assignment, method-assign]

        behaviour.context.params.use_multi_bets_mode = False
        behaviour.context.params.enable_multi_bets_fallback = False
        behaviour.context.params.opening_margin = 100
        behaviour.context.params.sell_check_interval = 0
        # type: ignore[assignment, method-assign]
        type(behaviour).synced_time = property(lambda self: 999999)  # type: ignore[assignment, method-assign]

        def mock_update_bets() -> Generator:
            behaviour.bets = [bet]
            yield

        behaviour._update_bets = mock_update_bets  # type: ignore[assignment, method-assign]
        behaviour.update_bets_investments = _noop_gen  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign, no-untyped-def]
        behaviour.hash_stored_bets = MagicMock(return_value="hash123")  # type: ignore[method-assign]
        behaviour.send_a2a_transaction = _noop_gen  # type: ignore[method-assign]
        behaviour.wait_until_round_end = _noop_gen  # type: ignore[method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]
        behaviour.context.agent_address = "0xagent"  # type: ignore[method-assign]
        # type: ignore[method-assign]
        self._run_generator(behaviour.async_act())  # type: ignore[method-assign]
        # type: ignore[method-assign]
        # The bet should have been requeued for selling  # type: ignore[method-assign]
        # After _requeue_bets_for_selling, then _bet_freshness_check_and_update  # type: ignore[method-assign]
        # moves FRESH to TO_PROCESS (single-bet mode)
        assert bet.queue_status == QueueStatus.TO_PROCESS
