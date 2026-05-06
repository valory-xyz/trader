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

"""Polymarket withdrawal behaviour — sells unredeemable CTF positions on FAK."""

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.chatui_abci.models import (
    CHATUI_PARAM_STORE,
    WITHDRAWAL_STATE_COMPLETE,
    WITHDRAWAL_STATE_ERRORED,
    WITHDRAWAL_STATE_SELLING,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import WithdrawalPayload
from packages.valory.skills.decision_maker_abci.states.polymarket_withdraw import (
    PolymarketWithdrawRound,
)

# Dust threshold for both whole-position filtering and per-position residual
# completion. 0.01 CTF shares is at most ~1¢ of stuck value at any realistic
# CTF price (0 < p < 1 USDC/share), and below this the SDK's 6-decimal-fixed
# maker/taker amount calc can round to 0 — the CLOB rejects such orders with
# "invalid amounts, maker and taker amount must be higher than 0". Treating
# such residuals as fully sold avoids a guaranteed-failing retry burn.
DUST_EPSILON = 1e-2
TOP_LEVEL_ERROR_TOKEN_ID = ""


class PolymarketWithdrawBehaviour(DecisionMakerBaseBehaviour):
    """Sells every unredeemable Polymarket position via market FAK orders.

    Lifecycle (see WITHDRAWAL_POLYMARKET_IMPL_SPEC.md §3.1):

    1. Persist ``selling`` to the JSON store.
    2. Refresh CLOB balance/allowance (top-level retry).
    3. Fetch unredeemable positions (top-level retry).
    4. Filter to sellable shares (size > epsilon, has CTF token id).
    5. Per position: FAK sell, retry on partial / SDK errors (per-position retry).
    6. Append fill / error records as they happen.
    7. Persist ``complete`` (no errors) or ``errored`` (any errors), then finish.
    """

    matching_round = PolymarketWithdrawRound

    def async_act(self) -> Generator:
        """Run the sell-off."""
        self._set_state(WITHDRAWAL_STATE_SELLING)

        positions = yield from self._with_top_level_retry(
            "fetch_positions",
            self._request_fetch_positions,
        )
        if positions is None:
            self._set_state(WITHDRAWAL_STATE_ERRORED)
            yield from self._finish()
            return

        sellable = self._filter_sellable(positions)
        if not sellable:
            store = self._read_store()
            if store.get("withdrawal_errors"):
                self._set_state(WITHDRAWAL_STATE_ERRORED)
            else:
                self._set_state(WITHDRAWAL_STATE_COMPLETE)
            yield from self._finish()
            return

        self.context.logger.info(
            f"withdrawal: discovered {len(sellable)} unredeemable position(s)"
        )

        for position in sellable:
            yield from self._sell_one_position_with_retry(position)

        store = self._read_store()
        if store.get("withdrawal_errors"):
            self._set_state(WITHDRAWAL_STATE_ERRORED)
        else:
            self._set_state(WITHDRAWAL_STATE_COMPLETE)
        yield from self._finish()

    # ------------------------------------------------------------------ #
    # Top-level retry helper                                             #
    # ------------------------------------------------------------------ #

    def _with_top_level_retry(
        self,
        op_name: str,
        request_fn: Callable[[], Generator[None, None, Tuple[Any, Optional[str]]]],
    ) -> Generator[None, None, Optional[Any]]:
        """Run ``request_fn`` with up to N FAK-style retries.

        Returns the result on success; on exhaustion records a top-level
        error and returns ``None``.

        :param op_name: human-readable label written to the error record.
        :param request_fn: generator yielding ``(result, error)`` tuples.
        :yield: framework yields between attempts (sleep + nested generator).
        :return: the result on success; ``None`` once retries are exhausted.
        """
        backoff = self._retry_schedule()
        last_error: Optional[str] = "unknown"
        for attempt, sleep_s in enumerate(backoff):
            result, error = yield from request_fn()
            if error is None:
                return result
            last_error = error
            self.context.logger.warning(
                f"withdrawal: top-level retry {attempt + 1}/{len(backoff)} "
                f"on {op_name} reason={last_error!r}"
            )
            if attempt < len(backoff) - 1:
                yield from self.sleep(sleep_s)
        self._record_top_level_error(op_name, last_error or "unknown")
        return None

    # ------------------------------------------------------------------ #
    # Connection-side requests                                           #
    # ------------------------------------------------------------------ #

    def _request_fetch_positions(
        self,
    ) -> Generator[None, None, Tuple[Optional[List[Dict[str, Any]]], Optional[str]]]:
        """Send FETCH_ALL_POSITIONS with ``redeemable=False``."""
        payload = {
            "request_type": RequestType.FETCH_ALL_POSITIONS.value,
            "params": {"redeemable": False},
        }
        response = yield from self.send_polymarket_connection_request(payload)
        # The connection returns either a list of positions on success or an
        # error dict on failure — list responses cannot have an "error" key.
        if response is None:
            return None, "no response from connection"
        if isinstance(response, dict) and response.get("error"):
            return None, str(response["error"])
        return response, None

    def _request_sell(
        self,
        token_id: str,
        amount: float,
    ) -> Generator[None, None, Tuple[Optional[Dict[str, Any]], Optional[str]]]:
        """Send SELL_POSITION; return the normalized ``(response, error)`` tuple.

        :param token_id: the CTF token id to sell.
        :param amount: shares to sell on this attempt (may be the full size or
            a residual after a partial fill).
        :yield: framework yields between dispatch and response.
        :return: normalized ``(payload_dict, error_or_none)``.
        """
        params: Dict[str, Any] = {"token_id": token_id, "amount": amount}
        payload = {
            "request_type": RequestType.SELL_POSITION.value,
            "params": params,
        }
        response = yield from self.send_polymarket_connection_request(payload)
        return self._extract_response_or_error(response)

    @staticmethod
    def _extract_response_or_error(
        response: Any,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Coerce a connection-layer response into ``(payload, error)``.

        The connection returns ``{"error": "..."}`` on failure (preserving
        any extra keys like ``signed_order_json``) and a normal dict on
        success. ``None`` means dispatch / timeout failure.

        :param response: raw response from the polymarket connection layer.
        :return: a normalized ``(payload_dict_or_none, error_or_none)`` tuple.
        """
        if response is None:
            return None, "no response from connection"
        if isinstance(response, dict) and response.get("error"):
            return response, str(response["error"])
        return response, None

    # ------------------------------------------------------------------ #
    # Position filtering                                                 #
    # ------------------------------------------------------------------ #

    def _filter_sellable(self, positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop redeemable / dust / malformed positions; record drops as errors."""
        sellable: List[Dict[str, Any]] = []
        for p in positions:
            if p.get("redeemable", False):
                continue
            asset = p.get("asset")
            if not asset:
                self.context.logger.warning(
                    f"withdrawal: dropping position without asset id: {p!r}"
                )
                self._record_error(
                    TOP_LEVEL_ERROR_TOKEN_ID,
                    float(p.get("size") or 0.0),
                    "malformed position record (missing asset)",
                )
                continue
            try:
                size = float(p.get("size") or 0.0)
            except (TypeError, ValueError):
                self._record_error(
                    asset,
                    0.0,
                    "malformed position record (non-numeric size)",
                )
                continue
            if size <= DUST_EPSILON:
                continue
            sellable.append(p)
        return sellable

    # ------------------------------------------------------------------ #
    # Per-position retry loop                                            #
    # ------------------------------------------------------------------ #

    def _sell_one_position_with_retry(self, position: Dict[str, Any]) -> Generator:
        """Retry FAK sells until residual is gone or the schedule is exhausted.

        Each attempt re-signs a fresh order (no signed-order cache); the CLOB
        rejects resubmissions of an already-acknowledged signed order with
        ``order ... is invalid. Duplicated.``, so caching across retries is
        actively harmful for FAK kills.

        :param position: a single Polymarket position record (asset, size, ...).
        :yield: framework yields between FAK attempts and inter-attempt sleeps.
        """
        token_id = position["asset"]
        shares = float(position["size"])
        residual = shares
        total_filled = 0.0
        total_usdc = 0.0
        last_error: Optional[str] = None

        backoff = self._retry_schedule()
        self.context.logger.info(f"withdrawal: selling {token_id} size={shares}")

        for attempt, sleep_s in enumerate(backoff):
            response, error = yield from self._request_sell(token_id, residual)
            if error is not None:
                last_error = error
            else:
                resp = response or {}
                filled = float(resp.get("filled_shares") or 0.0)
                if filled > 0:
                    total_filled += filled
                    total_usdc += float(resp.get("filled_usdc") or 0.0)
                    residual -= filled
                if residual <= DUST_EPSILON:
                    fill_price = total_usdc / total_filled if total_filled > 0 else 0.0
                    self.context.logger.info(
                        f"withdrawal: sold {total_filled} of {token_id} "
                        f"@ {fill_price} (residual=0.0)"
                    )
                    self._record_fill(token_id, total_filled, fill_price)
                    return
                last_error = f"partial fill, residual={residual}"

            if attempt < len(backoff) - 1:
                self.context.logger.info(
                    f"withdrawal: FAK retry {attempt + 2}/{len(backoff)} "
                    f"for {token_id} residual={residual}"
                )
                yield from self.sleep(sleep_s)

        # Retries exhausted. Record the residual as an error; the on-chain
        # record (via get_trades) is the audit trail for what filled.
        reason = self._stuck_reason(last_error)
        self.context.logger.warning(
            f"withdrawal: stuck {residual} of {token_id} reason={reason!r}"
        )
        self._record_error(token_id, residual, reason)

    @staticmethod
    def _stuck_reason(last_error: Optional[str]) -> str:
        """Map the last loop-iteration error into a human-readable reason."""
        if last_error is None or last_error.startswith("partial fill"):
            return "no liquidity after FAK attempts"
        return f"sdk error: {last_error}"

    # ------------------------------------------------------------------ #
    # Configuration accessors                                            #
    # ------------------------------------------------------------------ #

    def _retry_schedule(self) -> List[int]:
        """Return the FAK backoff schedule from params."""
        return list(self.context.params.withdrawal_fak_backoff_s)

    # ------------------------------------------------------------------ #
    # Persistence (direct disk read/write — see spec §3.5 option A)      #
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
        # Match the existing repo convention (no atomic-write helper —
        # storage_manager.py, bet_placement.py, etc. all do the same).
        try:
            with open(self._store_path(), "w") as f:
                json.dump(store, f, indent=4)
        except OSError as e:
            self.context.logger.error(f"withdrawal: failed to write store: {e}")

    def _set_state(self, state: str) -> None:
        """Update ``withdrawal_state`` on disk and log the transition."""
        store = self._read_store()
        store["withdrawal_state"] = state
        self._write_store(store)
        self.context.logger.info(f"withdrawal: state -> {state}")

    def _record_fill(self, token_id: str, shares: float, fill_price: float) -> None:
        """Append a fill record to ``withdrawal_fills`` on disk."""
        store = self._read_store()
        fills = store.setdefault("withdrawal_fills", [])
        fills.append(
            {
                "token_id": token_id,
                "shares_sold": shares,
                "fill_price": fill_price,
                "ts": int(time.time()),
            }
        )
        self._write_store(store)

    def _record_error(
        self, token_id: str, shares_remaining: float, reason: str
    ) -> None:
        """Append an error record to ``withdrawal_errors`` on disk."""
        store = self._read_store()
        errors = store.setdefault("withdrawal_errors", [])
        errors.append(
            {
                "token_id": token_id,
                "shares_remaining": shares_remaining,
                "reason": reason,
                "ts": int(time.time()),
            }
        )
        self._write_store(store)

    def _record_top_level_error(self, op_name: str, reason: str) -> None:
        """Record a top-level error (no token_id) e.g. positions API down."""
        self.context.logger.error(
            f"withdrawal: top-level failure on {op_name} reason={reason!r}"
        )
        self._record_error(TOP_LEVEL_ERROR_TOKEN_ID, 0.0, f"{op_name}: {reason}")

    # ------------------------------------------------------------------ #
    # FSM hand-off                                                       #
    # ------------------------------------------------------------------ #

    def _finish(self) -> Generator:
        """Emit the consensus payload and route to the idle round."""
        payload = WithdrawalPayload(sender=self.context.agent_address, vote=True)
        yield from self.finish_behaviour(payload)
