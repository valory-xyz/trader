# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2026 Valory AG
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

"""Tests for the RPC manager module."""

import time
from unittest.mock import MagicMock, patch

import pytest
from web3 import Web3

from packages.valory.skills.trader_abci.rpc_manager import (
    CONNECTION_ERROR_BACKOFF,
    QUOTA_EXCEEDED_BACKOFF,
    RATE_LIMIT_BACKOFF,
    RPCManager,
    SERVER_ERROR_BACKOFF,
    classify_error,
    parse_rpc_urls,
)


# ---------------------------------------------------------------------------
# parse_rpc_urls
# ---------------------------------------------------------------------------


class TestParseRpcUrls:
    """Tests for parse_rpc_urls."""

    def test_single_url(self) -> None:
        """Single URL is returned as a one-element list."""
        assert parse_rpc_urls("http://localhost:8545") == ["http://localhost:8545"]

    def test_multiple_urls(self) -> None:
        """Comma-separated URLs are split into a list."""
        result = parse_rpc_urls("http://rpc1,http://rpc2,http://rpc3")
        assert result == ["http://rpc1", "http://rpc2", "http://rpc3"]

    def test_whitespace_stripped(self) -> None:
        """Whitespace around URLs is stripped."""
        result = parse_rpc_urls(" http://a , http://b ")
        assert result == ["http://a", "http://b"]

    def test_empty_segments_ignored(self) -> None:
        """Empty segments from consecutive commas are ignored."""
        result = parse_rpc_urls("http://a,,http://b,")
        assert result == ["http://a", "http://b"]


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Tests for classify_error."""

    @pytest.mark.parametrize(
        "msg,expected",
        [
            ("429 Too Many Requests", "rate_limit"),
            ("rate limit exceeded", "rate_limit"),
            ("connection refused", "connection"),
            ("read timeout", "connection"),
            ("exceeded the quota", "quota"),
            ("quota exceeded", "quota"),
            ("502 Bad Gateway", "server"),
            ("503 Service Unavailable", "server"),
            ("too many open files", "fd_exhaustion"),
            ("errno 24", "fd_exhaustion"),
            ("random error", "unknown"),
        ],
    )
    def test_classification(self, msg: str, expected: str) -> None:
        """Error message is classified into the expected category."""
        assert classify_error(Exception(msg)) == expected


# ---------------------------------------------------------------------------
# RPCManager
# ---------------------------------------------------------------------------


class TestRPCManager:
    """Tests for RPCManager."""

    def test_register_and_get_web3(self) -> None:
        """Registering a chain creates a cached Web3 instance."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1.example.com")
        w3 = mgr.get_web3("gnosis")
        assert w3 is not None
        # Same instance returned on second call (cached)
        assert mgr.get_web3("gnosis") is w3

    def test_get_web3_unknown_chain(self) -> None:
        """Unknown chain returns None."""
        mgr = RPCManager()
        assert mgr.get_web3("unknown") is None

    def test_register_idempotent(self) -> None:
        """Registering same chain twice is a no-op."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1")
        w3_first = mgr.get_web3("gnosis")
        mgr.register_chain("gnosis", "http://rpc2")
        assert mgr.get_web3("gnosis") is w3_first

    def test_single_rpc_no_rotation(self) -> None:
        """With a single RPC, execute_with_rotation calls directly."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1")

        result = mgr.execute_with_rotation("gnosis", lambda w3: 42, "test")
        assert result == 42

    def test_unregistered_chain_returns_none(self) -> None:
        """execute_with_rotation on unregistered chain returns None."""
        mgr = RPCManager()
        result = mgr.execute_with_rotation("unknown", lambda w3: 42, "test")
        assert result is None

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_rotation_on_rate_limit(self, mock_sleep: MagicMock) -> None:
        """Rate limit errors trigger rotation and retry."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        call_count = 0

        def _op(w3: Web3) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("429 rate limit")
            return "success"

        result = mgr.execute_with_rotation("gnosis", _op, "test_rotation")
        assert result == "success"
        assert call_count == 3

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_write_not_retried_on_rate_limit(self, mock_sleep: MagicMock) -> None:
        """Write operations don't retry on rate limit errors."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        call_count = 0

        def _op(w3: Web3) -> None:
            nonlocal call_count
            call_count += 1
            raise Exception("429 rate limit")

        with pytest.raises(Exception, match="rate limit"):
            mgr.execute_with_rotation("gnosis", _op, "write_test", is_write=True)
        assert call_count == 1

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_write_retries_on_connection_error(self, mock_sleep: MagicMock) -> None:
        """Write operations DO retry on connection errors."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        call_count = 0

        def _op(w3: Web3) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("connection refused")
            return "tx_hash_123"

        result = mgr.execute_with_rotation("gnosis", _op, "write_conn", is_write=True)
        assert result == "tx_hash_123"
        assert call_count == 3

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_unknown_error_not_retried(self, mock_sleep: MagicMock) -> None:
        """Unknown errors are raised immediately."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        call_count = 0

        def _op(w3: Web3) -> None:
            nonlocal call_count
            call_count += 1
            raise TypeError("unexpected")

        with pytest.raises(TypeError):
            mgr.execute_with_rotation("gnosis", _op, "test_unknown")
        assert call_count == 1

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_exhausts_retries(self, mock_sleep: MagicMock) -> None:
        """After max retries, exception is raised."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        def _op(w3: Web3) -> None:
            raise Exception("connection refused forever")

        with pytest.raises(Exception, match="connection refused"):
            mgr.execute_with_rotation("gnosis", _op, "test_exhaust")

    def test_rotation_changes_w3_instance(self) -> None:
        """After rotation, a different Web3 instance is used."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        w3_before = mgr.get_web3("gnosis")
        mgr._rotate("gnosis")
        w3_after = mgr.get_web3("gnosis")
        assert w3_before is not w3_after

    def test_fd_exhaustion_backs_off_all(self) -> None:
        """FD exhaustion marks all RPCs as unhealthy."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2,http://rpc3")

        should_retry = mgr._handle_error(
            "gnosis", Exception("too many open files"), "test"
        )
        assert should_retry is True

        state = mgr._chains["gnosis"]
        assert not mgr._is_healthy(state, 0)
        assert not mgr._is_healthy(state, 1)
        assert not mgr._is_healthy(state, 2)


# ---------------------------------------------------------------------------
# Backoff duration verification
# ---------------------------------------------------------------------------


class TestBackoffDurations:
    """Verify correct backoff is applied per error category."""

    @pytest.mark.parametrize(
        "error_msg,expected_backoff",
        [
            ("429 rate limit", RATE_LIMIT_BACKOFF),
            ("connection refused", CONNECTION_ERROR_BACKOFF),
            ("quota exceeded", QUOTA_EXCEEDED_BACKOFF),
            ("502 Bad Gateway", SERVER_ERROR_BACKOFF),
        ],
    )
    def test_correct_backoff_per_category(
        self, error_msg: str, expected_backoff: float
    ) -> None:
        """Each error category applies the correct backoff."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")
        mgr._handle_error("gnosis", Exception(error_msg), "test")
        state = mgr._chains["gnosis"]
        backoff_until = state.backoff_until.get(0, 0.0)
        remaining = backoff_until - time.monotonic()
        assert remaining > 0
        assert remaining <= expected_backoff + 1.0


# ---------------------------------------------------------------------------
# RPCManager — multi-chain scenarios
# ---------------------------------------------------------------------------


class TestRPCManagerMultiChain:
    """Test RPCManager with multiple chains registered."""

    def test_independent_chains(self) -> None:
        """Chains have independent state and Web3 instances."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://gnosis1,http://gnosis2")
        mgr.register_chain("polygon", "http://polygon1,http://polygon2")

        w3_gnosis = mgr.get_web3("gnosis")
        w3_polygon = mgr.get_web3("polygon")
        assert w3_gnosis is not w3_polygon

    def test_rotation_affects_only_one_chain(self) -> None:
        """Rotating one chain doesn't affect the other."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://gnosis1,http://gnosis2")
        mgr.register_chain("polygon", "http://polygon1,http://polygon2")

        w3_polygon_before = mgr.get_web3("polygon")
        mgr._rotate("gnosis")
        w3_polygon_after = mgr.get_web3("polygon")
        assert w3_polygon_before is w3_polygon_after

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_execute_passes_web3_to_operation(self, mock_sleep: MagicMock) -> None:
        """execute_with_rotation passes the cached Web3 instance to the operation."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1")

        received_w3 = []

        def _op(w3: Web3) -> str:
            received_w3.append(w3)
            return "ok"

        mgr.execute_with_rotation("gnosis", _op, "test")
        assert len(received_w3) == 1
        assert received_w3[0] is mgr.get_web3("gnosis")

    @patch("packages.valory.skills.trader_abci.rpc_manager.time.sleep")
    def test_rotation_gives_different_w3_to_retry(self, mock_sleep: MagicMock) -> None:
        """After rotation, retries receive the new Web3 instance."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1,http://rpc2")

        received_w3s = []
        call_count = 0

        def _op(w3: Web3) -> str:
            nonlocal call_count
            received_w3s.append(id(w3))
            call_count += 1
            if call_count < 3:
                raise Exception("429 rate limit")
            return "ok"

        mgr.execute_with_rotation("gnosis", _op, "test")
        # After rotation, a different Web3 instance should be used
        assert len(received_w3s) == 3
        # First and second might differ (after rotation)
        assert received_w3s[0] != received_w3s[1] or received_w3s[1] != received_w3s[2]

    def test_single_rpc_propagates_exception(self) -> None:
        """Single RPC: exceptions propagate directly without wrapping."""
        mgr = RPCManager()
        mgr.register_chain("gnosis", "http://rpc1")

        def _op(w3: Web3) -> None:
            raise ValueError("contract revert")

        with pytest.raises(ValueError, match="contract revert"):
            mgr.execute_with_rotation("gnosis", _op, "test")
