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

"""This module contains the base behaviour for the MarketManager ABCI application."""

import json
import os
import os.path
from abc import ABC
from json import JSONDecodeError
from typing import Any, Dict, Generator, List, Optional, cast

from aea.helpers.ipfs.base import IPFSHashOnly
from aea.protocols.base import Message

from packages.valory.connections.polymarket_client.connection import (
    PUBLIC_ID as POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID,
)
from packages.valory.protocols.srr.dialogues import SrrDialogue, SrrDialogues
from packages.valory.protocols.srr.message import SrrMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.models import Requests
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetsDecoder,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.models import (
    BenchmarkingMode,
    SharedState,
)


BETS_FILENAME = "bets.json"
MULTI_BETS_FILENAME = "multi_bets.json"
READ_MODE = "r"
WRITE_MODE = "w"


class BetsManagerBehaviour(BaseBehaviour, ABC):
    """Abstract behaviour responsible for bets management, such as storing, hashing, reading."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `BetsManagerBehaviour`."""
        super().__init__(**kwargs)
        self.bets: List[Bet] = []
        self.multi_bets_filepath: str = self.params.store_path / MULTI_BETS_FILENAME
        self.bets_filepath: str = self.params.store_path / BETS_FILENAME

    @property
    def shared_state(self) -> SharedState:
        """Get the shared state."""
        return cast(SharedState, self.context.state)

    @property
    def benchmarking_mode(self) -> BenchmarkingMode:
        """Return the benchmarking mode configurations."""
        return cast(BenchmarkingMode, self.context.benchmarking_mode)

    def _do_connection_request(
        self,
        message: Message,
        dialogue: Message,
        timeout: Optional[float] = None,
    ) -> Generator[None, None, Message]:
        """Do a request and wait the response, asynchronously."""

        self.context.outbox.put_message(message=message)
        request_nonce = self._get_request_nonce_from_dialogue(dialogue)  # type: ignore
        cast(Requests, self.context.requests).request_id_to_callback[
            request_nonce
        ] = self.get_callback_request()
        response = yield from self.wait_for_message(timeout=timeout)
        return response

    def do_connection_request(
        self,
        message: Message,
        dialogue: Message,
        timeout: Optional[float] = None,
    ) -> Generator[None, None, Message]:
        """Public wrapper for making a connection request and waiting for response."""
        return (yield from self._do_connection_request(message, dialogue, timeout))

    def send_polymarket_connection_request(
        self,
        payload_data: Dict[str, Any],
    ) -> Generator[None, None, Any]:
        """Send a request to the Polymarket connection and wait for the response."""

        self.context.logger.info(f"Payload data: {payload_data}")

        srr_dialogues = cast(SrrDialogues, self.context.srr_dialogues)
        srr_message, srr_dialogue = srr_dialogues.create(
            counterparty=str(POLYMARKET_CLIENT_CONNECTION_PUBLIC_ID),
            performative=SrrMessage.Performative.REQUEST,
            payload=json.dumps(payload_data),
        )

        srr_message = cast(SrrMessage, srr_message)
        srr_dialogue = cast(SrrDialogue, srr_dialogue)
        response = yield from self.do_connection_request(srr_message, srr_dialogue)  # type: ignore

        response_json = json.loads(response.payload)  # type: ignore

        return response_json

    def store_bets(self) -> None:
        """Store the bets to the agent's data dir as JSON."""
        serialized = serialize_bets(self.bets)
        if serialized is None:
            self.context.logger.warning("No bets to store.")
            return

        try:
            with open(self.multi_bets_filepath, WRITE_MODE) as bets_file:
                try:
                    bets_file.write(serialized)
                    return
                except (IOError, OSError):
                    err = f"Error writing to file {self.multi_bets_filepath!r}!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {self.multi_bets_filepath!r} in write mode!"

        self.context.logger.error(err)

    def read_bets(self) -> None:
        """Read the bets from the agent's data dir as JSON."""
        self.bets = []
        read_path = self.multi_bets_filepath

        if not os.path.isfile(read_path):
            self.context.logger.warning(
                f"No stored bets file was detected in {read_path}. "
                "Assuming trader is being run for the first time in multi-bets mode."
            )
            read_path = self.bets_filepath

        if not os.path.isfile(read_path):
            self.context.logger.warning(
                f"No stored bets file was detected in {read_path}. Assuming bets are empty."
            )
            return

        try:
            with open(read_path, READ_MODE) as bets_file:
                try:
                    self.bets = json.load(bets_file, cls=BetsDecoder)
                    return
                except (JSONDecodeError, TypeError):
                    err = f"Error decoding file {read_path!r} to a list of bets!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {read_path!r} in read mode!"

        self.context.logger.error(err)

    def hash_stored_bets(self) -> str:
        """Get the hash of the stored bets' file."""
        return IPFSHashOnly.hash_file(self.multi_bets_filepath)
