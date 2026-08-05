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

"""Flag-branching tests for both Omen and Polymarket fetchers.

The full mech-analytics client behaviour is covered in
``test_mech_analytics_client.py``. These tests only prove the branching
dispatches correctly on the flag and reads the right fields off the
matched scored row — so a future refactor that silently made the flag a
no-op would fail here.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.mech_analytics_client import (
    PER_POSITION_LOOKUP_WINDOW_DAYS,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper import (
    PolymarketPredictionsFetcher,
)
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    PredictionsFetcher,
)

BASE_URL = "https://mech-analytics.test"
SAFE = "0x" + "ab" * 20
TITLE = "Will X happen?"


def _make_context(use_flag: bool = False, is_polymarket: bool = False) -> MagicMock:
    """Build a context with SimpleNamespace params (Mock-tolerant)."""
    context = MagicMock()
    context.params = SimpleNamespace(
        use_mech_analytics=use_flag,
        mech_analytics_url=BASE_URL,
        is_running_on_polymarket=is_polymarket,
    )
    context.olas_mech_subgraph.url = "https://subgraph.test/mech"
    context.polygon_mech_subgraph.url = "https://subgraph.test/polygon-mech"
    return context


def _matching_row() -> dict:
    return {
        "question_title": TITLE,
        "requested_at": "2026-07-10T12:00:00+00:00",
        "tool": "prediction-tool-x",
        "p_yes": 0.7,
        "p_no": 0.3,
        "confidence": 0.85,
        "info_utility": 0.6,
    }


class TestOmenFetcherFlagOnPath2:
    """fetch_mech_tool_for_question on Omen branches to mech-analytics on flag-on."""

    def test_flag_on_returns_tool_from_matched_scored_row(self) -> None:
        """Flag on returns tool from matched scored row."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            result = fetcher.fetch_mech_tool_for_question(
                TITLE, SAFE, bet_timestamp=1_700_000_000
            )
        assert result == "prediction-tool-x"
        # chain_id is passed for Gnosis (100) since is_polymarket=False
        assert mock_fetch.call_args.kwargs["chain_id"] == 100
        assert mock_fetch.call_args.kwargs["requester"] == SAFE

    def test_flag_on_returns_none_when_no_row_matches_title(self) -> None:
        """Flag on returns none when no row matches title."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        other_row = {**_matching_row(), "question_title": "Different Question"}
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=[other_row],
        ):
            result = fetcher.fetch_mech_tool_for_question(TITLE, SAFE)
        assert result is None

    def test_flag_on_returns_none_on_client_failure(self) -> None:
        """Flag on returns none on client failure."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=None,
        ):
            result = fetcher.fetch_mech_tool_for_question(TITLE, SAFE)
        assert result is None

    def test_flag_off_does_not_call_mech_analytics_client(self) -> None:
        """Flag off does not call mech analytics client."""
        # Load-bearing off-path assertion: a refactor that accidentally
        # made the flag a no-op (always-on or always-off) would be caught
        # here. If the mech-analytics client was reached with flag off, the
        # patched fetch would record a call.
        fetcher = PredictionsFetcher(_make_context(use_flag=False), MagicMock())
        with (
            patch(
                "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            ) as mock_fetch,
            patch(
                "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post",
                return_value=MagicMock(status_code=500),
            ),
        ):
            fetcher.fetch_mech_tool_for_question(TITLE, SAFE)
        assert mock_fetch.call_count == 0


class TestOmenFetcherFlagOnPath3:
    """_fetch_prediction_response_from_mech on Omen branches to mech-analytics on flag-on."""

    def test_flag_on_returns_prediction_fields_from_matched_row(self) -> None:
        """Flag on returns prediction fields from matched row."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ):
            result = fetcher._fetch_prediction_response_from_mech(TITLE, SAFE)
        assert result == {
            "p_yes": 0.7,
            "p_no": 0.3,
            "confidence": 0.85,
            "info_utility": 0.6,
        }

    def test_flag_on_coalesces_null_columns_to_zero(self) -> None:
        """Null columns coalesce to 0 so downstream ``.get(k,0)*100`` won't crash."""
        # ``matched.get("p_yes")`` returns a present-but-None on a NULL
        # column; downstream ``_format_bet_for_position`` does
        # ``prediction_response.get("p_yes", 0) * 100`` which only
        # substitutes when the KEY is absent. A present-but-None slips
        # through and raises TypeError, silently swallowed by
        # ``fetch_position_details`` — dropping the whole position from
        # the report. Coalesce here so downstream stays untouched.
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        null_row = {
            "question_title": TITLE,
            "requested_at": "2026-07-10T00:00:00+00:00",
            "p_yes": None,
            "p_no": None,
            "confidence": None,
            "info_utility": None,
        }
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=[null_row],
        ):
            result = fetcher._fetch_prediction_response_from_mech(TITLE, SAFE)
        assert result == {
            "p_yes": 0,
            "p_no": 0,
            "confidence": 0,
            "info_utility": 0,
        }
        # Sanity: multiplying any of these by 100 must not raise.
        assert result is not None
        for key in ("p_yes", "p_no", "confidence", "info_utility"):
            _ = result.get(key, 0) * 100

    def test_flag_on_returns_none_on_empty_title(self) -> None:
        """Flag on returns none on empty title."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
        ) as mock_fetch:
            result = fetcher._fetch_prediction_response_from_mech("", SAFE)
        assert result is None
        # Empty title short-circuits BEFORE the fetch happens.
        assert mock_fetch.call_count == 0


class TestPolymarketFetcherFlagOn:
    """Polymarket mirror behaves identically on flag-on with Polygon chain_id."""

    def _fetcher(self) -> "PolymarketPredictionsFetcher":
        """Fetcher."""
        return PolymarketPredictionsFetcher(
            _make_context(use_flag=True, is_polymarket=True), MagicMock()
        )

    def test_path_2_uses_polygon_chain_id(self) -> None:
        """Path 2 uses polygon chain id."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            self._fetcher().fetch_mech_tool_for_question(TITLE, SAFE)
        assert mock_fetch.call_args.kwargs["chain_id"] == 137

    def test_path_3_uses_polygon_chain_id_and_returns_fields(self) -> None:
        """Path 3 uses polygon chain id and returns fields."""
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            result = self._fetcher()._fetch_prediction_response_from_mech(TITLE, SAFE)
        assert mock_fetch.call_args.kwargs["chain_id"] == 137
        assert result == {
            "p_yes": 0.7,
            "p_no": 0.3,
            "confidence": 0.85,
            "info_utility": 0.6,
        }

    @pytest.mark.parametrize("use_flag", [False])
    def test_flag_off_does_not_call_mech_analytics_client(self, use_flag: bool) -> None:
        """Flag off does not call mech analytics client."""
        fetcher = PolymarketPredictionsFetcher(
            _make_context(use_flag=use_flag, is_polymarket=True), MagicMock()
        )
        with (
            patch(
                "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.fetch_scored_rows",
            ) as mock_fetch,
            patch(
                "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.requests.post",
                return_value=MagicMock(status_code=500),
            ),
        ):
            fetcher.fetch_mech_tool_for_question(TITLE, SAFE)
            fetcher._fetch_prediction_response_from_mech(TITLE, SAFE)
        assert mock_fetch.call_count == 0


class TestPerPositionLookbackWindow:
    """Per-position fetches must send a bounded ``since`` window.

    Without a ``since`` bound the client would page the Safe's full
    mech history on every position, which blocks cold-start reports on
    long-history Safes. These assertions pin the guard in place so a
    future refactor that drops the ``since=`` kwarg (or widens the
    window without justification) fails loudly instead of silently
    slowing every report.
    """

    _BET_TS = 1_700_000_000  # 2023-11-14T22:13:20Z

    def _assert_since_window(
        self, kwargs: Mapping[str, Any], expected_until_ts: int, expected_days: int
    ) -> None:
        assert "since" in kwargs, "per-position fetch must send a since bound"
        assert "until" in kwargs, "per-position fetch must send an until bound"
        expected_until = datetime.fromtimestamp(expected_until_ts + 1, tz=timezone.utc)
        expected_since = expected_until - timedelta(days=expected_days)
        assert kwargs["until"] == expected_until
        assert kwargs["since"] == expected_since

    def test_omen_path_2_sends_bounded_since_from_bet_timestamp(self) -> None:
        """Omen fetch_mech_tool_for_question sends since = until - 30d."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            fetcher.fetch_mech_tool_for_question(
                TITLE, SAFE, bet_timestamp=self._BET_TS
            )
        self._assert_since_window(
            mock_fetch.call_args.kwargs, self._BET_TS, PER_POSITION_LOOKUP_WINDOW_DAYS
        )

    def test_omen_path_3_sends_bounded_since_from_bet_timestamp(self) -> None:
        """Omen _fetch_prediction_response_from_mech sends since = until - 30d."""
        fetcher = PredictionsFetcher(_make_context(use_flag=True), MagicMock())
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            fetcher._fetch_prediction_response_from_mech(
                TITLE, SAFE, bet_timestamp=self._BET_TS
            )
        self._assert_since_window(
            mock_fetch.call_args.kwargs, self._BET_TS, PER_POSITION_LOOKUP_WINDOW_DAYS
        )

    def test_polymarket_path_2_sends_bounded_since_from_bet_timestamp(self) -> None:
        """Polymarket fetch_mech_tool_for_question sends since = until - 30d."""
        fetcher = PolymarketPredictionsFetcher(
            _make_context(use_flag=True, is_polymarket=True), MagicMock()
        )
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            fetcher.fetch_mech_tool_for_question(
                TITLE, SAFE, bet_timestamp=self._BET_TS
            )
        self._assert_since_window(
            mock_fetch.call_args.kwargs, self._BET_TS, PER_POSITION_LOOKUP_WINDOW_DAYS
        )

    def test_polymarket_path_3_sends_bounded_since_from_bet_timestamp(self) -> None:
        """Polymarket _fetch_prediction_response_from_mech sends since = until - 30d."""
        fetcher = PolymarketPredictionsFetcher(
            _make_context(use_flag=True, is_polymarket=True), MagicMock()
        )
        with patch(
            "packages.valory.skills.agent_performance_summary_abci.graph_tooling.polymarket_predictions_helper.fetch_scored_rows",
            return_value=[_matching_row()],
        ) as mock_fetch:
            fetcher._fetch_prediction_response_from_mech(
                TITLE, SAFE, bet_timestamp=self._BET_TS
            )
        self._assert_since_window(
            mock_fetch.call_args.kwargs, self._BET_TS, PER_POSITION_LOOKUP_WINDOW_DAYS
        )
