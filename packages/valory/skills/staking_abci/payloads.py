# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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

"""This module contains the transaction payloads for the staking abci."""

from dataclasses import dataclass
from typing import Optional

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload


@dataclass(frozen=True)
class MultisigTxPayload(BaseTxPayload):
    """Represents a transaction payload for preparing an on-chain transaction to be sent via the agents' multisig."""

    tx_submitter: str
    tx_hash: Optional[str]


@dataclass(frozen=True)
class CallCheckpointPayload(MultisigTxPayload):
    """A transaction payload for the checkpoint call."""

    service_staking_state: int
    ts_checkpoint: int
    is_checkpoint_reached: bool
    agent_ids: str
    service_id: Optional[int]
