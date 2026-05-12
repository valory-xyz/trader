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

"""Shared chatui JSON-store I/O for the Omen withdrawal sweep.

The Omen withdrawal flow is split across two behaviours — the
planning side (``OmenWithdrawBehaviour``) and the post-settlement
receipt parser (``PostOmenWithdrawBehaviour``). Both write into the
same chatui-side JSON store the FE reads, so they need the same
file I/O and the same record schemas. Pre-extraction those helpers
were duplicated verbatim across both files and had already drifted
(``_record_top_level_error`` accepted ``op_name`` in one file and
``reason`` in the other).
"""

import json
import time
from logging import Logger
from pathlib import Path
from typing import Any, Dict, List

from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    WithdrawablePosition,
)

# Sentinel ``token_id`` for store rows that don't map to a single
# position (top-level errors that affected the whole sweep). Bandit
# flags any bare string named with a ``TOKEN`` substring as a
# potential credential — it isn't one, it's the absence of a
# venue-specific identifier.
TOP_LEVEL_ERROR_TOKEN_ID = ""  # nosec B105


class OmenWithdrawalStore:
    """Disk-backed JSON store for the Omen withdrawal sweep.

    Encapsulates every read/write against the chatui-side
    ``chatui_param_store.json`` file. Defensive against missing or
    malformed files (returns an empty dict on read failures, logs and
    swallows write failures so a transient disk error doesn't crash
    the sweep behaviour).
    """

    def __init__(self, store_dir: Path, filename: str, logger: Logger) -> None:
        """Bind to a directory + filename + logger.

        :param store_dir: directory holding the chatui JSON store
            (typically ``self.context.params.store_path``).
        :param filename: store filename (typically
            ``CHATUI_PARAM_STORE``).
        :param logger: skill logger used for warn/error messages.
        """
        self._store_dir = store_dir
        self._filename = filename
        self._logger = logger

    def path(self) -> Path:
        """Return the absolute path of the chatui JSON store."""
        return self._store_dir / self._filename

    def read(self) -> Dict[str, Any]:
        """Load the store, returning ``{}`` on missing/malformed file."""
        try:
            with open(self.path(), "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    def write(self, store: Dict[str, Any]) -> None:
        """Persist the store; log on OS-level write failure."""
        try:
            with open(self.path(), "w") as f:
                json.dump(store, f, indent=4)
        except OSError as exc:
            self._logger.error(f"omen withdrawal: failed to write store: {exc}")

    def set_state(self, state: str) -> None:
        """Update ``withdrawal_state`` on disk and log the transition."""
        store = self.read()
        store["withdrawal_state"] = state
        self.write(store)
        self._logger.info(f"omen withdrawal: state -> {state}")

    def reset_session_records(self) -> None:
        """Clear ``withdrawal_fills`` and ``withdrawal_errors``.

        Called at the start of a fresh sweep so the FE doesn't show
        rows from a prior session.
        """
        store = self.read()
        store["withdrawal_fills"] = []
        store["withdrawal_errors"] = []
        self.write(store)

    def record_fill(self, event: Dict[str, Any]) -> None:
        """Append a fill record from a decoded ``FPMMSell`` event.

        Computes a display-friendly ``fill_price`` (wxDAI per share)
        for the FE without having to redo the math.

        :param event: a single decoded FPMMSell event as returned by
            :func:`packages.valory.contracts.market_maker.contract.\
parse_sell_events`.
        """
        outcome_tokens_sold = int(event.get("outcome_tokens_sold", 0))
        return_amount = int(event.get("return_amount", 0))
        fee_amount = int(event.get("fee_amount", 0))
        shares_sold = outcome_tokens_sold / 1e18
        fill_price = (return_amount / 1e18) / shares_sold if shares_sold > 0 else 0.0
        store = self.read()
        fills = store.setdefault("withdrawal_fills", [])
        fills.append(
            {
                # token_id derivation requires position-id keccak; the FE
                # tolerates an empty string and uses (fpmm, outcome_index)
                # for display. The OmenWithdrawBehaviour planning step
                # captures the decimal position id in its error records;
                # fills only need the venue-specific identifier pair.
                "token_id": TOP_LEVEL_ERROR_TOKEN_ID,
                "shares_sold": shares_sold,
                "fill_price": fill_price,
                "ts": int(time.time()),
                "fpmm": event.get("fpmm"),
                "outcome_index": int(event.get("outcome_index", 0)),
                "return_amount": return_amount / 1e18,
                "fee_amount": fee_amount / 1e18,
            }
        )
        self.write(store)

    def record_error(self, position: WithdrawablePosition, reason: str) -> None:
        """Append an error record for a per-position drop.

        :param position: the position that couldn't be included in the
            sweep multisend (e.g. ``calcSellAmount`` reverted, halve
            attempts exhausted).
        :param reason: short human-readable reason; goes verbatim into
            the FE row.
        """
        store = self.read()
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
        self.write(store)
        self._logger.warning(
            f"omen withdrawal: drop {position.fpmm_address} "
            f"outcome={position.outcome_index} reason={reason!r}"
        )

    def record_top_level_error(self, reason: str) -> None:
        """Record an error that affected the whole sweep (no per-position attribution).

        :param reason: complete reason string for the FE row. Callers
            in ``OmenWithdrawBehaviour`` pass a composed message like
            ``f"{op_name}: retries exhausted"``; the post-settlement
            side passes a free-form message describing the receipt
            failure.
        """
        store = self.read()
        errors = store.setdefault("withdrawal_errors", [])
        errors.append(
            {
                "token_id": TOP_LEVEL_ERROR_TOKEN_ID,
                "shares_remaining": 0.0,
                "reason": reason,
                "ts": int(time.time()),
            }
        )
        self.write(store)
        self._logger.error(f"omen withdrawal: top-level failure: {reason}")

    def has_errors(self) -> bool:
        """Return ``True`` if any errors were persisted in this session."""
        return bool(self.read().get("withdrawal_errors"))

    def record_planned_fpmms(self, fpmms: List[str]) -> None:
        """Persist the FPMM addresses the sweep planned to sell against.

        Used as the allowlist for post-settlement receipt parsing —
        without it, an FPMMSell event emitted by a non-target FPMM in
        the same receipt (e.g. via a future cross-contract hook) would
        silently land in the operator-visible fill audit trail.
        Addresses are stored lower-cased so receipt-side comparisons
        don't need to worry about checksum casing.

        :param fpmms: FPMM addresses the multisend will sell on.
        """
        store = self.read()
        store["planned_fpmms"] = sorted({addr.lower() for addr in fpmms if addr})
        self.write(store)

    def planned_fpmms(self) -> List[str]:
        """Return the persisted planned-FPMM allowlist (or empty if missing)."""
        return list(self.read().get("planned_fpmms") or [])
