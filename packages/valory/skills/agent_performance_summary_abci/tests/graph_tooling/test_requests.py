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

"""Tests for the graph_tooling.requests module (APTQueryingBehaviour)."""

import json
from abc import ABC
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from packages.valory.skills.agent_performance_summary_abci.tests.test_behaviours import (
    SAFE_ADDRESS,
    SAFE_ADDRESS_LOWER,
)

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.requests import (
    APTQueryingBehaviour,
    DECIMAL_SCALING_FACTOR,
    FetchStatus,
    MAX_LOG_SIZE,
    OLAS_TOKEN_ADDRESS,
    QUERY_BATCH_SIZE,
    QUESTION_DATA_SEPARATOR,
    USD_PRICE_FIELD,
    _MAX_SLEEP_TIME,
    _unwrap_trader_agent,
    to_content,
)

# ---------------------------------------------------------------------------
# to_content tests
# ---------------------------------------------------------------------------


class TestToContent:
    """Tests for the to_content function."""

    def test_basic_query(self) -> None:
        """Test that a basic query string is properly converted to bytes."""
        query = "{ markets { id } }"
        variables = {"id": "0x123"}
        result = to_content(query, variables)
        assert isinstance(result, bytes)
        decoded = json.loads(result)
        assert "query" in decoded
        assert decoded["query"] == query
        assert decoded["variables"] == variables

    def test_empty_query(self) -> None:
        """Test that an empty query string is properly handled."""
        result = to_content("", {})
        decoded = json.loads(result)
        assert decoded["query"] == ""
        assert decoded["variables"] == {}

    def test_encoding_is_utf8(self) -> None:
        """Test that the result is UTF-8 encoded."""
        result = to_content("test", {"x": 1})
        decoded_str = result.decode("utf-8")
        assert isinstance(decoded_str, str)

    def test_json_keys_sorted(self) -> None:
        """Test that JSON keys are sorted in the output."""
        result = to_content("test", {"b": 2, "a": 1})
        decoded_str = result.decode("utf-8")
        parsed = json.loads(decoded_str)
        assert parsed == {"query": "test", "variables": {"b": 2, "a": 1}}

    def test_special_characters(self) -> None:
        """Test that special characters in queries are preserved."""
        query = '{ user(id: "0xabc") { positions(where: {balance_gt: "0"}) { id } } }'
        result = to_content(query, {})
        decoded = json.loads(result)
        assert decoded["query"] == query


# ---------------------------------------------------------------------------
# APTQueryingBehaviour structure tests
# ---------------------------------------------------------------------------


class TestAPTQueryingBehaviourStructure:
    """Tests for the APTQueryingBehaviour abstract class structure."""

    def test_is_abstract(self) -> None:
        """Test that APTQueryingBehaviour is an ABC subclass."""
        assert issubclass(APTQueryingBehaviour, ABC)

    def test_has_expected_methods(self) -> None:
        """Test that APTQueryingBehaviour has the expected method signatures."""
        assert hasattr(APTQueryingBehaviour, "_fetch_from_subgraph")
        assert hasattr(APTQueryingBehaviour, "_handle_response")
        assert hasattr(APTQueryingBehaviour, "_fetch_mech_sender")
        assert hasattr(APTQueryingBehaviour, "_fetch_trader_agent")
        assert hasattr(APTQueryingBehaviour, "_fetch_staking_service")
        assert hasattr(APTQueryingBehaviour, "_fetch_open_markets")
        assert hasattr(APTQueryingBehaviour, "_fetch_trader_agent_bets")
        assert hasattr(APTQueryingBehaviour, "_fetch_agent_details")
        assert hasattr(APTQueryingBehaviour, "_fetch_trader_agent_performance")
        assert hasattr(APTQueryingBehaviour, "_fetch_pending_bets")
        assert hasattr(APTQueryingBehaviour, "_fetch_all_resolved_markets")
        assert hasattr(APTQueryingBehaviour, "_fetch_olas_in_usd_price")
        assert hasattr(APTQueryingBehaviour, "_fetch_daily_profit_statistics")
        assert hasattr(APTQueryingBehaviour, "_fetch_all_mech_requests")
        assert hasattr(APTQueryingBehaviour, "_fetch_mech_requests_by_titles")
        assert hasattr(APTQueryingBehaviour, "send_polymarket_connection_request")

    def test_has_expected_properties(self) -> None:
        """Test that APTQueryingBehaviour has the params property."""
        assert hasattr(APTQueryingBehaviour, "params")

    def test_init_sets_attributes(self) -> None:
        """Test that __init__ sets the expected default attributes."""
        from packages.valory.skills.abstract_round_abci.base import AbstractRound

        class _ConcreteAPTBehaviour(APTQueryingBehaviour):
            """Concrete subclass for testing."""

            matching_round = MagicMock(spec=AbstractRound)

            # type: ignore[no-untyped-def]
            def async_act(self) -> None:  # type: ignore[misc, override]
                """No-op implementation for testing."""
                yield

        with patch(
            "packages.valory.skills.abstract_round_abci.behaviour_utils.BaseBehaviour.__init__"
        ):  # type: ignore[type-abstract]
            instance = _ConcreteAPTBehaviour.__new__(_ConcreteAPTBehaviour)  # type: ignore[type-abstract]
            instance._context = MagicMock()
            _ConcreteAPTBehaviour.__init__(instance)

        assert instance._call_failed is False
        assert instance._fetch_status == FetchStatus.NONE
        assert instance._current_market == ""


# ---------------------------------------------------------------------------
# Helpers for generator-based tests
# ---------------------------------------------------------------------------


# type: ignore[no-untyped-def]
def _noop_gen(*args: Any, **kwargs: Any) -> Generator:
    """No-op generator that yields once and returns None."""
    yield
    return None


# type: ignore[no-untyped-def]
def _return_gen(value: Any) -> Any:
    """Create a generator factory that yields once and returns *value*."""

    # type: ignore[no-untyped-def]
    def _gen(*args: Any, **kwargs: Any) -> Generator:
        """Inner generator returning value."""
        yield
        return value

    return _gen


def _recording_gen(sink: List[Any]) -> Any:
    """Create a generator factory that records each call's ``content`` kwarg."""
    response: Any = MagicMock()

    # type: ignore[no-untyped-def]
    def _gen(*args: Any, **kwargs: Any) -> Generator:
        """Inner generator recording the request body."""
        sink.append(kwargs.get("content"))
        yield
        return response

    return _gen


class _ConcreteAPTBehaviour(APTQueryingBehaviour):
    """Minimal concrete subclass of APTQueryingBehaviour for testing."""

    matching_round = MagicMock()  # type: ignore[no-untyped-def]

    def async_act(self) -> None:  # type: ignore[misc, override]
        """No-op."""
        yield


# type: ignore[no-untyped-def]


def _make_behaviour(**overrides: Any) -> _ConcreteAPTBehaviour:
    """Instantiate a _ConcreteAPTBehaviour without framework wiring.

    Uses object.__new__ to skip __init__ (which requires the full
    Open Autonomy runtime), then manually sets the attributes that the
    methods under test rely on.

    :param **overrides: keyword arguments to override default attributes.
    :return: a configured _ConcreteAPTBehaviour instance.
    """
    b = object.__new__(_ConcreteAPTBehaviour)  # type: ignore[type-abstract]

    ctx = MagicMock()
    ctx.params.is_running_on_polymarket = False
    ctx.params.coingecko_olas_in_usd_price_url = "https://api.coingecko.com/test"
    b._context = ctx

    # internal state
    b._call_failed = False
    b._fetch_status = FetchStatus.NONE
    b._current_market = ""

    for k, v in overrides.items():  # type: ignore[no-untyped-def]
        setattr(b, k, v)
    return b


def _exhaust(gen: "Generator[Any, Any, Any]") -> Any:
    """Drive a generator to completion and return its final value."""
    result = None
    try:
        while True:
            next(gen)
    except StopIteration as exc:
        result = exc.value
    return result


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


class TestAPTQueryingBehaviourProperties:
    """Tests for the properties exposed by APTQueryingBehaviour."""

    def test_params_returns_cast_params(self) -> None:
        """Test that the params property returns context.params."""
        b = _make_behaviour()
        result = b.params
        assert result is b.context.params


# ---------------------------------------------------------------------------
# _handle_response tests
# ---------------------------------------------------------------------------


# type: ignore[no-untyped-def]
class TestHandleResponse:
    """Tests for _handle_response."""

    @staticmethod
    def _make_subgraph(
        retries_exceeded: bool = False, sleep_time: float = 1.0
    ) -> MagicMock:
        """Create a mock subgraph with controllable retry behaviour."""
        sg = MagicMock()
        sg.api_id = "test_subgraph"
        sg.is_retries_exceeded.return_value = retries_exceeded
        sg.retries_info.suggested_sleep_time = sleep_time
        return sg

    def test_none_response_increments_retries_and_sleeps(self) -> None:
        """A None response logs error, increments retries, sleeps."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        sg = self._make_subgraph()

        gen = b._handle_response(sg, None, "things")
        result = _exhaust(gen)

        assert result is None
        assert b._call_failed is True
        sg.increment_retries.assert_called_once()
        b.context.logger.error.assert_called_once()

    def test_none_response_sets_fail_when_retries_exceeded(self) -> None:
        """When retries are exceeded, status becomes FAIL."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        sg = self._make_subgraph(retries_exceeded=True)

        gen = b._handle_response(sg, None, "things")
        _exhaust(gen)

        assert b._fetch_status == FetchStatus.FAIL  # type: ignore[no-untyped-def]

    def test_none_response_no_sleep_when_sleep_on_fail_false(self) -> None:
        """When sleep_on_fail=False, the sleep generator is not invoked."""
        b = _make_behaviour()
        sleep_called = False

        def _tracking_sleep(*a: Any, **kw: Any) -> Generator:
            nonlocal sleep_called
            sleep_called = True
            yield

        b.sleep = _tracking_sleep  # type: ignore[method-assign]
        sg = self._make_subgraph()

        gen = b._handle_response(sg, None, "things", sleep_on_fail=False)
        _exhaust(gen)

        assert sleep_called is False

    def test_successful_response_resets_retries(self) -> None:
        """A non-None response resets retries and returns the data."""
        b = _make_behaviour()
        sg = self._make_subgraph()
        data = [{"id": "1"}]

        gen = b._handle_response(sg, data, "things")  # type: ignore[arg-type]
        result = _exhaust(gen)

        assert result == data
        assert b._call_failed is False
        assert b._fetch_status == FetchStatus.SUCCESS
        sg.reset_retries.assert_called_once()
        b.context.logger.info.assert_called_once()

    def test_successful_response_truncates_log(self) -> None:
        """Long responses are truncated in logs."""
        b = _make_behaviour()
        sg = self._make_subgraph()
        data = {"key": "x" * (MAX_LOG_SIZE + 500)}

        gen = b._handle_response(sg, data, "things")
        _exhaust(gen)

        # Verify logger.info was called - the truncation happens internally
        b.context.logger.info.assert_called_once()

    def test_successful_response_replaces_separator_in_log(self) -> None:
        """The QUESTION_DATA_SEPARATOR is replaced with space in logs."""
        b = _make_behaviour()
        sg = self._make_subgraph()
        data = {"key": f"before{QUESTION_DATA_SEPARATOR}after"}

        gen = b._handle_response(sg, data, "things")
        _exhaust(gen)

        call_args = b.context.logger.info.call_args[0][0]
        assert QUESTION_DATA_SEPARATOR not in call_args

    def test_none_response_retries_not_exceeded_no_fail(self) -> None:
        """When retries are not exceeded, status should not become FAIL."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        sg = self._make_subgraph(retries_exceeded=False)

        gen = b._handle_response(sg, None, "things")
        _exhaust(gen)

        assert b._fetch_status != FetchStatus.FAIL


# ---------------------------------------------------------------------------
# _fetch_from_subgraph tests
# ---------------------------------------------------------------------------


class TestFetchFromSubgraph:
    """Tests for _fetch_from_subgraph."""

    def test_successful_fetch(self) -> None:
        """A successful fetch returns the processed result."""
        b = _make_behaviour()
        sg = MagicMock()
        sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        sg.process_response.return_value = {"data": "ok"}
        sg.is_retries_exceeded.return_value = False

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_from_subgraph("query", {}, sg, "test_context")
        result = _exhaust(gen)

        assert result == {"data": "ok"}
        assert b._fetch_status == FetchStatus.SUCCESS

    def test_fetch_sets_in_progress(self) -> None:
        """The fetch status is set to IN_PROGRESS at the start."""
        b = _make_behaviour()
        sg = MagicMock()
        sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        sg.process_response.return_value = {"data": "ok"}
        sg.is_retries_exceeded.return_value = False

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_from_subgraph("query", {}, sg, "test_context")
        # After first yield, status should be IN_PROGRESS
        next(gen)
        assert b._fetch_status == FetchStatus.IN_PROGRESS

    def test_fetch_with_none_response(self) -> None:
        """When process_response returns None, _handle_response handles it."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        sg = MagicMock()
        sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        sg.process_response.return_value = None
        sg.api_id = "test_subgraph"
        sg.is_retries_exceeded.return_value = False
        sg.retries_info.suggested_sleep_time = 1.0

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_from_subgraph("query", {}, sg, "test_context")
        result = _exhaust(gen)

        assert result is None
        assert b._call_failed is True


# ---------------------------------------------------------------------------
# send_polymarket_connection_request tests
# ---------------------------------------------------------------------------


class TestSendPolymarketConnectionRequest:
    """Tests for send_polymarket_connection_request."""

    def test_sends_request_and_returns_json(self) -> None:
        """Test that the method creates a message, sends it, and returns parsed JSON."""
        b = _make_behaviour()

        # Mock SrrDialogues
        mock_srr_dialogues = MagicMock()
        mock_message = MagicMock()
        mock_dialogue = MagicMock()
        mock_srr_dialogues.create.return_value = (mock_message, mock_dialogue)
        b.context.srr_dialogues = mock_srr_dialogues

        # Mock request/response
        b._get_request_nonce_from_dialogue = MagicMock(return_value="nonce_1")  # type: ignore[method-assign]
        b.get_callback_request = MagicMock(return_value=MagicMock())  # type: ignore[method-assign]

        mock_response = MagicMock()
        mock_response.payload = json.dumps({"result": "success"})
        b.wait_for_message = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b.send_polymarket_connection_request({"action": "test"})
        result = _exhaust(gen)

        assert result == {"result": "success"}
        b.context.outbox.put_message.assert_called_once()


# ---------------------------------------------------------------------------
# _fetch_mech_sender tests
# ---------------------------------------------------------------------------


class TestFetchMechSender:
    """Tests for _fetch_mech_sender."""

    def test_polymarket_path(self) -> None:
        """When running on polymarket, uses polygon_mech_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"sender": {"requests": [{"id": "1"}]}}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polygon_mech_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_sender("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"requests": [{"id": "1"}]}

    def test_omen_path(self) -> None:
        """When not on polymarket, uses olas_mech_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"sender": {"requests": [{"id": "2"}]}}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_sender("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"requests": [{"id": "2"}]}

    def test_returns_result_when_no_sender_key(self) -> None:
        """When result has no 'sender' key, returns the raw result."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"other": "data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_sender("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"other": "data"}

    def test_returns_none_when_result_is_none(self) -> None:
        """When the subgraph returns None, returns None."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.olas_mech_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_sender("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_returns_result_when_not_dict(self) -> None:
        """When result is not a dict, returns it directly."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = [{"id": "1"}]
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_sender("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "1"}]


# ---------------------------------------------------------------------------
# _fetch_trader_agent tests
# ---------------------------------------------------------------------------


class TestFetchTraderAgent:
    """Tests for _fetch_trader_agent."""

    def test_polymarket_path(self) -> None:
        """When running on polymarket, uses polymarket_agents_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"id": "0xagent", "totalBets": 5}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"id": "0xagent", "totalBets": 5}

    def test_omen_path(self) -> None:
        """When not on polymarket, uses olas_agents_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"id": "0xagent", "totalBets": 10}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"id": "0xagent", "totalBets": 10}

    def test_returns_raw_when_no_traderAgent_key(self) -> None:
        """When result has no traderAgent key, returns raw result."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"other": "data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"other": "data"}

    def test_returns_none_when_fetch_fails(self) -> None:
        """When fetch returns None, returns None."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_returns_result_when_not_dict(self) -> None:
        """When result is not a dict, returns raw result."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = "some_string"
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == "some_string"

    def test_polymarket_path_sends_lowercased_address(self) -> None:
        """OPE-1923: the squid matches ``id`` exactly, so ``$id`` must be lowercase."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"traderAgent": {"id": "0xagent"}}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_agents_subgraph = mock_sg

        sent: List[Any] = []
        b.get_http_response = _recording_gen(sent)  # type: ignore[method-assign]

        _exhaust(b._fetch_trader_agent(SAFE_ADDRESS))  # type: ignore[arg-type]

        assert json.loads(sent[-1])["variables"]["id"] == SAFE_ADDRESS_LOWER

    def test_omen_path_sends_lowercased_address(self) -> None:
        """The Omen branch is pinned too, in case that endpoint ever moves."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"traderAgent": {"id": "0xagent"}}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        sent: List[Any] = []
        b.get_http_response = _recording_gen(sent)  # type: ignore[method-assign]

        _exhaust(b._fetch_trader_agent(SAFE_ADDRESS))  # type: ignore[arg-type]

        assert json.loads(sent[-1])["variables"]["id"] == SAFE_ADDRESS_LOWER


# ---------------------------------------------------------------------------
# _fetch_staking_service tests
# ---------------------------------------------------------------------------


class TestFetchStakingService:
    """Tests for _fetch_staking_service."""

    def test_polymarket_path(self) -> None:
        """When running on polymarket, uses polygon_staking_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"staking": "data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polygon_staking_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_staking_service("service_1")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"staking": "data"}

    def test_omen_path(self) -> None:
        """When not on polymarket, uses gnosis_staking_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"staking": "gnosis_data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.gnosis_staking_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_staking_service("service_1")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"staking": "gnosis_data"}


# ---------------------------------------------------------------------------
# _fetch_open_markets tests
# ---------------------------------------------------------------------------


class TestFetchOpenMarkets:
    """Tests for _fetch_open_markets."""

    def test_returns_result(self) -> None:
        """Test that open markets are fetched from the subgraph."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = [{"id": "market_1"}]
        mock_sg.is_retries_exceeded.return_value = False
        b.context.open_markets_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_open_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "market_1"}]


# ---------------------------------------------------------------------------
# _fetch_trader_agent_bets tests
# ---------------------------------------------------------------------------


class TestFetchTraderAgentBets:
    """Tests for _fetch_trader_agent_bets."""

    def test_polymarket_path_with_bets(self) -> None:
        """When on polymarket, extracts bets from participants."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = [
            {"bets": [{"id": "bet1"}, {"id": "bet2"}]},
            {"bets": [{"id": "bet3"}]},
        ]
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_bets_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"bets": [{"id": "bet1"}, {"id": "bet2"}, {"id": "bet3"}]}

    def test_polymarket_path_with_no_bets(self) -> None:
        """When on polymarket but no bets, returns None."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = [{"bets": []}]
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_bets_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_polymarket_path_non_list_result(self) -> None:
        """When on polymarket but result is not a list, returns None."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"not_a_list": True}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_bets_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_omen_path_with_traderAgent(self) -> None:
        """When on omen, extracts from traderAgent key."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"bets": [{"id": "bet1"}]}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"bets": [{"id": "bet1"}]}

    def test_omen_path_returns_raw_when_no_traderAgent_key(self) -> None:
        """When on omen but no traderAgent key, returns raw."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"other": "data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"other": "data"}

    def test_polymarket_path_fetch_fails(self) -> None:
        """When polymarket fetch returns None, returns None."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.polymarket_bets_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_polymarket_path_sends_lowercased_address(self) -> None:
        """OPE-1923: ``id_eq`` is exact equality, so ``$id`` must be lowercase."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = [{"bets": [{"id": "bet1"}]}]
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_bets_subgraph = mock_sg

        sent: List[Any] = []
        b.get_http_response = _recording_gen(sent)  # type: ignore[method-assign]

        _exhaust(b._fetch_trader_agent_bets(SAFE_ADDRESS))  # type: ignore[arg-type]

        assert json.loads(sent[-1])["variables"]["id"] == SAFE_ADDRESS_LOWER

    def test_omen_path_sends_lowercased_address(self) -> None:
        """The Omen branch is pinned too, in case that endpoint ever moves."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"traderAgent": {"bets": []}}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        sent: List[Any] = []
        b.get_http_response = _recording_gen(sent)  # type: ignore[method-assign]

        _exhaust(b._fetch_trader_agent_bets(SAFE_ADDRESS))  # type: ignore[arg-type]

        assert json.loads(sent[-1])["variables"]["id"] == SAFE_ADDRESS_LOWER


# ---------------------------------------------------------------------------
# _fetch_agent_details tests
# ---------------------------------------------------------------------------


class TestFetchAgentDetails:
    """Tests for _fetch_agent_details."""

    def test_polymarket_path(self) -> None:
        """When on polymarket, uses polymarket_agents_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"id": "0x1", "createdAt": "100"}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_agent_details("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"id": "0x1", "createdAt": "100"}

    def test_omen_path(self) -> None:
        """When not on polymarket, uses olas_agents_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"id": "0x2", "createdAt": "200"}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_agent_details("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"id": "0x2", "createdAt": "200"}

    def test_forwards_the_address_verbatim(self) -> None:
        """OPE-1923 fixed two helpers only; the neighbours keep their behaviour.

        ``_fetch_agent_details`` binds the same ``{"id": ...}`` shape and was
        deliberately left un-normalised: it is correct today because its
        callers already lowercase. Pinning that here makes a later
        "make it uniform" sweep a conscious edit rather than silent drift.
        """
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"traderAgent": {"id": "0x1"}}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_agents_subgraph = mock_sg

        sent: List[Any] = []
        b.get_http_response = _recording_gen(sent)  # type: ignore[method-assign]

        _exhaust(b._fetch_agent_details(SAFE_ADDRESS))  # type: ignore[arg-type]

        assert json.loads(sent[-1])["variables"]["id"] == SAFE_ADDRESS

    def test_returns_raw_when_no_traderAgent_key(self) -> None:
        """When no traderAgent key, returns raw result."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"other": "data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_agent_details("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"other": "data"}

    def test_returns_result_when_not_dict(self) -> None:
        """When result is not dict, returns raw."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = "string_result"
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_agent_details("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == "string_result"


# ---------------------------------------------------------------------------
# _fetch_trader_agent_performance tests
# ---------------------------------------------------------------------------


class TestFetchTraderAgentPerformance:
    """Tests for _fetch_trader_agent_performance."""

    def test_polymarket_path(self) -> None:
        """When on polymarket, uses polymarket_agents_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"totalBets": 10, "totalTraded": 1000}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polymarket_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_performance("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"totalBets": 10, "totalTraded": 1000}

    def test_omen_path_with_pagination_args(self) -> None:
        """When on omen, includes first/skip variables."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"totalBets": 20, "bets": []}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_performance("0xagent", first=50, skip=10)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"totalBets": 20, "bets": []}

    def test_returns_raw_when_no_traderAgent_key(self) -> None:
        """When no traderAgent key, returns raw result."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = [{"id": "1"}]
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_performance("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "1"}]


# ---------------------------------------------------------------------------
# _fetch_pending_bets tests
# ---------------------------------------------------------------------------


class TestFetchPendingBets:
    """Tests for _fetch_pending_bets."""

    def test_with_traderAgent_key(self) -> None:
        """When result has traderAgent key, extracts it."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "traderAgent": {"bets": [{"id": "pending1"}]}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_pending_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"bets": [{"id": "pending1"}]}

    def test_without_traderAgent_key(self) -> None:
        """When result has no traderAgent key, returns raw."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"other": "data"}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_pending_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == {"other": "data"}


# ---------------------------------------------------------------------------
# _fetch_all_resolved_markets tests  # type: ignore[no-untyped-def]
# ---------------------------------------------------------------------------


class TestFetchAllResolvedMarkets:
    """Tests for _fetch_all_resolved_markets."""

    def _setup_subgraph(self, b: _ConcreteAPTBehaviour, responses: list) -> MagicMock:  # type: ignore[type-arg]
        """Set up mock subgraph with a sequence of responses."""  # type: ignore[no-untyped-def]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.is_retries_exceeded.return_value = False

        call_count = [0]

        def process_response_side_effect(*args: Any, **kwargs: Any) -> Any:
            if call_count[0] < len(responses):
                result = responses[call_count[0]]
                call_count[0] += 1
                return result
            return None

        mock_sg.process_response.side_effect = process_response_side_effect
        b.context.olas_agents_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]
        return mock_sg

    def test_single_batch_full(self) -> None:
        """When first batch has fewer items than batch_size, no second query."""
        b = _make_behaviour()
        markets = [{"id": f"m{i}"} for i in range(5)]
        self._setup_subgraph(b, [markets])

        gen = b._fetch_all_resolved_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == markets

    def test_pagination_across_batches(self) -> None:
        """When first batch is full, fetches another batch."""
        b = _make_behaviour()
        batch1 = [{"id": f"m{i}"} for i in range(QUERY_BATCH_SIZE)]
        batch2 = [{"id": f"m{QUERY_BATCH_SIZE + i}"} for i in range(5)]
        self._setup_subgraph(b, [batch1, batch2])

        gen = b._fetch_all_resolved_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert len(result) == QUERY_BATCH_SIZE + 5

    def test_empty_first_batch(self) -> None:
        """When first batch is empty, returns empty list."""
        b = _make_behaviour()
        self._setup_subgraph(b, [[]])

        gen = b._fetch_all_resolved_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_none_result_breaks(self) -> None:
        """When fetch returns None, breaks the loop."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.olas_agents_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_all_resolved_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_with_timestamp_lte(self) -> None:
        """When timestamp_lte is provided, it is included in variables."""
        b = _make_behaviour()
        self._setup_subgraph(b, [[{"id": "m1"}]])

        gen = b._fetch_all_resolved_markets(1000, timestamp_lte=2000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "m1"}]

    def test_dict_result_extracts_fixedProductMarketMakers(self) -> None:
        """When result is a dict, extracts fixedProductMarketMakers key."""
        b = _make_behaviour()
        markets = [{"id": "m1"}, {"id": "m2"}]
        self._setup_subgraph(b, [{"fixedProductMarketMakers": markets}])

        gen = b._fetch_all_resolved_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == markets

    def test_dict_result_empty_fixedProductMarketMakers(self) -> None:
        """When result dict has empty fixedProductMarketMakers, returns empty."""
        b = _make_behaviour()
        self._setup_subgraph(b, [{"fixedProductMarketMakers": []}])

        gen = b._fetch_all_resolved_markets(1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []


# ---------------------------------------------------------------------------
# _fetch_olas_in_usd_price tests
# ---------------------------------------------------------------------------


class TestFetchOlasInUsdPrice:
    """Tests for _fetch_olas_in_usd_price."""

    def test_successful_fetch(self) -> None:
        """Test fetching a valid USD price."""
        b = _make_behaviour()

        mock_response = MagicMock()
        mock_response.body = json.dumps(
            {OLAS_TOKEN_ADDRESS: {USD_PRICE_FIELD: 1.5}}
        ).encode()
        b.get_http_response = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._fetch_olas_in_usd_price()
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == int(1.5 * DECIMAL_SCALING_FACTOR)

    def test_invalid_json_response(self) -> None:
        """Test handling of invalid JSON response."""
        b = _make_behaviour()

        mock_response = MagicMock()
        mock_response.body = b"not valid json"
        b.get_http_response = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._fetch_olas_in_usd_price()
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None
        b.context.logger.error.assert_called_once()

    def test_missing_token_address(self) -> None:
        """Test handling when token address is not in response."""
        b = _make_behaviour()

        mock_response = MagicMock()
        mock_response.body = json.dumps({"other_token": {"usd": 1.0}}).encode()
        b.get_http_response = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._fetch_olas_in_usd_price()
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_missing_usd_field(self) -> None:
        """Test handling when usd field is not in response."""
        b = _make_behaviour()

        mock_response = MagicMock()
        mock_response.body = json.dumps({OLAS_TOKEN_ADDRESS: {"eur": 1.5}}).encode()
        b.get_http_response = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._fetch_olas_in_usd_price()
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_sets_in_progress(self) -> None:
        """Test that fetch status is set to IN_PROGRESS."""
        b = _make_behaviour()

        mock_response = MagicMock()
        mock_response.body = json.dumps(
            {OLAS_TOKEN_ADDRESS: {USD_PRICE_FIELD: 2.0}}
        ).encode()
        b.get_http_response = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._fetch_olas_in_usd_price()
        next(gen)
        assert b._fetch_status == FetchStatus.IN_PROGRESS

    def test_binary_garbage_body_returns_none(self) -> None:
        """Binary garbage body is caught and returns None."""
        b = _make_behaviour()

        mock_response = MagicMock()
        # Binary garbage that fails UTF-8 decode
        mock_response.body = b"\x80\x81\x82\xff\xfe"
        b.get_http_response = _return_gen(mock_response)  # type: ignore[method-assign]

        gen = b._fetch_olas_in_usd_price()
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None
        b.context.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _fetch_daily_profit_statistics tests  # type: ignore[no-untyped-def]
# ---------------------------------------------------------------------------


class TestFetchDailyProfitStatistics:
    """Tests for _fetch_daily_profit_statistics."""

    def _setup_subgraph(self, b: _ConcreteAPTBehaviour, responses: list, is_polymarket: bool = False) -> MagicMock:  # type: ignore[type-arg]
        """Set up mock subgraph with sequential responses."""  # type: ignore[no-untyped-def]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.is_retries_exceeded.return_value = False

        call_count = [0]

        def process_response_side_effect(*args: Any, **kwargs: Any) -> Any:
            if call_count[0] < len(responses):
                result = responses[call_count[0]]
                call_count[0] += 1
                return result
            return None

        mock_sg.process_response.side_effect = process_response_side_effect
        b.context.params.is_running_on_polymarket = is_polymarket

        if is_polymarket:
            b.context.polymarket_agents_subgraph = mock_sg
        else:
            b.context.olas_agents_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]
        return mock_sg

    def test_omen_single_batch(self) -> None:
        """Test fetching daily profit stats on Omen, single batch."""
        b = _make_behaviour()
        stats = [{"day": "2024-01-01", "profit": "100"}]
        self._setup_subgraph(
            b,
            [{"traderAgent": {"dailyProfitStatistics": stats}}],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == stats

    def test_polymarket_single_batch(self) -> None:
        """Test fetching daily profit stats on Polymarket, single batch."""
        b = _make_behaviour()
        stats = [{"day": "2024-01-01", "profit": "50"}]
        self._setup_subgraph(
            b,
            [{"traderAgent": {"dailyProfitStatistics": stats}}],
            is_polymarket=True,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == stats

    def test_first_page_transport_failure_returns_none(self) -> None:
        """Transport failure on the first page propagates as ``None``.

        Under the schema-v2 rebuild every deployed agent routes through
        ``_perform_initial_backfill`` once. If daily stats came back as
        ``[]`` on a real transport failure, backfill would write an
        empty series stamped ``schema_version=2`` and wipe the agent's
        history with no rebuild path left to fire.
        """
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.olas_agents_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_mid_pagination_failure_returns_none(self) -> None:
        """Transport failure on page N propagates as ``None`` too.

        A truncated-but-non-empty result is even worse than an empty
        one under the schema-v2 rebuild — it looks plausible, so no
        downstream guard fires.
        """
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        first_full_batch = [{"day": f"d{i}"} for i in range(QUERY_BATCH_SIZE)]
        self._setup_subgraph(
            b,
            # Page 1: full batch (forces pagination). Page 2: transport
            # failure (``None``).
            [
                {"traderAgent": {"dailyProfitStatistics": first_full_batch}},
                None,
            ],
            is_polymarket=False,
        )
        b.context.olas_agents_subgraph.api_id = "test"
        b.context.olas_agents_subgraph.retries_info.suggested_sleep_time = 1.0

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_no_dailyProfitStatistics_key(self) -> None:
        """When result has no dailyProfitStatistics key, returns empty list."""
        b = _make_behaviour()
        self._setup_subgraph(
            b,
            [{"traderAgent": {"otherKey": "value"}}],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_pagination(self) -> None:
        """Test pagination across multiple batches."""
        b = _make_behaviour()
        batch1 = [{"day": f"d{i}"} for i in range(QUERY_BATCH_SIZE)]
        batch2 = [{"day": "final"}]
        self._setup_subgraph(
            b,
            [
                {"traderAgent": {"dailyProfitStatistics": batch1}},
                {"traderAgent": {"dailyProfitStatistics": batch2}},
            ],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert len(result) == QUERY_BATCH_SIZE + 1

    def test_result_without_traderAgent_wrapper(self) -> None:
        """When result does not have traderAgent key, uses result directly."""
        b = _make_behaviour()
        stats = [{"day": "2024-01-01", "profit": "100"}]
        self._setup_subgraph(
            b,
            [{"dailyProfitStatistics": stats}],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == stats

    def test_null_traderAgent(self) -> None:
        """When traderAgent is None, returns empty list."""
        b = _make_behaviour()
        self._setup_subgraph(
            b,
            [{"traderAgent": None}],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_empty_daily_profit_statistics(self) -> None:
        """When dailyProfitStatistics is empty list, returns empty list."""
        b = _make_behaviour()
        self._setup_subgraph(
            b,
            [{"traderAgent": {"dailyProfitStatistics": []}}],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_daily_profit_statistics_truthy_then_falsy(self) -> None:
        """Test when dailyProfitStatistics is truthy on first get, falsy on second.

        This covers the secondary empty check at line 498-499.
        Line 494: ``not result.get("dailyProfitStatistics")`` -> truthy (passes)
        Line 497: ``batch_statistics = result.get("dailyProfitStatistics", [])``
                  -> returns falsy value, triggering the ``if not batch_statistics``
                  guard at line 498.

        We use a custom dict subclass whose .get("dailyProfitStatistics")
        returns a truthy value on the first call and an empty list on the
        second call.  # type: ignore[no-untyped-def]
        """
        b = _make_behaviour()

        class FlipFlopDict(dict):
            """Dict where get('dailyProfitStatistics') changes on each call."""  # type: ignore[no-untyped-def]

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                """Initialize with call counter."""
                super().__init__(*args, **kwargs)  # type: ignore[no-untyped-def]
                self._call_count = 0

            def __bool__(self) -> bool:
                """Always truthy so ``or {}`` does not replace us."""
                return True

            def get(self, key: Any, default: Any = None) -> Any:
                """Return truthy first, falsy second for dailyProfitStatistics."""
                if key == "dailyProfitStatistics":
                    self._call_count += 1
                    if self._call_count == 1:
                        return [{"sentinel": True}]  # truthy -> passes line 494
                    return []  # falsy -> triggers line 498-499
                return super().get(key, default)

        flip_dict = FlipFlopDict()

        self._setup_subgraph(
            b,
            [{"traderAgent": flip_dict}],
            is_polymarket=False,
        )

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []


# ---------------------------------------------------------------------------
# _fetch_all_mech_requests tests  # type: ignore[no-untyped-def]
# ---------------------------------------------------------------------------


class TestFetchAllMechRequests:
    """Tests for _fetch_all_mech_requests."""

    def _setup_subgraph(self, b: _ConcreteAPTBehaviour, responses: list, is_polymarket: bool = False) -> MagicMock:  # type: ignore[type-arg]
        """Set up mock subgraph with sequential responses."""  # type: ignore[no-untyped-def]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.is_retries_exceeded.return_value = False

        call_count = [0]

        def process_response_side_effect(*args: Any, **kwargs: Any) -> Any:
            if call_count[0] < len(responses):
                result = responses[call_count[0]]
                call_count[0] += 1
                return result
            return None

        mock_sg.process_response.side_effect = process_response_side_effect
        b.context.params.is_running_on_polymarket = is_polymarket

        if is_polymarket:
            b.context.polygon_mech_subgraph = mock_sg
        else:
            b.context.olas_mech_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]
        return mock_sg

    def test_omen_single_batch(self) -> None:
        """Test fetching mech requests on omen."""
        b = _make_behaviour()
        requests_data = [{"id": "req1"}, {"id": "req2"}]
        self._setup_subgraph(
            b,
            [{"sender": {"requests": requests_data}}],
            is_polymarket=False,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == requests_data

    def test_polymarket_single_batch(self) -> None:
        """Test fetching mech requests on polymarket."""
        b = _make_behaviour()
        requests_data = [{"id": "req1"}]
        self._setup_subgraph(
            b,
            [{"sender": {"requests": requests_data}}],
            is_polymarket=True,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == requests_data

    def test_first_page_transport_failure_returns_none(self) -> None:
        """Transport failure on the first page propagates as ``None``.

        The caller (``_build_mech_request_lookup``) uses ``None`` to
        distinguish "fetch failed, preserve prior data" from ``[]``
        ("agent genuinely has no mech requests yet"). Coercing to
        ``[]`` here would let the schema-v2 rebuild consume an empty
        lookup, write a zero-attribution series, and persist
        ``schema_version=2`` — locking the agent out of the rebuild
        it needs.
        """
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_mid_pagination_failure_returns_none(self) -> None:
        """Transport failure on page N propagates as ``None`` too.

        Same rationale as first-page failure: returning the partial
        prefix would be indistinguishable from a complete result, and
        the caller has no way to tell the rebuild is undercounting.
        """
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        first_full_batch = [{"id": f"r{i}"} for i in range(QUERY_BATCH_SIZE)]
        self._setup_subgraph(
            b,
            # Page 1: full batch (forces pagination). Page 2: transport
            # failure (``None``).
            [
                {"sender": {"requests": first_full_batch}},
                None,
            ],
            is_polymarket=False,
        )
        # ``_setup_subgraph`` wires ``get_http_response`` non-retry;
        # give the retry sleep something to yield.
        b.context.olas_mech_subgraph.api_id = "test"
        b.context.olas_mech_subgraph.retries_info.suggested_sleep_time = 1.0

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_well_formed_empty_page_terminates_pagination(self) -> None:
        """A well-formed empty response (``{}``) ends pagination cleanly.

        Locks in the distinction between a transport failure (``None``,
        propagate) and an empty page (``{}``, terminate). Without this
        test the ``if not result: break`` line is uncovered — every
        other termination path in the loop is now driven by returning
        ``None``, and coverage would silently regress if the empty-
        page branch were removed.
        """
        b = _make_behaviour()
        first_full_batch = [{"id": f"r{i}"} for i in range(QUERY_BATCH_SIZE)]
        self._setup_subgraph(
            b,
            # Page 1: full batch (forces the loop past its
            # ``len < batch_size`` shortcut). Page 2: well-formed
            # empty dict from the subgraph, which is what a healthy
            # end-of-collection looks like at this layer.
            [
                {"sender": {"requests": first_full_batch}},
                {},
            ],
            is_polymarket=False,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == first_full_batch

    def test_empty_requests_list(self) -> None:
        """When requests list is empty, returns empty list."""
        b = _make_behaviour()
        self._setup_subgraph(
            b,
            [{"sender": {"requests": []}}],
            is_polymarket=False,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_pagination(self) -> None:
        """Test pagination across multiple batches."""
        b = _make_behaviour()
        batch1 = [{"id": f"r{i}"} for i in range(QUERY_BATCH_SIZE)]
        batch2 = [{"id": "final"}]
        self._setup_subgraph(
            b,
            [
                {"sender": {"requests": batch1}},
                {"sender": {"requests": batch2}},
            ],
            is_polymarket=False,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert len(result) == QUERY_BATCH_SIZE + 1

    def test_result_without_sender_wrapper(self) -> None:
        """When result has no sender key, treats it as the result directly."""
        b = _make_behaviour()
        requests_data = [{"id": "req1"}]
        self._setup_subgraph(
            b,
            [{"requests": requests_data}],
            is_polymarket=False,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == requests_data

    def test_null_sender(self) -> None:
        """When sender is None (via .get returning None then or {}), returns empty."""
        b = _make_behaviour()
        self._setup_subgraph(
            b,
            [{"sender": None}],
            is_polymarket=False,
        )

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []


# ---------------------------------------------------------------------------
# _fetch_mech_requests_by_titles tests
# ---------------------------------------------------------------------------


class TestFetchMechRequestsByTitles:
    """Tests for _fetch_mech_requests_by_titles."""

    def test_empty_titles(self) -> None:
        """When question_titles is empty, returns empty list without querying."""
        b = _make_behaviour()

        gen = b._fetch_mech_requests_by_titles("0xagent", [])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_omen_with_sender_wrapper(self) -> None:
        """When on omen and result has sender key, extracts requests."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "sender": {"requests": [{"id": "req1"}]}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["question1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "req1"}]

    def test_polymarket_path(self) -> None:
        """When on polymarket, uses polygon_mech_subgraph."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {
            "sender": {"requests": [{"id": "req2"}]}
        }
        mock_sg.is_retries_exceeded.return_value = False
        b.context.polygon_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["question1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "req2"}]

    def test_result_without_sender_wrapper(self) -> None:
        """When result has no sender key, tries to get requests from result dict."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"requests": [{"id": "req3"}]}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["q1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == [{"id": "req3"}]

    def test_transport_failure_returns_none(self) -> None:
        """Transport failure propagates as ``None``, not coerced to ``[]``.

        The incremental-update path in ``behaviours.py`` distinguishes
        ``None`` (fail-closed, preserve existing profit data via the
        H6 lookback) from ``[]`` (legitimate "nothing new since
        watermark", proceed). Silently coercing ``None`` to ``[]``
        here made every subgraph outage look like a normal empty tick
        and wrote zero-attribution days that never self-heal.
        """
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["q1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None

    def test_result_not_dict(self) -> None:
        """When result is not a dict, returns empty list."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = "string_result"
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["q1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

    def test_null_sender_in_result(self) -> None:
        """When sender is None, returns empty list."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = {"sender": None}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["q1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []


# ---------------------------------------------------------------------------
# Sleep overflow hotfix tests (PREDICT-691)
# ---------------------------------------------------------------------------


class TestSleepTimeClamping:
    """Tests for sleep time clamping in _handle_response."""

    @staticmethod
    def _make_subgraph(
        retries_exceeded: bool = False, sleep_time: float = 1.0
    ) -> MagicMock:
        """Create a mock subgraph with controllable retry behaviour."""
        sg = MagicMock()
        sg.api_id = "test_subgraph"
        sg.is_retries_exceeded.return_value = retries_exceeded
        sg.retries_info.suggested_sleep_time = sleep_time
        return sg

    def test_overflow_sleep_time_clamped(self) -> None:
        """2**46 seconds (~46 failed retries) would overflow timedelta; clamp prevents it."""
        overflow_seconds = 2**46  # the value that caused the original OverflowError
        b = _make_behaviour()
        actual_sleep_time = None

        def _capture_sleep(seconds: float) -> Generator:
            nonlocal actual_sleep_time
            actual_sleep_time = seconds
            yield

        b.sleep = _capture_sleep  # type: ignore[method-assign]
        sg = self._make_subgraph(sleep_time=overflow_seconds)

        gen = b._handle_response(sg, None, "things")
        _exhaust(gen)

        assert actual_sleep_time == _MAX_SLEEP_TIME

    def test_sleep_time_below_max_unchanged(self) -> None:
        """Sleep time below _MAX_SLEEP_TIME passes through unchanged."""
        b = _make_behaviour()
        actual_sleep_time = None

        def _capture_sleep(seconds: float) -> Generator:
            nonlocal actual_sleep_time
            actual_sleep_time = seconds
            yield

        b.sleep = _capture_sleep  # type: ignore[method-assign]
        sg = self._make_subgraph(sleep_time=5.0)

        gen = b._handle_response(sg, None, "things")
        _exhaust(gen)

        assert actual_sleep_time == 5.0

    def test_no_sleep_when_retries_exceeded(self) -> None:
        """When retries are exceeded, sleep is skipped entirely."""
        b = _make_behaviour()
        sleep_called = False

        def _tracking_sleep(*a: Any, **kw: Any) -> Generator:
            nonlocal sleep_called
            sleep_called = True
            yield

        b.sleep = _tracking_sleep  # type: ignore[method-assign]
        sg = self._make_subgraph(retries_exceeded=True, sleep_time=10.0)

        gen = b._handle_response(sg, None, "things")
        _exhaust(gen)

        assert b._fetch_status == FetchStatus.FAIL
        assert sleep_called is False


# ---------------------------------------------------------------------------
# clean_up tests
# ---------------------------------------------------------------------------


class TestCleanUp:
    """Tests for the clean_up method."""

    def test_resets_retries_on_all_subgraphs(self) -> None:
        """clean_up resets retries on every subgraph."""
        b = _make_behaviour()

        subgraph_names = (
            "polygon_mech_subgraph",
            "olas_mech_subgraph",
            "olas_agents_subgraph",
            "polymarket_agents_subgraph",
            "open_markets_subgraph",
            "polymarket_bets_subgraph",
            "gnosis_staking_subgraph",
            "polygon_staking_subgraph",
        )
        mocks = {}
        for name in subgraph_names:
            m = MagicMock()
            setattr(b.context, name, m)
            mocks[name] = m

        b.clean_up()

        for _name, m in mocks.items():
            m.reset_retries.assert_called_once()

    def test_clean_up_tolerates_missing_subgraph(self) -> None:
        """clean_up does not crash when a subgraph attribute is missing."""
        b = _make_behaviour()
        # Delete all subgraph attributes so getattr returns None
        for name in (
            "polygon_mech_subgraph",
            "olas_mech_subgraph",
            "olas_agents_subgraph",
            "polymarket_agents_subgraph",
            "open_markets_subgraph",
            "polymarket_bets_subgraph",
            "gnosis_staking_subgraph",
            "polygon_staking_subgraph",
        ):
            b.context.configure_mock(**{name: None})

        # Should not raise
        b.clean_up()


class TestFetchCTHeldPositionKeys:
    """Tests for ``_fetch_ct_held_position_keys`` error semantics.

    The error path must return ``None`` so the downstream consumer in
    :func:`compute_funds_locked_from_bets` can fall back to the
    un-gated FIFO sum. Returning ``set()`` would collapse every
    position out and write a phantom ``0.0`` to
    ``funds_locked_in_markets``.
    """

    @staticmethod
    def _strip_ct_subgraph(b: _ConcreteAPTBehaviour) -> None:
        """Make ``context.conditional_tokens_subgraph`` raise ``AttributeError``.

        ``MagicMock`` auto-creates attributes on access, so the
        production-side ``except AttributeError`` would never fire on a
        bare ``_make_behaviour()`` instance. We replace the context
        with a spec'd mock that lacks the attribute entirely.

        :param b: behaviour instance whose ``_context`` will be swapped
            for a class instance lacking ``conditional_tokens_subgraph``.
        """

        class _CtxWithoutCt:
            logger = MagicMock()
            params = MagicMock()
            # deliberately no ``conditional_tokens_subgraph`` attribute

        b._context = _CtxWithoutCt()  # type: ignore[assignment]

    def test_missing_ct_subgraph_returns_none(self) -> None:
        """No ``conditional_tokens_subgraph`` on context -> ``None``."""
        b = _make_behaviour()
        self._strip_ct_subgraph(b)

        result = _exhaust(b._fetch_ct_held_position_keys("0xsafe"))

        assert result is None

    def test_subgraph_request_failure_returns_none(self) -> None:
        """``_fetch_from_subgraph`` returning ``None`` -> ``None``."""
        b = _make_behaviour()
        b.context.conditional_tokens_subgraph = MagicMock()
        b._fetch_from_subgraph = _return_gen(None)  # type: ignore[method-assign]

        result = _exhaust(b._fetch_ct_held_position_keys("0xsafe"))

        assert result is None

    def test_empty_list_returns_empty_set(self) -> None:
        """Subgraph returns ``[]`` -> empty set (not ``None``).

        The CT subgraph spec extracts ``data:user:userPositions`` as a
        ``list`` (``response_type: list`` in
        ``trader_abci/skill.yaml``), so ``process_response`` returns
        the unwrapped list directly. An empty list distinguishes
        "user genuinely holds nothing" (gate everything out -> 0.0
        correctly) from "fetch error" (``None``, no gate, un-gated
        sum).
        """
        b = _make_behaviour()
        b.context.conditional_tokens_subgraph = MagicMock()
        b._fetch_from_subgraph = _return_gen([])  # type: ignore[method-assign]

        result = _exhaust(b._fetch_ct_held_position_keys("0xsafe"))

        assert result == set()

    def test_populated_positions_returns_keys(self) -> None:
        """Returns the ``(condition_id, outcome_index)`` tuple per held row.

        Receives the unwrapped ``userPositions`` list directly (not a
        nested ``{"user": {...}}`` dict) — matches what
        ``process_response`` produces given the spec's
        ``response_key: data:user:userPositions``.
        """
        b = _make_behaviour()
        b.context.conditional_tokens_subgraph = MagicMock()
        condition_a = "0x" + "a1" * 32
        # indexSet "1" -> outcome 0, indexSet "2" -> outcome 1.
        b._fetch_from_subgraph = _return_gen(  # type: ignore[method-assign]
            [
                {
                    "balance": "1000",
                    "id": "0xpos1",
                    "position": {
                        "conditionIds": [condition_a],
                        "indexSets": ["1"],
                    },
                },
                {
                    "balance": "500",
                    "id": "0xpos2",
                    "position": {
                        "conditionIds": [condition_a],
                        "indexSets": ["2"],
                    },
                },
            ]
        )

        result = _exhaust(b._fetch_ct_held_position_keys("0xsafe"))

        assert result == {(condition_a.lower(), 0), (condition_a.lower(), 1)}

    def test_query_filters_balance_gt_zero_server_side(self) -> None:
        """The CT query carries ``balance_gt: "0"`` so the result set stays small.

        Without the server-side filter the query returns every
        historical ``userPosition`` (including thousands of redeemed
        zero-balance rows on a long-lived trader safe). Page 1 fills
        up at 1000 rows, the loop then tries page 2 which is
        susceptible to transient subgraph failures — when that fails
        the fetcher returns ``None`` and the consumer falls back to
        the un-gated sum, surfacing the 110-wxDAI phantom-locked-funds
        regression.

        Filtering server-side keeps the response to actually-held
        positions only (~tens of rows) and fits in one page.
        """
        b = _make_behaviour()
        b.context.conditional_tokens_subgraph = MagicMock()
        captured: Dict[str, Any] = {}

        def fake_fetch(**kwargs: Any) -> Generator[None, None, Any]:
            captured["query"] = kwargs.get("query", "")
            return []
            yield  # pragma: no cover

        b._fetch_from_subgraph = fake_fetch  # type: ignore[method-assign,assignment]
        _exhaust(b._fetch_ct_held_position_keys("0xsafe"))

        assert 'balance_gt: "0"' in captured["query"], captured["query"]


# ---------------------------------------------------------------------------
# Mech-analytics flag-on tests: cover the async-HTTP paths on the
# behaviour helper (``_page_mech_analytics_scored_rows``) and the two
# consumers that route through it (``_fetch_all_mech_requests`` and
# ``_fetch_mech_requests_by_titles``). Without these, the flag-on
# branches would ship with zero unit coverage, which is exactly the
# ROI-affecting key-chain the reviewer flagged as a coverage gate hard
# fail.
# ---------------------------------------------------------------------------


def _http_response(status: int, body: Any) -> MagicMock:
    """Build a MagicMock that mirrors an Autonomy HttpMessage.

    The framework's ``get_http_response`` returns an object with
    ``.status_code`` and ``.body`` (bytes); the pagination helper reads
    both, so this fixture pins the same interface.

    :param status: HTTP status code the mock should report.
    :param body: response body; ``bytes`` are copied as-is, anything
        else is JSON-serialised.
    :return: MagicMock with ``.status_code`` and ``.body`` set.
    """
    resp = MagicMock()
    resp.status_code = status
    if isinstance(body, (bytes, bytearray)):
        resp.body = bytes(body)
    else:
        resp.body = json.dumps(body).encode()
    return resp


def _mech_analytics_ctx(is_polymarket: bool = False) -> MagicMock:
    """Context with params.mech_analytics_url + is_running_on_polymarket set."""
    ctx = MagicMock()
    ctx.params = SimpleNamespace(
        mech_analytics_url="https://mech-analytics.test",
        use_mech_analytics=True,
        is_running_on_polymarket=is_polymarket,
    )
    return ctx


def _queued_get_http_response(pages: List[MagicMock]) -> Any:
    """Return a fake ``get_http_response`` that pops one response per call.

    Each call yields once (matching the real generator contract) and
    returns the next queued response. Used to drive the pagination
    loop with a predictable sequence of pages / failures.

    :param pages: sequence of response mocks to serve, one per call.
    :return: a generator-factory suitable for monkey-patching onto a
        behaviour instance's ``get_http_response`` attribute.
    """
    queue = list(pages)

    def _gen(*args: Any, **kwargs: Any) -> "Generator[Any, Any, MagicMock]":
        yield
        if not queue:
            raise AssertionError(
                "get_http_response called more times than pages queued"
            )
        return queue.pop(0)

    return _gen


class TestPageMechAnalyticsScoredRows:
    """Async pagination helper on ``APTQueryingBehaviour``: failures return None."""

    def test_single_page_success(self) -> None:
        """Single-page response returns the rows as a list."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [_http_response(200, {"rows": [{"a": 1}, {"a": 2}], "next_cursor": None})]
        )
        result = _exhaust(b._page_mech_analytics_scored_rows(requester="0xsafe"))
        assert result == [{"a": 1}, {"a": 2}]

    def test_multi_page_concatenates_in_order(self) -> None:
        """Cursor is followed across pages, rows concatenated in order."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [
                _http_response(200, {"rows": [{"i": 1}], "next_cursor": "c1"}),
                _http_response(200, {"rows": [{"i": 2}], "next_cursor": "c2"}),
                _http_response(200, {"rows": [{"i": 3}], "next_cursor": None}),
            ]
        )
        result = _exhaust(b._page_mech_analytics_scored_rows(requester="0xsafe"))
        assert result == [{"i": 1}, {"i": 2}, {"i": 3}]

    def test_non_2xx_returns_none(self) -> None:
        """Non-200 response returns None (fetch failure, not empty)."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [_http_response(502, {})]
        )
        assert _exhaust(b._page_mech_analytics_scored_rows(requester="0xsafe")) is None

    def test_json_parse_failure_returns_none(self) -> None:
        """Malformed JSON body surfaces as None, not silent empty."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [_http_response(200, b"not json at all")]
        )
        assert _exhaust(b._page_mech_analytics_scored_rows(requester="0xsafe")) is None

    def test_shape_drift_missing_rows_returns_none(self) -> None:
        """Payload with no ``rows`` list MUST NOT be treated as empty."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [_http_response(200, {"detail": "server error"})]
        )
        assert _exhaust(b._page_mech_analytics_scored_rows(requester="0xsafe")) is None

    def test_mid_pagination_failure_returns_none(self) -> None:
        """Partial result from a mid-loop failure MUST be discarded."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [
                _http_response(200, {"rows": [{"i": 1}], "next_cursor": "c1"}),
                _http_response(502, {}),
            ]
        )
        assert _exhaust(b._page_mech_analytics_scored_rows(requester="0xsafe")) is None


class TestFetchAllMechRequestsFlagOn:
    """``_fetch_all_mech_requests`` flag-on branch — uses async pagination + adapter."""

    def test_flag_on_success_returns_subgraph_shaped_rows(self) -> None:
        """Successful fetch returns rows in the trader's subgraph shape."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [
                _http_response(
                    200,
                    {
                        "rows": [
                            {
                                "question_title": "Q1",
                                "requested_at": "2026-07-10T12:00:00+00:00",
                                "tool": "t",
                            }
                        ],
                        "next_cursor": None,
                    },
                )
            ]
        )
        result = _exhaust(b._fetch_all_mech_requests("0xsafe"))
        assert result is not None
        assert result[0]["parsedRequest"]["questionTitle"] == "Q1"

    def test_flag_on_failure_returns_none(self) -> None:
        """Fetch failure propagates as None (distinct from empty ``[]``)."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [_http_response(500, {})]
        )
        assert _exhaust(b._fetch_all_mech_requests("0xsafe")) is None


class TestFetchMechRequestsByTitlesFlagOn:
    """``_fetch_mech_requests_by_titles`` flag-on branch — client-side title filter."""

    def test_flag_on_filters_to_requested_titles_only(self) -> None:
        """Titles not in the caller's list are dropped from the result."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [
                _http_response(
                    200,
                    {
                        "rows": [
                            {
                                "question_title": "wanted",
                                "requested_at": "2026-07-10T00:00:00Z",
                            },
                            {
                                "question_title": "other",
                                "requested_at": "2026-07-10T00:00:00Z",
                            },
                        ],
                        "next_cursor": None,
                    },
                )
            ]
        )
        result = _exhaust(
            b._fetch_mech_requests_by_titles("0xsafe", question_titles=["wanted"])
        )
        assert result is not None
        assert len(result) == 1
        assert result[0]["parsedRequest"]["questionTitle"] == "wanted"

    def test_flag_on_empty_titles_short_circuits_without_fetch(self) -> None:
        """Empty title list means no work, no HTTP call."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = MagicMock()  # type: ignore[method-assign]  # would fail if called
        assert _exhaust(b._fetch_mech_requests_by_titles("0xsafe", [])) == []
        assert b.get_http_response.call_count == 0

    def test_flag_on_fetch_failure_returns_none(self) -> None:
        """Fetch failure propagates as None (distinct from empty list)."""
        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _queued_get_http_response(  # type: ignore[method-assign]
            [_http_response(503, {})]
        )
        assert _exhaust(b._fetch_mech_requests_by_titles("0xsafe", ["t"])) is None

    def test_flag_on_since_offsets_watermark_by_one_second(self) -> None:
        """``block_timestamp_gt`` is a row already consumed; ``since`` must skip it.

        The subgraph query uses ``blockTimestamp_gt`` (strictly greater
        than); mech-analytics' ``since`` is inclusive. Passing
        ``last_mech_timestamp`` straight through re-fetches the boundary
        row each tick, and the monotonic ``max(prev, new)`` aggregation
        would then never let the resulting overcount self-correct. The
        ``+1`` offset keeps the two backends semantically aligned.
        """
        watermark = 1_700_000_000
        captured: Dict[str, Any] = {}

        def _spy_get_http_response(*args: Any, **kwargs: Any) -> Any:
            captured.setdefault("url", kwargs.get("url"))
            yield
            return _http_response(200, {"rows": [], "next_cursor": None})

        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _spy_get_http_response  # type: ignore[method-assign]

        _exhaust(
            b._fetch_mech_requests_by_titles(
                "0xsafe",
                question_titles=["wanted"],
                block_timestamp_gt=watermark,
            )
        )

        expected_since = datetime.fromtimestamp(
            watermark + 1, tz=timezone.utc
        ).isoformat()
        # ``build_scored_rows_url`` URL-encodes the ISO string; unquote
        # for a substring check that's readable in case of failure.
        assert captured.get("url") is not None
        assert f"since={quote(expected_since, safe='')}" in captured["url"]

    def test_flag_on_no_watermark_sends_no_since_bound(self) -> None:
        """Backfill entry point (``block_timestamp_gt=0``) omits ``since`` entirely.

        Guards against a symmetric bug where always adding +1 would
        skip epoch on the initial backfill path.
        """
        captured: Dict[str, Any] = {}

        def _spy_get_http_response(*args: Any, **kwargs: Any) -> Any:
            captured.setdefault("url", kwargs.get("url"))
            yield
            return _http_response(200, {"rows": [], "next_cursor": None})

        b = _make_behaviour()
        b._context = _mech_analytics_ctx()
        b.get_http_response = _spy_get_http_response  # type: ignore[method-assign]

        _exhaust(
            b._fetch_mech_requests_by_titles(
                "0xsafe",
                question_titles=["wanted"],
                block_timestamp_gt=0,
            )
        )
        assert captured.get("url") is not None
        assert "since=" not in captured["url"]


# ---------------------------------------------------------------------------
# squid migration: trader agent unwrapping and profitParticipants hydration
# ---------------------------------------------------------------------------


class TestUnwrapTraderAgent:
    """Tests for the _unwrap_trader_agent helper."""

    def test_unwraps_the_graph_field_name(self) -> None:
        """A subgraph-shaped response unwraps through the traderAgent key."""
        assert _unwrap_trader_agent({"traderAgent": {"id": "0x1"}}) == {"id": "0x1"}

    def test_unwraps_squid_field_name(self) -> None:
        """A squid-shaped response unwraps through the traderAgentById key."""
        assert _unwrap_trader_agent({"traderAgentById": {"id": "0x2"}}) == {"id": "0x2"}

    def test_prefers_the_graph_key_when_both_present(self) -> None:
        """The Graph spelling wins when a response carries both keys."""
        result = _unwrap_trader_agent(
            {"traderAgent": {"id": "0x1"}, "traderAgentById": {"id": "0x2"}}
        )
        assert result == {"id": "0x1"}

    def test_returns_unwrapped_payload_untouched(self) -> None:
        """An already-unwrapped payload passes straight through."""
        payload: Dict[str, Any] = {"dailyProfitStatistics": []}
        assert _unwrap_trader_agent(payload) is payload

    def test_returns_falsy_untouched(self) -> None:
        """Falsy inputs are returned as-is."""
        assert _unwrap_trader_agent(None) is None
        assert _unwrap_trader_agent({}) == {}

    def test_non_dict_passes_through(self) -> None:
        """The runtime isinstance guard holds even though no caller can hit it."""
        assert _unwrap_trader_agent([1, 2]) == [1, 2]  # type: ignore[arg-type]


class TestHydrateProfitParticipants:
    """Tests for _hydrate_profit_participants (squid conditionId rehydration)."""

    AGENT = "0xagent"

    @staticmethod
    def _setup(b: _ConcreteAPTBehaviour, responses: list) -> MagicMock:  # type: ignore[type-arg]
        """Wire polymarket_questions_subgraph to return *responses* in order."""
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.process_response.side_effect = list(responses)
        b.context.polymarket_questions_subgraph = mock_sg
        b.sent_contents = []  # type: ignore[attr-defined]
        b.get_http_response = _recording_gen(b.sent_contents)  # type: ignore[method-assign,attr-defined]
        return mock_sg

    def test_no_participants_skips_the_fetch(self) -> None:
        """With no conditionIds there is nothing to hydrate and no request."""
        b = _make_behaviour()
        mock_sg = self._setup(b, [])
        stats = [{"date": "1", "profitParticipants": []}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        mock_sg.process_response.assert_not_called()

    def test_replaces_condition_ids_with_question_objects(self) -> None:
        """Each conditionId string is spliced out for its question object."""
        b = _make_behaviour()
        question = {
            "id": "0xaaa",
            "questionId": "0xq",
            "metadata": {"title": "Will it rain?"},
            "bets": [{"blockTimestamp": "1700000000"}],
        }
        self._setup(b, [[question]])
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        assert stats[0]["profitParticipants"] == [question]
        sent = json.loads(b.sent_contents[-1])  # type: ignore[attr-defined]
        assert sent["variables"]["bettorId"] == self.AGENT

    def test_drops_condition_ids_the_squid_does_not_know(self) -> None:
        """An unresolvable conditionId is dropped rather than kept as a string."""
        b = _make_behaviour()
        question = {
            "id": "0xaaa",
            "metadata": {"title": "t"},
            "bets": [{"blockTimestamp": "1"}],
        }
        self._setup(b, [[question]])
        stats = [{"date": "1", "profitParticipants": ["0xaaa", "0xmissing"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        assert stats[0]["profitParticipants"] == [question]
        b.context.logger.warning.assert_called_once()
        warning = b.context.logger.warning.call_args[0][0]
        assert "1/2 profit participants had no matching question" in warning

    def test_question_without_id_is_ignored(self) -> None:
        """A row missing an id cannot be joined on and is skipped."""
        b = _make_behaviour()
        self._setup(b, [[{"metadata": {"title": "no id"}}]])
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        assert stats[0]["profitParticipants"] == []

    def test_warns_when_no_resolved_question_carries_bets(self) -> None:
        """A bettorId that stops matching resolves questions but returns no bets."""
        b = _make_behaviour()
        self._setup(b, [[{"id": "0xaaa", "metadata": {"title": "t"}, "bets": []}]])
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        warning = b.context.logger.warning.call_args[0][0]
        assert "1/1 resolved profit participants carry no bets" in warning

    def test_warns_for_the_subset_of_questions_without_bets(self) -> None:
        """One still-working question must not silence the degraded ones."""
        b = _make_behaviour()
        self._setup(
            b,
            [
                [
                    {
                        "id": "0xaaa",
                        "metadata": {"title": "a"},
                        "bets": [{"blockTimestamp": "1"}],
                    },
                    {"id": "0xbbb", "metadata": {"title": "b"}, "bets": []},
                ]
            ],
        )
        stats = [{"date": "1", "profitParticipants": ["0xaaa", "0xbbb"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        warning = b.context.logger.warning.call_args[0][0]
        assert "1/2 resolved profit participants carry no bets" in warning

    def test_quiet_when_every_question_carries_bets(self) -> None:
        """The healthy case: every resolved participant has at least one bet."""
        b = _make_behaviour()
        self._setup(
            b,
            [
                [
                    {
                        "id": "0xaaa",
                        "metadata": {"title": "t"},
                        "bets": [{"blockTimestamp": "1"}],
                    }
                ]
            ],
        )
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        b.context.logger.warning.assert_not_called()

    def test_fetch_failure_propagates_none(self) -> None:
        """A failed question fetch aborts instead of silently losing titles."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg = self._setup(b, [None])
        mock_sg.api_id = "polymarket_questions"
        mock_sg.retries_info.suggested_sleep_time = 1.0
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is False
        assert stats[0]["profitParticipants"] == ["0xaaa"]

    def test_non_string_participants_are_ignored(self) -> None:
        """Already-hydrated participants do not trigger a second fetch."""
        b = _make_behaviour()
        mock_sg = self._setup(b, [])
        stats = [{"date": "1", "profitParticipants": [{"id": "0xaaa"}]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        mock_sg.process_response.assert_not_called()

    def test_mixed_string_and_dict_participants(self) -> None:
        """A partly pre-hydrated list splices the strings and keeps the dicts.

        A dict is unhashable, so reaching the ``questions_by_id`` lookup with one
        raises ``TypeError`` and aborts the whole statistics fetch.
        """
        b = _make_behaviour()
        pre_hydrated = {"id": "0xbbb", "metadata": {"title": "b"}}
        question = {
            "id": "0xaaa",
            "metadata": {"title": "a"},
            "bets": [{"blockTimestamp": "1"}],
        }
        self._setup(b, [[question]])
        stats = [{"date": "1", "profitParticipants": ["0xaaa", pre_hydrated]}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        assert stats[0]["profitParticipants"] == [question, pre_hydrated]

    def test_batches_condition_ids_at_the_query_batch_size(self) -> None:
        """More ids than one batch are fetched over multiple requests."""
        b = _make_behaviour()
        total = QUERY_BATCH_SIZE + 5
        ids = [f"0x{i:064x}" for i in range(total)]
        ordered = sorted(ids)
        first = [
            {"id": i, "metadata": {"title": i}} for i in ordered[:QUERY_BATCH_SIZE]
        ]
        second = [
            {"id": i, "metadata": {"title": i}} for i in ordered[QUERY_BATCH_SIZE:]
        ]
        mock_sg = self._setup(b, [first, second])
        stats = [{"date": "1", "profitParticipants": ids}]

        assert _exhaust(b._hydrate_profit_participants(stats, self.AGENT)) is True
        assert mock_sg.process_response.call_count == 2
        assert len(stats[0]["profitParticipants"]) == total


class TestFetchDailyProfitStatisticsHydration:
    """_fetch_daily_profit_statistics wires hydration on the Polymarket path."""

    @staticmethod
    def _behaviour(pages: list, questions: Any) -> _ConcreteAPTBehaviour:  # type: ignore[type-arg]
        """Build a behaviour serving *pages* of daily stats, then *questions*."""
        b = _make_behaviour()
        b.context.params.is_running_on_polymarket = True

        agents_sg = MagicMock()
        agents_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        agents_sg.is_retries_exceeded.return_value = False
        agents_sg.process_response.side_effect = [
            {"dailyProfitStatistics": page} for page in pages
        ]
        b.context.polymarket_agents_subgraph = agents_sg

        questions_sg = MagicMock()
        questions_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        questions_sg.is_retries_exceeded.return_value = False
        questions_sg.process_response.side_effect = [questions]
        questions_sg.api_id = "polymarket_questions"
        questions_sg.retries_info.suggested_sleep_time = 1.0
        b.context.polymarket_questions_subgraph = questions_sg

        b.sent_contents = []  # type: ignore[attr-defined]
        b.get_http_response = _recording_gen(b.sent_contents)  # type: ignore[method-assign,attr-defined]
        b.sleep = _noop_gen  # type: ignore[method-assign]
        return b

    def test_page_is_hydrated(self) -> None:
        """Every conditionId on a Polymarket page is hydrated before returning."""
        question = {"id": "0xaaa", "metadata": {"title": "Will it rain?"}}
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]
        b = self._behaviour([stats], [question])

        result = _exhaust(b._fetch_daily_profit_statistics("0xAgEnT", 1000))

        assert result is not None
        assert result[0]["profitParticipants"] == [question]

    def test_wrapped_page_is_unwrapped_then_hydrated(self) -> None:
        """A response that still carries the traderAgentById wrapper works too."""
        question = {"id": "0xaaa", "metadata": {"title": "Will it rain?"}}
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]
        b = self._behaviour([[]], [question])
        b.context.polymarket_agents_subgraph.process_response.side_effect = [
            {"traderAgentById": {"dailyProfitStatistics": stats}}
        ]

        result = _exhaust(b._fetch_daily_profit_statistics("0xagent", 1000))

        assert result is not None
        assert result[0]["profitParticipants"] == [question]

    def test_participants_hydrate_across_every_page(self) -> None:
        """Hydration covers the union of all pages, not just the last one."""
        first_page = [
            {"date": str(i), "profitParticipants": []} for i in range(QUERY_BATCH_SIZE)
        ]
        first_page[0]["profitParticipants"] = ["0xaaa"]
        second_page = [{"date": "last", "profitParticipants": ["0xbbb"]}]
        q_a = {"id": "0xaaa", "metadata": {"title": "first page"}}
        q_b = {"id": "0xbbb", "metadata": {"title": "second page"}}
        b = self._behaviour([first_page, second_page], [q_a, q_b])

        result = _exhaust(b._fetch_daily_profit_statistics("0xagent", 1000))

        assert result is not None
        assert len(result) == QUERY_BATCH_SIZE + 1
        assert result[0]["profitParticipants"] == [q_a]
        assert result[-1]["profitParticipants"] == [q_b]

    def test_bettor_id_is_lowercased_agent_address(self) -> None:
        """The questions query is scoped to this agent's bets."""
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]
        b = self._behaviour([stats], [{"id": "0xaaa", "metadata": {"title": "t"}}])

        _exhaust(b._fetch_daily_profit_statistics("0xAgEnT", 1000))

        sent = json.loads(b.sent_contents[-1])  # type: ignore[attr-defined]
        assert sent["variables"]["bettorId"] == "0xagent"

    def test_empty_page_stops_pagination(self) -> None:
        """An empty (but not ``None``) page ends pagination cleanly."""
        b = self._behaviour([[]], [])
        b.context.polymarket_agents_subgraph.process_response.side_effect = [{}]

        assert _exhaust(b._fetch_daily_profit_statistics("0xagent", 1000)) == []

    def test_hydration_failure_aborts_the_fetch(self) -> None:
        """A hydration failure returns ``None`` so the rebuild can retry."""
        stats = [{"date": "1", "profitParticipants": ["0xaaa"]}]
        b = self._behaviour([stats], None)

        assert _exhaust(b._fetch_daily_profit_statistics("0xagent", 1000)) is None
