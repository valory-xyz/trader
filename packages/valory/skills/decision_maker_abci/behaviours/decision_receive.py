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

from typing import Any, Generator, Optional, Tuple, Union

from packages.valory.contracts.mech.contract import Mech
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import (
    MechInteractionResponse,
    MechResponseSpecs,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)


IPFS_HASH_PREFIX = "f01701220"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class DecisionReceiveBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents receive the mech response."""

    matching_round = DecisionReceiveRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._from_block: int = 0
        self._request_id: int = 0
        self._response_hex: str = ""
        self._mech_response: Optional[MechInteractionResponse] = None

    @property
    def from_block(self) -> int:
        """Get the block number in which the request to the mech was settled."""
        return self._from_block

    @from_block.setter
    def from_block(self, from_block: int) -> None:
        """Set the block number in which the request to the mech was settled."""
        self._from_block = from_block

    @property
    def request_id(self) -> int:
        """Get the request id."""
        return self._request_id

    @request_id.setter
    def request_id(self, request_id: Union[str, int]) -> None:
        """Set the request id."""
        try:
            self._request_id = int(request_id)
        except ValueError:
            msg = f"Request id {request_id} is not a valid integer!"
            self.context.logger.error(msg)

    @property
    def response_hex(self) -> str:
        """Get the hash of the response data."""
        return self._response_hex

    @response_hex.setter
    def response_hex(self, response_hash: bytes) -> None:
        """Set the hash of the response data."""
        try:
            self._response_hex = response_hash.hex()
        except AttributeError:
            msg = f"Response hash {response_hash!r} is not valid hex bytes!"
            self.context.logger.error(msg)

    @property
    def mech_response_api(self) -> MechResponseSpecs:
        """Get the mech response api specs."""
        return self.context.mech_response

    def set_mech_response_specs(self) -> None:
        """Set the mech's response specs."""
        full_ipfs_hash = IPFS_HASH_PREFIX + self.response_hex
        ipfs_link = self.params.ipfs_address + full_ipfs_hash + f"/{self.request_id}"
        # The url must be dynamically generated as it depends on the ipfs hash
        self.mech_response_api.__dict__["_frozen"] = False
        self.mech_response_api.url = ipfs_link
        self.mech_response_api.__dict__["_frozen"] = True

    @property
    def mech_response(self) -> MechInteractionResponse:
        """Get the mech response api specs."""
        if self._mech_response is None:
            error = "The mech's response has not been set!"
            return MechInteractionResponse(error=error)
        return self._mech_response

    def _get_block_number(self) -> WaitableConditionType:
        """Get the block number in which the request to the mech was settled."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            # we do not need the address to get the block number, but the base method does
            contract_address=ZERO_ADDRESS,
            contract_public_id=Mech.contract_id,
            contract_callable="get_block_number",
            data_key="number",
            placeholder=get_name(DecisionReceiveBehaviour.from_block),
            tx_hash=self.synchronized_data.final_tx_hash,
        )

        return result

    def _get_request_id(self) -> WaitableConditionType:
        """Get the request id."""
        result = yield from self._mech_contract_interact(
            contract_callable="process_request_event",
            data_key="requestId",
            placeholder=get_name(DecisionReceiveBehaviour.request_id),
            tx_hash=self.synchronized_data.final_tx_hash,
        )
        return result

    def _get_response_hash(self) -> WaitableConditionType:
        """Get the hash of the response data."""
        result = yield from self._mech_contract_interact(
            contract_callable="get_response",
            data_key="data",
            placeholder=get_name(DecisionReceiveBehaviour.response_hex),
            request_id=self.request_id,
            from_block=self.from_block,
        )

        if result:
            self.set_mech_response_specs()

        return result

    def _handle_response(
        self,
        res: Optional[str],
    ) -> Optional[Any]:
        """Handle a response from a subgraph.

        :param res: the response to handle.
        :return: the response's result, using the given keys. `None` if response is `None` (has failed).
        """
        if res is None:
            msg = f"Could not get the mech's response from {self.mech_response_api.api_id}"
            self.context.logger.error(msg)
            self.mech_response_api.increment_retries()
            return None

        self.context.logger.info(f"Retrieved the mech's response: {res}.")
        self.mech_response_api.reset_retries()
        return res

    def _get_response(self) -> WaitableConditionType:
        """Get the response data from IPFS."""
        specs = self.mech_response_api.get_spec()
        res_raw = yield from self.get_http_response(**specs)
        res = self.mech_response_api.process_response(res_raw)
        res = self._handle_response(res)

        if self.mech_response_api.is_retries_exceeded():
            error = "Retries were exceeded while trying to get the mech's response."
            self._mech_response = MechInteractionResponse(error=error)
            return True

        if res is None:
            return False

        try:
            self._mech_response = MechInteractionResponse(**res)
        except (ValueError, TypeError):
            self._mech_response = MechInteractionResponse.incorrect_format(res)

        return True

    def _get_decision(
        self,
    ) -> Generator[None, None, Tuple[Optional[int], Optional[float]]]:
        """Get the vote and it's confidence."""
        for step in (
            self._get_block_number,
            self._get_request_id,
            self._get_response_hash,
            self._get_response,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        self.context.logger.info(f"Decision has been received:\n{self.mech_response}")
        if self.mech_response.result is None:
            self.context.logger.error(
                f"There was an error on the mech's response: {self.mech_response.error}"
            )
            return None, None

        return self.mech_response.result.vote, self.mech_response.result.confidence

    def _is_profitable(self, confidence: float) -> bool:
        """Whether the decision is profitable or not."""
        bet_threshold = self.params.bet_threshold

        if bet_threshold < 0:
            self.context.logger.warning(
                f"A negative bet threshold was given ({bet_threshold}), "
                f"which means that the profitability check will be bypassed!"
            )
            return True

        bet_amount = self.params.get_bet_amount(confidence)
        fee = self.synchronized_data.sampled_bet.fee
        return bet_amount - fee >= bet_threshold

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            vote, confidence = yield from self._get_decision()
            is_profitable = None
            if vote is not None and confidence is not None:
                is_profitable = self._is_profitable(confidence)
            payload = DecisionReceivePayload(
                self.context.agent_address,
                is_profitable,
                vote,
                confidence,
            )

        yield from self.finish_behaviour(payload)
