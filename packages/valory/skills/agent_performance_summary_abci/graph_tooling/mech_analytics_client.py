#!/usr/bin/env python3
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

"""Synchronous client for mech-analytics /v1/data/scored-rows.

Post off-chain switch the marketplace subgraph no longer indexes individual
mech-request content (title, tool, response). This module pulls the same
per-Safe request list from mech-analytics' scored-rows endpoint instead.

The endpoint is chain-safe when the ``chain_id`` filter is passed: Gnosis
Safe proxies deploy to the same address on multiple chains by design
(CREATE2 + shared factory), so a Safe with the same address on both Gnosis
and Polygon would otherwise pollute the count. Every call from this module
passes ``chain_id`` explicitly.

Pagination is keyset via the opaque ``cursor`` the endpoint returns.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

_LOGGER = logging.getLogger(__name__)

GNOSIS_CHAIN_ID = 100
POLYGON_CHAIN_ID = 137

# Endpoint's max page size per data.py MAX_LIMIT. Higher = fewer round-trips.
SCORED_ROWS_PAGE_LIMIT = 5000

# Safety cap on pagination loop. Prevents an infinite loop if the endpoint
# returns a cursor cycle. For a Pearl trader with 50k lifetime rows this
# is ~10 pages; 200 pages tolerates a 1M-row Safe before tripping.
MAX_PAGES = 200

# Per-request timeout. Matches the trader's existing pattern of 30s on
# direct HTTP calls to mech-related endpoints (see predictions_helper.py).
REQUEST_TIMEOUT_SECONDS = 30

# Lookback window for per-position mech-request lookups
# (``fetch_mech_tool_for_question``, ``_fetch_prediction_response_from_mech``
# on both Omen and Polymarket fetchers). Without a ``since`` bound each
# per-position call pages the Safe's full mech history, which blows up
# on cold-start / long-history Safes. 30 days is a large safety margin
# over the typical trader prediction-to-bet lag (seconds to minutes)
# while trimming the fetch to a small window for most positions.
PER_POSITION_LOOKUP_WINDOW_DAYS = 30


def per_position_lookup_window(bet_timestamp: int) -> "tuple[datetime, datetime]":
    """Return the ``(since, until)`` bounds for a per-position mech lookup.

    Centralises the two boundary decisions the per-position helpers
    both need to get right and were previously duplicating verbatim at
    four call sites:

    - ``+1s`` on ``until`` maps the subgraph's ``blockTimestamp_lte``
      (inclusive) onto mech-analytics' ``until`` (exclusive), so a mech
      request timestamped exactly at ``bet_timestamp`` is still
      included instead of being dropped by strict-less-than.
    - ``since = until - PER_POSITION_LOOKUP_WINDOW_DAYS`` caps the
      fetch so each per-position call pages a bounded window rather
      than the Safe's full mech history.

    Keeping the two boundaries in one place means a future tweak (e.g.
    widening the window on operator feedback) lands in every call site
    at once.

    :param bet_timestamp: Unix seconds; the ``blockTimestamp_lte``-style
        upper bound before the ``+1s`` inclusive adjustment.
    :return: ``(since, until)`` as timezone-aware UTC datetimes ready
        to hand to ``fetch_scored_rows`` /
        ``_page_mech_analytics_scored_rows``.
    """
    until = datetime.fromtimestamp(bet_timestamp + 1, tz=timezone.utc)
    since = until - timedelta(days=PER_POSITION_LOOKUP_WINDOW_DAYS)
    return since, until


def is_flag_enabled(params: Any) -> bool:
    """Return True only when the flag is a real ``True`` and a URL is set.

    ``is True`` is deliberate — the fetcher-side tests build ``context``
    as a ``MagicMock``, whose auto-attribute access returns another
    ``MagicMock`` (truthy). A plain truthy check would silently flip
    every existing test onto the new code path. This helper is safe to
    call with a Mock, a real ``AgentPerformanceSummaryParams``, or
    ``None`` (behaviour-side callers that pre-check ``self.params``).

    :param params: params-like object (or ``None``) exposing
        ``use_mech_analytics`` and ``mech_analytics_url`` attributes.
    :return: True when the migration flag is truly enabled and a URL
        is configured; False otherwise.
    """
    if params is None:
        return False
    return getattr(params, "use_mech_analytics", False) is True and bool(
        getattr(params, "mech_analytics_url", "")
    )


def chain_id_for_platform(is_running_on_polymarket: bool) -> int:
    """Return the chain_id the trader is running on.

    Kept as a module-level helper so callers on both the behaviour path
    (requests.py) and the helper path (predictions_helper.py mirrors)
    resolve chain the same way, and the two integers only appear once.

    :param is_running_on_polymarket: whether the trader is running on
        the Polymarket variant (True) or the Omen variant (False).
    :return: Polygon chain id when True, Gnosis chain id when False.
    """
    return POLYGON_CHAIN_ID if is_running_on_polymarket else GNOSIS_CHAIN_ID


def build_scored_rows_url(
    base_url: str,
    requester: str,
    chain_id: int,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    cursor: Optional[str] = None,
) -> str:
    """Build a fully-qualified ``/v1/data/scored-rows`` URL with query params.

    Kept as a module-level helper so the synchronous ``fetch_scored_rows``
    and behaviour-side callers that use the framework's async
    ``get_http_response`` construct identical URLs (same params, same
    encoding, same rounding on datetimes).

    :param base_url: mech-analytics base URL. Trailing slash tolerated.
    :param requester: Safe address.
    :param chain_id: chain scope. Passed explicitly to prevent silent
        cross-chain sums.
    :param since: optional lower bound on ``requested_at`` (inclusive).
    :param until: optional upper bound on ``requested_at`` (exclusive).
    :param cursor: opaque keyset cursor for the next page.
    :return: full URL including the query string.
    """
    params: Dict[str, Any] = {
        "requester": requester,
        "chain_id": chain_id,
        "limit": SCORED_ROWS_PAGE_LIMIT,
    }
    if since is not None:
        params["since"] = since.isoformat()
    if until is not None:
        params["until"] = until.isoformat()
    if cursor is not None:
        params["cursor"] = cursor
    query = urlencode(params)
    return f"{base_url.rstrip('/')}/v1/data/scored-rows?{query}"


def build_requester_url(base_url: str, chain_id: int, address: str) -> str:
    """Build a ``/v1/metrics/requester/{chain_id}/{address}`` URL.

    :param base_url: mech-analytics base URL. Trailing slash tolerated.
    :param chain_id: chain scope for the Safe address.
    :param address: the Safe address (or any EOA).
    :return: full URL.
    """
    return f"{base_url.rstrip('/')}/v1/metrics/requester/{chain_id}/{address}"


def parse_scored_rows_page(
    payload: Any, logger: Optional[logging.Logger] = None
) -> Optional[Dict[str, Any]]:
    """Validate one scored-rows page and return ``{rows, next_cursor}``.

    Returns ``None`` on any shape drift (non-dict, ``rows`` missing or
    not a list). Callers on both the sync client and the async
    behaviour path share this validation so a proxy-error body cannot
    silently be treated as "call succeeded, no rows".

    :param payload: parsed JSON body (dict expected).
    :param logger: optional logger for shape-drift warnings.
    :return: dict with ``rows`` (list) and ``next_cursor`` (str or
        None) on success; ``None`` on shape drift.
    """
    if not isinstance(payload, dict):
        if logger is not None:
            logger.error(
                "mech-analytics scored-rows: unexpected top-level shape "
                "(payload is not a dict)"
            )
        return None
    rows = payload.get("rows")
    if not isinstance(rows, list):
        if logger is not None:
            logger.error(
                "mech-analytics scored-rows: unexpected response shape "
                "(rows is not a list)"
            )
        return None
    # ``.get("next_cursor")`` already returns None for an absent key;
    # ``or None`` additionally coerces a present-but-falsy value so a
    # schema-drift edge case can't leak an empty cursor into the next
    # request's params.
    next_cursor = payload.get("next_cursor") or None
    return {"rows": rows, "next_cursor": next_cursor}


def parse_requester_payload(
    payload: Any, logger: Optional[logging.Logger] = None
) -> Optional[Dict[str, Any]]:
    """Validate the ``/requester`` payload and return it, or ``None`` on drift.

    Validation depth matters: the consumer chain in
    ``_get_total_mech_requests`` reads
    ``payload["windows"]["all"]["n_mech_requests"]`` with permissive
    ``.get() or 0`` fallbacks at every step, which turns any missing key
    into a silent ``0``. A ``0`` then flows into
    ``self._total_mech_requests`` (**cached**), short-circuits
    ``_calculate_settled_mech_requests`` to ``0``, and zeroes
    ``all_mech_costs`` — silently inflating ROI. Worse, that outcome is
    indistinguishable from the genuine zero-shaped payload the endpoint
    returns for an unknown Safe. So a shallow "``windows`` is a dict"
    check is not enough: schema drift on ``all`` or ``n_mech_requests``
    must land in the failure lane (``None`` + log), not the success one.

    :param payload: parsed JSON body (dict expected).
    :param logger: optional logger for shape-drift warnings.
    :return: the payload dict on success; ``None`` if ``windows`` is
        missing, its ``all`` window is missing or non-dict, or
        ``n_mech_requests`` is missing / not an int-compatible value
        on the ``all`` window.
    """
    if not isinstance(payload, dict):
        if logger is not None:
            logger.error(
                "mech-analytics /requester: unexpected top-level shape "
                "(payload is not a dict)"
            )
        return None
    windows = payload.get("windows")
    if not isinstance(windows, dict):
        if logger is not None:
            logger.error(
                "mech-analytics /requester: unexpected response shape "
                "(windows is not a dict)"
            )
        return None
    all_window = windows.get("all")
    if not isinstance(all_window, dict):
        if logger is not None:
            logger.error(
                "mech-analytics /requester: unexpected response shape "
                "(``windows.all`` is missing or not a dict); refusing "
                "to fall through to a silent 0 count"
            )
        return None
    if "n_mech_requests" not in all_window:
        if logger is not None:
            logger.error(
                "mech-analytics /requester: unexpected response shape "
                "(``windows.all.n_mech_requests`` missing); refusing to "
                "fall through to a silent 0 count"
            )
        return None
    n_mech = all_window.get("n_mech_requests")
    if not isinstance(n_mech, (int, float)) or isinstance(n_mech, bool):
        if logger is not None:
            logger.error(
                "mech-analytics /requester: unexpected response shape "
                f"(``windows.all.n_mech_requests`` is {type(n_mech).__name__}, "
                "not a number); refusing to fall through to a silent 0 count"
            )
        return None
    return payload


def fetch_scored_rows(
    base_url: str,
    requester: str,
    chain_id: int,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    logger: Optional[logging.Logger] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Page /v1/data/scored-rows for a single Safe, chain-scoped.

    :param base_url: mech-analytics base URL (e.g.
        ``https://mech-analytics.autonolas.tech``). Trailing slash tolerated.
    :param requester: the Safe address. Endpoint lowercases before matching,
        so mixed-case checksummed addresses work.
    :param chain_id: chain id to scope the query to. Pass explicitly rather
        than defaulting — a Safe address can exist on multiple chains, and
        an unfiltered call sums their activity silently.
    :param since: optional lower bound on ``requested_at`` (inclusive).
        Omit for the all-time count use case.
    :param until: optional upper bound on ``requested_at`` (exclusive).
        Omit for the all-time count use case.
    :param logger: optional logger for warnings on non-2xx or shape errors.
    :return: list of scored-row dicts (unchanged from endpoint response), or
        ``None`` on any failure. Empty list means "call succeeded, no rows".
        The ``None`` vs ``[]`` distinction matters to callers that treat an
        empty count as ``0`` cost — a silent None-as-empty conversion here
        would inflate ROI on a transient endpoint outage.
    """
    if not base_url:
        if logger is not None:
            logger.warning("fetch_scored_rows called with empty base_url")
        return None

    # Route through the shared ``build_scored_rows_url`` +
    # ``parse_scored_rows_page`` helpers rather than hand-rolling URL /
    # payload extraction: the async ``_page_mech_analytics_scored_rows``
    # already uses them, and keeping the two paths on the same helpers
    # means a future rename of a query param or a cursor-normalisation
    # tweak lands in both places at once.
    all_rows: List[Dict[str, Any]] = []
    cursor: Optional[str] = None

    for page_index in range(MAX_PAGES):
        url = build_scored_rows_url(
            base_url=base_url,
            requester=requester,
            chain_id=chain_id,
            since=since,
            until=until,
            cursor=cursor,
        )

        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            if logger is not None:
                logger.error(f"mech-analytics fetch_scored_rows request failed: {exc}")
            return None

        if response.status_code != 200:
            if logger is not None:
                logger.error(
                    f"mech-analytics fetch_scored_rows responded {response.status_code} "
                    f"(page {page_index + 1})"
                )
            return None

        try:
            payload = response.json()
        except ValueError as exc:
            if logger is not None:
                logger.error(
                    f"mech-analytics fetch_scored_rows JSON parse failed: {exc}"
                )
            return None

        page = parse_scored_rows_page(payload, logger)
        if page is None:
            return None
        all_rows.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            return all_rows

    if logger is not None:
        logger.error(
            f"mech-analytics fetch_scored_rows exceeded MAX_PAGES={MAX_PAGES}; "
            "endpoint may be returning a cursor cycle"
        )
    return None


def rows_as_subgraph_mech_requests(
    rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Reshape endpoint rows into the trader's subgraph-shaped requests.

    The trader's existing helpers read ``request["blockTimestamp"]`` (int
    seconds) and ``request["parsedRequest"]["questionTitle"]``. mech-analytics
    returns ``requested_at`` (ISO datetime string) and ``question_title``
    (nullable). This adapter maps the endpoint shape onto the shape the
    downstream lookup expects so the day-bucketing and title-matching logic
    stays untouched behind the feature flag.

    Rows with a NULL ``question_title`` map to ``parsedRequest: None`` —
    the same "no title, no match" semantics the subgraph produces when a
    row has ``parsedRequest = null`` today.

    :param rows: list of scored-row dicts as returned by
        ``fetch_scored_rows`` (endpoint payloads unchanged).
    :return: list of dicts shaped like the trader's existing subgraph
        mech-request objects (``{blockTimestamp, parsedRequest}``).
    """
    adapted: List[Dict[str, Any]] = []
    for row in rows:
        title = row.get("question_title")
        requested_at_iso = row.get("requested_at")
        block_timestamp = _iso_to_unix_seconds(requested_at_iso)

        parsed_request: Optional[Dict[str, Any]]
        if title is None:
            parsed_request = None
        else:
            parsed_request = {
                "questionTitle": title,
                "tool": row.get("tool"),
            }

        adapted.append(
            {
                "blockTimestamp": block_timestamp,
                "parsedRequest": parsed_request,
            }
        )
    return adapted


def find_latest_row_for_title(
    rows: List[Dict[str, Any]], question_title: str
) -> Optional[Dict[str, Any]]:
    """Return the latest matching row for ``question_title``, else None.

    Rows are filtered by exact ``question_title`` equality to match
    the trader's existing exact-string match on the subgraph side.

    Only the "latest matching row from what was fetched" step is here;
    the caller is responsible for picking the ``until`` bound at fetch
    time (see the per-position helpers, which add one second to the
    bet timestamp to mirror the old ``blockTimestamp_lte`` inclusive
    boundary against the endpoint's exclusive ``until`` filter).

    :param rows: scored-row dicts returned by ``fetch_scored_rows``.
    :param question_title: exact title string to match on.
    :return: the row with the latest ``requested_at`` whose
        ``question_title`` equals the given string, or ``None`` if no
        row matches or the title is empty.
    """
    if not question_title:
        return None
    matching = [r for r in rows if r.get("question_title") == question_title]
    if not matching:
        return None
    return max(matching, key=lambda r: r.get("requested_at") or "")


def _iso_to_unix_seconds(iso_string: Optional[str]) -> int:
    """Convert an ISO-8601 UTC timestamp to Unix seconds.

    Returns 0 for None / unparseable inputs. The downstream day-bucketing
    treats 0 as an epoch-anchored request, which is far outside every
    real bet window — so a malformed row falls into the "unmatched" bucket
    rather than being silently attributed to a wrong day.

    Uses ``fromisoformat`` after normalising the ``Z`` suffix to
    ``+00:00``, so the parser is portable across Python versions and
    does not depend on native ``Z``-suffix support.

    Every parse failure is logged at WARNING via the module logger so
    a systematic endpoint format-drift is visible in ops output
    instead of silently zeroing every row's ``blockTimestamp`` and
    dumping fee attribution into the unmatched bucket.

    :param iso_string: an ISO-8601 UTC timestamp, ``Z`` or ``+00:00``
        suffix accepted, or ``None``.
    :return: Unix seconds since epoch, or 0 if the input is
        None / empty / unparseable.
    """
    if iso_string is None:
        return 0
    if iso_string == "":
        # Empty is expected when the row genuinely has no
        # ``requested_at`` set; not worth a log line each time.
        return 0
    try:
        normalised = iso_string.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalised).timestamp())
    except (ValueError, TypeError, AttributeError) as exc:
        _LOGGER.warning(
            "mech-analytics: unparseable requested_at %r (%s); row lands in "
            "the unmatched-day bucket",
            iso_string if len(str(iso_string)) < 100 else f"{str(iso_string)[:100]}...",
            exc.__class__.__name__,
        )
        return 0
