#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2025 Valory AG
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


"""This package contains LLM prompts."""

import enum
import pickle  # nosec
import typing
from dataclasses import dataclass


AUTOMATIC_SELECTION_VALUE = "###automatic_selection###"

CHATUI_PROMPT = (  # nosec
    """
You are an expert assistant tasked with helping users update an agent's trading configuration.

Configuration details:
- Trading strategy: "{current_trading_strategy}"
    -- Available strategies:
        --- "kelly_criterion_no_conf": Uses the Kelly Criterion formula, a well-known method in finance to optimize profits while maximizing the long-term return on an investment. The AI's predicted probability and market parameters are used to compute the bet amount, which is then adjusted based on the tool's weighted accuracy (higher accuracy increases trust in the suggested amount).
        --- "bet_amount_per_threshold": A static betting strategy using a mapping from confidence thresholds to fixed bet amounts. For example, with a mapping like {{"0.6": 60000000000000000, "0.7": 90000000000000000, ...}}, higher AI confidence leads to higher bet amounts. Here, 0.6 means 60 percent confidence, and 60000000000000000 means the amount in wei.
        --- "mike_strat": Similar to "bet_amount_per_threshold", but the fixed amount from the mapping is multiplied by the AI's confidence (e.g., for confidence 0.6 and mapping value 60000000000000000, the bet is 0.6 * 60000000000000000). Again, 0.6 means 60 percent confidence, and 60000000000000000 means wei.
- Mech tool:
    -- Available tools: {available_tools}
    -- Can be set to \""""
    + AUTOMATIC_SELECTION_VALUE
    + """\" to let the agent choose the best tool based on its policy if the user says to remove the tool.

Carefully read the user's prompt below and decide what configuration changes, if any, should be made. If only one field should be updated, set the others to null.

Always include a clear message to the user explaining your reasoning for the update, or ask for clarification if needed. This message should be phrased in a way that is for the user, not for the agent. The user may not always ask for a change, the user can also ask for information about the current configuration or the available configurations.

User prompt: "{user_prompt}"
"""
)


class TradingStrategy(enum.Enum):
    """TradingStrategy"""

    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
    MIKE_STRAT = "mike_strat"


@dataclass(frozen=True)
class UpdatedAgentConfig:
    """UpdatedAgentConfig"""

    trading_strategy: typing.Optional[TradingStrategy]
    mech_tool: typing.Optional[str]


@dataclass(frozen=True)
class ChatUILLMResponse:
    """ChatUILLMResponse"""

    updated_agent_config: typing.Optional[UpdatedAgentConfig]

    message: str


def build_chatui_llm_response_schema() -> dict:
    """Build a schema for the ChatUILLMResponse."""
    return {"class": pickle.dumps(ChatUILLMResponse).hex(), "is_list": False}
