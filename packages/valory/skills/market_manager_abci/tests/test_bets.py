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

"""Tests for the bets module of the MarketManager ABCI application."""

import json
import sys
from typing import Any, Dict

import pytest

from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetsDecoder,
    BetsEncoder,
    BinaryOutcome,
    DAY_IN_SECONDS,
    MARKET_TO_PLATFORM,
    PredictionResponse,
    QueueStatus,
    get_default_prediction_response,
    serialize_bets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bet(**overrides: Any) -> Bet:
    """Create a valid binary Bet with sensible defaults. Override any field via kwargs."""
    defaults: Dict[str, Any] = dict(
        id="0xabc123",
        market="omen_subgraph",
        title="Will it rain tomorrow?",
        collateralToken="0xtoken",
        creator="0xcreator",
        fee=10000000000000000,
        openingTimestamp=1700000000,
        outcomeSlotCount=2,
        outcomeTokenAmounts=[10, 20],
        outcomeTokenMarginalPrices=[0.4, 0.6],
        outcomes=["Yes", "No"],
        scaledLiquidityMeasure=5.0,
    )
    defaults.update(overrides)
    return Bet(**defaults)


def _make_prediction(**overrides: Any) -> PredictionResponse:
    """Create a PredictionResponse with sensible defaults."""
    defaults: Dict[str, Any] = dict(
        p_yes=0.6, p_no=0.4, confidence=0.8, info_utility=0.7
    )
    defaults.update(overrides)
    return PredictionResponse(**defaults)


# ===========================================================================
# 1. BinaryOutcome
# ===========================================================================


class TestBinaryOutcome:
    """Tests for the BinaryOutcome enum."""

    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("yes", BinaryOutcome.YES),
            ("Yes", BinaryOutcome.YES),
            ("YES", BinaryOutcome.YES),
            ("no", BinaryOutcome.NO),
            ("No", BinaryOutcome.NO),
            ("NO", BinaryOutcome.NO),
        ],
    )
    def test_from_string_valid(self, input_str: str, expected: BinaryOutcome) -> None:
        """Test from_string with valid inputs in various cases."""
        assert BinaryOutcome.from_string(input_str) == expected

    @pytest.mark.parametrize("invalid", ["maybe", "unknown", "", "yesno", "123"])
    def test_from_string_invalid_raises(self, invalid: str) -> None:
        """Test from_string raises ValueError for invalid inputs."""
        with pytest.raises(ValueError, match="Invalid binary outcome"):
            BinaryOutcome.from_string(invalid)


# ===========================================================================
# 2. QueueStatus
# ===========================================================================


class TestQueueStatus:
    """Tests for the QueueStatus enum helper methods."""

    # is_fresh ---------------------------------------------------------------
    def test_is_fresh_true(self) -> None:
        """Test that FRESH status is identified as fresh."""
        assert QueueStatus.FRESH.is_fresh() is True

    @pytest.mark.parametrize(
        "status",
        [
            QueueStatus.EXPIRED,
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
            QueueStatus.BENCHMARKING_DONE,
        ],
    )
    def test_is_fresh_false(self, status: QueueStatus) -> None:
        """Test that non-FRESH statuses return False for is_fresh."""
        assert status.is_fresh() is False

    # is_expired -------------------------------------------------------------
    def test_is_expired_true(self) -> None:
        """Test that EXPIRED status is identified as expired."""
        assert QueueStatus.EXPIRED.is_expired() is True

    @pytest.mark.parametrize(
        "status",
        [
            QueueStatus.FRESH,
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
            QueueStatus.BENCHMARKING_DONE,
        ],
    )
    def test_is_expired_false(self, status: QueueStatus) -> None:
        """Test that non-EXPIRED statuses return False for is_expired."""
        assert status.is_expired() is False

    # move_to_process --------------------------------------------------------
    def test_move_to_process_from_fresh(self) -> None:
        """Test FRESH moves to TO_PROCESS."""
        assert QueueStatus.FRESH.move_to_process() == QueueStatus.TO_PROCESS

    @pytest.mark.parametrize(
        "status",
        [
            QueueStatus.EXPIRED,
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
            QueueStatus.BENCHMARKING_DONE,
        ],
    )
    def test_move_to_process_unchanged(self, status: QueueStatus) -> None:
        """Test non-FRESH statuses remain the same after move_to_process."""
        assert status.move_to_process() == status

    # move_to_fresh ----------------------------------------------------------
    @pytest.mark.parametrize(
        "status",
        [
            QueueStatus.FRESH,
            QueueStatus.TO_PROCESS,
            QueueStatus.PROCESSED,
            QueueStatus.REPROCESSED,
        ],
    )
    def test_move_to_fresh_success(self, status: QueueStatus) -> None:
        """Test statuses that should move back to FRESH."""
        assert status.move_to_fresh() == QueueStatus.FRESH

    @pytest.mark.parametrize(
        "status",
        [
            QueueStatus.EXPIRED,
            QueueStatus.BENCHMARKING_DONE,
        ],
    )
    def test_move_to_fresh_no_change(self, status: QueueStatus) -> None:
        """Test EXPIRED and BENCHMARKING_DONE are not changed by move_to_fresh."""
        assert status.move_to_fresh() == status

    # next_status ------------------------------------------------------------
    def test_next_status_to_process(self) -> None:
        """Test TO_PROCESS advances to PROCESSED."""
        assert QueueStatus.TO_PROCESS.next_status() == QueueStatus.PROCESSED

    def test_next_status_processed(self) -> None:
        """Test PROCESSED advances to REPROCESSED."""
        assert QueueStatus.PROCESSED.next_status() == QueueStatus.REPROCESSED

    def test_next_status_reprocessed_stays(self) -> None:
        """Test REPROCESSED stays as REPROCESSED (terminal for next_status)."""
        assert QueueStatus.REPROCESSED.next_status() == QueueStatus.REPROCESSED

    @pytest.mark.parametrize(
        "status",
        [
            QueueStatus.FRESH,
            QueueStatus.EXPIRED,
            QueueStatus.BENCHMARKING_DONE,
        ],
    )
    def test_next_status_other_goes_fresh(self, status: QueueStatus) -> None:
        """Test other statuses reset to FRESH via next_status."""
        assert status.next_status() == QueueStatus.FRESH


# ===========================================================================
# 3. PredictionResponse
# ===========================================================================


class TestPredictionResponse:
    """Tests for PredictionResponse initialization and properties."""

    def test_valid_creation(self) -> None:
        """Test creation with valid probabilities."""
        pr = PredictionResponse(p_yes=0.7, p_no=0.3, confidence=0.9, info_utility=0.5)
        assert pr.p_yes == 0.7
        assert pr.p_no == 0.3
        assert pr.confidence == 0.9
        assert pr.info_utility == 0.5

    @pytest.mark.parametrize(
        "kwargs",
        [
            # probabilities don't sum to 1
            dict(p_yes=0.6, p_no=0.6, confidence=0.5, info_utility=0.5),
            # negative probability
            dict(p_yes=-0.1, p_no=1.1, confidence=0.5, info_utility=0.5),
            # probability greater than 1
            dict(p_yes=1.5, p_no=-0.5, confidence=0.5, info_utility=0.5),
            # confidence out of range
            dict(p_yes=0.5, p_no=0.5, confidence=1.5, info_utility=0.5),
            # info_utility out of range
            dict(p_yes=0.5, p_no=0.5, confidence=0.5, info_utility=-0.1),
        ],
    )
    def test_invalid_probabilities_raise(self, kwargs: Dict[str, float]) -> None:
        """Test that invalid probability values raise ValueError."""
        with pytest.raises(ValueError, match="Invalid prediction response"):
            PredictionResponse(**kwargs)

    # vote -------------------------------------------------------------------
    def test_vote_yes(self) -> None:
        """Test vote returns 0 when p_yes > p_no (i.e., vote YES)."""
        pr = PredictionResponse(p_yes=0.7, p_no=0.3, confidence=0.8, info_utility=0.5)
        assert pr.vote == 0

    def test_vote_no(self) -> None:
        """Test vote returns 1 when p_no > p_yes (i.e., vote NO)."""
        pr = PredictionResponse(p_yes=0.3, p_no=0.7, confidence=0.8, info_utility=0.5)
        assert pr.vote == 1

    def test_vote_equal_returns_none(self) -> None:
        """Test vote returns None when p_yes == p_no."""
        pr = PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.8, info_utility=0.5)
        assert pr.vote is None

    # win_probability --------------------------------------------------------
    def test_win_probability_yes(self) -> None:
        """Test win_probability returns max(p_yes, p_no) when p_yes is higher."""
        pr = PredictionResponse(p_yes=0.8, p_no=0.2, confidence=0.9, info_utility=0.5)
        assert pr.win_probability == 0.8

    def test_win_probability_no(self) -> None:
        """Test win_probability returns max(p_yes, p_no) when p_no is higher."""
        pr = PredictionResponse(p_yes=0.3, p_no=0.7, confidence=0.9, info_utility=0.5)
        assert pr.win_probability == 0.7

    def test_win_probability_equal(self) -> None:
        """Test win_probability when probabilities are equal."""
        pr = PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.9, info_utility=0.5)
        assert pr.win_probability == 0.5


# ===========================================================================
# 4. get_default_prediction_response
# ===========================================================================


class TestGetDefaultPredictionResponse:
    """Tests for the get_default_prediction_response factory function."""

    def test_returns_equal_probabilities(self) -> None:
        """Test that the default response has 0.5 for all fields."""
        pr = get_default_prediction_response()
        assert pr.p_yes == 0.5
        assert pr.p_no == 0.5
        assert pr.confidence == 0.5
        assert pr.info_utility == 0.5

    def test_vote_is_none(self) -> None:
        """Test that the default response vote is None (p_yes == p_no)."""
        pr = get_default_prediction_response()
        assert pr.vote is None


# ===========================================================================
# 5. Bet
# ===========================================================================


class TestBetPostInit:
    """Tests for Bet.__post_init__ logic (validation, casting, investments init)."""

    def test_investments_initialized_with_yes_and_no(self) -> None:
        """Test that __post_init__ populates empty investments with Yes and No keys."""
        bet = _make_bet()
        assert "Yes" in bet.investments
        assert "No" in bet.investments
        assert bet.investments["Yes"] == []
        assert bet.investments["No"] == []

    def test_investments_preserved_if_already_set(self) -> None:
        """Test that pre-existing investments are preserved."""
        bet = _make_bet(investments={"Yes": [100], "No": [200]})
        assert bet.investments["Yes"] == [100]
        assert bet.investments["No"] == [200]

    def test_validate_nulls_blacklists(self) -> None:
        """Test that a bet with a null necessary value is blacklisted."""
        bet = _make_bet(market=None)  # type: ignore
        assert bet.outcomes is None
        assert bet.processed_timestamp == sys.maxsize
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_validate_null_string_blacklists(self) -> None:
        """Test that a bet with a 'null' string value is blacklisted."""
        bet = _make_bet(title="null")
        assert bet.outcomes is None
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_validate_mismatching_outcomes_blacklists(self) -> None:
        """Test that mismatching outcome counts lead to blacklisting."""
        bet = _make_bet(
            outcomeSlotCount=3,
            outcomes=["Yes", "No"],  # only 2, but slot count says 3
        )
        assert bet.outcomes is None
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_zero_liquidity_blacklists(self) -> None:
        """Test that zero scaledLiquidityMeasure blacklists the bet."""
        bet = _make_bet(scaledLiquidityMeasure=0)
        assert bet.outcomes is None
        assert bet.queue_status == QueueStatus.EXPIRED


class TestBetNegRisk:
    """Tests for Bet.neg_risk field."""

    def test_neg_risk_defaults_to_false(self) -> None:
        """Test that neg_risk defaults to False when not provided."""
        bet = _make_bet()
        assert bet.neg_risk is False

    def test_neg_risk_stores_true(self) -> None:
        """Test that neg_risk=True is stored correctly."""
        bet = _make_bet(neg_risk=True)
        assert bet.neg_risk is True

    def test_neg_risk_round_trip(self) -> None:
        """Test that neg_risk survives a JSON round-trip."""
        original = _make_bet(neg_risk=True)
        encoded = json.dumps(original, cls=BetsEncoder)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.neg_risk is True


class TestBetLt:
    """Tests for Bet.__lt__."""

    def test_less_than(self) -> None:
        """Test that a bet with lower liquidity is less than one with higher."""
        a = _make_bet(scaledLiquidityMeasure=1.0)
        b = _make_bet(scaledLiquidityMeasure=5.0)
        assert a < b

    def test_not_less_than(self) -> None:
        """Test that a bet with higher liquidity is not less than one with lower."""
        a = _make_bet(scaledLiquidityMeasure=10.0)
        b = _make_bet(scaledLiquidityMeasure=5.0)
        assert not (a < b)


class TestBetInvestmentProperties:
    """Tests for investment-related properties on Bet."""

    def test_yes_investments(self) -> None:
        """Test the yes_investments property."""
        bet = _make_bet(investments={"Yes": [100, 200], "No": [50]})
        assert bet.yes_investments == [100, 200]

    def test_no_investments(self) -> None:
        """Test the no_investments property."""
        bet = _make_bet(investments={"Yes": [100], "No": [50, 75]})
        assert bet.no_investments == [50, 75]

    def test_n_yes_bets(self) -> None:
        """Test n_yes_bets returns the count of yes investments."""
        bet = _make_bet(investments={"Yes": [10, 20, 30], "No": []})
        assert bet.n_yes_bets == 3

    def test_n_no_bets(self) -> None:
        """Test n_no_bets returns the count of no investments."""
        bet = _make_bet(investments={"Yes": [], "No": [10, 20]})
        assert bet.n_no_bets == 2

    def test_n_bets(self) -> None:
        """Test n_bets returns the total count of all investments."""
        bet = _make_bet(investments={"Yes": [10], "No": [20, 30]})
        assert bet.n_bets == 3

    def test_invested_amount_yes(self) -> None:
        """Test invested_amount_yes returns the sum of yes investments."""
        bet = _make_bet(investments={"Yes": [100, 200], "No": []})
        assert bet.invested_amount_yes == 300

    def test_invested_amount_no(self) -> None:
        """Test invested_amount_no returns the sum of no investments."""
        bet = _make_bet(investments={"Yes": [], "No": [50, 75]})
        assert bet.invested_amount_no == 125

    def test_invested_amount(self) -> None:
        """Test invested_amount returns the total sum across yes and no."""
        bet = _make_bet(investments={"Yes": [100], "No": [200]})
        assert bet.invested_amount == 300

    def test_empty_investments(self) -> None:
        """Test investment properties with empty lists."""
        bet = _make_bet()
        assert bet.n_bets == 0
        assert bet.invested_amount == 0


class TestBetOppositeVote:
    """Tests for Bet.opposite_vote static method."""

    def test_opposite_of_zero(self) -> None:
        """Test that the opposite of 0 (Yes) is 1 (No)."""
        assert Bet.opposite_vote(0) == 1

    def test_opposite_of_one(self) -> None:
        """Test that the opposite of 1 (No) is 0 (Yes)."""
        assert Bet.opposite_vote(1) == 0


class TestBetBlacklistForever:
    """Tests for Bet.blacklist_forever."""

    def test_blacklist_forever(self) -> None:
        """Test that blacklist_forever sets outcomes, timestamp, and status."""
        bet = _make_bet()
        bet.blacklist_forever()
        assert bet.outcomes is None
        assert bet.processed_timestamp == sys.maxsize
        assert bet.queue_status == QueueStatus.EXPIRED


class TestBetGetOutcome:
    """Tests for Bet.get_outcome."""

    def test_get_outcome_yes(self) -> None:
        """Test retrieving the yes outcome by index."""
        bet = _make_bet()
        assert bet.get_outcome(0) == "Yes"

    def test_get_outcome_no(self) -> None:
        """Test retrieving the no outcome by index."""
        bet = _make_bet()
        assert bet.get_outcome(1) == "No"

    def test_get_outcome_none_outcomes_raises(self) -> None:
        """Test that get_outcome raises ValueError when outcomes is None."""
        bet = _make_bet()
        bet.outcomes = None
        with pytest.raises(ValueError, match="incorrect outcomes list of `None`"):
            bet.get_outcome(0)

    def test_get_outcome_key_error(self) -> None:
        """Test that get_outcome wraps KeyError into ValueError for invalid index."""
        # outcomes as a dict to trigger KeyError instead of IndexError
        bet = _make_bet()
        # Replace outcomes list with a dict-like object that raises KeyError
        bet.outcomes = {0: "Yes", 1: "No"}  # type: ignore
        # Index 5 does not exist in this dict, triggers KeyError
        with pytest.raises(ValueError, match="Cannot get outcome with index"):
            bet.get_outcome(5)


class TestBetGetBinaryOutcome:
    """Tests for Bet._get_binary_outcome and the yes/no properties."""

    def test_yes_property(self) -> None:
        """Test that the yes property returns the capitalized 'Yes' outcome."""
        bet = _make_bet()
        assert bet.yes == "Yes"

    def test_no_property(self) -> None:
        """Test that the no property returns the capitalized 'No' outcome."""
        bet = _make_bet()
        assert bet.no == "No"

    def test_non_binary_raises_yes(self) -> None:
        """Test that accessing yes on a non-binary bet raises ValueError."""
        bet = _make_bet(
            outcomeSlotCount=3,
            outcomes=["A", "B", "C"],
            outcomeTokenAmounts=[10, 20, 30],
            outcomeTokenMarginalPrices=[0.3, 0.3, 0.4],
        )
        with pytest.raises(ValueError, match="only available for binary questions"):
            _ = bet.yes

    def test_non_binary_raises_no(self) -> None:
        """Test that accessing no on a non-binary bet raises ValueError."""
        bet = _make_bet(
            outcomeSlotCount=3,
            outcomes=["A", "B", "C"],
            outcomeTokenAmounts=[10, 20, 30],
            outcomeTokenMarginalPrices=[0.3, 0.3, 0.4],
        )
        with pytest.raises(ValueError, match="only available for binary questions"):
            _ = bet.no


class TestBetGetVoteAmount:
    """Tests for Bet.get_vote_amount."""

    def test_get_vote_amount_yes(self) -> None:
        """Test getting the amount invested on a yes vote."""
        bet = _make_bet(investments={"Yes": [100, 200], "No": [50]})
        assert bet.get_vote_amount(0) == 300

    def test_get_vote_amount_no(self) -> None:
        """Test getting the amount invested on a no vote."""
        bet = _make_bet(investments={"Yes": [100], "No": [50, 75]})
        assert bet.get_vote_amount(1) == 125


class TestBetResetInvestments:
    """Tests for Bet.reset_investments."""

    def test_reset_investments(self) -> None:
        """Test that reset_investments clears all investment lists."""
        bet = _make_bet(investments={"Yes": [100, 200], "No": [50]})
        bet.reset_investments()
        assert bet.investments["Yes"] == []
        assert bet.investments["No"] == []


class TestBetAppendInvestmentAmount:
    """Tests for Bet.append_investment_amount."""

    def test_append_to_existing_key(self) -> None:
        """Test appending to an existing investment key."""
        bet = _make_bet(investments={"Yes": [100], "No": []})
        bet.append_investment_amount(0, 200)
        assert bet.investments["Yes"] == [100, 200]

    def test_append_creates_key_if_missing(self) -> None:
        """Test appending to a missing key creates the list."""
        bet = _make_bet()
        # Remove the "Yes" key to test the creation path
        del bet.investments["Yes"]
        bet.append_investment_amount(0, 300)
        assert bet.investments["Yes"] == [300]


class TestBetSetInvestmentAmount:
    """Tests for Bet.set_investment_amount."""

    def test_set_investment_amount(self) -> None:
        """Test setting the investment amount replaces the list with a single value."""
        bet = _make_bet(investments={"Yes": [100, 200], "No": []})
        bet.set_investment_amount(0, 500)
        assert bet.investments["Yes"] == [500]


class TestBetUpdateInvestments:
    """Tests for Bet.update_investments.

    NOTE: There is a duplicate `if vote is None` check (lines 340-341 and 343-344)
    in the source code. The second check is dead code because the first check
    already returns False. This test exercises the vote=None path to confirm the
    first guard returns False.
    """

    def test_vote_none_returns_false(self) -> None:
        """Test that update_investments returns False when vote is None.

        This also exposes the dead code bug: the second `if vote is None`
        check on line 343 is never reached because the first check on
        line 340 already returns False.
        """
        bet = _make_bet(
            prediction_response=PredictionResponse(
                p_yes=0.5, p_no=0.5, confidence=0.5, info_utility=0.5
            )
        )
        assert bet.prediction_response.vote is None
        result = bet.update_investments(100)
        assert result is False

    def test_amount_zero_resets(self) -> None:
        """Test that amount=0 sets the investment to [0]."""
        pred = _make_prediction(p_yes=0.7, p_no=0.3)
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100, 200], "No": []},
        )
        result = bet.update_investments(0)
        assert result is True
        assert bet.investments["Yes"] == [0]

    def test_normal_append(self) -> None:
        """Test that a normal amount is appended to the correct outcome."""
        pred = _make_prediction(p_yes=0.7, p_no=0.3)  # vote = 0 (Yes)
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100], "No": []},
        )
        result = bet.update_investments(200)
        assert result is True
        assert bet.investments["Yes"] == [100, 200]

    def test_append_to_no(self) -> None:
        """Test that a no vote appends to the No investment list."""
        pred = _make_prediction(p_yes=0.3, p_no=0.7)  # vote = 1 (No)
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [], "No": [50]},
        )
        result = bet.update_investments(75)
        assert result is True
        assert bet.investments["No"] == [50, 75]

    def test_uses_strategy_vote_not_mech_vote(self) -> None:
        """Investment should track under strategy_vote, not prediction_response.vote."""
        # Mech says YES (p_yes=0.7, vote=0), but strategy picked NO (strategy_vote=1)
        pred = _make_prediction(p_yes=0.7, p_no=0.3)
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [], "No": []},
        )
        bet.strategy_vote = 1  # strategy picked NO
        result = bet.update_investments(100)
        assert result is True
        # Should be tracked under "No" (strategy_vote=1), not "Yes" (mech vote=0)
        assert bet.investments["No"] == [100]
        assert bet.investments["Yes"] == []


class TestBetUpdateMarketInfo:
    """Tests for Bet.update_market_info."""

    def test_blacklisted_source_bet(self) -> None:
        """Test update_market_info blacklists when source (self) is blacklisted."""
        bet = _make_bet()
        bet.processed_timestamp = sys.maxsize  # blacklisted
        other = _make_bet()
        bet.update_market_info(other)
        assert bet.outcomes is None
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_blacklisted_target_bet(self) -> None:
        """Test update_market_info blacklists when the incoming bet is blacklisted."""
        bet = _make_bet()
        other = _make_bet()
        other.processed_timestamp = sys.maxsize  # blacklisted
        bet.update_market_info(other)
        assert bet.outcomes is None
        assert bet.queue_status == QueueStatus.EXPIRED

    def test_normal_update(self) -> None:
        """Test normal market info update copies amounts, prices, and liquidity."""
        bet = _make_bet(
            outcomeTokenAmounts=[10, 20],
            outcomeTokenMarginalPrices=[0.4, 0.6],
            scaledLiquidityMeasure=5.0,
        )
        other = _make_bet(
            outcomeTokenAmounts=[30, 40],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            scaledLiquidityMeasure=10.0,
        )
        bet.update_market_info(other)
        assert bet.outcomeTokenAmounts == [30, 40]
        assert bet.outcomeTokenMarginalPrices == [0.5, 0.5]
        assert bet.scaledLiquidityMeasure == 10.0

    def test_neg_risk_updated(self) -> None:
        """Test that update_market_info copies neg_risk from the incoming bet."""
        bet = _make_bet(neg_risk=False)
        other = _make_bet(neg_risk=True)
        bet.update_market_info(other)
        assert bet.neg_risk is True

    def test_update_market_info_copies_poly_tags(self) -> None:
        """update_market_info carries poly_tags from the incoming bet.

        Pre-PR bets deserialize from multi_bets.json with poly_tags=[]. Without
        this copy, the legacy-blacklist loop never sees the real tags and can
        never blacklist a legacy bet whose tag was later added to the disable
        list.
        """
        existing = _make_bet(id="b1", poly_tags=[])
        incoming = _make_bet(id="b1", poly_tags=["politics", "trump-iran"])
        existing.update_market_info(incoming)
        assert existing.poly_tags == ["politics", "trump-iran"]


class TestBetSetProcessedSellCheck:
    """Tests for Bet.set_processed_sell_check."""

    def test_sets_attribute(self) -> None:
        """Test that set_processed_sell_check sets the attribute on the bet."""
        bet = _make_bet()
        bet.set_processed_sell_check(123456)
        assert bet.last_processed_sell_check == 123456  # type: ignore[attr-defined]


class TestBetRebetAllowed:
    """Tests for Bet.rebet_allowed."""

    def test_first_time_always_allowed(self) -> None:
        """Test that rebet is always allowed when there are no prior bets."""
        bet = _make_bet()
        new_pred = _make_prediction(p_yes=0.8, p_no=0.2)
        assert bet.rebet_allowed(new_pred, liquidity=100, potential_net_profit=50)

    def test_same_vote_more_confident_and_higher_liquidity(self) -> None:
        """Test same vote rebet allowed when more confident with higher liquidity."""
        pred = _make_prediction(p_yes=0.7, p_no=0.3)
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100], "No": []},
            position_liquidity=200,
        )
        new_pred = _make_prediction(p_yes=0.6, p_no=0.4)  # less confident
        result = bet.rebet_allowed(new_pred, liquidity=100, potential_net_profit=0)
        assert result is True

    def test_same_vote_less_confident(self) -> None:
        """Test same vote rebet blocked when new prediction is more confident."""
        pred = _make_prediction(p_yes=0.6, p_no=0.4)
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100], "No": []},
            position_liquidity=200,
        )
        new_pred = _make_prediction(p_yes=0.9, p_no=0.1)  # more confident
        result = bet.rebet_allowed(new_pred, liquidity=100, potential_net_profit=0)
        assert result is False

    def test_different_vote_more_confident_profit_increases(self) -> None:
        """Test different vote rebet allowed when more confident and profit increases."""
        pred = _make_prediction(p_yes=0.7, p_no=0.3)  # vote=0
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100], "No": []},
            potential_net_profit=500,
        )
        new_pred = _make_prediction(p_yes=0.4, p_no=0.6)  # vote=1 (different)
        result = bet.rebet_allowed(new_pred, liquidity=100, potential_net_profit=300)
        assert result is True

    def test_different_vote_less_confident(self) -> None:
        """Test different vote rebet blocked when new prediction is more confident."""
        pred = _make_prediction(p_yes=0.6, p_no=0.4)  # vote=0
        bet = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100], "No": []},
            potential_net_profit=500,
        )
        new_pred = _make_prediction(p_yes=0.3, p_no=0.7)  # vote=1, more confident
        result = bet.rebet_allowed(new_pred, liquidity=100, potential_net_profit=300)
        assert result is False

    def test_rebet_uses_strategy_vote_for_comparison(self) -> None:
        """Rebet should compare strategy_vote, not prediction_response.vote."""
        # Previous bet: mech said YES (p_yes=0.7), strategy picked NO (strategy_vote=1)
        prev_pred = _make_prediction(p_yes=0.7, p_no=0.3)  # mech vote=0
        bet = _make_bet(
            prediction_response=prev_pred,
            position_liquidity=200,
            potential_net_profit=500,
            investments={"Yes": [], "No": [100]},  # n_bets > 0
        )
        bet.strategy_vote = 1  # strategy picked NO last time

        # New bet: mech says YES again (p_yes=0.6), strategy picks NO again
        new_pred = _make_prediction(p_yes=0.6, p_no=0.4)  # mech vote=0
        new_strategy_vote = 1  # strategy picks NO again

        # This is a same-side rebet (both strategy_vote=1).
        # Using mech votes (both=0) would also be same-side, but for wrong reason.
        # The test verifies strategy_vote is used, not mech vote.
        result = bet.rebet_allowed(
            new_pred,
            liquidity=100,
            potential_net_profit=300,
            new_vote=new_strategy_vote,
        )
        # Same side, more confident (0.7 >= 0.6), higher liquidity (200 >= 100)
        assert result is True


class TestBetIsReadyToSell:
    """Tests for Bet.is_ready_to_sell."""

    def test_ready_to_sell(self) -> None:
        """Test bet is ready to sell after opening + margin + 1 day with investments."""
        opening = 1000000
        margin = 100
        current = opening - margin + DAY_IN_SECONDS + 1
        bet = _make_bet(
            openingTimestamp=opening,
            investments={"Yes": [100], "No": []},
        )
        assert bet.is_ready_to_sell(current, margin) is True

    def test_not_ready_too_early(self) -> None:
        """Test bet is not ready to sell if not enough time has passed."""
        opening = 1000000
        margin = 100
        current = opening - margin + DAY_IN_SECONDS - 1  # just before threshold
        bet = _make_bet(
            openingTimestamp=opening,
            investments={"Yes": [100], "No": []},
        )
        assert bet.is_ready_to_sell(current, margin) is False

    def test_not_ready_no_investment(self) -> None:
        """Test bet is not ready to sell if there are no investments."""
        opening = 1000000
        margin = 100
        current = opening - margin + DAY_IN_SECONDS + 1
        bet = _make_bet(openingTimestamp=opening)
        assert bet.is_ready_to_sell(current, margin) is False


# ===========================================================================
# 6. BetsEncoder
# ===========================================================================


class TestBetsEncoder:
    """Tests for the BetsEncoder JSON encoder."""

    def test_encode_dataclass(self) -> None:
        """Test encoding a dataclass instance (PredictionResponse)."""
        pr = PredictionResponse(p_yes=0.6, p_no=0.4, confidence=0.8, info_utility=0.7)
        encoded = json.dumps(pr, cls=BetsEncoder)
        data = json.loads(encoded)
        assert data["p_yes"] == 0.6
        assert data["p_no"] == 0.4

    def test_encode_queue_status(self) -> None:
        """Test encoding a QueueStatus enum value."""
        encoded = json.dumps({"status": QueueStatus.PROCESSED}, cls=BetsEncoder)
        data = json.loads(encoded)
        assert data["status"] == 2

    def test_encode_bet(self) -> None:
        """Test encoding a full Bet instance."""
        bet = _make_bet()
        encoded = json.dumps(bet, cls=BetsEncoder)
        data = json.loads(encoded)
        assert data["id"] == "0xabc123"
        assert data["queue_status"] == 0  # FRESH -> 0

    def test_encode_non_supported_type_raises(self) -> None:
        """Test that encoding an unsupported type raises TypeError."""
        encoder = BetsEncoder()
        with pytest.raises(TypeError):
            encoder.default(object())


# ===========================================================================
# 7. BetsDecoder
# ===========================================================================


class TestBetsDecoder:
    """Tests for the BetsDecoder JSON decoder."""

    def test_decode_prediction_response(self) -> None:
        """Test decoding a PredictionResponse from JSON."""
        pr = PredictionResponse(p_yes=0.6, p_no=0.4, confidence=0.8, info_utility=0.7)
        encoded = json.dumps(pr, cls=BetsEncoder)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, PredictionResponse)
        assert decoded.p_yes == 0.6

    def test_decode_bet(self) -> None:
        """Test decoding a Bet from JSON."""
        bet = _make_bet(
            investments={"Yes": [100], "No": [200]},
            queue_status=QueueStatus.PROCESSED,
        )
        encoded = json.dumps(bet, cls=BetsEncoder)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.id == "0xabc123"
        assert decoded.queue_status == QueueStatus.PROCESSED
        assert decoded.investments["Yes"] == [100]

    def test_decode_partial_bet_with_id(self) -> None:
        """Test decoding a dict with id key but not all Bet fields."""
        partial_data = {
            "id": "0xpartial",
            "market": "test_market",
            "title": "Partial bet",
            "collateralToken": "0xtoken",
            "creator": "0xcreator",
            "fee": 1000,
            "openingTimestamp": 1700000000,
            "outcomeSlotCount": 2,
            "outcomeTokenAmounts": [10, 20],
            "outcomeTokenMarginalPrices": [0.4, 0.6],
            "outcomes": ["Yes", "No"],
            "scaledLiquidityMeasure": 5.0,
            "extra_field": "should_be_ignored",
        }
        encoded = json.dumps(partial_data)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.id == "0xpartial"

    def test_decode_partial_bet_with_queue_status(self) -> None:
        """Test decoding a partial Bet that includes queue_status."""
        partial_data = {
            "id": "0xpartial",
            "market": "test_market",
            "title": "Partial bet",
            "collateralToken": "0xtoken",
            "creator": "0xcreator",
            "fee": 1000,
            "openingTimestamp": 1700000000,
            "outcomeSlotCount": 2,
            "outcomeTokenAmounts": [10, 20],
            "outcomeTokenMarginalPrices": [0.4, 0.6],
            "outcomes": ["Yes", "No"],
            "scaledLiquidityMeasure": 5.0,
            "queue_status": 2,
            "extra_field": "ignored",
        }
        encoded = json.dumps(partial_data)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.queue_status == QueueStatus.PROCESSED

    def test_decode_non_matching_dict(self) -> None:
        """Test that a dict with no matching structure is returned as-is."""
        data = {"foo": "bar", "baz": 42}
        encoded = json.dumps(data)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, dict)
        assert decoded == {"foo": "bar", "baz": 42}

    def test_old_json_without_strategy_vote_deserializes(self) -> None:
        """Old bet JSON missing strategy_vote field should deserialize with None default."""
        bet = _make_bet()
        encoded = json.dumps(bet, cls=BetsEncoder)
        # Remove strategy_vote from the serialized JSON to simulate old format
        data = json.loads(encoded)
        data.pop("strategy_vote", None)
        old_json = json.dumps(data)
        decoded = json.loads(old_json, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.strategy_vote is None

    def test_new_json_with_strategy_vote_round_trips(self) -> None:
        """New bet JSON with strategy_vote should round-trip correctly."""
        bet = _make_bet()
        bet.strategy_vote = 1
        encoded = json.dumps(bet, cls=BetsEncoder)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.strategy_vote == 1

    def test_old_json_without_poly_tags_deserializes(self) -> None:
        """Legacy bet JSON missing poly_tags should deserialize with [] default."""
        bet = _make_bet()
        encoded = json.dumps(bet, cls=BetsEncoder)
        data = json.loads(encoded)
        data.pop("poly_tags", None)
        legacy_json = json.dumps(data)
        decoded = json.loads(legacy_json, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.poly_tags == []

    def test_new_json_with_poly_tags_round_trips(self) -> None:
        """New bet JSON with poly_tags should round-trip correctly."""
        bet = _make_bet(poly_tags=["politics", "trump-iran"])
        encoded = json.dumps(bet, cls=BetsEncoder)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.poly_tags == ["politics", "trump-iran"]


# ===========================================================================
# 8. serialize_bets
# ===========================================================================


class TestSerializeBets:
    """Tests for the serialize_bets function."""

    def test_empty_list_returns_none(self) -> None:
        """Test that an empty list returns None."""
        assert serialize_bets([]) is None

    def test_non_empty_list_returns_json(self) -> None:
        """Test that a non-empty list returns a valid JSON string."""
        bet = _make_bet()
        result = serialize_bets([bet])
        assert result is not None
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "0xabc123"


# ===========================================================================
# 9. Round-trip encoding/decoding
# ===========================================================================


class TestRoundTrip:
    """Test that encoding and decoding bets preserves the data."""

    def test_bet_round_trip(self) -> None:
        """Test that a Bet survives a JSON round-trip."""
        pred = _make_prediction(p_yes=0.7, p_no=0.3)
        original = _make_bet(
            prediction_response=pred,
            investments={"Yes": [100, 200], "No": [50]},
            queue_status=QueueStatus.PROCESSED,
            position_liquidity=1000,
            potential_net_profit=500,
        )
        encoded = json.dumps(original, cls=BetsEncoder)
        decoded = json.loads(encoded, cls=BetsDecoder)
        assert isinstance(decoded, Bet)
        assert decoded.id == original.id
        assert decoded.queue_status == original.queue_status
        assert decoded.prediction_response.p_yes == original.prediction_response.p_yes
        assert decoded.investments["Yes"] == [100, 200]
        assert decoded.investments["No"] == [50]


# ===========================================================================
# 10. Bet.to_request_context
# ===========================================================================


class TestBetToRequestContext:
    """Tests for Bet.to_request_context."""

    def test_omen_bet_returns_correct_context(self) -> None:
        """Test that an Omen bet produces the expected request_context."""
        bet = _make_bet(
            id="0xfpmm_address",
            market="omen_subgraph",
            fee=20000000000000000,  # 2% AMM fee
            outcomeTokenMarginalPrices=[0.4, 0.6],
            scaledLiquidityMeasure=5.0,
            openingTimestamp=1700000000,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_id"] == "0xfpmm_address"
        assert ctx["type"] == "omen"
        assert ctx["market_prob"] == 0.4
        assert ctx["market_liquidity_usd"] == 5.0
        assert ctx["market_close_at"] == "2023-11-14T22:13:20Z"
        assert ctx["amm_fee"] == 0.02
        assert "market_spread" not in ctx

    def test_polymarket_bet_uses_condition_id(self) -> None:
        """Test that a Polymarket bet uses condition_id as market_id."""
        bet = _make_bet(
            id="504911",
            market="polymarket_client",
            fee=0,
            condition_id="0xdef456abc",
            outcomeTokenMarginalPrices=[0.65, 0.35],
            scaledLiquidityMeasure=450000.0,
            openingTimestamp=1751241600,
            market_spread=0.03,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_id"] == "0xdef456abc"
        assert ctx["type"] == "polymarket"
        assert ctx["market_prob"] == 0.65
        assert ctx["market_liquidity_usd"] == 450000.0
        assert ctx["market_spread"] == 0.03
        assert "amm_fee" not in ctx

    def test_omen_bet_falls_back_to_id_when_no_condition_id(self) -> None:
        """Test that Omen bets (no condition_id) use bet.id as market_id."""
        bet = _make_bet(
            id="0xfpmm",
            market="omen_subgraph",
            condition_id=None,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_id"] == "0xfpmm"

    def test_unknown_platform_returns_none(self) -> None:
        """Test that an unrecognized market returns None."""
        bet = _make_bet(market="unknown_platform")
        ctx = bet.to_request_context()
        assert ctx is None

    def test_none_values_stripped(self) -> None:
        """Test that None values are excluded from the returned dict."""
        bet = _make_bet(
            market="omen_subgraph",
            outcomeTokenMarginalPrices=[],
            openingTimestamp=0,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert "market_prob" not in ctx
        assert "market_close_at" not in ctx

    def test_market_close_at_valid_timestamp(self) -> None:
        """Test market_close_at with a valid timestamp produces correct ISO format."""
        bet = _make_bet(
            market="omen_subgraph",
            openingTimestamp=1609459200,  # 2021-01-01T00:00:00Z
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_close_at"] == "2021-01-01T00:00:00Z"

    def test_market_prob_uses_first_index(self) -> None:
        """Test that market_prob uses outcomeTokenMarginalPrices[0], not [1].

        Mutation: changing [0] to [1] must fail this test.
        """
        bet = _make_bet(
            market="omen_subgraph",
            outcomeTokenMarginalPrices=[0.3, 0.7],
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_prob"] == 0.3
        assert ctx["market_prob"] != 0.7

    def test_market_to_platform_mapping(self) -> None:
        """Test that MARKET_TO_PLATFORM contains expected entries."""
        assert MARKET_TO_PLATFORM["omen_subgraph"] == "omen"
        assert MARKET_TO_PLATFORM["polymarket_client"] == "polymarket"

    def test_empty_condition_id_falls_back_to_id(self) -> None:
        """Test that an empty string condition_id falls back to bet.id."""
        bet = _make_bet(
            id="0xfpmm",
            market="omen_subgraph",
            condition_id="",
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_id"] == "0xfpmm"

    def test_nan_market_prob_excluded(self) -> None:
        """Test that NaN in outcomeTokenMarginalPrices is excluded from context."""
        bet = _make_bet(
            market="omen_subgraph",
            outcomeTokenMarginalPrices=[float("nan"), 0.5],
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert "market_prob" not in ctx

    def test_inf_market_prob_excluded(self) -> None:
        """Test that Infinity in outcomeTokenMarginalPrices is excluded from context."""
        bet = _make_bet(
            market="omen_subgraph",
            outcomeTokenMarginalPrices=[float("inf"), 0.5],
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert "market_prob" not in ctx

    def test_negative_inf_market_prob_excluded(self) -> None:
        """Test that -Infinity in outcomeTokenMarginalPrices is excluded from context."""
        bet = _make_bet(
            market="omen_subgraph",
            outcomeTokenMarginalPrices=[float("-inf"), 0.5],
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert "market_prob" not in ctx

    def test_zero_liquidity_included(self) -> None:
        """Test that 0.0 liquidity is included (not stripped by None filter).

        Note: zero-liquidity bets are normally blacklisted upstream, but the
        method itself should not strip valid 0.0 floats.
        """
        bet = _make_bet(
            market="omen_subgraph",
            scaledLiquidityMeasure=0.01,  # use >0 to avoid blacklisting
        )
        # manually set to 0.0 after construction to bypass _check_usefulness
        bet.scaledLiquidityMeasure = 0.0
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_liquidity_usd"] == 0.0

    def test_blacklisted_bet_still_returns_context(self) -> None:
        """Test that to_request_context works on a blacklisted bet.

        Blacklisted bets are filtered before reaching DecisionRequestBehaviour,
        but the method itself should not crash.
        """
        bet = _make_bet(market="omen_subgraph")
        bet.blacklist_forever()
        ctx = bet.to_request_context()
        # Should still return a dict (outcomes=None doesn't affect context)
        assert ctx is not None
        assert ctx["type"] == "omen"

    def test_omen_amm_fee_derived_from_fee(self) -> None:
        """Test that Omen amm_fee is derived from the AMM fee in wei."""
        bet = _make_bet(
            market="omen_subgraph",
            fee=20000000000000000,  # 2% = 2 * 10^16
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["amm_fee"] == 0.02
        assert "market_spread" not in ctx

    def test_omen_zero_fee_excludes_amm_fee(self) -> None:
        """Test that Omen bets with fee=0 exclude amm_fee."""
        bet = _make_bet(
            market="omen_subgraph",
            fee=0,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert "amm_fee" not in ctx

    def test_polymarket_spread_from_field(self) -> None:
        """Test that Polymarket market_spread comes from the market_spread field."""
        bet = _make_bet(
            market="polymarket_client",
            fee=0,
            market_spread=0.05,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["market_spread"] == 0.05
        assert "amm_fee" not in ctx

    def test_invalid_market_spread_excluded(self) -> None:
        """Test that out-of-range market_spread values are excluded."""
        for bad_value in [float("nan"), float("inf"), -0.01, 1.5]:
            bet = _make_bet(
                market="polymarket_client",
                fee=0,
                market_spread=bad_value,
            )
            ctx = bet.to_request_context()
            assert ctx is not None
            assert "market_spread" not in ctx, f"spread={bad_value} should be excluded"

    def test_polymarket_no_spread_excludes_field(self) -> None:
        """Test that Polymarket bets without spread exclude market_spread."""
        bet = _make_bet(
            market="polymarket_client",
            fee=0,
            market_spread=None,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert "market_spread" not in ctx

    def test_omen_amm_fee_and_market_spread_independent(self) -> None:
        """Test that amm_fee and market_spread are independent fields.

        An Omen bet with both fee and market_spread set should emit both.
        """
        bet = _make_bet(
            market="omen_subgraph",
            fee=20000000000000000,  # 2%
            market_spread=0.05,  # hypothetical explicit spread
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        assert ctx["amm_fee"] == 0.02
        assert ctx["market_spread"] == 0.05

    def test_context_is_json_serializable(self) -> None:
        """Test that the returned context can be serialized to JSON."""
        bet = _make_bet(
            market="omen_subgraph",
            outcomeTokenMarginalPrices=[0.4, 0.6],
            openingTimestamp=1700000000,
        )
        ctx = bet.to_request_context()
        assert ctx is not None
        serialized = json.dumps(ctx)
        deserialized = json.loads(serialized)
        assert deserialized == ctx
