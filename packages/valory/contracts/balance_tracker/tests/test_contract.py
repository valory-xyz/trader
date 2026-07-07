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

"""Encode-assertion tests for the balance_tracker contract package."""

import json
from pathlib import Path
from unittest.mock import patch

from web3 import Web3

from packages.valory.contracts.balance_tracker.contract import BalanceTrackerContract

_ABI_PATH = Path(__file__).parent.parent / "build" / "BalanceTracker.json"
_ACCOUNT = "0x1000000000000000000000000000000000000001"
_AMOUNT = 12345
_DEPOSIT_FOR_SELECTOR = "2f4f21e2"


def _web3_contract() -> object:
    """Build a Web3 contract instance from the packaged ABI."""
    with open(_ABI_PATH) as f:
        artifact = json.load(f)
    return Web3().eth.contract(abi=artifact["abi"])


class TestBuildDepositForData:
    """`build_deposit_for_data` produces well-formed `depositFor(account, amount)` calldata."""

    def test_calldata_starts_with_deposit_for_selector(self) -> None:
        """The 4-byte selector matches keccak256("depositFor(address,uint256)")[:4]."""
        with patch.object(
            BalanceTrackerContract, "get_instance", return_value=_web3_contract()
        ):
            result = BalanceTrackerContract.build_deposit_for_data(
                ledger_api=None,  # patched away
                contract_address="0x0000000000000000000000000000000000000000",
                account=_ACCOUNT,
                amount=_AMOUNT,
            )
        assert result["data"][:4].hex() == _DEPOSIT_FOR_SELECTOR

    def test_calldata_has_expected_length(self) -> None:
        """4-byte selector + 32-byte address + 32-byte uint256 = 68 bytes."""
        with patch.object(
            BalanceTrackerContract, "get_instance", return_value=_web3_contract()
        ):
            result = BalanceTrackerContract.build_deposit_for_data(
                ledger_api=None,
                contract_address="0x0000000000000000000000000000000000000000",
                account=_ACCOUNT,
                amount=_AMOUNT,
            )
        assert len(result["data"]) == 68

    def test_calldata_encodes_amount_argument(self) -> None:
        """The last 32 bytes decode to the supplied amount."""
        with patch.object(
            BalanceTrackerContract, "get_instance", return_value=_web3_contract()
        ):
            result = BalanceTrackerContract.build_deposit_for_data(
                ledger_api=None,
                contract_address="0x0000000000000000000000000000000000000000",
                account=_ACCOUNT,
                amount=_AMOUNT,
            )
        assert int.from_bytes(result["data"][-32:], "big") == _AMOUNT
