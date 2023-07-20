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

import re
from dataclasses import dataclass
from string import Template
from typing import Any, Dict, Set

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


RE_CONTENT_IN_BRACKETS = r"\{([^}]*)\}"
REQUIRED_BET_TEMPLATE_KEYS = {"yes", "no", "question"}
Template.delimiter = "@"


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls = DecisionMakerAbciApp


def extract_keys_from_template(delimiter: str, template: str) -> Set[str]:
    """Extract the keys from a string template, given the delimiter."""
    # matches the placeholders of the template's keys
    pattern = re.escape(delimiter) + RE_CONTENT_IN_BRACKETS
    keys = re.findall(pattern, template)
    return set(keys)


def check_prompt_template(bet_prompt_template: Template) -> None:
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
        self.mech_agent_id: int = self._ensure("mech_agent_id", kwargs, int)
        self.mech_tool: int = self._ensure("mech_tool", kwargs, str)
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
        self._prompt_template: str = self._ensure("prompt_template", kwargs, str)
        check_prompt_template(self.prompt_template)
        multisend_address = kwargs.get("multisend_address", None)
        enforce(multisend_address is not None, "Multisend address not specified!")
        self.multisend_address = multisend_address
        super().__init__(*args, **kwargs)

    @property
    def prompt_template(self) -> Template:
        """Get the prompt template as a string `Template`."""
        return Template(self._prompt_template)

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
