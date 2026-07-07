# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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

"""This module contains the balance_tracker contract definition."""

import logging
from typing import Any, Dict, Union, cast

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/balance_tracker:0.1.0")

_logger = logging.getLogger(
    f"aea.packages.{PUBLIC_ID.author}.contracts.{PUBLIC_ID.name}.contract"
)


class BalanceTrackerContract(Contract):
    """The scaffold contract class for a smart contract."""

    contract_id = PublicId.from_str("valory/balance_tracker:0.1.0")

    @classmethod
    def get_mech_balance(
        cls, ledger_api: LedgerApi, contract_address: str, mech_address: str
    ) -> JSONLike:
        """Get mech balance"""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        mech_balance = contract_instance.functions.mapMechBalances(mech_address).call()
        return {"mech_balance": mech_balance}

    @classmethod
    def get_requester_balance(
        cls, ledger_api: LedgerApi, contract_address: str, requester: str
    ) -> JSONLike:
        """Get requester balance."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        requester_balance = contract_instance.functions.mapRequesterBalances(
            requester
        ).call()
        return {"requester_balance": requester_balance}

    @classmethod
    def get_max_fee_factor(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
    ) -> JSONLike:
        """Get mech balance"""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        max_fee_factor = contract_instance.functions.MAX_FEE_FACTOR().call()
        return {"max_fee_factor": max_fee_factor}

    @classmethod
    def get_token_address(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
    ) -> JSONLike:
        """Get tx data"""

        contract_instance = cls.get_instance(ledger_api, contract_address)
        token_address = contract_instance.functions.token().call()
        return {"token_address": token_address}  # type: ignore

    @classmethod
    def get_token_credit_ratio(
        cls, ledger_api: LedgerApi, contract_address: str
    ) -> JSONLike:
        """Get token credit ratio"""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        token_credit_ratio = contract_instance.functions.tokenCreditRatio().call()
        return {"token_credit_ratio": token_credit_ratio}  # type: ignore

    @classmethod
    def simulate_tx(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        sender_address: str,
        data: str,
    ) -> JSONLike:
        """Simulate the transaction."""
        try:
            ledger_api.api.eth.call(
                {
                    "from": ledger_api.api.to_checksum_address(sender_address),
                    "to": ledger_api.api.to_checksum_address(contract_address),
                    "data": data,
                }
            )
            simulation_ok = True
        except Exception as e:
            _logger.info(f"Simulation failed: {str(e)}")
            simulation_ok = False

        return dict(data=simulation_ok)

    @classmethod
    def get_process_payment_tx(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        sender_address: str,
        mech_address: str,
    ) -> JSONLike:
        """Get tx data"""

        contract_instance = cls.get_instance(ledger_api, contract_address)
        tx_data = contract_instance.encode_abi(
            abi_element_identifier="processPaymentByMultisig",
            args=[mech_address],
        )
        simulation_ok = cls.simulate_tx(
            ledger_api, contract_address, sender_address, tx_data
        ).pop("data")
        return {"data": bytes.fromhex(tx_data[2:]), "simulation_ok": simulation_ok}  # type: ignore

    @classmethod
    def build_deposit_for_data(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        account: str,
        amount: int,
    ) -> JSONLike:
        """Encode depositFor(account, amount) for a Safe multisend batch."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encode_abi(
            abi_element_identifier="depositFor",
            args=[account, amount],
        )
        return {"data": bytes.fromhex(data[2:])}  # type: ignore

    # ------------------------------------------------------------------
    # NOTE (time-crunch, trader-local override):
    # This method was added trader-side under time pressure so the
    # pre-deposit-as-loss ROI accounting in
    # ``agent_performance_summary_abci`` can land without waiting on an
    # upstream release. To make that possible the whole
    # ``valory/balance_tracker`` package was moved from ``third_party``
    # into ``dev`` in ``packages.json``. When bandwidth allows, port this
    # classmethod upstream into ``valory-xyz/mech``'s ``balance_tracker``
    # contract, cut a mech release, bump ``upstream_pins`` in trader's
    # ``pyproject.toml``, move the package back to ``third_party``, and
    # drop this override.
    # ------------------------------------------------------------------
    @classmethod
    def get_deposit_events_for_requester(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        requester: str,
        from_block: int,
        to_block: Union[int, str] = "latest",
    ) -> JSONLike:
        """Return processed ``Deposit`` events for one requester.

        Filters ``Deposit(address indexed account, address indexed token,
        uint256 amount)`` by ``account == requester`` over
        ``[from_block, to_block]`` inclusive. Aggregation (summing amounts,
        tracking the latest matched block) lives in the caller by
        convention (see ``mech_marketplace.contract``); this classmethod
        only issues the ``eth_getLogs`` call and returns decoded entries.
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        event = contract_instance.events.Deposit()
        filter_params: Dict[str, Any] = {
            "fromBlock": from_block,
            "toBlock": to_block,
            "address": contract_instance.address,
            "topics": [
                event.topic,
                "0x" + requester[2:].lower().rjust(64, "0"),
            ],
        }
        logs = ledger_api.api.eth.get_logs(filter_params)
        return {"entries": [event.process_log(log) for log in logs]}
