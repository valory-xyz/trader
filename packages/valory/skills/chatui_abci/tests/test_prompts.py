# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""Tests for the prompts module of the chatui_abci skill."""

import pickle  # nosec

from packages.valory.skills.chatui_abci.prompts import (
    CHATUI_PROMPT,
    ChatUILLMResponse,
    FieldsThatCanBeRemoved,
    TradingStrategy,
    UpdatedAgentConfig,
    build_chatui_llm_response_schema,
)


class TestUpdatedAgentConfig:
    """Tests for the UpdatedAgentConfig pydantic model."""

    def test_all_none(self) -> None:
        """Test instantiation with all optional fields set to None."""
        config = UpdatedAgentConfig(
            trading_strategy=None,
            allowed_tools=None,
            fixed_bet_size=None,
            max_bet_size=None,
            removed_config_fields=[],
            behavior=None,
        )
        assert config.trading_strategy is None
        assert config.allowed_tools is None
        assert config.fixed_bet_size is None
        assert config.max_bet_size is None
        assert config.removed_config_fields == []
        assert config.behavior is None

    def test_with_values(self) -> None:
        """Test instantiation with all fields populated."""
        config = UpdatedAgentConfig(
            trading_strategy=TradingStrategy.KELLY_CRITERION,
            allowed_tools=["tool-a", "tool-b"],
            fixed_bet_size=1.0,
            max_bet_size=2.0,
            removed_config_fields=[FieldsThatCanBeRemoved.ALLOWED_TOOLS],
            behavior="test behavior",
        )
        assert config.trading_strategy == TradingStrategy.KELLY_CRITERION
        assert config.allowed_tools == ["tool-a", "tool-b"]
        assert config.fixed_bet_size == 1.0
        assert config.max_bet_size == 2.0
        assert config.removed_config_fields == [FieldsThatCanBeRemoved.ALLOWED_TOOLS]
        assert config.behavior == "test behavior"

    def test_with_bet_amount_per_threshold(self) -> None:
        """Test instantiation with the other trading strategy."""
        config = UpdatedAgentConfig(
            trading_strategy=TradingStrategy.FIXED_BET,
            allowed_tools=None,
            fixed_bet_size=5.0,
            max_bet_size=None,
            removed_config_fields=[
                FieldsThatCanBeRemoved.FIXED_BET_SIZE,
                FieldsThatCanBeRemoved.MAX_BET_SIZE,
            ],
            behavior=None,
        )
        assert config.trading_strategy == TradingStrategy.FIXED_BET
        assert config.fixed_bet_size == 5.0


class TestChatUILLMResponse:
    """Tests for the ChatUILLMResponse pydantic model."""

    def test_with_config(self) -> None:
        """Test instantiation with an UpdatedAgentConfig."""
        config = UpdatedAgentConfig(
            trading_strategy=None,
            allowed_tools=None,
            fixed_bet_size=None,
            max_bet_size=None,
            removed_config_fields=[],
            behavior=None,
        )
        resp = ChatUILLMResponse(updated_agent_config=config, message="test")
        assert resp.message == "test"
        assert resp.updated_agent_config is not None

    def test_without_config(self) -> None:
        """Test instantiation with no config (None)."""
        resp = ChatUILLMResponse(updated_agent_config=None, message="hello")
        assert resp.updated_agent_config is None
        assert resp.message == "hello"


class TestBuildChatuiLlmResponseSchema:
    """Tests for the build_chatui_llm_response_schema function."""

    def test_returns_dict_with_class_and_is_list(self) -> None:
        """Test that the schema dict has the expected keys."""
        schema = build_chatui_llm_response_schema()
        assert isinstance(schema, dict)
        assert "class" in schema
        assert "is_list" in schema
        assert schema["is_list"] is False

    def test_class_is_pickled_hex(self) -> None:
        """Test that the class value deserializes back to ChatUILLMResponse."""
        schema = build_chatui_llm_response_schema()
        restored = pickle.loads(bytes.fromhex(schema["class"]))  # nosec
        assert restored is ChatUILLMResponse


class TestChatuiPrompt:
    """Tests for the CHATUI_PROMPT template string."""

    def test_prompt_is_string(self) -> None:
        """Test that CHATUI_PROMPT is a string."""
        assert isinstance(CHATUI_PROMPT, str)

    def test_prompt_contains_placeholders(self) -> None:
        """Test that the prompt contains the expected format placeholders."""
        assert "{user_prompt}" in CHATUI_PROMPT
        assert "{current_trading_strategy}" in CHATUI_PROMPT
        assert "{current_allowed_tools}" in CHATUI_PROMPT
        assert "{available_tools}" in CHATUI_PROMPT
        assert "{current_fixed_bet_size}" in CHATUI_PROMPT
        assert "{current_max_bet_size}" in CHATUI_PROMPT
        assert "{units}" in CHATUI_PROMPT
        assert "{absolute_min_bet_size}" in CHATUI_PROMPT
        assert "{absolute_max_bet_size}" in CHATUI_PROMPT
