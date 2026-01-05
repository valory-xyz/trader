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

"""This module contains the behaviour for sampling a bet."""

import json
from typing import Any, Callable, Dict, Generator, Optional, cast

from aea.protocols.base import Message
from aea.protocols.dialogue.base import Dialogue
from hexbytes import HexBytes

from packages.valory.connections.polymarket_client.connection import (
    PUBLIC_ID as POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID,
)
from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.srr.dialogues import SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WXDAI,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import (
    BetPlacementPayload,
    PolymarketBetPlacementPayload,
)
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

    def _place_bet(self) -> None:
        outcome = self.sampled_bet.get_outcome(self.outcome_index)
        token_id = self.sampled_bet.outcome_token_ids[outcome]
        amount = self._collateral_amount_info(self.investment_amount)

        # Prepare payload data
        payload_data = {
            "request_type": RequestType.PLACE_BET.value,
            "params": {
                "token_id": token_id,
                "amount": amount,
            },
        }
        self._send_polymarket_connection_request(
            payload_data=payload_data, callback=lambda *args, **kwargs: None
        )

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self.wait_for_condition_with_sleep(self.check_balance)

            self._place_bet()
            payload = PolymarketBetPlacementPayload(
                sender=self.context.agent_address,
                vote=True,
            )

        yield from self.finish_behaviour(payload)

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()
