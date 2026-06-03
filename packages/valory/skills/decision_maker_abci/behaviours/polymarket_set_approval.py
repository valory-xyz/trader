# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""This module contains the behaviour for sampling a bet."""

import json
from typing import Any, Generator, Optional, cast

from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.connection import (
    PUBLIC_ID as POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID,
)
from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.contracts.deposit_wallet.contract import DepositWalletContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import MultisendBatch
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    PolymarketDepositWalletBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketSetApprovalPayload,
)
from packages.valory.skills.decision_maker_abci.states.polymarket_set_approval import (
    PolymarketSetApprovalRound,
)

# Cooperative-poll backoffs (seconds) for confirming a relayer tx mined.
# Sums to ~4 min — comfortably above the observed relayer mining latency while
# bounding how long a single setup pass spins before deferring to the next one.
RELAYER_TX_POLL_BACKOFFS_S = [5, 5, 10, 10, 15, 15, 20, 20, 30, 30, 30, 30]


class PolymarketSetApprovalBehaviour(PolymarketDepositWalletBehaviour):
    """A behaviour in which the agents set approval for Polymarket."""

    matching_round = PolymarketSetApprovalRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # CLOB v2: provision the DepositWallet and set its trading approvals
            # (pUSD allowance + CTF operator rights to the V2 Exchange,
            # NegRiskAdapter, NegRiskCTFExchange) via the relayer proxy. The
            # Safe keeps only the redemption approvals, built below.
            yield from self._provision_deposit_wallet()

            # Check if builder program is enabled
            if self.context.params.polymarket_builder_program_enabled:
                self.context.logger.info(
                    "Polymarket builder program enabled - calling connection to set approvals..."
                )
                # Call the polymarket client to set approvals
                yield from self._set_approval()
            else:
                self.context.logger.info(
                    "Polymarket builder program disabled - preparing approval transaction..."
                )
                # Prepare Safe transaction for approvals
                tx_submitter = self.matching_round.auto_round_id()
                tx_hash = yield from self._prepare_approval_tx()

                self.payload = PolymarketSetApprovalPayload(
                    self.context.agent_address,
                    tx_submitter,
                    tx_hash,
                    False,
                )

        yield from self.finish_behaviour(self.payload)

    def _set_approval(self) -> Generator[None, None, None]:
        """Set approval for Polymarket contracts."""
        # Get SRR dialogues
        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)

        # Create the request payload
        polymarket_set_approval_payload = {
            "request_type": RequestType.SET_APPROVAL.value,
            "params": {},
        }

        # Create the SRR message
        srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(polymarket_set_approval_payload),
        )

        # Send the request and wait for response
        response = yield from self.do_connection_request(srr_message, srr_dialogue)

        if response is None or response.error:
            error_msg = (
                response.error if response else "No response from Polymarket client"
            )
            self.context.logger.error(f"Error setting approvals: {error_msg}")
            self.payload = PolymarketSetApprovalPayload(
                self.context.agent_address,
                None,
                None,
                False,
            )
            return

        # Parse the response
        response_json = json.loads(response.payload)
        self.context.logger.info(f"Set approval response: {response_json}")

        # Check if the approval was successful
        success = response_json is not None and not response.error

        if success:
            self.context.logger.info(
                "Successfully set approvals for Polymarket contracts!"
            )
            self.context.logger.info(f"Transaction data: {response_json}")
        else:
            self.context.logger.error(f"Failed to set approvals: {response_json}")

        # Create the payload
        self.payload = PolymarketSetApprovalPayload(
            self.context.agent_address,
            None,
            None,
            False,
        )

    def _provision_deposit_wallet(self) -> Generator[None, None, None]:
        """Provision the DepositWallet and set its trading approvals.

        Resolves the DW (persisted state or a fresh relayer deploy whose mined
        address is read from the deploy receipt), then applies the DW trading
        approvals via ``EXEC_WALLET_BATCH`` and waits for that relayer tx to
        mine — so the agent never reaches bet placement before the allowances
        exist. Failures are logged and non-fatal; the setup gate re-enters on a
        later pass.

        :yield: framework yields between the relayer requests it drives.
        """
        dw_address = yield from self._resolve_or_deploy_dw()
        if not dw_address:
            self.context.logger.info(
                "DepositWallet not yet provisioned; setup will retry next pass."
            )
            return

        agent_eoa = self.context.agent_address
        persisted = self._read_deposit_wallet_file()
        owner = yield from self._verify_dw_owner(dw_address)
        if owner is not None and owner.lower() != agent_eoa.lower():
            self.context.logger.warning(
                f"DepositWallet {dw_address} on-chain owner {owner} != agent EOA "
                f"{agent_eoa} (rotation / stale state); invalidating persisted "
                "state to force a fresh deploy on the next pass."
            )
            self._invalidate_deposit_wallet_file()
            return
        # If ownership cannot be read AND there is no trusted prior record,
        # defer rather than approve a DW we might not control (a transient RPC
        # failure on a first-ever provision). A persisted ``dw_owner`` (written
        # from the deploy receipt) is the trusted bootstrap when the live read
        # is unavailable.
        if owner is None and not (persisted and persisted.get("dw_owner")):
            self.context.logger.warning(
                f"DepositWallet {dw_address} owner could not be verified and no "
                "prior record exists; deferring approvals until ownership is "
                "confirmed."
            )
            return
        # Skip the (idempotent) approvals batch when it is already recorded done
        # for this DW — otherwise every setup re-entry re-submits 6 relayer calls
        # and burns the full ~4-minute mine-confirmation backoff.
        if persisted and persisted.get("approvals_done"):
            self.context.logger.info(
                f"DepositWallet {dw_address} trading approvals already recorded; "
                "skipping re-approval."
            )
            return

        approvals_resp = yield from self._send_polymarket_request(
            RequestType.EXEC_WALLET_BATCH,
            {
                "dw_address": dw_address,
                "transactions": self._build_dw_trading_approvals(),
            },
        )
        if approvals_resp is None:
            self.context.logger.warning(
                f"DepositWallet {dw_address} trading approvals failed; will retry."
            )
            return

        tx_id = approvals_resp.get("transaction_id")
        if not tx_id:
            # No relayer tx id means the batch was not submitted; never mark the
            # DW approved without a mined confirmation (otherwise every later FAK
            # sell would fail with "insufficient allowance" and no clear cause).
            self.context.logger.warning(
                f"DepositWallet {dw_address} approvals response carried no "
                "transaction_id; retrying on the next pass."
            )
            return
        mined = yield from self._await_relayer_tx(tx_id)
        if not (mined and mined.get("ok")):
            self.context.logger.warning(
                f"DepositWallet {dw_address} approvals tx {tx_id} not confirmed "
                "mined; the post-approval gate will re-check and retry."
            )
            return
        # Persist approvals completion only now that the relayer tx is confirmed
        # mined, recording the on-chain-verified owner when available.
        self._write_deposit_wallet_file(
            dw_address, owner or agent_eoa, approvals_done=True
        )
        self.context.logger.info(f"DepositWallet {dw_address} trading approvals mined.")

    def _resolve_or_deploy_dw(self) -> Generator[None, None, Optional[str]]:
        """Resolve the DepositWallet, deploying + discovering it when absent.

        Prefers persisted state whose owner matches the current agent EOA;
        otherwise submits a relayer deploy and waits for it to mine, reading
        the new DW address from the deploy receipt and persisting it.

        :yield: framework yields between the relayer deploy/poll requests.
        :return: the DepositWallet address, or ``None`` if not yet available.
        """
        persisted = self._read_deposit_wallet_file()
        agent_eoa = self.context.agent_address
        if (
            persisted
            and persisted.get("dw_address")
            and str(persisted.get("dw_owner") or "").lower() == agent_eoa.lower()
        ):
            # Fast path returns before any ``yield``; this is still a generator
            # (the deploy path below yields) and ``yield from`` handles the
            # zero-suspend return via ``StopIteration.value`` correctly.
            return persisted["dw_address"]

        deploy_resp = yield from self._send_polymarket_request(
            RequestType.DEPLOY_DW, {}
        )
        if deploy_resp is None:
            return None
        # An already-registered DW is returned directly. ``approvals_done=False``
        # records "not yet confirmed for this resolution" (we have no trusted
        # record here); ``_provision_deposit_wallet`` then re-applies the
        # idempotent approvals batch — safe if they were already set.
        if deploy_resp.get("dw_address") and deploy_resp.get("deployed"):
            dw = deploy_resp["dw_address"]
            self._write_deposit_wallet_file(
                dw, deploy_resp.get("owner"), approvals_done=False
            )
            return dw

        tx_id = deploy_resp.get("transaction_id")
        if not tx_id:
            return None
        mined = yield from self._await_relayer_tx(tx_id, is_deploy=True)
        if mined and mined.get("ok") and mined.get("dw_address"):
            dw = mined["dw_address"]
            self._write_deposit_wallet_file(dw, agent_eoa, approvals_done=False)
            return dw
        if mined and mined.get("ok"):
            self.context.logger.warning(
                f"DepositWallet deploy tx {tx_id} mined but the DW address could "
                "not be read from the receipt; re-resolving on the next pass."
            )
            return None
        self.context.logger.info(
            f"DepositWallet deploy tx {tx_id} not yet mined; deferring."
        )
        return None

    def _await_relayer_tx(
        self, tx_id: str, is_deploy: bool = False
    ) -> Generator[None, None, Optional[dict]]:
        """Cooperatively poll a relayer tx until it reaches a terminal state.

        Drives the backoff loop behaviour-side (one ``RELAYER_TX`` request per
        iteration) so the connection worker is never blocked for the full
        settlement window.

        :param tx_id: the relayer transaction id to poll.
        :param is_deploy: whether this tx is a DW deploy (vs an approval batch).
            Only deploy polls scan the receipt for the new DW address; approval
            batches share the ``to=DW_FACTORY`` target and must not bind a funder.
        :yield: framework yields between each poll request and backoff sleep.
        :return: the terminal poll response (``{"ok", "dw_address", ...}``), or
            ``None`` if it did not settle within the backoff budget.
        """
        last = len(RELAYER_TX_POLL_BACKOFFS_S) - 1
        for idx, backoff in enumerate(RELAYER_TX_POLL_BACKOFFS_S):
            resp = yield from self._send_polymarket_request(
                RequestType.RELAYER_TX,
                {"transaction_id": tx_id, "is_deploy": is_deploy},
            )
            if resp is not None and resp.get("terminal"):
                return resp
            # No sleep after the final poll — the loop is exiting anyway.
            if idx < last:
                yield from self.sleep(backoff)
        return None

    def _verify_dw_owner(self, dw_address: str) -> Generator[None, None, Optional[str]]:
        """Read the DepositWallet ``owner`` on-chain.

        Best-effort rotation / stale-state probe: returns the owner address so
        the caller can compare it against the current agent EOA. A mismatch
        signals a mnemonic-recovery rotation or stale persisted state, on which
        the caller invalidates the cached DW to force a fresh deploy. Returns
        ``None`` when the owner cannot be read (e.g. the DW is still deploying),
        in which case the caller proceeds optimistically.

        :param dw_address: the DepositWallet to read.
        :yield: framework yields between the contract-API dispatch and response.
        :return: the on-chain owner address, or ``None`` if unreadable.
        """
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=dw_address,
            contract_id=str(DepositWalletContract.contract_id),
            contract_callable="get_owner",
            chain_id=self.params.mech_chain_id,
        )
        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.info(
                f"Could not read DepositWallet {dw_address} owner on-chain "
                "(may still be deploying); skipping rotation check."
            )
            return None
        return cast(Optional[str], response_msg.state.body.get("owner"))

    def _prepare_approval_tx(self) -> Generator[None, None, Optional[str]]:
        """Prepare Safe transaction for setting approvals."""
        # Get contract addresses from params. In v2 the collateral token is
        # pUSD (was USDC.e in v1); approvals are issued against the v2 exchange
        # contracts.
        collateral_address = self.params.polymarket_collateral_address
        ctf_address = self.params.polymarket_ctf_address
        ctf_exchange_address = self.params.polymarket_ctf_exchange_address
        neg_risk_ctf_exchange_address = (
            self.params.polymarket_neg_risk_ctf_exchange_address
        )
        neg_risk_adapter_address = self.params.polymarket_neg_risk_adapter_address
        ctf_collateral_adapter_address = (
            self.params.polymarket_ctf_collateral_adapter_address
        )
        neg_risk_ctf_collateral_adapter_address = (
            self.params.polymarket_neg_risk_ctf_collateral_adapter_address
        )

        # Build approval transactions and add to multisend_batches (must match
        # polymarket_client _check_approval: 3 collateral allowances + 5 CTF
        # setApprovalForAll; 8 entries total). The collateral adapters
        # intentionally receive only ERC-1155 operator rights — their redeem
        # path doesn't pull ERC-20 from the Safe, so no pUSD allowance.
        # 1. Collateral approve for CTF Exchange
        collateral_approve_batch = MultisendBatch(
            to=collateral_address,
            data=HexBytes(
                self._build_erc20_approve_data(ctf_exchange_address, 2**256 - 1)
            ),
            value=0,
        )
        self.multisend_batches.append(collateral_approve_batch)

        # 2. CTF setApprovalForAll for CTF Exchange
        ctf_approve1_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(ctf_exchange_address, True)
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve1_batch)

        # 3. Collateral approve for NegRisk CTF Exchange
        collateral_approve_neg_risk_ctf_batch = MultisendBatch(
            to=collateral_address,
            data=HexBytes(
                self._build_erc20_approve_data(
                    neg_risk_ctf_exchange_address, 2**256 - 1
                )
            ),
            value=0,
        )
        self.multisend_batches.append(collateral_approve_neg_risk_ctf_batch)

        # 4. CTF setApprovalForAll for NegRisk CTF Exchange
        ctf_approve2_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(
                    neg_risk_ctf_exchange_address, True
                )
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve2_batch)

        # 5. Collateral approve for NegRisk Adapter
        collateral_approve_neg_risk_adapter_batch = MultisendBatch(
            to=collateral_address,
            data=HexBytes(
                self._build_erc20_approve_data(neg_risk_adapter_address, 2**256 - 1)
            ),
            value=0,
        )
        self.multisend_batches.append(collateral_approve_neg_risk_adapter_batch)

        # 6. CTF setApprovalForAll for NegRisk Adapter
        ctf_approve3_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(neg_risk_adapter_address, True)
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve3_batch)

        # 7. CTF setApprovalForAll for CtfCollateralAdapter (redeem-critical:
        # without this the adapter cannot burn the Safe's position tokens).
        ctf_approve_collateral_adapter_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(
                    ctf_collateral_adapter_address, True
                )
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve_collateral_adapter_batch)

        # 8. CTF setApprovalForAll for NegRiskCtfCollateralAdapter (redeem-
        # critical for neg-risk markets).
        ctf_approve_neg_risk_collateral_adapter_batch = MultisendBatch(
            to=ctf_address,
            data=HexBytes(
                self._build_set_approval_for_all_data(
                    neg_risk_ctf_collateral_adapter_address, True
                )
            ),
            value=0,
        )
        self.multisend_batches.append(ctf_approve_neg_risk_collateral_adapter_batch)

        # Build the multisend transaction directly (no balance check needed for approvals)
        success = yield from self._build_multisend_data()
        if not success:
            self.context.logger.error("Failed to build multisend data for approvals")
            return ""

        success = yield from self._build_multisend_safe_tx_hash()
        if not success:
            self.context.logger.error("Failed to build safe tx hash for approvals")
            return ""

        return self.tx_hex

    def _build_erc20_approve_data(self, spender: str, amount: int) -> str:
        """Build ERC20 approve function data."""
        # approve(address spender, uint256 amount)
        function_signature = "0x095ea7b3"  # keccak256("approve(address,uint256)")[:4]
        spender_padded = spender[2:].zfill(64).lower()  # Remove 0x and pad to 32 bytes
        amount_hex = hex(amount)[2:].zfill(64)  # Convert to hex and pad
        return f"{function_signature}{spender_padded}{amount_hex}"

    def _build_set_approval_for_all_data(self, operator: str, approved: bool) -> str:
        """Build ERC1155 setApprovalForAll function data."""
        # setApprovalForAll(address operator, bool approved)
        function_signature = (
            "0xa22cb465"  # keccak256("setApprovalForAll(address,bool)")[:4]
        )
        operator_padded = operator[2:].zfill(64).lower()
        approved_value = "1" if approved else "0"
        approved_padded = approved_value.zfill(64)
        return f"{function_signature}{operator_padded}{approved_padded}"

    def _build_dw_trading_approvals(self) -> list:
        """Build the 6 DepositWallet trading-approval calls.

        pUSD allowance + CTF operator rights to the V2 Exchange,
        NegRiskCTFExchange and NegRiskAdapter — the first six of the eight
        Safe approvals built in ``_prepare_approval_tx``. The two
        redemption-adapter approvals are excluded: redemption is executed by
        the Safe, never the DepositWallet. The connection's
        ``EXEC_WALLET_BATCH`` is a generic relay, so the calls are constructed
        here rather than connection-side.

        :return: list of ``{"to", "data", "value"}`` calls for EXEC_WALLET_BATCH.
        """
        collateral = self.params.polymarket_collateral_address
        ctf = self.params.polymarket_ctf_address
        spenders = (
            self.params.polymarket_ctf_exchange_address,
            self.params.polymarket_neg_risk_ctf_exchange_address,
            self.params.polymarket_neg_risk_adapter_address,
        )
        max_uint = 2**256 - 1
        txs = [
            {
                "to": collateral,
                "data": self._build_erc20_approve_data(spender, max_uint),
                "value": "0",
            }
            for spender in spenders
        ]
        txs += [
            {
                "to": ctf,
                "data": self._build_set_approval_for_all_data(operator, True),
                "value": "0",
            }
            for operator in spenders
        ]
        return txs

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
