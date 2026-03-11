# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""Tests for the RealitioProxyContract."""

from unittest.mock import MagicMock, patch

from packages.valory.contracts.realitio_proxy.contract import RealitioProxyContract


CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"


class TestRealitioProxyContract:
    """Tests for RealitioProxyContract."""

    def test_build_resolve_tx(self) -> None:
        """Test building resolve transaction with all parameters."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_contract_instance.encode_abi.return_value = b"\x01\x02\x03"

        question_id = b"\x00" * 32
        template_id = 2
        question = "Will it rain tomorrow?"
        num_outcomes = 2

        with patch.object(
            RealitioProxyContract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = RealitioProxyContract.build_resolve_tx(
                ledger_api=mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                question_id=question_id,
                template_id=template_id,
                question=question,
                num_outcomes=num_outcomes,
            )

        assert result == {"data": b"\x01\x02\x03"}
        mock_contract_instance.encode_abi.assert_called_once_with(
            abi_element_identifier="resolve",
            args=[question_id, template_id, question, num_outcomes],
        )
