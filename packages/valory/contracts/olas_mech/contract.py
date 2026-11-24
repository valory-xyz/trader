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

"""This module contains the dynamic_contribution contract definition."""

import logging
import re
import threading
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union, cast

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi
from web3.exceptions import ContractLogicError

from packages.valory.contracts.mech_marketplace.contract import (
    DELIVERY_RATE_INDEX,
    MechMarketplaceContract,
)

PUBLIC_ID = PublicId.from_str("valory/olas_mech:0.1.0")

_logger = logging.getLogger(
    f"aea.packages.{PUBLIC_ID.author}.contracts.{PUBLIC_ID.name}.contract"
)

# Block-identifier shapes actually used by callers: an int block number or the
# literal strings "earliest"/"latest". Web3 accepts both as-is in its filter
# dicts; a dedicated local alias keeps the public signatures readable without
# reintroducing the web3.types import.
BlockIdentifier = Union[int, str]

# eth.call has no wall-clock bound; provider retries multiply the per-request timeout.
# Fits two 10s ledger-connection request attempts, so one retry can complete.
SIMULATION_RPC_DEADLINE_SECONDS = 25.0
# Simulations allowed in flight at once, abandoned ones included.
MAX_INFLIGHT_SIMULATIONS = 4
SIMULATION_OK_KEY = "simulation_ok"
SIMULATION_TIMED_OUT_KEY = "simulation_timed_out"

_inflight_simulations = threading.BoundedSemaphore(MAX_INFLIGHT_SIMULATIONS)
# (to, data) of each simulation still running; at most one per call at a time.
_inflight_calls: Set[Tuple[str, str]] = set()
_inflight_calls_lock = threading.Lock()
_HEX_REVERT_DATA = re.compile(r"0x[0-9a-fA-F]*")
_PREFIXED_REVERT_DATA = "Reverted "


def _simulation_result(ok: bool, timed_out: bool = False) -> Dict[str, bool]:
    """Build the simulation verdict carried in contract responses.

    :param ok: whether the simulated call succeeded.
    :param timed_out: whether the outcome is inconclusive (see ``simulate_with_deadline``).
    :return: ``{SIMULATION_OK_KEY: ok, SIMULATION_TIMED_OUT_KEY: timed_out}``.
    """
    return {SIMULATION_OK_KEY: ok, SIMULATION_TIMED_OUT_KEY: timed_out}


def _is_revert(error: Exception) -> bool:
    """Return whether ``error`` is a revert reported by the node.

    web3 also raises ``ContractLogicError`` for JSON-RPC errors whose ``data``
    is a dict, ``null`` or plain text, so the class alone is not enough. A
    revert carries hex or ``Reverted``-prefixed revert data, or non-dict data
    with "revert" in the message.

    :param error: the exception raised by ``eth_call``.
    :return: ``True`` only for a revert.
    """
    if not isinstance(error, ContractLogicError):
        return False
    data = error.data
    if isinstance(data, dict):
        return False
    if isinstance(data, str) and (
        _HEX_REVERT_DATA.fullmatch(data) or data.startswith(_PREFIXED_REVERT_DATA)
    ):
        return True
    return "revert" in str(error.message or "").lower()


def simulate_with_deadline(
    ledger_api: EthereumApi,
    contract_address: str,
    sender_address: str,
    data: str,
    deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
) -> Dict[str, bool]:
    """Simulate ``data`` with ``eth_call``, returning within ``deadline_seconds``.

    Only success or a revert (see ``_is_revert``) is conclusive. Anything else
    is inconclusive (``simulation_timed_out=True``, ``simulation_ok=False``):
    the call overruns the deadline, raises any other error (transport failures,
    JSON-RPC errors such as rate limits), or does not start because the same
    call is still running or ``MAX_INFLIGHT_SIMULATIONS`` calls are.
    Calls run on daemon threads, so an abandoned one never delays process exit.

    :param ledger_api: the ledger api.
    :param contract_address: the address the simulated call is sent to.
    :param sender_address: the address the simulated call is sent from.
    :param data: the calldata to simulate, hex-encoded.
    :param deadline_seconds: wall-clock upper bound for the call, in seconds.
    :return: the verdict built by ``_simulation_result``.
    """
    call_key = (contract_address.lower(), data)
    with _inflight_calls_lock:
        if call_key in _inflight_calls:
            _logger.warning(
                "Simulation not started: an earlier simulation of the same call "
                "is still in flight; result inconclusive."
            )
            return _simulation_result(ok=False, timed_out=True)
        if not _inflight_simulations.acquire(blocking=False):
            _logger.warning(
                f"Simulation not started: {MAX_INFLIGHT_SIMULATIONS} earlier "
                f"simulations are still in flight; result inconclusive."
            )
            return _simulation_result(ok=False, timed_out=True)
        _inflight_calls.add(call_key)

    errors: List[Exception] = []
    finished = threading.Event()

    def _release() -> None:
        with _inflight_calls_lock:
            _inflight_calls.discard(call_key)
            _inflight_simulations.release()

    def _call() -> None:
        try:
            ledger_api.api.eth.call(
                {
                    "from": ledger_api.api.to_checksum_address(sender_address),
                    "to": ledger_api.api.to_checksum_address(contract_address),
                    "data": data,
                }
            )
        except Exception as e:  # pylint: disable=broad-except
            errors.append(e)
        finally:
            _release()
            finished.set()

    try:
        threading.Thread(target=_call, name="olas-mech-simulate", daemon=True).start()
    except RuntimeError as e:
        _release()
        _logger.warning(f"Simulation not started: {e}; result inconclusive.")
        return _simulation_result(ok=False, timed_out=True)
    if not finished.wait(deadline_seconds):
        _logger.warning(
            f"Simulation did not return within {deadline_seconds}s; "
            f"result inconclusive."
        )
        return _simulation_result(ok=False, timed_out=True)
    if not errors:
        return _simulation_result(ok=True)
    if _is_revert(errors[0]):
        _logger.info(f"Simulation failed: {errors[0]}")
        return _simulation_result(ok=False)
    _logger.warning(f"Simulation did not complete; result inconclusive: {errors[0]!r}")
    return _simulation_result(ok=False, timed_out=True)


PAYMENT_TYPE_NATIVE_NVM = (
    "803dd08fe79d91027fc9024e254a0942372b92f3ccabc1bd19f4a5c2b251c316"  # nosec
)
PAYMENT_TYPE_TOKEN_NVM = (
    "0d6fd99afa9c4c580fab5e341922c2a5c4b61d880da60506193d7bf88944dd14"  # nosec
)

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


TOPIC_BYTES = 32
TOPIC_CHARS = TOPIC_BYTES * 2
Ox = "0x"
Ox_CHARS = len(Ox)


class MechOperation(Enum):
    """Operation types."""

    CALL = 0
    DELEGATE_CALL = 1


# The marketplace's settlement overloads, called through the mech's ``exec``
# so that a mech deployed without these wrappers can still use them. The
# marketplace takes ``msg.sender`` as the mech, so the delivery is recorded
# against the mech that runs ``exec``.
MARKETPLACE_DELIVER_WITH_CAP_SIGNATURE = (
    "deliverMarketplaceWithSignatures("
    "address,(bytes,bytes,bytes)[],uint256[],uint256[],bytes)"
)
MARKETPLACE_DELIVER_WITH_NONCES_SIGNATURE = (
    "deliverMarketplaceWithSignatures("
    "address,(bytes,bytes,bytes)[],uint256[],uint256[],uint256[],uint256[],bytes)"
)


def _marketplace_deliver_abi(uint_array_names: List[str]) -> Dict[str, Any]:
    """ABI entry of a marketplace ``deliverMarketplaceWithSignatures`` overload."""
    inputs: List[Dict[str, Any]] = [
        {"name": "requester", "type": "address"},
        {
            "name": "deliverWithSignatures",
            "type": "tuple[]",
            "components": [
                {"name": "requestData", "type": "bytes"},
                {"name": "signature", "type": "bytes"},
                {"name": "deliveryData", "type": "bytes"},
            ],
        },
    ]
    inputs.extend({"name": name, "type": "uint256[]"} for name in uint_array_names)
    inputs.append({"name": "paymentData", "type": "bytes"})
    return {
        "name": "deliverMarketplaceWithSignatures",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": inputs,
        "outputs": [],
    }


MARKETPLACE_SETTLEMENT_ABI = [
    _marketplace_deliver_abi(["deliveryRates", "maxRates"]),
    _marketplace_deliver_abi(["deliveryRates", "maxRates", "nonces", "deadlines"]),
]


def pad_address_for_topic(address: str) -> bytes:
    """Left-pad an Ethereum address to 32 bytes for use in a topic."""
    return bytes.fromhex(address[Ox_CHARS:].zfill(TOPIC_CHARS))


class OlasMechContract(Contract):
    """The scaffold contract class for a smart contract."""

    contract_id = PublicId.from_str("valory/olas_mech:0.1.0")

    @classmethod
    def get_raw_transaction(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """
        Handler method for the 'GET_RAW_TRANSACTION' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_raw_message(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> bytes:
        """
        Handler method for the 'GET_RAW_MESSAGE' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_state(
        cls, ledger_api: LedgerApi, contract_address: str, **kwargs: Any
    ) -> JSONLike:
        """
        Handler method for the 'GET_STATE' requests.

        Implement this method in the sub class if you want
        to handle the contract requests manually.

        :param ledger_api: the ledger apis.
        :param contract_address: the contract address.
        :param kwargs: the keyword arguments.
        :return: the tx  # noqa: DAR202
        """
        raise NotImplementedError

    @classmethod
    def get_deliver_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender_address: str,
        request_id: int,
        data: str,
        request_id_nonce: Optional[int],
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """
        Deliver a response to a request.

        :param ledger_api: LedgerApi object
        :param contract_address: the address of the token to be used
        :param sender_address: the address of the sender
        :param request_id: the id of the target request
        :param data: the response data
        :param request_id_nonce: request id with nonce, to ensure uniqueness on-chain.
        :param deadline_seconds: wall-clock bound for the deliver simulation.
        :return: the deliver data
        """
        ledger_api = cast(EthereumApi, ledger_api)

        if not isinstance(ledger_api, EthereumApi):
            raise ValueError(f"Only EthereumApi is supported, got {type(ledger_api)}")

        deliver_with_nonce = [
            {
                "inputs": [
                    {"internalType": "uint256", "name": "requestId", "type": "uint256"},
                    {
                        "internalType": "uint256",
                        "name": "requestIdWithNonce",
                        "type": "uint256",
                    },
                    {"internalType": "bytes", "name": "data", "type": "bytes"},
                ],
                "name": "deliver",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]
        if request_id_nonce is not None:
            contract_instance = ledger_api.api.eth.contract(
                contract_address, abi=deliver_with_nonce
            )
            data = contract_instance.encode_abi(
                abi_element_identifier="deliver",
                args=[request_id, request_id_nonce, bytes.fromhex(data)],
            )
        else:
            contract_instance = cls.get_instance(ledger_api, contract_address)
            data = contract_instance.encode_abi(
                abi_element_identifier="deliver", args=[request_id, bytes.fromhex(data)]
            )

        simulation = simulate_with_deadline(
            ledger_api, contract_address, sender_address, data, deadline_seconds
        )
        return {"data": bytes.fromhex(data[2:]), **simulation}  # type: ignore

    @classmethod
    def get_request_events(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Get the Request events emitted by the contract."""
        ledger_api = cast(EthereumApi, ledger_api)
        all_entries = []
        for abi in partial_abis:
            contract_instance = ledger_api.api.eth.contract(contract_address, abi=abi)
            event = contract_instance.events.Request()
            entries = cls.get_event_entries(
                ledger_api=ledger_api,
                event=event,
                address=contract_instance.address,
                from_block=from_block,
                to_block=to_block,
            )

            all_entries.extend(entries)

        request_events = list(
            {
                "tx_hash": "0x" + entry["transactionHash"].hex(),
                "block_number": entry["blockNumber"],
                **entry["args"],
                "contract_address": contract_address,
            }
            for entry in all_entries
        )
        return {"data": request_events}

    @classmethod
    def get_deliver_events(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Get the Deliver events emitted by the contract."""
        ledger_api = cast(EthereumApi, ledger_api)
        all_entries = []
        for abi in partial_abis:
            contract_instance = ledger_api.api.eth.contract(contract_address, abi=abi)
            event = contract_instance.events.Deliver()
            entries = cls.get_event_entries(
                ledger_api=ledger_api,
                event=event,
                address=contract_instance.address,
                from_block=from_block,
                to_block=to_block,
            )
            all_entries.extend(entries)

        deliver_events = list(
            {
                "tx_hash": "0x" + entry["transactionHash"].hex(),
                "block_number": entry["blockNumber"],
                **entry["args"],
            }
            for entry in all_entries
        )
        return {"data": deliver_events}

    @classmethod
    def process_tx_receipt(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        tx_receipt: Dict[str, Any],
    ) -> JSONLike:
        """Process transaction receipt to filter contract events."""

        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        event, *_ = contract_instance.events.Request().processReceipt(tx_receipt)
        return dict(event["args"])

    @classmethod
    def get_undelivered_reqs(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
        max_block_window: int = 1000,
        **kwargs: Any,
    ) -> JSONLike:
        """Get the requests that are not delivered."""
        ledger_api = cast(EthereumApi, ledger_api)
        if from_block == "earliest":
            from_block = 0

        current_block = ledger_api.api.eth.block_number
        requests, delivers = [], []
        for from_block_batch in range(int(from_block), current_block, max_block_window):
            to_block_batch: Union[int, str] = (from_block_batch + max_block_window) - 1
            if isinstance(to_block_batch, int) and to_block_batch >= current_block:
                to_block_batch = "latest"
            requests_batch: List[Dict[str, Any]] = cls.get_request_events(
                ledger_api, contract_address, from_block_batch, to_block_batch
            )["data"]
            delivers_batch: List[Dict[str, Any]] = cls.get_deliver_events(
                ledger_api, contract_address, from_block_batch, to_block_batch
            )["data"]
            requests.extend(requests_batch)
            delivers.extend(delivers_batch)
        pending_tasks: List[Dict[str, Any]] = []
        for request in requests:
            if request["requestId"] not in [
                deliver["requestId"] for deliver in delivers
            ]:
                # store each requests in the pending_tasks list, make sure each req is stored once
                pending_tasks.append(request)
        return {"data": pending_tasks}

    @classmethod
    def get_multiple_undelivered_reqs(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        contract_addresses: List[str],
        from_block: BlockIdentifier = "earliest",
        max_block_window: int = 1000,
        **kwargs: Any,
    ) -> JSONLike:
        """Get the requests that are not delivered."""
        pending_tasks: List[Dict[str, Any]] = []
        for contract_address in contract_addresses:
            pending_tasks_batch = cls.get_undelivered_reqs(
                ledger_api, contract_address, from_block, max_block_window
            ).get("data")
            pending_tasks.extend(pending_tasks_batch)
        return {"data": pending_tasks}

    @classmethod
    def get_exec_tx_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        to: str,
        value: int,
        data: bytes,
        operation: int,
        tx_gas: int,
    ) -> JSONLike:
        """Get tx data"""
        ledger_api = cast(EthereumApi, ledger_api)

        if not isinstance(ledger_api, EthereumApi):
            raise ValueError(f"Only EthereumApi is supported, got {type(ledger_api)}")

        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encode_abi(
            abi_element_identifier="exec", args=[to, value, data, operation, tx_gas]
        )
        return {"data": bytes.fromhex(data[2:])}  # type: ignore

    @classmethod
    def simulate_tx(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        sender_address: str,
        data: str,
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Simulate the transaction under a wall-clock deadline.

        :param ledger_api: the ledger api.
        :param contract_address: the mech contract address.
        :param sender_address: the address the simulated call is sent from.
        :param data: the calldata to simulate, hex-encoded.
        :param deadline_seconds: wall-clock upper bound for the call, in seconds.
        :return: ``{"data": <simulation_ok>, "simulation_timed_out": <bool>}``.
        """
        result = simulate_with_deadline(
            ledger_api, contract_address, sender_address, data, deadline_seconds
        )
        return {
            "data": result[SIMULATION_OK_KEY],
            SIMULATION_TIMED_OUT_KEY: result[SIMULATION_TIMED_OUT_KEY],
        }

    @classmethod
    def get_deliver_to_market_tx(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender_address: str,
        request_id: int,
        data: str,
        mech_staking_instance: str,
        mech_service_id: int,
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Get tx data"""
        ledger_api = cast(EthereumApi, ledger_api)

        if not isinstance(ledger_api, EthereumApi):
            raise ValueError(f"Only EthereumApi is supported, got {type(ledger_api)}")

        contract_instance = cls.get_instance(ledger_api, contract_address)
        tx_data = contract_instance.encode_abi(
            abi_element_identifier="deliverToMarketplace",
            args=[
                request_id,
                bytes.fromhex(data),
                ledger_api.api.to_checksum_address(mech_staking_instance),
                mech_service_id,
            ],
        )
        simulation = simulate_with_deadline(
            ledger_api, contract_address, sender_address, tx_data, deadline_seconds
        )
        return {"data": bytes.fromhex(tx_data[2:]), **simulation}  # type: ignore

    @classmethod
    def get_offchain_deliver_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender: str,
        requester: str,
        deliverWithSignatures: List[Dict[str, List]],
        deliveryRates: List[int],
        paymentData: bytes,
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Get offchain deliver tx data"""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encode_abi(
            abi_element_identifier="deliverMarketplaceWithSignatures",
            args=[
                ledger_api.api.to_checksum_address(requester),
                deliverWithSignatures,
                deliveryRates,
                paymentData,
            ],
        )

        simulation = simulate_with_deadline(
            ledger_api, contract_address, sender, data, deadline_seconds
        )
        return {"data": bytes.fromhex(data[2:]), **simulation}  # type: ignore

    @classmethod
    def _marketplace_deliver_through_exec(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        marketplace_address: str,
        sender: str,
        overload_signature: str,
        args: List[Any],
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Encode a marketplace settlement overload wrapped in the mech's ``exec``.

        :param ledger_api: the ledger API.
        :param contract_address: the mech that runs ``exec``.
        :param marketplace_address: the marketplace the mech is registered on.
        :param sender: the mech operator (service Safe) the call is simulated from.
        :param overload_signature: the marketplace overload to call.
        :param args: the overload's arguments.
        :param deadline_seconds: wall-clock bound for the deliver simulation.
        :return: the ``exec`` calldata and the verdict built by ``_simulation_result``.
        """
        contract_instance = cls.get_instance(ledger_api, contract_address)
        marketplace = contract_instance.w3.eth.contract(abi=MARKETPLACE_SETTLEMENT_ABI)
        inner = marketplace.encode_abi(
            abi_element_identifier=overload_signature, args=args
        )
        exec_data = cls.get_exec_tx_data(
            ledger_api,
            contract_address,
            to=contract_instance.w3.to_checksum_address(marketplace_address),
            value=0,
            data=bytes.fromhex(inner[2:]),
            operation=MechOperation.CALL.value,
            tx_gas=0,
        )["data"]
        data = cast(bytes, exec_data)
        simulation = simulate_with_deadline(
            cast(EthereumApi, ledger_api),
            contract_address,
            sender,
            "0x" + data.hex(),
            deadline_seconds,
        )
        return {"data": data, **simulation}  # type: ignore

    @classmethod
    def get_offchain_deliver_data_with_cap(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        marketplace_address: str,
        sender: str,
        requester: str,
        deliverWithSignatures: List[Dict[str, List]],
        deliveryRates: List[int],
        maxRates: List[int],
        paymentData: str,
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Get ``exec`` calldata for the marketplace's 5-arg cap-and-actual deliver."""
        return cls._marketplace_deliver_through_exec(
            ledger_api,
            contract_address,
            marketplace_address,
            sender,
            MARKETPLACE_DELIVER_WITH_CAP_SIGNATURE,
            [requester, deliverWithSignatures, deliveryRates, maxRates, paymentData],
            deadline_seconds,
        )

    @classmethod
    def get_offchain_deliver_data_with_nonces(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        marketplace_address: str,
        sender: str,
        requester: str,
        deliverWithSignatures: List[Dict[str, List]],
        deliveryRates: List[int],
        maxRates: List[int],
        nonces: List[int],
        deadlines: List[int],
        paymentData: str,
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Get ``exec`` calldata for the marketplace's 7-arg explicit-nonce deliver."""
        return cls._marketplace_deliver_through_exec(
            ledger_api,
            contract_address,
            marketplace_address,
            sender,
            MARKETPLACE_DELIVER_WITH_NONCES_SIGNATURE,
            [
                requester,
                deliverWithSignatures,
                deliveryRates,
                maxRates,
                nonces,
                deadlines,
                paymentData,
            ],
            deadline_seconds,
        )

    @classmethod
    def get_is_nvm_mech(cls, ledger_api: LedgerApi, contract_address: str) -> JSONLike:
        """Get tx data"""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        payment_type_bytes = contract_instance.functions.paymentType().call()
        payment_type = payment_type_bytes.hex()

        is_nvm_mech = payment_type in [PAYMENT_TYPE_NATIVE_NVM, PAYMENT_TYPE_TOKEN_NVM]
        return {"data": is_nvm_mech}

    @classmethod
    def get_mech_type(cls, ledger_api: LedgerApi, contract_address: str) -> JSONLike:
        """Get the mech's payment type."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        payment_type_bytes = contract_instance.functions.paymentType().call()

        return {"mech_type": payment_type_bytes}

    @classmethod
    def get_mech_marketplace(
        cls, ledger_api: LedgerApi, contract_address: str
    ) -> JSONLike:
        """Get the marketplace the mech is bound to (checksummed)."""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        marketplace = contract_instance.functions.mechMarketplace().call()
        return {
            "mech_marketplace": contract_instance.w3.to_checksum_address(marketplace)
        }

    @classmethod
    def get_mech_types(
        cls, ledger_api: LedgerApi, contract_address: str, mech_addresses: Set[str]
    ) -> Dict[str, Dict[str, Any]]:
        """Get the given mechs' payment types."""
        addresses_to_types = {
            mech_address: cls.get_mech_type(ledger_api, mech_address).get("mech_type")
            for mech_address in mech_addresses
        }
        return {"mech_types": addresses_to_types}

    @classmethod
    def get_marketplace_mech_request_events(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Get the Request events emitted by the contract."""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        event = contract_instance.events.Request()
        entries = cls.get_event_entries(
            ledger_api=ledger_api,
            from_block=from_block,
            to_block=to_block,
            event=event,
            address=contract_instance.address,
        )

        request_events = list(
            {
                "tx_hash": "0x" + entry["transactionHash"].hex(),
                "block_number": entry["blockNumber"],
                **entry["args"],
                "contract_address": contract_address,
            }
            for entry in entries
        )
        return {"data": request_events}

    @classmethod
    def get_marketplace_mech_deliver_events(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> JSONLike:
        """Get the Deliver events emitted by the contract."""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        event = contract_instance.events.Deliver()
        entries = cls.get_event_entries(
            ledger_api=ledger_api,
            event=event,
            address=contract_instance.address,
            from_block=from_block,
            to_block=to_block,
        )

        deliver_events = list(
            {
                "tx_hash": "0x" + entry["transactionHash"].hex(),
                "block_number": entry["blockNumber"],
                **entry["args"],
                "contract_address": contract_address,
            }
            for entry in entries
        )
        return {"data": deliver_events}

    @classmethod
    def get_marketplace_undelivered_reqs(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        marketplace_address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
        max_block_window: int = 1000,
        **kwargs: Any,
    ) -> JSONLike:
        """Get the requests that are not delivered."""
        ledger_api = cast(EthereumApi, ledger_api)
        if from_block == "earliest":
            from_block = 0

        current_block = ledger_api.api.eth.block_number
        checksumed_contract_address = ledger_api.api.to_checksum_address(
            contract_address
        )
        requests, delivers = [], []
        for from_block_batch in range(int(from_block), current_block, max_block_window):
            to_block_batch: Union[int, str] = (from_block_batch + max_block_window) - 1
            if isinstance(to_block_batch, int) and to_block_batch >= current_block:
                to_block_batch = "latest"
            requests_batch: List[Dict[str, Any]] = (
                cls.get_marketplace_mech_request_events(
                    ledger_api,
                    checksumed_contract_address,
                    from_block_batch,
                    to_block_batch,
                )["data"]
            )
            delivers_batch: List[Dict[str, Any]] = (
                cls.get_marketplace_mech_deliver_events(
                    ledger_api,
                    checksumed_contract_address,
                    from_block_batch,
                    to_block_batch,
                )["data"]
            )
            requests.extend(requests_batch)
            delivers.extend(delivers_batch)
        pending_tasks: List[Dict[str, Any]] = []
        for request in requests:
            if request["requestId"] not in [
                deliver["requestId"] for deliver in delivers
            ]:
                # fetch and store max delivery rate for each request id
                request_id_info = MechMarketplaceContract.get_request_id_info(
                    ledger_api, marketplace_address, request["requestId"]
                )
                request["request_delivery_rate"] = request_id_info["data"][
                    DELIVERY_RATE_INDEX
                ]
                # store each requests in the pending_tasks list, make sure each req is stored once
                pending_tasks.append(request)

        return {"data": pending_tasks}

    @classmethod
    def get_marketplace_deliver_data(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        sender: str,
        requestIds: List,
        datas: List,
        deadline_seconds: float = SIMULATION_RPC_DEADLINE_SECONDS,
    ) -> JSONLike:
        """Get tx data"""
        ledger_api = cast(EthereumApi, ledger_api)
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encode_abi(
            abi_element_identifier="deliverToMarketplace",
            args=[
                requestIds,
                datas,
            ],
        )

        simulation = simulate_with_deadline(
            ledger_api, contract_address, sender, data, deadline_seconds
        )
        return {"data": bytes.fromhex(data[2:]), **simulation}  # type: ignore

    @classmethod
    def get_delivery_rate(
        cls, ledger_api: LedgerApi, contract_address: str
    ) -> JSONLike:
        """Get tx data"""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        max_delivery_rate = contract_instance.functions.maxDeliveryRate().call()

        return {"data": max_delivery_rate}

    @classmethod
    def get_set_delivery_rate_tx_data(
        cls,
        ledger_api: EthereumApi,
        contract_address: str,
        new_max_delivery_rate: int,
    ) -> JSONLike:
        """Get tx data"""
        contract_instance = cls.get_instance(ledger_api, contract_address)
        data = contract_instance.encode_abi(
            abi_element_identifier="changeMaxDeliveryRate",
            args=[new_max_delivery_rate],
        )
        return {"data": bytes.fromhex(data[2:])}  # type: ignore

    @classmethod
    def get_event_entries(
        cls,
        ledger_api: EthereumApi,
        event: Any,
        address: str,
        from_block: BlockIdentifier = "earliest",
        to_block: BlockIdentifier = "latest",
    ) -> List:
        """Helper method to extract the events.

        :param ledger_api: the ledger API object
        :param event: a ``ContractEvent`` instance (e.g.
            ``contract_instance.events.Request()``)
        :param address: the contract address whose logs to scan
        :param from_block: from which block to start the search
        :param to_block: at which block to end the search
        :return: the parsed event entries
        """
        filter_params: Dict[str, Any] = {
            "fromBlock": from_block,
            "toBlock": to_block,
            "address": address,
            "topics": [event.topic],
        }
        logs = ledger_api.api.eth.get_logs(filter_params)
        return [event.process_log(log) for log in logs]
