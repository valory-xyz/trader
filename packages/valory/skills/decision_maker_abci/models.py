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

import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional, Set, Union

from aea.exceptions import enforce
from aea.skills.base import SkillContext
from hexbytes import HexBytes
from web3.types import BlockIdentifier

from packages.valory.contracts.multisend.contract import MultiSendOperation
from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.decision_maker_abci.redeem_info import Trade
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.market_manager_abci.models import MarketManagerParams


RE_CONTENT_IN_BRACKETS = r"\{([^}]*)\}"
REQUIRED_BET_TEMPLATE_KEYS = {"yes", "no", "question"}
DEFAULT_FROM_BLOCK = "earliest"


FromBlockMappingType = Dict[HexBytes, Union[int, str]]


class PromptTemplate(Template):
    """A prompt template."""

    delimiter = "@"


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


@dataclass
class RedeemingProgress:
    """A structure to keep track of the redeeming check progress."""

    trades: Set[Trade] = field(default_factory=lambda: set())
    utilized_tools: Dict[str, int] = field(default_factory=lambda: {})
    policy: Optional[EGreedyPolicy] = None
    claimable_amounts: Dict[HexBytes, int] = field(default_factory=lambda: {})
    from_block_mapping: FromBlockMappingType = field(
        default_factory=lambda: defaultdict(lambda: DEFAULT_FROM_BLOCK)
    )
    from_block: BlockIdentifier = "earliest"
    to_block: BlockIdentifier = "latest"
    payouts: Dict[str, int] = field(default_factory=lambda: {})
    started: bool = False

    @property
    def finished(self) -> bool:
        """Whether the check has finished."""
        return self.started and self.from_block == self.to_block


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = DecisionMakerAbciApp

    def __init__(self, *args: Any, skill_context: SkillContext, **kwargs: Any) -> None:
        """Initialize the state."""
        super().__init__(*args, skill_context=skill_context, **kwargs)
        self.redeeming_progress: RedeemingProgress = RedeemingProgress()


def extract_keys_from_template(delimiter: str, template: str) -> Set[str]:
    """Extract the keys from a string template, given the delimiter."""
    # matches the placeholders of the template's keys
    pattern = re.escape(delimiter) + RE_CONTENT_IN_BRACKETS
    keys = re.findall(pattern, template)
    return set(keys)


def check_prompt_template(bet_prompt_template: PromptTemplate) -> None:
    """Check if the keys required for a bet are given in the provided prompt's template."""
    delimiter = bet_prompt_template.delimiter
    template_keys = extract_keys_from_template(delimiter, bet_prompt_template.template)
    if template_keys != REQUIRED_BET_TEMPLATE_KEYS:
        example_key = (REQUIRED_BET_TEMPLATE_KEYS - template_keys).pop()
        n_found = len(template_keys)
        found = "no keys" if n_found == 0 else f"keys {template_keys}"
        raise ValueError(
            f"The bet's template should contain exclusively the following keys: {REQUIRED_BET_TEMPLATE_KEYS}.\n"
            f"Found {found} instead in the given template:\n{bet_prompt_template.template!r}\n"
            f"Please make sure that you are using the right delimiter {delimiter!r} for the prompt's template.\n"
            f"For example, to parametrize {example_key!r} you may use "
            f"'{delimiter}{{{example_key}}}'"
        )


class DecisionMakerParams(MarketManagerParams):
    """Decision maker's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
        self.mech_agent_address: str = self._ensure("mech_agent_address", kwargs, str)
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
        self._prompt_template: str = self._ensure("prompt_template", kwargs, str)
        check_prompt_template(self.prompt_template)
        multisend_address = kwargs.get("multisend_address", None)
        enforce(multisend_address is not None, "Multisend address not specified!")
        self.multisend_address = multisend_address
        self.dust_threshold = self._ensure("dust_threshold", kwargs, int)
        self.conditional_tokens_address = self._ensure(
            "conditional_tokens_address", kwargs, str
        )
        self.realitio_proxy_address = self._ensure(
            "realitio_proxy_address", kwargs, str
        )
        self.realitio_address = self._ensure("realitio_address", kwargs, str)
        # this is the maximum batch size that will be used when filtering blocks for events.
        # increasing this number allows for faster filtering operations,
        # but also increases the chances of getting a timeout error from the RPC
        self.event_filtering_batch_size = self._ensure(
            "event_filtering_batch_size", kwargs, int
        )
        # this is the max number of redeeming operations that will be batched on a single multisend transaction.
        # increasing this number equals fewer fees but more chances for the transaction to fail
        self.redeeming_batch_size = self._ensure("redeeming_batch_size", kwargs, int)
        # a slippage in the range of [0, 1] to apply to the `minOutcomeTokensToBuy` when buying shares on a fpmm
        self._slippage = 0.0
        self.slippage: float = self._ensure("slippage", kwargs, float)
        self.epsilon: float = self._ensure("policy_epsilon", kwargs, float)
        self.agent_registry_address: str = self._ensure(
            "agent_registry_address", kwargs, str
        )
        self.policy_store_path: Path = self.get_policy_store_path(kwargs)
        self.irrelevant_tools: set = set(self._ensure("irrelevant_tools", kwargs, list))
        super().__init__(*args, **kwargs)

    @property
    def ipfs_address(self) -> str:
        """Get the IPFS address."""
        if self._ipfs_address.endswith("/"):
            return self._ipfs_address
        return f"{self._ipfs_address}/"

    @property
    def prompt_template(self) -> PromptTemplate:
        """Get the prompt template as a string `PromptTemplate`."""
        return PromptTemplate(self._prompt_template)

    @property
    def slippage(self) -> float:
        """Get the slippage."""
        return self._slippage

    @slippage.setter
    def slippage(self, slippage: float) -> None:
        """Set the slippage."""
        if slippage < 0 or slippage > 1:
            raise ValueError(
                f"The configured slippage {slippage!r} is not in the range [0, 1]."
            )
        self._slippage = slippage

    def get_bet_amount(self, confidence: float) -> int:
        """Get the bet amount given a prediction's confidence."""
        threshold = round(confidence, 1)
        return self.bet_amount_per_threshold[threshold]

    def get_policy_store_path(self, kwargs: Dict) -> Path:
        """Get the path of the policy store."""
        path = self._ensure("policy_store_path", kwargs, str)
        # check if path exists, and we can write to it
        if (
            not os.path.isdir(path)
            or not os.access(path, os.W_OK)
            or not os.access(path, os.R_OK)
        ):
            raise ValueError(
                f"Policy store path {path!r} is not a directory or is not writable."
            )
        return Path(path)


class MechResponseSpecs(ApiSpecs):
    """A model that wraps ApiSpecs for the Mech's response specifications."""


class AgentToolsSpecs(ApiSpecs):
    """A model that wraps ApiSpecs for the Mech agent's tools specifications."""


@dataclass
class MultisendBatch:
    """A structure representing a single transaction of a multisend."""

    to: str
    data: HexBytes
    value: int = 0
    operation: MultiSendOperation = MultiSendOperation.CALL


@dataclass(init=False)
class PredictionResponse:
    """A response of a prediction."""

    p_yes: float
    p_no: float
    confidence: float
    info_utility: float

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the mech's prediction ignoring extra keys."""
        self.p_yes = float(kwargs.pop("p_yes"))
        self.p_no = float(kwargs.pop("p_no"))
        self.confidence = float(kwargs.pop("confidence"))
        self.info_utility = float(kwargs.pop("info_utility"))

        # all the fields are probabilities; run checks on whether the current prediction response is valid or not.
        probabilities = (getattr(self, field) for field in self.__annotations__)
        if (
            any(not (0 <= prob <= 1) for prob in probabilities)
            or self.p_yes + self.p_no != 1
        ):
            raise ValueError("Invalid prediction response initialization.")

    @property
    def vote(self) -> Optional[int]:
        """Return the vote. `0` represents "yes" and `1` represents "no"."""
        if self.p_no != self.p_yes:
            return int(self.p_no > self.p_yes)
        return None


@dataclass(init=False)
class MechInteractionResponse:
    """A structure for the response of a mech interaction task."""

    request_id: int
    result: Optional[PredictionResponse]
    error: str

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the mech's response ignoring extra keys."""
        self.request_id = kwargs.pop("requestId", 0)
        self.error = kwargs.pop("error", "Unknown")
        self.result = kwargs.pop("result", None)

        if isinstance(self.result, str):
            self.result = PredictionResponse(**json.loads(self.result))

    @classmethod
    def incorrect_format(cls, res: Any) -> "MechInteractionResponse":
        """Return an incorrect format response."""
        response = cls()
        response.error = f"The response's format was unexpected: {res}"
        return response
