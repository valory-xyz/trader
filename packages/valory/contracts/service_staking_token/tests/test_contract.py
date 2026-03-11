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

"""Tests for the ServiceStakingTokenContract."""

from unittest.mock import MagicMock, patch

from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)


CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


class TestServiceStakingTokenContract:
    """Tests for ServiceStakingTokenContract."""

    def setup_method(self) -> None:
        """Set up common test fixtures."""
        self.mock_ledger_api = MagicMock()
        self.mock_contract = MagicMock()
        self.patcher = patch.object(
            ServiceStakingTokenContract,
            "get_instance",
            return_value=self.mock_contract,
        )
        self.patcher.start()

    def teardown_method(self) -> None:
        """Tear down test fixtures."""
        self.patcher.stop()

    def test_get_service_staking_state(self) -> None:
        """Test retrieving service staking state."""
        self.mock_contract.functions.getServiceStakingState.return_value.call.return_value = 1
        result = ServiceStakingTokenContract.get_service_staking_state(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            service_id=42,
        )
        assert result == {"data": 1}
        self.mock_contract.functions.getServiceStakingState.assert_called_once_with(42)

    def test_build_stake_tx(self) -> None:
        """Test building stake transaction."""
        self.mock_contract.encode_abi.return_value = "0xaabbccdd"
        result = ServiceStakingTokenContract.build_stake_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            service_id=42,
        )
        assert result == {"data": bytes.fromhex("aabbccdd")}
        self.mock_contract.encode_abi.assert_called_once_with("stake", args=[42])

    def test_build_checkpoint_tx(self) -> None:
        """Test building checkpoint transaction."""
        self.mock_contract.encode_abi.return_value = "0x1122"
        result = ServiceStakingTokenContract.build_checkpoint_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": bytes.fromhex("1122")}
        self.mock_contract.encode_abi.assert_called_once_with("checkpoint")

    def test_build_unstake_tx(self) -> None:
        """Test building unstake transaction."""
        self.mock_contract.encode_abi.return_value = "0x3344"
        result = ServiceStakingTokenContract.build_unstake_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            service_id=42,
        )
        assert result == {"data": bytes.fromhex("3344")}
        self.mock_contract.encode_abi.assert_called_once_with("unstake", args=[42])

    def test_available_rewards(self) -> None:
        """Test retrieving available rewards."""
        self.mock_contract.functions.availableRewards.return_value.call.return_value = (
            1000
        )
        result = ServiceStakingTokenContract.available_rewards(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 1000}

    def test_get_staking_rewards(self) -> None:
        """Test retrieving staking rewards for a service."""
        self.mock_contract.functions.calculateServiceStakingReward.return_value.call.return_value = 500
        result = ServiceStakingTokenContract.get_staking_rewards(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            service_id=42,
        )
        assert result == {"data": 500}

    def test_get_next_checkpoint_ts(self) -> None:
        """Test retrieving next checkpoint timestamp."""
        self.mock_contract.functions.getNextRewardCheckpointTimestamp.return_value.call.return_value = 1700000000
        result = ServiceStakingTokenContract.get_next_checkpoint_ts(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 1700000000}

    def test_ts_checkpoint(self) -> None:
        """Test retrieving checkpoint timestamp."""
        self.mock_contract.functions.tsCheckpoint.return_value.call.return_value = (
            1699999000
        )
        result = ServiceStakingTokenContract.ts_checkpoint(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 1699999000}

    def test_liveness_ratio(self) -> None:
        """Test retrieving liveness ratio."""
        self.mock_contract.functions.livenessRatio.return_value.call.return_value = 10
        result = ServiceStakingTokenContract.liveness_ratio(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 10}

    def test_get_liveness_period(self) -> None:
        """Test retrieving liveness period."""
        self.mock_contract.functions.livenessPeriod.return_value.call.return_value = (
            86400
        )
        result = ServiceStakingTokenContract.get_liveness_period(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 86400}

    def test_get_service_info(self) -> None:
        """Test retrieving service info."""
        info = [42, "0xabc", [1, 2]]
        self.mock_contract.functions.getServiceInfo.return_value.call.return_value = (
            info
        )
        result = ServiceStakingTokenContract.get_service_info(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            service_id=42,
        )
        assert result == {"data": info}

    def test_max_num_services(self) -> None:
        """Test retrieving max number of services."""
        self.mock_contract.functions.maxNumServices.return_value.call.return_value = 100
        result = ServiceStakingTokenContract.max_num_services(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 100}

    def test_get_service_ids(self) -> None:
        """Test retrieving service IDs."""
        self.mock_contract.functions.getServiceIds.return_value.call.return_value = [
            1,
            2,
            3,
        ]
        result = ServiceStakingTokenContract.get_service_ids(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": [1, 2, 3]}

    def test_get_min_staking_duration(self) -> None:
        """Test retrieving minimum staking duration."""
        self.mock_contract.functions.minStakingDuration.return_value.call.return_value = 3600
        result = ServiceStakingTokenContract.get_min_staking_duration(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": 3600}

    def test_get_agent_ids(self) -> None:
        """Test retrieving agent IDs."""
        self.mock_contract.functions.getAgentIds.return_value.call.return_value = [
            10,
            20,
        ]
        result = ServiceStakingTokenContract.get_agent_ids(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": [10, 20]}
