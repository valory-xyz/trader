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

"""This module contains the transaction payloads of the MechInteractAbciApp."""

from dataclasses import dataclass
from typing import Optional

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload


@dataclass(frozen=True)
class MechRequestPayload(BaseTxPayload):
    """Represent a transaction payload for the MechRequestRound."""

    tx_submitter: Optional[str]
    tx_hash: Optional[str]
    price: Optional[int]
    chain_id: Optional[str]
    mech_requests: Optional[str]
    mech_responses: Optional[str]


@dataclass(frozen=True)
class MechResponsePayload(BaseTxPayload):
    """Represent a transaction payload for the MechResponseRound."""

    mech_responses: str
