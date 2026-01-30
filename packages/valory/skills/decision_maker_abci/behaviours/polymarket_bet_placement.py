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

from typing import Any, Generator

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)


class PolymarketBetPlacementBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = PolymarketBetPlacementRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self.wait_for_condition_with_sleep(self.check_balance)

        outcome = self.sampled_bet.get_outcome(self.outcome_index)
        if self.sampled_bet.outcome_token_ids is None:
            self.context.logger.error("Failed to place bet: outcome_token_ids is None")
            payload = PolymarketBetPlacementPayload(
                self.context.agent_address,
                None,
                None,
                False,
                event=Event.BET_PLACEMENT_FAILED.value,
            )
            yield from self.finish_behaviour(payload)
            return

        token_id = self.sampled_bet.outcome_token_ids[outcome]
        amount = self.usdc_to_native(self.investment_amount)

        if self.investment_amount > self.token_balance:
            self.context.logger.error("Failed to place bet: insufficient token balance")
            payload = PolymarketBetPlacementPayload(
                self.context.agent_address,
                None,
                None,
                False,
                event=Event.INSUFFICIENT_BALANCE.value,
            )
            yield from self.finish_behaviour(payload)
            return

        # Prepare payload data
        polymarket_bet_payload = {
            "request_type": RequestType.PLACE_BET.value,
            "params": {
                "token_id": token_id,
                "amount": amount,
            },
        }
        response = yield from self.send_polymarket_connection_request(
            polymarket_bet_payload
        )

        # Handle error case where response is None
        success = False
        if response is not None:
            self.context.logger.info(
                f"Bet placement: Status={response.get('status')}, "
                f"OrderID={response.get('orderID')}, "
                f"TX={response.get('transactionsHashes', [])}"
            )

            success = bool(
                response.get("success") or response.get("transactionsHashes")
            )

        else:
            self.context.logger.error(
                "Failed to place bet: No response from connection"
            )

        payload = PolymarketBetPlacementPayload(
            self.context.agent_address,
            None,
            None,
            False,
            event=(
                Event.BET_PLACEMENT_DONE.value
                if success
                else Event.BET_PLACEMENT_FAILED.value
            ),
        )

        yield from self.finish_behaviour(payload)
