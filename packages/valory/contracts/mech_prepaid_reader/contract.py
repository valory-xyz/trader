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

"""Trader-local reader for BalanceTracker ``Deposit`` events.

Exists as a distinct package so trader's pre-deposit-as-loss ROI
accounting can attach an ``eth_getLogs`` classmethod without editing
the third_party ``valory/balance_tracker`` contract package. Editing
that package in place would ripple into ``mech_interact_abci``'s
declared ``contracts:`` dependency list and force a locally-computed
hash for ``mech_interact_abci`` itself (a third_party skill, synced
via ``autonomy packages sync --source valory-xyz/mech-interact``).
That hash would never be published to IPFS, so CI's package sync would
hang trying to fetch it.

When the reader classmethod gets ported upstream into
``valory-xyz/mech-interact``'s vendored ``balance_tracker`` (which is
where ``Makefile:135`` actually syncs this package from), cut a
``mech-interact`` release, bump ``upstream_pins`` in trader's
``pyproject.toml``, and drop this package.
"""

from typing import Any, Dict, Union, cast

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/mech_prepaid_reader:0.1.0")


class MechPrepaidReaderContract(Contract):
    """Read ``Deposit(account, token, amount)`` events from a BalanceTracker.

    Not a general-purpose BalanceTracker binding: the shipped ABI
    fragment (``build/MechPrepaidReader.json``) carries only the
    ``Deposit`` event. Everything else the operator needs to interact
    with a BalanceTracker lives in the upstream ``valory/balance_tracker``
    contract package.
    """

    contract_id = PublicId.from_str("valory/mech_prepaid_reader:0.1.0")

    @classmethod
    def get_deposit_events_for_requester(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        requester: str,
        from_block: int,
        to_block: Union[int, str] = "latest",
    ) -> JSONLike:
        """Return decoded ``Deposit`` events for one requester.

        Filters ``Deposit(address indexed account, address indexed token,
        uint256 amount)`` by ``account == requester`` over
        ``[from_block, to_block]`` inclusive. Only the two fields the
        pre-deposit-as-loss caller in
        ``agent_performance_summary_abci`` reads (``amount``,
        ``block_number``) are surfaced, as plain-Python ints. Aggregation
        (summing amounts, tracking the latest matched block) is
        deliberately left to that caller.

        :param ledger_api: Ethereum ledger API to issue the log filter through.
        :param contract_address: BalanceTracker address on the target chain.
        :param requester: requester address whose deposits should be pulled;
            gets left-padded to the 32-byte indexed topic on the wire.
        :param from_block: inclusive lower bound on the log filter range.
        :param to_block: inclusive upper bound; ``"latest"`` at the current
            head by default.
        :return: ``{"entries": [{"amount": int, "block_number": int}, ...]}``.
            Plain dicts and primitives so the response survives
            ``ContractApiMessage.encode()`` at any transport boundary.
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
        # Flatten to plain-dict entries. ``event.process_log`` returns a
        # web3 ``AttributeDict`` with nested ``HexBytes`` in
        # ``transactionHash`` / ``blockHash``, which violates the
        # ``JSONLike`` contract and would raise
        # ``NotImplementedError: DictProtobufStructSerializer doesn't
        # support dict value type <class 'web3.datastructures.AttributeDict'>``
        # if ``ContractApiMessage(STATE, ...).encode()`` were ever called
        # over a real wire boundary. It only works today because the
        # ledger connection dispatches this callable in-process and the
        # caller pulls the two int fields it needs. Fold to primitives
        # here so the response is protobuf-safe regardless of transport.
        entries = []
        for log in logs:
            decoded = event.process_log(log)
            entries.append(
                {
                    "amount": int(decoded["args"]["amount"]),
                    "block_number": int(log["blockNumber"]),
                }
            )
        return {"entries": entries}
