# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains the behaviour for the decision-making of the skill."""

import re
import uuid
from typing import Any, Dict, List, Tuple

from eth_abi import encode
from web3 import Web3


def zero_x_transformer(input_str: str, zero_output: bool = True) -> str:
    """Transform a string to a hex string."""
    match = re.match(r"^(?:0x)*([a-f0-9]+)$", input_str, re.IGNORECASE)
    valid = match is not None
    output = match.group(1) if valid else ""  # type: ignore

    return ("0x" if zero_output and valid else "") + output


def generate_id(length: int = 64) -> str:
    """Generate a random ID."""
    generated_id = ""
    while len(generated_id) < length:
        generated_id += str(uuid.uuid4()).replace("-", "")

    return generated_id[:length]


def find_service_by_type(did_doc: Dict[str, Any], type: str) -> Dict[str, Any]:
    """Find a service by name."""
    services = did_doc.get("service", [])
    for service in services:
        if service.get("type") == type:
            return service

    raise Exception(f"No service found with type {type}")


def find_service_condition_by_name(
    service: Dict[str, Any], name: str
) -> Dict[str, Any]:
    """Find a condition by name."""
    conditions = (
        service.get("attributes", {})
        .get("serviceAgreementTemplate", {})
        .get("conditions", [])
    )

    condition = next((c for c in conditions if c["name"] == name), None)

    if condition is None:
        raise Exception(f"Condition '{name!r}' not found.")

    return condition


def get_asset_price_from_service(service: Dict[str, Any]) -> Dict[str, int]:
    """Get the price of a DID."""
    escrow_payment_condition = find_service_condition_by_name(service, "escrowPayment")

    if not escrow_payment_condition:
        raise Exception("escrowPayment not found in service")

    amounts: List = next(
        (
            p["value"]
            for p in escrow_payment_condition.get("parameters", [])
            if p["name"] == "_amounts"
        ),
        [],
    )
    receivers: List = next(
        (
            p["value"]
            for p in escrow_payment_condition.get("parameters", [])
            if p["name"] == "_receivers"
        ),
        [],
    )

    rewards_map = dict(zip(receivers, map(int, amounts)))

    return rewards_map


def get_price(did_doc: Dict[str, Any], type: str = "nft-sales") -> Dict[str, int]:
    """Get the price of a DID."""
    service = find_service_by_type(did_doc, type)
    return get_asset_price_from_service(service)


def get_nft_address(did_doc: Dict[str, Any], type: str = "nft-sales") -> str:
    """Get the NFT address of a DID."""
    service = find_service_by_type(did_doc, type)
    transfer_condition = find_service_condition_by_name(service, "transferNFT")
    contract_param = next(
        (
            p["value"]
            for p in transfer_condition.get("parameters", [])
            if p["name"] == "_contractAddress" or p["name"] == "_contract"
        ),
        None,
    )

    return contract_param if contract_param is not None else ""


def get_nft_holder(did_doc: Dict[str, Any], type: str = "nft-sales") -> str:
    """Get the NFT holder of a DID."""
    service = find_service_by_type(did_doc, type)
    transfer_condition = find_service_condition_by_name(service, "transferNFT")
    contract_param = next(
        (
            p["value"]
            for p in transfer_condition.get("parameters", [])
            if p["name"] == "_nftHolder"
        ),
        None,
    )

    return contract_param if contract_param is not None else ""


def get_nft_transfer(did_doc: Dict[str, Any], type: str = "nft-sales") -> str:
    """Get the NFT holder of a DID."""
    service = find_service_by_type(did_doc, type)
    transfer_condition = find_service_condition_by_name(service, "transferNFT")
    contract_param = next(
        (
            p["value"]
            for p in transfer_condition.get("parameters", [])
            if p["name"] == "_nftTransfer"
        ),
        None,
    )

    return contract_param if contract_param is not None else ""


def no_did_prefixed(input_string: str) -> str:
    """Remove the DID prefix from a string."""
    return did_transformer(input_string, False)


def did_transformer(input_string: str, prefix_output: bool = False) -> str:
    """Transform a string to a DID."""
    pattern = re.compile(r"^(?:0x|did:nv:)*([a-f0-9]{64})$", re.IGNORECASE)
    match_result = input_match(input_string, pattern)

    valid, output = match_result["valid"], match_result["output"]

    return ("did:nv:" if prefix_output and valid else "") + output


def input_match(input_string: str, pattern: re.Pattern[str]) -> Dict[str, Any]:
    """Match an input string with a pattern."""
    match_result = re.match(pattern, input_string)
    if match_result:
        return {"valid": True, "output": match_result.group(1)}
    else:
        return {"valid": False, "output": ""}


def hash_data(
    types: List[str],
    values: List[Any],
) -> str:
    """Hash data."""
    encoded_data = encode(types, values)
    return Web3.keccak(encoded_data).hex()


def short_id(did: str) -> str:
    """Get the short ID of a DID."""
    return did.replace("did:nv:", "")


def get_agreement_id(seed: str, creator: str) -> str:
    """Get the agreement ID."""
    seed_0x = zero_x_transformer(seed)
    creator_0x = Web3.to_checksum_address(creator)
    return hash_data(["bytes32", "address"], [bytes.fromhex(seed_0x[2:]), creator_0x])


def get_lock_payment_seed(
    agreement_id: str,
    did_doc: Dict[str, Any],
    lock_payment_condition_address: str,
    escrow_payment_condition_address: str,
    token_address: str,
    amounts: List[int],
    receivers: List[str],
) -> Tuple[str, str]:
    """Get the lock payment seed."""
    short_id_ = zero_x_transformer(short_id(did_doc["id"]))
    escrow_payment_condition_address_0x = zero_x_transformer(
        escrow_payment_condition_address
    )
    token_address = Web3.to_checksum_address(token_address)
    receivers = [Web3.to_checksum_address(receiver) for receiver in receivers]

    hash_values = hash_data(
        ["bytes32", "address", "address", "uint256[]", "address[]"],
        [
            bytes.fromhex(short_id_[2:]),
            escrow_payment_condition_address_0x,
            token_address,
            amounts,
            receivers,
        ],
    )
    return hash_values, hash_data(
        ["bytes32", "address", "bytes32"],
        [
            bytes.fromhex(agreement_id[2:]),
            lock_payment_condition_address,
            bytes.fromhex(hash_values[2:]),
        ],
    )


def get_transfer_nft_condition_seed(
    agreement_id: str,
    did_doc: Dict[str, Any],
    buyer_address: str,
    nft_amount: int,
    transfer_nft_condition_address: str,
    lock_condition_id: str,
    nft_contract_address: str,
    expiration: int = 0,
) -> Tuple[str, str]:
    """Get the lock payment seed."""
    short_id_ = zero_x_transformer(short_id(did_doc["id"]))
    nft_holder = Web3.to_checksum_address(get_nft_holder(did_doc))
    will_transfer = get_nft_transfer(did_doc) == "true"

    hash_values = hash_data(
        ["bytes32", "address", "address", "uint256", "bytes32", "address", "bool"],
        [
            bytes.fromhex(short_id_[2:]),
            nft_holder,
            Web3.to_checksum_address(buyer_address),
            nft_amount,
            bytes.fromhex(lock_condition_id[2:]),
            Web3.to_checksum_address(nft_contract_address),
            will_transfer,
        ],
    )

    return hash_values, hash_data(
        ["bytes32", "address", "bytes32"],
        [
            bytes.fromhex(agreement_id[2:]),
            transfer_nft_condition_address,
            bytes.fromhex(hash_values[2:]),
        ],
    )


def get_escrow_payment_seed(
    agreement_id: str,
    did_doc: Dict[str, Any],
    amounts: List[int],
    receivers: List[str],
    buyer_address: str,
    escrow_payment_condition_address: str,
    token_address: str,
    lock_seed: str,
    access_seed: str,
) -> Tuple[str, str]:
    """Get the escrow payment seed."""
    short_id_ = zero_x_transformer(short_id(did_doc["id"]))
    escrow_payment_condition_address = Web3.to_checksum_address(
        escrow_payment_condition_address
    )
    receivers = [Web3.to_checksum_address(receiver) for receiver in receivers]
    buyer_address = Web3.to_checksum_address(buyer_address)
    token_address = Web3.to_checksum_address(token_address)

    values_hash = hash_data(
        [
            "bytes32",
            "uint256[]",
            "address[]",
            "address",
            "address",
            "address",
            "bytes32",
            "bytes32[]",
        ],
        [
            bytes.fromhex(short_id_[2:]),
            amounts,
            receivers,
            buyer_address,
            escrow_payment_condition_address,
            token_address,
            bytes.fromhex(lock_seed[2:]),
            [bytes.fromhex(access_seed[2:])],
        ],
    )

    return values_hash, hash_data(
        ["bytes32", "address", "bytes32"],
        [
            bytes.fromhex(agreement_id[2:]),
            escrow_payment_condition_address,
            bytes.fromhex(values_hash[2:]),
        ],
    )


def get_timeouts_and_timelocks(did_doc: Dict[str, Any]) -> Tuple[List[int], List[int]]:
    """Get timeouts and timelocks"""
    type = "nft-sales"
    service = find_service_by_type(did_doc, type)
    conditions = (
        service.get("attributes", {})
        .get("serviceAgreementTemplate", {})
        .get("conditions", [])
    )
    timeouts, timelocks = [], []
    for condition in conditions:
        timeouts.append(condition.get("timeout", 0))
        timelocks.append(condition.get("timelock", 0))

    return timeouts, timelocks


def get_reward_address(did_doc: Dict[str, Any], type: str = "nft-sales") -> str:
    """Get the reward address of a DID."""
    service = find_service_by_type(did_doc, type)
    transfer_condition = find_service_condition_by_name(service, "lockPayment")
    contract_param = next(
        (
            p["value"]
            for p in transfer_condition.get("parameters", [])
            if p["name"] == "_rewardAddress"
        ),
        None,
    )

    return contract_param if contract_param is not None else ""


def get_creator(did_doc: Dict[str, Any]) -> str:
    """Get the creator of a DID."""
    return did_doc["proof"]["creator"]


def get_claim_endpoint(did_doc: Dict[str, Any]) -> str:
    """Get the claim endpoint of a DID."""
    service = find_service_by_type(did_doc, "nft-sales")
    return service["serviceEndpoint"]
