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

"""This module contains the models for the skill."""

from dataclasses import dataclass
from typing import Any, Dict

from aea.exceptions import enforce
from hexbytes import HexBytes

from packages.valory.contracts.multisend.contract import MultiSendOperation
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.market_manager_abci.models import MarketManagerParams


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = DecisionMakerAbciApp


class DecisionMakerParams(MarketManagerParams):
    """Decision maker's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.mech_agent_address: str = self._ensure("mech_agent_address", kwargs, str)
        self.mech_tool: str = self._ensure("mech_tool", kwargs, str)
        # this is a mapping from the confidence of a bet's choice to the amount we are willing to bet
        self.bet_amount_per_threshold: Dict[float, int] = self._ensure(
            "bet_amount_per_threshold", kwargs, Dict[float, int]
        )
        # the threshold amount in WEI starting from which we are willing to place a bet
        self.bet_threshold: int = self._ensure("bet_threshold", kwargs, int)
        # the duration, in seconds, of blacklisting a bet before retrying to make an estimate for it
        self.blacklisting_duration: int = self._ensure(
            "blacklisting_duration", kwargs, int
        )
        self._ipfs_address: str = self._ensure("ipfs_address", kwargs, str)
        multisend_address = kwargs.get("multisend_address", None)
        enforce(multisend_address is not None, "Multisend address not specified!")
        self.multisend_address = multisend_address
        super().__init__(*args, **kwargs)

    @property
    def ipfs_address(self) -> str:
        """Get the IPFS address."""
        if self._ipfs_address.endswith("/"):
            return self._ipfs_address
        return f"{self._ipfs_address}/"

    def get_bet_amount(self, confidence: float) -> int:
        """Get the bet amount given a prediction's confidence."""
        threshold = round(confidence, 1)
        return self.bet_amount_per_threshold[threshold]


@dataclass
class MultisendBatch:
    """A structure representing a single transaction of a multisend."""

    to: str
    data: HexBytes
    value: int = 0
    operation: MultiSendOperation = MultiSendOperation.CALL
