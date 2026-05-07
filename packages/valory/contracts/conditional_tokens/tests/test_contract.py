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

"""Tests for the ConditionalTokensContract."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from hexbytes import HexBytes

from packages.valory.contracts.conditional_tokens.contract import (
    ConditionalTokensContract,
    TOPIC_BYTEORDER,
    TOPIC_BYTES,
    get_logs,
    pad_int_for_topic,
    update_from_event,
)

CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"
CONDITION_ID = HexBytes(b"\xaa" * 32)


class TestPadIntForTopic:
    """Tests for pad_int_for_topic helper."""

    def test_pads_to_32_bytes(self) -> None:
        """Integer is padded to 32 bytes big-endian."""
        result = pad_int_for_topic(1)
        assert len(result) == TOPIC_BYTES
        assert result[-1] == 1
        assert result[0] == 0

    def test_zero(self) -> None:
        """Zero pads to 32 zero bytes."""
        result = pad_int_for_topic(0)
        assert result == HexBytes(b"\x00" * TOPIC_BYTES)

    def test_large_value(self) -> None:
        """Large value is correctly encoded."""
        result = pad_int_for_topic(256)
        assert int.from_bytes(result, TOPIC_BYTEORDER) == 256


class TestUpdateFromEvent:
    """Tests for update_from_event helper."""

    def test_updates_payouts_with_condition_id(self) -> None:
        """Event with valid condition_id and payout updates the payouts dict."""
        event = {"args": {"conditionId": b"\xaa" * 32, "payout": 1000}}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert (b"\xaa" * 32).hex() in payouts
        assert payouts[(b"\xaa" * 32).hex()] == 1000

    def test_skips_zero_payout(self) -> None:
        """Event with payout=0 does not update payouts."""
        event = {"args": {"conditionId": b"\xaa" * 32, "payout": 0}}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert len(payouts) == 0

    def test_skips_missing_condition_id(self) -> None:
        """Event without conditionId does not update payouts."""
        event = {"args": {"payout": 1000}}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert len(payouts) == 0

    def test_handles_bytes_payout(self) -> None:
        """Event with bytes payout converts to int."""
        payout_bytes = (500).to_bytes(TOPIC_BYTES, TOPIC_BYTEORDER)
        event = {"args": {"conditionId": b"\xbb" * 32, "payout": payout_bytes}}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert payouts[(b"\xbb" * 32).hex()] == 500

    def test_handles_string_condition_id(self) -> None:
        """Event with string conditionId (already hex) works."""
        event = {"args": {"conditionId": "aabb", "payout": 100}}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert payouts["aabb"] == 100

    def test_empty_args(self) -> None:
        """Event with empty args dict does not update payouts."""
        event = {"args": {}}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert len(payouts) == 0

    def test_no_args_key(self) -> None:
        """Event without args key does not update payouts."""
        event: dict = {}
        payouts: dict = {}
        update_from_event(event, payouts)
        assert len(payouts) == 0


class TestGetLogs:
    """Tests for get_logs helper."""

    def test_get_logs_returns_raw_logs(self) -> None:
        """get_logs returns raw log receipts from eth.get_logs."""
        mock_eth = MagicMock()
        mock_contract = MagicMock()
        mock_contract.address = CONTRACT_ADDRESS
        mock_event_abi = {"name": "TestEvent", "type": "event", "inputs": []}
        mock_log = MagicMock()
        mock_eth.get_logs.return_value = [mock_log]

        with patch(
            "packages.valory.contracts.conditional_tokens.contract.event_abi_to_log_topic",
            return_value=b"\x01" * 32,
        ):
            result = get_logs(mock_eth, mock_contract, mock_event_abi, [b"\x02" * 32])

        assert result == [mock_log]


class TestConditionalTokensContract:
    """Tests for ConditionalTokensContract."""

    def setup_method(self) -> None:
        """Set up common test fixtures."""
        self.mock_ledger_api = MagicMock()
        self.mock_contract = MagicMock()
        self.patcher = patch.object(
            ConditionalTokensContract,
            "get_instance",
            return_value=self.mock_contract,
        )
        self.patcher.start()

    def teardown_method(self) -> None:
        """Tear down test fixtures."""
        self.patcher.stop()

    def test_execute_with_timeout_success(self) -> None:
        """Successful function execution returns data and no error."""
        data, err = ConditionalTokensContract.execute_with_timeout(
            lambda: [1, 2, 3], timeout=5.0
        )
        assert data == [1, 2, 3]
        assert err is None

    def test_execute_with_timeout_string_error(self) -> None:
        """String return is treated as error."""
        data, err = ConditionalTokensContract.execute_with_timeout(
            lambda: "error message", timeout=5.0
        )
        assert data is None
        assert err == "error message"

    def test_execute_with_timeout_timeout(self) -> None:
        """Timeout returns None and error message."""
        import time

        def slow_func() -> int:
            time.sleep(10)
            return 1

        data, err = ConditionalTokensContract.execute_with_timeout(
            slow_func, timeout=0.01
        )
        assert data is None
        assert "didn't respond" in err

    def test_check_redeemed_success(self) -> None:
        """Test successful check_redeemed with matching events."""
        self.mock_contract.events.PayoutRedemption.return_value.abi = {
            "name": "PayoutRedemption"
        }
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        mock_event = {
            "args": {
                "conditionId": CONDITION_ID,
                "indexSets": [pad_int_for_topic(1)],
                "payout": 1000,
            }
        }

        with (
            patch(
                "packages.valory.contracts.conditional_tokens.contract.get_logs",
                return_value=[MagicMock()],
            ),
            patch(
                "packages.valory.contracts.conditional_tokens.contract.get_event_data",
                return_value=mock_event,
            ),
        ):
            result = ConditionalTokensContract.check_redeemed(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                redeemer="0xredeemer",
                from_block=0,
                to_block=100,
                collateral_tokens=["0xtoken"],
                parent_collection_ids=[b"\x00" * 32],
                condition_ids=[CONDITION_ID],
                index_sets=[[1]],
                timeout=5.0,
            )

        assert "payouts" in result

    def test_check_redeemed_timeout(self) -> None:
        """Test check_redeemed handles timeout."""
        self.mock_contract.events.PayoutRedemption.return_value.abi = {
            "name": "PayoutRedemption"
        }
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        import time

        def slow_get_logs(*args, **kwargs):  # type: ignore
            time.sleep(10)
            return []

        with patch(
            "packages.valory.contracts.conditional_tokens.contract.get_logs",
            side_effect=slow_get_logs,
        ):
            result = ConditionalTokensContract.check_redeemed(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                redeemer="0xredeemer",
                from_block=0,
                to_block=100,
                collateral_tokens=["0xtoken"],
                parent_collection_ids=[b"\x00" * 32],
                condition_ids=[CONDITION_ID],
                index_sets=[[1]],
                timeout=0.01,
            )

        assert "error" in result

    def test_check_redeemed_rpc_timeout(self) -> None:
        """Test check_redeemed handles RPC read timeout."""
        from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

        self.mock_contract.events.PayoutRedemption.return_value.abi = {
            "name": "PayoutRedemption"
        }
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        with patch(
            "packages.valory.contracts.conditional_tokens.contract.get_logs",
            side_effect=Urllib3ReadTimeoutError(None, None, "timeout"),
        ):
            result = ConditionalTokensContract.check_redeemed(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                redeemer="0xredeemer",
                from_block=0,
                to_block=100,
                collateral_tokens=["0xtoken"],
                parent_collection_ids=[b"\x00" * 32],
                condition_ids=[CONDITION_ID],
                index_sets=[[1]],
                timeout=5.0,
            )

        assert "error" in result
        assert "RPC timed out" in result["error"]

    def test_check_resolved_true(self) -> None:
        """Test check_resolved returns True when payout > 0."""
        self.mock_contract.functions.payoutDenominator.return_value.call.return_value = (
            100
        )
        result = ConditionalTokensContract.check_resolved(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            condition_id=CONDITION_ID,
        )
        assert result == {"resolved": True}

    def test_check_resolved_false(self) -> None:
        """Test check_resolved returns False when payout == 0."""
        self.mock_contract.functions.payoutDenominator.return_value.call.return_value = (
            0
        )
        result = ConditionalTokensContract.check_resolved(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            condition_id=CONDITION_ID,
        )
        assert result == {"resolved": False}

    def test_build_redeem_positions_tx(self) -> None:
        """Test building redeem positions transaction."""
        self.mock_contract.encode_abi.return_value = b"\xaa\xbb"
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = ConditionalTokensContract.build_redeem_positions_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            collateral_token="0xtoken",
            parent_collection_id=b"\x00" * 32,
            condition_id=CONDITION_ID,
            index_sets=[1, 2],
        )
        assert result == {"data": b"\xaa\xbb"}

    def test_get_prepare_condition_tx(self) -> None:
        """Test getting prepare condition transaction."""
        self.mock_ledger_api.api.to_checksum_address.return_value = "0xoracle"
        self.mock_ledger_api.build_transaction.return_value = {"tx": "data"}

        result = ConditionalTokensContract.get_prepare_condition_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id="0x" + "aa" * 32,
            oracle_contract="0xoracle",
        )
        assert result == {"tx": "data"}

    def test_get_prepare_condition_tx_data(self) -> None:
        """Test getting prepare condition tx data (encoded ABI)."""
        self.mock_ledger_api.api.to_checksum_address.return_value = "0xoracle"
        self.mock_contract.encode_abi.return_value = "0xaabb"

        result = ConditionalTokensContract.get_prepare_condition_tx_data(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            question_id="0x" + "aa" * 32,
            oracle_contract="0xoracle",
        )
        assert result == {"data": bytes.fromhex("aabb")}

    def test_calculate_condition_id_with_0x(self) -> None:
        """Test condition ID calculation when hex starts with 0x."""
        mock_hash = MagicMock()
        mock_hash.hex.return_value = "0xabcdef"
        self.mock_ledger_api.api.solidity_keccak.return_value = mock_hash
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = ConditionalTokensContract.calculate_condition_id(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            oracle_contract="0xoracle",
            question_id="0x" + "aa" * 32,
            outcome_slot_count=2,
        )
        assert result["condition_id"] == "0xabcdef"

    def test_calculate_condition_id_without_0x(self) -> None:
        """Test condition ID calculation when hex lacks 0x prefix."""
        mock_hash = MagicMock()
        mock_hash.hex.return_value = "abcdef"
        self.mock_ledger_api.api.solidity_keccak.return_value = mock_hash
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = ConditionalTokensContract.calculate_condition_id(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            oracle_contract="0xoracle",
            question_id="0x" + "aa" * 32,
            outcome_slot_count=2,
        )
        assert result["condition_id"] == "0xabcdef"

    def test_get_condition_id(self) -> None:
        """Test getting condition ID from tx receipt."""
        mock_log = {"args": {"conditionId": MagicMock(hex=lambda: "abcdef")}}
        self.mock_contract.events.ConditionPreparation.return_value.process_receipt.return_value = [
            mock_log
        ]
        self.mock_ledger_api.api.eth.getTransactionReceipt.return_value = MagicMock()

        result = ConditionalTokensContract.get_condition_id(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            tx_digest="0xtxhash",
        )
        assert result == "0xabcdef"

    def test_get_condition_id_with_0x_prefix(self) -> None:
        """Test getting condition ID when hex already has 0x prefix."""
        mock_log = {"args": {"conditionId": MagicMock(hex=lambda: "0xabcdef")}}
        self.mock_contract.events.ConditionPreparation.return_value.process_receipt.return_value = [
            mock_log
        ]
        self.mock_ledger_api.api.eth.getTransactionReceipt.return_value = MagicMock()

        result = ConditionalTokensContract.get_condition_id(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            tx_digest="0xtxhash",
        )
        assert result == "0xabcdef"

    def test_get_condition_preparation_events(self) -> None:
        """Test getting condition preparation events."""
        self.mock_contract.events.ConditionPreparation.return_value.abi = {
            "name": "ConditionPreparation"
        }
        mock_log = MagicMock()
        mock_entry = {
            "transactionHash": MagicMock(),
            "blockNumber": 100,
            "args": {
                "conditionId": b"\xaa" * 32,
                "oracle": "0xoracle",
                "questionId": b"\xbb" * 32,
                "outcomeSlotCount": 2,
            },
        }
        mock_entry["transactionHash"].to_0x_hex.return_value = "0xabc"

        with (
            patch(
                "packages.valory.contracts.conditional_tokens.contract.get_logs",
                return_value=[mock_log],
            ),
            patch(
                "packages.valory.contracts.conditional_tokens.contract.get_event_data",
                return_value=mock_entry,
            ),
        ):
            result = ConditionalTokensContract.get_condition_preparation_events(
                ledger_api=self.mock_ledger_api,
                contract_address=CONTRACT_ADDRESS,
                condition_ids=[CONDITION_ID],
            )

        assert len(result["data"]) == 1
        assert result["data"][0]["tx_hash"] == "0xabc"

    def test_get_partitions(self) -> None:
        """Test calculating partitions for outcome slots."""
        assert ConditionalTokensContract.get_partitions(2) == [1, 2]
        assert ConditionalTokensContract.get_partitions(3) == [1, 2, 4]
        assert ConditionalTokensContract.get_partitions(1) == [1]

    def test_get_user_holdings(self) -> None:
        """Test getting user holdings for all outcome slots."""
        self.mock_contract.functions.getCollectionId.return_value.call.return_value = (
            b"\x01" * 32
        )
        self.mock_contract.functions.balanceOf.return_value.call.return_value = 100
        self.mock_ledger_api.api.solidity_keccak.return_value = b"\x02" * 32
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = ConditionalTokensContract.get_user_holdings(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            outcome_slot_count=2,
            condition_id="0x" + "aa" * 32,
            creator="0xcreator",
            collateral_token="0xtoken",
            market="0xmarket",
            parent_collection_id="0x" + "00" * 32,
        )

        assert "holdings" in result
        assert "shares" in result
        assert len(result["holdings"]) == 2
        assert len(result["shares"]) == 2

    def test_get_balance_of(self) -> None:
        """Test getting balance for a specific position."""
        self.mock_contract.functions.balanceOf.return_value.call.return_value = 500
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = ConditionalTokensContract.get_balance_of(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            owner="0xowner",
            position_id=42,
        )
        assert result == {"balance": 500}

    def test_build_merge_positions_tx(self) -> None:
        """Test building merge positions transaction."""
        self.mock_contract.encode_abi.return_value = b"\xcc\xdd"
        self.mock_ledger_api.api.to_checksum_address.side_effect = lambda x: x

        result = ConditionalTokensContract.build_merge_positions_tx(
            ledger_api=self.mock_ledger_api,
            contract_address=CONTRACT_ADDRESS,
            collateral_token="0xtoken",
            parent_collection_id=b"\x00" * 32,
            condition_id=b"\xaa" * 32,
            outcome_slot_count=2,
            amount=1000,
        )
        assert result == {"data": b"\xcc\xdd"}


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
