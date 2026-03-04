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

"""Tests for check_stop_trading_abci models."""

from unittest.mock import MagicMock, patch

import pytest
from aea.exceptions import AEAEnforceError

from packages.valory.skills.check_stop_trading_abci.models import (
    BenchmarkTool,
    CheckStopTradingParams,
    Requests,
    SharedState,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
)
from packages.valory.skills.staking_abci.models import StakingParams


class TestCheckStopTradingParamsValidation:
    """Tests for CheckStopTradingParams._validate_required_params."""

    def test_missing_mech_contract_address_raises(self) -> None:
        """Missing mech_contract_address raises AEAEnforceError."""
        kwargs = {"use_mech_marketplace": False}
        with pytest.raises(AEAEnforceError, match="mech_contract_address"):
            CheckStopTradingParams._validate_required_params(None, kwargs)  # type: ignore

    def test_missing_use_mech_marketplace_raises(self) -> None:
        """Missing use_mech_marketplace raises AEAEnforceError."""
        kwargs = {"mech_contract_address": "0xabc"}
        with pytest.raises(AEAEnforceError, match="use_mech_marketplace"):
            CheckStopTradingParams._validate_required_params(None, kwargs)  # type: ignore

    def test_valid_params_pass(self) -> None:
        """Valid params pass validation without error."""
        kwargs = {"mech_contract_address": "0xabc", "use_mech_marketplace": False}
        # Should not raise
        CheckStopTradingParams._validate_required_params(None, kwargs)  # type: ignore


class TestCheckStopTradingParamsConfigureMarketplace:
    """Tests for CheckStopTradingParams._configure_marketplace."""

    def test_none_marketplace_config_raises(self) -> None:
        """None marketplace_config raises AEAEnforceError."""
        kwargs = {"mech_marketplace_config": None}
        instance = object.__new__(CheckStopTradingParams)
        with pytest.raises(AEAEnforceError, match="Market place config cannot be empty"):
            instance._configure_marketplace(kwargs)

    def test_valid_marketplace_config(self) -> None:
        """Valid marketplace config sets mech_marketplace_config and kpi address."""
        marketplace_config = {
            "mech_marketplace_address": "0xMarketplace",
            "response_timeout": 300,
        }
        kwargs = {"mech_marketplace_config": marketplace_config}
        instance = object.__new__(CheckStopTradingParams)
        instance._configure_marketplace(kwargs)

        assert (
            instance.staking_kpi_mech_count_request_address == "0xMarketplace"
        )
        assert instance.mech_marketplace_config is not None


class TestCheckStopTradingParamsInit:
    """Tests for CheckStopTradingParams.__init__."""

    def test_init_without_marketplace(self) -> None:
        """Test init with use_mech_marketplace=False."""
        mock_skill_context = MagicMock()
        with patch.object(StakingParams, "__init__", return_value=None):
            params = CheckStopTradingParams(
                skill_context=mock_skill_context,
                mech_contract_address="0xabc",
                disable_trading=False,
                stop_trading_if_staking_kpi_met=True,
                use_mech_marketplace=False,
                enable_position_review=True,
                review_period_seconds=3600,
            )
        assert params.mech_contract_address == "0xabc"
        assert params.disable_trading is False
        assert params.stop_trading_if_staking_kpi_met is True
        assert params.use_mech_marketplace is False
        assert params.enable_position_review is True
        assert params.review_period_seconds == 3600
        assert params.staking_kpi_mech_count_request_address == "0xabc"

    def test_init_with_marketplace(self) -> None:
        """Test init with use_mech_marketplace=True."""
        mock_skill_context = MagicMock()
        with patch.object(StakingParams, "__init__", return_value=None):
            params = CheckStopTradingParams(
                skill_context=mock_skill_context,
                mech_contract_address="0xabc",
                disable_trading=False,
                stop_trading_if_staking_kpi_met=True,
                use_mech_marketplace=True,
                enable_position_review=True,
                review_period_seconds=3600,
                mech_marketplace_config={
                    "mech_marketplace_address": "0xMarketplace",
                    "response_timeout": 300,
                },
            )
        assert params.mech_contract_address == "0xabc"
        assert params.use_mech_marketplace is True
        assert params.staking_kpi_mech_count_request_address == "0xMarketplace"


class TestModelAliases:
    """Tests for model aliases Requests and BenchmarkTool."""

    def test_requests_alias(self) -> None:
        """Requests is an alias for BaseRequests."""
        from packages.valory.skills.abstract_round_abci.models import (
            Requests as BaseRequests,
        )

        assert Requests is BaseRequests

    def test_benchmark_tool_alias(self) -> None:
        """BenchmarkTool is an alias for BaseBenchmarkTool."""
        from packages.valory.skills.abstract_round_abci.models import (
            BenchmarkTool as BaseBenchmarkTool,
        )

        assert BenchmarkTool is BaseBenchmarkTool


class TestSharedState:
    """Tests for SharedState model."""

    def test_abci_app_cls(self) -> None:
        """SharedState points to CheckStopTradingAbciApp."""
        assert SharedState.abci_app_cls is CheckStopTradingAbciApp
