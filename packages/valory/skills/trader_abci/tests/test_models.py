# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""Test the models.py module of the trader skill."""
import os.path
from pathlib import Path

from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext
from packages.valory.skills.abstract_round_abci.tests.test_models import (
    BASE_DUMMY_PARAMS,
    BASE_DUMMY_SPECS_CONFIG,
)
from packages.valory.skills.market_manager_abci.tests.test_models import (
    MARKET_MANAGER_PARAMS,
)
from packages.valory.skills.trader_abci.models import (
    MARGIN,
    RandomnessApi,
    SharedState,
    TraderParams,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.tests.test_tx_settlement_multiplexer_models import (
    DUMMY_TX_SETTLEMENT_MULTIPLEXER_PARAMS,
)


CURRENT_FILE_PATH = Path(__file__).resolve()
PACKAGE_DIR = CURRENT_FILE_PATH.parents[2]

DUMMY_DECISION_MAKER_PARAMS = {
    "sample_bets_closing_days": 1,
    "trading_strategy": "test",
    "use_fallback_strategy": True,
    "tools_accuracy_hash": "test",
    "bet_threshold": 1,
    "blacklisting_duration": 1,
    "prompt_template": "@{yes}@{no}@{question}",
    "dust_threshold": 1,
    "conditional_tokens_address": "0x123",
    "realitio_proxy_address": "0x456",
    "realitio_address": "0x789",
    "event_filtering_batch_size": 1,
    "reduce_factor": 1.1,
    "minimum_batch_size": 1,
    "max_filtering_retries": 1,
    "redeeming_batch_size": 1,
    "redeem_round_timeout": 1.1,
    "slippage": 0.05,
    "policy_epsilon": 0.1,
    "agent_registry_address": "0xabc",
    "irrelevant_tools": [],
    "tool_punishment_multiplier": 1,
    "contract_timeout": 2.0,
    "file_hash_to_strategies_json": [
        ['{"k1": "key2"}', '{"b1": "b2"}'],
        ['{"v1": "v2"}', '{"b1": "b2"}'],
    ],
    "strategies_kwargs": [
        ['{"k1": "key2"}', '{"b1": "b2"}'],
        ['{"v1": "v2"}', '{"b1": "b2"}'],
    ],
    "use_subgraph_for_redeeming": True,
    "use_nevermined": False,
    "rpc_sleep_time": 2,
    "mech_to_subscription_params": [
        ['{"k1": "key2"}', '{"b1": "b2"}'],
        ['{"v1": "v2"}', '{"b1": "b2"}'],
    ],
    "service_endpoint": "http://example.com",
    "store_path": str(PACKAGE_DIR),
}

DUMMY_MECH_INTERACT_PARAMS = {
    "multisend_address": "0x1234567890abcdef1234567890abcdef12345678",
    "multisend_batch_size": 100,
    "mech_contract_address": "0xabcdef1234567890abcdef1234567890abcdef12",
    "mech_request_price": 10,
    "ipfs_address": "https://ipfs.example.com",
    "mech_chain_id": "gnosis",
    "mech_wrapped_native_token_address": "0x9876543210abcdef9876543210abcdef98765432",
    "mech_interaction_sleep_time": 5,
}

DUMMY_TERMINATION_PARAMS = {"termination_sleep": 1, "termination_from_block": 1}

DUMMY_TRANSACTION_PARAMS = {
    "init_fallback_gas": 1,
    "keeper_allowed_retries": 1,
    "validate_timeout": 300,
    "finalize_timeout": 1.1,
    "history_check_timeout": 1,
}

DUMMY_CHECK_STOP_TRADING_PARAMS = {
    "disable_trading": True,
    "stop_trading_if_staking_kpi_met": True,
}

DUMMY_STAKING_PARAMS = {
    "staking_contract_address": "test",
    "staking_interaction_sleep_time": 1,
    "mech_activity_checker_contract": "test",
}


class TestRandomnessApi:
    """Test the RandomnessApi of the Trader skill."""

    def test_initialization(self) -> None:
        """Test initialization."""
        RandomnessApi(**BASE_DUMMY_SPECS_CONFIG)


class TestTraderParams:
    """Test the TraderParams of the Trader skill."""

    def test_initialization(self) -> None:
        """Test initialization."""
        TraderParams(
            **BASE_DUMMY_PARAMS,
            **DUMMY_DECISION_MAKER_PARAMS,
            **MARKET_MANAGER_PARAMS,
            **DUMMY_MECH_INTERACT_PARAMS,
            **DUMMY_TERMINATION_PARAMS,
            **DUMMY_TRANSACTION_PARAMS,
            **DUMMY_TX_SETTLEMENT_MULTIPLEXER_PARAMS,
            **DUMMY_STAKING_PARAMS,
            **DUMMY_CHECK_STOP_TRADING_PARAMS
        )


class TestSharedState:
    """Test SharedState of CheckStopTrading."""

    def setup(self) -> None:
        """Set up tests."""
        self.shared_state = SharedState(name="", skill_context=DummyContext())

    def test_initialization(self) -> None:
        """Test initialization."""
        SharedState(name="", skill_context=DummyContext())

    def test_params(self) -> None:
        """Test params of SharedState."""

    def test_setup(self) -> None:
        """Test setup of SharedState."""
