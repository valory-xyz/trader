# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for the trader-local BalanceTracker.Deposit reader."""

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from web3 import Web3

from packages.valory.contracts.mech_prepaid_reader.contract import (
    MechPrepaidReaderContract,
)

_ABI_PATH = Path(__file__).parent.parent / "build" / "MechPrepaidReader.json"
_TRACKER_ADDRESS = "0x2000000000000000000000000000000000000002"
_REQUESTER = "0x3000000000000000000000000000000000000003"


def _web3_contract() -> object:
    """Build a Web3 contract instance from the packaged ABI."""
    with open(_ABI_PATH) as f:
        artifact = json.load(f)
    return Web3().eth.contract(abi=artifact["abi"], address=_TRACKER_ADDRESS)


def _mock_ledger_api(logs: List[Dict[str, Any]]) -> MagicMock:
    """Build a ledger_api stub whose ``eth.get_logs`` returns ``logs``."""
    ledger_api = MagicMock()
    ledger_api.api.to_checksum_address.side_effect = Web3.to_checksum_address
    ledger_api.api.eth.get_logs.return_value = logs
    return ledger_api


def _make_deposit_log(
    *, account: str, amount: int, block_number: int
) -> Dict[str, Any]:
    """Build a raw Deposit log dict matching Web3.py's format.

    Deposit(address indexed account, address indexed token, uint256 amount)
    => topic[0]=event sig, topic[1]=padded account, topic[2]=padded token,
       data=abi-encoded amount (single uint256, 32 bytes hex).

    :param account: requester address that appears in ``topics[1]``
        (left-padded to 32 bytes).
    :param amount: deposit amount encoded as the 32-byte ``data`` field.
    :param block_number: block number stamped on the log entry.
    :return: log dict shaped exactly like the Web3.py get_logs response.
    """
    padded_account = "0x" + account[2:].lower().rjust(64, "0")
    padded_token = "0x" + "0" * 64  # zero token for tests
    event_signature = Web3.keccak(text="Deposit(address,address,uint256)").hex()
    data = "0x" + hex(amount)[2:].rjust(64, "0")
    return {
        "address": _TRACKER_ADDRESS,
        "topics": [
            bytes.fromhex(
                event_signature[2:]
                if event_signature.startswith("0x")
                else event_signature
            ),
            bytes.fromhex(padded_account[2:]),
            bytes.fromhex(padded_token[2:]),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": bytes.fromhex("aa" * 32),
        "transactionIndex": 0,
        "blockHash": bytes.fromhex("bb" * 32),
        "logIndex": 0,
        "removed": False,
    }


class TestGetDepositEventsForRequester:
    """``get_deposit_events_for_requester`` filters Deposit logs by requester."""

    def _filter_params_captured(self, logs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Invoke the method with returned logs and capture the get_logs call args."""
        instance = _web3_contract()
        ledger_api = _mock_ledger_api(logs)
        with patch.object(
            MechPrepaidReaderContract, "get_instance", return_value=instance
        ):
            MechPrepaidReaderContract.get_deposit_events_for_requester(
                ledger_api=ledger_api,
                contract_address=_TRACKER_ADDRESS,
                requester=_REQUESTER,
                from_block=100,
                to_block=200,
            )
        call_args, _ = ledger_api.api.eth.get_logs.call_args
        return call_args[0]

    def test_topic_filter_pads_requester_to_32_bytes(self) -> None:
        """topics[1] is the requester left-padded to 32 bytes for indexed-arg matching."""
        params = self._filter_params_captured([])
        assert len(params["topics"]) == 2
        expected_padded = "0x" + _REQUESTER[2:].lower().rjust(64, "0")
        assert params["topics"][1] == expected_padded

    def test_filter_uses_from_and_to_block_range(self) -> None:
        """The eth_getLogs filter carries the caller-provided block range verbatim."""
        params = self._filter_params_captured([])
        assert params["fromBlock"] == 100
        assert params["toBlock"] == 200

    def test_empty_logs_returns_empty_entries(self) -> None:
        """No matches -> empty entries list, no crash."""
        instance = _web3_contract()
        ledger_api = _mock_ledger_api([])
        with patch.object(
            MechPrepaidReaderContract, "get_instance", return_value=instance
        ):
            result = MechPrepaidReaderContract.get_deposit_events_for_requester(
                ledger_api=ledger_api,
                contract_address=_TRACKER_ADDRESS,
                requester=_REQUESTER,
                from_block=100,
                to_block=200,
            )
        assert result == {"entries": []}

    def test_matching_logs_decode_into_entries(self) -> None:
        """Real Deposit logs decode into entries carrying the amount and block number."""
        instance = _web3_contract()
        logs = [
            _make_deposit_log(account=_REQUESTER, amount=1500, block_number=142),
            _make_deposit_log(account=_REQUESTER, amount=250, block_number=175),
        ]
        ledger_api = _mock_ledger_api(logs)
        with patch.object(
            MechPrepaidReaderContract, "get_instance", return_value=instance
        ):
            result = MechPrepaidReaderContract.get_deposit_events_for_requester(
                ledger_api=ledger_api,
                contract_address=_TRACKER_ADDRESS,
                requester=_REQUESTER,
                from_block=100,
                to_block=200,
            )
        entries = result["entries"]
        assert entries == [
            {"amount": 1500, "block_number": 142},
            {"amount": 250, "block_number": 175},
        ]
