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
TOP_LEVEL_ERROR_TOKEN_ID = ""  # nosec B105

# Backoffs for polling get_order after a post_order ``delayed`` response.
# CLOB defers async matching for FAK orders; the post reply returns before
# the matching engine resolves. Polling client.get_order(order_id) reads the
# authoritative on-CLOB state. Total wait ≈ 122s before declaring the order
# in-flight. Live trace observed a match completing ~43s after post_order, so
# the cap was bumped from 32s to give ~3× headroom; on genuine exhaustion the
# behaviour signals ``in_flight`` and defers the position to the next sweep
# cycle rather than racing the in-flight match.
DELAYED_ORDER_POLL_BACKOFFS_S: Tuple[float, ...] = (2.0, 5.0, 10.0, 15.0, 30.0, 60.0)
# get_order returns ORDER_STATUS_* enum strings (different vocabulary than
# post_order's lowercase ``matched``/``delayed``/``unmatched``). LIVE is the
# only non-terminal value; everything else means we can stop polling.
GET_ORDER_TERMINAL_STATUSES = frozenset(
    {
        "ORDER_STATUS_MATCHED",
        "ORDER_STATUS_CANCELED",
        "ORDER_STATUS_INVALID",
        "ORDER_STATUS_CANCELED_MARKET_RESOLVED",
    }
)
# Terminal status vocabulary observed empirically from get_order responses.
# Permanent-failure values (``invalid``, ``market_resolved``) short-circuit
# the per-position retry loop because retrying them is mathematically
# guaranteed to fail. ``canceled`` stays in the retryable bucket — without
# production data we cannot distinguish FAK kills from external cancels.
# Unrecognized values fall through to ``unmatched`` (retryable) defensively.
TERMINAL_STATUS_MAP = {
    "ORDER_STATUS_MATCHED": "matched",
    "ORDER_STATUS_CANCELED": "canceled",
    "ORDER_STATUS_INVALID": "invalid",
    "ORDER_STATUS_CANCELED_MARKET_RESOLVED": "market_resolved",
}
PERMANENT_FAILURE_STATUSES = frozenset({"invalid", "market_resolved"})
# Polymarket CTF tokens use 6-decimal fixed-point scaling for share amounts
# in the get_order payload's ``size_matched`` field.
CTF_DECIMAL_FACTOR = 10**6


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
        # Reset per-session records so the GET endpoint and end-of-sweep
        # state reflect THIS sweep only. Without this, an automatic
        # re-entry (flag still True after a prior errored sweep) would
        # carry forward stale errors and force every subsequent sweep to
        # end ``errored`` regardless of its actual outcome. Mirrors the
        # POST handler's idle → armed reset.
        self._reset_session_records()

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

    def _request_get_order(
        self,
        order_id: str,
    ) -> Generator[None, None, Tuple[Optional[Dict[str, Any]], Optional[str]]]:
        """Issue a single GET_ORDER lookup against the connection.

        :param order_id: CLOB order id to look up.
        :yield: framework yields between dispatch and response.
        :return: ``(order_payload_or_none, error_or_none)``. The payload is
            the raw ``client.get_order`` response (may be a falsy/None body
            if the data API hasn't indexed the order yet).
        """
        payload = {
            "request_type": RequestType.GET_ORDER.value,
            "params": {"order_id": order_id},
        }
        response = yield from self.send_polymarket_connection_request(payload)
        return self._extract_response_or_error(response)

    def _poll_order_until_terminal_cooperative(
        self,
        order_id: str,
    ) -> Generator[None, None, Tuple[Optional[Dict[str, Any]], Optional[str]]]:
        """Drive the cooperative poll loop for a delayed order.

        Uses ``yield from self.sleep(...)`` between polls so the connection's
        worker thread is free to serve other consumers during the wait.

        Three return shapes distinguish the outcome:

        - ``(terminal_payload, None)`` — terminal status reached.
        - ``(None, None)`` — cap exhausted while still LIVE (in_flight defer).
        - ``(None, error_string)`` — every poll attempt errored, distinct
          from a LIVE-exhausted in_flight. Lets the caller record the
          parent position with a "polymarket API unreachable" reason
          rather than the misleading in-flight defer reason.

        :param order_id: CLOB order id to look up.
        :yield: framework yields between cooperative sleeps and dispatch.
        :return: tuple of ``(terminal_payload_or_none, error_string_or_none)``.
        """
        error_count = 0
        last_error: Optional[str] = None
        for backoff_s in DELAYED_ORDER_POLL_BACKOFFS_S:
            yield from self.sleep(backoff_s)
            order, error = yield from self._request_get_order(order_id)
            if error is not None:
                error_count += 1
                last_error = error
                self.context.logger.warning(
                    f"withdrawal: get_order failed for {order_id}: {error}"
                )
                continue
            # The SDK can return ``None`` shortly after ``post_order`` —
            # the data API hasn't indexed the new order yet. Keep polling
            # rather than crash on ``.get()``.
            if not order:
                continue
            status = order.get("status") or ""
            if status in GET_ORDER_TERMINAL_STATUSES:
                return order, None
        # exhausted
        if error_count == len(DELAYED_ORDER_POLL_BACKOFFS_S):
            return None, (
                f"all {error_count} poll attempts errored " f"(last: {last_error})"
            )
        self.context.logger.warning(
            f"withdrawal: order {order_id} still delayed after poll exhausted"
        )
        return None, None

    def _fill_from_terminal_get_order(
        self, order: Dict[str, Any], order_id: str
    ) -> Dict[str, Any]:
        """Compute fill response fields from a terminal ``get_order`` payload.

        ``size_matched`` is fixed-math 6-decimal shares; ``price`` is decimal
        USDC/share (the order's price field, used as an approximation of the
        fill price — for a multi-level fill this may diverge from VWAP, but
        the value is operator-reporting-only and not used in any decision
        logic).

        Maps the raw ``ORDER_STATUS_*`` value to a normalized status the
        per-position retry loop can branch on. Unmapped values fall through
        to ``"unmatched"`` (retryable) so an SDK contract change introducing
        a new status doesn't crash the sweep — instead a warning is logged
        so the new status can be added to the map deliberately.

        :param order: terminal ``get_order`` payload.
        :param order_id: order id (passthrough; ``order['id']`` may be unset).
        :return: response dict matching ``_request_sell``'s return shape.
        """
        size_matched_raw = order.get("size_matched") or "0"
        price_str = order.get("price") or "0"
        try:
            filled_shares = int(size_matched_raw) / CTF_DECIMAL_FACTOR
        except (ValueError, TypeError) as e:
            error_msg = (
                f"size_matched={size_matched_raw!r} not parseable as "
                f"6-decimal fixed-point int: {e}"
            )
            self.context.logger.error(error_msg)
            return {"error": error_msg}
        try:
            fill_price = float(price_str)
        except (ValueError, TypeError) as e:
            error_msg = f"price={price_str!r} not parseable as float: {e}"
            self.context.logger.error(error_msg)
            return {"error": error_msg}
        filled_usdc = filled_shares * fill_price
        status_raw = order.get("status") or ""
        status_norm = TERMINAL_STATUS_MAP.get(status_raw)
        if status_norm is None:
            self.context.logger.warning(
                f"withdrawal: unrecognized terminal status {status_raw!r}; "
                "treating as unmatched (retryable). Possibly an SDK contract "
                "change — verify against current Polymarket CLOB behaviour."
            )
            status_norm = "unmatched"
        return {
            "order_id": order_id,
            "status": status_norm,
            "filled_shares": filled_shares,
            "filled_usdc": filled_usdc,
            "fill_price": fill_price,
            "raw": order,
        }

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

        max_attempts = self.context.params.withdrawal_max_fak_attempts
        backoff = self._retry_schedule()  # length == max_attempts - 1
        self.context.logger.info(f"withdrawal: selling {token_id} size={shares}")

        for attempt in range(max_attempts):
            response, error = yield from self._request_sell(token_id, residual)
            if error is not None:
                last_error = error
            else:
                resp = response or {}
                # Async-match path: post_order returned ``delayed``. Drive
                # the cooperative poll loop here (rather than blocking the
                # connection's worker thread); transform the terminal
                # payload into the same shape the synchronous path would
                # return so the rest of the loop body is unaware of which
                # path produced ``resp``.
                if resp.get("status") == "delayed" and resp.get("order_id"):
                    order_id = resp["order_id"]
                    terminal, poll_error = (
                        yield from self._poll_order_until_terminal_cooperative(order_id)
                    )
                    if poll_error is not None:
                        # Every poll attempt errored — distinct from an
                        # in-flight defer. The Polymarket API was unreachable
                        # for the entire poll window, so retrying the SELL
                        # would race whatever the chain settled. Record a
                        # distinct reason so the diagnostic doesn't masquerade
                        # as an in-flight match.
                        self._flush_position_records(
                            token_id,
                            total_filled,
                            total_usdc,
                            residual,
                            error_reason=(
                                f"polymarket API unreachable during poll: {poll_error}"
                            ),
                        )
                        return
                    if terminal is None:
                        # Poll exhausted while still LIVE: retrying with the
                        # full residual would race the in-flight match and
                        # hit ``not enough balance`` once it lands. Defer
                        # this position to the next sweep cycle. Record a
                        # deferred error so the sweep ends ``errored`` and
                        # operator restart does NOT auto-resume betting
                        # before the in-flight order resolves.
                        self.context.logger.info(
                            f"withdrawal: order {order_id} in-flight after poll "
                            f"exhausted; deferring {token_id} to next sweep cycle"
                        )
                        self._flush_position_records(
                            token_id,
                            total_filled,
                            total_usdc,
                            residual,
                            error_reason=(
                                "in-flight after CLOB delayed-poll exhausted; "
                                "will resolve next sweep cycle"
                            ),
                        )
                        return
                    resp = self._fill_from_terminal_get_order(terminal, order_id)
                    # Parse failure on the terminal payload: surface as a
                    # position-level error rather than silently dropping
                    # to a "no fill" iteration. The on-chain state is now
                    # ambiguous (we received a payload but couldn't read
                    # it), so retrying with the full residual would risk
                    # racing whatever the chain settled. Record and move on.
                    if resp.get("error"):
                        self._flush_position_records(
                            token_id,
                            total_filled,
                            total_usdc,
                            residual,
                            error_reason=f"sdk error: {resp['error']}",
                        )
                        return
                    # Permanent-failure terminal statuses: retrying is
                    # mathematically guaranteed to fail. INVALID = signer
                    # mismatch (re-signing produces an identical payload,
                    # same rejection). MARKET_RESOLVED = market settled,
                    # liquidity is gone forever. Short-circuit the FAK
                    # retry loop and record an error for the residual.
                    if resp.get("status") in PERMANENT_FAILURE_STATUSES:
                        permanent_status = resp.get("status")
                        self.context.logger.info(
                            f"withdrawal: terminal status={permanent_status} "
                            f"for {token_id}; short-circuiting retry loop"
                        )
                        self._flush_position_records(
                            token_id,
                            total_filled,
                            total_usdc,
                            residual,
                            error_reason=(
                                f"permanent terminal status: {permanent_status}"
                            ),
                        )
                        return
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
                    self._flush_position_records(
                        token_id,
                        total_filled,
                        total_usdc,
                        residual,
                        error_reason=None,
                    )
                    return
                last_error = f"partial fill, residual={residual}"

            # ``backoff[attempt]`` is the gap AFTER attempt ``attempt``. No
            # sleep after the final attempt — the loop is exiting anyway.
            if attempt < max_attempts - 1:
                self.context.logger.info(
                    f"withdrawal: FAK retry {attempt + 2}/{max_attempts} "
                    f"for {token_id} residual={residual}"
                )
                yield from self.sleep(backoff[attempt])

        # Retries exhausted. Record the residual (and any partial fills) so
        # the operator-facing audit trail is symmetric across exit paths.
        # The on-chain record (via get_trades) is the authoritative source
        # for what filled.
        reason = self._stuck_reason(last_error)
        self.context.logger.warning(
            f"withdrawal: stuck {residual} of {token_id} reason={reason!r}"
        )
        self._flush_position_records(
            token_id, total_filled, total_usdc, residual, error_reason=reason
        )

    @staticmethod
    def _stuck_reason(last_error: Optional[str]) -> str:
        """Map the last loop-iteration error into a human-readable reason."""
        if last_error is None or last_error.startswith("partial fill"):
            return "no liquidity after FAK attempts"
        return f"sdk error: {last_error}"

    def _flush_position_records(
        self,
        token_id: str,
        total_filled: float,
        total_usdc: float,
        residual: float,
        error_reason: Optional[str],
    ) -> None:
        """Emit fill + residual-error records at any per-position loop exit.

        Normalizes the per-position exit paths (clean success / in_flight
        defer / retries exhausted / permanent-status short-circuit / parse
        failure) so a partial fill is always written when ``total_filled > 0``,
        independent of whether the residual sold or stuck. Without this,
        the in_flight and exhaustion paths would silently drop accumulated
        partial fills from prior FAK attempts.

        :param token_id: the CTF token id this loop iteration targeted.
        :param total_filled: accumulated filled shares across all attempts.
        :param total_usdc: accumulated USDC received across all attempts.
        :param residual: shares still unsold after the loop's final attempt.
        :param error_reason: human-readable reason for the residual; ``None``
            on clean success (``residual <= DUST_EPSILON``).
        """
        if total_filled > 0:
            fill_price = total_usdc / total_filled
            self._record_fill(token_id, total_filled, fill_price)
        if error_reason is not None and residual > DUST_EPSILON:
            self._record_error(token_id, residual, error_reason)

    # ------------------------------------------------------------------ #
    # Configuration accessors                                            #
    # ------------------------------------------------------------------ #

    def _retry_schedule(self) -> List[float]:
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

    def _reset_session_records(self) -> None:
        """Clear ``withdrawal_fills`` and ``withdrawal_errors`` on disk."""
        store = self._read_store()
        store["withdrawal_fills"] = []
        store["withdrawal_errors"] = []
        self._write_store(store)

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
        """Emit the consensus payload and route to the idle round.

        Snapshots the current locked-funds value into the agent
        performance summary so ``GET /api/v1/agent/performance``
        reflects the post-sweep state without waiting for the next
        normal performance refresh round (which could take minutes via
        the subgraph cycle). This is the only code path that knows
        ``I just changed on-chain positions; the cached value is now
        stale``, so the behaviour is the natural trigger.

        :yield: framework yields between snapshot dispatch and the
            consensus payload emission.
        """
        yield from self._snapshot_locked_funds()
        payload = WithdrawalPayload(sender=self.context.agent_address, vote=True)
        yield from self.finish_behaviour(payload)

    def _snapshot_locked_funds(self) -> Generator:
        """Best-effort: fetch current positions and update the perf summary.

        Failure to fetch (transient API issue, persistent outage) is
        non-fatal — log a warning and skip; the performance summary
        keeps its previous value, which gets overwritten by the next
        normal performance-summary round. The sweep terminal state is
        still emitted via the regular ``finish_behaviour`` payload.

        :yield: framework yields between dispatch and response.
        """
        positions, error = yield from self._request_fetch_positions()
        if error is not None or positions is None:
            self.context.logger.warning(
                f"withdrawal: skipping locked-funds snapshot "
                f"(fetch failed: {error})"
            )
            return
        locked = sum(
            float(p.get("size") or 0) * float(p.get("curPrice") or 0)
            for p in positions
            if not p.get("redeemable", False)
        )
        self.context.logger.info(
            f"withdrawal: snapshotting funds_locked_in_markets={locked}"
        )
        self.context.state.update_funds_locked_in_markets(locked)
