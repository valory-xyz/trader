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

"""Tests for the market_manager_abci behaviours package."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from packages.valory.skills.market_manager_abci.behaviours.base import (
    BETS_FILENAME,
    BetsManagerBehaviour,
    MULTI_BETS_FILENAME,
)
from packages.valory.skills.market_manager_abci.behaviours.fetch_markets_router import (
    FetchMarketsRouterBehaviour,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _noop_gen(*args: Any, **kwargs: Any) -> Any:
    """No-op generator that yields once and returns None."""
    yield
    return None


def _return_gen(value: Any) -> Any:  # type: ignore[no-untyped-def]
    """Create a generator factory that yields once and returns *value*."""

    def _gen(*args: Any, **kwargs: Any) -> Any:
        yield
        return value

    # type: ignore[no-untyped-def]
    return _gen


# type: ignore[no-untyped-def]
def _exhaust(gen: Any) -> Any:
    """Drive a generator to completion and return its final value."""
    result = None
    try:
        while True:
            next(gen)
    except StopIteration as exc:  # type: ignore[no-untyped-def]
        result = exc.value
    return result


class _ConcreteBetsManager(BetsManagerBehaviour):
    """Concrete subclass of BetsManagerBehaviour for testing."""

    matching_round = MagicMock()

    def async_act(self) -> None:  # type: ignore[misc, override]
        """No-op."""
        yield  # type: ignore[misc]


def _make_behaviour(tmp_path: Any = None, **overrides: Any) -> _ConcreteBetsManager:
    """Instantiate a _ConcreteBetsManager without framework wiring.  # type: ignore[no-untyped-def]

      Uses object.__new__ to skip __init__ (which requires the full
      Open Autonomy runtime), then manually sets the attributes that the
      methods under test rely on.
    # type: ignore[no-untyped-def]
      :param tmp_path: optional temporary path for file storage.
      :param **overrides: keyword arguments to override default attributes.
      :return: an instance of _ConcreteBetsManager.
    """
    b = object.__new__(_ConcreteBetsManager)  # type: ignore[type-abstract]

    # -- context / params --
    ctx = MagicMock()
    store_path = Path(tmp_path) if tmp_path else Path("/tmp/test_store")  # nosec B108
    ctx.params.store_path = store_path
    b._context = ctx

    # -- internal state --
    b.bets = []
    b.multi_bets_filepath = str(store_path / MULTI_BETS_FILENAME)
    b.bets_filepath = str(store_path / BETS_FILENAME)

    # Apply any caller-supplied overrides
    for k, v in overrides.items():
        setattr(b, k, v)
    return b


# ===========================================================================
# Tests for BetsManagerBehaviour.__init__
# ===========================================================================


class TestBetsManagerInit:
    """Tests for BetsManagerBehaviour.__init__."""

    def test_init_sets_attributes(self) -> None:
        """Test that __init__ sets bets, multi_bets_filepath, and bets_filepath."""
        mock_context = MagicMock()
        mock_context.params.store_path = Path("/tmp/test_store")  # nosec B108

        with patch(
            "packages.valory.skills.abstract_round_abci.behaviour_utils.BaseBehaviour.__init__"
        ):
            instance = _ConcreteBetsManager.__new__(_ConcreteBetsManager)  # type: ignore[type-abstract]
            instance._context = mock_context
            _ConcreteBetsManager.__init__(instance)  # type: ignore[type-abstract]

        assert instance.bets == []
        assert (
            instance.multi_bets_filepath
            == Path("/tmp/test_store") / MULTI_BETS_FILENAME  # nosec B108
        )
        assert (
            instance.bets_filepath
            == Path("/tmp/test_store") / BETS_FILENAME  # nosec B108
        )


# ===========================================================================
# Tests for BetsManagerBehaviour properties
# ===========================================================================


class TestBetsManagerProperties:
    """Tests for the properties exposed by BetsManagerBehaviour."""

    def test_shared_state_returns_context_state(self) -> None:
        """Test that shared_state delegates to context.state."""
        b = _make_behaviour()
        result = b.shared_state
        assert result is b.context.state

    def test_benchmarking_mode_returns_context_benchmarking_mode(self) -> None:
        """Test that benchmarking_mode delegates to context.benchmarking_mode."""
        b = _make_behaviour()
        result = b.benchmarking_mode
        assert result is b.context.benchmarking_mode


# ===========================================================================
# Tests for _do_connection_request / do_connection_request
# ===========================================================================


class TestDoConnectionRequest:
    """Tests for _do_connection_request and do_connection_request."""

    def test_do_connection_request_puts_message_and_waits(self) -> None:
        """Test that _do_connection_request puts message in outbox and waits."""
        b = _make_behaviour()

        mock_message = MagicMock()
        mock_dialogue = MagicMock()
        mock_response = MagicMock()

        # Mock _get_request_nonce_from_dialogue
        b._get_request_nonce_from_dialogue = MagicMock(return_value="nonce_123")  # type: ignore[method-assign]
        b.get_callback_request = MagicMock(return_value="callback")  # type: ignore[method-assign]
        b.wait_for_message = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._do_connection_request(mock_message, mock_dialogue, timeout=30.0)
        result = _exhaust(gen)

        b.context.outbox.put_message.assert_called_once_with(message=mock_message)
        b._get_request_nonce_from_dialogue.assert_called_once_with(mock_dialogue)
        assert result is mock_response

    def test_do_connection_request_public_wrapper(self) -> None:
        """Test that do_connection_request delegates to _do_connection_request."""
        b = _make_behaviour()

        mock_message = MagicMock()
        mock_dialogue = MagicMock()
        mock_response = MagicMock()

        b._get_request_nonce_from_dialogue = MagicMock(return_value="nonce_123")  # type: ignore[method-assign]
        b.get_callback_request = MagicMock(return_value="callback")  # type: ignore[method-assign]
        b.wait_for_message = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b.do_connection_request(mock_message, mock_dialogue, timeout=10.0)
        result = _exhaust(gen)

        assert result is mock_response

    def test_do_connection_request_no_timeout(self) -> None:
        """Test that _do_connection_request works without explicit timeout."""
        b = _make_behaviour()

        mock_message = MagicMock()
        mock_dialogue = MagicMock()
        mock_response = MagicMock()

        b._get_request_nonce_from_dialogue = MagicMock(return_value="nonce")  # type: ignore[method-assign]
        b.get_callback_request = MagicMock(return_value="cb")  # type: ignore[method-assign]
        b.wait_for_message = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._do_connection_request(mock_message, mock_dialogue)
        result = _exhaust(gen)

        assert result is mock_response


# ===========================================================================
# Tests for send_polymarket_connection_request
# ===========================================================================


class TestSendPolymarketConnectionRequest:
    """Tests for send_polymarket_connection_request."""

    def test_sends_request_and_parses_response(self) -> None:
        """Test that it creates an SRR message, sends it, and parses the JSON response."""
        b = _make_behaviour()

        payload_data = {"method": "get_markets", "params": {}}

        # Mock srr_dialogues.create
        mock_srr_msg = MagicMock()
        mock_srr_dialogue = MagicMock()
        b.context.srr_dialogues.create.return_value = (mock_srr_msg, mock_srr_dialogue)

        # Mock do_connection_request to return a response with a JSON payload
        response_payload = {"status": "ok", "data": [1, 2, 3]}
        mock_response = MagicMock()
        mock_response.payload = json.dumps(response_payload)

        b._get_request_nonce_from_dialogue = MagicMock(return_value="nonce")  # type: ignore[method-assign]
        b.get_callback_request = MagicMock(return_value="cb")  # type: ignore[method-assign]
        b.wait_for_message = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b.send_polymarket_connection_request(payload_data)
        result = _exhaust(gen)

        assert result == response_payload
        b.context.logger.info.assert_called_once()


# ===========================================================================
# Tests for store_bets
# ===========================================================================


class TestStoreBets:
    """Tests for store_bets."""

    def test_store_bets_no_bets(self) -> None:
        """Test that store_bets logs warning and returns when bets are empty."""
        b = _make_behaviour()
        b.bets = []

        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=None,
        ):
            b.store_bets()

        b.context.logger.warning.assert_called_once_with("No bets to store.")

    def test_store_bets_success(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test that store_bets writes serialized bets to file."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]
        b.bets = [MagicMock()]

        serialized = '{"bets": "data"}'
        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=serialized,
        ):
            b.store_bets()

        with open(b.multi_bets_filepath, "r") as f:
            content = f.read()
        assert content == serialized

    def test_store_bets_ioerror_writing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test that store_bets handles IOError during write."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]
        b.bets = [MagicMock()]

        serialized = '{"bets": "data"}'
        mock_file = MagicMock()
        mock_file.write.side_effect = IOError("disk full")
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=serialized,
        ), patch("builtins.open", return_value=mock_file):
            b.store_bets()

        b.context.logger.error.assert_called_once()
        assert "Error writing" in b.context.logger.error.call_args[0][0]

    def test_store_bets_error_opening_file(self) -> None:
        """Test that store_bets handles error when opening file."""
        b = _make_behaviour()
        b.multi_bets_filepath = "/nonexistent/path/bets.json"
        b.bets = [MagicMock()]

        serialized = '{"bets": "data"}'
        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=serialized,
        ), patch("builtins.open", side_effect=FileNotFoundError("no such dir")):
            b.store_bets()

        b.context.logger.error.assert_called_once()
        assert "Error opening" in b.context.logger.error.call_args[0][0]

    def test_store_bets_permission_error_opening(self) -> None:
        """Test that store_bets handles PermissionError when opening file."""
        b = _make_behaviour()
        b.bets = [MagicMock()]

        serialized = '{"bets": "data"}'
        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=serialized,
        ), patch("builtins.open", side_effect=PermissionError("forbidden")):
            b.store_bets()

        b.context.logger.error.assert_called_once()
        assert "Error opening" in b.context.logger.error.call_args[0][0]

    def test_store_bets_os_error_opening(self) -> None:
        """Test that store_bets handles OSError when opening file."""
        b = _make_behaviour()
        b.bets = [MagicMock()]

        serialized = '{"bets": "data"}'
        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=serialized,
        ), patch("builtins.open", side_effect=OSError("generic os error")):
            b.store_bets()

        b.context.logger.error.assert_called_once()
        assert "Error opening" in b.context.logger.error.call_args[0][0]

    def test_store_bets_os_error_writing(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test that store_bets handles OSError during write."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]
        b.bets = [MagicMock()]

        serialized = '{"bets": "data"}'
        mock_file = MagicMock()
        mock_file.write.side_effect = OSError("write os error")
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.serialize_bets",
            return_value=serialized,
        ), patch("builtins.open", return_value=mock_file):
            b.store_bets()

        b.context.logger.error.assert_called_once()
        assert "Error writing" in b.context.logger.error.call_args[0][0]


# ===========================================================================
# Tests for read_bets
# ===========================================================================


class TestReadBets:
    """Tests for read_bets."""

    def test_read_bets_no_files_exist(self) -> None:
        """Test that read_bets returns empty list when no files exist."""
        b = _make_behaviour()

        with patch("os.path.isfile", return_value=False):
            b.read_bets()

        assert b.bets == []
        assert b.context.logger.warning.call_count == 2

    def test_read_bets_multi_bets_exists(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test reading from multi_bets file when it exists."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]

        # Write a valid bets file
        bets_data = [{"id": "bet1", "market": "test"}]
        multi_path = tmp_path / MULTI_BETS_FILENAME
        multi_path.write_text(json.dumps(bets_data))

        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.BetsDecoder",
        ):
            # json.load with BetsDecoder will be called; mock it at the json.load level
            with patch(
                "json.load",
                return_value=bets_data,
            ):
                b.read_bets()

        assert b.bets == bets_data

    def test_read_bets_only_bets_file_exists(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test fallback to bets.json when multi_bets.json does not exist."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]

        bets_data = [{"id": "bet_fallback"}]
        bets_path = tmp_path / BETS_FILENAME
        bets_path.write_text(json.dumps(bets_data))

        # multi_bets does NOT exist, but bets does
        def isfile_side_effect(path: Any) -> bool:
            path_str = str(path)
            if MULTI_BETS_FILENAME in path_str:  # type: ignore[no-untyped-def]
                return False
            if BETS_FILENAME in path_str:
                return True
            return False

        with patch("os.path.isfile", side_effect=isfile_side_effect):
            with patch("json.load", return_value=bets_data):
                b.read_bets()

        assert b.bets == bets_data
        # First warning for missing multi_bets
        assert b.context.logger.warning.call_count == 1

    def test_read_bets_decode_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test that read_bets handles JSONDecodeError."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]

        multi_path = tmp_path / MULTI_BETS_FILENAME
        multi_path.write_text("not valid json {{{")

        with patch(
            "json.load",
            side_effect=json.JSONDecodeError("err", "doc", 0),
        ):
            b.read_bets()

        assert b.bets == []
        b.context.logger.error.assert_called_once()
        assert "Error decoding" in b.context.logger.error.call_args[0][0]

    def test_read_bets_type_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Test that read_bets handles TypeError from decoder."""
        b = _make_behaviour(tmp_path=tmp_path)  # type: ignore[no-untyped-def]

        multi_path = tmp_path / MULTI_BETS_FILENAME
        multi_path.write_text("[]")

        with patch(
            "json.load",
            side_effect=TypeError("bad type"),
        ):
            b.read_bets()

        assert b.bets == []
        b.context.logger.error.assert_called_once()
        assert "Error decoding" in b.context.logger.error.call_args[0][0]

    def test_read_bets_open_error(self) -> None:
        """Test that read_bets handles error opening file."""
        b = _make_behaviour()

        with patch("os.path.isfile", return_value=True), patch(
            "builtins.open", side_effect=FileNotFoundError("gone")
        ):
            b.read_bets()

        assert b.bets == []
        b.context.logger.error.assert_called_once()
        assert "Error opening" in b.context.logger.error.call_args[0][0]

    def test_read_bets_permission_error_opening(self) -> None:
        """Test that read_bets handles PermissionError when opening file."""
        b = _make_behaviour()

        with patch("os.path.isfile", return_value=True), patch(
            "builtins.open", side_effect=PermissionError("no access")
        ):
            b.read_bets()

        assert b.bets == []
        b.context.logger.error.assert_called_once()
        assert "Error opening" in b.context.logger.error.call_args[0][0]

    def test_read_bets_os_error_opening(self) -> None:
        """Test that read_bets handles OSError when opening file."""
        b = _make_behaviour()

        with patch("os.path.isfile", return_value=True), patch(
            "builtins.open", side_effect=OSError("os error")
        ):
            b.read_bets()

        assert b.bets == []
        b.context.logger.error.assert_called_once()
        assert "Error opening" in b.context.logger.error.call_args[0][0]


# ===========================================================================
# Tests for hash_stored_bets
# ===========================================================================


class TestHashStoredBets:
    """Tests for hash_stored_bets."""

    def test_hash_stored_bets_delegates_to_ipfs(self) -> None:
        """Test that hash_stored_bets calls IPFSHashOnly.hash_file."""
        b = _make_behaviour()

        with patch(
            "packages.valory.skills.market_manager_abci.behaviours.base.IPFSHashOnly.hash_file",
            return_value="QmHash123",
        ) as mock_hash:
            result = b.hash_stored_bets()

        mock_hash.assert_called_once_with(b.multi_bets_filepath)
        assert result == "QmHash123"


# ===========================================================================
# Tests for fetch_markets_router.py
# ===========================================================================


class TestFetchMarketsRouterBehaviour:
    """Tests for FetchMarketsRouterBehaviour."""

    def test_async_act(self) -> None:
        """Test that async_act creates payload, sends transaction, and waits."""
        b = object.__new__(FetchMarketsRouterBehaviour)  # type: ignore[type-abstract]
        ctx = MagicMock()
        ctx.agent_address = "0xAgent1"  # type: ignore[type-abstract]
        b._context = ctx

        b.send_a2a_transaction = _noop_gen  # type: ignore[method-assign]
        b.wait_until_round_end = _noop_gen  # type: ignore[method-assign]
        b.set_done = MagicMock()  # type: ignore[method-assign]
        # type: ignore[method-assign]
        gen = b.async_act()  # type: ignore[method-assign]
        _exhaust(gen)

        b.set_done.assert_called_once()  # type: ignore[attr-defined]


class TestMarketManagerRoundBehaviour:
    """Tests for MarketManagerRoundBehaviour."""

    def test_behaviours_are_base_behaviour_subclasses(self) -> None:
        """All registered behaviours should be BaseBehaviour subclasses."""
        from packages.valory.skills.abstract_round_abci.behaviours import BaseBehaviour
        from packages.valory.skills.market_manager_abci.behaviours.round_behaviour import (
            MarketManagerRoundBehaviour,
        )

        for b_cls in MarketManagerRoundBehaviour.behaviours:
            assert issubclass(b_cls, BaseBehaviour)
