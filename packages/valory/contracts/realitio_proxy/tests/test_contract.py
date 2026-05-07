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

"""Tests for the RealitioProxyContract."""

import json
import re
from pathlib import Path
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


PACKAGE_DIR = Path(__file__).parent.parent


class TestABIConsistency:
    """Test that functions and events used in contract.py exist in the ABI."""

    @staticmethod
    def _get_abi_names() -> tuple:
        """Extract function and event names from ABI files."""
        functions: set = set()
        events: set = set()
        for abi_file in PACKAGE_DIR.glob("build/*.json"):
            with open(abi_file) as f:
                data = json.load(f)
            abi = data.get("abi", data)
            for entry in abi:
                if entry.get("type") == "function":
                    functions.add(entry["name"])
                elif entry.get("type") == "event":
                    events.add(entry["name"])
        return functions, events

    @staticmethod
    def _get_contract_references() -> tuple:
        """Extract function and event names referenced in contract.py."""
        source = (PACKAGE_DIR / "contract.py").read_text()
        function_patterns = [
            r"\.functions\.(\w+)",
            r"encode[_.]?[aA][bB][iI]\(\s*(?:abi_element_identifier\s*=\s*)?[\"'](\w+)[\"']",
            r"method_name\s*=\s*[\"'](\w+)[\"']",
        ]
        referenced_functions: set = set()
        for pattern in function_patterns:
            referenced_functions.update(re.findall(pattern, source))
        event_pattern = r"\.events\.(\w+)"
        referenced_events: set = set(re.findall(event_pattern, source))
        return referenced_functions, referenced_events

    def test_functions_present_in_abi(self) -> None:
        """All contract functions referenced in contract.py must exist in the ABI."""
        abi_functions, _ = self._get_abi_names()
        referenced_functions, _ = self._get_contract_references()
        missing = referenced_functions - abi_functions
        assert (
            not missing
        ), f"Functions used in contract.py but missing from ABI: {missing}"

    def test_events_present_in_abi(self) -> None:
        """All contract events referenced in contract.py must exist in the ABI."""
        _, abi_events = self._get_abi_names()
        _, referenced_events = self._get_contract_references()
        missing = referenced_events - abi_events
        assert (
            not missing
        ), f"Events used in contract.py but missing from ABI: {missing}"
