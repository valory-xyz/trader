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

"""Tests for the RelayerContract."""

from unittest.mock import MagicMock, patch

from packages.valory.contracts.relayer.contract import RelayerContract


CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


class TestRelayerContract:
    """Tests for RelayerContract."""

    def test_build_operator_deposit_tx(self) -> None:
        """Test building operator deposit transaction."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_contract_instance.encode_abi.return_value = b"\x01\x02"

        with patch.object(
            RelayerContract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = RelayerContract.build_operator_deposit_tx(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                amount=1000,
            )

        assert result == {"data": b"\x01\x02"}
        mock_contract_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="operatorDeposit",
            args=[1000],
        )

    def test_build_exec_tx(self) -> None:
        """Test building exec transaction."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_contract_instance.encode_abi.return_value = b"\x03\x04"
        target = "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
        calldata = b"\xaa\xbb"

        with patch.object(
            RelayerContract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = RelayerContract.build_exec_tx(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                to=target,
                data=calldata,
            )

        assert result == {"data": b"\x03\x04"}
        mock_contract_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="exec",
            args=[target, calldata],
        )
