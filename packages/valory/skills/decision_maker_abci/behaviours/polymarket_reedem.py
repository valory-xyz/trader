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
from typing import Any, Dict, Generator, List, Optional, Union, cast

from eth_abi import encode
from eth_utils import keccak  # type: ignore[import-not-found]
from hexbytes import HexBytes
from web3.constants import HASH_ZERO

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.agent_performance_summary_abci.feed import (
    EventType,
    Field,
    field,
    format_amount,
    market_url,
)
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    MultisendBatch,
    V2_BALANCE_KEY,
)
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
ROUTER_REDEEM_TYPES = ["bytes31", "uint256", "uint256"]
ROUTER_REDEEM_SELECTOR = keccak(text=f"redeem({','.join(ROUTER_REDEEM_TYPES)})")[:4]


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

    def _payouts_by_market(self, positions: list) -> List[List[Field]]:
        """Build one payout card per market from the positions redeemed.

        A position pays its size times its resolved price: 1 for the winning
        outcome, 0 for the losing one and an equal share on an invalid market.

        :param positions: position dicts from the Polymarket API.
        :return: the cards' fields, one list per market that paid out.
        """
        markets: Dict[Any, Dict[str, Any]] = {}
        for position in positions:
            try:
                amount = float(position.get("size", 0)) * float(position["curPrice"])
            except (KeyError, TypeError, ValueError):
                self.context.logger.warning(
                    f"No valid size or curPrice for condition_id "
                    f"{position.get('conditionId')!r}; leaving it out of the payout card."
                )
                continue
            if amount <= 0:
                continue
            market = markets.setdefault(
                position.get("conditionId"),
                {
                    "title": str(position.get("title") or position.get("conditionId")),
                    "slug": position.get("slug"),
                    "amount": 0.0,
                },
            )
            market["amount"] += amount
        return [
            [
                field(
                    "Market", market["title"], market_url(True, None, market["slug"])
                ),
                field("Amount", format_amount(market["amount"], True)),
            ]
            for market in markets.values()
        ]

    def _record_settled_builder_redeems(self, redeemable_positions: list) -> None:
        """Write the payout cards of the builder redeems that have landed.

        The relayer only accepts a redeem, so a position counts as paid once the
        positions API no longer lists it as redeemable.

        :param redeemable_positions: the positions the API lists as redeemable.
        """
        still_redeemable = {
            position.get("conditionId") for position in redeemable_positions
        }
        pending = self.shared_state.polymarket_builder_redeems_pending
        settled = [
            position
            for condition_id, positions in pending.items()
            if condition_id not in still_redeemable
            for position in positions
        ]
        self.shared_state.polymarket_builder_redeems_pending = {
            condition_id: positions
            for condition_id, positions in pending.items()
            if condition_id in still_redeemable
        }
        for fields in self._payouts_by_market(settled):
            self._record_feed_event(EventType.PAYOUT_COLLECTED, fields)

    def _fetch_redeemable_positions(self) -> Generator[None, None, Optional[list]]:
        """Fetch redeemable positions from Polymarket.

        :yield: framework yields between dispatch and the connection response.
        :return: the redeemable positions, or None if the read failed.
        """
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

        if not isinstance(redeemable_positions, list):
            self.context.logger.error(
                f"Redeemable positions fetch failed: {redeemable_positions}"
            )
            return None

        return redeemable_positions

    def _redeem_position(
        self,
        condition_id: str,
        outcome_index: int,
        collateral_token: str,
        is_neg_risk: bool = False,
        amount: Optional[int] = None,
    ) -> Generator[None, None, Optional[Union[List[Dict[str, Any]], Dict[str, Any]]]]:
        """Redeem a single position.

        :param condition_id: The condition ID for the position
        :param outcome_index: The outcome index (0 for Yes, 1 for No typically)
        :param collateral_token: The collateral token address
        :param is_neg_risk: Whether this is a negative risk market
        :param amount: the amount of a Protocol V2 position; None for V1
        :return: the relayer's transactions for the redeem, an error dict if the
            request failed, or None if the connection gave no response
        :yield: None
        """
        # The deployed Polymarket collateral adapters ignore the uint256[]
        # argument — they read both position balances and call the internal
        # partition themselves. Passing [1 << outcomeIndex] is a calldata-size
        # choice that documents agent intent; it does not limit on-chain work.
        index_sets = [1 << outcome_index]

        polymarket_redeem_payload: Dict[str, Any] = {
            "request_type": RequestType.REDEEM_POSITIONS.value,
            "params": {
                "condition_id": condition_id,
                "index_sets": index_sets,
                "collateral_token": collateral_token,
                "is_neg_risk": is_neg_risk,
            },
        }
        if amount is not None:
            polymarket_redeem_payload["params"].update(
                outcome_index=outcome_index, amount=amount
            )

        redeem_result = yield from self.send_polymarket_connection_request(
            polymarket_redeem_payload
        )

        return redeem_result

    def _setup_policy_and_tools(self) -> Generator[None, None, bool]:
        """Set up the policy and tools."""
        if self.synchronized_data.is_policy_set:
            self._policy = self.synchronized_data.policy
            self.mech_tools = self.synchronized_data.available_mech_tools
            self._migrate_legacy_keys()
            # The base setup is skipped here, so publish the suitable set for the
            # ChatUI explicitly. Covers db-replay restarts where `is_policy_set`
            # is already true at boot but `available_prediction_tools` (in-memory)
            # is back to None; the `is None` gate no-ops it otherwise.
            yield from self._maybe_publish_suitable_tools()
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
            fetched_positions = yield from self._fetch_redeemable_positions()
            redeemable_positions = fetched_positions or []
            self.context.logger.info(
                f"Fetched {len(redeemable_positions)} redeemable positions"
            )

            # Update the e-greedy policy's accuracy store for every winning position
            # whose conditionId is recorded in utilized_tools.  All positions returned
            # by the Polymarket API with redeemable=True are winning positions, so the
            # update is always called with winning=True.  This mirrors
            # RedeemInfoBehaviour._update_policy in reedem.py for Omen.
            self._update_policy_for_redeemable_positions(redeemable_positions)
            # The losing side of a resolved V2 market is redeemable too, but has
            # nothing to claim. V1 positions are all claimed, as before.
            redeemable_positions = [
                p
                for p in redeemable_positions
                if V2_BALANCE_KEY not in p
                or (p.get("currentValue") and p[V2_BALANCE_KEY])
            ]
            self.shared_state.polymarket_payouts_to_record = []
            # A failed read says nothing about whether the pending redeems landed.
            if fetched_positions is not None:
                self._record_settled_builder_redeems(redeemable_positions)

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

        redeemed: Dict[str, List[Dict[str, Any]]] = {}
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size", 0)
            is_neg_risk = position.get("negativeRisk", False)

            if condition_id is None or outcome_index is None:
                self.context.logger.error(
                    f"Skipping malformed position (missing conditionId or "
                    f"outcomeIndex): {position}"
                )
                continue

            market_type = "negative risk" if is_neg_risk else "standard"
            self.context.logger.info(
                f"Redeeming {market_type} position: {condition_id} - {outcome} (size: {size})"
            )

            # A V2 position also passes its amount, to claim through the Router.
            v2 = (
                {"amount": position[V2_BALANCE_KEY]}
                if V2_BALANCE_KEY in position
                else {}
            )
            result = yield from self._redeem_position(
                condition_id=condition_id,
                outcome_index=outcome_index,
                collateral_token=self.params.polymarket_collateral_address,
                is_neg_risk=is_neg_risk,
                **v2,
            )

            self.context.logger.info(f"Redemption result for {condition_id}: {result}")
            if result is not None and not (
                isinstance(result, dict) and result.get("error")
            ):
                redeemed.setdefault(condition_id, []).append(position)

        # A resend for the same market replaces its pending positions.
        self.shared_state.polymarket_builder_redeems_pending.update(redeemed)

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

        included: list = []
        # Build redemption transactions and add to multisend_batches
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size", 0)
            is_neg_risk = position.get("negativeRisk", False)

            if condition_id is None or outcome_index is None:
                self.context.logger.error(
                    f"Skipping malformed position (missing conditionId or "
                    f"outcomeIndex): {position}"
                )
                continue

            market_type = "negative risk" if is_neg_risk else "standard"
            self.context.logger.info(
                f"Preparing redeem tx for {market_type} position: {condition_id} - {outcome} (size: {size})"
            )

            # Both adapters expose the same 4-arg redeemPositions(IERC20,
            # bytes32, bytes32, uint256[]) signature; only the destination
            # contract differs. The deployed adapters ignore the uint256[]
            # argument — they redeem both sides via CTFHelpers.partition() /
            # balanceOf regardless. Passing [1 << outcomeIndex] is a
            # calldata-size choice; it does not limit on-chain redemption.
            redeem_data = self._build_redeem_positions_data(
                collateral_token=self.params.polymarket_collateral_address,
                condition_id=condition_id,
                index_sets=[1 << outcome_index],
            )
            if V2_BALANCE_KEY in position:
                # A V2 claim goes to the Router, which takes a bytes31 condition
                # ID: the Data API's zero pad byte drops.
                cid = bytes.fromhex(condition_id.removeprefix("0x"))[:31]
                args = [cid, outcome_index, position[V2_BALANCE_KEY]]
                redeem_data = (
                    ROUTER_REDEEM_SELECTOR + encode(ROUTER_REDEEM_TYPES, args)
                ).hex()
                target_address = self.params.polymarket_router_address
            elif is_neg_risk:
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
            included.append(position)

        # Build the multisend transaction
        success = yield from self._build_multisend_data()
        if not success:
            self.context.logger.error("Failed to build multisend data for redemptions")
            return ""

        success = yield from self._build_multisend_safe_tx_hash()
        if not success:
            self.context.logger.error("Failed to build safe tx hash for redemptions")
            return ""

        # Written by the tx settlement once this tx lands, not before.
        self.shared_state.polymarket_payouts_to_record = self._payouts_by_market(
            included
        )
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
