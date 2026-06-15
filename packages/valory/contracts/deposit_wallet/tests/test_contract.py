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

"""Tests for the DepositWalletContract."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.contracts.deposit_wallet.contract import DepositWalletContract

ADDR = "0x1234567890abcdef1234567890abcdef12345678"
DW = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"


class TestNotImplementedHandlers:
    """The base ABCI handlers are intentionally unimplemented."""

    def test_get_raw_transaction(self) -> None:
        """get_raw_transaction raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            DepositWalletContract.get_raw_transaction(MagicMock(), ADDR)

    def test_get_raw_message(self) -> None:
        """get_raw_message raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            DepositWalletContract.get_raw_message(MagicMock(), ADDR)

    def test_get_state(self) -> None:
        """get_state raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            DepositWalletContract.get_state(MagicMock(), ADDR)


class TestGetOwner:
    """Tests for the on-chain owner read."""

    def test_get_owner(self) -> None:
        """get_owner returns the owner from the on-chain call."""
        ledger_api = MagicMock()
        instance = MagicMock()
        instance.functions.owner.return_value.call.return_value = ADDR
        with patch.object(DepositWalletContract, "get_instance", return_value=instance):
            result = DepositWalletContract.get_owner(
                ledger_api=ledger_api, contract_address=DW
            )
        assert result == {"owner": ADDR}
        instance.functions.owner.assert_called_once()


class TestGetNonce:
    """Tests for the on-chain batch-nonce read."""

    def test_get_nonce(self) -> None:
        """get_nonce returns the DW's batch nonce from the on-chain call."""
        ledger_api = MagicMock()
        instance = MagicMock()
        instance.functions.nonce.return_value.call.return_value = 7
        with patch.object(DepositWalletContract, "get_instance", return_value=instance):
            result = DepositWalletContract.get_nonce(
                ledger_api=ledger_api, contract_address=DW
            )
        assert result == {"nonce": 7}
        instance.functions.nonce.assert_called_once()


class TestABIConsistency:
    """The methods used by the contract must exist in the shipped ABI."""

    def test_abi_exposes_used_functions(self) -> None:
        """Owner / nonce / execute / isValidSignature are in the ABI."""
        abi_path = Path(__file__).parent.parent / "build" / "DepositWallet.json"
        with open(abi_path) as f:
            abi = json.load(f)["abi"]
        names = {e["name"] for e in abi if e.get("type") == "function"}
        assert {"owner", "nonce", "execute", "isValidSignature"} <= names
