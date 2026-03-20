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

"""Tests for DecisionReceiveBehaviour."""

import json
import tempfile
from pathlib import Path
from typing import Any, Generator, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.decision_maker_abci.behaviours.decision_receive import (
    DecisionReceiveBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import LiquidityInfo
from packages.valory.skills.decision_maker_abci.utils.vwap import VWAPResult
from packages.valory.skills.market_manager_abci.bets import (
    PredictionResponse,
    QueueStatus,
)
from packages.valory.skills.mech_interact_abci.states.base import (
    MechInteractionResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_behaviour() -> DecisionReceiveBehaviour:
    """Return a DecisionReceiveBehaviour with mocked dependencies."""
    behaviour = object.__new__(DecisionReceiveBehaviour)  # type: ignore[type-abstract]
    behaviour._request_id = 0
    behaviour._mech_response = None
    behaviour._rows_exceeded = False
    behaviour.sell_amount = 0

    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context

    return behaviour


def _return_gen(value: Any) -> Generator:
    """Create a generator that yields once and returns value."""
    yield
    return value


def _make_bet(**overrides: Any) -> MagicMock:
    """Create a MagicMock bet with sensible defaults."""
    bet = MagicMock()
    bet.id = overrides.get("id", "bet_123")
    bet.market = overrides.get("market", "market_1")
    bet.title = overrides.get("title", "Will it rain?")
    bet.collateralToken = overrides.get("collateralToken", "0xtoken")
    bet.creator = overrides.get("creator", "0xcreator")
    bet.fee = overrides.get("fee", 2)
    bet.openingTimestamp = overrides.get("openingTimestamp", 1700000000)
    bet.outcomeSlotCount = overrides.get("outcomeSlotCount", 2)
    bet.outcomeTokenAmounts = overrides.get("outcomeTokenAmounts", [1000, 1000])
    bet.outcomeTokenMarginalPrices = overrides.get(
        "outcomeTokenMarginalPrices", [0.5, 0.5]
    )
    bet.outcomes = overrides.get("outcomes", ["Yes", "No"])
    bet.scaledLiquidityMeasure = overrides.get("scaledLiquidityMeasure", 100.0)
    bet.prediction_response = overrides.get(
        "prediction_response",
        PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.5, info_utility=0.5),
    )
    bet.position_liquidity = overrides.get("position_liquidity", 0)
    bet.potential_net_profit = overrides.get("potential_net_profit", 0)
    bet.invested_amount = overrides.get("invested_amount", 0)
    bet.n_bets = overrides.get("n_bets", 0)
    bet.opposite_vote = MagicMock(side_effect=lambda v: v ^ 1)
    bet.get_outcome = MagicMock(side_effect=lambda i: ["Yes", "No"][i])
    bet.get_vote_amount = MagicMock(return_value=overrides.get("vote_amount", 0))
    bet.rebet_allowed = MagicMock(return_value=overrides.get("rebet_allowed", True))
    bet.update_investments = MagicMock(return_value=True)
    bet.queue_status = overrides.get("queue_status", QueueStatus.FRESH)
    bet.investments = overrides.get("investments", {"Yes": [], "No": []})
    return bet


def _make_prediction_response(
    p_yes: float = 0.8, p_no: float = 0.2, confidence: float = 0.9
) -> PredictionResponse:
    """Create a PredictionResponse with given values."""
    return PredictionResponse(
        p_yes=p_yes, p_no=p_no, confidence=confidence, info_utility=0.5
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestDecisionReceiveBehaviourProperties:
    """Tests for DecisionReceiveBehaviour properties."""

    def test_request_id_getter(self) -> None:
        """request_id should return _request_id."""
        behaviour = _make_behaviour()
        behaviour._request_id = 42
        assert behaviour.request_id == 42

    def test_request_id_setter_valid(self) -> None:
        """request_id setter should convert to int."""
        behaviour = _make_behaviour()
        behaviour.request_id = "123"  # type: ignore[assignment]
        assert behaviour.request_id == 123

    def test_request_id_setter_int(self) -> None:
        """request_id setter should accept int directly."""
        behaviour = _make_behaviour()
        behaviour.request_id = 456
        assert behaviour.request_id == 456

    def test_request_id_setter_invalid(self) -> None:
        """request_id setter should log error on invalid input."""
        behaviour = _make_behaviour()
        behaviour.request_id = "not_a_number"  # type: ignore[assignment]
        # Should remain at default
        assert behaviour._request_id == 0

    def test_mech_response_none(self) -> None:
        """mech_response should return error MechInteractionResponse when _mech_response is None."""
        behaviour = _make_behaviour()
        response = behaviour.mech_response
        assert isinstance(response, MechInteractionResponse)
        assert response.error is not None

    def test_mech_response_set(self) -> None:
        """mech_response should return _mech_response when set."""
        behaviour = _make_behaviour()
        resp = MechInteractionResponse(result="test")
        behaviour._mech_response = resp
        assert behaviour.mech_response is resp

    def test_is_invalid_response_none_result(self) -> None:
        """is_invalid_response should return True when result is None."""
        behaviour = _make_behaviour()
        behaviour._mech_response = MechInteractionResponse(error="err")
        assert behaviour.is_invalid_response is True

    def test_is_invalid_response_matches_invalid(self) -> None:
        """is_invalid_response should return True when result matches mech_invalid_response."""
        behaviour = _make_behaviour()
        behaviour._mech_response = MechInteractionResponse(result="INVALID")
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(mech_invalid_response="INVALID")
            assert behaviour.is_invalid_response is True

    def test_is_invalid_response_normal(self) -> None:
        """is_invalid_response should return False for normal responses."""
        behaviour = _make_behaviour()
        behaviour._mech_response = MechInteractionResponse(result="valid_data")
        with patch.object(
            type(behaviour), "params", new_callable=PropertyMock
        ) as mock_params:
            mock_params.return_value = MagicMock(mech_invalid_response="INVALID")
            assert behaviour.is_invalid_response is False

    def test_review_bets_for_selling_mode(self) -> None:
        """review_bets_for_selling_mode should return synchronized_data value."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(review_bets_for_selling=True)
            assert behaviour.review_bets_for_selling_mode is True


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestDecisionReceiveInit:
    """Tests for DecisionReceiveBehaviour.__init__."""

    def test_init_sets_defaults(self) -> None:
        """__init__ should set default values for internal attributes."""
        behaviour = _make_behaviour()
        assert behaviour._request_id == 0
        assert behaviour._mech_response is None
        assert behaviour._rows_exceeded is False

    def test_init_calls_super(self) -> None:
        """__init__ should call super().__init__ with loader_cls and set defaults."""
        with patch(
            "packages.valory.skills.decision_maker_abci.behaviours.decision_receive.StorageManagerBehaviour.__init__"
        ) as mock_super_init:
            mock_super_init.return_value = None
            behaviour = DecisionReceiveBehaviour(name="test", skill_context=MagicMock())
            mock_super_init.assert_called_once()
            # Check that loader_cls was passed
            call_kwargs = mock_super_init.call_args[1]
            assert "loader_cls" in call_kwargs
            assert behaviour._request_id == 0
            assert behaviour._mech_response is None
            assert behaviour._rows_exceeded is False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestGetDecision:
    """Tests for _get_decision."""

    def test_get_decision_with_valid_response(self) -> None:
        """_get_decision should return PredictionResponse for valid mech response."""
        behaviour = _make_behaviour()
        pred_data = {
            "p_yes": 0.8,
            "p_no": 0.2,
            "confidence": 0.9,
            "info_utility": 0.5,
        }
        behaviour._mech_response = MechInteractionResponse(result=json.dumps(pred_data))

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(
                    mech_responses=[behaviour._mech_response]
                )
                result = behaviour._get_decision()

        assert isinstance(result, PredictionResponse)
        assert result.p_yes == 0.8
        assert result.confidence == 0.9

    def test_get_decision_with_none_response(self) -> None:
        """_get_decision should return None when _mech_response stays None."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=True)
            # Mock _mock_response to leave _mech_response as None
            with patch.object(behaviour, "_mock_response"):
                result = behaviour._get_decision()

        assert result is None

    def test_get_decision_with_invalid_json(self) -> None:
        """_get_decision should return None for non-JSON response."""
        behaviour = _make_behaviour()
        behaviour._mech_response = MechInteractionResponse(result="not json")

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(
                    mech_responses=[behaviour._mech_response]
                )
                result = behaviour._get_decision()

        assert result is None

    def test_get_decision_error_response(self) -> None:
        """_get_decision should return None when result is None (error)."""
        behaviour = _make_behaviour()
        behaviour._mech_response = MechInteractionResponse(error="some error")

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(
                    mech_responses=[behaviour._mech_response]
                )
                result = behaviour._get_decision()

        assert result is None

    def test_get_decision_benchmarking_calls_mock(self) -> None:
        """_get_decision should call _mock_response in benchmarking mode."""
        behaviour = _make_behaviour()
        pred_data = {
            "p_yes": 0.7,
            "p_no": 0.3,
            "confidence": 0.8,
            "info_utility": 0.5,
        }

        def mock_response_side_effect() -> None:
            """Set the mech response."""
            behaviour._mech_response = MechInteractionResponse(
                result=json.dumps(pred_data)
            )

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=True)
            with patch.object(
                behaviour,
                "_mock_response",
                side_effect=mock_response_side_effect,
            ):
                result = behaviour._get_decision()

        assert isinstance(result, PredictionResponse)
        assert result.p_yes == 0.7


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestGetBetSampleInfo:
    """Tests for _get_bet_sample_info static method."""

    def test_binary_bet_vote_0(self) -> None:
        """Should return correct token amounts for vote=0."""
        bet = MagicMock()
        bet.outcomeTokenAmounts = [100, 200]
        bet.opposite_vote.return_value = 1

        selected, other = DecisionReceiveBehaviour._get_bet_sample_info(bet, 0)
        assert selected == 100
        assert other == 200

    def test_binary_bet_vote_1(self) -> None:
        """Should return correct token amounts for vote=1."""
        bet = MagicMock()
        bet.outcomeTokenAmounts = [100, 200]
        bet.opposite_vote.return_value = 0

        selected, other = DecisionReceiveBehaviour._get_bet_sample_info(bet, 1)
        assert selected == 200
        assert other == 100


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestGetResponse:
    """Tests for _get_response."""

    def test_get_response_with_mech_responses(self) -> None:
        """_get_response should set the first mech response."""
        behaviour = _make_behaviour()
        resp = MechInteractionResponse(result="data")

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(mech_responses=[resp])
            behaviour._get_response()

        assert behaviour._mech_response is resp

    def test_get_response_empty_mech_responses(self) -> None:
        """_get_response should set error when no mech responses."""
        behaviour = _make_behaviour()

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(mech_responses=[])
            behaviour._get_response()

        assert behaviour._mech_response is not None
        assert behaviour._mech_response.error is not None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestComputeNewTokensDistribution:
    """Tests for _compute_new_tokens_distribution."""

    def test_basic_computation(self) -> None:
        """Should compute new token distribution correctly."""
        behaviour = _make_behaviour()

        token_amounts = [1000, 1000]
        prices = [0.5, 0.5]
        net_bet_amount = 100
        vote = 0

        result = behaviour._compute_new_tokens_distribution(
            token_amounts, prices, net_bet_amount, vote
        )
        assert len(result) == 5
        (
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            other_shares,
            num_shares,
            available_shares,
        ) = result

        assert selected_type_tokens_in_pool == 1000
        assert other_tokens_in_pool == 1000
        # With equal prices, each gets half the bet
        assert other_shares == 100  # 50/0.5
        assert available_shares == 500  # 1000 * 0.5

    def test_computation_with_vote_1(self) -> None:
        """Should compute correctly when vote is 1."""
        behaviour = _make_behaviour()

        token_amounts = [800, 1200]
        prices = [0.6, 0.4]
        net_bet_amount = 200
        vote = 1

        result = behaviour._compute_new_tokens_distribution(
            token_amounts, prices, net_bet_amount, vote
        )
        assert len(result) == 5
        # Just verify the method doesn't error and returns the right structure
        selected, other, other_shares, num_shares, available_shares = result
        assert selected == 1200
        assert other == 800


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestShouldSellOutcomeTokens:
    """Tests for should_sell_outcome_tokens."""

    def test_none_prediction_response(self) -> None:
        """Should return False when prediction_response is None."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        assert behaviour.should_sell_outcome_tokens(None) is False

    def test_none_vote(self) -> None:
        """Should return False when prediction_response.vote is None."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        pred = PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.9, info_utility=0.1)
        # PredictionResponse with vote None
        assert (
            pred.vote is not None or behaviour.should_sell_outcome_tokens(pred) is False
        )

    def test_tokens_to_be_sold_zero(self) -> None:
        """Should return False when tokens_to_be_sold is zero."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        bet = _make_bet(vote_amount=0)
        with patch.object(  # type: ignore[method-assign]
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = bet
            pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)
            result = behaviour.should_sell_outcome_tokens(pred)
        assert result is False  # type: ignore[method-assign]

    def test_tokens_to_be_sold_nonzero_low_confidence(self) -> None:
        """Should return False when confidence is below threshold."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        bet = _make_bet(vote_amount=100)
        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = bet  # type: ignore[method-assign]
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(min_confidence_for_selling=0.9)
                pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.5)
                result = behaviour.should_sell_outcome_tokens(pred)
        assert result is False

    def test_tokens_to_be_sold_nonzero_high_confidence(self) -> None:
        """Should return True when confidence is above threshold."""
        behaviour = _make_behaviour()
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        bet = _make_bet(vote_amount=100)  # type: ignore[method-assign]
        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = bet
            with patch.object(
                type(behaviour), "params", new_callable=PropertyMock
            ) as mock_params:
                mock_params.return_value = MagicMock(min_confidence_for_selling=0.5)
                pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)
                result = behaviour.should_sell_outcome_tokens(pred)
        assert result is True
        assert behaviour.sell_amount == 100


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# type: ignore[method-assign]


class TestCalcBinaryShares:
    """Tests for _calc_binary_shares."""

    def test_calc_binary_shares_normal(self) -> None:
        """Should calculate num_shares and available_shares correctly."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[1000, 1000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
        )
        num_shares, available_shares = behaviour._calc_binary_shares(bet, 100, 0)
        assert num_shares > 0
        assert available_shares > 0

    def test_calc_binary_shares_none_prices(self) -> None:
        """Should return (0, 0) when prices are None."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[1000, 1000],
            outcomeTokenMarginalPrices=None,
        )
        num_shares, available_shares = behaviour._calc_binary_shares(bet, 100, 0)
        assert num_shares == 0
        assert available_shares == 0


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestUpdateMarketLiquidity:
    """Tests for _update_market_liquidity."""

    def test_empty_dict(self) -> None:
        """Should initialize liquidity when liquidity_amounts is empty."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            id="q1",
            outcomeTokenAmounts=[500, 600],
            outcomeTokenMarginalPrices=[0.45, 0.55],
            scaledLiquidityMeasure=50.0,
        )
        shared_state = MagicMock()
        shared_state.liquidity_amounts = {}
        shared_state.liquidity_cache = {}

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = shared_state
            with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
                behaviour._update_market_liquidity()

        assert shared_state.current_liquidity_amounts == [500, 600]
        assert shared_state.current_liquidity_prices == [0.45, 0.55]
        assert shared_state.liquidity_cache["q1"] == 50.0

    def test_new_market(self) -> None:
        """Should initialize liquidity for a new market."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            id="q2",
            outcomeTokenAmounts=[700, 300],
            outcomeTokenMarginalPrices=[0.7, 0.3],
            scaledLiquidityMeasure=70.0,
        )
        shared_state = MagicMock()
        shared_state.liquidity_amounts = {"q1": [100, 200]}
        shared_state.liquidity_cache = {}

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = shared_state
            with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
                behaviour._update_market_liquidity()

        assert shared_state.current_liquidity_amounts == [700, 300]

    def test_existing_market_no_update(self) -> None:
        """Should not update liquidity for an existing market."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="q1")
        shared_state = MagicMock()
        shared_state.liquidity_amounts = {"q1": [100, 200]}
        shared_state.liquidity_cache = {}

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = shared_state
            with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
                behaviour._update_market_liquidity()

        # current_liquidity_amounts should NOT have been set for existing market
        # (the keys() check means q1 is already there, so neither empty_dict nor new_market is True)
        # The mock's setter won't be called so no assertion needed beyond no error.


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestCalculateNewLiquidity:
    """Tests for _calculate_new_liquidity."""

    def test_vote_0(self) -> None:
        """Should return correct LiquidityInfo for vote 0."""
        behaviour = _make_behaviour()
        shared_state = MagicMock()
        shared_state.current_liquidity_amounts = [1000, 1000]
        shared_state.current_liquidity_prices = [0.5, 0.5]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = shared_state
            result = behaviour._calculate_new_liquidity(100, 0)

        assert isinstance(result, LiquidityInfo)
        assert result.l0_start == 1000
        assert result.l1_start == 1000

    def test_vote_1(self) -> None:
        """Should return correct LiquidityInfo for vote 1."""
        behaviour = _make_behaviour()
        shared_state = MagicMock()
        shared_state.current_liquidity_amounts = [1000, 1000]
        shared_state.current_liquidity_prices = [0.5, 0.5]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = shared_state
            result = behaviour._calculate_new_liquidity(100, 1)

        assert isinstance(result, LiquidityInfo)
        # For vote=1, other_tokens is at index 0, selected is at index 1
        assert result.l0_start == 1000
        assert result.l1_start == 1000


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestComputeScaledLiquidityMeasure:
    """Tests for _compute_scaled_liquidity_measure."""

    def test_basic(self) -> None:
        """Should compute scaled liquidity measure correctly."""
        behaviour = _make_behaviour()
        with patch.object(behaviour, "get_token_precision", return_value=10**18):
            result = behaviour._compute_scaled_liquidity_measure(
                [10**18, 10**18], [0.5, 0.5]
            )
        assert result == 1.0

    def test_with_usdc_precision(self) -> None:
        """Should compute scaled liquidity measure with USDC precision."""
        behaviour = _make_behaviour()
        with patch.object(behaviour, "get_token_precision", return_value=10**6):
            result = behaviour._compute_scaled_liquidity_measure(
                [10**6, 10**6], [0.5, 0.5]
            )
        assert result == 1.0


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestUpdateLiquidityInfo:
    """Tests for _update_liquidity_info."""

    def test_updates_shared_state(self) -> None:
        """Should update the shared state with new liquidity info."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="q1")
        shared_state = MagicMock()
        shared_state.current_liquidity_amounts = [1000, 1000]
        shared_state.current_liquidity_prices = [0.5, 0.5]
        shared_state.liquidity_cache = {}

        liquidity_info = LiquidityInfo(
            l0_start=1000, l1_start=1000, l0_end=950, l1_end=1100
        )

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = shared_state
            with patch.object(
                behaviour, "_calculate_new_liquidity", return_value=liquidity_info
            ):
                with patch.object(
                    behaviour, "get_active_sampled_bet", return_value=bet
                ):
                    with patch.object(
                        behaviour,
                        "_compute_scaled_liquidity_measure",
                        return_value=50.0,
                    ):
                        result = behaviour._update_liquidity_info(100, 0)

        assert isinstance(result, LiquidityInfo)
        assert shared_state.liquidity_cache["q1"] == 50.0


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestRebetAllowed:
    """Tests for rebet_allowed."""

    def test_rebet_allowed_true(self) -> None:
        """Should return True when rebet is allowed."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            rebet_allowed=True,
            outcomeTokenAmounts=[1000, 1000],
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = bet
            result = behaviour.rebet_allowed(pred, 50)

        assert result is True

    def test_rebet_not_allowed(self) -> None:
        """Should return False and read bets when rebet is not allowed."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            rebet_allowed=False,
            outcomeTokenAmounts=[1000, 1000],
        )
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        with patch.object(
            type(behaviour), "sampled_bet", new_callable=PropertyMock
        ) as mock_sb:
            mock_sb.return_value = bet
            result = behaviour.rebet_allowed(pred, 50)

        assert result is False
        behaviour.read_bets.assert_called_once()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestIsProfitable:
    """Tests for _is_profitable."""

    def _run_is_profitable(
        self,
        behaviour: DecisionReceiveBehaviour,
        pred: PredictionResponse,  # type: ignore[method-assign]
    ) -> Tuple[bool, int]:
        """Run the _is_profitable generator to completion."""
        gen = behaviour._is_profitable(pred)
        try:
            # Advance past all yield points
            _ = next(gen)
            while True:
                _ = gen.send(None)
        except StopIteration as e:
            return e.value  # type: ignore[return-value]

    def test_vote_is_none(self) -> None:
        """Should return (False, 0) when vote is None."""
        behaviour = _make_behaviour()
        pred = PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.9, info_utility=0.5)
        # vote is None because p_yes == p_no
        gen = behaviour._is_profitable(pred)
        try:
            next(gen)
            while True:
                gen.send(None)
        except StopIteration as e:
            assert e.value == (False, 0)

    def test_omen_profitable(self) -> None:
        """Should return (True, bet_amount) when Omen bet is profitable."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 500  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)  # type: ignore[return-value]
                            with patch.object(
                                behaviour, "convert_to_native", return_value=0.001
                            ):
                                with patch.object(
                                    behaviour, "get_token_name", return_value="xDAI"
                                ):
                                    with patch.object(
                                        behaviour, "rebet_allowed", return_value=True
                                    ):
                                        result = self._run_is_profitable(
                                            behaviour, pred
                                        )

        is_profitable, bet_amount = result
        assert is_profitable is True
        assert bet_amount == 500

    def test_omen_not_profitable_low_bet_amount(self) -> None:
        """Should return (False, 0) when bet amount is zero or below threshold."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator returning zero."""
            yield
            return 0  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=10,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)  # type: ignore[return-value]
                            result = self._run_is_profitable(behaviour, pred)

        is_profitable, bet_amount = result
        assert is_profitable is False
        assert bet_amount == 0

    def test_omen_not_profitable_negative_profit(self) -> None:
        """Should return (False, bet_amount) when net profit is negative."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator returning a small amount."""
            yield
            return 10  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=10000,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)  # type: ignore[return-value]
                            with patch.object(
                                behaviour, "convert_to_native", return_value=0.0001
                            ):
                                with patch.object(
                                    behaviour, "get_token_name", return_value="xDAI"
                                ):
                                    result = self._run_is_profitable(behaviour, pred)

        is_profitable, _ = result
        assert is_profitable is False

    def test_omen_slippage_warning(self) -> None:
        """Should log warning when num_shares exceeds available_shares * SLIPPAGE."""
        behaviour = _make_behaviour()
        # Set up conditions where num_shares > available_shares * SLIPPAGE
        # by making available_shares very small
        bet = _make_bet(
            outcomeTokenAmounts=[100, 100],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator returning a large amount."""
            yield
            return 10000  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)  # type: ignore[return-value]
                            with patch.object(
                                behaviour, "convert_to_native", return_value=0.001
                            ):
                                with patch.object(
                                    behaviour, "get_token_name", return_value="xDAI"
                                ):
                                    with patch.object(
                                        behaviour, "rebet_allowed", return_value=True
                                    ):
                                        self._run_is_profitable(behaviour, pred)

        # Should have triggered warning about slippage
        behaviour.context.logger.warning.assert_called()

    def test_omen_non_positive_bet_threshold(self) -> None:
        """Should log warning when bet_threshold is non-positive."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 500  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=-10,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour, "convert_to_native", return_value=0.001  # type: ignore[return-value]
                            ):
                                with patch.object(
                                    behaviour, "get_token_name", return_value="xDAI"
                                ):
                                    with patch.object(
                                        behaviour, "rebet_allowed", return_value=True
                                    ):
                                        self._run_is_profitable(behaviour, pred)

        # Should have triggered warning about non-positive threshold
        behaviour.context.logger.warning.assert_called()

    def test_omen_rebet_not_allowed(self) -> None:
        """Should return False when rebet is not allowed."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 500  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour, "convert_to_native", return_value=0.001
                            ):
                                with patch.object(  # type: ignore[return-value]
                                    behaviour, "get_token_name", return_value="xDAI"
                                ):
                                    with patch.object(
                                        behaviour, "rebet_allowed", return_value=False
                                    ):
                                        result = self._run_is_profitable(
                                            behaviour, pred
                                        )

        is_profitable, _ = result
        assert is_profitable is False

    def test_polymarket_profitable(self) -> None:
        """Should return (True, bet_amount) for profitable Polymarket bet (mid-price fallback)."""
        behaviour = _make_behaviour()
        # Use prices where market prob < predicted prob so expected profit > 0
        # With convert_unit_to_wei scale=10**6:
        #   market_price_for_selected = int(0.3*10**6) = 300000
        #   opposing = int(0.7*10**6) = 700000
        #   market_prob = 300000/1000000 = 0.3
        #   net_bet_amount = remove_fraction_wei(10**7, 0.0) = 10**7
        #   num_shares = 10**7/0.3 = 33333333
        #   mech_costs = int(0.01*10**6) = 10000
        #   expected = 0.8*33333333 - 10**7 - 10000 = 26666666 - 10000000 - 10000 = 16656666 > 0
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.3, 0.7],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap_none(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price returning None (mid-price fallback)."""
            yield
            return None  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),  # type: ignore[return-value]
                            ):
                                with patch.object(
                                    behaviour,
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="USDC",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "rebet_allowed",
                                            return_value=True,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "_fetch_vwap_price",
                                                side_effect=mock_fetch_vwap_none,
                                            ):
                                                result = self._run_is_profitable(
                                                    behaviour, pred
                                                )

        is_profitable, bet_amount = result
        assert is_profitable is True
        assert bet_amount == 10**7

    def test_polymarket_not_profitable(self) -> None:
        """Should return (False, bet_amount) for non-profitable Polymarket bet (mid-price fallback)."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.6, p_no=0.4)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 5000  # type: ignore[return-value]

        def mock_fetch_vwap_none(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price returning None (mid-price fallback)."""
            yield
            return None  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,  # type: ignore[return-value]
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="USDC",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "_fetch_vwap_price",
                                            side_effect=mock_fetch_vwap_none,
                                        ):
                                            result = self._run_is_profitable(
                                                behaviour, pred
                                            )

        is_profitable, _ = result
        assert is_profitable is False

    def test_polymarket_invalid_prices(self) -> None:
        """Should return (False, 0) when Polymarket prices are invalid."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.0, 0.0],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 5000  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                return_value=0,
                            ):
                                result = self._run_is_profitable(behaviour, pred)
        # type: ignore[return-value]
        is_profitable, bet_amount = result
        assert is_profitable is False
        assert bet_amount == 0

    def test_polymarket_rebet_not_allowed(self) -> None:
        """Should return False when Polymarket rebet is not allowed (mid-price fallback)."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.3, 0.7],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap_none(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price returning None (mid-price fallback)."""
            yield
            return None  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,  # type: ignore[return-value]
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="USDC",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "rebet_allowed",
                                            return_value=False,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "_fetch_vwap_price",
                                                side_effect=mock_fetch_vwap_none,
                                            ):
                                                result = self._run_is_profitable(
                                                    behaviour, pred
                                                )

        is_profitable, _ = result
        assert is_profitable is False

    def test_polymarket_vote_1_p_no(self) -> None:
        """Should use p_no when predicted vote side is 1 (mid-price fallback)."""
        behaviour = _make_behaviour()
        # vote=1 because p_no > p_yes, so selected is index 1 (price=0.3)
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.7, 0.3],
            fee=0,
        )
        # p_no > p_yes -> vote=1
        pred = _make_prediction_response(p_yes=0.2, p_no=0.8)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap_none(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price returning None (mid-price fallback)."""
            yield
            return None  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,  # type: ignore[return-value]
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="USDC",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "rebet_allowed",
                                            return_value=True,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "_fetch_vwap_price",
                                                side_effect=mock_fetch_vwap_none,
                                            ):
                                                result = self._run_is_profitable(
                                                    behaviour, pred
                                                )

        is_profitable, bet_amount = result
        assert is_profitable is True

    # -------------------------------------------------------------------
    # _fetch_vwap_price tests
    # -------------------------------------------------------------------

    def _run_fetch_vwap_price(
        self,
        behaviour: DecisionReceiveBehaviour,
        bet: Any,
        predicted_vote_side: int,
        net_bet_amount: int,
    ) -> Any:
        """Run the _fetch_vwap_price generator to completion."""
        gen = behaviour._fetch_vwap_price(bet, predicted_vote_side, net_bet_amount)
        try:
            _ = next(gen)
            while True:
                _ = gen.send(None)
        except StopIteration as e:
            return e.value

    def test_fetch_vwap_price_success(self) -> None:
        """Should return VWAPResult when order book is available."""
        behaviour = _make_behaviour()
        bet = _make_bet(fee=0)
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}

        book_response = {
            "asks": [
                {"price": "0.40", "size": "100"},
                {"price": "0.60", "size": "50"},
            ],
            "bids": [],
        }

        def mock_send_request(*args: Any, **kwargs: Any) -> Generator:
            """Mock send_polymarket_connection_request."""
            yield
            return book_response  # type: ignore[return-value]

        with patch.object(
            behaviour,
            "send_polymarket_connection_request",
            side_effect=mock_send_request,
        ):
            with patch.object(
                behaviour,
                "convert_to_native",
                return_value=70.0,
            ):
                result = self._run_fetch_vwap_price(behaviour, bet, 0, 10**7)

        assert isinstance(result, VWAPResult)
        # Budget=70, asks at 0.40*100=$40 + 0.60*50=$30 = $70 total
        assert result.fully_filled is True
        assert result.total_shares == pytest.approx(150.0)
        assert result.vwap == pytest.approx(70.0 / 150.0)

    def test_fetch_vwap_price_no_outcome_token_ids(self) -> None:
        """Should return None when outcome_token_ids is None."""
        behaviour = _make_behaviour()
        bet = _make_bet(fee=0)
        bet.outcome_token_ids = None

        result = self._run_fetch_vwap_price(behaviour, bet, 0, 10**7)
        assert result is None

    def test_fetch_vwap_price_missing_outcome_key(self) -> None:
        """Should return None when outcome_token_ids exists but key is missing."""
        behaviour = _make_behaviour()
        bet = _make_bet(fee=0)
        # outcome_token_ids has "Yes"/"No" but get_outcome returns "Yes"
        # so we make the dict missing that key
        bet.outcome_token_ids = {"Missing": "tok_missing"}

        result = self._run_fetch_vwap_price(behaviour, bet, 0, 10**7)
        assert result is None

    def test_fetch_vwap_price_error_response(self) -> None:
        """Should return None when connection returns an error."""
        behaviour = _make_behaviour()
        bet = _make_bet(fee=0)
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}

        def mock_send_request(*args: Any, **kwargs: Any) -> Generator:
            """Mock send_polymarket_connection_request."""
            yield
            return {"error": "network timeout"}  # type: ignore[return-value]

        with patch.object(
            behaviour,
            "send_polymarket_connection_request",
            side_effect=mock_send_request,
        ):
            with patch.object(
                behaviour,
                "convert_to_native",
                return_value=50.0,
            ):
                result = self._run_fetch_vwap_price(behaviour, bet, 0, 10**7)

        assert result is None

    def test_fetch_vwap_price_none_response(self) -> None:
        """Should return None when connection returns None."""
        behaviour = _make_behaviour()
        bet = _make_bet(fee=0)
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}

        def mock_send_request(*args: Any, **kwargs: Any) -> Generator:
            """Mock send_polymarket_connection_request."""
            yield
            return None  # type: ignore[return-value]

        with patch.object(
            behaviour,
            "send_polymarket_connection_request",
            side_effect=mock_send_request,
        ):
            with patch.object(
                behaviour,
                "convert_to_native",
                return_value=50.0,
            ):
                result = self._run_fetch_vwap_price(behaviour, bet, 0, 10**7)

        assert result is None

    def test_fetch_vwap_price_malformed_asks(self) -> None:
        """Should return None when asks have unexpected format."""
        behaviour = _make_behaviour()
        bet = _make_bet(fee=0)
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}

        book_response = {"asks": [{"bad_key": "value"}], "bids": []}

        def mock_send_request(*args: Any, **kwargs: Any) -> Generator:
            """Mock send_polymarket_connection_request."""
            yield
            return book_response  # type: ignore[return-value]

        with patch.object(
            behaviour,
            "send_polymarket_connection_request",
            side_effect=mock_send_request,
        ):
            with patch.object(
                behaviour,
                "convert_to_native",
                return_value=50.0,
            ):
                result = self._run_fetch_vwap_price(behaviour, bet, 0, 10**7)

        assert result is None

    # -------------------------------------------------------------------
    # Polymarket VWAP integration with _is_profitable
    # -------------------------------------------------------------------

    def test_polymarket_vwap_profitable(self) -> None:
        """Should use VWAP pricing when order book is available."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.3, 0.7],
            fee=0,
        )
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        # VWAP of 0.35 with 28.57 shares from a $10 budget
        vwap_result = VWAPResult(
            vwap=0.35, total_shares=28.571, budget_spent=10.0, fully_filled=True
        )

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price generator."""
            yield
            return vwap_result  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="USDC",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "rebet_allowed",
                                            return_value=True,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "_fetch_vwap_price",
                                                side_effect=mock_fetch_vwap,
                                            ):
                                                result = self._run_is_profitable(
                                                    behaviour, pred
                                                )

        is_profitable, bet_amount = result
        assert is_profitable is True
        assert bet_amount == 10**7

    def test_polymarket_vwap_empty_book(self) -> None:
        """Should return (False, 0) when VWAP is 0 (no liquidity)."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.3, 0.7],
            fee=0,
        )
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        vwap_result = VWAPResult(
            vwap=0.0, total_shares=0.0, budget_spent=0.0, fully_filled=False
        )

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price generator."""
            yield
            return vwap_result  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "_fetch_vwap_price",
                                        side_effect=mock_fetch_vwap,
                                    ):
                                        result = self._run_is_profitable(
                                            behaviour, pred
                                        )

        is_profitable, bet_amount = result
        assert is_profitable is False
        assert bet_amount == 0

    def test_polymarket_vwap_thin_book(self) -> None:
        """Should return (False, 0) when book can't fully fill (FOK would fail)."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.3, 0.7],
            fee=0,
        )
        bet.outcome_token_ids = {"Yes": "tok_yes", "No": "tok_no"}
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        vwap_result = VWAPResult(
            vwap=0.45, total_shares=50.0, budget_spent=22.5, fully_filled=False
        )

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price generator."""
            yield
            return vwap_result  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "_fetch_vwap_price",
                                        side_effect=mock_fetch_vwap,
                                    ):
                                        result = self._run_is_profitable(
                                            behaviour, pred
                                        )

        is_profitable, bet_amount = result
        assert is_profitable is False
        assert bet_amount == 0

    def test_polymarket_vwap_fallback_to_midprice(self) -> None:
        """Should fall back to mid-price when VWAP fetch returns None."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10**7, 10**7],
            outcomeTokenMarginalPrices=[0.3, 0.7],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 10**7  # type: ignore[return-value]

        def mock_fetch_vwap(*args: Any, **kwargs: Any) -> Generator:
            """Mock _fetch_vwap_price returning None (fallback)."""
            yield
            return None  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=0,
                        is_running_on_polymarket=True,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            with patch.object(
                                behaviour,
                                "convert_unit_to_wei",
                                side_effect=lambda x: int(x * 10**6),
                            ):
                                with patch.object(
                                    behaviour,
                                    "convert_to_native",
                                    return_value=0.0,
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="USDC",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "rebet_allowed",
                                            return_value=True,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "_fetch_vwap_price",
                                                side_effect=mock_fetch_vwap,
                                            ):
                                                result = self._run_is_profitable(
                                                    behaviour, pred
                                                )

        # Falls back to mid-price logic: same as test_polymarket_profitable
        is_profitable, bet_amount = result
        assert is_profitable is True
        assert bet_amount == 10**7

    def test_benchmarking_profitable(self) -> None:
        """Should update liquidity and write results in benchmarking mode."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            id="q1",
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 500  # type: ignore[return-value]

        shared_state = MagicMock()
        shared_state.liquidity_amounts = {}
        shared_state.current_liquidity_amounts = [10000, 10000]
        shared_state.current_liquidity_prices = [0.5, 0.5]
        shared_state.liquidity_cache = {"q1": 50.0}
        shared_state.benchmarking_mech_calls = 0

        liquidity_info = LiquidityInfo(
            l0_start=1000, l1_start=1000, l0_end=950, l1_end=1050
        )

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=True)
            with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
                with patch.object(behaviour, "_update_market_liquidity"):
                    with patch.object(
                        type(behaviour), "params", new_callable=PropertyMock
                    ) as mock_params:
                        mock_params.return_value = MagicMock(
                            bet_threshold=0,
                            is_running_on_polymarket=False,
                        )
                        with patch.object(
                            behaviour,
                            "get_bet_amount",
                            side_effect=mock_get_bet_amount,
                        ):
                            with patch.object(
                                type(behaviour),  # type: ignore[return-value]
                                "synchronized_data",
                                new_callable=PropertyMock,
                            ) as mock_sd:
                                mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                                with patch.object(
                                    behaviour, "convert_to_native", return_value=0.001
                                ):
                                    with patch.object(
                                        behaviour,
                                        "get_token_name",
                                        return_value="xDAI",
                                    ):
                                        with patch.object(
                                            behaviour,
                                            "rebet_allowed",
                                            return_value=True,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "_update_liquidity_info",
                                                return_value=liquidity_info,
                                            ):
                                                with patch.object(
                                                    behaviour, "store_bets"
                                                ):
                                                    with patch.object(
                                                        behaviour,
                                                        "_write_benchmark_results",
                                                    ):
                                                        with patch.object(
                                                            type(behaviour),
                                                            "shared_state",
                                                            new_callable=PropertyMock,
                                                        ) as mock_ss:
                                                            mock_ss.return_value = (
                                                                shared_state
                                                            )
                                                            result = (
                                                                self._run_is_profitable(
                                                                    behaviour, pred
                                                                )
                                                            )

        is_profitable, bet_amount = result
        assert is_profitable is True
        assert bet_amount == 500
        assert shared_state.benchmarking_mech_calls == 1

    def test_benchmarking_not_profitable(self) -> None:
        """Should write results and increment mech calls even when not profitable in benchmarking."""
        behaviour = _make_behaviour()
        # bet_amount=1000 > bet_threshold=10 (passes threshold check)
        # But _calc_binary_shares returns small num_shares so profit < 0
        bet = _make_bet(
            id="q1",
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator."""
            yield
            return 1000  # type: ignore[return-value]

        shared_state = MagicMock()
        shared_state.benchmarking_mech_calls = 0

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=True)
            with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
                with patch.object(behaviour, "_update_market_liquidity"):
                    with patch.object(
                        type(behaviour), "params", new_callable=PropertyMock
                    ) as mock_params:
                        mock_params.return_value = MagicMock(
                            bet_threshold=10,
                            is_running_on_polymarket=False,
                        )
                        with patch.object(
                            behaviour,
                            "get_bet_amount",
                            side_effect=mock_get_bet_amount,
                        ):
                            with patch.object(
                                type(behaviour),
                                "synchronized_data",
                                new_callable=PropertyMock,
                            ) as mock_sd:
                                mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                                with patch.object(
                                    behaviour, "_write_benchmark_results"
                                ):
                                    with patch.object(  # type: ignore[return-value]
                                        type(behaviour),
                                        "shared_state",
                                        new_callable=PropertyMock,
                                    ) as mock_ss:
                                        mock_ss.return_value = shared_state
                                        with patch.object(
                                            behaviour,
                                            "convert_to_native",
                                            return_value=0.0,
                                        ):
                                            with patch.object(
                                                behaviour,
                                                "get_token_name",
                                                return_value="xDAI",
                                            ):
                                                # Mock _calc_binary_shares to return very small num_shares
                                                with patch.object(
                                                    behaviour,
                                                    "_calc_binary_shares",
                                                    return_value=(0, 0),
                                                ):
                                                    result = self._run_is_profitable(
                                                        behaviour, pred
                                                    )

        is_profitable, bet_amount = result
        assert is_profitable is False
        assert shared_state.benchmarking_mech_calls == 1

    def test_bet_amount_below_threshold(self) -> None:
        """Should return (False, 0) when bet_amount is positive but below threshold."""
        behaviour = _make_behaviour()
        bet = _make_bet(
            outcomeTokenAmounts=[10000, 10000],
            outcomeTokenMarginalPrices=[0.5, 0.5],
            fee=0,
        )
        pred = _make_prediction_response(p_yes=0.8, p_no=0.2)

        def mock_get_bet_amount(*args: Any, **kwargs: Any) -> Generator:
            """Mock the get_bet_amount generator returning a value below threshold."""
            yield
            return 5  # type: ignore[return-value]

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(enabled=False)
            with patch.object(
                type(behaviour), "sampled_bet", new_callable=PropertyMock
            ) as mock_sb:
                mock_sb.return_value = bet
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(
                        bet_threshold=10,
                        is_running_on_polymarket=False,
                    )
                    with patch.object(
                        behaviour, "get_bet_amount", side_effect=mock_get_bet_amount
                    ):
                        with patch.object(
                            type(behaviour),
                            "synchronized_data",
                            new_callable=PropertyMock,
                        ) as mock_sd:
                            mock_sd.return_value = MagicMock(weighted_accuracy=0.9)
                            result = self._run_is_profitable(behaviour, pred)

        is_profitable, bet_amount = result
        assert is_profitable is False
        assert bet_amount == 0


# type: ignore[return-value]
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestUpdateSelectedBet:
    """Tests for _update_selected_bet."""

    def test_updates_bet_and_stores(self) -> None:
        """Should update the selected bet's timestamp and store bets."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="q1")
        behaviour.bets = [bet]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        shared_state = MagicMock()
        shared_state.get_simulated_now_timestamp.return_value = 1700000000

        pred = _make_prediction_response()

        with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
            with patch.object(
                type(behaviour), "shared_state", new_callable=PropertyMock
            ) as mock_ss:
                mock_ss.return_value = shared_state
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(safe_voting_range=100)
                    behaviour._update_selected_bet(pred)

        assert bet.processed_timestamp == 1700000000
        bet.update_investments.assert_called_once()
        behaviour.store_bets.assert_called_once()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestNextDatasetRow:
    """Tests for _next_dataset_row."""

    def test_returns_row(self) -> None:
        """Should return the next row from the dataset."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="q1")
        # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.csv"
            with open(dataset_path, "w") as f:
                f.write("question_id,question,answer,p_yes_tool1\n")
                f.write("q1,Will it rain?,yes,0.8\n")

            shared_state = MagicMock()
            shared_state.bet_id_row_manager = {"q1": [1]}

            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(
                    sep=",", dataset_filename="dataset.csv"
                )
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                    with patch.object(
                        behaviour, "get_active_sampled_bet", return_value=bet
                    ):
                        with patch.object(
                            type(behaviour),
                            "shared_state",
                            new_callable=PropertyMock,
                        ) as mock_ss:
                            mock_ss.return_value = shared_state
                            with patch.object(
                                type(behaviour),
                                "sampled_bet",
                                new_callable=PropertyMock,
                            ) as mock_sb:
                                mock_sb.return_value = bet
                                result = behaviour._next_dataset_row()

        assert result is not None
        assert result["question_id"] == "q1"

    def test_no_more_rows(self) -> None:
        """Should return None when no rows remain."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="q1")

        shared_state = MagicMock()
        shared_state.bet_id_row_manager = {"q1": []}
        shared_state.last_benchmarking_has_run = False

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(sep=",", dataset_filename="dataset.csv")
            with patch.object(behaviour, "get_active_sampled_bet", return_value=bet):
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = shared_state
                    with patch.object(
                        type(behaviour), "sampled_bet", new_callable=PropertyMock
                    ) as mock_sb:
                        mock_sb.return_value = bet
                        result = behaviour._next_dataset_row()

        assert result is None
        assert behaviour._rows_exceeded is True
        assert bet.queue_status == QueueStatus.BENCHMARKING_DONE

    def test_empty_row(self) -> None:
        """Should return None when the row at the given index is empty."""
        behaviour = _make_behaviour()
        bet = _make_bet(id="q1")

        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.csv"
            with open(dataset_path, "w") as f:
                f.write("question_id,question,answer,p_yes_tool1\n")
                # Only 1 data row, but we request row 5
                f.write("q1,Will it rain?,yes,0.8\n")

            shared_state = MagicMock()
            shared_state.bet_id_row_manager = {"q1": [5]}

            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(
                    sep=",", dataset_filename="dataset.csv"
                )
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                    with patch.object(
                        behaviour, "get_active_sampled_bet", return_value=bet
                    ):
                        with patch.object(
                            type(behaviour),
                            "shared_state",
                            new_callable=PropertyMock,
                        ) as mock_ss:
                            mock_ss.return_value = shared_state
                            with patch.object(
                                type(behaviour),
                                "sampled_bet",
                                new_callable=PropertyMock,
                            ) as mock_sb:
                                mock_sb.return_value = bet
                                result = behaviour._next_dataset_row()

        assert result is None
        assert behaviour._rows_exceeded is True


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestParseDatasetRow:
    """Tests for _parse_dataset_row."""

    def test_part_prefix_mode(self) -> None:
        """Should parse row with prefix part mode."""
        behaviour = _make_behaviour()
        shared_state = MagicMock()
        shared_state.mock_data = None

        row = {
            "p_yes_tool1": "0.8",
            "p_no_tool1": "0.2",
            "confidence_tool1": "0.9",
            "question_id": "q1",
            "question": "Will it rain?",
            "answer": "yes",
        }

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(
                p_yes_field_part="p_yes_",
                p_no_field_part="p_no_",
                confidence_field_part="confidence_",
                part_prefix_mode=True,
                question_id_field="question_id",
                question_field="question",
                answer_field="answer",
            )
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(mech_tool="tool1")
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = shared_state
                    result = behaviour._parse_dataset_row(row)

        parsed = json.loads(result)
        assert parsed["p_yes"] == "0.8"
        assert parsed["p_no"] == "0.2"
        assert parsed["confidence"] == "0.9"
        assert parsed["info_utility"] == "0"

    def test_part_suffix_mode(self) -> None:
        """Should parse row with suffix part mode."""
        behaviour = _make_behaviour()
        shared_state = MagicMock()
        shared_state.mock_data = None

        row = {
            "tool1_p_yes": "0.7",
            "tool1_p_no": "0.3",
            "tool1_confidence": "0.85",
            "question_id": "q1",
            "question": "Will it rain?",
            "answer": "yes",
        }

        with patch.object(
            type(behaviour), "benchmarking_mode", new_callable=PropertyMock
        ) as mock_bm:
            mock_bm.return_value = MagicMock(
                p_yes_field_part="_p_yes",
                p_no_field_part="_p_no",
                confidence_field_part="_confidence",
                part_prefix_mode=False,
                question_id_field="question_id",
                question_field="question",
                answer_field="answer",
            )
            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                mock_sd.return_value = MagicMock(mech_tool="tool1")
                with patch.object(
                    type(behaviour), "shared_state", new_callable=PropertyMock
                ) as mock_ss:
                    mock_ss.return_value = shared_state
                    result = behaviour._parse_dataset_row(row)

        parsed = json.loads(result)
        assert parsed["p_yes"] == "0.7"
        assert parsed["p_no"] == "0.3"
        assert parsed["confidence"] == "0.85"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestMockResponse:
    """Tests for _mock_response."""

    def test_mock_response_with_data(self) -> None:
        """Should set _mech_response when dataset row is available."""
        behaviour = _make_behaviour()
        pred_json = json.dumps(
            {"p_yes": "0.8", "p_no": "0.2", "confidence": "0.9", "info_utility": "0"}
        )

        with patch.object(
            behaviour, "_next_dataset_row", return_value={"some": "data"}
        ):
            with patch.object(behaviour, "_parse_dataset_row", return_value=pred_json):
                behaviour._mock_response()

        assert behaviour._mech_response is not None
        assert behaviour._mech_response.result == pred_json

    def test_mock_response_no_data(self) -> None:
        """Should not set _mech_response when no dataset rows."""
        behaviour = _make_behaviour()

        with patch.object(behaviour, "_next_dataset_row", return_value=None):
            behaviour._mock_response()

        assert behaviour._mech_response is None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestInitializeBetIdRowManager:
    """Tests for initialize_bet_id_row_manager."""

    def test_parses_csv_correctly(self) -> None:
        """Should parse CSV and return mapping from question_id to row numbers."""
        behaviour = _make_behaviour()

        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.csv"
            with open(dataset_path, "w") as f:
                f.write("question_id,question,answer,p_yes_tool1\n")
                f.write("q1,Will it rain?,yes,0.8\n")
                f.write("q2,Will it snow?,no,0.3\n")
                f.write("q1,Will it rain again?,yes,0.7\n")

            with patch.object(
                type(behaviour), "benchmarking_mode", new_callable=PropertyMock
            ) as mock_bm:
                mock_bm.return_value = MagicMock(
                    dataset_filename="dataset.csv",
                    question_id_field="question_id",
                )
                with patch.object(
                    type(behaviour), "params", new_callable=PropertyMock
                ) as mock_params:
                    mock_params.return_value = MagicMock(store_path=Path(tmpdir))
                    result = behaviour.initialize_bet_id_row_manager()

        assert result == {"q1": [1, 3], "q2": [2]}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


class TestAsyncAct:
    """Tests for async_act."""

    def _run_generator(self, gen: Generator) -> Any:
        """Run a generator to completion."""
        try:
            _ = next(gen)
            while True:
                _ = gen.send(None)
        except StopIteration as e:
            return e.value

    def test_setup_fails(self) -> None:
        """Should return None when _setup_policy_and_tools fails."""
        behaviour = _make_behaviour()

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that fails."""
            yield
            return False  # type: ignore[return-value]

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour.context, "benchmark_tool", benchmark):
                gen = behaviour.async_act()
                result = self._run_generator(gen)

        assert result is None

    def test_prediction_response_none(self) -> None:
        """Should handle None prediction_response gracefully."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=None):
                with patch.object(behaviour.context, "benchmark_tool", benchmark):
                    with patch.object(  # type: ignore[return-value]
                        type(behaviour),
                        "benchmarking_mode",
                        new_callable=PropertyMock,
                    ) as mock_bm:
                        mock_bm.return_value = MagicMock(enabled=False)
                        with patch.object(
                            behaviour, "finish_behaviour", side_effect=mock_finish
                        ):
                            gen = behaviour.async_act()
                            self._run_generator(gen)

        behaviour._store_all.assert_called_once()  # type: ignore[union-attr]

    def test_prediction_with_vote_not_selling_profitable(self) -> None:
        """Should process profitable bet when not in selling mode."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour._rows_exceeded = False  # type: ignore[method-assign]

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""  # type: ignore[return-value]
            yield
            return True  # type: ignore[return-value]

        def mock_is_profitable(*args: Any, **kwargs: Any) -> Generator:
            """Mock _is_profitable returning profitable."""
            yield
            return (True, 500)  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(
                    behaviour, "_is_profitable", side_effect=mock_is_profitable
                ):
                    with patch.object(behaviour.context, "benchmark_tool", benchmark):
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling_mode",
                            new_callable=PropertyMock,
                        ) as mock_rsm:  # type: ignore[method-assign]
                            mock_rsm.return_value = False
                            with patch.object(
                                type(behaviour),
                                "synced_timestamp",
                                new_callable=PropertyMock,
                            ) as mock_ts:
                                mock_ts.return_value = 1700000000
                                with patch.object(behaviour, "store_bets"):  # type: ignore[return-value]
                                    with patch.object(
                                        behaviour,
                                        "hash_stored_bets",
                                        return_value="hash123",
                                    ):  # type: ignore[return-value]
                                        with patch.object(
                                            type(behaviour),
                                            "policy",
                                            new_callable=PropertyMock,
                                        ) as mock_pol:
                                            mock_pol.return_value = mock_policy
                                            with patch.object(
                                                type(behaviour),
                                                "synchronized_data",
                                                new_callable=PropertyMock,
                                            ) as mock_sd:
                                                mock_sd.return_value = MagicMock(
                                                    mech_tool="tool1"
                                                )
                                                with patch.object(
                                                    type(behaviour),
                                                    "is_invalid_response",
                                                    new_callable=PropertyMock,
                                                ) as mock_ir:
                                                    mock_ir.return_value = False
                                                    with patch.object(
                                                        type(behaviour),
                                                        "benchmarking_mode",
                                                        new_callable=PropertyMock,
                                                    ) as mock_bm:
                                                        mock_bm.return_value = (
                                                            MagicMock(enabled=False)
                                                        )
                                                        with patch.object(
                                                            behaviour,
                                                            "finish_behaviour",
                                                            side_effect=mock_finish,
                                                        ):
                                                            gen = behaviour.async_act()
                                                            self._run_generator(gen)

        behaviour._store_all.assert_called_once()  # type: ignore[union-attr]
        mock_policy.tool_responded.assert_called_once()

    def test_prediction_with_selling_mode(self) -> None:
        """Should process selling when in selling mode and conditions met."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour.sell_amount = 100
        behaviour._rows_exceeded = False

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"
        mock_bet = _make_bet()

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(behaviour.context, "benchmark_tool", benchmark):
                    with patch.object(
                        type(behaviour),
                        "review_bets_for_selling_mode",
                        new_callable=PropertyMock,
                    ) as mock_rsm:
                        mock_rsm.return_value = True
                        with patch.object(
                            behaviour,
                            "should_sell_outcome_tokens",
                            return_value=True,
                        ):  # type: ignore[method-assign]
                            with patch.object(
                                type(behaviour),
                                "synced_timestamp",
                                new_callable=PropertyMock,
                            ) as mock_ts:
                                mock_ts.return_value = 1700000000
                                with patch.object(behaviour, "store_bets"):
                                    with patch.object(
                                        behaviour,  # type: ignore[return-value]
                                        "hash_stored_bets",
                                        return_value="hash123",
                                    ):
                                        with patch.object(
                                            type(behaviour),
                                            "policy",
                                            new_callable=PropertyMock,
                                        ) as mock_pol:
                                            mock_pol.return_value = mock_policy
                                            with patch.object(
                                                type(behaviour),
                                                "synchronized_data",
                                                new_callable=PropertyMock,
                                            ) as mock_sd:
                                                mock_sd.return_value = MagicMock(
                                                    mech_tool="tool1"
                                                )
                                                with patch.object(
                                                    type(behaviour),
                                                    "is_invalid_response",
                                                    new_callable=PropertyMock,
                                                ) as mock_ir:
                                                    mock_ir.return_value = False
                                                    with patch.object(
                                                        type(behaviour),
                                                        "benchmarking_mode",
                                                        new_callable=PropertyMock,
                                                    ) as mock_bm:
                                                        mock_bm.return_value = (
                                                            MagicMock(enabled=False)
                                                        )
                                                        with patch.object(
                                                            type(behaviour),
                                                            "sampled_bet",
                                                            new_callable=PropertyMock,
                                                        ) as mock_sb:
                                                            mock_sb.return_value = (
                                                                mock_bet
                                                            )
                                                            with patch.object(
                                                                behaviour,
                                                                "finish_behaviour",
                                                                side_effect=mock_finish,
                                                            ):
                                                                gen = (
                                                                    behaviour.async_act()
                                                                )
                                                                self._run_generator(gen)

        behaviour._store_all.assert_called_once()  # type: ignore[union-attr]

    def test_prediction_with_vote_none_benchmarking(self) -> None:
        """Should write benchmark results when vote is None and benchmarking enabled."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour._rows_exceeded = False

        pred = PredictionResponse(p_yes=0.5, p_no=0.5, confidence=0.9, info_utility=0.5)
        # vote is None because p_yes == p_no

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"

        shared_state = MagicMock()
        shared_state.benchmarking_mech_calls = 0
        shared_state.bet_id_row_manager = {"q1": [1]}

        mock_bet = _make_bet(id="q1")

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(behaviour.context, "benchmark_tool", benchmark):
                    with patch.object(
                        type(behaviour),
                        "benchmarking_mode",
                        new_callable=PropertyMock,
                    ) as mock_bm:
                        mock_bm.return_value = MagicMock(enabled=True)  # type: ignore[method-assign]
                        with patch.object(
                            behaviour, "_write_benchmark_results"
                        ) as mock_wbr:
                            with patch.object(
                                type(behaviour),
                                "shared_state",
                                new_callable=PropertyMock,
                            ) as mock_ss:
                                mock_ss.return_value = shared_state  # type: ignore[return-value]
                                with patch.object(
                                    type(behaviour),
                                    "policy",
                                    new_callable=PropertyMock,
                                ) as mock_pol:
                                    mock_pol.return_value = mock_policy
                                    with patch.object(
                                        type(behaviour),
                                        "synchronized_data",
                                        new_callable=PropertyMock,
                                    ) as mock_sd:
                                        mock_sd.return_value = MagicMock(
                                            mech_tool="tool1"
                                        )
                                        with patch.object(
                                            type(behaviour),
                                            "is_invalid_response",
                                            new_callable=PropertyMock,
                                        ) as mock_ir:
                                            mock_ir.return_value = True
                                            with patch.object(
                                                behaviour,
                                                "get_active_sampled_bet",
                                                return_value=mock_bet,
                                            ):
                                                with patch.object(
                                                    behaviour,
                                                    "_update_selected_bet",
                                                ):
                                                    with patch.object(
                                                        behaviour,
                                                        "finish_behaviour",
                                                        side_effect=mock_finish,
                                                    ):
                                                        gen = behaviour.async_act()
                                                        self._run_generator(gen)

        mock_wbr.assert_called_once()
        assert shared_state.benchmarking_mech_calls == 1

    def test_benchmarking_mode_updates_and_removes_row(self) -> None:
        """Should update selected bet and remove processed row in benchmarking mode."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour._rows_exceeded = False

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_is_profitable(*args: Any, **kwargs: Any) -> Generator:
            """Mock _is_profitable returning not profitable."""
            yield
            return (False, 0)  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"

        shared_state = MagicMock()
        shared_state.bet_id_row_manager = {"q1": [1, 2]}

        mock_bet = _make_bet(id="q1")

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(
                    behaviour, "_is_profitable", side_effect=mock_is_profitable
                ):
                    with patch.object(behaviour.context, "benchmark_tool", benchmark):  # type: ignore[method-assign]
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling_mode",
                            new_callable=PropertyMock,
                        ) as mock_rsm:
                            mock_rsm.return_value = False
                            with patch.object(
                                type(behaviour),  # type: ignore[return-value]
                                "synced_timestamp",
                                new_callable=PropertyMock,
                            ) as mock_ts:
                                mock_ts.return_value = 1700000000
                                with patch.object(  # type: ignore[return-value]
                                    type(behaviour),
                                    "policy",
                                    new_callable=PropertyMock,
                                ) as mock_pol:
                                    mock_pol.return_value = mock_policy
                                    with patch.object(
                                        type(behaviour),
                                        "synchronized_data",
                                        new_callable=PropertyMock,
                                    ) as mock_sd:
                                        mock_sd.return_value = MagicMock(
                                            mech_tool="tool1"
                                        )
                                        with patch.object(
                                            type(behaviour),
                                            "is_invalid_response",
                                            new_callable=PropertyMock,
                                        ) as mock_ir:
                                            mock_ir.return_value = False
                                            with patch.object(
                                                type(behaviour),
                                                "benchmarking_mode",
                                                new_callable=PropertyMock,
                                            ) as mock_bm:
                                                mock_bm.return_value = MagicMock(
                                                    enabled=True
                                                )
                                                with patch.object(
                                                    type(behaviour),
                                                    "shared_state",
                                                    new_callable=PropertyMock,
                                                ) as mock_ss:
                                                    mock_ss.return_value = shared_state
                                                    with patch.object(
                                                        behaviour,
                                                        "get_active_sampled_bet",
                                                        return_value=mock_bet,
                                                    ):
                                                        with patch.object(
                                                            behaviour,
                                                            "_update_selected_bet",
                                                        ) as mock_usb:
                                                            with patch.object(
                                                                behaviour,
                                                                "finish_behaviour",
                                                                side_effect=mock_finish,
                                                            ):
                                                                gen = (
                                                                    behaviour.async_act()
                                                                )
                                                                self._run_generator(gen)

        # Row should have been popped
        assert shared_state.bet_id_row_manager["q1"] == [2]
        mock_usb.assert_called_once()

    def test_selling_mode_opposite_vote(self) -> None:
        """Should use opposite vote when selling."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour.sell_amount = 100
        behaviour._rows_exceeded = False

        # vote = 1 (p_no > p_yes) - must be truthy for the opposite_vote branch
        pred = _make_prediction_response(p_yes=0.2, p_no=0.8, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"
        mock_bet = _make_bet()

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(behaviour.context, "benchmark_tool", benchmark):
                    with patch.object(
                        type(behaviour),
                        "review_bets_for_selling_mode",
                        new_callable=PropertyMock,
                    ) as mock_rsm:
                        mock_rsm.return_value = True
                        with patch.object(
                            behaviour,
                            "should_sell_outcome_tokens",
                            return_value=True,  # type: ignore[method-assign]
                        ):
                            with patch.object(
                                type(behaviour),
                                "synced_timestamp",
                                new_callable=PropertyMock,
                            ) as mock_ts:
                                mock_ts.return_value = 1700000000
                                with patch.object(behaviour, "store_bets"):
                                    with patch.object(
                                        behaviour,  # type: ignore[return-value]
                                        "hash_stored_bets",
                                        return_value="hash123",
                                    ):
                                        with patch.object(
                                            type(behaviour),
                                            "policy",
                                            new_callable=PropertyMock,
                                        ) as mock_pol:
                                            mock_pol.return_value = mock_policy
                                            with patch.object(
                                                type(behaviour),
                                                "synchronized_data",
                                                new_callable=PropertyMock,
                                            ) as mock_sd:
                                                mock_sd.return_value = MagicMock(
                                                    mech_tool="tool1"
                                                )
                                                with patch.object(
                                                    type(behaviour),
                                                    "is_invalid_response",
                                                    new_callable=PropertyMock,
                                                ) as mock_ir:
                                                    mock_ir.return_value = False
                                                    with patch.object(
                                                        type(behaviour),
                                                        "benchmarking_mode",
                                                        new_callable=PropertyMock,
                                                    ) as mock_bm:
                                                        mock_bm.return_value = (
                                                            MagicMock(enabled=False)
                                                        )
                                                        with patch.object(
                                                            type(behaviour),
                                                            "sampled_bet",
                                                            new_callable=PropertyMock,
                                                        ) as mock_sb:
                                                            mock_sb.return_value = (
                                                                mock_bet
                                                            )
                                                            with patch.object(
                                                                behaviour,
                                                                "finish_behaviour",
                                                                side_effect=mock_finish,
                                                            ):
                                                                gen = (
                                                                    behaviour.async_act()
                                                                )
                                                                self._run_generator(gen)

        # The opposite_vote call should have been made with the predicted vote
        mock_bet.opposite_vote.assert_called()

    def test_prediction_not_profitable_no_selling(self) -> None:
        """Should handle case where bet is not profitable and not selling."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour._rows_exceeded = False

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_is_profitable(*args: Any, **kwargs: Any) -> Generator:
            """Mock _is_profitable returning not profitable."""
            yield
            return (False, 0)  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(
                    behaviour, "_is_profitable", side_effect=mock_is_profitable
                ):
                    with patch.object(behaviour.context, "benchmark_tool", benchmark):
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling_mode",
                            new_callable=PropertyMock,
                        ) as mock_rsm:  # type: ignore[method-assign]
                            mock_rsm.return_value = False
                            with patch.object(
                                type(behaviour),
                                "synced_timestamp",
                                new_callable=PropertyMock,
                            ) as mock_ts:
                                mock_ts.return_value = 1700000000
                                with patch.object(  # type: ignore[return-value]
                                    type(behaviour),
                                    "policy",
                                    new_callable=PropertyMock,
                                ) as mock_pol:
                                    mock_pol.return_value = mock_policy  # type: ignore[return-value]
                                    with patch.object(
                                        type(behaviour),
                                        "synchronized_data",
                                        new_callable=PropertyMock,
                                    ) as mock_sd:
                                        mock_sd.return_value = MagicMock(
                                            mech_tool="tool1"
                                        )
                                        with patch.object(
                                            type(behaviour),
                                            "is_invalid_response",
                                            new_callable=PropertyMock,
                                        ) as mock_ir:
                                            mock_ir.return_value = False
                                            with patch.object(
                                                type(behaviour),
                                                "benchmarking_mode",
                                                new_callable=PropertyMock,
                                            ) as mock_bm:
                                                mock_bm.return_value = MagicMock(
                                                    enabled=False
                                                )
                                                with patch.object(
                                                    behaviour,
                                                    "finish_behaviour",
                                                    side_effect=mock_finish,
                                                ):
                                                    gen = behaviour.async_act()
                                                    self._run_generator(gen)

        behaviour._store_all.assert_called_once()  # type: ignore[union-attr]

    def test_benchmarking_empty_rows_queue(self) -> None:
        """Should handle empty rows queue in benchmarking mode gracefully."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour._rows_exceeded = False

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_is_profitable(*args: Any, **kwargs: Any) -> Generator:
            """Mock _is_profitable returning not profitable."""
            yield
            return (False, 0)  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"

        shared_state = MagicMock()
        shared_state.bet_id_row_manager = {"q1": []}

        mock_bet = _make_bet(id="q1")

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(
                    behaviour, "_is_profitable", side_effect=mock_is_profitable
                ):
                    with patch.object(behaviour.context, "benchmark_tool", benchmark):  # type: ignore[method-assign]
                        with patch.object(
                            type(behaviour),
                            "review_bets_for_selling_mode",
                            new_callable=PropertyMock,
                        ) as mock_rsm:
                            mock_rsm.return_value = False
                            with patch.object(
                                type(behaviour),  # type: ignore[return-value]
                                "synced_timestamp",
                                new_callable=PropertyMock,
                            ) as mock_ts:
                                mock_ts.return_value = 1700000000
                                with patch.object(  # type: ignore[return-value]
                                    type(behaviour),
                                    "policy",
                                    new_callable=PropertyMock,
                                ) as mock_pol:
                                    mock_pol.return_value = mock_policy
                                    with patch.object(
                                        type(behaviour),
                                        "synchronized_data",
                                        new_callable=PropertyMock,
                                    ) as mock_sd:
                                        mock_sd.return_value = MagicMock(
                                            mech_tool="tool1"
                                        )
                                        with patch.object(
                                            type(behaviour),
                                            "is_invalid_response",
                                            new_callable=PropertyMock,
                                        ) as mock_ir:
                                            mock_ir.return_value = False
                                            with patch.object(
                                                type(behaviour),
                                                "benchmarking_mode",
                                                new_callable=PropertyMock,
                                            ) as mock_bm:
                                                mock_bm.return_value = MagicMock(
                                                    enabled=True
                                                )
                                                with patch.object(
                                                    type(behaviour),
                                                    "shared_state",
                                                    new_callable=PropertyMock,
                                                ) as mock_ss:
                                                    mock_ss.return_value = shared_state
                                                    with patch.object(
                                                        behaviour,
                                                        "get_active_sampled_bet",
                                                        return_value=mock_bet,
                                                    ):
                                                        with patch.object(
                                                            behaviour,
                                                            "_update_selected_bet",
                                                        ):
                                                            with patch.object(
                                                                behaviour,
                                                                "finish_behaviour",
                                                                side_effect=mock_finish,
                                                            ):
                                                                gen = (
                                                                    behaviour.async_act()
                                                                )
                                                                self._run_generator(gen)

        # No pop should happen since rows_queue is empty
        assert shared_state.bet_id_row_manager["q1"] == []

    def test_selling_mode_not_selling(self) -> None:
        """Should handle selling mode when should_sell_outcome_tokens returns False."""
        behaviour = _make_behaviour()
        behaviour._store_all = MagicMock()  # type: ignore[method-assign]
        behaviour._rows_exceeded = False

        pred = _make_prediction_response(p_yes=0.8, p_no=0.2, confidence=0.9)

        def mock_setup(*args: Any, **kwargs: Any) -> Generator:
            """Mock setup that succeeds."""
            yield
            return True  # type: ignore[return-value]

        def mock_finish(*args: Any, **kwargs: Any) -> Generator:
            """Mock finish_behaviour."""
            yield

        benchmark = MagicMock()
        benchmark.measure.return_value.local.return_value.__enter__ = MagicMock()
        benchmark.measure.return_value.local.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "policy_data"

        with patch.object(behaviour, "_setup_policy_and_tools", side_effect=mock_setup):
            with patch.object(behaviour, "_get_decision", return_value=pred):
                with patch.object(behaviour.context, "benchmark_tool", benchmark):
                    with patch.object(
                        type(behaviour),
                        "review_bets_for_selling_mode",
                        new_callable=PropertyMock,
                    ) as mock_rsm:
                        mock_rsm.return_value = True
                        with patch.object(
                            behaviour,
                            "should_sell_outcome_tokens",
                            return_value=False,
                        ):
                            with patch.object(
                                type(behaviour),  # type: ignore[method-assign]
                                "policy",
                                new_callable=PropertyMock,
                            ) as mock_pol:
                                mock_pol.return_value = mock_policy
                                with patch.object(
                                    type(behaviour),
                                    "synchronized_data",
                                    new_callable=PropertyMock,  # type: ignore[return-value]
                                ) as mock_sd:
                                    mock_sd.return_value = MagicMock(mech_tool="tool1")
                                    with patch.object(
                                        type(behaviour),
                                        "is_invalid_response",
                                        new_callable=PropertyMock,
                                    ) as mock_ir:
                                        mock_ir.return_value = False
                                        with patch.object(
                                            type(behaviour),
                                            "benchmarking_mode",
                                            new_callable=PropertyMock,
                                        ) as mock_bm:
                                            mock_bm.return_value = MagicMock(
                                                enabled=False
                                            )
                                            with patch.object(
                                                behaviour,
                                                "finish_behaviour",
                                                side_effect=mock_finish,
                                            ):
                                                gen = behaviour.async_act()
                                                self._run_generator(gen)

        behaviour._store_all.assert_called_once()  # type: ignore[union-attr]
