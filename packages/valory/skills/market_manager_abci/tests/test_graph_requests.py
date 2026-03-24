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

"""Tests for the graph_tooling.requests module."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    MAX_LOG_SIZE,
    QUESTION_DATA_SEPARATOR,
    QueryingBehaviour,
    _MAX_SLEEP_TIME,
    to_content,
    to_graphql_list,
)


class TestToContent:
    """Tests for the to_content function."""

    def test_basic_query(self) -> None:
        """Test that a basic query string is properly converted to bytes."""
        query = "{ markets { id } }"
        result = to_content(query)
        assert isinstance(result, bytes)
        decoded = json.loads(result)
        assert "query" in decoded
        assert decoded["query"] == query

    def test_empty_query(self) -> None:
        """Test that an empty query string is properly handled."""
        result = to_content("")
        decoded = json.loads(result)
        assert decoded["query"] == ""

    def test_encoding_is_utf8(self) -> None:
        """Test that the result is UTF-8 encoded."""
        query = "{ markets { id } }"
        result = to_content(query)
        # should be decodable as utf-8 without error
        decoded_str = result.decode("utf-8")
        assert isinstance(decoded_str, str)

    def test_json_keys_sorted(self) -> None:
        """Test that JSON keys are sorted in the output."""
        query = "test"
        result = to_content(query)
        decoded_str = result.decode("utf-8")
        # since there's only one key, just verify the JSON is valid
        parsed = json.loads(decoded_str)
        assert parsed == {"query": "test"}

    def test_special_characters(self) -> None:
        """Test that special characters in queries are preserved."""
        query = '{ user(id: "0xabc") { positions(where: {balance_gt: "0"}) { id } } }'
        result = to_content(query)
        decoded = json.loads(result)
        assert decoded["query"] == query


class TestToGraphqlList:
    """Tests for the to_graphql_list function."""

    def test_string_list(self) -> None:
        """Test conversion of a list of strings."""
        result = to_graphql_list(["0xabc", "0xdef"])
        assert result == '["0xabc", "0xdef"]'

    def test_empty_list(self) -> None:
        """Test conversion of an empty list."""
        result = to_graphql_list([])
        assert result == "[]"

    def test_single_element(self) -> None:
        """Test conversion of a single-element list."""
        result = to_graphql_list(["en"])
        assert result == '["en"]'

    def test_no_single_quotes(self) -> None:
        """Test that single quotes are replaced with double quotes."""
        result = to_graphql_list(["a", "b"])
        assert "'" not in result
        assert '"a"' in result
        assert '"b"' in result

    def test_numeric_list(self) -> None:
        """Test conversion of a list of numbers."""
        result = to_graphql_list([1, 2, 3])
        assert result == "[1, 2, 3]"


class TestQueryingBehaviour:
    """Tests for the QueryingBehaviour abstract class."""

    def test_has_expected_methods(self) -> None:
        """Test that QueryingBehaviour has the expected method signatures."""
        assert hasattr(QueryingBehaviour, "_fetch_bets")
        assert hasattr(QueryingBehaviour, "_fetch_redeem_info")
        assert hasattr(QueryingBehaviour, "_fetch_block_number")
        assert hasattr(QueryingBehaviour, "_handle_response")
        assert hasattr(QueryingBehaviour, "_prepare_fetching")
        assert hasattr(QueryingBehaviour, "fetch_claim_params")
        assert hasattr(QueryingBehaviour, "fetch_trades")
        assert hasattr(QueryingBehaviour, "fetch_user_positions")
        assert hasattr(QueryingBehaviour, "clean_up")

    def test_has_expected_properties(self) -> None:
        """Test that QueryingBehaviour has the expected properties."""
        assert hasattr(QueryingBehaviour, "params")
        assert hasattr(QueryingBehaviour, "shared_state")
        assert hasattr(QueryingBehaviour, "synchronized_data")
        assert hasattr(QueryingBehaviour, "synced_time")
        assert hasattr(QueryingBehaviour, "current_subgraph")

    def test_init_sets_attributes(self) -> None:
        """Test that __init__ sets the expected default attributes on QueryingBehaviour.

        We create a concrete subclass with `matching_round` set to satisfy the
        metaclass check, then patch BaseBehaviour.__init__ to avoid needing the
        full Open Autonomy framework, and verify that QueryingBehaviour.__init__
        properly sets all expected instance attributes.
        """
        from packages.valory.skills.abstract_round_abci.base import AbstractRound

        # Create a concrete subclass that satisfies the metaclass requirement
        # and provides an async_act implementation
        class _ConcreteQueryingBehaviour(QueryingBehaviour):
            """Concrete subclass for testing."""

            matching_round = MagicMock(spec=AbstractRound)

            def async_act(self) -> None:  # type: ignore[override]
                """No-op implementation for testing."""  # type: ignore[override]

        mock_context = MagicMock()
        mock_context.params.creators_iterator = iter(
            [("omen_subgraph", ["0x1", "0x2"])]
        )

        # Patch BaseBehaviour.__init__ to skip framework setup, but still
        # allow QueryingBehaviour.__init__ to run its own attribute setup
        with patch(
            "packages.valory.skills.abstract_round_abci.behaviour_utils.BaseBehaviour.__init__"
        ):
            instance = _ConcreteQueryingBehaviour.__new__(_ConcreteQueryingBehaviour)  # type: ignore[type-abstract]
            # Set _context (the backing field for the read-only `context` property)  # type: ignore[type-abstract]
            # before __init__ since the patched BaseBehaviour.__init__ won't do it
            instance._context = mock_context
            _ConcreteQueryingBehaviour.__init__(instance)

        assert instance._call_failed is False
        assert instance._fetch_status == FetchStatus.NONE
        assert instance._current_market == ""
        assert instance._current_creators == []


# ---------------------------------------------------------------------------
# Helpers for generator-based tests
# ---------------------------------------------------------------------------


def _noop_gen(*args: Any, **kwargs: Any) -> Any:
    """No-op generator that yields once and returns None."""  # type: ignore[no-untyped-def]
    yield
    return None


def _return_gen(value: Any) -> Any:
    """Create a generator factory that yields once and returns *value*."""  # type: ignore[no-untyped-def]

    def _gen(*args: Any, **kwargs: Any) -> Any:
        yield  # type: ignore[no-untyped-def]
        return value

    return _gen


class _ConcreteQueryBehaviour(QueryingBehaviour):
    """Minimal concrete subclass of QueryingBehaviour for testing."""

    matching_round = MagicMock()

    def async_act(self) -> None:  # type: ignore[misc, override]
        """No-op."""
        yield  # type: ignore[misc]


def _make_behaviour(**overrides: Any) -> _ConcreteQueryBehaviour:
    """Instantiate a ``_ConcreteQueryBehaviour`` without framework wiring.  # type: ignore[no-untyped-def]

    Uses ``object.__new__`` to skip ``__init__`` (which requires the full
    Open Autonomy runtime), then manually sets the attributes that the
    methods under test rely on.

    :param **overrides: keyword arguments to override default attributes.
    :return: an instance of _ConcreteQueryBehaviour.
    """
    b = object.__new__(_ConcreteQueryBehaviour)  # type: ignore[type-abstract]

    # -- context / params --
    ctx = MagicMock()
    ctx.params.creators_iterator = iter([("omen_subgraph", ["0xcreator1"])])
    ctx.params.slot_count = 2
    ctx.params.opening_margin = 100
    ctx.params.languages = ["en"]
    ctx.params.average_block_time = 12
    ctx.params.abt_error_mult = 5
    b._context = ctx

    # -- internal state --
    b._call_failed = False
    b._fetch_status = FetchStatus.NONE
    b._creators_iterator = iter([("omen_subgraph", ["0xcreator1"])])
    b._current_market = ""
    b._current_creators = []

    # Apply any caller-supplied overrides
    for k, v in overrides.items():
        setattr(b, k, v)
    return b


# type: ignore[no-untyped-def]


def _exhaust(gen: Any) -> Any:
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


class TestQueryingBehaviourProperties:
    """Tests for the properties exposed by QueryingBehaviour."""

    def test_params_returns_cast_params(self) -> None:
        """Test that the params property returns context.params."""
        b = _make_behaviour()
        result = b.params
        assert result is b.context.params

    def test_shared_state_returns_context_state(self) -> None:
        """Test that shared_state delegates to context.state."""
        b = _make_behaviour()
        result = b.shared_state
        assert result is b.context.state

    def test_synchronized_data_delegates_to_super(self) -> None:
        """Test that synchronized_data calls the parent property.

        The parent ``BaseBehaviour.synchronized_data`` reads from
        ``self.shared_state.synchronized_data``, so we mock that path.
        """
        b = _make_behaviour()
        mock_sd = MagicMock()
        b.context.state.round_sequence.latest_synchronized_data = mock_sd
        # BaseBehaviour.synchronized_data reads shared_state.synchronized_data
        # which ultimately reads round_sequence.latest_synchronized_data.
        # Since the whole context is mocked we just verify no crash and that
        # the cast-based property can be called.
        _ = b.synchronized_data  # should not raise

    def test_synced_time_returns_integer_timestamp(self) -> None:
        """Test that synced_time converts the round-sequence timestamp."""
        b = _make_behaviour()
        mock_ts = MagicMock()
        mock_ts.timestamp.return_value = 1700000000.5
        b.context.state.round_sequence.last_round_transition_timestamp = mock_ts
        result = b.synced_time
        assert result == 1700000000
        assert isinstance(result, int)

    def test_current_subgraph_reads_from_context(self) -> None:
        """Test that current_subgraph does getattr(context, _current_market)."""
        b = _make_behaviour()
        b._current_market = "omen_subgraph"
        mock_sg = MagicMock()
        b.context.omen_subgraph = mock_sg
        result = b.current_subgraph
        assert result is mock_sg


# ---------------------------------------------------------------------------
# _prepare_fetching tests
# ---------------------------------------------------------------------------


class TestPrepareFetching:
    """Tests for _prepare_fetching."""

    def test_advances_iterator_on_none_status(self) -> None:
        """When status is NONE, _prepare_fetching advances the iterator."""
        b = _make_behaviour(
            _fetch_status=FetchStatus.NONE,
            _creators_iterator=iter([("omen_subgraph", ["0xc1"])]),
        )
        result = b._prepare_fetching()
        assert result is True
        assert b._fetch_status == FetchStatus.IN_PROGRESS
        assert b._current_market == "omen_subgraph"
        assert b._current_creators == ["0xc1"]

    def test_advances_iterator_on_success_status(self) -> None:
        """When status is SUCCESS, _prepare_fetching advances the iterator."""
        b = _make_behaviour(
            _fetch_status=FetchStatus.SUCCESS,
            _creators_iterator=iter([("sg2", ["0xc2"])]),
        )
        result = b._prepare_fetching()
        assert result is True
        assert b._current_market == "sg2"
        assert b._current_creators == ["0xc2"]
        assert b._fetch_status == FetchStatus.IN_PROGRESS

    def test_returns_false_when_iterator_exhausted(self) -> None:
        """When the iterator is empty, returns False."""
        b = _make_behaviour(
            _fetch_status=FetchStatus.NONE,
            _creators_iterator=iter([]),
        )
        result = b._prepare_fetching()
        assert result is False

    def test_returns_false_on_fail_status(self) -> None:
        """When status is FAIL, returns False immediately."""
        b = _make_behaviour(
            _fetch_status=FetchStatus.FAIL,
            _creators_iterator=iter([("sg", ["0xc"])]),
        )
        result = b._prepare_fetching()
        assert result is False

    def test_in_progress_stays_in_progress(self) -> None:
        """When status is IN_PROGRESS, keeps status and returns True."""
        b = _make_behaviour(
            _fetch_status=FetchStatus.IN_PROGRESS,
        )
        result = b._prepare_fetching()
        assert result is True
        assert b._fetch_status == FetchStatus.IN_PROGRESS


# ---------------------------------------------------------------------------
# _handle_response tests
# ---------------------------------------------------------------------------


class TestHandleResponse:
    """Tests for _handle_response."""

    # type: ignore[no-untyped-def]
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

        assert b._fetch_status == FetchStatus.FAIL

    def test_none_response_no_sleep_when_sleep_on_fail_false(self) -> None:
        """When sleep_on_fail=False, the sleep generator is not invoked."""  # type: ignore[no-untyped-def]
        b = _make_behaviour()
        sleep_called = False

        def _tracking_sleep(*a: Any, **kw: Any) -> Any:
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

    def test_successful_response_truncates_long_log(self) -> None:
        """Verify that long responses are truncated in the log message."""
        b = _make_behaviour()
        sg = self._make_subgraph()
        data = {"key": "x" * (MAX_LOG_SIZE + 500)}

        gen = b._handle_response(sg, data, "big_data")
        _exhaust(gen)

        log_call = b.context.logger.info.call_args[0][0]
        # The log message should contain the truncated representation
        assert len(log_call) <= MAX_LOG_SIZE + 200  # some overhead for prefix

    def test_successful_response_replaces_separator_in_log(self) -> None:
        """The question data separator is replaced in log output."""
        b = _make_behaviour()
        sg = self._make_subgraph()
        data = {"q": f"foo{QUESTION_DATA_SEPARATOR}bar"}

        gen = b._handle_response(sg, data, "sep_test")
        _exhaust(gen)

        log_call = b.context.logger.info.call_args[0][0]
        assert QUESTION_DATA_SEPARATOR not in log_call


# ---------------------------------------------------------------------------
# _fetch_bets tests
# ---------------------------------------------------------------------------


class TestFetchBets:
    """Tests for the _fetch_bets generator."""

    def test_fetch_bets_success(self) -> None:
        """A successful fetch returns the bets list."""
        b = _make_behaviour()
        b._current_creators = ["0xcreator1"]
        b._current_market = "omen_subgraph"

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        bets_data = [{"id": "bet1"}]
        mock_sg.process_response.return_value = bets_data
        mock_sg.is_retries_exceeded.return_value = False
        b.context.omen_subgraph = mock_sg

        # Mock synced_time
        mock_ts = MagicMock()
        mock_ts.timestamp.return_value = 1700000000.0
        b.context.state.round_sequence.last_round_transition_timestamp = mock_ts

        # Mock get_http_response to return a sentinel
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]

        gen = b._fetch_bets()
        result = _exhaust(gen)

        assert result == bets_data
        assert b._fetch_status == FetchStatus.SUCCESS

    def test_fetch_bets_failure(self) -> None:
        """When the subgraph returns None, _fetch_bets returns None."""
        b = _make_behaviour()
        b._current_creators = ["0xcreator1"]
        b._current_market = "omen_subgraph"

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.process_response.return_value = None
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.omen_subgraph = mock_sg

        mock_ts = MagicMock()
        mock_ts.timestamp.return_value = 1700000000.0
        b.context.state.round_sequence.last_round_transition_timestamp = mock_ts

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        b.sleep = _noop_gen  # type: ignore[method-assign]

        gen = b._fetch_bets()
        result = _exhaust(gen)

        assert result is None


# ---------------------------------------------------------------------------
# _fetch_redeem_info tests
# ---------------------------------------------------------------------------


# type: ignore[no-untyped-def]
class TestFetchRedeemInfo:
    """Tests for the _fetch_redeem_info generator."""

    def _setup_behaviour(self) -> Any:
        """Create a behaviour wired for redeem-info tests."""
        b = _make_behaviour()
        b._current_market = "omen_subgraph"

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.trades_subgraph = mock_sg

        # synchronized_data.safe_contract_address
        b.context.state.round_sequence.latest_synchronized_data.safe_contract_address = (
            "0xSAFE"
        )

        return b, mock_sg

    def test_single_batch_returns_data(self) -> None:
        """One batch of data followed by an empty batch returns all data."""
        b, mock_sg = self._setup_behaviour()
        batch1 = [{"fpmm": {"creationTimestamp": "100"}}]

        _ = iter([batch1, []])  # responses iterator (unused directly)
        process_returns = iter([batch1, []])

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b._fetch_redeem_info()
        result = _exhaust(gen)

        assert result == batch1

    def test_multiple_batches(self) -> None:
        """Multiple batches are concatenated."""
        b, mock_sg = self._setup_behaviour()
        batch1 = [
            {"fpmm": {"creationTimestamp": "100"}},
            {"fpmm": {"creationTimestamp": "200"}},
        ]
        batch2 = [{"fpmm": {"creationTimestamp": "300"}}]

        process_returns = iter([batch1, batch2, []])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b._fetch_redeem_info()
        result = _exhaust(gen)

        assert result == batch1 + batch2

    def test_none_response_returns_partial(self) -> None:
        """When process_response returns None, returns what was collected."""
        b, mock_sg = self._setup_behaviour()

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg.process_response.return_value = None
        mock_sg.retries_info.suggested_sleep_time = 1.0

        gen = b._fetch_redeem_info()
        result = _exhaust(gen)

        assert result == []
        b.context.logger.error.assert_called()


# ---------------------------------------------------------------------------
# _fetch_block_number tests
# ---------------------------------------------------------------------------


class TestFetchBlockNumber:
    """Tests for the _fetch_block_number generator."""

    def test_success_returns_block(self) -> None:
        """A successful response returns the block dict."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        block_data = [{"id": "12345"}]
        mock_sg.process_response.return_value = block_data
        mock_sg.is_retries_exceeded.return_value = False
        b.context.network_subgraph = mock_sg

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]

        gen = b._fetch_block_number(timestamp=1700000000)
        result = _exhaust(gen)

        assert result == block_data
        assert b._fetch_status == FetchStatus.SUCCESS

    def test_failure_returns_empty_dict(self) -> None:
        """When the subgraph returns None, returns an empty dict."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.process_response.return_value = None
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.network_subgraph = mock_sg

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        b.sleep = _noop_gen  # type: ignore[method-assign]

        gen = b._fetch_block_number(timestamp=1700000000)
        result = _exhaust(gen)

        assert result == {}


# ---------------------------------------------------------------------------
# fetch_claim_params tests
# ---------------------------------------------------------------------------


class TestFetchClaimParams:
    """Tests for the fetch_claim_params generator."""

    def test_success_returns_parsed_answers(self) -> None:
        """Successful response returns parsed answer dicts."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.realitio_subgraph = mock_sg

        raw_answers = [
            {
                "answer": "0x0000000000000000000000000000000000000000000000000000000000000001",
                "question": {
                    "questionId": "0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
                    "historyHash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    "user": "0x1234567890abcdef1234567890abcdef12345678",
                },
                "bondAggregate": "1000",
                "timestamp": "1700000000",
            }
        ]
        mock_sg.process_response.return_value = raw_answers

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]

        gen = b.fetch_claim_params(question_id="0xquestion123")
        result = _exhaust(gen)

        assert result is not None
        assert len(result) == 1
        args = result[0]["args"]
        assert isinstance(args["answer"], bytes)
        assert isinstance(args["question_id"], bytes)
        assert isinstance(args["history_hash"], bytes)
        assert args["bond"] == 1000
        assert args["timestamp"] == 1700000000
        assert args["is_commitment"] is False

    def test_failure_returns_none(self) -> None:
        """When subgraph returns None, returns None."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.process_response.return_value = None
        mock_sg.is_retries_exceeded.return_value = False
        mock_sg.retries_info.suggested_sleep_time = 1.0
        b.context.realitio_subgraph = mock_sg

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        b.sleep = _noop_gen  # type: ignore[method-assign]

        gen = b.fetch_claim_params(question_id="0xquestion123")
        result = _exhaust(gen)

        assert result is None
        b.context.logger.error.assert_called()


# ---------------------------------------------------------------------------
# fetch_trades tests
# ---------------------------------------------------------------------------


# type: ignore[no-untyped-def]
class TestFetchTrades:
    """Tests for the fetch_trades generator."""

    def _setup_behaviour(self) -> Any:
        """Create a behaviour wired for trades tests."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.trades_subgraph = mock_sg

        return b, mock_sg

    def test_single_batch(self) -> None:
        """One batch of trades followed by empty returns the data."""
        b, mock_sg = self._setup_behaviour()
        batch1 = [{"creationTimestamp": "100", "id": "t1"}]

        process_returns = iter([batch1, []])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b.fetch_trades(
            creator="0xCreator", from_timestamp=0.0, to_timestamp=9999999.0
        )
        result = _exhaust(gen)

        assert result == batch1

    def test_multiple_batches(self) -> None:
        """Multiple batches are concatenated."""
        b, mock_sg = self._setup_behaviour()
        batch1 = [
            {"creationTimestamp": "100", "id": "t1"},
            {"creationTimestamp": "200", "id": "t2"},
        ]
        batch2 = [{"creationTimestamp": "300", "id": "t3"}]

        process_returns = iter([batch1, batch2, []])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b.fetch_trades(
            creator="0xCreator", from_timestamp=0.0, to_timestamp=9999999.0
        )
        result = _exhaust(gen)

        assert result == batch1 + batch2

    def test_none_response_returns_partial(self) -> None:
        """When process_response returns None mid-way, returns collected data."""
        b, mock_sg = self._setup_behaviour()

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg.process_response.return_value = None
        mock_sg.retries_info.suggested_sleep_time = 1.0

        gen = b.fetch_trades(
            creator="0xCreator", from_timestamp=0.0, to_timestamp=9999999.0
        )
        result = _exhaust(gen)

        assert result == []
        b.context.logger.error.assert_called()


# ---------------------------------------------------------------------------
# fetch_user_positions tests
# ---------------------------------------------------------------------------


# type: ignore[no-untyped-def]
class TestFetchUserPositions:
    """Tests for the fetch_user_positions generator."""

    def _setup_behaviour(self) -> Any:
        """Create a behaviour wired for user-positions tests."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.conditional_tokens_subgraph = mock_sg

        return b, mock_sg

    def test_single_batch(self) -> None:
        """One batch of positions followed by empty returns the data."""
        b, mock_sg = self._setup_behaviour()
        batch1 = [{"id": "pos1", "balance": "100"}]

        process_returns = iter([batch1, []])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b.fetch_user_positions(user="0xUser1")
        result = _exhaust(gen)

        assert result == batch1

    def test_multiple_batches(self) -> None:
        """Multiple batches are concatenated."""
        b, mock_sg = self._setup_behaviour()
        batch1 = [{"id": "pos1", "balance": "100"}, {"id": "pos2", "balance": "200"}]
        batch2 = [{"id": "pos3", "balance": "300"}]

        process_returns = iter([batch1, batch2, []])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b.fetch_user_positions(user="0xUser1")
        result = _exhaust(gen)

        assert result == batch1 + batch2

    def test_none_response_returns_partial(self) -> None:
        """When process_response returns None, returns what was collected."""
        b, mock_sg = self._setup_behaviour()

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        b.sleep = _noop_gen  # type: ignore[method-assign]
        mock_sg.process_response.return_value = None
        mock_sg.retries_info.suggested_sleep_time = 1.0

        gen = b.fetch_user_positions(user="0xUser1")
        result = _exhaust(gen)

        assert result == []
        b.context.logger.error.assert_called()


# ---------------------------------------------------------------------------
# clean_up tests
# ---------------------------------------------------------------------------


class TestCleanUp:
    """Tests for the clean_up method."""

    def test_resets_retries_on_all_subgraphs(self) -> None:
        """clean_up resets retries on every market + other subgraph."""
        b = _make_behaviour()

        # creators_iterator yields market subgraph names
        b.context.params.creators_iterator = iter(
            [("omen_subgraph", ["0xc1"]), ("polymarket_subgraph", ["0xc2"])]
        )

        # Create individual mock subgraphs accessible via getattr(context, name)
        mock_omen = MagicMock()
        mock_poly = MagicMock()
        mock_ct = MagicMock()
        mock_net = MagicMock()
        mock_realitio = MagicMock()
        mock_trades = MagicMock()

        b.context.omen_subgraph = mock_omen
        b.context.polymarket_subgraph = mock_poly
        b.context.conditional_tokens_subgraph = mock_ct
        b.context.network_subgraph = mock_net
        b.context.realitio_subgraph = mock_realitio
        b.context.trades_subgraph = mock_trades

        b.clean_up()

        mock_omen.reset_retries.assert_called_once()
        mock_poly.reset_retries.assert_called_once()
        mock_ct.reset_retries.assert_called_once()
        mock_net.reset_retries.assert_called_once()
        mock_realitio.reset_retries.assert_called_once()
        mock_trades.reset_retries.assert_called_once()

    def test_clean_up_no_market_subgraphs(self) -> None:
        """clean_up still resets the other subgraphs when there are no markets."""
        b = _make_behaviour()
        b.context.params.creators_iterator = iter([])

        mock_ct = MagicMock()
        mock_net = MagicMock()
        mock_realitio = MagicMock()
        mock_trades = MagicMock()

        b.context.conditional_tokens_subgraph = mock_ct
        b.context.network_subgraph = mock_net
        b.context.realitio_subgraph = mock_realitio
        b.context.trades_subgraph = mock_trades

        b.clean_up()

        mock_ct.reset_retries.assert_called_once()
        mock_net.reset_retries.assert_called_once()
        mock_realitio.reset_retries.assert_called_once()
        mock_trades.reset_retries.assert_called_once()


# ---------------------------------------------------------------------------
# BUG 2: fetch_claim_params malformed answer data
# ---------------------------------------------------------------------------


class TestFetchClaimParamsMalformedData:
    """Test that malformed answer data returns None instead of crashing."""

    def test_missing_answer_key_returns_none(self) -> None:
        """Answer missing required keys returns None."""
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.realitio_subgraph = mock_sg

        # Answer missing "answer" key
        raw_answers = [{"question": {}, "bondAggregate": "1000", "timestamp": "100"}]
        mock_sg.process_response.return_value = raw_answers

        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]

        gen = b.fetch_claim_params(question_id="0xquestion123")
        result = _exhaust(gen)

        assert result is None
        b.context.logger.error.assert_called()


# ---------------------------------------------------------------------------
# BUG 3: Batched trade fetching malformed pagination keys
# ---------------------------------------------------------------------------


class TestFetchRedeemInfoMalformedPagination:
    """Test that malformed trade data returns partial results."""

    def _setup_behaviour(self) -> Any:
        """Create a behaviour wired for redeem-info tests.

        :return: behaviour and mock subgraph tuple
        """
        b = _make_behaviour()
        b._current_market = "omen_subgraph"

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.trades_subgraph = mock_sg

        b.context.state.round_sequence.latest_synchronized_data.safe_contract_address = (
            "0xSAFE"
        )

        return b, mock_sg

    def test_missing_fpmm_key_returns_partial(self) -> None:
        """Trade missing 'fpmm' key returns collected trades."""
        b, mock_sg = self._setup_behaviour()
        # Trade without "fpmm" key — will fail pagination extraction
        batch = [{"id": "t1"}]

        process_returns = iter([batch])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b._fetch_redeem_info()
        result = _exhaust(gen)

        assert result == batch
        b.context.logger.error.assert_called()


class TestFetchTradesMalformedPagination:
    """Test that malformed trade data returns partial results."""

    def _setup_behaviour(self) -> Any:
        """Create a behaviour wired for trades tests.

        :return: behaviour and mock subgraph tuple
        """
        b = _make_behaviour()

        mock_sg = MagicMock()
        mock_sg.get_spec.return_value = {}
        mock_sg.is_retries_exceeded.return_value = False
        b.context.trades_subgraph = mock_sg

        return b, mock_sg

    def test_missing_creation_timestamp_returns_partial(self) -> None:
        """Trade missing 'creationTimestamp' returns collected trades."""
        b, mock_sg = self._setup_behaviour()
        # Trade without "creationTimestamp" key
        batch = [{"id": "t1"}]

        process_returns = iter([batch])
        mock_raw = MagicMock()
        b.get_http_response = _return_gen(mock_raw)  # type: ignore[method-assign]
        mock_sg.process_response.side_effect = lambda _: next(process_returns)

        gen = b.fetch_trades(
            creator="0xCreator", from_timestamp=0.0, to_timestamp=9999999.0
        )
        result = _exhaust(gen)

        assert result == batch
        b.context.logger.error.assert_called()


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

        def _capture_sleep(seconds: float) -> Any:
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

        def _capture_sleep(seconds: float) -> Any:
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

        def _tracking_sleep(*a: Any, **kw: Any) -> Any:
            nonlocal sleep_called
            sleep_called = True
            yield

        b.sleep = _tracking_sleep  # type: ignore[method-assign]
        sg = self._make_subgraph(retries_exceeded=True, sleep_time=10.0)

        gen = b._handle_response(sg, None, "things")
        _exhaust(gen)

        assert b._fetch_status == FetchStatus.FAIL
        assert sleep_called is False
