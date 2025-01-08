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

"""This module contains the base functionality for the rounds of the mech interact abci app."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Mapping, Optional, cast

from packages.valory.skills.abstract_round_abci.base import (
    BaseTxPayload,
    CollectSameUntilThresholdRound,
    CollectionRound,
)
from packages.valory.skills.mech_interact_abci.payloads import (
    MechRequestPayload,
    MechResponsePayload,
)
from packages.valory.skills.transaction_settlement_abci.rounds import (
    SynchronizedData as TxSynchronizedData,
)


class Event(Enum):
    """MechInteractAbciApp Events"""

    DONE = "done"
    NO_MAJORITY = "no_majority"
    ROUND_TIMEOUT = "round_timeout"
    SKIP_REQUEST = "skip_request"


@dataclass
class MechMetadata:
    """A Mech's metadata."""

    prompt: str
    tool: str
    nonce: str


@dataclass
class MechRequest:
    """A Mech's request."""

    data: str = ""
    requestId: int = 0


@dataclass
class MechInteractionResponse(MechRequest):
    """A structure for the response of a mech interaction task."""

    nonce: str = ""
    result: Optional[str] = None
    error: str = "Unknown"

    def retries_exceeded(self) -> None:
        """Set an incorrect format response."""
        self.error = "Retries were exceeded while trying to get the mech's response."

    def incorrect_format(self, res: Any) -> None:
        """Set an incorrect format response."""
        self.error = f"The response's format was unexpected: {res}"


class SynchronizedData(TxSynchronizedData):
    """
    Class to represent the synchronized data.

    This data is replicated by the tendermint application.
    """

    @property
    def mech_price(self) -> int:
        """Get the mech's request price."""
        return int(self.db.get_strict("mech_price"))

    @property
    def mech_requests(self) -> List[MechMetadata]:
        """Get the mech requests."""
        requests = self.db.get("mech_requests", "[]")
        if isinstance(requests, str):
            requests = json.loads(requests)
        return [MechMetadata(**metadata_item) for metadata_item in requests]

    @property
    def mech_responses(self) -> List[MechInteractionResponse]:
        """Get the mech responses."""
        responses = self.db.get("mech_responses", "[]")
        if isinstance(responses, str):
            responses = json.loads(responses)
        return [MechInteractionResponse(**response_item) for response_item in responses]

    @property
    def participant_to_requests(self) -> Mapping[str, MechRequestPayload]:
        """Get the `participant_to_requests`."""
        serialized = self.db.get_strict("participant_to_requests")
        deserialized = CollectionRound.deserialize_collection(serialized)
        return cast(Mapping[str, MechRequestPayload], deserialized)

    @property
    def participant_to_responses(self) -> Mapping[str, MechResponsePayload]:
        """Get the `participant_to_responses`."""
        serialized = self.db.get_strict("participant_to_responses")
        deserialized = CollectionRound.deserialize_collection(serialized)
        return cast(Mapping[str, MechResponsePayload], deserialized)

    @property
    def final_tx_hash(self) -> Optional[str]:
        """Get the verified tx hash."""
        return cast(str, self.db.get("final_tx_hash", None))

    @property
    def chain_id(self) -> Optional[str]:
        """Get the chain name where to send the transactions."""
        return cast(str, self.db.get("chain_id", None))

    @property
    def tx_submitter(self) -> str:
        """Get the round that submitted a tx to transaction_settlement_abci."""
        return str(self.db.get_strict("tx_submitter"))


class MechInteractionRound(CollectSameUntilThresholdRound):
    """A base round for the mech interactions."""

    payload_class = BaseTxPayload
    synchronized_data_class = SynchronizedData
    done_event = Event.DONE
    no_majority_event = Event.NO_MAJORITY
