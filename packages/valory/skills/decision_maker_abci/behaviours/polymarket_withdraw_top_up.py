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

"""This module contains the Polymarket (CLOB v2) DepositWallet withdrawal top-up behaviour."""

from typing import Generator, List, Optional, Tuple

from eth_abi import encode
from eth_utils import keccak, to_checksum_address  # type: ignore[import-not-found]
from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import MultisendBatch
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    PolymarketDepositWalletBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketTopUpPayload
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_withdraw_top_up import (
    PolymarketWithdrawTopUpRound,
)

# CTF ERC-1155 positions are 6-decimal fixed-point (mirrors USDC/pUSD), so a
# human ``size`` of 1.0 share is 1_000_000 base units.
CTF_DECIMAL_FACTOR = 10**6
# Matches the withdrawal sell-loop's dust floor (polymarket_withdraw.DUST_EPSILON):
# don't move a position Safe→DW that the loop would then refuse to sell, leaving
# it stranded in the DW.
DUST_EPSILON = 1e-2
SAFE_BATCH_TRANSFER_SELECTOR = keccak(
    text="safeBatchTransferFrom(address,address,uint256[],uint256[],bytes)"
)[:4]


class PolymarketWithdrawTopUpBehaviour(PolymarketDepositWalletBehaviour):
    """Moves all sellable CTF positions from the Safe to the DepositWallet.

    Runs once before the withdrawal sell-loop. Fetches the unredeemable
    positions, resolves the DepositWallet, and builds a single Safe multisend
    ``safeBatchTransferFrom`` moving every sellable CTF position to the DW so
    the loop's DW-funded FAK sells have the shares to sell. When nothing is
    sellable the round short-circuits to ``WITHDRAWAL_DONE``.
    """

    matching_round = PolymarketWithdrawTopUpRound

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._prepare_withdraw_top_up()

        yield from self.finish_behaviour(self.payload)

    def _fetch_sellable(
        self,
    ) -> Generator[None, None, Optional[List[Tuple[int, int]]]]:
        """Fetch unredeemable positions and return ``(token_id, amount)`` pairs.

        :yield: framework yields between dispatch and the connection response.
        :return: list of ``(token_id_int, amount_base_units)`` for sellable
            positions, or ``None`` on a fetch error.
        """
        # Query the Safe (the connection default): this runs BEFORE the top-up
        # moves anything, so the sellable CTF is still held by the Safe. (The
        # round is only re-entered on a pre-PREPARE_TX failure — never after the
        # Safe→DW batch settles — so the holder is always the Safe here. The
        # post-move DW query lives in the sell-loop's _request_fetch_positions.)
        response = yield from self._send_polymarket_request(
            RequestType.FETCH_ALL_POSITIONS, {"redeemable": False}
        )
        if response is None or isinstance(response, dict):
            return None

        sellable: List[Tuple[int, int]] = []
        for position in response:
            asset = position.get("asset")
            try:
                size = float(position.get("size") or 0.0)
            except (TypeError, ValueError):
                continue
            if not asset or size <= DUST_EPSILON:
                continue
            sellable.append((int(asset), int(round(size * CTF_DECIMAL_FACTOR))))
        return sellable

    def _build_safe_batch_transfer_data(
        self,
        safe_address: str,
        dw_address: str,
        token_ids: List[int],
        amounts: List[int],
    ) -> bytes:
        """Encode CTF ``safeBatchTransferFrom(safe, dw, ids, amounts, "")``.

        :param safe_address: the Safe (current CTF holder / from).
        :param dw_address: the DepositWallet (to).
        :param token_ids: CTF token ids to move.
        :param amounts: parallel amounts in base units.
        :return: the encoded calldata.
        """
        encoded_args = encode(
            ["address", "address", "uint256[]", "uint256[]", "bytes"],
            [
                to_checksum_address(safe_address),
                to_checksum_address(dw_address),
                token_ids,
                amounts,
                b"",
            ],
        )
        return SAFE_BATCH_TRANSFER_SELECTOR + encoded_args

    def _prepare_withdraw_top_up(self) -> Generator[None, None, None]:
        """Resolve the DW and build the CTF batch-transfer multisend.

        Sets ``self.payload`` carrying the FSM event to emit
        (WITHDRAWAL_DONE / PREPARE_TX / NONE).

        :yield: framework yields between the fetch request and tx-hash builds.
        """
        dw_address = self._resolve_deposit_wallet()
        if not dw_address:
            self.context.logger.warning(
                "DepositWallet not yet available; deferring withdrawal top-up."
            )
            self._set_payload(Event.NONE, None)
            return

        sellable = yield from self._fetch_sellable()
        if sellable is None:
            self.context.logger.warning("Failed to fetch positions for withdrawal.")
            self._set_payload(Event.NONE, None)
            return
        if not sellable:
            self.context.logger.info("No sellable positions; withdrawal complete.")
            self._set_payload(Event.WITHDRAWAL_DONE, None)
            return

        token_ids = [t for t, _ in sellable]
        amounts = [a for _, a in sellable]
        self.multisend_batches.append(
            MultisendBatch(
                to=self.params.polymarket_ctf_address,
                data=HexBytes(
                    self._build_safe_batch_transfer_data(
                        self.synchronized_data.safe_contract_address,
                        dw_address,
                        token_ids,
                        amounts,
                    )
                ),
                value=0,
            )
        )
        if not (yield from self._build_multisend_data()):
            self.context.logger.error("Failed to build withdrawal top-up multisend.")
            self._set_payload(Event.NONE, None)
            return
        if not (yield from self._build_multisend_safe_tx_hash()):
            self.context.logger.error("Failed to build withdrawal top-up tx hash.")
            self._set_payload(Event.NONE, None)
            return

        self._set_payload(Event.PREPARE_TX, self.tx_hex)

    def _set_payload(self, event: Event, tx_hash: Optional[str]) -> None:
        """Build the top-up payload carrying the onward event.

        :param event: the FSM event to emit.
        :param tx_hash: the prepared safe tx hash (``None`` when not preparing).
        """
        # PolymarketWithdrawTopUpRound reuses PolymarketTopUpPayload (via its
        # PolymarketTopUpRound base); keep this in sync if the round ever
        # declares a dedicated payload class.
        self.payload = PolymarketTopUpPayload(
            self.context.agent_address,
            self.matching_round.auto_round_id(),
            tx_hash,
            False,
            event.value,
        )

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
