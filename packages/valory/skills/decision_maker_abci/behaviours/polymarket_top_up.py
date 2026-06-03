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

"""This module contains the Polymarket (CLOB v2) DepositWallet top-up behaviour."""

from typing import Any, Generator, Optional

from eth_utils import to_checksum_address  # type: ignore[import-not-found]
from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import MultisendBatch
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    PolymarketDepositWalletBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketTopUpPayload
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_top_up import (
    PolymarketTopUpRound,
)

ERC20_TRANSFER_SELECTOR = "0xa9059cbb"  # keccak("transfer(address,uint256)")[:4]


class PolymarketTopUpBehaviour(PolymarketDepositWalletBehaviour):
    """Funds the DepositWallet from the Safe just before a CLOB match.

    Resolves the DepositWallet (provisioning it through the relayer proxy when
    absent), opportunistically sweeps any pUSD stranded in the DW from a prior
    cycle, then builds a Safe multisend transferring the buy amount of pUSD to
    the DW and routes it through tx settlement. When the buy amount is
    non-positive the round short-circuits to ``INSUFFICIENT_BALANCE``.
    """

    matching_round = PolymarketTopUpRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the top-up behaviour."""
        super().__init__(**kwargs)
        self.dw_address: Optional[str] = None

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._prepare_top_up()

        yield from self.finish_behaviour(self.payload)

    def _build_erc20_transfer_data(self, to_address: str, amount: int) -> str:
        """Build ERC20 ``transfer(address,uint256)`` calldata.

        :param to_address: recipient address.
        :param amount: token amount (base units).
        :return: 0x-prefixed calldata hex.
        """
        # Checksum-normalize first: strips/validates the 0x prefix rather than
        # blindly slicing ``[2:]`` (a non-0x address would silently corrupt the
        # encoded recipient).
        to_padded = to_checksum_address(to_address)[2:].zfill(64).lower()
        amount_hex = hex(amount)[2:].zfill(64)
        return f"{ERC20_TRANSFER_SELECTOR}{to_padded}{amount_hex}"

    def _prepare_top_up(self) -> Generator[None, None, None]:
        """Resolve the DW, sweep stranded funds, and prepare the Safe top-up.

        Sets ``self.payload`` carrying the FSM event to emit
        (DONE / PREPARE_TX / INSUFFICIENT_BALANCE).

        :yield: framework yields between the sweep request and tx-hash builds.
        """
        dw_address = self._resolve_deposit_wallet()
        if not dw_address:
            self.context.logger.warning(
                "DepositWallet not yet available; deferring top-up."
            )
            self._set_payload(Event.INSUFFICIENT_BALANCE, None, None)
            return
        self.dw_address = dw_address

        # Opportunistic sweep: reclaim any pUSD AND CTF stranded in the DW by a
        # prior crash (e.g. a matched buy that never swept) before topping it up
        # again. Best-effort — failures are logged and do not block the top-up.
        yield from self._send_polymarket_request(
            RequestType.SWEEP_DW,
            {"dw_address": dw_address, "token_ids": self._position_token_ids()},
        )

        buy_amount = self.synchronized_data.bet_amount
        if buy_amount <= 0:
            self.context.logger.warning(
                f"Non-positive buy amount ({buy_amount}); cannot top up the DW."
            )
            self._set_payload(Event.INSUFFICIENT_BALANCE, None, dw_address)
            return

        # Guard against an under-funded Safe: a pUSD transfer for more than the
        # Safe holds would revert on-chain and burn a full settlement cycle.
        yield from self.wait_for_condition_with_sleep(self.check_balance)
        if buy_amount > self.token_balance:
            self.context.logger.warning(
                f"Safe pUSD balance ({self.token_balance}) below the buy amount "
                f"({buy_amount}); deferring top-up."
            )
            self._set_payload(Event.INSUFFICIENT_BALANCE, None, dw_address)
            return

        # Build the Safe multisend: a single pUSD transfer Safe→DW.
        self.multisend_batches.append(
            MultisendBatch(
                to=self.params.polymarket_collateral_address,
                data=HexBytes(self._build_erc20_transfer_data(dw_address, buy_amount)),
                value=0,
            )
        )
        if not (yield from self._build_multisend_data()):
            self.context.logger.error("Failed to build top-up multisend data.")
            self._set_payload(Event.INSUFFICIENT_BALANCE, None, dw_address)
            return
        if not (yield from self._build_multisend_safe_tx_hash()):
            self.context.logger.error("Failed to build top-up safe tx hash.")
            self._set_payload(Event.INSUFFICIENT_BALANCE, None, dw_address)
            return

        self._set_payload(Event.PREPARE_TX, self.tx_hex, dw_address)

    def _set_payload(
        self, event: Event, tx_hash: Optional[str], dw_address: Optional[str]
    ) -> None:
        """Build the top-up payload carrying the onward event and DW address.

        :param event: the FSM event to emit.
        :param tx_hash: the prepared safe tx hash (``None`` when not preparing).
        :param dw_address: the resolved DepositWallet address.
        """
        self.payload = PolymarketTopUpPayload(
            self.context.agent_address,
            self.matching_round.auto_round_id(),
            tx_hash,
            False,
            event.value,
            dw_address,
        )

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
