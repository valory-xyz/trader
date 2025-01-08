# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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
from eth_typing import HexStr
from web3.types import BlockData, BlockIdentifier, EventData, TxReceipt


PUBLIC_ID = PublicId.from_str("valory/mech:0.1.0")
FIVE_MINUTES = 300.0


partial_abis = [
    [
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "requestId",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "bytes",
                    "name": "data",
                    "type": "bytes",
                },
            ],
            "name": "Deliver",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "sender",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "requestId",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "bytes",
                    "name": "data",
                    "type": "bytes",
                },
            ],
            "name": "Request",
            "type": "event",
        },
    ],
    [
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "sender",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "requestId",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "requestIdWithNonce",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "bytes",
                    "name": "data",
                    "type": "bytes",
                },
            ],
            "name": "Request",
            "type": "event",
        },
        {
            "anonymous": False,
            "inputs": [
                {
                    "indexed": True,
                    "internalType": "address",
                    "name": "sender",
                    "type": "address",
                },
                {
                    "indexed": False,
                    "internalType": "uint256",
                    "name": "requestId",
                    "type": "uint256",
                },
                {
                    "indexed": False,
                    "internalType": "bytes",
                    "name": "data",
                    "type": "bytes",
                },
            ],
            "name": "Deliver",
            "type": "event",
        },
    ],
]


class Mech(Contract):
    """The Mech contract."""

    contract_id = PUBLIC_ID

    @staticmethod
    def execute_with_timeout(func: Callable, timeout: float) -> Any:
        """Execute a function with a timeout."""

        # Create a ProcessPoolExecutor with a maximum of 1 worker (process)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # Submit the function to the executor
            future = executor.submit(
                func,
            )

            try:
                # Wait for the result with a 5-minute timeout
                data = future.result(timeout=timeout)
            except TimeoutError:
                # Handle the case where the execution times out
                err = f"The RPC didn't respond in {timeout}."
                return None, err

            # Check if an error occurred
            if isinstance(data, str):
                # Handle the case where the execution failed
                return None, data

            return data, None

    @classmethod
    def get_price(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        **kwargs: Any
    ) -> JSONLike:
        """Get the price of a request."""
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        price = ledger_api.contract_method_call(contract_instance, "price")
        return dict(price=price)

    @classmethod
    def get_request_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        request_data: bytes,
        **kwargs: Any
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
        **kwargs: Any
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
                return {"error": f"The emitted event's ({event_name}) logs for tx {tx_hash} do not match the expected format: {log}"}
            results.append({arg_name: event_args[arg_name] for arg_name in args})

        return dict(results=results)

    @classmethod
    def process_request_event(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        tx_hash: HexStr,
        expected_logs: int = 1,
        **kwargs: Any
    ) -> JSONLike:
        """
        Process the request receipt to get the requestId and the given data from the `Request` event's logs.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param tx_hash: the hash of a request tx to be processed.
        :param expected_logs: the number of logs expected.
        :return: a dictionary with a key named `results`
        which contains a list of dictionaries (as many as the expected logs) containing the request id and the data.
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        res = {}
        for abi in partial_abis:
            contract_instance = ledger_api.api.eth.contract(contract_address, abi=abi)
            res = cls._process_event(
                ledger_api, contract_instance, tx_hash, expected_logs, "Request", "requestId", "data"
            )
            if "error" not in res:
                return res

        return res

    @classmethod
    def process_deliver_event(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        tx_hash: HexStr,
        expected_logs: int = 1,
        **kwargs: Any
    ) -> JSONLike:
        """
        Process the request receipt to get the requestId and the delivered data if the `Deliver` event has been emitted.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param tx_hash: the hash of a request tx to be processed.
        :param expected_logs: the number of logs expected.
        :return: a dictionary with the request id and the data.
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        res = {}
        for abi in partial_abis:
            contract_instance = ledger_api.api.eth.contract(contract_address, abi=abi)
            res = cls._process_event(
                ledger_api, contract_instance, tx_hash, expected_logs, "Deliver", "requestId", "data"
            )
            if "error" not in res:
                return res

        return res
    @classmethod
    def get_block_number(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        tx_hash: HexStr,
        **kwargs: Any
    ) -> JSONLike:
        """Get the number of the block in which the tx of the given hash was settled."""
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        receipt: TxReceipt = ledger_api.api.eth.get_transaction_receipt(tx_hash)
        block: BlockData = ledger_api.api.eth.get_block(receipt["blockNumber"])
        return dict(number=block["number"])

    @classmethod
    def get_response(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        request_id: int,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
        timeout: float = FIVE_MINUTES,
        **kwargs: Any
    ) -> JSONLike:
        """Filter the `Deliver` events emitted by the contract and get the data of the given `request_id`."""
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        ledger_api = cast(EthereumApi, ledger_api)

        def get_responses() -> Any:
            """Get the responses from the contract."""
            contract_instance = cls.get_instance(ledger_api, contract_address)
            deliver_filter = contract_instance.events.Deliver.build_filter()
            deliver_filter.fromBlock = from_block
            deliver_filter.toBlock = to_block
            deliver_filter.args.requestId.match_single(request_id)
            delivered = list(deliver_filter.deploy(ledger_api.api).get_all_entries())
            n_delivered = len(delivered)

            if n_delivered == 0:
                info = f"The mech ({contract_address}) has not delivered a response yet for request with id {request_id}."
                return {"info": info}

            if n_delivered != 1:
                error = (
                    f"A single response was expected by the mech ({contract_address}) for request with id {request_id}. "
                    f"Received {n_delivered} responses: {delivered}."
                )
                return error

            delivered_event = delivered.pop()
            deliver_args = delivered_event.get("args", None)
            if deliver_args is None or "data" not in deliver_args:
                error = f"The mech's response does not match the expected format: {delivered_event}"
                return error

            return dict(data=deliver_args["data"])

        data, err = cls.execute_with_timeout(get_responses, timeout=timeout)
        if err is not None:
            return {"error": err}

        return data

    @classmethod
    def get_mech_id(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        **kwargs: Any
    ) -> JSONLike:
        """Get the price of a request."""
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        mech_id = ledger_api.contract_method_call(contract_instance, "tokenId")
        return dict(id=mech_id)

    @classmethod
    def get_requests_count(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        address: str,
        **kwargs: Any
    ) -> JSONLike:
        """Get the requests count."""
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        address = ledger_api.api.to_checksum_address(address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        requests_count = contract_instance.functions.getRequestsCount(address).call()
        return {"requests_count": requests_count}

    @classmethod
    def get_pending_requests(cls, ledger_api: EthereumApi, contract_address: str, sender_address: str, **kwargs: Any) -> JSONLike:
        """Get the pending requests."""
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        sender_address = ledger_api.api.to_checksum_address(sender_address)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        pending_requests = contract_instance.functions.mapUndeliveredRequestsCounts(sender_address).call()
        return {"pending_requests": pending_requests}
