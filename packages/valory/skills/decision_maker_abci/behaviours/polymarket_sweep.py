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

"""This module contains the Polymarket (CLOB v2) DepositWallet sweep behaviour."""

from typing import Generator

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    PolymarketDepositWalletBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PolymarketSweepPayload
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_sweep import (
    PolymarketSweepRound,
)


class PolymarketSweepBehaviour(PolymarketDepositWalletBehaviour):
    """Sweeps the DepositWallet back to the Safe after a CLOB match.

    Issues an idempotent ``SWEEP_DW`` to the relayer proxy ("transfer
    whatever's there") via the shared ``_send_polymarket_request`` helper. A
    successful sweep — including the no-op empty-DW case — emits ``DONE`` so the
    cycle wraps up; a failed sweep emits ``NONE`` so the round loops and the
    funds linger in the DW until the next pass.
    """

    matching_round = PolymarketSweepRound

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._sweep()

        yield from self.finish_behaviour(self.payload)

    def _sweep(self) -> Generator[None, None, None]:
        """Request the DepositWallet→Safe sweep and set the onward payload.

        Passes the sampled bet's outcome token ids so the bought CTF position
        (not just pUSD) is moved back to the canonical Safe.

        :yield: framework yields between dispatch and the connection response.
        """
        dw_address = self._resolve_deposit_wallet()
        response = yield from self._send_polymarket_request(
            RequestType.SWEEP_DW,
            {"dw_address": dw_address, "token_ids": self._position_token_ids()},
        )

        if response is None:
            self.context.logger.warning(
                "DepositWallet sweep failed; looping until the next pass."
            )
            self._set_payload(Event.NONE)
            return

        self.context.logger.info(f"DepositWallet sweep result: {response}")
        self._set_payload(Event.DONE)

    def _set_payload(self, event: Event) -> None:
        """Build the sweep payload carrying the onward event.

        :param event: the FSM event to emit.
        """
        self.payload = PolymarketSweepPayload(
            self.context.agent_address,
            self.matching_round.auto_round_id(),
            None,
            False,
            event.value,
        )

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
