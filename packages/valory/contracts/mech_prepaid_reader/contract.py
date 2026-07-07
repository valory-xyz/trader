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

"""Trader-local reader for BalanceTracker ``Deposit`` events.

The vendored ``valory/balance_tracker`` contract package is third-party
(pinned to ``mech-interact``) and therefore not modified in trader. This
package sits alongside it with the same ABI and adds one helper
(:py:meth:`MechPrepaidReaderContract.get_deposit_events_for_requester`)
used by ``agent_performance_summary_abci`` to sum pre-deposits per Safe
under the pre-deposit-as-loss ROI rule.
"""

import logging
from typing import Any, Dict, Union, cast

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi
from aea_ledger_ethereum import EthereumApi

PUBLIC_ID = PublicId.from_str("valory/mech_prepaid_reader:0.1.0")

_logger = logging.getLogger(
    f"aea.packages.{PUBLIC_ID.author}.contracts.{PUBLIC_ID.name}.contract"
)


class MechPrepaidReaderContract(Contract):
    """Read ``Deposit`` events on a BalanceTracker for one requester Safe."""

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
        """Sum ``Deposit(account, token, amount)`` events for one requester.

        Under pre-deposit-as-loss ROI accounting, every top-up to a Safe's
        ``mapRequesterBalances`` in the mech marketplace's BalanceTracker is
        booked as spent the moment it lands on chain — the tracker exposes
        no requester-withdraw path, so committed funds are unrecoverable
        regardless of consumption. This helper reads new ``Deposit`` events
        for one requester Safe and returns the cumulative sum plus the
        highest block scanned so the caller can persist the checkpoint and
        scan incrementally next cycle.

        :param ledger_api: the ledger API object.
        :param contract_address: the BalanceTracker contract address.
        :param requester: the Safe address to filter ``Deposit`` events by.
        :param from_block: block from which to scan; exclusive of the
            previous run so the caller must persist ``latest_block + 1``
            (or ``latest_block`` unchanged when the current run found
            nothing new — the caller can detect this by comparing the
            returned value with the input).
        :param to_block: block at which to stop scanning; defaults to
            ``latest``.
        :return: ``{"total_wei": int, "latest_block": int}``.
            ``latest_block`` equals ``from_block`` when no new deposits
            landed, so the caller can safely persist it as the checkpoint
            without moving backward.
        """
        contract_address = ledger_api.api.to_checksum_address(contract_address)
        ledger_api = cast(EthereumApi, ledger_api)

        contract_instance = cls.get_instance(ledger_api, contract_address)
        deposit_event = contract_instance.events.Deposit()

        filter_params: Dict[str, Any] = {
            "fromBlock": from_block,
            "toBlock": to_block,
            "address": contract_instance.address,
            "topics": [
                deposit_event.topic,
                # ``account`` is the first indexed arg on
                # ``Deposit(address indexed account, address indexed token, uint256 amount)``.
                # 32-byte pad the requester address to match indexed-topic encoding.
                "0x" + requester[2:].lower().rjust(64, "0"),
            ],
        }

        logs = ledger_api.api.eth.get_logs(filter_params)
        total_wei = 0
        latest_block = from_block
        for log in logs:
            entry = deposit_event.process_log(log)
            total_wei += int(entry["args"]["amount"])
            block_number = int(log["blockNumber"])
            if block_number > latest_block:
                latest_block = block_number

        return {"total_wei": total_wei, "latest_block": latest_block}
