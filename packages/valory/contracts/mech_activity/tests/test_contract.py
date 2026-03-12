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

"""Tests for the MechActivityContract."""

from unittest.mock import MagicMock, patch

from packages.valory.contracts.mech_activity.contract import MechActivityContract


class TestMechActivityContract:
    """Tests for MechActivityContract."""

    def test_liveness_ratio(self) -> None:
        """Test liveness_ratio returns the on-chain liveness ratio."""
        mock_ledger_api = MagicMock()
        mock_contract_instance = MagicMock()
        mock_contract_instance.functions.livenessRatio.return_value.call.return_value = (
            42
        )

        with patch.object(
            MechActivityContract,
            "get_instance",
            return_value=mock_contract_instance,
        ):
            result = MechActivityContract.liveness_ratio(
                ledger_api=mock_ledger_api,
                contract_address="0x1234567890abcdef1234567890abcdef12345678",
            )

        assert result == {"data": 42}
        mock_contract_instance.functions.livenessRatio.assert_called_once()
