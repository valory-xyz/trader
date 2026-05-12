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

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from hexbytes import HexBytes

from packages.valory.contracts.market_maker.contract import (
    Contract,
    FPMM_SELL_TOPIC0,
    FixedProductMarketMakerContract,
)

CONTRACT_ADDRESS = "0x1234567890abcdef1234567890abcdef12345678"
WXDAI = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"  # nosec B105
CONDITIONAL_TOKENS_ADDRESS = (  # nosec B105 gitleaks:allow
    "0xCeAfDD6bc0bEF976fdCd1112955828E00543c0Ce"
)
FPMM_ADDR = "0x9371158c040dc04AdeC99E03f82CDa9C0D804af7"  # nosec B105
SELLER_ADDR = "0x19f4d0728906968649862788c7975ef503f43380"  # nosec B105


def _padded_address(addr: str) -> str:
    """Return the 32-byte zero-padded address as a 0x-prefixed hex string."""
    return "0x" + "00" * 12 + addr[2:].lower()


def _padded_uint(value: int) -> str:
    """Return the 32-byte big-endian uint as a 0x-prefixed hex string."""
    return "0x" + value.to_bytes(32, "big").hex()


def _build_fpmm_sell_log(
    fpmm: str,
    seller: str,
    outcome_index: int,
    return_amount: int,
    fee_amount: int,
    outcome_tokens_sold: int,
) -> dict:
    """Construct a synthetic FPMMSell log entry matching the on-chain layout."""
    data_bytes = (
        return_amount.to_bytes(32, "big")
        + fee_amount.to_bytes(32, "big")
        + outcome_tokens_sold.to_bytes(32, "big")
    )
    return {
        "address": fpmm,
        "topics": [
            FPMM_SELL_TOPIC0.hex(),
            _padded_address(seller),
            _padded_uint(outcome_index),
        ],
        "data": "0x" + data_bytes.hex(),
    }


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


class TestParseSellEvents:
    """Tests for FixedProductMarketMakerContract.parse_sell_events."""

    @staticmethod
    def _ledger_api_mock() -> MagicMock:
        """Build a ledger_api mock whose ``to_checksum_address`` is pass-through."""
        mock = MagicMock()
        mock.api.to_checksum_address.side_effect = lambda a: a
        return mock

    def test_decodes_single_fpmm_sell_log(self) -> None:
        """A single FPMMSell log decodes into its declared fields."""
        # Fixture #3 from spec §4.2: returnAmount = 3,519,873,291,980,893,
        # outcomeTokensSold = 21,748,084,402,732,159, feeAmount = 35,554,275,676,574,
        # outcomeIndex = 0, FPMM = 0x9371158c…
        receipt = {
            "logs": [
                _build_fpmm_sell_log(
                    fpmm=FPMM_ADDR,
                    seller=SELLER_ADDR,
                    outcome_index=0,
                    return_amount=3_519_873_291_980_893,
                    fee_amount=35_554_275_676_574,
                    outcome_tokens_sold=21_748_084_402_732_159,
                )
            ]
        }
        result = FixedProductMarketMakerContract.parse_sell_events(
            ledger_api=self._ledger_api_mock(),
            contract_address=CONTRACT_ADDRESS,
            receipt=receipt,
        )
        assert result == {
            "events": [
                {
                    "seller": SELLER_ADDR,
                    "fpmm": FPMM_ADDR,
                    "outcome_index": 0,
                    "return_amount": 3_519_873_291_980_893,
                    "fee_amount": 35_554_275_676_574,
                    "outcome_tokens_sold": 21_748_084_402_732_159,
                }
            ]
        }

    def test_decodes_multiple_logs_in_order(self) -> None:
        """Multiple FPMMSell logs are decoded into a list in receipt order."""
        log0 = _build_fpmm_sell_log(
            fpmm=FPMM_ADDR,
            seller=SELLER_ADDR,
            outcome_index=0,
            return_amount=1_000_000_000_000_000,
            fee_amount=10_000_000_000_000,
            outcome_tokens_sold=2_500_000_000_000_000,
        )
        log1 = _build_fpmm_sell_log(
            fpmm="0x3767f3b500d7d0d51e72f80213b3531beea1b6f5",
            seller=SELLER_ADDR,
            outcome_index=1,
            return_amount=5_000_000_000_000_000,
            fee_amount=0,
            outcome_tokens_sold=12_000_000_000_000_000,
        )
        result = FixedProductMarketMakerContract.parse_sell_events(
            ledger_api=self._ledger_api_mock(),
            contract_address=CONTRACT_ADDRESS,
            receipt={"logs": [log0, log1]},
        )
        events = result["events"]
        assert len(events) == 2
        assert events[0]["outcome_index"] == 0
        assert events[0]["return_amount"] == 1_000_000_000_000_000
        assert events[1]["outcome_index"] == 1
        assert events[1]["return_amount"] == 5_000_000_000_000_000
        assert events[1]["fee_amount"] == 0

    def test_filters_logs_by_topic0(self) -> None:
        """Non-FPMMSell logs (different topic0) are skipped."""
        unrelated_log = {
            "address": "0x0000000000000000000000000000000000001234",
            "topics": ["0x" + "ab" * 32, _padded_address(SELLER_ADDR)],
            "data": "0x" + "00" * 32,
        }
        sell_log = _build_fpmm_sell_log(
            fpmm=FPMM_ADDR,
            seller=SELLER_ADDR,
            outcome_index=0,
            return_amount=42,
            fee_amount=0,
            outcome_tokens_sold=100,
        )
        result = FixedProductMarketMakerContract.parse_sell_events(
            ledger_api=self._ledger_api_mock(),
            contract_address=CONTRACT_ADDRESS,
            receipt={"logs": [unrelated_log, sell_log]},
        )
        assert len(result["events"]) == 1
        assert result["events"][0]["return_amount"] == 42

    def test_empty_receipt(self) -> None:
        """A receipt with no logs returns an empty events list."""
        result = FixedProductMarketMakerContract.parse_sell_events(
            ledger_api=self._ledger_api_mock(),
            contract_address=CONTRACT_ADDRESS,
            receipt={"logs": []},
        )
        assert result == {"events": []}

    def test_missing_logs_key(self) -> None:
        """A receipt with no ``logs`` key returns an empty events list."""
        result = FixedProductMarketMakerContract.parse_sell_events(
            ledger_api=self._ledger_api_mock(),
            contract_address=CONTRACT_ADDRESS,
            receipt={},
        )
        assert result == {"events": []}


class TestGetPoolBalancesViaCT:
    """Tests for FixedProductMarketMakerContract.get_pool_balances_via_ct."""

    @staticmethod
    def _setup_ct_instance(slot_count: int, collection_ids: list, balances: list):
        """Build a CT mock that yields the given collection IDs and balances in order."""
        ct_instance = MagicMock()
        slot_count_call = MagicMock()
        slot_count_call.call.return_value = slot_count
        ct_instance.functions.getOutcomeSlotCount.return_value = slot_count_call

        coll_id_callers = [MagicMock() for _ in collection_ids]
        for caller, cid_bytes in zip(coll_id_callers, collection_ids):
            caller.call.return_value = cid_bytes
        ct_instance.functions.getCollectionId.side_effect = coll_id_callers

        balance_callers = [MagicMock() for _ in balances]
        for caller, bal in zip(balance_callers, balances):
            caller.call.return_value = bal
        ct_instance.functions.balanceOf.side_effect = balance_callers
        return ct_instance

    def test_reads_one_balance_per_outcome(self) -> None:
        """Returns slot_count balances; queries CT for each."""
        # Mirror live read on FPMM 0x9371158c… from spec §13.8: outcome 0 ≈
        # 16.24 tokens, outcome 1 ≈ 3.02 tokens.
        coll_id_0 = b"\xaa" * 31 + b"\x01"
        coll_id_1 = b"\xaa" * 31 + b"\x02"
        position_id_0 = b"\x42" * 32
        position_id_1 = b"\x43" * 32
        balances = [16_240_700_000_000_000_000, 3_017_100_000_000_000_000]

        ct_instance = self._setup_ct_instance(
            slot_count=2,
            collection_ids=[coll_id_0, coll_id_1],
            balances=balances,
        )

        ledger_api = MagicMock()
        ledger_api.api.to_checksum_address.side_effect = lambda a: a
        # solidity_keccak is called once per outcome with
        # (["address","uint256"], [collateral, collection_id_int]).
        ledger_api.api.solidity_keccak.side_effect = [
            HexBytes(position_id_0),
            HexBytes(position_id_1),
        ]

        with patch(
            "packages.valory.contracts.market_maker.contract."
            "ConditionalTokensContract.get_instance",
            return_value=ct_instance,
        ):
            result = FixedProductMarketMakerContract.get_pool_balances_via_ct(
                ledger_api=ledger_api,
                contract_address=FPMM_ADDR,
                conditional_tokens_address=CONDITIONAL_TOKENS_ADDRESS,
                collateral_token=WXDAI,
                condition_id="0x" + "4e" * 32,
            )

        assert result == {"balances": balances}

        # getCollectionId called with (zero parent, condition bytes, 1 << i).
        call_args = ct_instance.functions.getCollectionId.call_args_list
        assert [c.args[0] for c in call_args] == [b"\x00" * 32, b"\x00" * 32]
        assert [c.args[2] for c in call_args] == [1, 2]

        # solidity_keccak called with the canonical (address, uint256) shape.
        for call in ledger_api.api.solidity_keccak.call_args_list:
            types, values = call.args
            assert types == ["address", "uint256"]
            assert values[0] == WXDAI

        # balanceOf called with (fpmm, derived_position_id) in outcome order.
        bal_calls = ct_instance.functions.balanceOf.call_args_list
        assert bal_calls[0].args == (FPMM_ADDR, int.from_bytes(position_id_0, "big"))
        assert bal_calls[1].args == (FPMM_ADDR, int.from_bytes(position_id_1, "big"))

    def test_binary_market_returns_two_entries(self) -> None:
        """Slot count of 2 produces exactly two balance entries."""
        ct_instance = self._setup_ct_instance(
            slot_count=2,
            collection_ids=[b"\x00" * 32, b"\x01" * 32],
            balances=[100, 200],
        )
        ledger_api = MagicMock()
        ledger_api.api.to_checksum_address.side_effect = lambda a: a
        ledger_api.api.solidity_keccak.side_effect = [
            HexBytes(b"\xaa" * 32),
            HexBytes(b"\xbb" * 32),
        ]
        with patch(
            "packages.valory.contracts.market_maker.contract."
            "ConditionalTokensContract.get_instance",
            return_value=ct_instance,
        ):
            result = FixedProductMarketMakerContract.get_pool_balances_via_ct(
                ledger_api=ledger_api,
                contract_address=FPMM_ADDR,
                conditional_tokens_address=CONDITIONAL_TOKENS_ADDRESS,
                collateral_token=WXDAI,
                condition_id="0x" + "4e" * 32,
            )
        assert result == {"balances": [100, 200]}


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
            r"_method_call\([^)]*?[\"'](\w+)[\"']",
            r"_encode_abi\([^)]*?[\"'](\w+)[\"']",
        ]
        referenced_functions: set = set()
        for pattern in function_patterns:
            referenced_functions.update(re.findall(pattern, source))
        event_pattern = r"\.events\.(\w+)"
        referenced_events: set = set(re.findall(event_pattern, source))
        return referenced_functions, referenced_events

    # Functions that are called via cross-contract instances (e.g.
    # ConditionalTokens), not via the FPMM contract — these legitimately
    # don't appear in the FPMM ABI and must be excluded from the check.
    _CROSS_CONTRACT_FUNCTIONS = frozenset(
        {"getOutcomeSlotCount", "getCollectionId", "balanceOf"}
    )

    def test_functions_present_in_abi(self) -> None:
        """All contract functions referenced in contract.py must exist in the ABI."""
        abi_functions, _ = self._get_abi_names()
        referenced_functions, _ = self._get_contract_references()
        missing = referenced_functions - abi_functions - self._CROSS_CONTRACT_FUNCTIONS
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
