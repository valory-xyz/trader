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

"""Shared addresses, expectations and decoding for the Polymarket approval tests.

Every calldata check decodes the ABI words independently (selector plus two
32-byte words) instead of reusing the encoders under test. The expected
approval sets are declared as tables of address param names, so a test states
which approvals it expects without rebuilding them the way the code does.
"""

import random
from typing import Any, Dict, List, Sequence, Tuple

from web3 import Web3

# Polygon addresses from https://docs.polymarket.com/resources/contracts
PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
CTF_COLLATERAL_ADAPTER = "0xAdA100Db00Ca00073811820692005400218FcE1f"
NEG_RISK_CTF_COLLATERAL_ADAPTER = "0xadA2005600Dec949baf300f4C6120000bDB6eAab"
EXCHANGE_V3 = "0xe3333700cA9d93003F00f0F71f8515005F6c00Aa"
POSITION_MANAGER = "0x006F54F7f9A22e0000CC2AB60031000000ae9fEF"
ROUTER = "0x12121212006e4CD160D18e3f00711DA5c3372600"
AUTO_REDEEMER = "0xa1200000d0002264C9a1698e001292D00E1b00af"

MAX_UINT256 = 2**256 - 1
APPROVE = "095ea7b3"  # approve(address,uint256)
SET_APPROVAL_FOR_ALL = "a22cb465"  # setApprovalForAll(address,bool)

# A decoded call: (target, selector, address argument, uint argument, value).
Call = Tuple[str, str, str, int, str]

# An expected approval: (target param, selector, argument param, uint argument).
Expectation = Tuple[str, str, str, int]

_PUSD_PARAM = "polymarket_collateral_address"
_CTF_PARAM = "polymarket_ctf_address"
_EXCHANGE_PARAM = "polymarket_ctf_exchange_address"
_NEG_RISK_EXCHANGE_PARAM = "polymarket_neg_risk_ctf_exchange_address"
_EXCHANGE_V3_PARAM = "polymarket_exchange_v3_address"
_POSITION_MANAGER_PARAM = "polymarket_position_manager_address"

# DepositWallet approvals for the V1 exchanges, kept in the full batch.
DW_V1_APPROVALS: Tuple[Expectation, ...] = (
    (_PUSD_PARAM, APPROVE, _EXCHANGE_PARAM, MAX_UINT256),
    (_PUSD_PARAM, APPROVE, _NEG_RISK_EXCHANGE_PARAM, MAX_UINT256),
    (_CTF_PARAM, SET_APPROVAL_FOR_ALL, _EXCHANGE_PARAM, 1),
    (_CTF_PARAM, SET_APPROVAL_FOR_ALL, _NEG_RISK_EXCHANGE_PARAM, 1),
)

# The two Protocol V2 DepositWallet approvals.
DW_V2_APPROVALS: Tuple[Expectation, ...] = (
    (_PUSD_PARAM, APPROVE, _EXCHANGE_V3_PARAM, MAX_UINT256),
    (_POSITION_MANAGER_PARAM, SET_APPROVAL_FOR_ALL, _EXCHANGE_V3_PARAM, 1),
)

# The Safe approvals that predate Protocol V2, in their multisend order.
SAFE_EXISTING_APPROVALS: Tuple[Expectation, ...] = (
    (_PUSD_PARAM, APPROVE, _EXCHANGE_PARAM, MAX_UINT256),
    (_CTF_PARAM, SET_APPROVAL_FOR_ALL, _EXCHANGE_PARAM, 1),
    (_PUSD_PARAM, APPROVE, _NEG_RISK_EXCHANGE_PARAM, MAX_UINT256),
    (_CTF_PARAM, SET_APPROVAL_FOR_ALL, _NEG_RISK_EXCHANGE_PARAM, 1),
    (_PUSD_PARAM, APPROVE, "polymarket_neg_risk_adapter_address", MAX_UINT256),
    (_CTF_PARAM, SET_APPROVAL_FOR_ALL, "polymarket_neg_risk_adapter_address", 1),
    (
        _CTF_PARAM,
        SET_APPROVAL_FOR_ALL,
        "polymarket_ctf_collateral_adapter_address",
        1,
    ),
    (
        _CTF_PARAM,
        SET_APPROVAL_FOR_ALL,
        "polymarket_neg_risk_ctf_collateral_adapter_address",
        1,
    ),
)

# The Safe's PositionManager ``setApprovalForAll(Router, true)``.
SAFE_ROUTER_APPROVAL: Expectation = (
    _POSITION_MANAGER_PARAM,
    SET_APPROVAL_FOR_ALL,
    "polymarket_router_address",
    1,
)


def docs_addresses() -> Dict[str, str]:
    """Return the address params set to the documented Polygon addresses.

    :return: a mapping of address param name to address.
    """
    return {
        _PUSD_PARAM: PUSD,
        _CTF_PARAM: CTF,
        _EXCHANGE_PARAM: CTF_EXCHANGE,
        _NEG_RISK_EXCHANGE_PARAM: NEG_RISK_CTF_EXCHANGE,
        "polymarket_neg_risk_adapter_address": NEG_RISK_ADAPTER,
        "polymarket_ctf_collateral_adapter_address": CTF_COLLATERAL_ADAPTER,
        "polymarket_neg_risk_ctf_collateral_adapter_address": (
            NEG_RISK_CTF_COLLATERAL_ADAPTER
        ),
        _EXCHANGE_V3_PARAM: EXCHANGE_V3,
        _POSITION_MANAGER_PARAM: POSITION_MANAGER,
        "polymarket_router_address": ROUTER,
    }


def distinct_addresses() -> Dict[str, str]:
    """Return the address params set to fixed addresses unlike the documented ones.

    :return: a mapping of address param name to address.
    """
    return {
        name: Web3.to_checksum_address("0x" + f"{0x10 + 0x11 * index:02x}" * 20)
        for index, name in enumerate(docs_addresses())
    }


def random_addresses(rng: random.Random) -> Dict[str, str]:
    """Return the address params set to distinct random checksum addresses.

    :param rng: the seeded random generator.
    :return: a mapping of address param name to a random address.
    """
    seen: set = set()
    out: Dict[str, str] = {}
    for name in docs_addresses():
        address = Web3.to_checksum_address(f"0x{rng.getrandbits(160):040x}")
        while address in seen:
            address = Web3.to_checksum_address(f"0x{rng.getrandbits(160):040x}")
        seen.add(address)
        out[name] = address
    return out


def expected_calls(
    expectations: Sequence[Expectation], addresses: Dict[str, str]
) -> List[Call]:
    """Resolve expected approvals against ``addresses``.

    :param expectations: the expected approvals, by address param name.
    :param addresses: the address params.
    :return: the expected decoded calls, each with no native value.
    """
    return [
        (addresses[target], selector, addresses[argument], amount, "0")
        for target, selector, argument, amount in expectations
    ]


def _to_bytes(data: Any) -> bytes:
    """Coerce 0x-hex text or bytes calldata to bytes.

    :param data: the calldata.
    :return: the calldata bytes.
    """
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    text = str(data)
    return bytes.fromhex(text[2:] if text.startswith("0x") else text)


def decode(target: str, data: Any, value: Any) -> Call:
    """Decode an approve / setApprovalForAll call from its ABI words.

    :param target: the call target.
    :param data: the calldata.
    :param value: the native value sent with the call.
    :return: the decoded call.
    """
    raw = _to_bytes(data)
    assert len(raw) == 4 + 32 + 32, f"unexpected calldata length {len(raw)}"
    address_word, uint_word = raw[4:36], raw[36:68]
    assert address_word[:12] == bytes(12), "address word is not left-padded"
    return (
        Web3.to_checksum_address(target),
        raw[:4].hex(),
        Web3.to_checksum_address("0x" + address_word[12:].hex()),
        int.from_bytes(uint_word, "big"),
        str(value),
    )


def decode_dw_calls(calls: List[Dict[str, Any]]) -> List[Call]:
    """Decode the ``{"to", "data", "value"}`` calls of a DepositWallet batch.

    :param calls: the batch calls.
    :return: the decoded calls.
    """
    return [decode(c["to"], c["data"], c["value"]) for c in calls]


def addresses_in(calls: List[Call]) -> List[str]:
    """Return every address that appears in ``calls`` as target or argument.

    :param calls: the decoded calls.
    :return: the addresses.
    """
    return [c[0] for c in calls] + [c[2] for c in calls]
