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
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.requests import (
    APTQueryingBehaviour,
    DECIMAL_SCALING_FACTOR,
    FetchStatus,
    MAX_LOG_SIZE,
    OLAS_TOKEN_ADDRESS,
    QUERY_BATCH_SIZE,
    QUESTION_DATA_SEPARATOR,
    USD_PRICE_FIELD,
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


def _exhaust(gen: Generator) -> Any:
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
        b.context.polymarket_bets_subgraph = mock_sg

        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_trader_agent_bets("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result is None


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

    def test_empty_result(self) -> None:
        """When fetch returns None, returns empty list."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_agents_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_daily_profit_statistics("0xagent", 1000)
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

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

    def test_empty_result(self) -> None:
        """When fetch returns None, returns empty list."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_all_mech_requests("0xagent")
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

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

    def test_none_result(self) -> None:
        """When fetch returns None, returns empty list."""
        b = _make_behaviour()
        b.sleep = _noop_gen  # type: ignore[method-assign]
        b.context.params.is_running_on_polymarket = False

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {"method": "POST", "url": "http://test"}
        mock_sg.process_response.return_value = None
        mock_sg.api_id = "test"
        mock_sg.is_retries_exceeded.return_value = False
        b.context.olas_mech_subgraph = mock_sg
        b.get_http_response = _return_gen(MagicMock())  # type: ignore[method-assign]

        gen = b._fetch_mech_requests_by_titles("0xagent", ["q1"])
        result = _exhaust(gen)  # type: ignore[arg-type]

        assert result == []

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
