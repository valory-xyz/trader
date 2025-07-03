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
You are an expert assistant responsible for updating the configuration of an agent based on user input.

The agent's current configuration is:
- current_trading_strategy: "{current_trading_strategy}"

Carefully analyze the following user prompt and determine the most appropriate updates for the agent. If the prompt lacks sufficient information to make a meaningful change (e.g., it is a greeting, off-topic or if the user has asked for a value that is not supported), return null for all fields. Null values signify no change to that field. If only one field has changed, keep the other field null.

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


def build_updated_agent_config_schema() -> dict:
    """Build a schema for updated agent config"""
    return {"class": pickle.dumps(UpdatedAgentConfig).hex(), "is_list": False}
