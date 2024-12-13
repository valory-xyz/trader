# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This package contains the behaviours of the transaction settlement multiplexer."""

from typing import Generator, Optional, Set, Type, cast

from aea.exceptions import AEAEnforceError

from packages.valory.protocols.ledger_api import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import RedeemingProgress
from packages.valory.skills.decision_maker_abci.payloads import VotingPayload
from packages.valory.skills.tx_settlement_multiplexer_abci.models import (
    TxSettlementMultiplexerParams,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    PostTxSettlementRound,
    PreTxSettlementRound,
    SynchronizedData,
    TxSettlementMultiplexerAbciApp,
)


class PreTxSettlementBehaviour(BaseBehaviour):
    """
    The pre transaction settlement behaviour.

    This behaviour should be executed before a tx is sent via the transaction_settlement_abci.
    """

    matching_round = PreTxSettlementRound

    @property
    def params(self) -> TxSettlementMultiplexerParams:
        """Return the params."""
        return cast(TxSettlementMultiplexerParams, self.context.params)

    def _get_balance(self, agent: str) -> Generator[None, None, Optional[int]]:
        """Get the given agent's balance."""
        self.context.logger.info(f"Checking balance for agent with address {agent}...")
        ledger_api_response = yield from self.get_ledger_api_response(
            performative=LedgerApiMessage.Performative.GET_STATE,  # type: ignore
            ledger_callable="get_balance",
            account=agent,
            chain_id=self.params.mech_chain_id,
        )

        try:
            balance = int(ledger_api_response.state.body["get_balance_result"])
        except (AEAEnforceError, KeyError, ValueError, TypeError):
            balance = None

        if balance is None:
            log_msg = f"Failed to get the balance for agent with address {agent}."
            self.context.logger.error(f"{log_msg}: {ledger_api_response}")
            return None

        self.context.logger.info(f"The agent with address {agent} has {balance} WEI.")
        return balance

    def _check_balance(self, agent: str) -> Generator[None, None, bool]:
        """Check if the given agent's balance is sufficient."""
        balance = None
        while balance is None:
            balance = yield from self._get_balance(agent)

        threshold = self.params.agent_balance_threshold
        refill_required = balance < threshold
        if refill_required:
            msg = f"Please refill agent with address {agent}. Balance is below {threshold}."
            self.context.logger.warning(msg)

        return refill_required

    def _refill_required(self) -> Generator[None, None, bool]:
        """Check whether a refill is required."""
        refill_required = False
        for agent in self.synchronized_data.all_participants:
            refill_required |= yield from self._check_balance(agent)
        return refill_required

    def async_act(self) -> Generator:
        """Check whether the agents' balances are sufficient."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            refill_required = yield from self._refill_required()
            if refill_required:
                # pause to give the user some time to refill before transitioning to the same round again
                yield from self.sleep(self.params.refill_check_interval)

            payload = VotingPayload(self.context.agent_address, not refill_required)

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()


class PostTxSettlementBehaviour(BaseBehaviour):
    """
    The post transaction settlement behaviour.

    This behaviour should be executed after a tx is settled via the transaction_settlement_abci.
    """

    matching_round = PostTxSettlementRound

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    @property
    def redeeming_progress(self) -> RedeemingProgress:
        """Get the redeeming progress."""
        return self.shared_state.redeeming_progress  # type: ignore

    @redeeming_progress.setter
    def redeeming_progress(self, value: RedeemingProgress) -> None:
        """Set the redeeming progress."""
        self.shared_state.redeeming_progress = value

    def _on_redeem_round_tx_settled(self) -> None:
        """Handle the redeem round."""
        self.context.logger.info(
            "Redeeming transaction was settled. Resetting the redeeming progress."
        )
        claimed_condition_ids = self.redeeming_progress.claimed_condition_ids
        claimed_condition_ids.extend(self.redeeming_progress.claiming_condition_ids)
        self.redeeming_progress = RedeemingProgress()
        self.redeeming_progress.claimed_condition_ids = claimed_condition_ids
        self.context.logger.info(
            f"The following condition ids were claimed so far: {claimed_condition_ids}"
        )

    def _on_tx_settled(self) -> None:
        """Handle the tx settled event."""
        tx_submitter = self.synchronized_data.tx_submitter
        handler_name = f"_on_{tx_submitter}_tx_settled"
        handler = getattr(self, handler_name, None)
        if handler is None:
            self.context.logger.info(
                f"No post tx settlement handler exists for {tx_submitter} txs."
            )
            return
        handler()

    def async_act(self) -> Generator:
        """Simply log that a tx is settled and wait for the round end."""
        msg = f"The transaction submitted by {self.synchronized_data.tx_submitter} was successfully settled."
        self.context.logger.info(msg)
        self._on_tx_settled()
        yield from self.wait_until_round_end()
        self.set_done()


class PostTxSettlementFullBehaviour(AbstractRoundBehaviour):
    """The post tx settlement full behaviour."""

    initial_behaviour_cls = PostTxSettlementBehaviour
    abci_app_cls = TxSettlementMultiplexerAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {
        PreTxSettlementBehaviour,  # type: ignore
        PostTxSettlementBehaviour,  # type: ignore
    }
