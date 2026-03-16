# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

"""Tests for BlacklistingBehaviour."""

from unittest.mock import MagicMock, PropertyMock, patch

from packages.valory.skills.decision_maker_abci.behaviours.blacklisting import (
    BlacklistingBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import BlacklistingPayload
from packages.valory.skills.decision_maker_abci.states.handle_failed_tx import (
    HandleFailedTxRound,
)
from packages.valory.skills.market_manager_abci.bets import QueueStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen():  # type: ignore[no-untyped-def]
    """A no-op generator that yields once."""
    yield  # type: ignore[no-untyped-def]


def _return_gen(value):  # type: ignore[no-untyped-def]
    """A generator that yields once and returns a value."""
    yield  # type: ignore[no-untyped-def]
    return value


def _make_behaviour():  # type: ignore[no-untyped-def]
    """Return a BlacklistingBehaviour with mocked dependencies."""
    behaviour = object.__new__(BlacklistingBehaviour)  # type: ignore[no-untyped-def]

    # context
    context = MagicMock()
    context.agent_address = "test_agent"
    context.logger = MagicMock()
    context.benchmark_tool.measure.return_value.__enter__ = MagicMock()
    context.benchmark_tool.measure.return_value.__exit__ = MagicMock()
    behaviour.__dict__["_context"] = context

    # shared_state
    shared_state = MagicMock()
    shared_state.mech_timed_out = False
    behaviour.__dict__["_shared_state"] = shared_state

    # benchmarking_mode
    benchmarking_mode = MagicMock()
    benchmarking_mode.enabled = False
    behaviour.__dict__["_benchmarking_mode"] = benchmarking_mode

    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBlacklistingSyncedTime:
    """Tests for the synced_time property."""

    def test_synced_time_returns_timestamp(self) -> None:
        """synced_time should return the float timestamp from round_sequence."""
        behaviour = _make_behaviour()
        ts_mock = MagicMock()
        ts_mock.timestamp.return_value = 1234567890.5
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            mock_ss.return_value = MagicMock(
                round_sequence=MagicMock(last_round_transition_timestamp=ts_mock)
            )
            assert behaviour.synced_time == 1234567890.5


class TestBlacklistBlacklist:
    """Tests for the _blacklist method."""

    def test_blacklist_bumps_queue_status(self) -> None:
        """_blacklist should advance the sampled bet's queue_status."""
        behaviour = _make_behaviour()

        mock_bet = MagicMock()
        mock_bet.queue_status = QueueStatus.TO_PROCESS
        expected_next = QueueStatus.TO_PROCESS.next_status()

        behaviour.bets = [mock_bet]

        with patch.object(
            type(behaviour), "synchronized_data", new_callable=PropertyMock
        ) as mock_sd:
            mock_sd.return_value = MagicMock(sampled_bet_index=0)
            behaviour._blacklist()

        assert mock_bet.queue_status == expected_next


class TestBlacklistingAsyncAct:
    """Tests for the async_act generator."""

    def test_mech_timed_out_penalizes_mech(self) -> None:
        """When mech_timed_out is True, penalize_last_called_mech should be called."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.mech_timed_out = True
            mock_ss.return_value = ss

            # Make _setup_policy_and_tools return False to exit early
            behaviour._setup_policy_and_tools = lambda: _return_gen(False)  # type: ignore[method-assign]
            behaviour.finish_behaviour = lambda payload: _noop_gen()  # type: ignore[method-assign]

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

            ss.penalize_last_called_mech.assert_called_once()

    def test_setup_failure_logs_info_and_returns(self) -> None:
        """When _setup_policy_and_tools fails, the behaviour should log and return."""
        behaviour = _make_behaviour()
        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.mech_timed_out = False
            mock_ss.return_value = ss

            behaviour._setup_policy_and_tools = lambda: _return_gen(False)  # type: ignore[method-assign]

            gen = behaviour.async_act()
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

            behaviour.__dict__["_context"].logger.info.assert_called()

    def test_no_tool_selection_run_sends_payload_early(self) -> None:
        """When has_tool_selection_run is False, payload should be sent without blacklisting."""
        behaviour = _make_behaviour()

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = '{"test": true}'
        behaviour.__dict__["_policy"] = mock_policy

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        # After the first finish_behaviour returns, the code falls through
        # to read_bets/store_bets/hash_stored_bets, so mock those too.
        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.hash_stored_bets = MagicMock(return_value="hash123")  # type: ignore[method-assign]
        behaviour.bets = [MagicMock()]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.mech_timed_out = False
            mock_ss.return_value = ss

            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                sd = MagicMock()
                sd.has_tool_selection_run = False
                sd.sampled_bet_index = 0
                sd.tx_submitter = "other_submitter"
                sd.mech_tool = "tool1"
                mock_sd.return_value = sd

                behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
                with patch.object(
                    type(behaviour), "policy", new_callable=PropertyMock
                ) as mock_pol:
                    mock_pol.return_value = mock_policy
                    with patch.object(
                        type(behaviour), "synced_timestamp", new_callable=PropertyMock
                    ) as mock_ts:
                        mock_ts.return_value = 12345.0
                        with patch.object(
                            type(behaviour),
                            "benchmarking_mode",
                            new_callable=PropertyMock,
                        ) as mock_bm_prop:
                            mock_bm_prop.return_value = MagicMock(enabled=False)

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        # First payload (when has_tool_selection_run is False) should have bets_hash=None
        assert len(payloads_sent) >= 1
        assert isinstance(payloads_sent[0], BlacklistingPayload)
        assert payloads_sent[0].bets_hash is None

    def test_full_blacklisting_flow_with_tool_responded(self) -> None:
        """Full async_act when has_tool_selection_run is True and tx_submitter differs from HandleFailedTxRound."""
        behaviour = _make_behaviour()

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = '{"test": true}'
        behaviour.__dict__["_policy"] = mock_policy

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.queue_status = QueueStatus.TO_PROCESS

        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.hash_stored_bets = MagicMock(return_value="hash456")  # type: ignore[method-assign]
        behaviour.bets = [mock_bet]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.mech_timed_out = False
            mock_ss.return_value = ss

            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                sd = MagicMock()
                sd.has_tool_selection_run = True
                sd.sampled_bet_index = 0
                sd.tx_submitter = "other_submitter"
                sd.mech_tool = "tool1"
                mock_sd.return_value = sd

                behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
                with patch.object(
                    type(behaviour), "policy", new_callable=PropertyMock
                ) as mock_pol:
                    mock_pol.return_value = mock_policy
                    with patch.object(
                        type(behaviour), "synced_timestamp", new_callable=PropertyMock
                    ) as mock_ts:
                        mock_ts.return_value = 12345.0
                        with patch.object(
                            type(behaviour),
                            "benchmarking_mode",
                            new_callable=PropertyMock,
                        ) as mock_bm_prop:
                            mock_bm_prop.return_value = MagicMock(enabled=False)

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        # tool_responded should have been called since tx_submitter != HandleFailedTxRound
        mock_policy.tool_responded.assert_called_once_with("tool1", 12345.0)
        # Should have payload with bets_hash
        assert len(payloads_sent) >= 1
        last_payload = payloads_sent[-1]
        assert isinstance(last_payload, BlacklistingPayload)
        assert last_payload.bets_hash == "hash456"

    def test_full_blacklisting_flow_with_handle_failed_tx(self) -> None:
        """Full async_act when tx_submitter matches HandleFailedTxRound - tool_responded should NOT be called."""
        behaviour = _make_behaviour()

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = '{"test": true}'
        behaviour.__dict__["_policy"] = mock_policy

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.queue_status = QueueStatus.TO_PROCESS

        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.hash_stored_bets = MagicMock(return_value="hash789")  # type: ignore[method-assign]
        behaviour.bets = [mock_bet]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.mech_timed_out = False
            mock_ss.return_value = ss

            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                sd = MagicMock()
                sd.has_tool_selection_run = True
                sd.sampled_bet_index = 0
                sd.tx_submitter = HandleFailedTxRound.auto_round_id()
                sd.mech_tool = "tool1"
                mock_sd.return_value = sd

                behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
                with patch.object(
                    type(behaviour), "policy", new_callable=PropertyMock
                ) as mock_pol:
                    mock_pol.return_value = mock_policy
                    with patch.object(
                        type(behaviour), "synced_timestamp", new_callable=PropertyMock
                    ) as mock_ts:
                        mock_ts.return_value = 12345.0
                        with patch.object(
                            type(behaviour),
                            "benchmarking_mode",
                            new_callable=PropertyMock,
                        ) as mock_bm_prop:
                            mock_bm_prop.return_value = MagicMock(enabled=False)

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        # tool_responded should NOT have been called since tx_submitter matches HandleFailedTxRound
        mock_policy.tool_responded.assert_not_called()

    def test_benchmarking_mode_skips_hash(self) -> None:
        """In benchmarking mode, bets_hash should be None."""
        behaviour = _make_behaviour()

        mock_policy = MagicMock()
        mock_policy.serialize.return_value = '{"test": true}'
        behaviour.__dict__["_policy"] = mock_policy

        payloads_sent = []

        behaviour.send_a2a_transaction = lambda payload: (  # type: ignore[method-assign]
            payloads_sent.append(payload) or (yield)  # type: ignore[func-returns-value]
        )
        behaviour.wait_until_round_end = lambda: _noop_gen()  # type: ignore[func-returns-value, method-assign]
        behaviour.set_done = MagicMock()  # type: ignore[method-assign]

        mock_bet = MagicMock()
        mock_bet.queue_status = QueueStatus.TO_PROCESS

        behaviour.read_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.store_bets = MagicMock()  # type: ignore[method-assign]
        behaviour.hash_stored_bets = MagicMock(return_value="hash123")  # type: ignore[method-assign]
        behaviour.bets = [mock_bet]

        with patch.object(
            type(behaviour), "shared_state", new_callable=PropertyMock
        ) as mock_ss:
            ss = MagicMock()
            ss.mech_timed_out = False
            mock_ss.return_value = ss

            with patch.object(
                type(behaviour), "synchronized_data", new_callable=PropertyMock
            ) as mock_sd:
                sd = MagicMock()
                sd.has_tool_selection_run = True
                sd.sampled_bet_index = 0
                sd.tx_submitter = "other_submitter"
                sd.mech_tool = "tool1"
                mock_sd.return_value = sd

                behaviour._setup_policy_and_tools = lambda: _return_gen(True)  # type: ignore[method-assign]
                with patch.object(
                    type(behaviour), "policy", new_callable=PropertyMock
                ) as mock_pol:
                    mock_pol.return_value = mock_policy
                    with patch.object(
                        type(behaviour), "synced_timestamp", new_callable=PropertyMock
                    ) as mock_ts:
                        mock_ts.return_value = 12345.0
                        with patch.object(
                            type(behaviour),
                            "benchmarking_mode",
                            new_callable=PropertyMock,
                        ) as mock_bm_prop:
                            mock_bm_prop.return_value = MagicMock(enabled=True)

                            gen = behaviour.async_act()
                            try:
                                while True:
                                    next(gen)
                            except StopIteration:
                                pass

        # In benchmarking mode, bets_hash should be None
        assert len(payloads_sent) >= 1
        last_payload = payloads_sent[-1]
        assert last_payload.bets_hash is None
