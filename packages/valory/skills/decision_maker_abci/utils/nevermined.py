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
from typing import Dict, Any

import requests


def zero_x_transformer(input_str: str, zero_output: bool = True) -> str:
    """Transform a string to a hex string."""
    match = re.match(r'^(?:0x)*([a-f0-9]+)$', input_str, re.IGNORECASE)
    valid = match is not None
    output = match.group(1) if valid else ''

    return ('0x' if zero_output and valid else '') + output


def generate_id(length: int = 64) -> str:
    """Generate a random ID."""
    generated_id = ''
    while len(generated_id) < length:
        generated_id += str(uuid.uuid4()).replace('-', '')

    return generated_id[:length]


def find_service_by_type(did_doc: Dict[str, Any], type: str) -> Dict[str, Any]:
    """Find a service by name."""
    services = did_doc.get('service', [])
    for service in services:
        if service.get('type') == type:
            return service

    raise Exception(f'No service found with type {type}')


def find_service_condition_by_name(service: Dict[str, Any], name: str):
    conditions = service.get('attributes', {}).get('serviceAgreementTemplate', {}).get('conditions', [])

    condition = next((c for c in conditions if c['name'] == name), None)

    if condition is None:
        raise Exception(f"Condition '{name}' not found.")

    return condition

def get_asset_price_from_service(service: Dict[str, Any]) -> Dict[str, int]:
    """Get the price of a DID."""
    escrow_payment_condition = find_service_condition_by_name(service, 'escrowPayment')

    if not escrow_payment_condition:
        raise Exception('escrowPayment not found in service')

    amounts = next((p['value'] for p in escrow_payment_condition.get('parameters', []) if p['name'] == '_amounts'), [])
    receivers = next((p['value'] for p in escrow_payment_condition.get('parameters', []) if p['name'] == '_receivers'), [])

    rewards_map = dict(zip(receivers, map(int, amounts)))

    return rewards_map

def get_price(did_doc: Dict[str, Any], type: str = 'nft-sales') -> Dict[str, int]:
    """Get the price of a DID."""
    service = find_service_by_type(did_doc, type)
    return get_asset_price_from_service(service)


def get_nft_address(did_doc: Dict[str, Any], type: str = 'nft-sales') -> str:
    """Get the NFT address of a DID."""
    service = find_service_by_type(did_doc, type)
    transfer_condition = find_service_condition_by_name(service, 'transferNFT')
    contract_param = next((p['value'] for p in transfer_condition.get('parameters', []) if p['name'] == '_contractAddress' or p['name'] == '_contract'), None)

    return contract_param if contract_param is not None else ''


def no_did_prefixed(input_string: str) -> str:
    """Remove the DID prefix from a string."""
    return did_transformer(input_string, False)


def did_transformer(input_string: str, prefix_output: bool = False) -> str:
    """Transform a string to a DID."""
    pattern = re.compile(r'^(?:0x|did:nv:)*([a-f0-9]{64})$', re.IGNORECASE)
    match_result = input_match(input_string, pattern, 'did_transformer')

    valid, output = match_result['valid'], match_result['output']

    return ('did:nv:' if prefix_output and valid else '') + output


def input_match(input_string, pattern, function_name):
    match_result = re.match(pattern, input_string)
    if match_result:
        return {'valid': True, 'output': match_result.group(1)}
    else:
        return {'valid': False, 'output': ''}

# TODO: remove
res = requests.get('https://marketplace-api.gnosis.nevermined.app/api/v1/metadata/assets/ddo/did:nv:416e35cb209ecbfbf23e1192557b06e94c5d9a9afb025cce2e9baff23e907195')
did_doc = res.json()
print(get_nft_address(did_doc))