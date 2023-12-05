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

"""This module contains the handler for the 'decision_maker_abci' skill."""

from typing import cast

from packages.valory.protocols.ipfs import IpfsMessage
from packages.valory.skills.abstract_round_abci.handlers import (
    ABCIRoundHandler as BaseABCIRoundHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import AbstractResponseHandler
from packages.valory.skills.abstract_round_abci.handlers import (
    ContractApiHandler as BaseContractApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    HttpHandler as BaseHttpHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    LedgerApiHandler as BaseLedgerApiHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    SigningHandler as BaseSigningHandler,
)
from packages.valory.skills.abstract_round_abci.handlers import (
    TendermintHandler as BaseTendermintHandler,
)
from packages.valory.skills.decision_maker_abci.models import SharedState


ABCIHandler = BaseABCIRoundHandler
HttpHandler = BaseHttpHandler
SigningHandler = BaseSigningHandler
LedgerApiHandler = BaseLedgerApiHandler
ContractApiHandler = BaseContractApiHandler
TendermintHandler = BaseTendermintHandler


class IpfsHandler(AbstractResponseHandler):
    """IPFS message handler."""

    SUPPORTED_PROTOCOL = IpfsMessage.protocol_id
    allowed_response_performatives = frozenset({IpfsMessage.Performative.IPFS_HASH})
    custom_support_performative = IpfsMessage.Performative.FILES

    @property
    def shared_state(self) -> SharedState:
        """Get the parameters."""
        return cast(SharedState, self.context.state)

    def handle(self, message: IpfsMessage) -> None:
        """
        Implement the reaction to an IPFS message.

        :param message: the message
        :return: None
        """
        self.context.logger.debug(f"Received message: {message}")
        self.shared_state.in_flight_req = False

        if message.performative != self.custom_support_performative:
            return super().handle(message)

        dialogue = self.context.ipfs_dialogues.update(message)
        nonce = dialogue.dialogue_label.dialogue_reference[0]
        callback = self.shared_state.req_to_callback.pop(nonce)
        callback(message, dialogue)
