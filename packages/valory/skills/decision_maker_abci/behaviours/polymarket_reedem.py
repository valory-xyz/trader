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

"""This module contains the redeeming state of the decision-making abci app."""

import json
from typing import Generator, Optional, cast

from hexbytes import HexBytes
from web3.constants import HASH_ZERO

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import MultisendBatch
from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    StorageManagerBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import DecisionMakerParams
from packages.valory.skills.decision_maker_abci.payloads import PolymarketRedeemPayload
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    PolymarketRedeemRound,
)

ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)
BLOCK_NUMBER_KEY = "number"
DEFAULT_TO_BLOCK = "latest"


class PolymarketRedeemBehaviour(StorageManagerBehaviour):
    """Redeem the winnings."""

    matching_round = PolymarketRedeemRound

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        self._store_utilized_tools()
        yield from super().finish_behaviour(payload)

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    def _update_policy_for_redeemable_positions(
        self, redeemable_positions: list
    ) -> None:
        """Update policy accuracy store for each redeemable (settled) position.

        ``redeemable=True`` from the Polymarket positions API includes both winning
        and losing settled positions.  The ``curPrice`` field is 1.0 for a winning
        outcome token and 0.0 for a losing one once the market has resolved, so we
        use a 0.5 midpoint threshold to distinguish them.  This mirrors how
        ``RedeemInfoBehaviour._update_policy`` in reedem.py handles Omen trades
        via ``Trade.is_winning``.

        :param redeemable_positions: list of position dicts from the Polymarket API.
        """
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            if condition_id is None:
                continue
            tool = self.utilized_tools.get(condition_id)
            if tool is None:
                self.context.logger.warning(
                    f"No tool recorded for condition_id {condition_id!r}; "
                    "skipping accuracy store update."
                )
                continue
            cur_price = position.get("curPrice")
            if cur_price is None:
                self.context.logger.warning(
                    f"No curPrice for condition_id {condition_id!r}; "
                    "skipping accuracy store update."
                )
                continue
            winning = float(cur_price) > 0.5
            try:
                self.policy.update_accuracy_store(tool, winning=winning)
                outcome = "winning" if winning else "losing"
                self.context.logger.info(
                    f"Updated accuracy store for tool {tool!r} ({outcome}, curPrice={cur_price}) "
                    f"from condition_id {condition_id!r}."
                )
                del self.utilized_tools[condition_id]
            except KeyError:
                self.context.logger.warning(
                    f"Tool {tool!r} not found in accuracy store; skipping."
                )

    def _fetch_redeemable_positions(self) -> Generator[None, None, list]:
        """Fetch redeemable positions from Polymarket."""
        # Prepare payload data
        polymarket_bet_payload = {
            "request_type": RequestType.FETCH_ALL_POSITIONS.value,
            "params": {
                "redeemable": True,
            },
        }
        redeemable_positions = yield from self.send_polymarket_connection_request(
            polymarket_bet_payload
        )

        return redeemable_positions

    def _redeem_position(
        self,
        condition_id: str,
        outcome_index: int,
        collateral_token: str,
        is_neg_risk: bool = False,
    ) -> Generator[None, None, dict]:
        """Redeem a single position.

        :param condition_id: The condition ID for the position
        :param outcome_index: The outcome index (0 for Yes, 1 for No typically)
        :param collateral_token: The collateral token address
        :param is_neg_risk: Whether this is a negative risk market
        :return: Redemption result
        :yield: None
        """
        # The collateral adapter discovers the Safe's ERC1155 balance itself,
        # so we only need the held outcome's bitmask (1 << outcomeIndex).
        index_sets = [1 << outcome_index]

        polymarket_redeem_payload = {
            "request_type": RequestType.REDEEM_POSITIONS.value,
            "params": {
                "condition_id": condition_id,
                "index_sets": index_sets,
                "collateral_token": collateral_token,
                "is_neg_risk": is_neg_risk,
            },
        }

        redeem_result = yield from self.send_polymarket_connection_request(
            polymarket_redeem_payload
        )

        return redeem_result

    def _setup_policy_and_tools(self) -> Generator[None, None, bool]:
        """Set up the policy and tools."""
        if self.synchronized_data.is_policy_set:
            self._policy = self.synchronized_data.policy
            self.mech_tools = self.synchronized_data.available_mech_tools
            return True
        status = yield from super()._setup_policy_and_tools()
        return status

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Mirror Omen's RedeemBehaviour._setup_policy_and_tools + _build_payload:
            # load from synchronized_data properties, then serialize for the payload.
            # PolymarketRedeemRound.selection_key includes all three fields, so leaving
            # them as defaults (mech_tools="[]", policy=None, utilized_tools=None) would
            # overwrite the live values in synchronized data on every redeem round.
            success = yield from self._setup_policy_and_tools()
            if not success:
                return
            is_policy_set = self.synchronized_data.is_policy_set

            current_mech_tools = json.dumps(list(self.mech_tools))

            # Fetch redeemable positions once for both flows
            redeemable_positions = yield from self._fetch_redeemable_positions()
            self.context.logger.info(
                f"Fetched {len(redeemable_positions)} redeemable positions"
            )

            # Update the e-greedy policy's accuracy store for every winning position
            # whose conditionId is recorded in utilized_tools.  All positions returned
            # by the Polymarket API with redeemable=True are winning positions, so the
            # update is always called with winning=True.  This mirrors
            # RedeemInfoBehaviour._update_policy in reedem.py for Omen.
            self._update_policy_for_redeemable_positions(redeemable_positions)

            # Re-serialise policy and utilized_tools *after* the accuracy-store update
            # so that the updated values are carried in the payload.
            current_policy = self.policy.serialize() if is_policy_set else None
            current_utilized_tools = json.dumps(self.utilized_tools)

            if redeemable_positions == []:
                self.context.logger.info("No redeemable positions found.")
                self.payload = PolymarketRedeemPayload(
                    sender=self.context.agent_address,
                    tx_submitter=None,
                    tx_hash=None,
                    mocking_mode=False,
                    mech_tools=current_mech_tools,
                    policy=current_policy,
                    utilized_tools=current_utilized_tools,
                    event=Event.NO_REDEEMING.value,
                )
                yield from self.finish_behaviour(self.payload)
                return

            # Check if builder program is enabled
            if self.context.params.polymarket_builder_program_enabled:
                self.context.logger.info(
                    "Polymarket builder program enabled - calling connection to redeem positions..."
                )
                # Call the polymarket client to redeem positions
                yield from self._redeem_via_builder(
                    redeemable_positions,
                    current_mech_tools,
                    current_policy,
                    current_utilized_tools,
                )
            else:
                self.context.logger.info(
                    "Polymarket builder program disabled - preparing redemption transaction..."
                )
                # Prepare Safe transaction for redemption
                tx_submitter = self.matching_round.auto_round_id()
                tx_hash = yield from self._prepare_redeem_tx(redeemable_positions)

                self.payload = PolymarketRedeemPayload(
                    sender=self.context.agent_address,
                    tx_submitter=tx_submitter,
                    tx_hash=tx_hash,
                    mocking_mode=False,
                    mech_tools=current_mech_tools,
                    policy=current_policy,
                    utilized_tools=current_utilized_tools,
                    event=Event.PREPARE_TX.value,
                )

        yield from self.finish_behaviour(self.payload)

    def _redeem_via_builder(
        self,
        redeemable_positions: list,
        current_mech_tools: str = "[]",
        current_policy: Optional[str] = None,
        current_utilized_tools: Optional[str] = None,
    ) -> Generator:
        """Redeem positions via builder flow (connection request)."""

        # Redeem each position
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size", 0)
            is_neg_risk = position.get("negativeRisk", False)

            market_type = "negative risk" if is_neg_risk else "standard"
            self.context.logger.info(
                f"Redeeming {market_type} position: {condition_id} - {outcome} (size: {size})"
            )

            result = yield from self._redeem_position(
                condition_id=condition_id,
                outcome_index=outcome_index,
                collateral_token=self.params.polymarket_collateral_address,
                is_neg_risk=is_neg_risk,
            )

            self.context.logger.info(f"Redemption result for {condition_id}: {result}")

        self.payload = PolymarketRedeemPayload(
            sender=self.context.agent_address,
            tx_submitter=None,
            tx_hash=None,
            mocking_mode=False,
            mech_tools=current_mech_tools,
            policy=current_policy,
            utilized_tools=current_utilized_tools,
            event=Event.DONE.value,
        )

    def _prepare_redeem_tx(
        self, redeemable_positions: list
    ) -> Generator[None, None, Optional[str]]:
        """Prepare Safe transaction for redeeming positions."""
        if not redeemable_positions:
            self.context.logger.info("No redeemable positions found")
            return ""

        # Build redemption transactions and add to multisend_batches
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size", 0)
            is_neg_risk = position.get("negativeRisk", False)

            market_type = "negative risk" if is_neg_risk else "standard"
            self.context.logger.info(
                f"Preparing redeem tx for {market_type} position: {condition_id} - {outcome} (size: {size})"
            )

            # Both adapters expose the same 4-arg redeemPositions(
            # IERC20, bytes32, bytes32, uint256[]) signature; only the
            # destination contract differs. Redeem only the held outcome's
            # index set (1 << outcomeIndex) — including the losing side
            # would still pay 0 but burn extra gas on balance/payout reads.
            redeem_data = self._build_redeem_positions_data(
                collateral_token=self.params.polymarket_collateral_address,
                condition_id=condition_id,
                index_sets=[1 << outcome_index],
            )
            if is_neg_risk:
                target_address = (
                    self.params.polymarket_neg_risk_ctf_collateral_adapter_address
                )
            else:
                target_address = self.params.polymarket_ctf_collateral_adapter_address

            # Add to multisend batch
            redeem_batch = MultisendBatch(
                to=target_address,
                data=HexBytes(redeem_data),
                value=0,
            )
            self.multisend_batches.append(redeem_batch)

        # Build the multisend transaction
        success = yield from self._build_multisend_data()
        if not success:
            self.context.logger.error("Failed to build multisend data for redemptions")
            return ""

        success = yield from self._build_multisend_safe_tx_hash()
        if not success:
            self.context.logger.error("Failed to build safe tx hash for redemptions")
            return ""

        return self.tx_hex

    def _build_redeem_positions_data(
        self, collateral_token: str, condition_id: str, index_sets: list
    ) -> str:
        """Build redeemPositions function data for standard CTF contract."""
        # redeemPositions(address,bytes32,bytes32,uint256[])
        function_signature = "0x01b7037c"  # keccak256("redeemPositions(address,bytes32,bytes32,uint256[])")[:4]

        # Encode parameters
        collateral_padded = collateral_token[2:].zfill(64).lower()

        # parentCollectionId (bytes32) - always zeros
        parent_collection = "0" * 64

        condition_id_clean = condition_id.removeprefix("0x")
        condition_id_padded = condition_id_clean.zfill(64).lower()

        # indexSets (uint256[])
        # Array encoding: offset to array data (4 * 32 bytes from start = 0x80)
        array_offset = (
            "0000000000000000000000000000000000000000000000000000000000000080"
        )

        # Array length
        array_length = hex(len(index_sets))[2:].zfill(64)

        # Array elements
        array_elements = "".join([hex(idx)[2:].zfill(64) for idx in index_sets])

        return f"{function_signature}{collateral_padded}{parent_collection}{condition_id_padded}{array_offset}{array_length}{array_elements}"
