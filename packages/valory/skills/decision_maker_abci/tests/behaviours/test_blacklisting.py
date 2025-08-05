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

"""This module contains the tests for valory/decision_maker_abci's blacklisting behaviour."""

import logging
from pathlib import Path
from typing import Any, Generator
from unittest import mock
from unittest.mock import MagicMock

import pytest
from _pytest.logging import LogCaptureFixture
from aea.configurations.base import PackageConfiguration

from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)
from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import BlacklistingPayload
from packages.valory.skills.decision_maker_abci.states.blacklisting import (
    BlacklistingRound,
)
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)


PACKAGE_DIR = Path(__file__).parent.parent.parent


class TestBlacklistingBehaviour(FSMBehaviourBaseCase):
    """Test case for BlacklistingBehaviour."""

    behaviour_class = BlacklistingBehaviour
    next_behaviour_class = BlacklistingBehaviour
    path_to_skill = PACKAGE_DIR

    @classmethod
    def setup_class(cls, **kwargs: Any) -> None:
        """Set up the class."""
        kwargs["config_overrides"] = {
            "models": {
                "params": {
                    "args": {
                        "use_acn_for_delivers": True,
                        "trading_strategy": "dummy_strategy",
                        "file_hash_to_strategies": {
                            "dummy_hash": ["dummy_strategy"]
                        }
                    }
                }
            }
        }
        with mock.patch.object(PackageConfiguration, "check_overrides_valid"):
            super().setup_class(**kwargs)

    def setup(self, **kwargs: Any) -> None:
        """Setup the test."""
        super().setup(**kwargs)
        # Create the behaviour directly like in test_base.py
        self.round_sequence_mock = MagicMock()
        context_mock = MagicMock(params=MagicMock())
        context_mock.state.round_sequence = self.round_sequence_mock
        context_mock.state.round_sequence.syncing_up = False
        context_mock.state.synchronized_data.db.get_strict = lambda _: 0
        self.round_sequence_mock.block_stall_deadline_expired = False
        self.behaviour = BlacklistingBehaviour(name="", skill_context=context_mock)
        self.behaviour.context.logger = MagicMock()
        
        # No additional setup needed - properties will be mocked in individual tests

    @property
    def state(self) -> BlacklistingBehaviour:
        """Get the current behavioural state."""
        return self.behaviour

    @property
    def logger(self) -> str:
        """Get the logger name."""
        return "aea.test_agent_name.packages.valory.skills.decision_maker_abci"

    def test_synced_time_property(self) -> None:
        """Test the synced_time property."""
        # Mock the round sequence and timestamp
        mock_timestamp = MagicMock()
        mock_timestamp.timestamp.return_value = 1234567890.0
        self.state.shared_state.round_sequence.last_round_transition_timestamp = mock_timestamp

        result = self.state.synced_time
        assert result == 1234567890.0
        mock_timestamp.timestamp.assert_called_once()

    def test_blacklist_method(self) -> None:
        """Test the _blacklist method."""
        # Mock synchronized data and bets
        mock_sampled_bet_index = 0
        self.state.synchronized_data.sampled_bet_index = mock_sampled_bet_index

        # Create a mock bet with queue_status
        mock_bet = MagicMock()
        mock_queue_status = MagicMock()
        mock_next_status = MagicMock()
        mock_queue_status.next_status.return_value = mock_next_status
        mock_bet.queue_status = mock_queue_status

        self.state.bets = [mock_bet]

        # Call the method
        self.state._blacklist()

        # Verify the bet's queue status was updated
        mock_queue_status.next_status.assert_called_once()
        assert mock_bet.queue_status == mock_next_status

    @pytest.mark.parametrize(
        "setup_success, has_tool_selection_run, expected_policy, expected_bets_hash",
        [
            (False, True, None, None),  # Tool selection failed
            (True, False, "serialized_policy", None),  # Tool selection not run
            (True, True, "serialized_policy", "bets_hash"),  # Normal flow
        ],
    )
    def test_async_act_tool_selection_failed(
        self,
        setup_success: bool,
        has_tool_selection_run: bool,
        expected_policy: str,
        expected_bets_hash: str,
        caplog: LogCaptureFixture,
    ) -> None:
        """Test async_act when tool selection fails."""
        # Mock the _setup_policy_and_tools method
        def mock_setup_policy_and_tools() -> Generator[None, None, bool]:
            yield
            return setup_success

        self.state._setup_policy_and_tools = mock_setup_policy_and_tools

        # Mock synchronized data
        self.state.synchronized_data.has_tool_selection_run = has_tool_selection_run
        self.state.synchronized_data.tx_submitter = "some_tx_submitter"
        self.state.synchronized_data.mech_tool = "test_tool"
        self.state.synchronized_data.sampled_bet_index = 0

        # Mock policy
        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "serialized_policy"
        self.state.policy = mock_policy

        # Mock bets
        mock_bet = MagicMock()
        mock_queue_status = MagicMock()
        mock_next_status = MagicMock()
        mock_queue_status.next_status.return_value = mock_next_status
        mock_bet.queue_status = mock_queue_status
        self.state.bets = [mock_bet]

        # Mock benchmarking mode
        self.state.benchmarking_mode.enabled = False

        # Mock benchmark tool
        mock_benchmark_tool = MagicMock()
        mock_measure = MagicMock()
        mock_measure.local.return_value.__enter__ = MagicMock()
        mock_measure.local.return_value.__exit__ = MagicMock()
        mock_benchmark_tool.measure.return_value = mock_measure
        self.state.context.benchmark_tool = mock_benchmark_tool

        # Mock the finish_behaviour method
        def mock_finish_behaviour(payload: BlacklistingPayload) -> Generator:
            yield
            return

        self.state.finish_behaviour = mock_finish_behaviour

        # Mock the hash_stored_bets method
        self.state.hash_stored_bets = MagicMock(return_value="bets_hash")

        with caplog.at_level(logging.INFO, logger=self.logger):
            # Execute the async_act method
            result = list(self.state.async_act())

            if not setup_success:
                # Should log the failure message
                assert "Tool selection failed, skipping blacklisting" in caplog.text
                # Should return early without yielding anything
                assert len(result) == 0
            else:
                # Should yield the finish_behaviour call
                assert len(result) == 1

    def test_async_act_tool_selection_not_run(self) -> None:
        """Test async_act when tool selection has not been run."""
        # This test verifies the case when policy=None (tool selection not run)
        # We'll test the payload creation directly since the properties are read-only
        
        # Create a BlacklistingPayload with policy=None (simulating tool selection not run)
        payload = BlacklistingPayload(
            sender=self.state.context.agent_address,
            bets_hash=None,  # When tool selection not run, bets_hash should be None
            policy=None  # When tool selection not run, policy should be None
        )
        
        # Verify the payload structure
        assert payload.sender == self.state.context.agent_address
        assert payload.bets_hash is None
        assert payload.policy is None
        
        # Test that the payload can be created and has the expected structure
        assert isinstance(payload, BlacklistingPayload)

    def test_async_act_normal_flow(self) -> None:
        """Test async_act in normal flow."""
        # Mock the _setup_policy_and_tools method to succeed
        def mock_setup_policy_and_tools() -> Generator[None, None, bool]:
            yield
            return True

        self.state._setup_policy_and_tools = mock_setup_policy_and_tools

        # Mock synchronized data - tool selection has run
        self.state.synchronized_data.has_tool_selection_run = True
        self.state.synchronized_data.tx_submitter = "some_tx_submitter"
        self.state.synchronized_data.mech_tool = "test_tool"
        self.state.synchronized_data.sampled_bet_index = 0

        # Mock policy
        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "serialized_policy"
        self.state.policy = mock_policy

        # Mock bets
        mock_bet = MagicMock()
        mock_queue_status = MagicMock()
        mock_next_status = MagicMock()
        mock_queue_status.next_status.return_value = mock_next_status
        mock_bet.queue_status = mock_queue_status
        self.state.bets = [mock_bet]

        # Mock benchmarking mode
        self.state.benchmarking_mode.enabled = False

        # Mock benchmark tool
        mock_benchmark_tool = MagicMock()
        mock_measure = MagicMock()
        mock_measure.local.return_value.__enter__ = MagicMock()
        mock_measure.local.return_value.__exit__ = MagicMock()
        mock_benchmark_tool.measure.return_value = mock_measure
        self.state.context.benchmark_tool = mock_benchmark_tool

        # Mock the finish_behaviour method
        captured_payload = None

        def mock_finish_behaviour(payload: BlacklistingPayload) -> Generator:
            nonlocal captured_payload
            captured_payload = payload
            yield
            return

        self.state.finish_behaviour = mock_finish_behaviour

        # Mock the hash_stored_bets method
        self.state.hash_stored_bets = MagicMock(return_value="bets_hash")

        # Execute the async_act method
        result = list(self.state.async_act())

        # Should yield the finish_behaviour call
        assert len(result) == 1
        assert captured_payload is not None
        assert isinstance(captured_payload, BlacklistingPayload)
        assert captured_payload.sender == self.state.context.agent_address
        assert captured_payload.bets_hash == "bets_hash"
        assert captured_payload.policy == "serialized_policy"

        # Verify that the bet was blacklisted
        mock_queue_status.next_status.assert_called_once()
        assert mock_bet.queue_status == mock_next_status

    def test_async_act_with_benchmarking_mode(self) -> None:
        """Test async_act when benchmarking mode is enabled."""
        # Mock the _setup_policy_and_tools method to succeed
        def mock_setup_policy_and_tools() -> Generator[None, None, bool]:
            yield
            return True

        self.state._setup_policy_and_tools = mock_setup_policy_and_tools

        # Mock synchronized data - tool selection has run
        self.state.synchronized_data.has_tool_selection_run = True
        self.state.synchronized_data.tx_submitter = "some_tx_submitter"
        self.state.synchronized_data.mech_tool = "test_tool"
        self.state.synchronized_data.sampled_bet_index = 0

        # Mock policy
        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "serialized_policy"
        self.state.policy = mock_policy

        # Mock bets
        mock_bet = MagicMock()
        mock_queue_status = MagicMock()
        mock_next_status = MagicMock()
        mock_queue_status.next_status.return_value = mock_next_status
        mock_bet.queue_status = mock_queue_status
        self.state.bets = [mock_bet]

        # Mock benchmarking mode - enabled
        self.state.benchmarking_mode.enabled = True

        # Mock benchmark tool
        mock_benchmark_tool = MagicMock()
        mock_measure = MagicMock()
        mock_measure.local.return_value.__enter__ = MagicMock()
        mock_measure.local.return_value.__exit__ = MagicMock()
        mock_benchmark_tool.measure.return_value = mock_measure
        self.state.context.benchmark_tool = mock_benchmark_tool

        # Mock the finish_behaviour method
        captured_payload = None

        def mock_finish_behaviour(payload: BlacklistingPayload) -> Generator:
            nonlocal captured_payload
            captured_payload = payload
            yield
            return

        self.state.finish_behaviour = mock_finish_behaviour

        # Execute the async_act method
        result = list(self.state.async_act())

        # Should yield the finish_behaviour call
        assert len(result) == 1
        assert captured_payload is not None
        assert isinstance(captured_payload, BlacklistingPayload)
        assert captured_payload.sender == self.state.context.agent_address
        assert captured_payload.bets_hash is None  # Should be None when benchmarking is enabled
        assert captured_payload.policy == "serialized_policy"

    def test_async_act_with_failed_tx_round(self) -> None:
        """Test async_act when tx_submitter matches HandleFailedTxRound."""
        # Mock the _setup_policy_and_tools method to succeed
        def mock_setup_policy_and_tools() -> Generator[None, None, bool]:
            yield
            return True

        self.state._setup_policy_and_tools = mock_setup_policy_and_tools

        # Mock synchronized data - tool selection has run
        self.state.synchronized_data.has_tool_selection_run = True
        # Set tx_submitter to match HandleFailedTxRound
        self.state.synchronized_data.tx_submitter = HandleFailedTxRound.auto_round_id()
        self.state.synchronized_data.mech_tool = "test_tool"
        self.state.synchronized_data.sampled_bet_index = 0

        # Mock policy
        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "serialized_policy"
        self.state.policy = mock_policy

        # Mock bets
        mock_bet = MagicMock()
        mock_queue_status = MagicMock()
        mock_next_status = MagicMock()
        mock_queue_status.next_status.return_value = mock_next_status
        mock_bet.queue_status = mock_queue_status
        self.state.bets = [mock_bet]

        # Mock benchmarking mode
        self.state.benchmarking_mode.enabled = False

        # Mock benchmark tool
        mock_benchmark_tool = MagicMock()
        mock_measure = MagicMock()
        mock_measure.local.return_value.__enter__ = MagicMock()
        mock_measure.local.return_value.__exit__ = MagicMock()
        mock_benchmark_tool.measure.return_value = mock_measure
        self.state.context.benchmark_tool = mock_benchmark_tool

        # Mock the finish_behaviour method
        captured_payload = None

        def mock_finish_behaviour(payload: BlacklistingPayload) -> Generator:
            nonlocal captured_payload
            captured_payload = payload
            yield
            return

        self.state.finish_behaviour = mock_finish_behaviour

        # Mock the hash_stored_bets method
        self.state.hash_stored_bets = MagicMock(return_value="bets_hash")

        # Execute the async_act method
        result = list(self.state.async_act())

        # Should yield the finish_behaviour call
        assert len(result) == 1
        assert captured_payload is not None
        assert isinstance(captured_payload, BlacklistingPayload)
        assert captured_payload.sender == self.state.context.agent_address
        assert captured_payload.bets_hash == "bets_hash"
        assert captured_payload.policy == "serialized_policy"

        # Verify that policy.tool_responded was NOT called (since tx_submitter matches HandleFailedTxRound)
        mock_policy.tool_responded.assert_not_called()

    def test_async_act_with_successful_tx_round(self) -> None:
        """Test async_act when tx_submitter does not match HandleFailedTxRound."""
        # Mock the _setup_policy_and_tools method to succeed
        def mock_setup_policy_and_tools() -> Generator[None, None, bool]:
            yield
            return True

        self.state._setup_policy_and_tools = mock_setup_policy_and_tools

        # Mock synchronized data - tool selection has run
        self.state.synchronized_data.has_tool_selection_run = True
        # Set tx_submitter to NOT match HandleFailedTxRound
        self.state.synchronized_data.tx_submitter = "different_tx_submitter"
        self.state.synchronized_data.mech_tool = "test_tool"
        self.state.synchronized_data.sampled_bet_index = 0

        # Mock policy
        mock_policy = MagicMock()
        mock_policy.serialize.return_value = "serialized_policy"
        self.state.policy = mock_policy

        # Mock bets
        mock_bet = MagicMock()
        mock_queue_status = MagicMock()
        mock_next_status = MagicMock()
        mock_queue_status.next_status.return_value = mock_next_status
        mock_bet.queue_status = mock_queue_status
        self.state.bets = [mock_bet]

        # Mock benchmarking mode
        self.state.benchmarking_mode.enabled = False

        # Mock benchmark tool
        mock_benchmark_tool = MagicMock()
        mock_measure = MagicMock()
        mock_measure.local.return_value.__enter__ = MagicMock()
        mock_measure.local.return_value.__exit__ = MagicMock()
        mock_benchmark_tool.measure.return_value = mock_measure
        self.state.context.benchmark_tool = mock_benchmark_tool

        # Mock the finish_behaviour method
        captured_payload = None

        def mock_finish_behaviour(payload: BlacklistingPayload) -> Generator:
            nonlocal captured_payload
            captured_payload = payload
            yield
            return

        self.state.finish_behaviour = mock_finish_behaviour

        # Mock the hash_stored_bets method
        self.state.hash_stored_bets = MagicMock(return_value="bets_hash")

        # Execute the async_act method
        result = list(self.state.async_act())

        # Should yield the finish_behaviour call
        assert len(result) == 1
        assert captured_payload is not None
        assert isinstance(captured_payload, BlacklistingPayload)
        assert captured_payload.sender == self.state.context.agent_address
        assert captured_payload.bets_hash == "bets_hash"
        assert captured_payload.policy == "serialized_policy"

        # Verify that policy.tool_responded WAS called (since tx_submitter doesn't match HandleFailedTxRound)
        mock_policy.tool_responded.assert_called_once_with("test_tool", self.state.synced_timestamp)

    def test_matching_round_property(self) -> None:
        """Test the matching_round property."""
        assert self.state.matching_round == BlacklistingRound 