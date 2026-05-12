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

"""Omen withdrawal sweep behaviour — builds an (approve, sell)*N multisend."""

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from hexbytes import HexBytes

from packages.valory.contracts.conditional_tokens.contract import (
    ConditionalTokensContract,
)
from packages.valory.contracts.market_maker.contract import (
    FixedProductMarketMakerContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.chatui_abci.models import (
    CHATUI_PARAM_STORE,
    WITHDRAWAL_STATE_COMPLETE,
    WITHDRAWAL_STATE_ERRORED,
    WITHDRAWAL_STATE_SELLING,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    MultisendBatch,
)
from packages.valory.skills.decision_maker_abci.payloads import OmenWithdrawalPayload
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.omen_withdraw import (
    OmenWithdrawRound,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    WithdrawablePosition,
    get_withdrawable_positions,
)

# Hardcoded per spec §9.3 — every Olas-touched Omen FPMM uses wxDAI as
# collateral. Verified across 7,203 distinct FPMMs in the empirical scan.
WXDAI = "0xe91D153E0b41518A2Ce8Dd3D7944Fa863463a97d"
TOP_LEVEL_ERROR_TOKEN_ID = ""  # nosec B105
# Spec §6.3 step 2: cap on halving attempts when the marginal-price estimate
# overshoots the slippage-headroom invariant `n_estimate*(1+slip) <= B`.
MAX_SIZING_ATTEMPTS = 5


def inflate_for_slippage(amount: int, slippage: float) -> int:
    """Inflate ``amount`` by ``slippage`` fraction, rounding up.

    Symmetric to ``behaviours/base.remove_fraction_wei`` for the buy
    direction. Use for SELL ``maxOutcomeTokensToSell`` (a ceiling) — see
    spec §6.3 for the floor-vs-ceiling rationale.

    :param amount: the base amount (e.g. ``calcSellAmount`` output).
    :param slippage: fraction in [0, 1].
    :return: ``int(amount * (1 + slippage)) + 1`` (the ``+1`` forces
        round-up so even a 0% slippage still strictly exceeds ``amount``,
        guarding against integer-floor under-shoot).
    """
    if not 0 <= slippage <= 1:
        raise ValueError(f"slippage {slippage!r} must be in [0, 1]")
    return int(amount * (1 + slippage)) + 1


class OmenWithdrawBehaviour(DecisionMakerBaseBehaviour, QueryingBehaviour):
    """Builds the Omen withdrawal sweep multisend.

    Lifecycle (spec §6.5a):
      1. Persist ``selling`` state, reset fills/errors session records.
      2. Fetch CT ``user_positions`` (current ERC1155 balance) and omen
         ``fpmmTrades`` (FPMM metadata) — top-level retries.
      3. Filter via :func:`get_withdrawable_positions` (OPEN bucket only).
      4. Per position: size the sell via marginal-price + calcSellAmount
         halve-retry, drop on revert or sizing exhaustion.
      5. If nothing sellable: persist ``complete`` (or ``errored``), emit
         ``WITHDRAWAL_DONE`` (short-circuit; no tx settles, so no
         ``PostOmenWithdrawRound`` runs this cycle).
      6. Else: build the (setApprovalForAll, sell)*N multisend, compute
         the Safe tx hash, emit ``PREPARE_TX`` to route through tx
         settlement and on to ``PostOmenWithdrawRound``.
    """

    matching_round = OmenWithdrawRound

    def async_act(self) -> Generator:
        """Run the sweep build."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload = yield from self._build_payload()

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
        self.set_done()

    # ------------------------------------------------------------------ #
    # Top-level orchestration                                            #
    # ------------------------------------------------------------------ #

    def _build_payload(self) -> Generator[None, None, OmenWithdrawalPayload]:
        """Run the full sweep-build pipeline and return the payload to emit."""
        self._set_state(WITHDRAWAL_STATE_SELLING)
        self._reset_session_records()

        safe = self.synchronized_data.safe_contract_address
        user_positions = yield from self._with_top_level_retry(
            "fetch_user_positions",
            lambda: self.fetch_user_positions(safe),
        )
        if user_positions is None:
            return self._short_circuit_payload(errored=True)

        creator_rows = yield from self._with_top_level_retry(
            "fetch_withdrawal_creator_fpmms",
            lambda: self.fetch_withdrawal_creator_fpmms(safe),
        )
        if creator_rows is None:
            return self._short_circuit_payload(errored=True)

        sellable = get_withdrawable_positions(creator_rows, user_positions)
        if not sellable:
            self.context.logger.info("omen withdrawal: no sellable positions found")
            return self._short_circuit_payload(errored=False)

        sellable.sort(key=lambda p: (p.fpmm_address.lower(), p.outcome_index))
        self.context.logger.info(
            f"omen withdrawal: discovered {len(sellable)} sellable position(s)"
        )

        batches: List[MultisendBatch] = []
        for position in sellable:
            position_batches = yield from self._size_and_build_position(position)
            if position_batches is not None:
                batches.extend(position_batches)

        if not batches:
            self.context.logger.info(
                "omen withdrawal: all positions filtered out (dust or sizing)"
            )
            return self._short_circuit_payload(errored=self._store_has_errors())

        # Stage batches on the base behaviour so the existing
        # _build_multisend_* helpers see them.
        self.multisend_batches = batches

        for step in (
            self._build_multisend_data,
            self._build_multisend_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        return OmenWithdrawalPayload(
            sender=self.context.agent_address,
            tx_submitter=self.matching_round.auto_round_id(),
            tx_hash=self.tx_hex,
            mocking_mode=False,
            event=Event.PREPARE_TX.value,
        )

    def _short_circuit_payload(self, errored: bool) -> OmenWithdrawalPayload:
        """Persist terminal state and build the ``WITHDRAWAL_DONE`` payload.

        :param errored: whether to flag the session as ``errored`` (any
            top-level fetch failure or per-position error already
            persisted) or ``complete``.
        :return: a payload with no tx fields; the round's ``end_block``
            override routes the trailing ``event`` field through.
        """
        terminal = WITHDRAWAL_STATE_ERRORED if errored else WITHDRAWAL_STATE_COMPLETE
        self._set_state(terminal)
        return OmenWithdrawalPayload(
            sender=self.context.agent_address,
            tx_submitter=None,
            tx_hash=None,
            mocking_mode=None,
            event=Event.WITHDRAWAL_DONE.value,
        )

    # ------------------------------------------------------------------ #
    # Top-level retry helper (Polystrat-compatible)                      #
    # ------------------------------------------------------------------ #

    def _with_top_level_retry(
        self,
        op_name: str,
        request_fn: Callable[[], Generator[None, None, Any]],
    ) -> Generator[None, None, Optional[Any]]:
        """Run ``request_fn`` with up to ``withdrawal_max_fak_attempts`` retries.

        Mirrors the Polystrat retry wrapper (same params; the name is
        Polystrat-historic but the schedule is venue-agnostic).

        :param op_name: human-readable label written to the error record.
        :param request_fn: zero-arg generator returning the result (or
            ``None`` on subgraph failure — caller-supplied semantics).
        :yield: framework yields between attempts.
        :return: the result on success; ``None`` on exhaustion.
        """
        max_attempts = self.context.params.withdrawal_max_fak_attempts
        backoff = list(self.context.params.withdrawal_fak_backoff_s)
        for attempt in range(max_attempts):
            result = yield from request_fn()
            if result is not None:
                return result
            self.context.logger.warning(
                f"omen withdrawal: top-level retry {attempt + 1}/{max_attempts} "
                f"on {op_name}"
            )
            if attempt < max_attempts - 1 and attempt < len(backoff):
                yield from self.sleep(backoff[attempt])
        self._record_top_level_error(op_name)
        return None

    # ------------------------------------------------------------------ #
    # Per-position sizing + batch assembly                               #
    # ------------------------------------------------------------------ #

    def _size_and_build_position(
        self, position: WithdrawablePosition
    ) -> Generator[None, None, Optional[List[MultisendBatch]]]:
        """Size the per-position sell and return the (approve, sell) batches.

        Returns ``None`` if the position is dropped (dust below
        ``dust_epsilon_wxdai``, sizing exhausted, or ``calcSellAmount``
        reverts); the caller continues with the next position.

        :param position: a single :class:`WithdrawablePosition` row.
        :yield: framework yields for the on-chain reads.
        :return: a list with exactly two ``MultisendBatch`` entries
            (``setApprovalForAll`` + ``sell``), or ``None`` to drop.
        """
        slip = self.context.params.withdrawal_slippage
        buffer_frac = self.context.params.withdrawal_return_buffer
        dust_threshold = self.context.params.dust_epsilon_wxdai

        pool_balances = yield from self._read_pool_balances(position)
        if pool_balances is None or sum(pool_balances) == 0:
            self._record_error(
                position,
                "pool_balances unavailable or empty",
            )
            return None

        other_sum = sum(
            balance
            for idx, balance in enumerate(pool_balances)
            if idx != position.outcome_index
        )
        marginal_price = other_sum / sum(pool_balances)
        notional_wxdai = int(position.balance * marginal_price)
        if notional_wxdai < dust_threshold:
            # spec §6.3 dust threshold — exclude silently
            return None

        return_amount = int(notional_wxdai * (1 - buffer_frac))
        headroom_cap = int(position.balance / (1 + slip))

        n_estimate: Optional[int] = None
        for _ in range(MAX_SIZING_ATTEMPTS):
            n_estimate = yield from self._calc_sell_amount_static(
                position.fpmm_address, return_amount, position.outcome_index
            )
            if n_estimate is None:
                self._record_error(
                    position,
                    "calcSellAmount reverted: see logs",
                )
                return None
            if n_estimate <= headroom_cap:
                break
            return_amount //= 2
            if return_amount == 0:
                break
        else:
            self._record_error(
                position,
                "returnAmount could not be sized to fit balance with "
                "slippage headroom",
            )
            return None

        if n_estimate is None or n_estimate <= 0 or return_amount <= 0:
            self._record_error(
                position,
                "returnAmount could not be sized to fit balance with "
                "slippage headroom",
            )
            return None

        max_outcome_tokens_to_sell = min(
            inflate_for_slippage(n_estimate, slip), position.balance
        )

        approval_batch = yield from self._build_set_approval_batch(
            position.fpmm_address
        )
        if approval_batch is None:
            self._record_error(position, "failed to encode setApprovalForAll")
            return None

        sell_batch = yield from self._build_sell_batch(
            position, return_amount, max_outcome_tokens_to_sell
        )
        if sell_batch is None:
            self._record_error(position, "failed to encode sell calldata")
            return None

        self.context.logger.info(
            f"omen withdrawal: sized {position.fpmm_address} outcome="
            f"{position.outcome_index} return={return_amount} max_tokens="
            f"{max_outcome_tokens_to_sell}"
        )
        return [approval_batch, sell_batch]

    # ------------------------------------------------------------------ #
    # Contract interactions                                              #
    # ------------------------------------------------------------------ #

    def _read_pool_balances(
        self, position: WithdrawablePosition
    ) -> Generator[None, None, Optional[List[int]]]:
        """Read the FPMM's per-outcome ERC1155 reserves via CT."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=position.fpmm_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="get_pool_balances_via_ct",
            conditional_tokens_address=self.params.conditional_tokens_address,
            collateral_token=WXDAI,
            condition_id=position.condition_id,
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.warning(
                f"omen withdrawal: pool balances unavailable for "
                f"{position.fpmm_address}: {response_msg}"
            )
            return None
        balances = response_msg.state.body.get("balances")
        if not balances:
            return None
        return [int(b) for b in balances]

    def _calc_sell_amount_static(
        self, fpmm_address: str, return_amount: int, outcome_index: int
    ) -> Generator[None, None, Optional[int]]:
        """Static-call ``FPMM.calcSellAmount``; ``None`` on revert."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=fpmm_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="calc_sell_amount",
            return_amount=return_amount,
            outcome_index=outcome_index,
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.warning(
                f"omen withdrawal: calcSellAmount reverted for {fpmm_address}: "
                f"{response_msg}"
            )
            return None
        amount = response_msg.raw_transaction.body.get("amount")
        if amount is None:
            return None
        return int(amount)

    def _build_set_approval_batch(
        self, fpmm_address: str
    ) -> Generator[None, None, Optional[MultisendBatch]]:
        """Encode ``setApprovalForAll(fpmm, true)`` on ConditionalTokens."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.params.conditional_tokens_address,
            contract_id=str(ConditionalTokensContract.contract_id),
            contract_callable="build_set_approval_for_all_tx",
            operator=fpmm_address,
            approved=True,
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            return None
        data = response_msg.state.body.get("data")
        if data is None:
            return None
        return MultisendBatch(
            to=self.params.conditional_tokens_address,
            data=HexBytes(data),
        )

    def _build_sell_batch(
        self,
        position: WithdrawablePosition,
        return_amount: int,
        max_outcome_tokens_to_sell: int,
    ) -> Generator[None, None, Optional[MultisendBatch]]:
        """Encode ``FPMM.sell(returnAmount, outcomeIndex, maxOut)``."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=position.fpmm_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="get_sell_data",
            return_amount=return_amount,
            outcome_index=position.outcome_index,
            max_outcome_tokens_to_sell=max_outcome_tokens_to_sell,
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            return None
        data = response_msg.state.body.get("data")
        if data is None:
            return None
        return MultisendBatch(
            to=position.fpmm_address,
            data=HexBytes(data),
        )

    # ------------------------------------------------------------------ #
    # Multisend / Safe tx-hash plumbing — re-uses base behaviour helpers #
    # ------------------------------------------------------------------ #

    # `_build_multisend_data` and `_build_multisend_safe_tx_hash` live on
    # `DecisionMakerBaseBehaviour` and read from `self.multisend_batches`
    # / write to `self.safe_tx_hash` — staged in `_build_payload`.

    # ------------------------------------------------------------------ #
    # Disk-backed persistence (mirror Polystrat)                         #
    # ------------------------------------------------------------------ #

    def _store_path(self) -> Path:
        """Return the path of the chatui JSON store."""
        return Path(self.context.params.store_path) / CHATUI_PARAM_STORE

    def _read_store(self) -> Dict[str, Any]:
        """Load the chatui JSON store, defensive against missing/invalid file."""
        try:
            with open(self._store_path(), "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_store(self, store: Dict[str, Any]) -> None:
        """Persist the chatui JSON store."""
        try:
            with open(self._store_path(), "w") as f:
                json.dump(store, f, indent=4)
        except OSError as e:
            self.context.logger.error(f"omen withdrawal: failed to write store: {e}")

    def _set_state(self, state: str) -> None:
        """Update ``withdrawal_state`` on disk and log the transition."""
        store = self._read_store()
        store["withdrawal_state"] = state
        self._write_store(store)
        self.context.logger.info(f"omen withdrawal: state -> {state}")

    def _reset_session_records(self) -> None:
        """Clear ``withdrawal_fills`` and ``withdrawal_errors`` on disk."""
        store = self._read_store()
        store["withdrawal_fills"] = []
        store["withdrawal_errors"] = []
        self._write_store(store)

    def _record_error(self, position: WithdrawablePosition, reason: str) -> None:
        """Append an error record for a per-position drop."""
        store = self._read_store()
        errors = store.setdefault("withdrawal_errors", [])
        errors.append(
            {
                "token_id": position.token_id,
                "shares_remaining": position.balance / 1e18,
                "reason": reason,
                "ts": int(time.time()),
                "fpmm": position.fpmm_address,
                "outcome_index": position.outcome_index,
            }
        )
        self._write_store(store)
        self.context.logger.warning(
            f"omen withdrawal: drop {position.fpmm_address} "
            f"outcome={position.outcome_index} reason={reason!r}"
        )

    def _record_top_level_error(self, op_name: str) -> None:
        """Record a top-level error (no per-position attribution)."""
        store = self._read_store()
        errors = store.setdefault("withdrawal_errors", [])
        errors.append(
            {
                "token_id": TOP_LEVEL_ERROR_TOKEN_ID,
                "shares_remaining": 0.0,
                "reason": f"{op_name}: retries exhausted",
                "ts": int(time.time()),
            }
        )
        self._write_store(store)
        self.context.logger.error(f"omen withdrawal: top-level failure on {op_name}")

    def _store_has_errors(self) -> bool:
        """Check whether the current session has any persisted errors."""
        return bool(self._read_store().get("withdrawal_errors"))
