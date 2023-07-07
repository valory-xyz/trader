# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the behaviour for the decision-making of the skill."""

from multiprocessing.pool import AsyncResult
from pathlib import Path
from string import Template
from typing import Any, Generator, Optional, Tuple, cast

from mech_client.interact import PRIVATE_KEY_FILE_PATH

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionMakerPayload
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerRound
from packages.valory.skills.decision_maker_abci.tasks import (
    MechInteractionResponse,
    MechInteractionTask,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS


BET_PROMPT = Template(
    """
    With the given question "${question}"
    and the `yes` option represented by ${yes}
    and the `no` option represented by ${no},
    what are the respective probabilities of `p_yes` and `p_no` occurring?
    """
)


class DecisionMakerBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents decide which answer they are going to choose for the next bet."""

    matching_round = DecisionMakerRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._async_result: Optional[AsyncResult] = None

    @property
    def n_slots_unsupported(self) -> bool:
        """Whether the behaviour supports the current number of slots as it currently only supports binary decisions."""
        return self.params.slot_count != BINARY_N_SLOTS

    def setup(self) -> None:
        """Setup behaviour."""
        if self.n_slots_unsupported:
            return

        mech_task = MechInteractionTask()
        sampled_bet = self.synchronized_data.sampled_bet
        prompt_params = dict(
            question=sampled_bet.title, yes=sampled_bet.yes, no=sampled_bet.no
        )
        task_kwargs = dict(
            prompt=BET_PROMPT.substitute(prompt_params),
            agent_id=self.params.mech_agent_id,
            tool=self.params.mech_tool,
            private_key_path=str(Path(self.context.data_dir) / PRIVATE_KEY_FILE_PATH),
        )
        task_id = self.context.task_manager.enqueue_task(mech_task, kwargs=task_kwargs)
        self._async_result = self.context.task_manager.get_task_result(task_id)

    def _get_decision(
        self,
    ) -> Generator[None, None, Optional[Tuple[Optional[int], Optional[float]]]]:
        """Get the vote and it's confidence."""
        if self._async_result is None:
            return None, None

        if not self._async_result.ready():
            self.context.logger.debug("The decision making task is not finished yet.")
            yield from self.sleep(self.params.sleep_time)
            return None

        # Get the decision from the task.
        mech_response = cast(MechInteractionResponse, self._async_result.get())
        self.context.logger.info(f"Decision has been received:\n{mech_response}")

        if mech_response.prediction is None:
            self.context.logger.info(
                f"There was an error on the mech response: {mech_response.error}"
            )
            return None, None

        return mech_response.prediction.vote, mech_response.prediction.confidence

    def _is_profitable(self, vote: Optional[int], confidence: Optional[float]) -> bool:
        """Whether the decision is profitable or not."""
        if vote is None or confidence is None:
            return False

        bet_amount = self.params.get_bet_amount(confidence)
        fee = self.synchronized_data.sampled_bet.fee
        bet_threshold = self.params.bet_threshold
        return bet_amount - fee >= bet_threshold

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            decision = yield from self._get_decision()
            if decision is None:
                return

            vote, confidence = decision
            is_profitable = self._is_profitable(vote, confidence)
            payload = DecisionMakerPayload(
                self.context.agent_address,
                self.n_slots_unsupported,
                is_profitable,
                vote,
                confidence,
            )

        yield from self.finish_behaviour(payload)
