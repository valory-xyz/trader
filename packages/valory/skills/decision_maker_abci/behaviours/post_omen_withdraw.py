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

"""Post-settlement behaviour for the Omen withdrawal sweep.

Runs after ``tx_settlement_multiplexer_abci`` routes the settled sweep
multisend back into ``decision_maker_abci``. Parses the on-chain
receipt, records per-fill / per-error rows to the chatui JSON store,
and snapshots ``funds_locked_in_markets`` on a best-effort basis so
the FE reflects the post-sweep state without waiting for the next
normal perf-summary round.
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from hexbytes import HexBytes

from packages.valory.contracts.market_maker.contract import (
    FixedProductMarketMakerContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.chatui_abci.models import (
    CHATUI_PARAM_STORE,
    WITHDRAWAL_STATE_COMPLETE,
    WITHDRAWAL_STATE_ERRORED,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PostOmenWithdrawalPayload,
)
from packages.valory.skills.decision_maker_abci.states.post_omen_withdraw import (
    PostOmenWithdrawRound,
)


# Safe v1.x event topics — keccak("ExecutionFailure(bytes32,uint256)") /
# ("ExecutionSuccess(bytes32,uint256)"). The outer Safe ``execTransaction``
# returns true (status=1) regardless of whether the inner multisend
# reverted; the only signal of inner failure on a status=1 tx is the
# ``ExecutionFailure`` topic.
EXECUTION_FAILURE_TOPIC0 = HexBytes(
    "0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23"
)
TOP_LEVEL_ERROR_TOKEN_ID = ""  # nosec B105


class PostOmenWithdrawBehaviour(DecisionMakerBaseBehaviour):
    """Parses the Omen sweep tx receipt; persists fills / errors / snapshot."""

    matching_round = PostOmenWithdrawRound

    def async_act(self) -> Generator:
        """Run the receipt-parse pipeline."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._parse_receipt_and_persist()
            yield from self._snapshot_funds_locked()
            payload = PostOmenWithdrawalPayload(
                sender=self.context.agent_address,
                vote=True,
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
        self.set_done()

    # ------------------------------------------------------------------ #
    # Receipt parse + fill/error persistence                             #
    # ------------------------------------------------------------------ #

    def _parse_receipt_and_persist(self) -> Generator:
        """Decode FPMMSell events and write fills/errors to the JSON store.

        :yield: framework yields between the receipt fetch and parse.
        """
        tx_hash = self.synchronized_data.final_tx_hash
        if not tx_hash:
            self._record_top_level_error("missing final_tx_hash")
            self._set_state(WITHDRAWAL_STATE_ERRORED)
            return

        receipt = yield from self.get_transaction_receipt(
            tx_hash, chain_id=self.params.mech_chain_id
        )
        if receipt is None:
            self._record_top_level_error(
                f"get_transaction_receipt returned None for {tx_hash}"
            )
            self._set_state(WITHDRAWAL_STATE_ERRORED)
            return

        if int(receipt.get("status", 0)) == 0:
            self._record_top_level_error("Safe tx reverted")
            self._set_state(WITHDRAWAL_STATE_ERRORED)
            return

        if self._receipt_has_execution_failure(receipt):
            self._record_top_level_error(
                f"Safe ExecutionFailure: {tx_hash}"
            )
            self._set_state(WITHDRAWAL_STATE_ERRORED)
            return

        events = yield from self._parse_sell_events(receipt)
        if events is None:
            self._record_top_level_error("parse_sell_events returned None")
            self._set_state(WITHDRAWAL_STATE_ERRORED)
            return

        if not events:
            # Receipt valid but no FPMMSell logs — shouldn't happen on a
            # well-formed sweep, but defensible.
            self.context.logger.warning(
                f"omen withdrawal: tx {tx_hash} status=1 but no FPMMSell logs"
            )

        for event in events:
            self._record_fill(event)
        self.context.logger.info(
            f"omen withdrawal: recorded {len(events)} fill(s) from {tx_hash}"
        )

        # The fills are all the new fills from this sweep. Per-position
        # errors from the build step were persisted by ``OmenWithdrawBehaviour``
        # already (sizing exhaustion, calcSellAmount reverts, dust drops).
        terminal = (
            WITHDRAWAL_STATE_ERRORED
            if self._store_has_errors()
            else WITHDRAWAL_STATE_COMPLETE
        )
        self._set_state(terminal)

    def _receipt_has_execution_failure(self, receipt: Dict[str, Any]) -> bool:
        """Return True iff the receipt contains a Safe ExecutionFailure log."""
        for log in receipt.get("logs", []) or []:
            topics = log.get("topics") or []
            if topics and HexBytes(topics[0]) == EXECUTION_FAILURE_TOPIC0:
                return True
        return False

    def _parse_sell_events(
        self, receipt: Dict[str, Any]
    ) -> Generator[None, None, Optional[List[Dict[str, Any]]]]:
        """Call ``FixedProductMarketMakerContract.parse_sell_events`` on the receipt.

        :param receipt: the tx receipt dict.
        :yield: framework yields for the contract call.
        :return: decoded events or ``None`` on dispatch error.
        """
        # parse_sell_events doesn't read on-chain state — it decodes the
        # receipt we already have. Use any FPMM address in the receipt for
        # contract dispatch (or the zero address; the method ignores it).
        contract_address = self._first_fpmm_in_receipt(receipt) or (
            "0x0000000000000000000000000000000000000000"
        )
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=contract_address,
            contract_id=str(FixedProductMarketMakerContract.contract_id),
            contract_callable="parse_sell_events",
            receipt=receipt,
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                f"omen withdrawal: parse_sell_events dispatch failed: "
                f"{response_msg}"
            )
            return None
        events = response_msg.state.body.get("events")
        if events is None:
            return []
        return [dict(e) for e in events]

    @staticmethod
    def _first_fpmm_in_receipt(receipt: Dict[str, Any]) -> Optional[str]:
        """Return the first non-Safe log's address (best-effort)."""
        for log in receipt.get("logs", []) or []:
            address = log.get("address")
            if address:
                return str(address)
        return None

    # ------------------------------------------------------------------ #
    # Funds-locked snapshot — best-effort                                #
    # ------------------------------------------------------------------ #

    def _snapshot_funds_locked(self) -> Generator:
        """Best-effort post-sweep refresh of ``funds_locked_in_markets``.

        Bridges the indexer-lag gap between settlement and the next
        normal perf-summary round, so the FE doesn't show a stale value
        for minutes. Failure here is non-fatal — log a warning and let
        the next normal round catch up.

        :yield: framework yield for the (currently no-op) generator.
        """
        # NOTE (#943): kept as a hook for Phase 3 — the per-position
        # locked-funds formula (spec §10.13.1) will land alongside the
        # perf-summary edits and call into this method. Until then we
        # leave the existing snapshot alone to avoid a non-monotonic FE
        # jump.
        if False:  # pragma: no cover — generator-shape preservation
            yield

    # ------------------------------------------------------------------ #
    # Disk-backed persistence (mirror OmenWithdrawBehaviour)             #
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
            self.context.logger.error(
                f"omen withdrawal: failed to write store: {e}"
            )

    def _set_state(self, state: str) -> None:
        """Update ``withdrawal_state`` on disk and log the transition."""
        store = self._read_store()
        store["withdrawal_state"] = state
        self._write_store(store)
        self.context.logger.info(f"omen withdrawal: state -> {state}")

    def _record_fill(self, event: Dict[str, Any]) -> None:
        """Append a fill record from a decoded FPMMSell event."""
        outcome_tokens_sold = int(event.get("outcome_tokens_sold", 0))
        return_amount = int(event.get("return_amount", 0))
        fee_amount = int(event.get("fee_amount", 0))
        shares_sold = outcome_tokens_sold / 1e18
        fill_price = (
            (return_amount / 1e18) / shares_sold if shares_sold > 0 else 0.0
        )
        store = self._read_store()
        fills = store.setdefault("withdrawal_fills", [])
        fills.append(
            {
                # token_id derivation requires position-id keccak; the FE
                # tolerates an empty string and uses (fpmm, outcome_index)
                # for display. The OmenWithdrawBehaviour planning step
                # captures the decimal position id in its error records;
                # fills only need the venue-specific identifier pair.
                "token_id": "",
                "shares_sold": shares_sold,
                "fill_price": fill_price,
                "ts": int(time.time()),
                "fpmm": event.get("fpmm"),
                "outcome_index": int(event.get("outcome_index", 0)),
                "return_amount": return_amount / 1e18,
                "fee_amount": fee_amount / 1e18,
            }
        )
        self._write_store(store)

    def _record_top_level_error(self, reason: str) -> None:
        """Record a top-level error (no per-position attribution)."""
        store = self._read_store()
        errors = store.setdefault("withdrawal_errors", [])
        errors.append(
            {
                "token_id": TOP_LEVEL_ERROR_TOKEN_ID,
                "shares_remaining": 0.0,
                "reason": reason,
                "ts": int(time.time()),
            }
        )
        self._write_store(store)
        self.context.logger.error(f"omen withdrawal: top-level failure: {reason}")

    def _store_has_errors(self) -> bool:
        """Check whether the current session has any persisted errors."""
        return bool(self._read_store().get("withdrawal_errors"))
