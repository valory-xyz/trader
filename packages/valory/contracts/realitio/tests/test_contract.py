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

"""Tests for the RealitioContract."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from web3.exceptions import ContractLogicError

from packages.valory.contracts.realitio.contract import (
    UNIT_SEPARATOR,
    RealitioContract,
    build_question,
    format_answers,
    get_entries,
)


CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"
QUESTION_ID = b"\x00" * 32


class TestFormatAnswers:
    """Tests for the format_answers helper."""

    def test_single_answer(self) -> None:
        """Format single answer with quotes."""
        assert format_answers(["Yes"]) == '"Yes"'

    def test_multiple_answers(self) -> None:
        """Format multiple answers comma-separated with quotes."""
        assert format_answers(["Yes", "No"]) == '"Yes","No"'

    def test_empty_list(self) -> None:
        """Empty list returns empty string."""
        assert format_answers([]) == ""


class TestBuildQuestion:
    """Tests for the build_question helper."""

    def test_builds_question_string(self) -> None:
        """Build question from data dict with unit separator."""
        question_data = {
            "question": "Will it rain?",
            "answers": ["Yes", "No"],
            "topic": "weather",
            "language": "en",
        }
        result = build_question(question_data)
        parts = result.split(UNIT_SEPARATOR)
        assert len(parts) == 4
        assert parts[0] == "Will it rain?"
        assert parts[1] == '"Yes","No"'
        assert parts[2] == "weather"
        assert parts[3] == "en"


class TestGetEntries:
    """Tests for the get_entries helper."""

    def test_get_entries_processes_logs(self) -> None:
        """get_entries filters logs and decodes event data."""
        mock_eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.address = CONTRACT_ADDRESS
        mock_event_abi = {"name": "TestEvent", "type": "event", "inputs": []}
        mock_log = MagicMock()
        mock_eth.get_logs.return_value = [mock_log]

        with patch(
            "packages.valory.contracts.realitio.contract.event_abi_to_log_topic",
            return_value=b"\x01" * 32,
        ), patch(
            "packages.valory.contracts.realitio.contract.get_event_data",
            return_value={"decoded": True},
        ) as mock_get_event_data:
            result = get_entries(
                mock_eth, mock_contract, mock_event_abi, [b"\x02" * 32]
            )

        assert result == [{"decoded": True}]
        mock_get_event_data.assert_called_once()


class TestRealitioContract:
    """Tests for RealitioContract."""

    def setup_method(self) -> None:
        """Set up common test fixtures."""
        self.mock_ledger_api = MagicMock()
        self.mock_contract = MagicMock()
        self.patcher = patch.object(
            RealitioContract,
            "get_instance",
            return_value=self.mock_contract,
        )
        self.patcher.start()

    def teardown_method(self) -> None:
        """Tear down test fixtures."""
        self.patcher.stop()

    def test_execute_with_timeout_success(self) -> None:
        """Successful function execution returns data and no error."""
        data, err = RealitioContract.execute_with_timeout(lambda: 42, timeout=5.0)
        assert data == 42
        assert err is None

    def test_execute_with_timeout_returns_string_as_error(self) -> None:
        """When the executed function returns a string, it is treated as error."""
        data, err = RealitioContract.execute_with_timeout(
            lambda: "some error", timeout=5.0
        )
        assert data is None
        assert err == "some error"

    def test_execute_with_timeout_timeout(self) -> None:
        """When function times out, returns None and error message."""
        import time

        def slow_func() -> int:
            time.sleep(10)
            return 1

        data, err = RealitioContract.execute_with_timeout(slow_func, timeout=0.01)
        assert data is None
        assert "didn't respond" in err

    def test_check_finalized(self) -> None:
        """Test checking if a market is finalized."""
        self.mock_contract.functions.isFinalized.return_value.call.return_value = True
        result = RealitioContract.check_finalized(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
        )
        assert result == {"finalized": True}

    def test_get_best_answer(self) -> None:
        """Test reading the best answer for a question."""
        answer_bytes = b"\x01" + b"\x00" * 31
        self.mock_contract.functions.getBestAnswer.return_value.call.return_value = (
            answer_bytes
        )
        result = RealitioContract.get_best_answer(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
        )
        assert result == {"best_answer": "0x" + answer_bytes.hex()}

    def test_get_bond(self) -> None:
        """Test reading the bond for a question."""
        self.mock_contract.functions.getBond.return_value.call.return_value = 123
        result = RealitioContract.get_bond(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
        )
        assert result == {"bond": 123}

    def test_get_claim_params_success(self) -> None:
        """Test successful claim params retrieval."""
        mock_event = MagicMock()
        self.mock_contract.events.LogNewAnswer.return_value.abi = {
            "name": "LogNewAnswer"
        }

        with patch(
            "packages.valory.contracts.realitio.contract.get_entries",
            return_value=[mock_event, mock_event],
        ):
            result = RealitioContract.get_claim_params(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                from_block=0,
                to_block=100,
                question_id=QUESTION_ID,
                timeout=5.0,
            )

        assert "answered" in result
        assert "info" in result
        assert len(result["answered"]) == 2

    def test_get_claim_params_timeout(self) -> None:
        """Test claim params returns error on timeout."""
        self.mock_contract.events.LogNewAnswer.return_value.abi = {
            "name": "LogNewAnswer"
        }

        import time

        def slow_get_entries(*args, **kwargs):  # type: ignore
            time.sleep(10)
            return []

        with patch(
            "packages.valory.contracts.realitio.contract.get_entries",
            side_effect=slow_get_entries,
        ):
            result = RealitioContract.get_claim_params(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                from_block=0,
                to_block=100,
                question_id=QUESTION_ID,
                timeout=0.01,
            )

        assert "error" in result

    def test_get_claim_params_rpc_timeout(self) -> None:
        """Test claim params handles RPC read timeout."""
        from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

        self.mock_contract.events.LogNewAnswer.return_value.abi = {
            "name": "LogNewAnswer"
        }

        with patch(
            "packages.valory.contracts.realitio.contract.get_entries",
            side_effect=Urllib3ReadTimeoutError(None, None, "timeout"),
        ):
            result = RealitioContract.get_claim_params(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                from_block=0,
                to_block=100,
                question_id=QUESTION_ID,
                timeout=5.0,
            )

        assert "error" in result
        assert "RPC timed out" in result["error"]

    def test_build_claim_winnings(self) -> None:
        """Test building claim winnings transaction."""
        self.mock_contract.encode_abi.return_value = b"\xaa\xbb"
        claim_params = ([b"\x01"], ["0xabc"], [1], [b"\x02"])
        result = RealitioContract.build_claim_winnings(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
            claim_params=claim_params,
        )
        assert result == {"data": b"\xaa\xbb"}

    def test_simulate_claim_winnings_success(self) -> None:
        """Test successful simulation of claim winnings."""
        self.mock_contract.encode_abi.return_value = "0xaabb"
        self.mock_ledger_api.api.eth.call.return_value = b""
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        claim_params = ([b"\x01"], ["0xabc"], [1], [b"\x02"])
        result = RealitioContract.simulate_claim_winnings(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
            claim_params=claim_params,
            sender_address="0xsender",
        )
        assert result == {"data": True}

    def test_simulate_claim_winnings_failure_value_error(self) -> None:
        """Test failed simulation returns False on ValueError."""
        self.mock_contract.encode_abi.return_value = "0xaabb"
        self.mock_ledger_api.api.eth.call.side_effect = ValueError("revert")
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        claim_params = ([b"\x01"], ["0xabc"], [1], [b"\x02"])
        result = RealitioContract.simulate_claim_winnings(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
            claim_params=claim_params,
            sender_address="0xsender",
        )
        assert result == {"data": False}

    def test_simulate_claim_winnings_failure_contract_logic(self) -> None:
        """Test failed simulation returns False on ContractLogicError."""
        self.mock_contract.encode_abi.return_value = "0xaabb"
        self.mock_ledger_api.api.eth.call.side_effect = ContractLogicError("revert")
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        claim_params = ([b"\x01"], ["0xabc"], [1], [b"\x02"])
        result = RealitioContract.simulate_claim_winnings(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
            claim_params=claim_params,
            sender_address="0xsender",
        )
        assert result == {"data": False}

    def test_get_history_hash(self) -> None:
        """Test getting history hash for a question."""
        self.mock_contract.functions.getHistoryHash.return_value.call.return_value = (
            b"\xcc" * 32
        )
        result = RealitioContract.get_history_hash(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
        )
        assert result == {"data": b"\xcc" * 32}

    def test_get_ask_question_tx(self) -> None:
        """Test getting ask question transaction."""
        question_data = {
            "question": "Will it rain?",
            "answers": ["Yes", "No"],
            "topic": "weather",
            "language": "en",
        }
        self.mock_ledger_api.api.to_checksum_address.return_value = "0xarbitrator"
        self.mock_ledger_api.build_transaction.return_value = {"tx": "data"}

        result = RealitioContract.get_ask_question_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_data=question_data,
            opening_timestamp=1700000000,
            timeout=86400,
            arbitrator_contract="0xarbitrator",
        )
        assert result == {"tx": "data"}
        self.mock_ledger_api.build_transaction.assert_called_once()

    def test_get_ask_question_tx_data(self) -> None:
        """Test getting ask question tx data (encoded ABI)."""
        question_data = {
            "question": "Will it rain?",
            "answers": ["Yes", "No"],
            "topic": "weather",
            "language": "en",
        }
        self.mock_ledger_api.api.to_checksum_address.return_value = "0xarbitrator"
        self.mock_contract.encode_abi.return_value = "0xaabb"

        result = RealitioContract.get_ask_question_tx_data(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_data=question_data,
            opening_timestamp=1700000000,
            timeout=86400,
            arbitrator_contract="0xarbitrator",
        )
        assert result == {"data": bytes.fromhex("aabb")}

    def test_calculate_question_id_with_0x_prefix(self) -> None:
        """Test calculating question ID when hex starts with 0x."""
        question_data = {
            "question": "Will it rain?",
            "answers": ["Yes", "No"],
            "topic": "weather",
            "language": "en",
        }
        mock_hash = MagicMock()
        mock_hash.hex.return_value = "0xabcdef1234567890"
        self.mock_ledger_api.api.solidity_keccak.side_effect = [
            b"\x01" * 32,
            mock_hash,
        ]
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = RealitioContract.calculate_question_id(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_data=question_data,
            opening_timestamp=1700000000,
            timeout=86400,
            arbitrator_contract="0xarbitrator",
            sender="0xsender",
        )
        assert result["question_id"] == "0xabcdef1234567890"

    def test_calculate_question_id_without_0x_prefix(self) -> None:
        """Test calculating question ID when hex does not start with 0x."""
        question_data = {
            "question": "Will it rain?",
            "answers": ["Yes", "No"],
            "topic": "weather",
            "language": "en",
        }
        mock_hash = MagicMock()
        mock_hash.hex.return_value = "abcdef1234567890"
        self.mock_ledger_api.api.solidity_keccak.side_effect = [
            b"\x01" * 32,
            mock_hash,
        ]
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = RealitioContract.calculate_question_id(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_data=question_data,
            opening_timestamp=1700000000,
            timeout=86400,
            arbitrator_contract="0xarbitrator",
            sender="0xsender",
        )
        assert result["question_id"] == "0xabcdef1234567890"

    def test_get_question_events(self) -> None:
        """Test getting question events with proper formatting."""
        mock_entry = {
            "transactionHash": MagicMock(hex=lambda: "0xabc123"),
            "blockNumber": 100,
            "args": {
                "question_id": b"\x01" * 32,
                "user": "0xuser",
                "template_id": 2,
                "question": "test?",
                "content_hash": b"\x02" * 32,
                "arbitrator": "0xarb",
                "timeout": 86400,
                "opening_ts": 1700000000,
                "nonce": 0,
                "created": 1699999000,
            },
        }
        self.mock_contract.events.LogNewQuestion.return_value.abi = {
            "name": "LogNewQuestion"
        }

        with patch(
            "packages.valory.contracts.realitio.contract.get_entries",
            return_value=[mock_entry],
        ):
            result = RealitioContract.get_question_events(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                question_ids=[QUESTION_ID],
            )

        assert len(result["data"]) == 1
        assert result["data"][0]["tx_hash"] == "0xabc123"
        assert result["data"][0]["block_number"] == 100

    def test_get_question_events_without_0x_prefix(self) -> None:
        """Test question events formatting when tx hash lacks 0x prefix."""
        mock_entry = {
            "transactionHash": MagicMock(hex=lambda: "abc123"),
            "blockNumber": 100,
            "args": {
                "question_id": b"\x01" * 32,
                "user": "0xuser",
                "template_id": 2,
                "question": "test?",
                "content_hash": b"\x02" * 32,
                "arbitrator": "0xarb",
                "timeout": 86400,
                "opening_ts": 1700000000,
                "nonce": 0,
                "created": 1699999000,
            },
        }
        self.mock_contract.events.LogNewQuestion.return_value.abi = {
            "name": "LogNewQuestion"
        }

        with patch(
            "packages.valory.contracts.realitio.contract.get_entries",
            return_value=[mock_entry],
        ):
            result = RealitioContract.get_question_events(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                question_ids=[QUESTION_ID],
            )

        assert result["data"][0]["tx_hash"] == "0xabc123"

    def test_get_submit_answer_tx(self) -> None:
        """Test getting submit answer transaction data."""
        self.mock_contract.encode_abi.return_value = b"\xee\xff"
        result = RealitioContract.get_submit_answer_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id=QUESTION_ID,
            answer=b"\x01" * 32,
            max_previous=0,
        )
        assert result == {"data": b"\xee\xff"}

    def test_balance_of(self) -> None:
        """Test getting balance for an address."""
        self.mock_contract.functions.balanceOf.return_value.call.return_value = 1000
        result = RealitioContract.balance_of(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            address="0xowner",
        )
        assert result == {"data": 1000}

    def test_build_withdraw_tx(self) -> None:
        """Test building withdraw transaction."""
        self.mock_contract.encode_abi.return_value = b"\x11\x22"
        result = RealitioContract.build_withdraw_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
        )
        assert result == {"data": b"\x11\x22"}


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
        assert not missing, (
            f"Functions used in contract.py but missing from ABI: {missing}"
        )

    def test_events_present_in_abi(self) -> None:
        """All contract events referenced in contract.py must exist in the ABI."""
        _, abi_events = self._get_abi_names()
        _, referenced_events = self._get_contract_references()
        missing = referenced_events - abi_events
        assert not missing, (
            f"Events used in contract.py but missing from ABI: {missing}"
        )
