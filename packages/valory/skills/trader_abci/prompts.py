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


CHATUI_PROMPT = """
You are an expert assistant tasked with helping users update an agent's trading configuration.

Configuration details:
- Trading strategy: "{current_trading_strategy}"
    -- Available strategies: "kelly_criterion_no_conf", "bet_amount_per_threshold", "mike_strat"

Carefully read the user's prompt below and decide what configuration changes, if any, should be made. If the prompt is unclear, irrelevant, or does not specify a supported value, set all fields to null and explain why—null means no change. If only one field should be updated, set the others to null.

Always include a clear message to the user explaining your reasoning for the update, or ask for clarification if needed.

User prompt: "{user_prompt}"
"""


@dataclass(frozen=True)
class BetAmountPerThreshold:
    """BetAmountPerThreshold"""

    zero_point_zero: typing.Optional[int]
    zero_point_one: typing.Optional[int]
    zero_point_two: typing.Optional[int]
    zero_point_three: typing.Optional[int]
    zero_point_four: typing.Optional[int]
    zero_point_five: typing.Optional[int]
    zero_point_six: typing.Optional[int]
    zero_point_seven: typing.Optional[int]
    zero_point_eight: typing.Optional[int]
    zero_point_nine: typing.Optional[int]
    one_point_zero: typing.Optional[int]
    one_point_one: typing.Optional[int]


class TradingStrategy(enum.Enum):
    """TradingStrategy"""

    KELLY_CRITERION_NO_CONF = "kelly_criterion_no_conf"
    BET_AMOUNT_PER_THRESHOLD = "bet_amount_per_threshold"
    MIKE_STRAT = "mike_strat"


@dataclass(frozen=True)
class UpdatedAgentConfig:
    """UpdatedAgentConfig"""

    # bet_amount_per_threshold: typing.Optional[BetAmountPerThreshold] # noqa: E800
    trading_strategy: typing.Optional[TradingStrategy]


@dataclass(frozen=True)
class ChatUILLMResponse:
    """ChatUILLMResponse"""

    updated_agent_config: typing.Optional[UpdatedAgentConfig]

    message: str


def build_chatui_llm_response_schema() -> dict:
    """Build a schema for the ChatUILLMResponse."""
    return {"class": pickle.dumps(ChatUILLMResponse).hex(), "is_list": False}
