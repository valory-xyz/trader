# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

from web3.constants import HASH_ZERO

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import DecisionMakerParams
from packages.valory.skills.decision_maker_abci.payloads import PolymarketRedeemPayload
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    PolymarketRedeemRound,
)


ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)
BLOCK_NUMBER_KEY = "number"
DEFAULT_TO_BLOCK = "latest"
COLLATERAL_TOKEN_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"


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
        # index_sets = [1 << outcome_index]
        index_sets = [outcome_index + 1]
        # index_sets = [outcome_index]

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

        redeemable_positions = yield from self._fetch_redeemable_positions()
        self.context.logger.info(
            f"Fetched {len(redeemable_positions)} redeemable positions"
        )

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

        payload = PolymarketRedeemPayload(
            sender=self.context.agent_address,
        )

        yield from self.finish_behaviour(payload)
