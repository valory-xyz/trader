# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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

"""This module contains the class to connect to a Mech contract."""

import concurrent.futures
from typing import Any, Callable, Dict, List, cast

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from aea_ledger_ethereum.ethereum import rpc_call_with_timeout
from eth_typing import HexStr
from web3.types import BlockData, BlockIdentifier, EventData, TxReceipt


PUBLIC_ID = PublicId.from_str("valory/mech_mm:0.1.0")
FIVE_MINUTES = 300.0


class MechMM(Contract):
    """The Mech contract for marketplace."""

    contract_id = PUBLIC_ID

    @classmethod
    def get_request_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        request_data: bytes,
        **kwargs: Any,
    ) -> Dict[str, bytes]:
        """Gets the encoded arguments for a request tx, which should only be called via the multisig.

        :param ledger_api: the ledger API object
        :param contract_address: the contract's address
        :param request_data: the request data
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        encoded_data = contract_instance.encodeABI("request", args=(request_data,))
        return {"data": bytes.fromhex(encoded_data[2:])}

    @classmethod
    def _process_event(
        cls,
        ledger_api: LedgerApi,
        contract: Any,
        tx_hash: HexStr,
        expected_logs: int,
        event_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> JSONLike:
        """Process the logs of the given event."""
        ledger_api = cast(EthereumApi, ledger_api)
        receipt: TxReceipt = ledger_api.api.eth.get_transaction_receipt(tx_hash)
        event_method = getattr(contract.events, event_name)
        logs: List[EventData] = list(event_method().process_receipt(receipt))

        n_logs = len(logs)
        if n_logs != expected_logs:
            error = f"{expected_logs} {event_name!r} events were expected. tx {tx_hash} emitted {n_logs} instead."
            return {"error": error}

        results = []
        for log in logs:
            event_args = log.get("args", None)
            if event_args is None or any(
                expected_key not in event_args for expected_key in args
            ):
                return {
                    "error": f"The emitted event's ({event_name}) logs for tx {tx_hash} do not match the expected format: {log}"
                }
            results.append({arg_name: event_args[arg_name] for arg_name in args})

        return dict(results=results)

    @staticmethod
    def _to_prefixed_hex(value: bytes) -> str:
        """Convert bytes to a hex string prefixed with '0x'."""
        return "0x" + value.hex()

    @classmethod
    def get_response(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        request_id: bytes,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
        timeout: float = FIVE_MINUTES,
        **kwargs: Any,
    ) -> JSONLike:
        """Filter the `Deliver` events emitted by the contract and get the data of the given `request_id`.

        :param request_id: bytes32 request ID to match against event logs
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        ledger_api = cast(EthereumApi, ledger_api)

        def get_responses() -> Any:
            """Get the responses from the contract."""
            contract_instance = cls.get_instance(ledger_api, contract_address)
            deliver_filter = contract_instance.events.Deliver.build_filter()
            deliver_filter.fromBlock = from_block
            deliver_filter.toBlock = to_block
            # Match against bytes32 requestId
            deliver_filter.args.requestId.match_single(request_id)
            delivered = list(deliver_filter.deploy(ledger_api.api).get_all_entries())
            n_delivered = len(delivered)

            if n_delivered == 0:
                # Convert bytes to hex for logging
                hex_request_id = cls._to_prefixed_hex(request_id)
                info = f"The mech ({contract_address}) has not delivered a response yet for request with id {hex_request_id}."
                return {"info": info}

            if n_delivered != 1:
                hex_request_id = cls._to_prefixed_hex(request_id)
                error = (
                    f"A single response was expected by the mech ({contract_address}) for request with id {hex_request_id}. "
                    f"Received {n_delivered} responses: {delivered}."
                )
                return error

            delivered_event = delivered.pop()
            deliver_args = delivered_event.get("args", None)
            if deliver_args is None or "data" not in deliver_args:
                error = f"The mech's response does not match the expected format: {delivered_event}"
                return error

            return dict(data=deliver_args["data"])

        data, err = rpc_call_with_timeout(get_responses, timeout=int(timeout))
        if err is not None:
            return {"error": err}

        return data

    @classmethod
    def get_payment_type(
        cls, ledger_api: EthereumApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """Get the payment type (bytes32) from the contract.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :return: the payment type as a hex string with '0x' prefix
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        # Call the paymentType() function
        payment_type = ledger_api.contract_method_call(contract_instance, "paymentType")
        # Convert bytes32 to hex string with '0x' prefix
        payment_type_hex = cls._to_prefixed_hex(payment_type)
        return dict(payment_type=payment_type_hex)

    @classmethod
    def get_max_delivery_rate(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        **kwargs: Any,
    ) -> JSONLike:
        """Get the max delivery rate from the contract.

        :param ledger_api: the ledger API object
        :param contract_address: the contract address
        :return: the max delivery rate
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        max_delivery_rate = ledger_api.contract_method_call(
            contract_instance, "maxDeliveryRate"
        )
        return dict(max_delivery_rate=max_delivery_rate)
