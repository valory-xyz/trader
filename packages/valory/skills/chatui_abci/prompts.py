#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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
from typing import List

from pydantic import BaseModel

CHATUI_PROMPT = """You are an expert assistant tasked with helping users update an agent's trading configuration.

Configuration details:
- Trading strategy: "{current_trading_strategy}"
    -- Available strategies:
        --- "kelly_criterion": Uses the Kelly Criterion formula, a well-known method in finance to optimize the long-term return on an investment. The AI's predicted probability and real market conditions are used to compute the optimal bet amount and which side to bet on. This is also known as the risky strategy.
        --- "fixed_bet": A simple fixed-amount betting strategy. The user sets a fixed bet size that applies to all trades. This is also known as the balanced strategy.
    -- Can not be deselected, but can be changed to another strategy if the user says to change it.
- Allowed tools: {current_allowed_tools}
    -- Available tools: {available_tools}
    -- When set, the agent's e-greedy policy will only select from this subset of tools on each trade. The policy continues learning across all tools, but selection is restricted to the allowed list.
    -- When null/empty, the agent freely selects from all available tools based on its policy.
    -- Can be cleared to restore unrestricted tool selection if the user says to remove or clear the allowed tools.
    -- Each tool in the list must be one of the available tools listed above.
    -- The user can add tools to or remove individual tools from the current allowed list, or replace it entirely.
- Fixed bet size: "{current_fixed_bet_size}"
    -- Used with the "fixed_bet" (Balanced) strategy only.
    -- When set, this overrides the threshold-based bet amounts and uses a fixed amount for all bets.
    -- Value is in {units} units.
    -- Cannot be less than {absolute_min_bet_size} {units}.
    -- Cannot exceed {absolute_max_bet_size} {units}.
    -- Can be deselected to fall back to the default value if the user says to remove it.
- Max bet size: "{current_max_bet_size}"
    -- Used with the "kelly_criterion" (Risky) strategy only.
    -- When set, this caps the maximum bet amount calculated by the Kelly Criterion formula.
    -- Value is in {units} units.
    -- Cannot be less than {absolute_min_bet_size} {units}.
    -- Cannot exceed {absolute_max_bet_size} {units}.
    -- Can be deselected to fall back to the default value if the user says to remove it.

Note: The fixed_bet_size parameter only applies when using the Balanced strategy, and max_bet_size only applies when using the Risky strategy. Setting one does not affect the other strategy.

Carefully read the user's prompt below and decide what configuration changes, if any, should be made. If only one field should be updated, set the others to null. A field can not be deselected and set at the same time.

Always include a clear message to the user explaining your reasoning for the update, or ask for clarification if needed. This message should be phrased in a way that is for the user, not for the agent. The user may not always ask for a change, the user can also ask for information about the current configuration or the available configurations, in which case, you should respond appropriately. You can format your message using basic HTML tags such as <b> for bold, <i> for italics, <ul>/<li> for lists, and <br> for line breaks. Use these tags to make your explanation clearer and easier to read.

When summarizing your actions, include a field called 'behavior' that describes the agent's behavior in one sentence. This description should be easy for a non-technical user to understand. For example: 'A steady, conservative fixed trade size on markets independent of agent confidence. Ensures a fixed cost basis and insulates outcomes from agent sizing logic instead allowing wins, loss, and market odds at time of participation to determine ROI.' if using fixed_bet or 'Dynamic trade sizes based on the pre-existing market conditions, agent confidence, and available agent funds. This more complex strategy allows both agent sizing bias, and market outcome to determine payout and loss and may be subject to greater volatility.' if using kelly_criterion.

Always refer to actions as a 'trade' when communicating with users; never describe them as a bet.

User prompt: "{user_prompt}"
"""


class TradingStrategy(enum.Enum):
    """TradingStrategy"""

    KELLY_CRITERION = "kelly_criterion"
    FIXED_BET = "fixed_bet"


class FieldsThatCanBeRemoved(enum.Enum):
    """FieldsThatCanBeRemoved"""

    ALLOWED_TOOLS = "allowed_tools"
    FIXED_BET_SIZE = "fixed_bet_size"
    MAX_BET_SIZE = "max_bet_size"


class UpdatedAgentConfig(BaseModel):
    """UpdatedAgentConfig"""

    trading_strategy: typing.Optional[TradingStrategy]
    allowed_tools: typing.Optional[List[str]]
    fixed_bet_size: typing.Optional[float]
    max_bet_size: typing.Optional[float]
    removed_config_fields: typing.List[FieldsThatCanBeRemoved]
    behavior: typing.Optional[str]


class ChatUILLMResponse(BaseModel):
    """ChatUILLMResponse"""

    updated_agent_config: typing.Optional[UpdatedAgentConfig]
    message: str


def build_chatui_llm_response_schema() -> dict:
    """Build a schema for the ChatUILLMResponse."""
    return {"class": pickle.dumps(ChatUILLMResponse).hex(), "is_list": False}
