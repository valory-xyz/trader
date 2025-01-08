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

"""This module contains the response state of the mech interaction abci app."""

import json
from typing import Any, Callable, Dict, Generator, List, Optional

from web3.constants import ADDRESS_ZERO

from packages.valory.contracts.mech.contract import Mech
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.mech_interact_abci.behaviours.base import (
    DataclassEncoder,
    MechInteractBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.mech_interact_abci.behaviours.request import V1_HEX_PREFIX
from packages.valory.skills.mech_interact_abci.models import MechResponseSpecs
from packages.valory.skills.mech_interact_abci.payloads import MechResponsePayload
from packages.valory.skills.mech_interact_abci.states.base import (
    MechInteractionResponse,
    MechRequest,
)
from packages.valory.skills.mech_interact_abci.states.response import MechResponseRound


IPFS_HASH_PREFIX = f"{V1_HEX_PREFIX}701220"


class MechResponseBehaviour(MechInteractBaseBehaviour):
    """A behaviour in which the agents receive the Mech's responses."""

    matching_round = MechResponseRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._from_block: int = 0
        self._requests: List[MechRequest] = []
        self._response_hex: str = ""
        self._mech_responses: List[
            MechInteractionResponse
        ] = self.synchronized_data.mech_responses
        self._current_mech_response: MechInteractionResponse = MechInteractionResponse(
            error="The mech's response has not been set!"
        )

    @property
    def from_block(self) -> int:
        """Get the block number in which the request to the mech was settled."""
        return self._from_block

    @from_block.setter
    def from_block(self, from_block: int) -> None:
        """Set the block number in which the request to the mech was settled."""
        self._from_block = from_block

    @property
    def requests(self) -> List[MechRequest]:
        """Get the requests."""
        return self._requests

    @requests.setter
    def requests(self, requests: List[Dict[str, str]]) -> None:
        """Set the requests."""
        self._requests = [MechRequest(**request) for request in requests]

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

    @property
    def serialized_responses(self) -> str:
        """Get the Mech's responses serialized."""
        return json.dumps(self._mech_responses, cls=DataclassEncoder)

    def setup(self) -> None:
        """Set up the `MechResponse` behaviour."""
        self._mech_responses = self.synchronized_data.mech_responses

    def set_mech_response_specs(self, request_id: int) -> None:
        """Set the mech's response specs."""
        full_ipfs_hash = IPFS_HASH_PREFIX + self.response_hex
        ipfs_link = self.params.ipfs_address + full_ipfs_hash + f"/{request_id}"
        # The url must be dynamically generated as it depends on the ipfs hash
        self.mech_response_api.__dict__["_frozen"] = False
        self.mech_response_api.url = ipfs_link
        self.mech_response_api.__dict__["_frozen"] = True

    def _get_block_number(self) -> WaitableConditionType:
        """Get the block number in which the request to the mech was settled."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            # we do not need the address to get the block number, but the base method does
            contract_address=ADDRESS_ZERO,
            contract_public_id=Mech.contract_id,
            contract_callable="get_block_number",
            data_key="number",
            placeholder=get_name(MechResponseBehaviour.from_block),
            tx_hash=self.synchronized_data.final_tx_hash,
            chain_id=self.params.mech_chain_id,
        )

        return result

    @property
    def mech_contract_interact(self) -> Callable[..., WaitableConditionType]:
        """Interact with the mech contract."""
        if self.params.use_mech_marketplace:
            return self._mech_marketplace_contract_interact

        return self._mech_contract_interact

    def _process_request_event(self) -> WaitableConditionType:
        """Process the request event."""
        result = yield from self.mech_contract_interact(
            contract_callable="process_request_event",
            data_key="results",
            placeholder=get_name(MechResponseBehaviour.requests),
            tx_hash=self.synchronized_data.final_tx_hash,
            expected_logs=len(self._mech_responses),
            chain_id=self.params.mech_chain_id,
        )
        return result

    def _get_response_hash(self) -> WaitableConditionType:
        """Get the hash of the response data."""
        request_id = self._current_mech_response.requestId
        self.context.logger.info(
            f"Filtering the mech's events from block {self.from_block} "
            f"for a response to our request with id {request_id!r}."
        )
        result = yield from self.mech_contract_interact(
            contract_callable="get_response",
            data_key="data",
            placeholder=get_name(MechResponseBehaviour.response_hex),
            request_id=request_id,
            from_block=self.from_block,
            chain_id=self.params.mech_chain_id,
        )

        if result:
            self.set_mech_response_specs(request_id)

        return result

    def _handle_response(
        self,
        res: Optional[str],
    ) -> Optional[Any]:
        """Handle the response from the IPFS.

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
            self._current_mech_response.retries_exceeded()
            return True

        if res is None:
            return False

        try:
            self._current_mech_response.result = res
        except (ValueError, TypeError):
            self._current_mech_response.incorrect_format(res)

        return True

    def _set_current_response(self, request: MechRequest) -> None:
        """Set the current Mech response."""
        for pending_response in self._mech_responses:
            if (
                pending_response.data == request.data.hex()
            ):  # TODO: why is request.data bytes now?
                pending_response.requestId = request.requestId
                self._current_mech_response = pending_response
                break

    def _process_responses(
        self,
    ) -> Generator:
        """Get the response."""
        for step in (
            self._get_block_number,
            self._process_request_event,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        for request in self.requests:
            self._set_current_response(request)

            for step in (self._get_response_hash, self._get_response):
                yield from self.wait_for_condition_with_sleep(step)

            self.context.logger.info(
                f"Response has been received:\n{self._current_mech_response}"
            )
            if self._current_mech_response.result is None:
                self.context.logger.error(
                    f"There was an error in the mech's response: {self._current_mech_response.error}"
                )

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            if self.synchronized_data.final_tx_hash:
                yield from self._process_responses()

            self.context.logger.info(
                f"Received mech responses: {self.serialized_responses}"
            )

            payload = MechResponsePayload(
                self.context.agent_address,
                self.serialized_responses,
            )

        yield from self.finish_behaviour(payload)
