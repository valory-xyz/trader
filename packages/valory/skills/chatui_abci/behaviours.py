#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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


"""This package contains round behaviours of ChatUIAbciApp."""

from typing import Generator, Set, Type, cast

from packages.valory.skills.abstract_round_abci.behaviours import (
    AbstractRoundBehaviour,
    BaseBehaviour,
)
from packages.valory.skills.chatui_abci.models import ChatuiParams, SharedState
from packages.valory.skills.chatui_abci.payloads import ChatuiPayload
from packages.valory.skills.chatui_abci.rounds import ChatuiAbciApp, ChatuiLoadRound


class ChatuiLoadBehaviour(BaseBehaviour):
    """This behaviour loads the chat UI parameters into shared state and a JSON file."""

    matching_round = ChatuiLoadRound

    @property
    def params(self) -> ChatuiParams:
        """Return the params."""
        return cast(ChatuiParams, self.context.params)

    @property
    def shared_state(self) -> SharedState:
        """Return the shared state."""
        return cast(SharedState, self.context.state)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload = ChatuiPayload(sender=self.context.agent_address, vote=True)
            self.shared_state._ensure_chatui_store()
            if self.shared_state._chatui_config is None:
                raise ValueError("The chat UI config has not been set!")
            self.context.logger.info(
                f"Loaded chat UI parameters: {self.shared_state._chatui_config}"
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()


class ChatuiRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the ChatUI behaviour."""

    initial_behaviour_cls = ChatuiLoadBehaviour
    abci_app_cls = ChatuiAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {ChatuiLoadBehaviour}  # type: ignore
