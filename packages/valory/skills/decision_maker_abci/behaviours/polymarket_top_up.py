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

import math
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
# pUSD base units per whole token. Spelled out rather than taken from
# ``get_token_precision()`` so it stays the exact inverse of ``usdc_to_native``,
# which hardcodes the same 6 decimals two lines below — deriving one of the pair
# and hardcoding the other is how a scale bug gets in.
PUSD_UNITS = 10**6
# Cushion on the measured taker fee. The fee is priced here, a round and a full
# on-chain settlement before the order is signed, and it moves with the price
# (≈0.5%–3.7% across the price range), so the figure quoted now understates the
# one charged then whenever the price drifts toward the middle of the book.
# Reserving half as much again absorbs that; whatever the buy leaves behind is
# swept back to the Safe at the start of the next cycle, so over-funding the DW
# costs nothing but a little idle pUSD.
FEE_HEADROOM_RATIO = 1.5


class PolymarketTopUpBehaviour(PolymarketDepositWalletBehaviour):
    """Funds the DepositWallet from the Safe just before a CLOB match.

    Resolves the DepositWallet (provisioning it through the relayer proxy when
    absent), opportunistically sweeps any pUSD stranded in the DW from a prior
    cycle, then builds a Safe multisend transferring the buy amount of pUSD —
    plus the quoted CLOB taker fee, which the SDK would otherwise carve out of
    the bet — to the DW, and routes it through tx settlement. When the buy
    amount is non-positive the round short-circuits to ``INSUFFICIENT_BALANCE``.
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
            self._set_payload(Event.INSUFFICIENT_BALANCE, None)
            return
        self.dw_address = dw_address

        # Opportunistic sweep before re-funding the DW. The connection sweeps
        # the DW's pUSD by live balance (token-id-independent), so any pUSD
        # stranded by a prior crash is fully reclaimed. CTF is only swept for
        # the CURRENTLY sampled bet's outcome token ids, so a position stranded
        # from a DIFFERENT market by an earlier crashed cycle is NOT reclaimed
        # here (ERC-1155 has no cheap enumeration); only its pUSD is. Best-effort
        # — failures are logged and do not block the top-up.
        yield from self._send_polymarket_request(
            RequestType.SWEEP_DW,
            {"dw_address": dw_address, "token_ids": self._position_token_ids()},
        )

        buy_amount = self.synchronized_data.bet_amount
        if buy_amount <= 0:
            self.context.logger.warning(
                f"Non-positive buy amount ({buy_amount}); cannot top up the DW."
            )
            self._set_payload(Event.INSUFFICIENT_BALANCE, None)
            return

        top_up_amount = yield from self._top_up_amount(buy_amount)

        # Guard against an under-funded Safe: a pUSD transfer for more than the
        # Safe holds would revert on-chain and burn a full settlement cycle.
        yield from self.wait_for_condition_with_sleep(self.check_balance)
        if top_up_amount > self.token_balance:
            self.context.logger.warning(
                f"Safe pUSD balance ({self.token_balance}) below the top-up amount "
                f"({top_up_amount}); deferring top-up."
            )
            self._set_payload(Event.INSUFFICIENT_BALANCE, None)
            return

        # Build the Safe multisend: a single pUSD transfer Safe→DW.
        self.multisend_batches.append(
            MultisendBatch(
                to=self.params.polymarket_collateral_address,
                data=HexBytes(
                    self._build_erc20_transfer_data(dw_address, top_up_amount)
                ),
                value=0,
            )
        )
        if not (yield from self._build_multisend_data()):
            self.context.logger.error("Failed to build top-up multisend data.")
            self._set_payload(Event.INSUFFICIENT_BALANCE, None)
            return
        if not (yield from self._build_multisend_safe_tx_hash()):
            self.context.logger.error("Failed to build top-up safe tx hash.")
            self._set_payload(Event.INSUFFICIENT_BALANCE, None)
            return

        self._set_payload(Event.PREPARE_TX, self.tx_hex)

    def _sampled_outcome_token_id(self) -> Optional[str]:
        """The CTF token id the imminent buy will target, if it can be resolved.

        :return: the token id, or ``None`` when no bet/outcome is resolvable.
        """
        try:
            outcome = self.sampled_bet.get_outcome(self.outcome_index)
            return (self.sampled_bet.outcome_token_ids or {})[outcome]
        except Exception as e:  # noqa: BLE001 — best-effort; the fee is advisory
            # Name the cause. Degrading here funds the bare bet, which is the
            # state that gets the order shrunk under the venue minimum — so this
            # warning is the only trace of why a later placement was refused.
            self.context.logger.warning(
                f"Could not resolve the sampled outcome token id ({e}); "
                "topping up the bet without a fee reserve."
            )
            return None

    def _top_up_amount(self, buy_amount: int) -> Generator[None, None, int]:
        """Add the CLOB taker fee to the bet, so the order is not shrunk by it.

        The SDK sizes a market buy against the funder's live balance and holds
        the fee back out of it, so a DepositWallet funded with exactly the bet
        always puts ``bet - fee`` on the book. That both buys fewer shares than
        the strategy sized (kelly charges the fee on top of ``spend``, not out
        of it) and, for a bet sitting on the venue's $1 floor, drops the order
        under the minimum and gets it rejected outright. Funding the fee
        alongside the bet makes the order equal the bet.

        Best-effort: an unreadable book or fee schedule falls back to the bare
        bet, leaving the connection's own preflight to catch what that costs.

        :param buy_amount: the bet, in pUSD base units.
        :yield: framework yields around the quote request.
        :return: the pUSD base units to transfer Safe→DW.
        """
        token_id = self._sampled_outcome_token_id()
        if token_id is None:
            return buy_amount

        quote = yield from self._send_polymarket_request(
            RequestType.QUOTE_BUY,
            {
                "token_id": token_id,
                "amount": self.usdc_to_native(buy_amount),
                "funder": self.dw_address,
            },
        )
        fee = (quote or {}).get("fee_usd")
        if fee is None:
            # Either the request failed or the book/fee schedule was unreadable.
            # Distinguished from a genuine zero fee because this one degrades to
            # the pre-fix behaviour — the bet gets funded bare, the SDK shrinks
            # the order by the fee, and a floor-sized bet is then refused. Say so
            # here or the refusal looks unexplained a round later.
            self.context.logger.warning(
                "No CLOB fee quote available; topping up the bare bet. The order "
                "may be shrunk by the taker fee and refused if it is near the "
                "venue minimum."
            )
            return buy_amount
        if fee <= 0:
            # A market that charges no taker fee: nothing to reserve. The
            # negative arm is unreachable with a well-behaved SDK (the fee is
            # measured as what it declines to spend, which cannot exceed the
            # amount), and guards a value that crosses a process boundary.
            return buy_amount

        # Round the reserve up: truncating it would leave the order a base unit
        # short of the bet, which is the whole failure this reserve exists for.
        reserve = math.ceil(fee * FEE_HEADROOM_RATIO * PUSD_UNITS)
        self.context.logger.info(
            f"Reserving {reserve} pUSD units for the CLOB taker fee "
            f"(quoted {fee}) on top of the {buy_amount} bet."
        )
        return buy_amount + reserve

    def _set_payload(self, event: Event, tx_hash: Optional[str]) -> None:
        """Build the top-up payload carrying the onward event.

        :param event: the FSM event to emit.
        :param tx_hash: the prepared safe tx hash (``None`` when not preparing).
        """
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
