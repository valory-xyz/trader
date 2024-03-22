# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""This module contains the behaviour of the skill which is responsible for requesting a decision from the mech."""

import json
from dataclasses import asdict
from typing import Any, Dict, Generator, Optional
from uuid import uuid4

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionRequestPayload
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS
from packages.valory.skills.mech_interact_abci.states.base import MechMetadata


class DecisionRequestBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents prepare a tx to initiate a request to a mech to determine the answer to a bet."""

    matching_round = DecisionRequestRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._metadata: Optional[MechMetadata] = None

    @property
    def metadata(self) -> Dict[str, str]:
        """Get the metadata as a dictionary."""
        return asdict(self._metadata)

    @property
    def n_slots_supported(self) -> bool:
        """Whether the behaviour supports the current number of slots as it currently only supports binary decisions."""
        return self.params.slot_count == BINARY_N_SLOTS

    def setup(self) -> None:
        """Setup behaviour."""
        if not self.n_slots_supported:
            return

        sampled_bet = self.sampled_bet
        prompt_params = dict(
            question=sampled_bet.title, yes=sampled_bet.yes, no=sampled_bet.no
        )
        prompt = self.params.prompt_template.substitute(prompt_params)
        tool = self.synchronized_data.mech_tool
        nonce = str(uuid4())
        self._metadata = MechMetadata(prompt, tool, nonce)
        msg = f"Prepared metadata {self.metadata!r} for the request."
        self.context.logger.info(msg)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            mech_requests = []
            if self.n_slots_supported:
                mech_requests.append(self.metadata)
            serialized_mech_requests = json.dumps(mech_requests, sort_keys=True)
            agent = self.context.agent_address
            payload = DecisionRequestPayload(agent, serialized_mech_requests)
        yield from self.finish_behaviour(payload)
