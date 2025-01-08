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

"""This module contains the models for the abci skill of MechInteractAbciApp."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from aea.exceptions import enforce
from hexbytes import HexBytes

from packages.valory.contracts.multisend.contract import MultiSendOperation
from packages.valory.skills.abstract_round_abci.models import ApiSpecs, BaseParams
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.mech_interact_abci.rounds import MechInteractAbciApp


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class MechResponseSpecs(ApiSpecs):
    """A model that wraps ApiSpecs for the Mech's response specifications."""


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = MechInteractAbciApp


@dataclass(frozen=True)
class MechMarketplaceConfig:
    """The configuration for the Mech marketplace."""

    mech_marketplace_address: str
    priority_mech_address: str
    priority_mech_staking_instance_address: str
    priority_mech_service_id: int
    requester_staking_instance_address: str
    response_timeout: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MechMarketplaceConfig":
        """Create an instance from a dictionary."""
        return cls(
            mech_marketplace_address=data["mech_marketplace_address"],
            priority_mech_address=data["priority_mech_address"],
            priority_mech_staking_instance_address=data[
                "priority_mech_staking_instance_address"
            ],
            priority_mech_service_id=data["priority_mech_service_id"],
            requester_staking_instance_address=data[
                "requester_staking_instance_address"
            ],
            response_timeout=data["response_timeout"],
        )


class MechParams(BaseParams):
    """The mech interact abci skill's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Set up the mech-interaction parameters."""
        multisend_address = kwargs.get("multisend_address", None)
        enforce(multisend_address is not None, "Multisend address not specified!")
        self.multisend_address: str = multisend_address
        self.multisend_batch_size: int = self._ensure(
            "multisend_batch_size", kwargs, int
        )
        self.mech_contract_address: str = self._ensure(
            "mech_contract_address", kwargs, str
        )
        self.mech_request_price: Optional[int] = kwargs.get("mech_request_price", None)
        self._ipfs_address: str = self._ensure("ipfs_address", kwargs, str)
        self.mech_chain_id: Optional[str] = kwargs.get("mech_chain_id", "gnosis")
        self.mech_wrapped_native_token_address: Optional[str] = kwargs.get(
            "mech_wrapped_native_token_address", None
        )
        self.mech_interaction_sleep_time: int = self._ensure(
            "mech_interaction_sleep_time", kwargs, int
        )
        self.use_mech_marketplace = self._ensure("use_mech_marketplace", kwargs, bool)
        self.mech_marketplace_config: MechMarketplaceConfig = (
            MechMarketplaceConfig.from_dict(kwargs["mech_marketplace_config"])
        )
        enforce(
            not self.use_mech_marketplace
            or self.mech_contract_address
            == self.mech_marketplace_config.priority_mech_address,
            "The mech contract address must be the same as the priority mech address when using the marketplace.",
        )
        super().__init__(*args, **kwargs)

    @property
    def ipfs_address(self) -> str:
        """Get the IPFS address."""
        if self._ipfs_address.endswith("/"):
            return self._ipfs_address
        return f"{self._ipfs_address}/"


Params = MechParams


@dataclass
class MultisendBatch:
    """A structure representing a single transaction of a multisend."""

    to: str
    data: HexBytes
    value: int = 0
    operation: MultiSendOperation = MultiSendOperation.CALL
