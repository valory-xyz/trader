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

"""Shared DepositWallet state and relayer helpers for the Polymarket behaviours."""

import json
from abc import ABC
from typing import Any, Generator, Optional, cast

from packages.valory.connections.polymarket_client.connection import (
    PUBLIC_ID as POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID,
)
from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)

DEPOSIT_WALLET_STORE = "deposit_wallet.json"


class PolymarketDepositWalletBehaviour(DecisionMakerBaseBehaviour, ABC):
    """Shared DepositWallet state + relayer-proxy helpers for the CLOB v2 flows.

    The DepositWallet is provisioned (deploy + trading approvals) once by
    ``PolymarketSetApprovalBehaviour``; the top-up / withdrawal flows only
    resolve the recorded DW and relay calls through the proxy. The SRR request
    wrapper and the ``deposit_wallet.json`` read/write/invalidate/resolve
    helpers are shared here to avoid duplication across those behaviours.
    """

    def _send_polymarket_request(
        self, request_type: RequestType, params: dict
    ) -> Generator[None, None, Optional[Any]]:
        """Send an SRR request to the Polymarket connection and return its JSON.

        :param request_type: the connection request type.
        :param params: request parameters.
        :yield: framework yields between dispatch and the connection response.
        :return: the parsed response (dict or list), or ``None`` on error.
        """
        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)
        srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps({"request_type": request_type.value, "params": params}),
        )
        response = yield from self.do_connection_request(srr_message, srr_dialogue)
        if response is None or response.error:
            # ``SrrMessage.error`` is a bool flag; the human-readable detail
            # lives in the payload (the connection sets it to ``{"error": ...}``
            # on failure), so surface that rather than the uninformative ``True``.
            error_msg = (
                self._extract_error_message(response.payload)
                if response
                else "No response from Polymarket client"
            )
            self.context.logger.error(
                f"{request_type.value} request failed: {error_msg}"
            )
            return None
        return json.loads(response.payload)

    @staticmethod
    def _extract_error_message(payload: Optional[str]) -> str:
        """Pull a human-readable error out of a connection error payload.

        :param payload: the raw SRR response payload (JSON string or ``None``).
        :return: the ``error`` field when the payload is an error dict, else the
            raw payload, else a generic fallback.
        """
        if not payload:
            return "unspecified error"
        try:
            decoded = json.loads(payload)
        except (ValueError, TypeError):
            return payload
        if isinstance(decoded, dict) and decoded.get("error"):
            return str(decoded["error"])
        return payload

    def _position_token_ids(self) -> list:
        """Best-effort integer CTF outcome token ids of the sampled bet.

        Used by the post-buy sweep and the top-up's opportunistic sweep so the
        bought outcome token(s) are moved out of the transient DW alongside the
        pUSD. Returns ``[]`` when no bet is sampled (e.g. an opportunistic
        empty-DW sweep), in which case only pUSD is swept.

        :return: the integer CTF token ids, or ``[]`` when unavailable.
        """
        try:
            token_map = self.sampled_bet.outcome_token_ids or {}
        except Exception:  # noqa: BLE001 — best-effort token id retrieval
            self.context.logger.warning("Failed to retrieve outcome token IDs.")
            return []
        ids = []
        for tid in token_map.values():
            try:
                ids.append(int(tid))
            except (TypeError, ValueError):
                self.context.logger.warning(f"Invalid token ID '{tid}' skipped.")
                continue
        return ids

    def _read_deposit_wallet_file(self) -> Optional[dict]:
        """Read the persisted DepositWallet state, if any.

        :return: the parsed ``deposit_wallet.json`` dict, or ``None``.
        """
        path = self.params.store_path / DEPOSIT_WALLET_STORE
        try:
            with open(path) as f:
                return cast(dict, json.load(f))
        except (OSError, ValueError):
            return None

    def _write_deposit_wallet_file(
        self, dw_address: str, dw_owner: Optional[str], approvals_done: bool
    ) -> None:
        """Persist the DepositWallet state for the setup gate / self-heal.

        :param dw_address: the resolved DepositWallet address.
        :param dw_owner: the DW owner (current agent EOA).
        :param approvals_done: whether the DW trading approvals have been
            confirmed mined; only ``True`` once the relayer tx has settled.
        """
        path = self.params.store_path / DEPOSIT_WALLET_STORE
        data = {
            "dw_address": dw_address,
            "dw_owner": dw_owner,
            "approvals_done": approvals_done,
        }
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            self.context.logger.error(f"Failed to write {DEPOSIT_WALLET_STORE}: {e}")

    def _invalidate_deposit_wallet_file(self) -> None:
        """Remove the persisted DepositWallet state to force a fresh deploy.

        Called when the on-chain owner no longer matches the agent EOA while
        the persisted state still claims a match (optimistic / stale write):
        deleting the cache routes ``_resolve_or_deploy_dw`` back onto the
        ``DEPLOY_DW`` path on the next setup pass.
        """
        path = self.params.store_path / DEPOSIT_WALLET_STORE
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            self.context.logger.error(f"Failed to remove {DEPOSIT_WALLET_STORE}: {e}")

    def _resolve_deposit_wallet(self) -> Optional[str]:
        """Resolve the DepositWallet address for the agent EOA.

        Prefers the address agreed in synchronized data; otherwise falls back
        to the persisted ``deposit_wallet.json`` (owner-checked) written by the
        setup round. Provisioning (deploy + trading approvals) is owned by
        ``PolymarketSetApprovalBehaviour`` and guaranteed by the setup gate to
        have run; this only resolves the recorded DW and defers (returns
        ``None``) when it is not yet available.

        :return: the DepositWallet address, or ``None`` if not yet available.
        """
        dw = self.synchronized_data.deposit_wallet_address
        if dw:
            return dw
        persisted = self._read_deposit_wallet_file()
        agent_eoa = self.context.agent_address
        if (
            persisted
            and persisted.get("dw_address")
            and str(persisted.get("dw_owner") or "").lower() == agent_eoa.lower()
        ):
            return persisted["dw_address"]
        return None
