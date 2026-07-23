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

"""Tests for the mech_analytics_client module.

Every test below targets a real correctness or safety property of the
scored-rows fetcher, not the mocked return values. The failure modes
covered mirror the ones that would silently corrupt the trader's ROI /
count numbers rather than crash (a dropped page, a swallowed schema
drift, a cursor cycle).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client import (
    GNOSIS_CHAIN_ID,
    MAX_PAGES,
    POLYGON_CHAIN_ID,
    build_requester_url,
    build_scored_rows_url,
    chain_id_for_platform,
    fetch_requester_usage,
    fetch_scored_rows,
    find_latest_row_for_title,
    is_flag_enabled,
    parse_requester_payload,
    parse_scored_rows_page,
    rows_as_subgraph_mech_requests,
)

BASE_URL = "https://mech-analytics.test"
SAFE = "0x" + "ab" * 20
SINCE = datetime(2026, 7, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 7, 15, tzinfo=timezone.utc)


def _mock_response(
    status_code: int = 200, json_body: Optional[dict] = None, raise_json: bool = False
) -> MagicMock:
    """Build a MagicMock modelling a requests.Response with .status_code and .json()."""
    response = MagicMock()
    response.status_code = status_code
    if raise_json:
        response.json.side_effect = ValueError("no JSON body")
    else:
        response.json.return_value = json_body if json_body is not None else {}
    return response


class TestChainIdForPlatform:
    """chain_id_for_platform routes to the correct chain constant."""

    def test_omen_returns_gnosis(self) -> None:
        """Omen returns gnosis."""
        assert chain_id_for_platform(False) == GNOSIS_CHAIN_ID == 100

    def test_polymarket_returns_polygon(self) -> None:
        """Polymarket returns polygon."""
        assert chain_id_for_platform(True) == POLYGON_CHAIN_ID == 137


class TestFetchRequesterUsage:
    """fetch_requester_usage hits /v1/metrics/requester/{chain}/{address}."""

    def _sample_payload(self) -> dict:
        return {
            "chain_id": GNOSIS_CHAIN_ID,
            "address": SAFE.lower(),
            "windows": {
                "7d": {"n_mech_requests": 12, "tool_accuracy": 0.75},
                "30d": {"n_mech_requests": 42, "tool_accuracy": 0.7},
                "90d": {"n_mech_requests": 100, "tool_accuracy": 0.68},
                "all": {"n_mech_requests": 500, "tool_accuracy": 0.71},
            },
            "days": [],
        }

    def test_returns_none_when_base_url_empty(self) -> None:
        """Returns none when base url empty."""
        assert fetch_requester_usage("", GNOSIS_CHAIN_ID, SAFE) is None

    def test_returns_full_payload_on_success(self) -> None:
        """Returns full payload on success."""
        expected = self._sample_payload()
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body=expected),
        ):
            result = fetch_requester_usage(BASE_URL, GNOSIS_CHAIN_ID, SAFE)
        assert result == expected

    def test_sends_chain_and_address_in_url_path(self) -> None:
        """Sends chain and address in url path."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body=self._sample_payload()),
        ) as mock_get:
            fetch_requester_usage(BASE_URL, POLYGON_CHAIN_ID, SAFE)
        called_url = mock_get.call_args.args[0]
        assert (
            called_url == f"{BASE_URL}/v1/metrics/requester/{POLYGON_CHAIN_ID}/{SAFE}"
        )

    def test_returns_zero_shaped_payload_for_unknown_safe(self) -> None:
        """Returns zero shaped payload for unknown safe."""
        # Endpoint returns zero-shaped body (not 404) for never-seen
        # addresses. Caller distinguishes "no activity" (payload with
        # n_mech_requests=0) from "fetch failure" (None), so a real
        # zero still caches correctly.
        zero_payload = {
            "chain_id": GNOSIS_CHAIN_ID,
            "address": SAFE.lower(),
            "windows": {
                "7d": {"n_mech_requests": 0, "tool_accuracy": None},
                "30d": {"n_mech_requests": 0, "tool_accuracy": None},
                "90d": {"n_mech_requests": 0, "tool_accuracy": None},
                "all": {"n_mech_requests": 0, "tool_accuracy": None},
            },
            "days": [],
        }
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body=zero_payload),
        ):
            result = fetch_requester_usage(BASE_URL, GNOSIS_CHAIN_ID, SAFE)
        assert result == zero_payload
        assert result is not None  # not None: caller sees explicit zero

    def test_returns_none_on_non_2xx(self) -> None:
        """Returns none on non 2xx."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(status_code=503),
        ):
            assert fetch_requester_usage(BASE_URL, GNOSIS_CHAIN_ID, SAFE) is None

    def test_returns_none_when_windows_field_missing(self) -> None:
        """Returns none when windows field missing."""
        # Proxy error / upstream shape drift MUST NOT be silently treated
        # as "Safe has zero requests" — that would zero the mech-fee cost
        # leg and inflate ROI.
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"detail": "server error"}),
        ):
            assert fetch_requester_usage(BASE_URL, GNOSIS_CHAIN_ID, SAFE) is None

    def test_returns_none_on_request_exception(self) -> None:
        """Returns none on request exception."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            side_effect=requests.ConnectionError("network down"),
        ):
            assert fetch_requester_usage(BASE_URL, GNOSIS_CHAIN_ID, SAFE) is None


class TestIsFlagEnabled:
    """Flag helper is True only for a real ``True`` + non-empty URL."""

    def test_returns_true_when_both_set(self) -> None:
        """Returns true when both set."""
        params = SimpleNamespace(use_mech_analytics=True, mech_analytics_url=BASE_URL)
        assert is_flag_enabled(params) is True

    def test_returns_false_when_flag_false(self) -> None:
        """Returns false when flag false."""
        params = SimpleNamespace(use_mech_analytics=False, mech_analytics_url=BASE_URL)
        assert is_flag_enabled(params) is False

    def test_returns_false_when_url_empty(self) -> None:
        """Returns false when url empty."""
        params = SimpleNamespace(use_mech_analytics=True, mech_analytics_url="")
        assert is_flag_enabled(params) is False

    def test_returns_false_when_params_is_none(self) -> None:
        """Returns false when params is none."""
        assert is_flag_enabled(None) is False

    def test_returns_false_for_magicmock_params(self) -> None:
        """Returns false for magicmock params."""
        # This is the load-bearing property: existing fetcher tests build
        # ``context = MagicMock()`` and the flag check must not trip on
        # MagicMock's truthy auto-attributes. Without the ``is True``
        # discipline every legacy test would silently flip to the new path.
        params = MagicMock()
        assert is_flag_enabled(params) is False

    def test_returns_false_when_flag_is_a_truthy_non_bool(self) -> None:
        """Returns false when flag is a truthy non bool."""
        # A stringly-configured "true" (yaml-loader mistake) must NOT enable
        # the flag — the config schema requires a real bool.
        params = SimpleNamespace(use_mech_analytics="true", mech_analytics_url=BASE_URL)
        assert is_flag_enabled(params) is False


class TestFetchScoredRows:
    """Pagination loop failure modes that would silently return partial data."""

    def test_returns_none_when_base_url_empty(self) -> None:
        """Returns none when base url empty."""
        assert fetch_scored_rows("", SAFE, GNOSIS_CHAIN_ID) is None

    def test_single_page_success_returns_rows(self) -> None:
        """Single page success returns rows."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(
                json_body={
                    "rows": [{"question_title": "Q1"}, {"question_title": "Q2"}],
                    "next_cursor": None,
                }
            ),
        ):
            result = fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        assert result == [{"question_title": "Q1"}, {"question_title": "Q2"}]

    def test_multi_page_success_concatenates_in_order(self) -> None:
        """Multi page success concatenates in order."""
        pages = [
            _mock_response(json_body={"rows": [{"i": 1}], "next_cursor": "c1"}),
            _mock_response(json_body={"rows": [{"i": 2}], "next_cursor": "c2"}),
            _mock_response(json_body={"rows": [{"i": 3}], "next_cursor": None}),
        ]
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            side_effect=pages,
        ):
            result = fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        assert result == [{"i": 1}, {"i": 2}, {"i": 3}]

    def test_cursor_undefined_is_normalised_to_none(self) -> None:
        """Cursor undefined is normalised to none."""
        # The ``next_cursor or None`` guard makes an absent key or literal
        # ``undefined`` end pagination rather than issue a ``cursor=None``
        # string on the next request. Without this the loop would either
        # 400 opaquely or spin.
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"rows": []}),  # no next_cursor key
        ) as mock_get:
            result = fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        assert result == []
        assert mock_get.call_count == 1

    def test_passes_requester_chain_id_and_limit_on_first_page(self) -> None:
        """Passes requester chain id and limit on first page."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"rows": [], "next_cursor": None}),
        ) as mock_get:
            fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["requester"] == SAFE
        assert kwargs["params"]["chain_id"] == GNOSIS_CHAIN_ID
        assert kwargs["params"]["limit"] == 5000
        assert "cursor" not in kwargs["params"]
        assert "since" not in kwargs["params"]
        assert "until" not in kwargs["params"]

    def test_passes_since_and_until_iso_when_provided(self) -> None:
        """Passes since and until iso when provided."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"rows": [], "next_cursor": None}),
        ) as mock_get:
            fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID, since=SINCE, until=UNTIL)
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["since"] == "2026-07-01T00:00:00+00:00"
        assert kwargs["params"]["until"] == "2026-07-15T00:00:00+00:00"

    def test_forwards_cursor_on_subsequent_pages(self) -> None:
        """Forwards cursor on subsequent pages."""
        pages = [
            _mock_response(json_body={"rows": [], "next_cursor": "abc"}),
            _mock_response(json_body={"rows": [], "next_cursor": None}),
        ]
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            side_effect=pages,
        ) as mock_get:
            fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        # First call has no cursor, second call has cursor="abc"
        assert "cursor" not in mock_get.call_args_list[0].kwargs["params"]
        assert mock_get.call_args_list[1].kwargs["params"]["cursor"] == "abc"

    def test_trailing_slash_on_base_url_produces_single_slash_path(self) -> None:
        """Trailing slash on base url produces single slash path."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"rows": [], "next_cursor": None}),
        ) as mock_get:
            fetch_scored_rows(BASE_URL + "//", SAFE, GNOSIS_CHAIN_ID)
        called_url = mock_get.call_args.args[0]
        assert called_url == f"{BASE_URL}/v1/data/scored-rows"

    def test_returns_none_on_non_2xx(self) -> None:
        """Returns none on non 2xx."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(status_code=502),
        ):
            assert fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID) is None

    def test_returns_none_on_json_parse_error(self) -> None:
        """Returns none on json parse error."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(raise_json=True),
        ):
            assert fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID) is None

    def test_returns_none_when_rows_field_missing(self) -> None:
        """Returns none when rows field missing."""
        # A response missing ``rows`` (proxy error, upstream shape change)
        # must NOT be silently treated as empty — an empty list would zero
        # the mech-fee cost leg and inflate ROI, which is the exact failure
        # mode this client's guards exist to prevent.
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"detail": "query too broad"}),
        ):
            assert fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID) is None

    def test_returns_none_when_rows_is_not_a_list(self) -> None:
        """Returns none when rows is not a list."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=_mock_response(json_body={"rows": "not-a-list"}),
        ):
            assert fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID) is None

    def test_returns_none_on_request_exception(self) -> None:
        """Returns none on request exception."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            side_effect=requests.ConnectionError("network down"),
        ):
            assert fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID) is None

    def test_returns_none_when_max_pages_exceeded(self) -> None:
        """Returns none when max pages exceeded."""
        # Endpoint returning a never-null cursor must not hang; the loop
        # caps at MAX_PAGES and returns None so the caller retries next
        # cycle rather than baking a partial list into the cache.
        never_ending = _mock_response(
            json_body={"rows": [{"i": 0}], "next_cursor": "same-cursor-forever"}
        )
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            return_value=never_ending,
        ) as mock_get:
            result = fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        assert result is None
        assert mock_get.call_count == MAX_PAGES

    def test_mid_pagination_failure_returns_none(self) -> None:
        """Mid pagination failure returns none."""
        # Partial results are as dangerous as a dropped page — the caller
        # can't distinguish "some rows" from "all rows" and would count
        # only the fetched prefix.
        pages = [
            _mock_response(json_body={"rows": [{"i": 1}], "next_cursor": "c1"}),
            _mock_response(status_code=502),
        ]
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client.requests.get",
            side_effect=pages,
        ):
            assert fetch_scored_rows(BASE_URL, SAFE, GNOSIS_CHAIN_ID) is None


class TestRowsAsSubgraphMechRequests:
    """Adapter maps endpoint rows onto the subgraph shape for downstream reuse."""

    def test_maps_populated_title_to_parsedrequest_dict(self) -> None:
        """Maps populated title to parsedrequest dict."""
        rows = [
            {
                "question_title": "Will X happen?",
                "tool": "prediction-tool",
                "requested_at": "2026-07-10T12:00:00+00:00",
            }
        ]
        adapted = rows_as_subgraph_mech_requests(rows)
        assert len(adapted) == 1
        assert adapted[0]["parsedRequest"] == {
            "questionTitle": "Will X happen?",
            "tool": "prediction-tool",
        }
        assert adapted[0]["blockTimestamp"] > 0

    def test_null_title_maps_to_parsedrequest_none(self) -> None:
        """Null title maps to parsedrequest none."""
        # ``parsedRequest: None`` matches the "no match" semantics the
        # subgraph produces today for rows with null parsedRequest.
        rows = [{"question_title": None, "requested_at": "2026-07-10T12:00:00Z"}]
        adapted = rows_as_subgraph_mech_requests(rows)
        assert adapted[0]["parsedRequest"] is None

    def test_iso_z_suffix_converts_to_unix_seconds(self) -> None:
        """Iso z suffix converts to unix seconds."""
        rows = [{"question_title": "Q", "requested_at": "2026-07-10T12:00:00Z"}]
        adapted = rows_as_subgraph_mech_requests(rows)
        expected = int(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc).timestamp())
        assert adapted[0]["blockTimestamp"] == expected

    def test_unparseable_timestamp_becomes_zero(self) -> None:
        """Unparseable timestamp becomes zero."""
        # Falls into the "unmatched" day-bucket rather than being silently
        # attributed to a wrong day.
        rows = [{"question_title": "Q", "requested_at": "not-a-date"}]
        adapted = rows_as_subgraph_mech_requests(rows)
        assert adapted[0]["blockTimestamp"] == 0

    def test_missing_requested_at_becomes_zero(self) -> None:
        """Missing requested at becomes zero."""
        rows = [{"question_title": "Q"}]
        adapted = rows_as_subgraph_mech_requests(rows)
        assert adapted[0]["blockTimestamp"] == 0

    def test_empty_input_returns_empty_list(self) -> None:
        """Empty list in → empty list out; no items to reshape."""
        assert rows_as_subgraph_mech_requests([]) == []

    def test_none_input_raises_typeerror(self) -> None:
        """None isn't part of the contract; explicit crash beats silent swallow."""
        with pytest.raises(TypeError):
            rows_as_subgraph_mech_requests(None)  # type: ignore[arg-type]


class TestFindLatestRowForTitle:
    """Title-match is exact-equality and picks the max ``requested_at``."""

    def test_returns_none_when_no_row_matches(self) -> None:
        """Returns none when no row matches."""
        rows = [{"question_title": "Other Q", "requested_at": "2026-07-10T00:00:00Z"}]
        assert find_latest_row_for_title(rows, "Will X happen?") is None

    def test_returns_none_when_title_empty(self) -> None:
        """Returns none when title empty."""
        rows = [{"question_title": "Q", "requested_at": "2026-07-10T00:00:00Z"}]
        assert find_latest_row_for_title(rows, "") is None

    def test_returns_none_when_rows_empty(self) -> None:
        """Returns none when rows empty."""
        assert find_latest_row_for_title([], "Q") is None

    def test_picks_latest_matching_row_by_requested_at(self) -> None:
        """Picks lamatching row by requested at."""
        """Picks la."""
        rows = [
            {
                "question_title": "Q",
                "requested_at": "2026-07-01T00:00:00Z",
                "tool": "t1",
            },
            {
                "question_title": "Q",
                "requested_at": "2026-07-10T00:00:00Z",
                "tool": "t2",
            },
            {
                "question_title": "Q",
                "requested_at": "2026-07-05T00:00:00Z",
                "tool": "t3",
            },
            {"question_title": "Other", "requested_at": "2026-07-15T00:00:00Z"},
        ]
        matched = find_latest_row_for_title(rows, "Q")
        assert matched is not None
        assert matched["tool"] == "t2"

    def test_exact_title_match_only_no_substring(self) -> None:
        """Exact title match only no substring."""
        # Substring collisions would over-match; the subgraph uses exact
        # ``questionTitle_eq`` on the same filter, so exact-only preserves
        # semantics for the flag-off vs flag-on parity check.
        rows = [
            {"question_title": "Will X happen?", "requested_at": "2026-07-10T00:00:00Z"}
        ]
        assert find_latest_row_for_title(rows, "Will X") is None


class TestBuildScoredRowsUrl:
    """URL builder produces stable, chain-scoped, param-encoded URLs."""

    def test_minimum_params_include_requester_chain_and_limit(self) -> None:
        """Only requester + chain + limit encoded when no filters given."""
        url = build_scored_rows_url(BASE_URL, SAFE, GNOSIS_CHAIN_ID)
        assert url.startswith(f"{BASE_URL}/v1/data/scored-rows?")
        assert f"requester={SAFE}" in url
        assert "chain_id=100" in url
        assert "limit=5000" in url
        assert "since=" not in url
        assert "until=" not in url
        assert "cursor=" not in url

    def test_since_until_and_cursor_encoded_when_present(self) -> None:
        """Since / until ISO-encoded, cursor passed as-is."""
        url = build_scored_rows_url(
            BASE_URL, SAFE, POLYGON_CHAIN_ID, since=SINCE, until=UNTIL, cursor="c1"
        )
        assert "chain_id=137" in url
        assert "cursor=c1" in url
        # ISO datetime with URL-encoded ``+``
        assert "since=2026-07-01T00%3A00%3A00%2B00%3A00" in url
        assert "until=2026-07-15T00%3A00%3A00%2B00%3A00" in url

    def test_trailing_slash_tolerated(self) -> None:
        """Base URL trailing slash doesn't produce a double-slash path."""
        url = build_scored_rows_url(BASE_URL + "//", SAFE, GNOSIS_CHAIN_ID)
        assert url.startswith(f"{BASE_URL}/v1/data/scored-rows?")


class TestBuildRequesterUrl:
    """URL builder for the /requester endpoint."""

    def test_chain_and_address_in_path(self) -> None:
        """Chain and address land in the URL path, no query string."""
        url = build_requester_url(BASE_URL, POLYGON_CHAIN_ID, SAFE)
        assert url == f"{BASE_URL}/v1/metrics/requester/137/{SAFE}"

    def test_trailing_slash_tolerated(self) -> None:
        """Trailing slash on base URL is stripped."""
        url = build_requester_url(BASE_URL + "//", GNOSIS_CHAIN_ID, SAFE)
        assert url == f"{BASE_URL}/v1/metrics/requester/100/{SAFE}"


class TestParseScoredRowsPage:
    """Validator for a scored-rows page payload."""

    def test_valid_page_returns_rows_and_next_cursor(self) -> None:
        """Valid page returns the rows and next cursor unchanged."""
        result = parse_scored_rows_page({"rows": [{"i": 1}], "next_cursor": "abc"})
        assert result == {"rows": [{"i": 1}], "next_cursor": "abc"}

    def test_empty_or_absent_next_cursor_becomes_none(self) -> None:
        """Absent, null, or empty next_cursor all collapse to None."""
        bodies: tuple = (
            {"rows": []},
            {"rows": [], "next_cursor": None},
            {"rows": [], "next_cursor": ""},
        )
        for body in bodies:
            result = parse_scored_rows_page(body)
            assert result is not None
            assert result["next_cursor"] is None

    def test_non_dict_payload_returns_none(self) -> None:
        """A non-dict body cannot carry a scored-rows page."""
        assert parse_scored_rows_page(["not", "a", "dict"]) is None
        assert parse_scored_rows_page(None) is None

    def test_rows_not_a_list_returns_none(self) -> None:
        """Rows must be a list — anything else means shape drift."""
        assert parse_scored_rows_page({"rows": "oops", "next_cursor": None}) is None
        assert parse_scored_rows_page({"next_cursor": None}) is None


class TestParseRequesterPayload:
    """Validator for the /requester endpoint payload."""

    def test_valid_payload_returns_it(self) -> None:
        """A valid payload with a windows dict passes through unchanged."""
        payload = {
            "chain_id": 100,
            "address": SAFE.lower(),
            "windows": {"all": {"n_mech_requests": 42}},
            "days": [],
        }
        assert parse_requester_payload(payload) == payload

    def test_non_dict_returns_none(self) -> None:
        """A non-dict body cannot carry the requester payload."""
        assert parse_requester_payload("nope") is None
        assert parse_requester_payload(None) is None

    def test_windows_not_a_dict_returns_none(self) -> None:
        """A missing or non-dict windows field means shape drift."""
        assert parse_requester_payload({"windows": []}) is None
        assert parse_requester_payload({"chain_id": 100}) is None
