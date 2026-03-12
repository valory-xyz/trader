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

"""Tests for the FixedProductMarketMakerContract."""

from unittest.mock import MagicMock, patch

from packages.valory.contracts.market_maker.contract import (
    Contract,
    FixedProductMarketMakerContract,
)


CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


class TestContractBase:
    """Tests for the Contract base class methods."""

    def test_method_call(self) -> None:
        """Test _method_call delegates to ledger_api.contract_method_call."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_ledger_api.contract_method_call.return_value = 42

        with patch.object(
            Contract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = Contract._method_call(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                method_name="testMethod",
                arg1="value1",
            )

        assert result == 42
        mock_ledger_api.contract_method_call.assert_called_once_with(
            mock_contract_instance,
            "testMethod",
            arg1="value1",
        )

    def test_encode_abi(self) -> None:
        """Test _encode_abi returns hex-decoded data from contract."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        # encode_abi returns hex string with 0x prefix
        mock_contract_instance.encode_abi.return_value = "0xaabbccdd"

        with patch.object(
            Contract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = Contract._encode_abi(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                method_name="testMethod",
                arg1="value1",
            )

        assert result == {"data": bytes.fromhex("aabbccdd")}
        mock_contract_instance.encode_abi.assert_called_once_with(
            "testMethod",
            kwargs={"arg1": "value1"},
        )


class TestFixedProductMarketMakerContract:
    """Tests for FixedProductMarketMakerContract."""

    def test_calc_buy_amount(self) -> None:
        """Test calc_buy_amount returns the calculated buy amount."""
        mock_ledger_api = MagicMock()
        mock_ledger_api.contract_method_call.return_value = 500

        with patch.object(
            FixedProductMarketMakerContract,
            "get_instance",
            return_value=MagicMock(),
        ):
            result = FixedProductMarketMakerContract.calc_buy_amount(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                investment_amount=1000,
                outcome_index=0,
            )

        assert result == {"amount": 500}

    def test_get_buy_data(self) -> None:
        """Test get_buy_data returns encoded buy tx data."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_contract_instance.encode_abi.return_value = "0xaabb"

        with patch.object(
            FixedProductMarketMakerContract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = FixedProductMarketMakerContract.get_buy_data(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                investment_amount=1000,
                outcome_index=0,
                min_outcome_tokens_to_buy=500,
            )

        assert result == {"data": bytes.fromhex("aabb")}

    def test_calc_sell_amount(self) -> None:
        """Test calc_sell_amount returns the calculated sell amount."""
        mock_ledger_api = MagicMock()
        mock_ledger_api.contract_method_call.return_value = 300

        with patch.object(
            FixedProductMarketMakerContract,
            "get_instance",
            return_value=MagicMock(),
        ):
            result = FixedProductMarketMakerContract.calc_sell_amount(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                return_amount=500,
                outcome_index=1,
            )

        assert result == {"amount": 300}

    def test_get_sell_data(self) -> None:
        """Test get_sell_data returns encoded sell tx data."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_contract_instance.encode_abi.return_value = "0xccdd"

        with patch.object(
            FixedProductMarketMakerContract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = FixedProductMarketMakerContract.get_sell_data(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                return_amount=500,
                outcome_index=1,
                max_outcome_tokens_to_sell=300,
            )

        assert result == {"data": bytes.fromhex("ccdd")}
