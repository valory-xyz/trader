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

        success = False
        error_message = None
        event = None

        if response is None:
            error_message = "Failed to place bet: No response from connection"
            self.context.logger.error(error_message)
            event = Event.BET_PLACEMENT_FAILED
        else:
            status = response.get("status")
            order_id = response.get("orderID")
            tx_hashes = response.get("transactionsHashes", [])
            self.context.logger.info(
                f"Bet placement: Status={status}, OrderID={order_id}, TX={tx_hashes}"
            )

            response_str = str(response)
            if "No orderbook exists for the requested token id" in response_str:
                error_message = "Failed to place bet: No orderbook exists for the requested token id"
                self.context.logger.error(error_message)

                event = Event.BET_PLACEMENT_IMPOSSIBLE
            success = bool(response.get("success") or tx_hashes)

            # Only set event to DONE if not already set to IMPOSSIBLE
            if event is None:
                if success:
                    self.update_bet_transaction_information()
                    self.context.logger.info("Bet placement successful.")
                    event = Event.BET_PLACEMENT_DONE
                else:
                    self.context.logger.error("Bet placement failed.")
                    event = Event.BET_PLACEMENT_FAILED

        # Fallback in case event is not set (should not happen, but for safety)
        if event is None:
            event = Event.BET_PLACEMENT_FAILED

        payload = PolymarketBetPlacementPayload(
            self.context.agent_address,
            None,
            None,
            False,
            event=event.value,
        )

        yield from self.finish_behaviour(payload)
