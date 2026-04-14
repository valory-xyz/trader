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

"""This module contains the behaviour for the post-bet update round."""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import PostBetUpdatePayload
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.post_bet_update import (
    PostBetUpdateRound,
)
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)


class PostBetUpdateBehaviour(DecisionMakerBaseBehaviour):
    """Run local-state bookkeeping after an Omen bet/sell tx settles.

    The legacy design used `RedeemBehaviour.async_act` as the
    post-tx-settlement hook for `BetPlacementRound` and
    `SellOutcomeTokensRound`. Under the always-redeem-first FSM
    restructure, redemption no longer runs after the bet, so this
    dedicated round provides the same hook: it dispatches to
    `update_bet_transaction_information` or
    `update_sell_transaction_information` based on the `tx_submitter`,
    then advances the round so the cycle can continue to the staking
    checkpoint.

    Intentional divergence from the legacy `RedeemBehaviour.async_act`
    hook (`reedem.py:956-964`): the legacy code called
    `update_bet_transaction_information()` for both `BetPlacementRound`
    and `SellOutcomeTokensRound`, lazily reusing the bet helper for
    sells. This was the outlier — every other inline caller in the
    codebase already dispatches by tx type:

    - `BetPlacementBehaviour` (benchmarking, `bet_placement.py:127`) calls
      `update_bet_transaction_information`
    - `SellOutcomeTokensBehaviour` (benchmarking,
      `sell_outcome_tokens.py:91`) calls
      `update_sell_transaction_information`
    - `PolymarketBetPlacementBehaviour`
      (`polymarket_bet_placement.py:148,156`) calls
      `update_bet_transaction_information` (Polymarket has no sell)

    `test_sell_outcome_tokens.py::test_async_act_benchmarking_mode`
    already codifies the sell-uses-sell-helper expectation. Calling
    `update_sell_transaction_information` for sell-outcome tx is
    semantically correct (it does not bump `invested_amount` and skips
    the strategy-attribution write that only makes sense for fresh
    bets), and aligns this new hook with the rest of the codebase.

    The legacy `RedeemBehaviour` post-tx hook is left in place as a
    defensive no-op: under the new FSM the period reset clears
    `tx_submitter`/`did_transact` before the next cycle's early redeem
    runs, so the divergence is academic in normal flow.
    """

    matching_round = PostBetUpdateRound

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Defensive: `PostBetUpdateRound` is registered as an
            # `initial_state` of `DecisionMakerAbciApp` because the chain
            # composition routes `FinishedBetPlacementTxRound` /
            # `FinishedSellOutcomeTokensTxRound` (final states of
            # `tx_settlement_multiplexer_abci`) into it. That means a
            # tendermint replay or agent restart could land here without a
            # fresh successful tx in the current period. The
            # `did_transact` guard mirrors the legacy `RedeemBehaviour`
            # post-tx hook (`reedem.py:956-957`) and prevents
            # re-mutating `queue_status` / `processed_timestamp` /
            # `invested_amount` based on stale `tx_submitter` state.
            did_transact = self.synchronized_data.did_transact
            tx_submitter = self.synchronized_data.tx_submitter if did_transact else None
            # Idempotency guard: `PostBetUpdateRound` self-loops on
            # NO_MAJORITY / ROUND_TIMEOUT / NONE. On retry, synced data is
            # unchanged so a naive re-run would re-mutate local bet state
            # (queue_status advances twice, invested_amount double-bumps,
            # processed_timestamp rewrites). Key the guard on
            # `final_tx_hash` so a new period with a fresh settled tx
            # naturally re-applies bookkeeping.
            settled_tx_hash = (
                self.synchronized_data.final_tx_hash if did_transact else None
            )
            already_applied = (
                settled_tx_hash is not None
                and self.context.state.post_bet_update_applied_tx_hash
                == settled_tx_hash
            )
            if already_applied:
                self.context.logger.info(
                    "PostBetUpdateRound retry for tx_hash=%s; "
                    "bookkeeping already applied in this period; skipping.",
                    settled_tx_hash,
                )
            elif did_transact and settled_tx_hash is None:
                # `PostTxSettlementRound.end_block` logs a warning and still
                # emits `BET_PLACEMENT_DONE` / `SELL_OUTCOME_TOKENS_DONE`
                # when `final_tx_hash` is None. Skip bookkeeping here rather
                # than applying mutations we cannot idempotency-key, which
                # would double-mutate on a self-loop retry.
                self.context.logger.warning(
                    "PostBetUpdateRound reached with did_transact=True but "
                    "final_tx_hash is None; skipping bookkeeping to avoid "
                    "non-idempotent mutations."
                )
            elif did_transact and tx_submitter == BetPlacementRound.auto_round_id():
                self.context.logger.info(
                    "Running post-bet bookkeeping after BetPlacementRound."
                )
                self.update_bet_transaction_information()
                self.context.state.post_bet_update_applied_tx_hash = settled_tx_hash
            elif (
                did_transact and tx_submitter == SellOutcomeTokensRound.auto_round_id()
            ):
                self.context.logger.info(
                    "Running post-sell bookkeeping after SellOutcomeTokensRound."
                )
                self.update_sell_transaction_information()
                self.context.state.post_bet_update_applied_tx_hash = settled_tx_hash
            elif not did_transact:
                self.context.logger.info(
                    "PostBetUpdateRound reached without a fresh successful tx "
                    "in the current period (likely a tendermint replay or "
                    "restart); skipping bookkeeping to avoid re-mutating "
                    "stale state."
                )
            else:
                self.context.logger.warning(
                    f"PostBetUpdateRound reached with unexpected "
                    f"tx_submitter={tx_submitter!r}; skipping bookkeeping."
                )

            payload = PostBetUpdatePayload(sender=self.context.agent_address, vote=True)

        yield from self.finish_behaviour(payload)
