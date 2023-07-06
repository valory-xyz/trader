from multiprocessing.pool import AsyncResult
from string import Template
from typing import Any, Optional, cast, Generator, Tuple

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.decision_maker_abci.models import DecisionMakerParams
from packages.valory.skills.decision_maker_abci.payloads import DecisionMakerPayload
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerRound, SynchronizedData
from packages.valory.skills.decision_maker_abci.tasks import MechInteractionTask, MechInteractionResponse

BET_PROMPT = Template(
    """
    With the given question "${question}" 
    and the `yes` option represented by ${yes} 
    and the `no` option represented by ${no}, 
    what are the respective probabilities of `p_yes` and `p_no` occurring?
    """
)


class DecisionMakerBehaviour(BaseBehaviour):
    """A round in which the agents decide which answer they are going to choose for the next bet."""

    matching_round = DecisionMakerRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._async_result: Optional[AsyncResult] = None

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    def setup(self) -> None:
        """Setup behaviour."""
        mech_task = MechInteractionTask()
        sampled_bet = self.synchronized_data.sampled_bet
        prompt_params = dict(
            question=sampled_bet.title, yes=sampled_bet.yes, no=sampled_bet.no
        )
        task_kwargs = dict(
            prompt=BET_PROMPT.substitute(prompt_params),
            agent_id=self.params.mech_agent_id,
            tool=self.params.mech_tool,
            private_key_path=self.context.private_key_paths.read("ethereum"),
        )
        task_id = self.context.task_manager.enqueue_task(mech_task, kwargs=task_kwargs)
        self._async_result = self.context.task_manager.get_task_result(task_id)

    def _get_decision(self) -> Generator[None, None, Optional[Tuple[Optional[int], float]]]:
        """Get the vote and it's confidence."""
        self._async_result = cast(AsyncResult, self._async_result)
        if not self._async_result.ready():
            self.context.logger.debug("The decision making task is not finished yet.")
            yield from self.sleep(self.params.sleep_time)
            return None

        # Get the decision from the task.
        mech_response = cast(MechInteractionResponse, self._async_result.get())
        self.context.logger.info(f"Decision has been received:\n{mech_response}")

        if mech_response.prediction is None:
            self.context.logger.info(f"There was an error on the mech response: {mech_response.error}")
            return None, -1

        return mech_response.prediction.vote, mech_response.prediction.confidence

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()

        self.set_done()

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            decision = yield from self._get_decision()
            if decision is None:
                return

            vote, confidence = decision
            payload = DecisionMakerPayload(self.context.agent_address, vote, confidence)

        yield from self.finish_behaviour(payload)
