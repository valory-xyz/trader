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

from typing import Any, Generator, Optional, Tuple, Union, cast

from packages.valory.contracts.mech.contract import Mech
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.io_.store import SupportedFiletype
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MechInteractionResponse
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)


IPFS_HASH_PREFIX = "f01701220"


class DecisionReceiveBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents receive the mech response."""

    matching_round = DecisionReceiveRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._from_block: int = 0
        self._request_id: int = 0
        self._response_hex: str = ""

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
    def ipfs_link(self) -> str:
        """Get the IPFS link using the response hex."""
        full_ipfs_hash = IPFS_HASH_PREFIX + self.response_hex
        return self.params.ipfs_address + full_ipfs_hash + f"/{self.request_id}"

    def _get_block_number(self) -> WaitableConditionType:
        """Get the block number in which the request to the mech was settled."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=None,
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
        return result

    def _get_response(self) -> Generator[None, None, Optional[MechInteractionResponse]]:
        """Get the response data from IPFS."""
        res = yield from self.get_from_ipfs(self.ipfs_link, SupportedFiletype.JSON)
        if res is None:
            return None

        try:
            prediction = MechInteractionResponse(**cast(dict, res))
        except (ValueError, TypeError):
            return MechInteractionResponse.incorrect_format(res)
        else:
            return prediction

    def _get_decision(
        self,
    ) -> Generator[None, None, Tuple[Optional[int], Optional[float]]]:
        """Get the vote and it's confidence."""
        for step in (
            self._get_block_number,
            self._get_request_id,
            self._get_response_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        mech_response = yield from self._get_response()
        if mech_response is None:
            self.context.logger.error("No decision has been received from the mech.")
            return None, None

        self.context.logger.info(f"Decision has been received:\n{mech_response}")
        if mech_response.result is None:
            msg = f"There was an error on the mech response: {mech_response.error}"
            self.context.logger.error(msg)
            return None, None

        return mech_response.result.vote, mech_response.result.confidence

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
