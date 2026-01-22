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

from typing import Generator, cast

from hexbytes import HexBytes
from web3.constants import HASH_ZERO

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    MultisendBatch,
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
COLLATERAL_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # nosec: B105


class PolymarketRedeemBehaviour(DecisionMakerBaseBehaviour):
    """Redeem the winnings."""

    matching_round = PolymarketRedeemRound

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    def _fetch_redeemable_positions(self) -> Generator:
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
        self, condition_id: str, outcome_index: int, collateral_token: str
    ) -> Generator:
        """Redeem a single position.

        :param condition_id: The condition ID to redeem
        :param outcome_index: The outcome index (0 or 1)
        :param collateral_token: The collateral token address
        :return: Generator yielding the redemption result
        """
        # Prepare redemption payload
        # index_sets should be calculated as 1 << outcome_index
        index_sets = [outcome_index + 1]

        polymarket_redeem_payload = {
            "request_type": RequestType.REDEEM_POSITIONS.value,
            "params": {
                "condition_id": condition_id,
                "index_sets": index_sets,
                "collateral_token": collateral_token,
            },
        }

        redeem_result = yield from self.send_polymarket_connection_request(
            polymarket_redeem_payload
        )

        return redeem_result

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Fetch redeemable positions once for both flows
            redeemable_positions = yield from self._fetch_redeemable_positions()
            self.context.logger.info(
                f"Fetched {len(redeemable_positions)} redeemable positions"
            )

            if redeemable_positions == []:
                self.context.logger.info("No redeemable positions found.")
                self.payload = PolymarketRedeemPayload(
                    sender=self.context.agent_address,
                    tx_submitter=None,
                    tx_hash=None,
                    mocking_mode=False,
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
                yield from self._redeem_via_builder(redeemable_positions)
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
                    event=Event.PREPARE_TX.value,
                )

        yield from self.finish_behaviour(self.payload)

    def _redeem_via_builder(self, redeemable_positions: list) -> Generator:
        """Redeem positions via builder flow (connection request).

        :param redeemable_positions: List of redeemable positions to redeem
        """

        # Redeem each position
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size")

            self.context.logger.info(
                f"Redeeming position: {condition_id} - {outcome} (size: {size})"
            )

            result = yield from self._redeem_position(
                condition_id=condition_id,
                outcome_index=outcome_index,
                collateral_token=COLLATERAL_TOKEN_ADDRESS,
            )

            self.context.logger.info(f"Redemption result for {condition_id}: {result}")

        self.payload = PolymarketRedeemPayload(
            sender=self.context.agent_address,
            tx_submitter=None,
            tx_hash=None,
            mocking_mode=False,
            event=Event.DONE.value,
        )

    def _prepare_redeem_tx(
        self, redeemable_positions: list
    ) -> Generator[None, None, str]:
        """Prepare Safe transaction for redeeming positions.

        :param redeemable_positions: List of redeemable positions to redeem
        :return: Transaction hash hex string
        """
        if not redeemable_positions:
            self.context.logger.info("No redeemable positions found")
            return ""

        # Get contract addresses from params
        ctf_address = self.params.polymarket_ctf_address

        # Build redemption transactions and add to multisend_batches
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size")

            self.context.logger.info(
                f"Preparing redeem tx for position: {condition_id} - {outcome} (size: {size})"
            )

            # Build the redemption data
            index_sets = [outcome_index + 1]
            redeem_data = self._build_redeem_positions_data(
                collateral_token=COLLATERAL_TOKEN_ADDRESS,
                condition_id=condition_id,
                index_sets=index_sets,
            )

            # Add to multisend batch
            redeem_batch = MultisendBatch(
                to=ctf_address,
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
        """Build redeemPositions function data.

        Function signature: redeemPositions(address,bytes32,bytes32,uint256[])
        - collateralToken: address
        - parentCollectionId: bytes32 (always 0x0000...0000)
        - conditionId: bytes32
        - indexSets: uint256[]
        """
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
