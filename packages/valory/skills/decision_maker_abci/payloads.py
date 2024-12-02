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

"""This module contains the transaction payloads for the decision maker."""

from dataclasses import dataclass
from typing import Optional

from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload


@dataclass(frozen=True)
class DecisionReceivePayload(UpdateBetsPayload):
    """Represents a transaction payload for the decision-making."""

    is_profitable: Optional[bool]
    vote: Optional[int]
    confidence: Optional[float]
    bet_amount: Optional[int]
    next_mock_data_row: Optional[int]
    decision_received_timestamp: Optional[int]


@dataclass(frozen=True)
class SamplingPayload(UpdateBetsPayload):
    """Represents a transaction payload for the sampling of a bet."""

    index: Optional[int]
    benchmarking_finished: Optional[bool]
    day_increased: Optional[bool]


@dataclass(frozen=True)
class MultisigTxPayload(BaseTxPayload):
    """Represents a transaction payload for preparing an on-chain transaction to be sent via the agents' multisig."""

    tx_submitter: Optional[str] = None
    tx_hash: Optional[str] = None
    mocking_mode: Optional[bool] = None


@dataclass(frozen=True)
class RedeemPayload(MultisigTxPayload):
    """Represents a transaction payload for preparing an on-chain transaction for redeeming."""

    mech_tools: str = "[]"
    policy: Optional[str] = None
    utilized_tools: Optional[str] = None
    redeemed_condition_ids: Optional[str] = None
    payout_so_far: Optional[int] = None


@dataclass(frozen=True)
class DecisionRequestPayload(BaseTxPayload):
    """Represents a transaction payload for preparing mech requests."""

    mech_requests: Optional[str] = None
    mocking_mode: Optional[bool] = None


@dataclass(frozen=True)
class SubscriptionPayload(MultisigTxPayload):
    """Represents a transaction payload for subscribing."""

    agreement_id: str = ""
    wallet_balance: Optional[int] = None


@dataclass(frozen=True)
class ClaimPayload(BaseTxPayload):
    """Represents a transaction payload for claiming a subscription."""

    vote: bool


@dataclass(frozen=True)
class VotingPayload(BaseTxPayload):
    """Represents a transaction payload for voting."""

    vote: bool


@dataclass(frozen=True)
class BlacklistingPayload(UpdateBetsPayload):
    """Represents a transaction payload for blacklisting."""

    policy: str


@dataclass(frozen=True)
class ToolSelectionPayload(BaseTxPayload):
    """Represents a transaction payload for selecting a mech tool."""

    mech_tools: Optional[str]
    policy: Optional[str]
    utilized_tools: Optional[str]
    selected_tool: Optional[str]


@dataclass(frozen=True)
class BetPlacementPayload(MultisigTxPayload):
    """Represents a transaction payload for placing a bet."""

    wallet_balance: Optional[int] = None
