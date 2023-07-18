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

"""This module contains the transaction payloads for the decision maker."""

from dataclasses import dataclass
from typing import Optional

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload


@dataclass(frozen=True)
class DecisionMakerPayload(BaseTxPayload):
    """Represents a transaction payload for the decision-making."""

    unsupported: bool
    is_profitable: bool
    vote: Optional[int]
    confidence: Optional[float]


@dataclass(frozen=True)
class SamplingPayload(UpdateBetsPayload):
    """Represents a transaction payload for the sampling of a bet."""

    index: Optional[int]


@dataclass(frozen=True)
class MultisigTxPayload(BaseTxPayload):
    """Represents a transaction payload for preparing an on-chain transaction to be sent via the agents' multisig."""

    tx_hash: Optional[str]
