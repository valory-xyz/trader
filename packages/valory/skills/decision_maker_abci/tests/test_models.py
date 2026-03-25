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

"""Tests for the models module of decision_maker_abci."""

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hexbytes import HexBytes
from web3.constants import HASH_ZERO

from packages.valory.skills.decision_maker_abci.models import (
    AccuracyInfoFields,
    BenchmarkingMockData,
    DecisionMakerParams,
    LiquidityInfo,
    MultisendBatch,
    PromptTemplate,
    REQUIRED_BET_TEMPLATE_KEYS,
    RedeemingProgress,
    STRATEGY_KELLY_CRITERION,
    SharedState,
    ZERO_BYTES,
    ZERO_HEX,
    _raise_incorrect_config,
    check_prompt_template,
    extract_keys_from_template,
)


class TestPromptTemplate:
    """Tests for the PromptTemplate class."""

    def test_template_substitution(self) -> None:
        """Test that PromptTemplate performs substitution with '@' delimiter."""
        template = PromptTemplate("Will @{question} happen? Yes: @{yes}, No: @{no}")
        result = template.safe_substitute(
            question="it rain", yes="likely", no="unlikely"
        )
        assert result == "Will it rain happen? Yes: likely, No: unlikely"


class TestLiquidityInfo:
    """Tests for the LiquidityInfo dataclass."""

    def test_default_values(self) -> None:
        """Test that default values are None."""
        info = LiquidityInfo()
        assert info.l0_start is None
        assert info.l1_start is None
        assert info.l0_end is None
        assert info.l1_end is None

    def test_validate_start_information_success(self) -> None:
        """Test validate_start_information with valid data."""
        info = LiquidityInfo(l0_start=100, l1_start=200)
        result = info.validate_start_information()
        assert result == (100, 200)

    def test_validate_start_information_missing_l0(self) -> None:
        """Test validate_start_information raises when l0_start is None."""
        info = LiquidityInfo(l1_start=200)
        with pytest.raises(ValueError, match="incomplete"):
            info.validate_start_information()

    def test_validate_start_information_missing_l1(self) -> None:
        """Test validate_start_information raises when l1_start is None."""
        info = LiquidityInfo(l0_start=100)
        with pytest.raises(ValueError, match="incomplete"):
            info.validate_start_information()

    def test_validate_end_information_success(self) -> None:
        """Test validate_end_information with valid data."""
        info = LiquidityInfo(l0_end=300, l1_end=400)
        result = info.validate_end_information()
        assert result == (300, 400)

    def test_validate_end_information_missing_l0(self) -> None:
        """Test validate_end_information raises when l0_end is None."""
        info = LiquidityInfo(l1_end=400)
        with pytest.raises(ValueError, match="incomplete"):
            info.validate_end_information()

    def test_validate_end_information_missing_l1(self) -> None:
        """Test validate_end_information raises when l1_end is None."""
        info = LiquidityInfo(l0_end=300)
        with pytest.raises(ValueError, match="incomplete"):
            info.validate_end_information()

    def test_get_new_prices(self) -> None:
        """Test get_new_prices calculation."""
        info = LiquidityInfo(l0_end=200, l1_end=400)
        liquidity_constants = [1000.0, 2000.0]
        prices = info.get_new_prices(liquidity_constants)
        assert prices == [5.0, 5.0]

    def test_get_end_liquidity(self) -> None:
        """Test get_end_liquidity returns end liquidity values."""
        info = LiquidityInfo(l0_end=300, l1_end=400)
        result = info.get_end_liquidity()
        assert result == [300, 400]


class TestRedeemingProgress:
    """Tests for the RedeemingProgress dataclass."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        progress = RedeemingProgress()
        assert progress.trades == set()
        assert progress.utilized_tools == {}
        assert progress.policy is None
        assert progress.claimable_amounts == {}
        assert progress.earliest_block_number == 0
        assert progress.event_filtering_batch_size == 0
        assert progress.check_started is False
        assert progress.check_from_block == "earliest"
        assert progress.check_to_block == "latest"
        assert progress.cleaned is False
        assert progress.payouts == {}
        assert progress.unredeemed_trades == {}
        assert progress.claim_started is False
        assert progress.claim_from_block == "earliest"
        assert progress.claim_to_block == "latest"
        assert progress.answered == []
        assert progress.claiming_condition_ids == []
        assert progress.claimed_condition_ids == []

    def test_check_finished_not_started(self) -> None:
        """Test check_finished when check has not started."""
        progress = RedeemingProgress()
        assert progress.check_finished is False

    def test_check_finished_in_progress(self) -> None:
        """Test check_finished when check is in progress."""
        progress = RedeemingProgress(
            check_started=True, check_from_block=0, check_to_block=100
        )
        assert progress.check_finished is False

    def test_check_finished_completed(self) -> None:
        """Test check_finished when check is completed."""
        progress = RedeemingProgress(
            check_started=True, check_from_block=100, check_to_block=100
        )
        assert progress.check_finished is True

    def test_claim_finished_not_started(self) -> None:
        """Test claim_finished when claim has not started."""
        progress = RedeemingProgress()
        assert progress.claim_finished is False

    def test_claim_finished_in_progress(self) -> None:
        """Test claim_finished when claim is in progress."""
        progress = RedeemingProgress(
            claim_started=True, claim_from_block=0, claim_to_block=100
        )
        assert progress.claim_finished is False

    def test_claim_finished_completed(self) -> None:
        """Test claim_finished when claim is completed."""
        progress = RedeemingProgress(
            claim_started=True, claim_from_block=100, claim_to_block=100
        )
        assert progress.claim_finished is True

    def test_claim_params_empty(self) -> None:
        """Test claim_params when answered is empty."""
        progress = RedeemingProgress()
        result = progress.claim_params
        assert result == ([], [], [], [])

    def test_claim_params_with_answers(self) -> None:
        """Test claim_params with valid answers."""
        progress = RedeemingProgress(
            answered=[
                {
                    "args": {
                        "history_hash": b"\x00" * 32,
                        "user": "0xuser1",
                        "bond": 100,
                        "answer": b"\x01",
                    }
                },
                {
                    "args": {
                        "history_hash": b"\x01" * 32,
                        "user": "0xuser2",
                        "bond": 200,
                        "answer": b"\x02",
                    }
                },
            ]
        )
        result = progress.claim_params
        assert result is not None
        history_hashes, addresses, bonds, answers = result
        assert len(history_hashes) == 2
        assert len(addresses) == 2
        assert len(bonds) == 2
        assert len(answers) == 2
        # Last entry in reversed iteration gets ZERO_BYTES
        assert history_hashes[1] == ZERO_BYTES
        # First entry in reversed iteration gets history_hash from self.answered[i+1]
        # reversed: [answer2, answer1], i=0: self.answered[1] = answer2
        assert history_hashes[0] == b"\x01" * 32

    def test_claim_params_with_key_error(self) -> None:
        """Test claim_params returns None when KeyError is raised."""
        progress = RedeemingProgress(
            answered=[
                {"args": {"missing_key": "value"}},
            ]
        )
        result = progress.claim_params
        assert result is None


class TestExtractKeysFromTemplate:
    """Tests for the extract_keys_from_template function."""

    def test_extract_keys_at_delimiter(self) -> None:
        """Test extracting keys with '@' delimiter."""
        keys = extract_keys_from_template("@", "@{yes} and @{no} and @{question}")
        assert keys == {"yes", "no", "question"}

    def test_extract_keys_dollar_delimiter(self) -> None:
        """Test extracting keys with '$' delimiter."""
        keys = extract_keys_from_template("$", "${key1} ${key2}")
        assert keys == {"key1", "key2"}

    def test_extract_keys_no_match(self) -> None:
        """Test extracting keys when no keys are present."""
        keys = extract_keys_from_template("@", "no keys here")
        assert keys == set()


class TestCheckPromptTemplate:
    """Tests for the check_prompt_template function."""

    def test_valid_template(self) -> None:
        """Test that a valid template passes the check."""
        template = PromptTemplate("@{yes} @{no} @{question}")
        check_prompt_template(template)

    def test_missing_key_raises(self) -> None:
        """Test that a template missing required keys raises ValueError."""
        template = PromptTemplate("@{yes} @{no}")
        with pytest.raises(ValueError, match="should contain exclusively"):
            check_prompt_template(template)

    def test_extra_key_raises(self) -> None:
        """Test that a template with extra keys raises an error (KeyError from pop on empty set)."""
        template = PromptTemplate("@{yes} @{no} @{question} @{extra}")
        with pytest.raises(KeyError):
            check_prompt_template(template)

    def test_no_keys_raises(self) -> None:
        """Test that a template with no keys raises ValueError."""
        template = PromptTemplate("no keys at all")
        with pytest.raises(ValueError, match="should contain exclusively"):
            check_prompt_template(template)


class TestRaiseIncorrectConfig:
    """Tests for the _raise_incorrect_config function."""

    def test_raises_value_error(self) -> None:
        """Test that _raise_incorrect_config raises ValueError."""
        with pytest.raises(ValueError, match="incorrectly formatted"):
            _raise_incorrect_config("test_key", [1, 2, 3])


class TestMultisendBatch:
    """Tests for the MultisendBatch dataclass."""

    def test_creation(self) -> None:
        """Test creating a MultisendBatch."""
        batch = MultisendBatch(to="0xaddress", data=HexBytes(b"\x01"))
        assert batch.to == "0xaddress"
        assert batch.data == HexBytes(b"\x01")
        assert batch.value == 0

    def test_custom_value(self) -> None:
        """Test creating a MultisendBatch with custom value."""
        batch = MultisendBatch(to="0xaddress", data=HexBytes(b"\x01"), value=100)
        assert batch.value == 100


class TestBenchmarkingMockData:
    """Tests for the BenchmarkingMockData dataclass."""

    def test_creation(self) -> None:
        """Test creating a BenchmarkingMockData instance."""
        data = BenchmarkingMockData(
            id="test_id", question="Will it rain?", answer="yes", p_yes=0.8
        )
        assert data.id == "test_id"
        assert data.question == "Will it rain?"
        assert data.answer == "yes"
        assert data.p_yes == 0.8

    def test_is_winning_yes_high_pyes(self) -> None:
        """Test is_winning when answer is yes and p_yes > 0.5."""
        data = BenchmarkingMockData(id="1", question="q", answer="yes", p_yes=0.7)
        assert data.is_winning is True

    def test_is_winning_yes_low_pyes(self) -> None:
        """Test is_winning when answer is yes and p_yes < 0.5."""
        data = BenchmarkingMockData(id="1", question="q", answer="yes", p_yes=0.3)
        assert data.is_winning is False

    def test_is_winning_no_low_pyes(self) -> None:
        """Test is_winning when answer is no and p_yes < 0.5."""
        data = BenchmarkingMockData(id="1", question="q", answer="no", p_yes=0.3)
        assert data.is_winning is True

    def test_is_winning_no_high_pyes(self) -> None:
        """Test is_winning when answer is no and p_yes > 0.5."""
        data = BenchmarkingMockData(id="1", question="q", answer="no", p_yes=0.7)
        assert data.is_winning is False


class TestConstants:
    """Tests for module-level constants."""

    def test_zero_hex(self) -> None:
        """Test ZERO_HEX constant."""
        assert ZERO_HEX == HASH_ZERO[2:]

    def test_zero_bytes(self) -> None:
        """Test ZERO_BYTES constant."""
        assert ZERO_BYTES == bytes.fromhex(HASH_ZERO[2:])

    def test_required_bet_template_keys(self) -> None:
        """Test REQUIRED_BET_TEMPLATE_KEYS constant."""
        assert REQUIRED_BET_TEMPLATE_KEYS == {"yes", "no", "question"}


def _make_shared_state_via_init() -> SharedState:
    """Create a SharedState by calling __init__ with mocked super().__init__."""
    mock_context = MagicMock()
    with patch.object(SharedState.__mro__[1], "__init__", return_value=None):
        state = SharedState(skill_context=mock_context)
    state._context = mock_context
    return state


class TestSharedStateInit:
    """Tests for the SharedState.__init__ method."""

    def test_init_sets_default_attributes(self) -> None:
        """Test that __init__ sets all expected default attributes."""
        state = _make_shared_state_via_init()
        assert isinstance(state.redeeming_progress, RedeemingProgress)
        assert state.strategy_to_filehash == {}
        assert state.strategies_executables == {}
        assert state.in_flight_req is False
        assert state.req_to_callback == {}
        assert state.mock_data is None
        assert state.liquidity_cache == {}
        assert state.simulated_days == []
        assert state.simulated_days_idx == 0
        assert state.liquidity_amounts == {}
        assert state.liquidity_prices == {}
        assert state.last_benchmarking_has_run is False
        assert state.bet_id_row_manager == {}
        assert state.benchmarking_mech_calls == 0
        assert state.mech_timed_out is False


class TestSharedState:
    """Tests for the SharedState model class."""

    def setup_method(self) -> None:
        """Set up the SharedState instance bypassing __init__."""
        self.state = object.__new__(SharedState)
        self.state.mock_data = None
        self.state.liquidity_prices = {}
        self.state.liquidity_amounts = {}
        self.state.simulated_days = []
        self.state.simulated_days_idx = 0
        self.state._context = MagicMock()
        self.state.redeeming_progress = MagicMock()
        self.state.strategy_to_filehash = {}
        self.state.strategies_executables = {}

    def test_mock_question_id_raises_when_no_mock_data(self) -> None:
        """Test mock_question_id raises ValueError when mock_data is None."""
        with pytest.raises(ValueError, match="mock data have not been set"):
            _ = self.state.mock_question_id

    def test_mock_question_id_returns_id(self) -> None:
        """Test mock_question_id returns the id from mock_data."""
        self.state.mock_data = BenchmarkingMockData(
            id="test_id", question="q", answer="yes", p_yes=0.5
        )
        assert self.state.mock_question_id == "test_id"

    def test_get_liquidity_info_raises_when_id_not_found(self) -> None:
        """Test _get_liquidity_info raises ValueError when id is not in the data."""
        self.state.mock_data = BenchmarkingMockData(
            id="missing_id", question="q", answer="yes", p_yes=0.5
        )
        with pytest.raises(ValueError, match="no liquidity information"):
            self.state._get_liquidity_info({})

    def test_get_liquidity_info_returns_data(self) -> None:
        """Test _get_liquidity_info returns data when id is found."""
        self.state.mock_data = BenchmarkingMockData(
            id="test_id", question="q", answer="yes", p_yes=0.5
        )
        data = {"test_id": [100, 200]}
        result = self.state._get_liquidity_info(data)
        assert result == [100, 200]

    def test_current_liquidity_prices_getter(self) -> None:
        """Test current_liquidity_prices getter."""
        self.state.mock_data = BenchmarkingMockData(
            id="test_id", question="q", answer="yes", p_yes=0.5
        )
        self.state.liquidity_prices = {"test_id": [0.6, 0.4]}
        result = self.state.current_liquidity_prices
        assert result == [0.6, 0.4]

    def test_current_liquidity_prices_setter(self) -> None:
        """Test current_liquidity_prices setter."""
        self.state.mock_data = BenchmarkingMockData(
            id="test_id", question="q", answer="yes", p_yes=0.5
        )
        self.state.current_liquidity_prices = [0.7, 0.3]
        assert self.state.liquidity_prices["test_id"] == [0.7, 0.3]

    def test_current_liquidity_amounts_getter(self) -> None:
        """Test current_liquidity_amounts getter."""
        self.state.mock_data = BenchmarkingMockData(
            id="test_id", question="q", answer="yes", p_yes=0.5
        )
        self.state.liquidity_amounts = {"test_id": [1000, 2000]}
        result = self.state.current_liquidity_amounts
        assert result == [1000, 2000]

    def test_current_liquidity_amounts_setter(self) -> None:
        """Test current_liquidity_amounts setter."""
        self.state.mock_data = BenchmarkingMockData(
            id="test_id", question="q", answer="yes", p_yes=0.5
        )
        self.state.current_liquidity_amounts = [3000, 4000]
        assert self.state.liquidity_amounts["test_id"] == [3000, 4000]

    def test_initialize_simulated_now_timestamps(self) -> None:
        """Test _initialize_simulated_now_timestamps populates simulated_days."""
        now_ts = int(time.time())
        safe_voting_range = 60

        # Create mock bets with openingTimestamp in the future
        mock_bet1 = MagicMock()
        mock_bet1.openingTimestamp = now_ts + 86400 * 3 + safe_voting_range + 1
        mock_bet2 = MagicMock()
        mock_bet2.openingTimestamp = now_ts + 86400 * 5 + safe_voting_range + 1
        bets = [mock_bet1, mock_bet2]

        self.state._initialize_simulated_now_timestamps(bets, safe_voting_range)  # type: ignore[arg-type]

        assert self.state.simulated_days_idx == 0
        assert len(self.state.simulated_days) > 0
        # Each day is separated by one day interval
        for i in range(1, len(self.state.simulated_days)):  # type: ignore[arg-type]
            diff = self.state.simulated_days[i] - self.state.simulated_days[i - 1]
            assert diff == 86400

    def test_increase_one_day_simulation(self) -> None:
        """Test increase_one_day_simulation increments the index."""
        self.state.simulated_days_idx = 2
        self.state.increase_one_day_simulation()
        assert self.state.simulated_days_idx == 3

    def test_check_benchmarking_finished_false(self) -> None:
        """Test check_benchmarking_finished returns False when not all days simulated."""
        self.state.simulated_days = [1, 2, 3]
        self.state.simulated_days_idx = 1
        assert self.state.check_benchmarking_finished() is False

    def test_check_benchmarking_finished_true(self) -> None:
        """Test check_benchmarking_finished returns True when all days simulated."""
        self.state.simulated_days = [1, 2, 3]
        self.state.simulated_days_idx = 3
        assert self.state.check_benchmarking_finished() is True

    def test_get_simulated_now_timestamp_initializes_when_empty(self) -> None:
        """Test get_simulated_now_timestamp initializes simulated_days when empty."""
        now_ts = int(time.time())
        safe_voting_range = 60

        mock_bet = MagicMock()
        mock_bet.openingTimestamp = now_ts + 86400 * 2 + safe_voting_range + 1
        bets = [mock_bet]

        result = self.state.get_simulated_now_timestamp(bets, safe_voting_range)  # type: ignore[arg-type]

        assert len(self.state.simulated_days) > 0
        assert result == self.state.simulated_days[0]

    def test_get_simulated_now_timestamp_returns_current_day(self) -> None:  # type: ignore[arg-type]
        """Test get_simulated_now_timestamp returns the timestamp at the current index."""
        self.state.simulated_days = [100, 200, 300]
        self.state.simulated_days_idx = 1
        result = self.state.get_simulated_now_timestamp([], 60)
        assert result == 200

    def test_setup(self) -> None:
        """Test the setup method of SharedState."""
        mock_params = MagicMock()
        mock_params.event_filtering_batch_size = 100
        mock_params.file_hash_to_strategies = {
            "hash1": ["strategy_a", "strategy_b"],
            "hash2": ["strategy_c"],
        }
        mock_params.trading_strategy = "strategy_a"
        self.state.context.params = mock_params
        self.state.redeeming_progress = MagicMock()

        with patch.object(type(self.state).__mro__[1], "setup", return_value=None):  # type: ignore[arg-type]
            self.state.setup()

        assert self.state.strategy_to_filehash == {
            "strategy_a": "hash1",
            "strategy_b": "hash1",
            "strategy_c": "hash2",
        }
        assert self.state.redeeming_progress.event_filtering_batch_size == 100

    def test_setup_raises_for_invalid_strategy(self) -> None:
        """Test setup raises ValueError when selected strategy is not in executables."""
        mock_params = MagicMock()
        mock_params.event_filtering_batch_size = 100
        mock_params.file_hash_to_strategies = {
            "hash1": ["strategy_a"],
        }
        mock_params.trading_strategy = "nonexistent_strategy"
        self.state.context.params = mock_params
        self.state.redeeming_progress = MagicMock()

        with patch.object(
            type(self.state).__mro__[1], "setup", return_value=None  # type: ignore[arg-type]
        ), pytest.raises(ValueError, match="not in the strategies"):
            self.state.setup()


def _build_decision_maker_params_kwargs() -> dict:
    """Build a complete kwargs dict suitable for DecisionMakerParams.__init__."""
    mock_context = MagicMock()
    return {
        "skill_context": mock_context,
        "name": "params",
        "agent_registry_address": "0xaddr",
        "sample_bets_closing_days": 7,
        "trading_strategy": "kelly_criterion",
        "use_fallback_strategy": False,
        "tools_accuracy_hash": "hash123",
        "prompt_template": "@{yes} @{no} @{question}",
        "dust_threshold": 100,
        "conditional_tokens_address": "0xcond",
        "realitio_proxy_address": "0xproxy",
        "realitio_address": "0xrealitio",
        "event_filtering_batch_size": 500,
        "reduce_factor": 0.5,
        "minimum_batch_size": 10,
        "max_filtering_retries": 3,
        "redeeming_batch_size": 5,
        "redeem_round_timeout": 30.0,
        "slippage": 0.1,
        "policy_epsilon": 0.2,
        "tool_punishment_multiplier": 2,
        "contract_timeout": 10.0,
        "file_hash_to_strategies": {"hash1": ["kelly_criterion"]},
        "strategies_kwargs": {"kelly_criterion": {}},
        "use_subgraph_for_redeeming": True,
        "rpc_sleep_time": 5,
        "service_endpoint": "http://localhost:8080",
        "safe_voting_range": 86400,
        "rebet_chance": 0.5,
        "policy_store_update_offset": 10,
        "expected_mech_response_time": 600,
        "mech_invalid_response": "invalid",
        "mech_consecutive_failures_threshold": 3,
        "tool_quarantine_duration": 10800,
        "enable_position_review": False,
        "review_period_seconds": 3600,
        "polymarket_builder_program_enabled": False,
        "polymarket_usdc_address": "0xusdc",
        "polymarket_ctf_address": "0xctf",
        "polymarket_ctf_exchange_address": "0xexch",
        "polymarket_neg_risk_ctf_exchange_address": "0xnegexch",
        "polymarket_neg_risk_adapter_address": "0xnegadapt",
        "pol_threshold_for_swap": 1000,
        "slippages_for_swap": {"ETH": 0.01},
        "is_outcome_side_threshold_filter_enabled": False,
        "outcome_side_threshold_filter_threshold": 0.5,
    }


class TestDecisionMakerParams:
    """Tests for the DecisionMakerParams model class."""

    def test_sample_bets_closing_days_zero_raises(self) -> None:
        """Test that sample_bets_closing_days <= 0 raises ValueError via __init__."""

        # Mock _ensure to return 0 for sample_bets_closing_days
        def mock_ensure(key: str, kwargs: dict, type_: Any) -> Any:
            """Return controlled values for _ensure calls."""
            if key == "sample_bets_closing_days":
                return 0
            return MagicMock()

        with patch.object(
            DecisionMakerParams, "_ensure", side_effect=mock_ensure
        ), pytest.raises(ValueError, match="must be positive"):
            DecisionMakerParams(
                skill_context=MagicMock(),
                agent_registry_address="0xaddr",
                sample_bets_closing_days=0,
            )

    def test_full_init(self) -> None:
        """Test DecisionMakerParams.__init__ with all required kwargs."""
        kwargs = _build_decision_maker_params_kwargs()
        with patch.object(
            DecisionMakerParams.__mro__[1], "__init__", return_value=None
        ):
            params = DecisionMakerParams(**kwargs)
        assert params.sample_bets_closing_days == 7
        assert params.trading_strategy == "kelly_criterion"
        assert params.slippage == 0.1
        assert params.epsilon == 0.2
        assert params.agent_registry_address == "0xaddr"
        assert params.dust_threshold == 100
        assert params.event_filtering_batch_size == 500
        assert params.reduce_factor == 0.5
        assert params.minimum_batch_size == 10
        assert params.max_filtering_retries == 3
        assert params.redeeming_batch_size == 5
        assert params.redeem_round_timeout == 30.0
        assert params.tool_punishment_multiplier == 2
        assert params.contract_timeout == 10.0
        assert params.use_subgraph_for_redeeming is True
        assert params.rpc_sleep_time == 5
        assert params.service_endpoint == "http://localhost:8080"
        assert params.safe_voting_range == 86400
        assert params.rebet_chance == 0.5
        assert params.policy_store_update_offset == 10
        assert params.expected_mech_response_time == 600
        assert params.mech_invalid_response == "invalid"
        assert params.policy_threshold == 3
        assert params.tool_quarantine_duration == 10800
        assert params.enable_position_review is False
        assert params.review_period_seconds == 3600
        assert params.min_confidence_for_selling == 0.5
        assert params.polymarket_builder_program_enabled is False
        assert params.polymarket_usdc_address == "0xusdc"
        assert params.polymarket_ctf_address == "0xctf"
        assert params.polymarket_ctf_exchange_address == "0xexch"
        assert params.polymarket_neg_risk_ctf_exchange_address == "0xnegexch"
        assert params.polymarket_neg_risk_adapter_address == "0xnegadapt"
        assert params.pol_threshold_for_swap == 1000
        assert params.slippages_for_swap == {"ETH": 0.01}
        assert params.is_outcome_side_threshold_filter_enabled is False
        assert params.outcome_side_threshold_filter_threshold == 0.5

    def test_prompt_template_property(self) -> None:
        """Test prompt_template property returns a PromptTemplate."""
        params = object.__new__(DecisionMakerParams)
        params._prompt_template = "@{yes} @{no} @{question}"
        result = params.prompt_template
        assert isinstance(result, PromptTemplate)
        assert result.template == "@{yes} @{no} @{question}"

    def test_slippage_getter(self) -> None:
        """Test slippage getter returns the private _slippage value."""
        params = object.__new__(DecisionMakerParams)
        params._slippage = 0.5
        assert params.slippage == 0.5

    def test_slippage_setter_valid(self) -> None:
        """Test slippage setter with valid value."""
        params = object.__new__(DecisionMakerParams)
        params._slippage = 0.0
        params.slippage = 0.5
        assert params.slippage == 0.5

    def test_slippage_setter_invalid_negative(self) -> None:
        """Test slippage setter raises ValueError for negative value."""
        params = object.__new__(DecisionMakerParams)
        params._slippage = 0.0
        with pytest.raises(ValueError, match="not in the range"):
            params.slippage = -0.1

    def test_slippage_setter_invalid_above_one(self) -> None:
        """Test slippage setter raises ValueError for value above 1."""
        params = object.__new__(DecisionMakerParams)
        params._slippage = 0.0
        with pytest.raises(ValueError, match="not in the range"):
            params.slippage = 1.1


class TestAccuracyInfoFields:
    """Tests for the AccuracyInfoFields model class."""

    def test_init(self) -> None:
        """Test AccuracyInfoFields.__init__ sets all fields."""
        mock_context = MagicMock()
        with patch.object(AccuracyInfoFields.__mro__[1], "__init__", return_value=None):
            fields = AccuracyInfoFields(
                skill_context=mock_context,
                name="accuracy_info_fields",
                tool="tool_field",
                requests="requests_field",
                accuracy="accuracy_field",
                sep=",",
                max="max_field",
                datetime_format="%Y-%m-%d",
            )
        assert fields.tool == "tool_field"
        assert fields.requests == "requests_field"
        assert fields.accuracy == "accuracy_field"
        assert fields.sep == ","
        assert fields.max == "max_field"
        assert fields.datetime_format == "%Y-%m-%d"
