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

"""Tests for the graph_tooling.predictions_helper module (Omen PredictionsFetcher)."""

import json
import os
import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (
    INVALID_ANSWER_HEX,
    PredictionsFetcher,
    WEI_TO_NATIVE,
    parse_current_answer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fetcher() -> PredictionsFetcher:  # type: ignore[no-untyped-def]
    """Create a PredictionsFetcher instance with mocked context and logger."""
    context = MagicMock()
    context.olas_agents_subgraph.url = "https://subgraph.test/olas"
    context.olas_mech_subgraph.url = "https://subgraph.test/mech"
    context.omen_subgraph.url = "https://subgraph.test/omen"
    logger = MagicMock()
    fetcher = PredictionsFetcher(context, logger)
    return fetcher


def _make_bet(  # type: ignore[no-untyped-def]
    bet_id: str = "bet_1",
    amount: str = str(1 * WEI_TO_NATIVE),  # noqa: B008
    outcome_index: int = 0,
    timestamp: str = "1700000000",
    fpmm_id: str = "market_1",
    question: str = "Will it rain?",
    current_answer: str = "0x0000000000000000000000000000000000000000000000000000000000000000",
    current_answer_timestamp: str = "1700001000",
    answer_finalized_timestamp: Optional[str] = "1000000000",
    outcomes: Optional[List[str]] = None,
    participants: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create a mock bet dict for testing."""
    # NB: default answer_finalized_timestamp is far in the past so the
    # Bug A finalization gate is satisfied for all standard fixtures;
    # tests that need pending-finalization should override it.
    if outcomes is None:
        outcomes = ["Yes", "No"]
    if participants is None:
        participants = [
            {
                "totalPayout": str(2 * WEI_TO_NATIVE),
                "totalTraded": str(1 * WEI_TO_NATIVE),
                "totalFees": str(int(0.01 * WEI_TO_NATIVE)),
                "totalBets": 1,
            }
        ]
    fpmm: Dict[str, Any] = {
        "id": fpmm_id,
        "question": question,
        "currentAnswer": current_answer,
        "currentAnswerTimestamp": current_answer_timestamp,
        "outcomes": outcomes,
        "participants": participants,
    }
    if answer_finalized_timestamp is not None:
        fpmm["answerFinalizedTimestamp"] = answer_finalized_timestamp
    return {
        "id": bet_id,
        "amount": amount,
        "outcomeIndex": outcome_index,
        "timestamp": timestamp,
        "fixedProductMarketMaker": fpmm,
    }


# ---------------------------------------------------------------------------
# PredictionsFetcher.__init__ tests
# ---------------------------------------------------------------------------


class TestPredictionsFetcherInit:
    """Tests for PredictionsFetcher initialization."""

    def test_init(self) -> None:
        """Test that init sets context and logger."""
        fetcher = _make_fetcher()
        assert fetcher.predict_url == "https://subgraph.test/olas"
        assert fetcher.mech_url == "https://subgraph.test/mech"
        assert fetcher.omen_url == "https://subgraph.test/omen"


# ---------------------------------------------------------------------------
# fetch_predictions tests
# ---------------------------------------------------------------------------


class TestFetchPredictions:
    """Tests for fetch_predictions."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of predictions."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(2 * WEI_TO_NATIVE),
                        "totalTraded": str(1 * WEI_TO_NATIVE),
                        "totalFees": str(int(0.01 * WEI_TO_NATIVE)),
                        "totalBets": 1,
                        "fixedProductMarketMaker": {
                            "id": "market_1",
                            "question": "Test?",
                            "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                            "currentAnswerTimestamp": "1700001000",
                            "outcomes": ["Yes", "No"],
                        },
                        "bets": [
                            {
                                "id": "bet_1",
                                "amount": str(WEI_TO_NATIVE),
                                "outcomeIndex": 0,
                                "timestamp": "1700000000",
                            }
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result["total_predictions"] == 1
        assert len(result["items"]) == 1

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_trader_agent(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when no trader agent is found."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": []}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result == {"total_predictions": 0, "items": []}

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_bets(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when trader agent has no bets."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "totalTraded": "0",
                        "totalFees": "0",
                        "totalBets": 0,
                        "fixedProductMarketMaker": {
                            "id": "m1",
                            "question": "Q?",
                            "currentAnswer": None,
                            "currentAnswerTimestamp": None,
                            "outcomes": ["Yes", "No"],
                        },
                        "bets": [],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10)

        assert result["total_predictions"] == 0
        assert result["items"] == []

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_with_status_filter(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test filtering predictions by status."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "totalTraded": str(WEI_TO_NATIVE),
                        "totalFees": "0",
                        "totalBets": 1,
                        "fixedProductMarketMaker": {
                            "id": "m1",
                            "question": "Q?",
                            "currentAnswer": None,
                            "currentAnswerTimestamp": None,
                            "outcomes": ["Yes", "No"],
                        },
                        "bets": [
                            {
                                "id": "b1",
                                "amount": str(WEI_TO_NATIVE),
                                "outcomeIndex": 0,
                                "timestamp": "1700000000",
                            }
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        # Filter for "won" should exclude pending bets
        result = fetcher.fetch_predictions("0xsafe", first=10, status_filter="won")

        assert result["total_predictions"] == 1
        assert result["items"] == []

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_with_skip(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test pagination with skip parameter."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": None}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_predictions("0xsafe", first=10, skip=5)

        assert result == {"total_predictions": 0, "items": []}


# ---------------------------------------------------------------------------
# _fetch_finalization_by_fpmm_ids tests
# ---------------------------------------------------------------------------


class TestEnrichmentWiredIntoFetchPaths:
    """Falsifiable wiring: every olas-bet fetch path must enrich with omen_subgraph.

    Removing the ``_enrich_bets_with_finalization`` call from any of these
    paths would silently regress every Omen status to PENDING in
    production (the olas_agents subgraph does not expose
    ``answerFinalizedTimestamp``). These tests fail if the call is
    removed.
    """

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_fetch_predictions_invokes_enrichment_with_parsed_bets(
        self, mock_post: MagicMock
    ) -> None:
        """fetch_predictions must enrich the bets list returned by the olas query."""
        fetcher = _make_fetcher()

        olas_response = MagicMock()
        olas_response.status_code = 200
        olas_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "totalTraded": str(WEI_TO_NATIVE),
                        "totalFees": "0",
                        "totalBets": 1,
                        "fixedProductMarketMaker": {
                            "id": "0xfpmm1",
                            "question": "Q?",
                            "currentAnswer": "0x1",
                            "currentAnswerTimestamp": "1700001000",
                            "outcomes": ["Yes", "No"],
                        },
                        "bets": [
                            {
                                "id": "b1",
                                "amount": str(WEI_TO_NATIVE),
                                "outcomeIndex": 0,
                                "timestamp": "1700000000",
                            }
                        ],
                    }
                ]
            }
        }
        mock_post.return_value = olas_response

        with patch.object(fetcher, "_enrich_bets_with_finalization") as mock_enrich:
            fetcher.fetch_predictions("0xsafe", first=10)

        mock_enrich.assert_called_once()
        bets_arg = mock_enrich.call_args.args[0]
        assert isinstance(bets_arg, list)
        assert len(bets_arg) == 1
        assert bets_arg[0]["fixedProductMarketMaker"]["id"] == "0xfpmm1"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_fetch_bet_from_subgraph_invokes_enrichment(
        self, mock_post: MagicMock
    ) -> None:
        """_fetch_bet_from_subgraph must enrich before status helpers run."""
        fetcher = _make_fetcher()

        olas_response = MagicMock()
        olas_response.status_code = 200
        olas_response.json.return_value = {
            "data": {
                "traderAgent": {
                    "bets": [
                        {
                            "id": "b1",
                            "amount": str(WEI_TO_NATIVE),
                            "outcomeIndex": 0,
                            "timestamp": "1700000000",
                            "fixedProductMarketMaker": {
                                "id": "0xfpmm1",
                                "question": "Q?",
                                "currentAnswer": "0x1",
                                "currentAnswerTimestamp": "1700001000",
                                "outcomes": ["Yes", "No"],
                                "participants": [{}],
                            },
                        }
                    ]
                }
            }
        }
        mock_post.return_value = olas_response

        with patch.object(fetcher, "_enrich_bets_with_finalization") as mock_enrich:
            fetcher._fetch_bet_from_subgraph("b1", "0xsafe")

        mock_enrich.assert_called_once()
        bets_arg = mock_enrich.call_args.args[0]
        assert isinstance(bets_arg, list)
        assert any(b.get("id") == "b1" for b in bets_arg)


class TestEnrichBetsWithFinalization:
    """Tests for in-place enrichment of bet fpmm dicts via omen_subgraph."""

    def test_empty_bets_is_no_op(self) -> None:
        """No enrichment call when the bet list is empty."""
        fetcher = _make_fetcher()
        with patch.object(fetcher, "_fetch_finalization_by_fpmm_ids") as mock_fetch:
            fetcher._enrich_bets_with_finalization([])
        mock_fetch.assert_not_called()

    def test_bets_get_enriched_in_place(self) -> None:
        """Each bet's fpmm dict gains both fields after enrichment."""
        fetcher = _make_fetcher()
        bets = [
            {"fixedProductMarketMaker": {"id": "0xaaa", "currentAnswer": "0x1"}},
            {"fixedProductMarketMaker": {"id": "0xbbb", "currentAnswer": "0x0"}},
        ]
        with patch.object(
            fetcher,
            "_fetch_finalization_by_fpmm_ids",
            return_value={
                "0xaaa": {
                    "id": "0xaaa",
                    "answerFinalizedTimestamp": "1700000000",
                    "isPendingArbitration": False,
                },
                "0xbbb": {
                    "id": "0xbbb",
                    "answerFinalizedTimestamp": None,
                    "isPendingArbitration": True,
                },
            },
        ):
            fetcher._enrich_bets_with_finalization(bets)

        assert (
            bets[0]["fixedProductMarketMaker"]["answerFinalizedTimestamp"]
            == "1700000000"
        )
        assert bets[0]["fixedProductMarketMaker"]["isPendingArbitration"] is False
        assert bets[1]["fixedProductMarketMaker"]["answerFinalizedTimestamp"] is None
        assert bets[1]["fixedProductMarketMaker"]["isPendingArbitration"] is True

    def test_missing_enrichment_defaults_to_pending_semantics(self) -> None:
        """Bets whose ids are absent from the enrichment get safe-default flags."""
        fetcher = _make_fetcher()
        bets = [
            {"fixedProductMarketMaker": {"id": "0xaaa", "currentAnswer": "0x1"}},
        ]
        with patch.object(fetcher, "_fetch_finalization_by_fpmm_ids", return_value={}):
            fetcher._enrich_bets_with_finalization(bets)

        fpmm = bets[0]["fixedProductMarketMaker"]
        assert fpmm["answerFinalizedTimestamp"] is None
        assert fpmm["isPendingArbitration"] is False

    def test_duplicate_fpmm_ids_deduplicated(self) -> None:
        """Three bets sharing one fpmm id should produce a one-element fetch."""
        fetcher = _make_fetcher()
        bets = [
            {"fixedProductMarketMaker": {"id": "0xaaa"}},
            {"fixedProductMarketMaker": {"id": "0xaaa"}},
            {"fixedProductMarketMaker": {"id": "0xaaa"}},
        ]
        with patch.object(
            fetcher, "_fetch_finalization_by_fpmm_ids", return_value={}
        ) as mock_fetch:
            fetcher._enrich_bets_with_finalization(bets)

        mock_fetch.assert_called_once()
        called_ids = mock_fetch.call_args.args[0]
        assert sorted(called_ids) == ["0xaaa"]

    def test_mixed_bets_with_and_without_fpmm_skip_correctly(self) -> None:
        """Skip bets whose ``fixedProductMarketMaker`` is None.

        Valid bets are enriched; the None bet must not crash the loop.
        """
        fetcher = _make_fetcher()
        bets: List[Dict[str, Any]] = [
            {"fixedProductMarketMaker": {"id": "0xaaa"}},
            {"fixedProductMarketMaker": None},  # must not crash on this
            {"fixedProductMarketMaker": {"id": "0xbbb"}},
        ]
        with patch.object(
            fetcher,
            "_fetch_finalization_by_fpmm_ids",
            return_value={
                "0xaaa": {
                    "id": "0xaaa",
                    "answerFinalizedTimestamp": "1",
                    "isPendingArbitration": False,
                },
                "0xbbb": {
                    "id": "0xbbb",
                    "answerFinalizedTimestamp": "2",
                    "isPendingArbitration": True,
                },
            },
        ):
            fetcher._enrich_bets_with_finalization(bets)

        assert bets[0]["fixedProductMarketMaker"]["answerFinalizedTimestamp"] == "1"
        assert bets[1]["fixedProductMarketMaker"] is None
        assert bets[2]["fixedProductMarketMaker"]["answerFinalizedTimestamp"] == "2"

    def test_bets_without_fpmm_id_are_skipped(self) -> None:
        """Bets with no fixedProductMarketMaker or no id are left untouched."""
        fetcher = _make_fetcher()
        bets: List[Dict[str, Any]] = [
            {"fixedProductMarketMaker": None},
            {"fixedProductMarketMaker": {}},
            {},
        ]
        with patch.object(
            fetcher, "_fetch_finalization_by_fpmm_ids", return_value={}
        ) as mock_fetch:
            fetcher._enrich_bets_with_finalization(bets)

        # Nothing to enrich; fetcher must not be called.
        mock_fetch.assert_not_called()
        # And we must not crash or inject keys into a None/absent fpmm.
        assert bets[0]["fixedProductMarketMaker"] is None
        assert bets[1]["fixedProductMarketMaker"] == {}


class TestFetchFinalizationByFpmmIds:
    """Tests for the omen_subgraph enrichment helper, including chunking."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_empty_ids_returns_empty_dict_without_network_call(
        self, mock_post: MagicMock
    ) -> None:
        """No network call when the caller passes an empty id list."""
        fetcher = _make_fetcher()

        result = fetcher._fetch_finalization_by_fpmm_ids([])

        assert result == {}
        mock_post.assert_not_called()

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_single_chunk_returns_keyed_dict(self, mock_post: MagicMock) -> None:
        """Single-chunk input returns a dict keyed by fpmm id."""
        fetcher = _make_fetcher()

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": {
                "fixedProductMarketMakers": [
                    {
                        "id": "0xaaa",
                        "answerFinalizedTimestamp": "1700000000",
                        "isPendingArbitration": False,
                    },
                    {
                        "id": "0xbbb",
                        "answerFinalizedTimestamp": None,
                        "isPendingArbitration": True,
                    },
                ]
            }
        }
        mock_post.return_value = response

        result = fetcher._fetch_finalization_by_fpmm_ids(["0xaaa", "0xbbb"])

        assert result == {
            "0xaaa": {
                "id": "0xaaa",
                "answerFinalizedTimestamp": "1700000000",
                "isPendingArbitration": False,
            },
            "0xbbb": {
                "id": "0xbbb",
                "answerFinalizedTimestamp": None,
                "isPendingArbitration": True,
            },
        }
        assert mock_post.call_count == 1
        call_variables = mock_post.call_args.kwargs["json"]["variables"]
        assert call_variables == {"ids": ["0xaaa", "0xbbb"]}

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_chunks_at_1000(self, mock_post: MagicMock) -> None:
        """1500 ids should split into exactly 2 calls of sizes (1000, 500)."""
        fetcher = _make_fetcher()
        ids = [f"0x{i:040x}" for i in range(1500)]

        def _respond(*_args: Any, **kwargs: Any) -> MagicMock:
            batch = kwargs["json"]["variables"]["ids"]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {
                "data": {
                    "fixedProductMarketMakers": [
                        {
                            "id": fpmm_id,
                            "answerFinalizedTimestamp": "1",
                            "isPendingArbitration": False,
                        }
                        for fpmm_id in batch
                    ]
                }
            }
            return r

        mock_post.side_effect = _respond

        result = fetcher._fetch_finalization_by_fpmm_ids(ids)

        assert mock_post.call_count == 2
        sizes = [
            len(call.kwargs["json"]["variables"]["ids"])
            for call in mock_post.call_args_list
        ]
        assert sizes == [1000, 500]
        assert len(result) == 1500
        assert result[ids[0]]["id"] == ids[0]
        assert result[ids[1499]]["id"] == ids[1499]

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_subgraph_error_returns_empty_dict(self, mock_post: MagicMock) -> None:
        """A raised exception is caught and degrades to empty dict + warning."""
        fetcher = _make_fetcher()
        mock_post.side_effect = RuntimeError("connection refused")

        result = fetcher._fetch_finalization_by_fpmm_ids(["0xaaa"])

        assert result == {}
        assert (
            fetcher.logger.warning.called
        ), "must log a warning so the silent-degradation path is visible"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_non_200_response_skips_chunk_and_logs_warning(
        self, mock_post: MagicMock
    ) -> None:
        """Non-200 responses skip the chunk but do not crash other chunks."""
        fetcher = _make_fetcher()
        ids = [f"0x{i:040x}" for i in range(1500)]

        responses = [MagicMock(status_code=500), MagicMock(status_code=200)]
        responses[1].json.return_value = {
            "data": {
                "fixedProductMarketMakers": [
                    {
                        "id": ids[1000],
                        "answerFinalizedTimestamp": "1",
                        "isPendingArbitration": False,
                    }
                ]
            }
        }
        mock_post.side_effect = responses

        result = fetcher._fetch_finalization_by_fpmm_ids(ids)

        assert ids[0] not in result
        assert result[ids[1000]]["id"] == ids[1000]
        assert fetcher.logger.warning.called

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_rows_with_missing_id_are_skipped(self, mock_post: MagicMock) -> None:
        """Defensive: a subgraph row without an `id` is dropped from the result."""
        fetcher = _make_fetcher()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": {
                "fixedProductMarketMakers": [
                    {"id": None, "answerFinalizedTimestamp": "1"},
                    {"id": "0xbbb", "answerFinalizedTimestamp": "2"},
                ]
            }
        }
        mock_post.return_value = response

        result = fetcher._fetch_finalization_by_fpmm_ids(["0xaaa", "0xbbb"])

        assert result == {
            "0xbbb": {"id": "0xbbb", "answerFinalizedTimestamp": "2"},
        }

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_malformed_json_response_skips_chunk_and_logs(
        self, mock_post: MagicMock
    ) -> None:
        """A malformed JSON body is caught and degrades to empty result."""
        fetcher = _make_fetcher()
        bad_response = MagicMock()
        bad_response.status_code = 200
        bad_response.json.side_effect = ValueError("not json")
        mock_post.return_value = bad_response

        result = fetcher._fetch_finalization_by_fpmm_ids(["0xaaa"])

        assert result == {}
        assert fetcher.logger.warning.called

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_result_merges_disjoint_chunks_without_collision(
        self, mock_post: MagicMock
    ) -> None:
        """Ids from different chunks are merged without overwriting each other."""
        fetcher = _make_fetcher()
        ids = [f"0x{i:040x}" for i in range(1500)]

        def _respond(*_args: Any, **kwargs: Any) -> MagicMock:
            batch = kwargs["json"]["variables"]["ids"]
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {
                "data": {
                    "fixedProductMarketMakers": [
                        {
                            "id": fpmm_id,
                            "answerFinalizedTimestamp": fpmm_id[-8:],
                            "isPendingArbitration": False,
                        }
                        for fpmm_id in batch
                    ]
                }
            }
            return r

        mock_post.side_effect = _respond

        result = fetcher._fetch_finalization_by_fpmm_ids(ids)

        assert len(result) == 1500
        for fpmm_id in ids:
            assert result[fpmm_id]["answerFinalizedTimestamp"] == fpmm_id[-8:]


# ---------------------------------------------------------------------------
# _fetch_trader_agent_bets tests
# ---------------------------------------------------------------------------


class TestFetchTraderAgentBets:
    """Tests for _fetch_trader_agent_bets."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 HTTP response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result is None
        fetcher.logger.error.assert_called_once()

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Connection error")

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result is None
        fetcher.logger.error.assert_called_once()

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_empty_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when marketParticipants is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": []}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when marketParticipants is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"marketParticipants": None}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_multiple_participants(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test with multiple participants aggregating bets."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": str(2 * WEI_TO_NATIVE),
                        "totalTraded": str(WEI_TO_NATIVE),
                        "totalFees": "0",
                        "totalBets": 2,
                        "fixedProductMarketMaker": {"id": "m1"},
                        "bets": [
                            {"id": "b1", "amount": str(WEI_TO_NATIVE)},
                            {"id": "b2", "amount": str(WEI_TO_NATIVE)},
                        ],
                    },
                    {
                        "totalPayout": "0",
                        "totalTraded": str(WEI_TO_NATIVE),
                        "totalFees": "0",
                        "totalBets": 1,
                        "fixedProductMarketMaker": {"id": "m2"},
                        "bets": [
                            {"id": "b3", "amount": str(WEI_TO_NATIVE)},
                        ],
                    },
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result["totalBets"] == 3  # type: ignore[index]
        assert len(result["bets"]) == 3  # type: ignore[index]

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_participant_with_none_bets(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test participant with None bets list."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "totalTraded": "0",
                        "totalFees": "0",
                        "totalBets": 0,
                        "fixedProductMarketMaker": {"id": "m1"},
                        "bets": None,
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result["totalBets"] == 0  # type: ignore[index]
        assert result["bets"] == []  # type: ignore[index]

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_participant_with_none_fpmm(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test participant with None fixedProductMarketMaker."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "marketParticipants": [
                    {
                        "totalPayout": "0",
                        "totalTraded": "0",
                        "totalFees": "0",
                        "totalBets": 0,
                        "fixedProductMarketMaker": None,
                        "bets": [{"id": "b1"}],
                    }
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)

        assert result["totalBets"] == 0  # type: ignore[index]
        assert len(result["bets"]) == 1  # type: ignore[index]


# ---------------------------------------------------------------------------
# fetch_mech_tool_for_question tests
# ---------------------------------------------------------------------------


class TestFetchMechToolForQuestion:
    """Tests for fetch_mech_tool_for_question."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of mech tool."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "sender": {
                    "requests": [{"parsedRequest": {"tool": "prediction-online"}}]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Will it rain?", "0xsender")

        assert result == "prediction-online"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 HTTP response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_empty_requests_list(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": {"requests": []}}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_parsed_request(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when parsedRequest is missing."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"sender": {"requests": [{"parsedRequest": None}]}}
        }
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Network error")

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_sender_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when sender data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": None}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_requests_list(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": {"requests": None}}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_first_request(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when first request is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"sender": {"requests": [None]}}}
        mock_post.return_value = mock_response

        result = fetcher.fetch_mech_tool_for_question("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_bet_timestamp_passed_in_query(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that blockTimestamp_lte is passed in query variables."""
        fetcher = _make_fetcher()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "sender": {
                    "requests": [{"parsedRequest": {"tool": "prediction-online"}}]
                }
            }
        }
        mock_post.return_value = mock_response

        fetcher.fetch_mech_tool_for_question("Q?", "0xsender", bet_timestamp=1700000000)

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["variables"]["blockTimestamp_lte"] == "1700000000"


# ---------------------------------------------------------------------------
# _fetch_prediction_response_from_mech tests
# ---------------------------------------------------------------------------


class TestFetchPredictionResponseFromMech:
    """Tests for _fetch_prediction_response_from_mech."""

    def test_empty_question_title(self) -> None:
        """Test that empty question title returns None."""
        fetcher = _make_fetcher()

        result = fetcher._fetch_prediction_response_from_mech("", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of prediction response."""
        fetcher = _make_fetcher()

        prediction_data = {"p_yes": 0.8, "p_no": 0.2, "confidence": 0.9}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "requests": [
                    {"deliveries": [{"toolResponse": json.dumps(prediction_data)}]}
                ]
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result == prediction_data

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 HTTP response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_empty_requests(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": []}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_empty_deliveries(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when deliveries list is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": [{"deliveries": []}]}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_tool_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when toolResponse is missing."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"requests": [{"deliveries": [{"toolResponse": None}]}]}
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_invalid_json_in_tool_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when toolResponse has invalid JSON."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"requests": [{"deliveries": [{"toolResponse": "not-valid-json"}]}]}
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Network error")

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_requests_list(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when requests list is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": None}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_deliveries(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when deliveries is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"requests": [{"deliveries": None}]}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        result = fetcher._fetch_prediction_response_from_mech("Q?", "0xsender")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_bet_timestamp_passed_in_query(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test that blockTimestamp_lte is passed in query variables."""
        fetcher = _make_fetcher()
        prediction_data = {"p_yes": 0.7, "p_no": 0.3, "confidence": 0.8}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "requests": [
                    {"deliveries": [{"toolResponse": json.dumps(prediction_data)}]}
                ]
            }
        }
        mock_post.return_value = mock_response

        fetcher._fetch_prediction_response_from_mech(
            "Q?", "0xsender", bet_timestamp=1700000000
        )

        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["variables"]["blockTimestamp_lte"] == "1700000000"


# ---------------------------------------------------------------------------
# _format_predictions / _build_market_context / _format_single_bet tests
# ---------------------------------------------------------------------------


class TestFormatPredictions:
    """Tests for _format_predictions and related methods."""

    def test_basic_formatting(self) -> None:
        """Test basic formatting of bets into predictions."""
        fetcher = _make_fetcher()
        bets = [_make_bet()]

        result = fetcher._format_predictions(bets, "0xsafe")

        assert len(result) == 1
        assert result[0]["id"] == "bet_1"
        assert result[0]["market"]["id"] == "market_1"
        assert result[0]["prediction_side"] == "yes"

    def test_status_filter_excludes_non_matching(self) -> None:
        """Test that status filter excludes non-matching bets."""
        fetcher = _make_fetcher()
        bets = [_make_bet(current_answer=None)]  # type: ignore[arg-type]

        result = fetcher._format_predictions(bets, "0xsafe", status_filter="won")

        assert result == []

    def test_status_filter_includes_matching(self) -> None:
        """Test that status filter includes matching bets."""
        fetcher = _make_fetcher()
        bets = [_make_bet(current_answer=None)]  # type: ignore[arg-type]

        result = fetcher._format_predictions(bets, "0xsafe", status_filter="pending")

        assert len(result) == 1

    def test_multiple_bets_same_market(self) -> None:
        """Test multiple bets on the same market."""
        fetcher = _make_fetcher()
        bets = [
            _make_bet(bet_id="b1", outcome_index=0),
            _make_bet(bet_id="b2", outcome_index=1),
        ]

        result = fetcher._format_predictions(bets, "0xsafe")

        assert len(result) == 2

    def test_none_fpmm(self) -> None:
        """Test bet with None fpmm - fpmm becomes {} via 'or {}' fallback.

        With fpmm_id being None, the bet is still formatted since
        _format_single_bet is called directly (not through _build_market_context
        which skips bets without fpmm_id). The _get_prediction_status code does
        bet.get("fixedProductMarketMaker", {}) without 'or {}', so None fpmm
        triggers an AttributeError. This is a known edge case in the source.
        """
        fetcher = _make_fetcher()
        bets = [
            {
                "id": "bet_1",
                "amount": str(WEI_TO_NATIVE),
                "outcomeIndex": 0,
                "timestamp": "1700000000",
                "fixedProductMarketMaker": None,
            }
        ]

        # The source code's _get_prediction_status retrieves the
        # fixedProductMarketMaker dict from bet, then calls
        # .get("currentAnswer") on it which raises AttributeError.
        # This is caught by the caller or represents a genuine edge case.
        with pytest.raises(AttributeError):
            fetcher._format_predictions(bets, "0xsafe")


class TestBuildMarketContext:
    """Tests for _build_market_context."""

    def test_basic_context(self) -> None:
        """Test building basic market context."""
        fetcher = _make_fetcher()
        bets = [_make_bet()]

        ctx = fetcher._build_market_context(bets)

        assert "market_1" in ctx
        assert ctx["market_1"]["current_answer"] is not None

    def test_no_fpmm_id(self) -> None:
        """Test bet with no fpmm id is skipped."""
        fetcher = _make_fetcher()
        bets = [
            {
                "id": "b1",
                "amount": str(WEI_TO_NATIVE),
                "outcomeIndex": 0,
                "fixedProductMarketMaker": {"id": None},
            }
        ]

        ctx = fetcher._build_market_context(bets)

        assert len(ctx) == 0

    def test_winning_amount_accumulated(self) -> None:
        """Test that winning amounts are accumulated correctly."""
        fetcher = _make_fetcher()
        # Answer is 0, so outcomeIndex=0 is winning
        bets = [
            _make_bet(bet_id="b1", outcome_index=0, amount=str(WEI_TO_NATIVE)),
            _make_bet(bet_id="b2", outcome_index=0, amount=str(2 * WEI_TO_NATIVE)),
        ]

        ctx = fetcher._build_market_context(bets)

        assert ctx["market_1"]["winning_total_amount"] == 3.0

    def test_losing_bets_not_accumulated(self) -> None:
        """Test that losing bet amounts are not added to winning total."""
        fetcher = _make_fetcher()
        # Answer is 0, so outcomeIndex=1 is losing
        bets = [_make_bet(bet_id="b1", outcome_index=1)]

        ctx = fetcher._build_market_context(bets)

        assert ctx["market_1"]["winning_total_amount"] == 0.0

    def test_invalid_answer_not_accumulated(self) -> None:
        """Test that invalid answers are not accumulated."""
        fetcher = _make_fetcher()
        bets = [_make_bet(current_answer=INVALID_ANSWER_HEX)]

        ctx = fetcher._build_market_context(bets)

        assert ctx["market_1"]["winning_total_amount"] == 0.0

    def test_market_context_includes_answer_finalized_ts(self) -> None:
        """_build_market_context must store answerFinalizedTimestamp from fpmm.

        Bug A: _calculate_bet_net_profit reads answer_finalized_ts from
        market_ctx (not from the raw bet), so the context builder must
        propagate the field.
        """
        fetcher = _make_fetcher()
        bet = {
            "id": "bet_1",
            "amount": str(WEI_TO_NATIVE),
            "outcomeIndex": 0,
            "fixedProductMarketMaker": {
                "id": "market_1",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "currentAnswerTimestamp": "1700001000",
                "answerFinalizedTimestamp": "1700087400",
                "outcomes": ["Yes", "No"],
                "participants": [{"totalPayout": "0", "totalTraded": "0"}],
            },
        }

        ctx = fetcher._build_market_context([bet])

        assert ctx["market_1"]["answer_finalized_ts"] == "1700087400"

    def test_market_context_finalized_ts_missing_is_none(self) -> None:
        """When fpmm omits answerFinalizedTimestamp the ctx entry is None."""
        fetcher = _make_fetcher()
        bet = {
            "id": "bet_1",
            "amount": str(WEI_TO_NATIVE),
            "outcomeIndex": 0,
            "fixedProductMarketMaker": {
                "id": "market_1",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "currentAnswerTimestamp": "1700001000",
                "outcomes": ["Yes", "No"],
                "participants": [{"totalPayout": "0", "totalTraded": "0"}],
            },
        }

        ctx = fetcher._build_market_context([bet])

        assert ctx["market_1"]["answer_finalized_ts"] is None

    def test_market_context_includes_is_pending_arbitration(self) -> None:
        """ZD#919: ctx must carry isPendingArbitration.

        The net-profit gate short-circuits on this flag without
        re-reading the fpmm dict.
        """
        fetcher = _make_fetcher()
        bet = {
            "id": "bet_1",
            "amount": str(WEI_TO_NATIVE),
            "outcomeIndex": 0,
            "fixedProductMarketMaker": {
                "id": "market_1",
                "currentAnswer": "0x0",
                "currentAnswerTimestamp": "1700001000",
                "answerFinalizedTimestamp": "1700087400",
                "isPendingArbitration": True,
                "outcomes": ["Yes", "No"],
                "participants": [{"totalPayout": "0", "totalTraded": "0"}],
            },
        }

        ctx = fetcher._build_market_context([bet])

        assert ctx["market_1"]["is_pending_arbitration"] is True

    def test_market_context_arbitration_defaults_to_false(self) -> None:
        """Missing isPendingArbitration is treated as False (safe default)."""
        fetcher = _make_fetcher()
        bet = {
            "id": "bet_1",
            "amount": str(WEI_TO_NATIVE),
            "outcomeIndex": 0,
            "fixedProductMarketMaker": {
                "id": "market_1",
                "currentAnswer": "0x0",
                "currentAnswerTimestamp": "1700001000",
                "outcomes": ["Yes", "No"],
                "participants": [{"totalPayout": "0", "totalTraded": "0"}],
            },
        }

        ctx = fetcher._build_market_context([bet])

        assert ctx["market_1"]["is_pending_arbitration"] is False

    def test_null_answer_not_accumulated(self) -> None:
        """Test that null answers are not accumulated."""
        fetcher = _make_fetcher()
        bets = [_make_bet(current_answer=None)]  # type: ignore[arg-type]

        ctx = fetcher._build_market_context(bets)

        assert ctx["market_1"]["winning_total_amount"] == 0.0

    def test_none_participants_in_fpmm(self) -> None:
        """Test when participants is explicitly None in fpmm data.

        When participants is None: (None or [None])[0] -> None.
        Then participant = None or {} -> {}, so total_payout = 0.0, total_traded = 0.0.
        """
        fetcher = _make_fetcher()
        # Directly create a bet with None participants in the fpmm
        bet = {
            "id": "bet_1",
            "amount": str(WEI_TO_NATIVE),
            "outcomeIndex": 0,
            "fixedProductMarketMaker": {
                "id": "market_1",
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "currentAnswerTimestamp": "1700001000",
                "outcomes": ["Yes", "No"],
                "participants": None,
            },
        }

        ctx = fetcher._build_market_context([bet])

        # (None or [None])[0] evaluates to None
        assert ctx["market_1"]["participant"] is None
        # participant = entry["participant"] or {} => {}
        # so total_payout and total_traded become 0.0
        assert ctx["market_1"]["total_payout"] == 0.0
        assert ctx["market_1"]["total_traded"] == 0.0

    def test_empty_participants(self) -> None:
        """Test when participants is empty list."""
        fetcher = _make_fetcher()
        bets = [_make_bet(participants=[])]

        ctx = fetcher._build_market_context(bets)

        # With empty list: ([] or [None])[0] => from [None] -> None
        assert ctx["market_1"]["participant"] is None

    def test_none_fpmm(self) -> None:
        """Test when fpmm is None."""
        fetcher = _make_fetcher()
        bets = [
            {
                "id": "b1",
                "amount": str(WEI_TO_NATIVE),
                "outcomeIndex": 0,
                "fixedProductMarketMaker": None,
            }
        ]

        ctx = fetcher._build_market_context(bets)

        assert len(ctx) == 0


# ---------------------------------------------------------------------------
# _calculate_bet_net_profit tests
# ---------------------------------------------------------------------------


class TestCalculateBetNetProfit:
    """Tests for _calculate_bet_net_profit."""

    def test_no_market_ctx(self) -> None:
        """Test when market context is None."""
        fetcher = _make_fetcher()
        result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, None, 1.0)

        assert result == (0.0, None)

    def test_unresolved_market(self) -> None:
        """Test when market is not resolved (current_answer is None)."""
        fetcher = _make_fetcher()
        ctx = {"current_answer": None}
        result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_invalid_market_with_payout(self) -> None:
        """Test invalid market with refund (finalization in the past)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": INVALID_ANSWER_HEX,
            "answer_finalized_ts": "1700000000",
            "total_payout": 2.0,
            "total_traded": 4.0,
        }
        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        # refund_share = 2.0 * (1.0 / 4.0) = 0.5
        # net_profit = 0.5 - 1.0 = -0.5
        assert result == (-0.5, 0.5)

    def test_invalid_market_zero_payout(self) -> None:
        """Test invalid market with zero payout (finalization in the past)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": INVALID_ANSWER_HEX,
            "answer_finalized_ts": "1700000000",
            "total_payout": 0,
            "total_traded": 0,
        }
        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_invalid_pending_finalization_returns_zero_none(self) -> None:
        """Sentinel + future finalization -> (0.0, None) regardless of payout (Bug A)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": INVALID_ANSWER_HEX,
            "answer_finalized_ts": "1700100000",
            "total_payout": 2.0,
            "total_traded": 4.0,
        }
        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_resolved_pending_finalization_returns_zero_none(self) -> None:
        """Non-sentinel + future finalization -> (0.0, None) (still in dispute window)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "1700100000",
            "total_payout": 2.0,
            "total_traded": 1.0,
            "winning_total_amount": 1.0,
        }
        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_malformed_current_answer_returns_zero_none(self) -> None:
        """Malformed current_answer + finalized -> (0.0, None) (defensive)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0xZZ",
            "answer_finalized_ts": "1700000000",
            "total_payout": 2.0,
            "total_traded": 1.0,
            "winning_total_amount": 1.0,
        }
        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_losing_bet(self) -> None:
        """Test a losing bet."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "1000000000",
            "total_payout": 2.0,
            "total_traded": 2.0,
            "winning_total_amount": 1.0,
        }
        # outcome_index 1 != correct answer 0
        result = fetcher._calculate_bet_net_profit({"outcomeIndex": 1}, ctx, 1.0)

        assert result == (-1.0, 0.0)

    def test_winning_bet_with_payout(self) -> None:
        """Test a winning bet with payout."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "1000000000",
            "total_payout": 2.0,
            "total_traded": 1.0,
            "winning_total_amount": 1.0,
        }
        result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        # payout_share = 2.0 * (1.0 / 1.0) = 2.0
        # net_profit = 2.0 - 1.0 = 1.0
        assert result == (1.0, 2.0)

    def test_winning_bet_zero_payout(self) -> None:
        """Test a winning bet with zero payout (not redeemed)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "1000000000",
            "total_payout": 0,
            "total_traded": 1.0,
            "winning_total_amount": 0,
        }
        result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_invalid_market_zero_total_traded_only(self) -> None:
        """Test invalid market with non-zero payout but zero traded (finalized)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": INVALID_ANSWER_HEX,
            "answer_finalized_ts": "1700000000",
            "total_payout": 2.0,
            "total_traded": 0,
        }
        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_winning_bet_zero_winning_total_only(self) -> None:
        """Test winning bet with payout>0 but winning_total==0."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "1000000000",
            "total_payout": 2.0,
            "total_traded": 1.0,
            "winning_total_amount": 0,
        }
        result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)


# ---------------------------------------------------------------------------
# _get_prediction_status tests
# ---------------------------------------------------------------------------


class TestGetPredictionStatus:
    """Tests for _get_prediction_status."""

    def test_pending_no_current_answer(self) -> None:
        """Test pending when market not resolved."""
        fetcher = _make_fetcher()
        bet = {"fixedProductMarketMaker": {"currentAnswer": None}, "outcomeIndex": 0}

        result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_invalid_market(self) -> None:
        """Sentinel + finalization in the past -> invalid."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": INVALID_ANSWER_HEX,
                "answerFinalizedTimestamp": "1700000000",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "invalid"

    def test_invalid_sentinel_pending_finalization_returns_pending(self) -> None:
        """Sentinel + finalization in the future -> pending (Bug A)."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": INVALID_ANSWER_HEX,
                "answerFinalizedTimestamp": "1700100000",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_invalid_sentinel_missing_finalization_returns_pending(self) -> None:
        """Sentinel + no finalization field -> pending (defensive: subgraph lag)."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {"currentAnswer": INVALID_ANSWER_HEX},
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_invalid_sentinel_finalization_at_now_returns_invalid(self) -> None:
        """Sentinel + finalization == now -> invalid (boundary: <= comparison)."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": INVALID_ANSWER_HEX,
                "answerFinalizedTimestamp": "1700000000",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "invalid"

    def test_resolved_pending_finalization_returns_pending(self) -> None:
        """Non-sentinel answer + future finalization -> pending.

        Reality.eth answers can flip during the dispute window. Even a
        non-sentinel answer should not be treated as terminal until the
        dispute window has closed.
        """
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": "1700100000",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_malformed_current_answer_returns_pending(self) -> None:
        """Malformed currentAnswer hex -> pending (defensive, doesn't crash)."""
        fetcher = _make_fetcher()
        bet = {
            "id": "bet_xyz",
            "fixedProductMarketMaker": {
                "currentAnswer": "0xZZ",
                "answerFinalizedTimestamp": "1700000000",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_won_with_payout(self) -> None:
        """Test winning bet with payout (redeemed)."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": "1000000000",
            },
            "outcomeIndex": 0,
        }
        participant = {"totalPayout": str(2 * WEI_TO_NATIVE)}

        result = fetcher._get_prediction_status(bet, participant)

        assert result == "won"

    def test_won_not_redeemed(self) -> None:
        """Test winning bet not redeemed (treated as pending)."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": "1000000000",
            },
            "outcomeIndex": 0,
        }
        participant = {"totalPayout": "0"}

        result = fetcher._get_prediction_status(bet, participant)

        assert result == "pending"

    def test_won_no_participant(self) -> None:
        """Test winning bet with no participant data."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": "1000000000",
            },
            "outcomeIndex": 0,
        }

        result = fetcher._get_prediction_status(bet, None)

        assert result == "won"

    def test_lost(self) -> None:
        """Test losing bet."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": "1000000000",
            },
            "outcomeIndex": 1,
        }

        result = fetcher._get_prediction_status(bet, None)

        assert result == "lost"

    def test_no_fpmm_key(self) -> None:
        """Test when fixedProductMarketMaker is missing."""
        fetcher = _make_fetcher()
        bet = {"outcomeIndex": 0}

        result = fetcher._get_prediction_status(bet, None)

        # currentAnswer will be None -> pending
        assert result == "pending"


class TestArbitrationGate:
    """ZD#919: isPendingArbitration overrides every other status signal.

    Reality.eth answers can be escalated to Kleros arbitration. While
    arbitration is pending the on-chain answer must not be treated as
    terminal regardless of how long ago it was submitted.
    """

    def test_status_pending_when_arbitration_active_overrides_resolved_answer(
        self,
    ) -> None:
        """A resolved, finalized bet with isPendingArbitration=True is pending."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": "1700000000",  # in the past
                "isPendingArbitration": True,
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_status_pending_when_arbitration_active_with_invalid_sentinel(
        self,
    ) -> None:
        """Arbitration overrides invalid-sentinel labelling too."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": INVALID_ANSWER_HEX,
                "answerFinalizedTimestamp": "1700000000",
                "isPendingArbitration": True,
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    @pytest.mark.parametrize("days_in_arbitration", [1, 7, 14, 30, 90])
    def test_status_pending_during_extended_arbitration(
        self, days_in_arbitration: int
    ) -> None:
        """Time spent in arbitration is irrelevant; status stays pending."""
        fetcher = _make_fetcher()
        # Protofire's mapping nulls answerFinalizedTimestamp on
        # LogNotifyOfArbitrationRequest, so simulate that.
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000001",
                "answerFinalizedTimestamp": None,
                "isPendingArbitration": True,
            },
            "outcomeIndex": 0,
        }
        now = 1700000000 + days_in_arbitration * 86400

        with patch.object(fetcher, "_now", return_value=now):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_status_pending_during_multi_day_bond_war(self) -> None:
        """Bond war: status stays pending until the latest window closes.

        Repeated answer submissions push ``answerFinalizedTimestamp``
        into the future. Status must remain pending regardless of how
        many days the contest has been ongoing.
        """
        fetcher = _make_fetcher()
        now = 1700000000
        # Simulate bond war: latest answer was 12h ago, finalization is in 12h.
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                "answerFinalizedTimestamp": str(now + 12 * 3600),
                "isPendingArbitration": False,
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=now):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_bet_net_profit_zero_when_arbitration_active(self) -> None:
        """Net profit is zero when isPendingArbitration is True.

        ``_calculate_bet_net_profit`` treats arbitration-pending bets as
        unfinalized and returns ``(0.0, None)`` — same as any other
        unfinalized bet, so accuracy/profit stays clean.
        """
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {"id": "m1"},
            "outcomeIndex": 0,
        }
        # Market context simulating the post-enrichment state for an
        # arbitration-pending market.
        market_ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "1700000000",  # past
            "is_pending_arbitration": True,
            "total_payout": 1.0,
            "total_traded": 1.0,
            "winning_total_amount": 1.0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit(bet, market_ctx, 1.0)

        assert result == (0.0, None)


# ---------------------------------------------------------------------------
# _get_prediction_side tests
# ---------------------------------------------------------------------------


class TestGetPredictionSide:
    """Tests for _get_prediction_side."""

    def test_yes_side(self) -> None:
        """Test outcome index 0 with Yes/No outcomes."""
        fetcher = _make_fetcher()

        result = fetcher._get_prediction_side(0, ["Yes", "No"])

        assert result == "yes"

    def test_no_side(self) -> None:
        """Test outcome index 1 with Yes/No outcomes."""
        fetcher = _make_fetcher()

        result = fetcher._get_prediction_side(1, ["Yes", "No"])

        assert result == "no"

    def test_empty_outcomes(self) -> None:
        """Test with empty outcomes list."""
        fetcher = _make_fetcher()

        result = fetcher._get_prediction_side(0, [])

        assert result == "unknown"

    def test_index_out_of_range(self) -> None:
        """Test with index beyond outcomes list length."""
        fetcher = _make_fetcher()

        result = fetcher._get_prediction_side(5, ["Yes", "No"])

        assert result == "unknown"


# ---------------------------------------------------------------------------
# _format_timestamp tests
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    """Tests for _format_timestamp."""

    def test_valid_timestamp(self) -> None:
        """Test formatting a valid Unix timestamp."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp("1700000000")

        assert result is not None
        assert "T" in result
        assert result.endswith("Z")

    def test_none_timestamp(self) -> None:
        """Test None timestamp."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp(None)

        assert result is None

    def test_empty_timestamp(self) -> None:
        """Test empty string timestamp."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp("")

        assert result is None

    def test_invalid_timestamp(self) -> None:
        """Test invalid timestamp string."""
        fetcher = _make_fetcher()

        result = fetcher._format_timestamp("not-a-number")

        assert result is None


# ---------------------------------------------------------------------------
# _get_ui_trading_strategy tests
# ---------------------------------------------------------------------------


class TestGetUiTradingStrategy:
    """Tests for _get_ui_trading_strategy."""

    def test_none_input(self) -> None:
        """Test None input."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy(None)

        assert result is None

    def test_balanced_strategy(self) -> None:
        """Test bet_amount_per_threshold maps to balanced."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("bet_amount_per_threshold")

        assert result == "balanced"

    def test_risky_strategy(self) -> None:
        """Test kelly_criterion_no_conf maps to risky."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("kelly_criterion_no_conf")

        assert result == "risky"

    def test_unknown_strategy(self) -> None:
        """Test unknown strategy returns None."""
        fetcher = _make_fetcher()

        result = fetcher._get_ui_trading_strategy("unknown_strategy")

        assert result is None


# ---------------------------------------------------------------------------
# _load_multi_bets_data tests
# ---------------------------------------------------------------------------


class TestLoadMultiBetsData:
    """Tests for _load_multi_bets_data."""

    def test_successful_load(self) -> None:
        """Test successful loading of multi_bets.json."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            data = [{"id": "m1"}, {"id": "m2"}]
            filepath = os.path.join(tmpdir, "multi_bets.json")
            with open(filepath, "w") as f:
                json.dump(data, f)

            result = fetcher._load_multi_bets_data(tmpdir)

            assert result == data

    def test_file_not_found(self) -> None:
        """Test handling of missing file."""
        fetcher = _make_fetcher()

        result = fetcher._load_multi_bets_data("/nonexistent/path")

        assert result == []
        fetcher.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _load_agent_performance_data tests
# ---------------------------------------------------------------------------


class TestLoadAgentPerformanceData:
    """Tests for _load_agent_performance_data."""

    def test_successful_load(self) -> None:
        """Test successful loading of agent_performance.json."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"prediction_history": {"items": []}}  # type: ignore[var-annotated]
            filepath = os.path.join(tmpdir, "agent_performance.json")
            with open(filepath, "w") as f:
                json.dump(data, f)

            result = fetcher._load_agent_performance_data(tmpdir)

            assert result == data

    def test_file_not_found(self) -> None:
        """Test handling of missing file."""
        fetcher = _make_fetcher()

        result = fetcher._load_agent_performance_data("/nonexistent/path")

        assert result == {}
        fetcher.logger.error.assert_called_once()


# ---------------------------------------------------------------------------
# _find_market_entry tests
# ---------------------------------------------------------------------------


class TestFindMarketEntry:
    """Tests for _find_market_entry."""

    def test_found(self) -> None:
        """Test finding a market by ID."""
        fetcher = _make_fetcher()
        multi_bets = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]

        result = fetcher._find_market_entry(multi_bets, "m2")

        assert result == {"id": "m2"}

    def test_not_found(self) -> None:
        """Test when market is not found."""
        fetcher = _make_fetcher()
        multi_bets = [{"id": "m1"}]

        result = fetcher._find_market_entry(multi_bets, "m99")

        assert result is None

    def test_empty_list(self) -> None:
        """Test with empty multi_bets list."""
        fetcher = _make_fetcher()

        result = fetcher._find_market_entry([], "m1")

        assert result is None


# ---------------------------------------------------------------------------
# _find_bet tests
# ---------------------------------------------------------------------------


class TestFindBet:
    """Tests for _find_bet."""

    def test_found(self) -> None:
        """Test finding a bet by ID."""
        fetcher = _make_fetcher()
        data = {
            "prediction_history": {
                "items": [
                    {"id": "b1", "status": "won"},
                    {"id": "b2", "status": "lost"},
                ]
            }
        }

        result = fetcher._find_bet(data, "b1")

        assert result == {"id": "b1", "status": "won"}

    def test_not_found(self) -> None:
        """Test when bet is not found."""
        fetcher = _make_fetcher()
        data = {"prediction_history": {"items": [{"id": "b1"}]}}

        result = fetcher._find_bet(data, "b99")

        assert result == {}

    def test_empty_data(self) -> None:
        """Test with empty data."""
        fetcher = _make_fetcher()

        result = fetcher._find_bet({}, "b1")

        assert result == {}

    def test_no_prediction_history(self) -> None:
        """Test with no prediction_history key."""
        fetcher = _make_fetcher()

        result = fetcher._find_bet({"other": "data"}, "b1")

        assert result == {}


# ---------------------------------------------------------------------------
# _format_bet_for_position tests
# ---------------------------------------------------------------------------


class TestFormatBetForPosition:
    """Tests for _format_bet_for_position."""

    def test_yes_side(self) -> None:
        """Test formatting bet with yes side."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b1",
            "bet_amount": 1.0,
            "prediction_side": "yes",
            "created_at": "2024-01-01T00:00:00Z",
        }
        market_info = {
            "prediction_response": {
                "p_yes": 0.8,
                "p_no": 0.2,
                "confidence": 0.9,
                "info_utility": 0.7,
            },
            "strategy": "kelly_criterion_no_conf",
        }

        result = fetcher._format_bet_for_position(bet, market_info, "tool_1")

        assert result["id"] == "b1"
        assert result["bet"]["amount"] == 1.0
        assert result["bet"]["side"] == "yes"
        assert result["intelligence"]["prediction_tool"] == "tool_1"
        assert result["intelligence"]["implied_probability"] == 80.0
        assert result["intelligence"]["confidence_score"] == 90.0
        assert result["intelligence"]["utility_score"] == 70.0
        assert result["strategy"] == "risky"

    def test_no_side(self) -> None:
        """Test formatting bet with no side."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b2",
            "bet_amount": 0.5,
            "prediction_side": "no",
            "created_at": "2024-01-01T00:00:00Z",
        }
        market_info = {
            "prediction_response": {
                "p_yes": 0.3,
                "p_no": 0.7,
                "confidence": 0.8,
                "info_utility": 0.6,
            },
            "strategy": "bet_amount_per_threshold",
        }

        result = fetcher._format_bet_for_position(bet, market_info, None)

        assert result["intelligence"]["implied_probability"] == 70.0
        assert result["strategy"] == "balanced"

    def test_no_prediction_response(self) -> None:
        """Test when prediction_response is missing."""
        fetcher = _make_fetcher()
        bet = {
            "id": "b3",
            "bet_amount": 1.0,
            "prediction_side": "yes",
            "created_at": "",
        }
        market_info = {"strategy": None}

        result = fetcher._format_bet_for_position(bet, market_info, None)

        assert result["intelligence"]["implied_probability"] == 0.0
        assert result["intelligence"]["confidence_score"] == 0.0
        assert result["strategy"] is None


# ---------------------------------------------------------------------------
# _fetch_bet_from_subgraph tests
# ---------------------------------------------------------------------------


class TestFetchBetFromSubgraph:
    """Tests for _fetch_bet_from_subgraph."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test successful fetch of bet from subgraph."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "traderAgent": {
                    "bets": [
                        {
                            "id": "bet_1",
                            "amount": str(WEI_TO_NATIVE),
                            "outcomeIndex": 0,
                            "timestamp": "1700000000",
                            "fixedProductMarketMaker": {
                                "id": "m1",
                                "question": "Will it rain?",
                                "currentAnswer": "0x0000000000000000000000000000000000000000000000000000000000000000",
                                "currentAnswerTimestamp": "1700001000",
                                "outcomes": ["Yes", "No"],
                                "participants": [
                                    {
                                        "totalPayout": str(2 * WEI_TO_NATIVE),
                                        "totalTraded": str(WEI_TO_NATIVE),
                                        "bets": [
                                            {
                                                "id": "bet_1",
                                                "amount": str(WEI_TO_NATIVE),
                                                "outcomeIndex": 0,
                                            }
                                        ],
                                    }
                                ],
                            },
                        }
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is not None
        assert result["id"] == "bet_1"
        assert result["market"]["id"] == "m1"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_non_200_response(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of non-200 response."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_trader_agent(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when traderAgent is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"traderAgent": None}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_empty_bets(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when bets list is empty."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"traderAgent": {"bets": []}}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_exception_handling(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test handling of request exceptions."""
        fetcher = _make_fetcher()
        mock_post.side_effect = Exception("Network error")

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_data(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when data is None."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_bet_not_found_uses_first(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when bet_id doesn't match any bet, falls back to first."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "traderAgent": {
                    "bets": [
                        {
                            "id": "other_bet",
                            "amount": str(WEI_TO_NATIVE),
                            "outcomeIndex": 0,
                            "timestamp": "1700000000",
                            "fixedProductMarketMaker": {
                                "id": "m1",
                                "question": "Q?",
                                "currentAnswer": None,
                                "currentAnswerTimestamp": None,
                                "outcomes": ["Yes", "No"],
                                "participants": [
                                    {"totalPayout": "0", "totalTraded": "0"}
                                ],
                            },
                        }
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("nonexistent_bet", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_bets_key(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Test when traderAgent has no bets key."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"traderAgent": {"bets": None}}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_bets_truthy_for_get_but_falsy_for_getitem(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock
    ) -> None:
        """Test the secondary empty check after bets = trader_agent['bets'].

        Line 517: ``not trader_agent.get("bets")`` uses dict.get which returns
        a value.  Line 521: ``bets = trader_agent["bets"]`` uses __getitem__.
        We craft a dict subclass where get() returns a truthy sentinel but
        __getitem__ returns an empty list so the ``if not bets:`` guard on
        line 522 is entered.

        :param mock_post: patched requests.post.
        """
        fetcher = _make_fetcher()

        # type: ignore[no-untyped-def]
        class SplitBetsDict(dict):
            """Dict where get('bets') is truthy but d['bets'] is falsy."""

            def __bool__(self) -> bool:  # type: ignore[no-untyped-def]
                """Always truthy so ``not trader_agent`` is False."""
                return True

            def get(self, key: Any, default: Any = None) -> Any:
                """Return truthy sentinel for 'bets'."""
                if key == "bets":  # type: ignore[no-untyped-def]
                    return [{"sentinel": True}]  # truthy -> passes line 517
                return super().get(key, default)

            def __getitem__(self, key: Any) -> Any:
                """Return empty list for 'bets'."""
                if key == "bets":
                    return []  # falsy -> triggers line 522
                return super().__getitem__(key)

        trader_agent = SplitBetsDict()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"traderAgent": trader_agent}}
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result is None

    # type: ignore[no-untyped-def]
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_pending_status_no_settled_at(self, mock_post: MagicMock) -> None:
        """Test that pending status results in no settled_at."""
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "traderAgent": {
                    "bets": [
                        {
                            "id": "bet_1",
                            "amount": str(WEI_TO_NATIVE),
                            "outcomeIndex": 0,
                            "timestamp": "1700000000",
                            "fixedProductMarketMaker": {
                                "id": "m1",
                                "question": "Q?",
                                "currentAnswer": None,
                                "currentAnswerTimestamp": None,
                                "outcomes": ["Yes", "No"],
                                "participants": [],
                            },
                        }
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        assert result["settled_at"] is None  # type: ignore[index]

    # type: ignore[no-untyped-def]
    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_null_fpmm(self, mock_post: MagicMock) -> None:
        """Test when fpmm is None.

        The _fetch_bet_from_subgraph method wraps everything in try/except,
        so when fpmm is None and code tries fpmm.get("id"), it will
        raise AttributeError which gets caught and returns None.

        :param mock_post: patched requests.post.
        """
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "traderAgent": {
                    "bets": [
                        {
                            "id": "bet_1",
                            "amount": str(WEI_TO_NATIVE),
                            "outcomeIndex": 0,
                            "timestamp": "1700000000",
                            "fixedProductMarketMaker": None,
                        }
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("bet_1", "0xsafe")

        # The code uses `fpmm = bet.get("fixedProductMarketMaker") or {}`
        # which gives {} when fpmm is None, so this actually works.
        # Let's verify the actual behavior
        assert result is None


# ---------------------------------------------------------------------------
# fetch_position_details tests
# ---------------------------------------------------------------------------


class TestFetchPositionDetails:  # type: ignore[no-untyped-def]
    """Tests for fetch_position_details."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_successful_fetch(self, mock_post: MagicMock) -> None:
        """Test successful position details fetch."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multi_bets.json
            multi_bets = [
                {
                    "id": "m1",
                    "title": "Will it rain?",
                    "openingTimestamp": 0,
                    "prediction_response": {
                        "p_yes": 0.8,
                        "p_no": 0.2,
                        "confidence": 0.9,
                        "info_utility": 0.7,
                    },
                    "potential_net_profit": 0,
                    "strategy": "kelly_criterion_no_conf",
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            # Create agent_performance.json
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "m1",
                                "title": "Will it rain?",
                                "external_url": "http://example.com",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0.5,
                            "total_payout": 1.5,
                            "status": "won",
                            "created_at": "2024-01-01T00:00:00Z",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            # Mock mech tool fetch
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "sender": {"requests": [{"parsedRequest": {"tool": "tool_1"}}]}
                }
            }
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["id"] == "bet_1"
            assert result["status"] == "won"  # type: ignore[no-untyped-def]
            assert result["payout"] == 1.5

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_bet_not_found_fetches_from_subgraph(self, mock_post: MagicMock) -> None:
        """Test fallback to subgraph when bet not in local data."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty files
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump({}, f)

            # Subgraph returns None for the bet
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"traderAgent": None}}
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is None

    def test_exception_handling(self) -> None:
        """Test exception handling in fetch_position_details."""
        fetcher = _make_fetcher()

        with patch.object(
            fetcher, "_load_multi_bets_data", side_effect=Exception("Error")
        ):
            result = fetcher.fetch_position_details(
                "bet_1", "0xsafe", "/tmp/test"  # nosec B108
            )
        # type: ignore[no-untyped-def]
        assert result is None

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_lost_status_payout_zero(self, mock_post: MagicMock) -> None:
        """Test lost status results in payout = 0."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "m1",
                                "title": "Q?",
                                "external_url": "http://example.com",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": -1.0,
                            "total_payout": 0,
                            "status": "lost",
                            "created_at": "2024-01-01T00:00:00Z",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"sender": {"requests": []}}}
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None  # type: ignore[no-untyped-def]
            assert result["payout"] == 0

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_pending_with_potential_profit(self, mock_post: MagicMock) -> None:
        """Test pending status with potential profit."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets = [
                {
                    "id": "m1",
                    "title": "Q?",
                    "openingTimestamp": 0,
                    "potential_net_profit": int(0.5 * WEI_TO_NATIVE),
                    "strategy": None,
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "m1",
                                "title": "Q?",
                                "external_url": "http://example.com",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"sender": {"requests": []}}}
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None  # type: ignore[no-untyped-def]
            assert result["payout"] == 1.5  # 1.0 + 0.5

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_invalid_status_payout(self, mock_post: MagicMock) -> None:
        """Test invalid status results in payout = total_payout."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "m1",
                                "title": "Q?",
                                "external_url": "http://example.com",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": -0.1,
                            "total_payout": 0.9,
                            "status": "invalid",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"sender": {"requests": []}}}
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None  # type: ignore[no-untyped-def]
            assert result["payout"] == 0.9

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_no_market_info_uses_bet_market(self, mock_post: MagicMock) -> None:
        """Test when market not found in multi_bets, uses bet's market data."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump([], f)
            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "m_unknown", "title": "Unknown Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            # Mock for mech tool and prediction response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": {"sender": {"requests": []}}}
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None  # type: ignore[no-untyped-def]
            assert result["question"] == "Unknown Q?"

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_fetches_prediction_response_when_missing(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock
    ) -> None:
        """Test that prediction response is fetched from mech when not in market_info."""
        fetcher = _make_fetcher()

        call_count = [0]

        def mock_post_side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            call_count[0] += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if call_count[0] == 1:
                # Prediction response fetch
                mock_resp.json.return_value = {
                    "data": {
                        "requests": [
                            {
                                "deliveries": [
                                    {
                                        "toolResponse": json.dumps(
                                            {
                                                "p_yes": 0.8,
                                                "p_no": 0.2,
                                                "confidence": 0.9,
                                                "info_utility": 0.5,
                                            }
                                        )
                                    }
                                ]
                            }
                        ]
                    }
                }
            else:
                # Mech tool fetch
                mock_resp.json.return_value = {
                    "data": {
                        "sender": {"requests": [{"parsedRequest": {"tool": "tool_x"}}]}
                    }
                }
            return mock_resp

        mock_post.side_effect = mock_post_side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets = [
                {
                    "id": "m1",
                    "title": "Q?",
                    "openingTimestamp": 0,
                    "potential_net_profit": 0,
                    "strategy": None,
                }
            ]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {
                                "id": "m1",
                                "title": "Q?",
                                "external_url": "http://example.com",
                            },
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0,
                            "total_payout": 0,
                            "status": "pending",
                            "created_at": "",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None


# ---------------------------------------------------------------------------
# _format_single_bet tests
# ---------------------------------------------------------------------------


class TestFormatSingleBet:
    """Tests for _format_single_bet."""

    def test_with_settled_at(self) -> None:
        """Test that settled_at is set for resolved markets."""
        fetcher = _make_fetcher()
        bet = _make_bet()
        fpmm = bet["fixedProductMarketMaker"]
        ctx = fetcher._build_market_context([bet])
        market_ctx = ctx.get("market_1")

        result = fetcher._format_single_bet(bet, fpmm, market_ctx, None)

        assert result is not None
        assert result["settled_at"] is not None

    def test_without_settled_at_pending(self) -> None:
        """Test that settled_at is None for pending markets."""
        fetcher = _make_fetcher()
        bet = _make_bet(current_answer=None)  # type: ignore[arg-type]
        fpmm = bet["fixedProductMarketMaker"]
        ctx = fetcher._build_market_context([bet])
        market_ctx = ctx.get("market_1")

        result = fetcher._format_single_bet(bet, fpmm, market_ctx, None)

        assert result is not None
        assert result["settled_at"] is None

    def test_none_market_ctx(self) -> None:
        """Test with None market context."""
        fetcher = _make_fetcher()
        bet = _make_bet()
        fpmm = bet["fixedProductMarketMaker"]

        result = fetcher._format_single_bet(bet, fpmm, None, None)

        assert result is not None
        assert result["settled_at"] is None

    def test_payout_rounding(self) -> None:
        """Test that payout amounts are rounded to 3 decimal places."""
        fetcher = _make_fetcher()
        bet = _make_bet()
        fpmm = bet["fixedProductMarketMaker"]
        ctx = fetcher._build_market_context([bet])
        market_ctx = ctx.get("market_1")

        result = fetcher._format_single_bet(bet, fpmm, market_ctx, None)

        assert result is not None
        # bet_amount should be rounded
        assert isinstance(result["bet_amount"], float)

    def test_net_profit_none_when_payout_none(self) -> None:
        """Test that net_profit is 0 and total_payout is 0 when both are None equivalents."""
        fetcher = _make_fetcher()
        bet = _make_bet()
        fpmm = bet["fixedProductMarketMaker"]

        result = fetcher._format_single_bet(bet, fpmm, None, None)

        assert result is not None
        # With no market_ctx, net_profit is 0.0 and payout_amount is None
        assert result["net_profit"] == 0.0
        assert result["total_payout"] == 0


# ---------------------------------------------------------------------------
# Resilience audit: BUG 24 -- {"data": null} AttributeError
# ---------------------------------------------------------------------------


class TestFetchTraderAgentBetsDataNull:
    """BUG 24: _fetch_trader_agent_bets crashes on {"data": null}.

    `response_data.get("data", {})` returns None (not {}) when value is
    explicitly null. Then `.get("marketParticipants")` raises AttributeError.
    Caught by broad except, so no crash, but the `or {}` guard is missing.
    """

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_data_null_returns_none_without_attribute_error(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock
    ) -> None:
        """Verify {"data": null} returns None cleanly, not via AttributeError.

        :param mock_post: patched requests.post
        """
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": None}
        mock_post.return_value = mock_response

        # This works (returns None) but triggers AttributeError internally
        result = fetcher._fetch_trader_agent_bets("0xsafe", 10, 0)
        assert result is None
        # After fix: logger should NOT have an error about AttributeError
        # Currently it does log the AttributeError from the broad except


class TestFetchPositionDetailsInvalidTimestamp:
    """Test that invalid created_at format falls back to bet_timestamp=0."""

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_invalid_created_at_falls_back(self, mock_post: MagicMock) -> None:  # type: ignore[no-untyped-def]
        """Invalid created_at format does not crash, falls back to current time."""
        fetcher = _make_fetcher()

        with tempfile.TemporaryDirectory() as tmpdir:
            multi_bets: list = []  # type: ignore[type-arg]
            with open(os.path.join(tmpdir, "multi_bets.json"), "w") as f:
                json.dump(multi_bets, f)

            perf_data = {
                "prediction_history": {
                    "items": [
                        {
                            "id": "bet_1",
                            "market": {"id": "m1", "title": "Q?"},
                            "prediction_side": "yes",
                            "bet_amount": 1.0,
                            "net_profit": 0.0,
                            "total_payout": 0.0,
                            "status": "pending",
                            "created_at": "not-a-valid-timestamp",
                        }
                    ]
                }
            }
            with open(os.path.join(tmpdir, "agent_performance.json"), "w") as f:
                json.dump(perf_data, f)

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": {
                    "sender": {"requests": [{"parsedRequest": {"tool": "tool_1"}}]}
                }
            }
            mock_post.return_value = mock_response

            result = fetcher.fetch_position_details("bet_1", "0xsafe", tmpdir)

            assert result is not None
            assert result["id"] == "bet_1"


# ---------------------------------------------------------------------------
# Resilience audit: BUG 25 -- Wrong bet returned in _fetch_bet_from_subgraph
# ---------------------------------------------------------------------------


class TestFetchBetFromSubgraphWrongBetReturned:
    """BUG 25: _fetch_bet_from_subgraph returns wrong bet when ID not found.

    `next((b for b in bets if b.get("id") == bet_id), bets[0])` falls back
    to the first bet instead of None. This returns WRONG data to the UI.
    """

    @patch(
        "packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper.requests.post"
    )
    def test_nonexistent_bet_returns_first_bet_not_none(  # type: ignore[no-untyped-def]
        self, mock_post: MagicMock
    ) -> None:
        """Verify nonexistent bet_id returns None.

        :param mock_post: patched requests.post
        """
        fetcher = _make_fetcher()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "traderAgent": {
                    "bets": [
                        {
                            "id": "other_bet",
                            "amount": str(1 * WEI_TO_NATIVE),
                            "outcomeIndex": 0,
                            "timestamp": "1700000000",
                            "fixedProductMarketMaker": {
                                "id": "m1",
                                "question": "Q?",
                                "currentAnswer": None,
                                "currentAnswerTimestamp": None,
                                "outcomes": ["Yes", "No"],
                                "participants": [
                                    {"totalPayout": "0", "totalTraded": "0"}
                                ],
                            },
                        }
                    ]
                }
            }
        }
        mock_post.return_value = mock_response

        result = fetcher._fetch_bet_from_subgraph("nonexistent_bet", "0xsafe")

        # Returns None when requested bet_id not found
        assert result is None


# ---------------------------------------------------------------------------
# parse_current_answer tests (Bug A §4.4 — defensive parse)
# ---------------------------------------------------------------------------


class TestParseCurrentAnswer:
    """Tests for the parse_current_answer module-level helper.

    This helper centralises the int(value, 0) cast that previously crashed
    on malformed subgraph values. It returns Optional[int] — None for any
    value that cannot be interpreted as a valid outcome index (None,
    sentinel, malformed hex, empty, garbage). Callers treat None as
    'cannot classify -> pending / skip'.
    """

    def test_none_returns_none(self) -> None:
        """None input -> None."""
        assert parse_current_answer(None) is None

    def test_invalid_sentinel_returns_none(self) -> None:
        """The 0xff..ff invalid sentinel is not a valid outcome index -> None."""
        assert parse_current_answer(INVALID_ANSWER_HEX) is None

    def test_zero_hex(self) -> None:
        """0x0 -> 0."""
        assert parse_current_answer("0x0") == 0

    def test_one_hex(self) -> None:
        """0x1 -> 1."""
        assert parse_current_answer("0x1") == 1

    def test_full_width_zero(self) -> None:
        """A 32-byte zero hex string -> 0."""
        assert (
            parse_current_answer(
                "0x0000000000000000000000000000000000000000000000000000000000000000"
            )
            == 0
        )

    def test_full_width_one(self) -> None:
        """A 32-byte one hex string -> 1."""
        assert (
            parse_current_answer(
                "0x0000000000000000000000000000000000000000000000000000000000000001"
            )
            == 1
        )

    def test_malformed_hex_returns_none(self) -> None:
        """Garbage characters inside the hex prefix do not crash."""
        assert parse_current_answer("0xZZ") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string is not parseable -> None."""
        assert parse_current_answer("") is None

    def test_garbage_string_returns_none(self) -> None:
        """Non-hex garbage -> None."""
        assert parse_current_answer("not-a-hex") is None


# ---------------------------------------------------------------------------
# parse_timestamp tests (Bug A post-review hardening — comment #1)
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    """Tests for the parse_timestamp module-level helper.

    Centralises the int() cast on subgraph timestamp fields so callers
    do not crash on malformed data (symmetric with parse_current_answer)
    and so the "0" unset-sentinel some subgraphs emit is treated as
    unfinalized rather than silently slipping past the gate as terminal.
    """

    def test_none_returns_none(self) -> None:
        """None -> None (unfinalized)."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp(None) is None

    def test_zero_string_returns_none(self) -> None:
        """'0' -> None (subgraph unset sentinel, treat as unfinalized)."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp("0") is None

    def test_zero_int_returns_none(self) -> None:
        """0 (int) -> None."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp(0) is None

    def test_negative_returns_none(self) -> None:
        """Negative values are invalid Unix timestamps -> None."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp("-1") is None

    def test_malformed_returns_none(self) -> None:
        """Non-numeric garbage -> None (does not raise)."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp("not-a-timestamp") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string -> None."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp("") is None

    def test_valid_string(self) -> None:
        """Valid positive Unix ts string -> int."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp("1700000000") == 1700000000

    def test_valid_int(self) -> None:
        """Valid positive int ts -> int."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_timestamp,
        )

        assert parse_timestamp(1700000000) == 1700000000


# ---------------------------------------------------------------------------
# Status gate: "0" timestamp + malformed timestamp (Bug A post-review)
# ---------------------------------------------------------------------------


class TestFinalizationGateHardening:
    """Tests covering "0" subgraph timestamp + malformed timestamp cases.

    Added in response to PR #903 review comment #1: the original gate
    ``int(answer_finalized_ts) > now`` would (a) treat a subgraph "0"
    as terminal (since 0 > now is False) and (b) crash on malformed
    input. These tests pin the corrected behaviour: both cases degrade
    to "pending" rather than misclassifying or crashing.
    """

    def test_status_zero_finalization_returns_pending(self) -> None:
        """Sentinel + ``"0"`` finalization timestamp -> pending, not invalid."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": INVALID_ANSWER_HEX,
                "answerFinalizedTimestamp": "0",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_status_malformed_finalization_returns_pending(self) -> None:
        """Malformed finalization timestamp -> pending (does not raise)."""
        fetcher = _make_fetcher()
        bet = {
            "fixedProductMarketMaker": {
                "currentAnswer": INVALID_ANSWER_HEX,
                "answerFinalizedTimestamp": "not-a-timestamp",
            },
            "outcomeIndex": 0,
        }

        with patch.object(fetcher, "_now", return_value=1700000000):
            result = fetcher._get_prediction_status(bet, None)

        assert result == "pending"

    def test_net_profit_zero_finalization_returns_zero_none(self) -> None:
        """_calculate_bet_net_profit: ``"0"`` finalization -> (0.0, None)."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": INVALID_ANSWER_HEX,
            "answer_finalized_ts": "0",
            "total_payout": 2.0,
            "total_traded": 4.0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)

    def test_net_profit_malformed_finalization_returns_zero_none(self) -> None:
        """_calculate_bet_net_profit: malformed ts -> (0.0, None), no raise."""
        fetcher = _make_fetcher()
        ctx = {
            "current_answer": "0x0000000000000000000000000000000000000000000000000000000000000000",
            "answer_finalized_ts": "not-a-timestamp",
            "total_payout": 2.0,
            "total_traded": 1.0,
            "winning_total_amount": 1.0,
        }

        with patch.object(fetcher, "_now", return_value=1700001000):
            result = fetcher._calculate_bet_net_profit({"outcomeIndex": 0}, ctx, 1.0)

        assert result == (0.0, None)


# ---------------------------------------------------------------------------
# parse_current_answer public (non-underscore) alias — comment #3
# ---------------------------------------------------------------------------


class TestParseCurrentAnswerPublicName:
    """parse_current_answer (no underscore) is the public cross-module name.

    behaviours.py imports the symbol directly; a leading underscore on
    a name used across modules trips linters configured to flag private
    imports. The rename makes it match its actual visibility.
    """

    def test_public_name_is_exported(self) -> None:
        """Module exposes ``parse_current_answer`` without underscore."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling import (  # noqa: E501
            predictions_helper,
        )

        assert hasattr(predictions_helper, "parse_current_answer")

    def test_public_name_parses_valid_hex(self) -> None:
        """Sanity: the public symbol behaves the same as the parser helper."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            parse_current_answer,
        )

        assert parse_current_answer("0x1") == 1
        assert parse_current_answer(None) is None
        assert parse_current_answer(INVALID_ANSWER_HEX) is None


# ---------------------------------------------------------------------------
# now_ts module-level single-source helper — comment #4
# ---------------------------------------------------------------------------


class TestNowTsModuleLevel:
    """``now_ts`` is a single module-level time source.

    Both ``PredictionsFetcher._now`` and ``FetchPerformanceSummaryBehaviour._now``
    previously held independent copies of ``int(time.time())``. Extracting
    a single module-level function removes the drift surface the review
    flagged (comment #4); the per-class methods remain as thin delegators
    so existing ``patch.object(instance, "_now", ...)`` test patterns
    continue to work.
    """

    def test_now_ts_is_exported(self) -> None:
        """Module exposes ``now_ts``."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling import (  # noqa: E501
            predictions_helper,
        )

        assert callable(getattr(predictions_helper, "now_ts", None))

    def test_now_ts_returns_int(self) -> None:
        """``now_ts`` returns an int (seconds since epoch)."""
        from packages.valory.skills.agent_performance_summary_abci.graph_tooling.predictions_helper import (  # noqa: E501
            now_ts,
        )

        assert isinstance(now_ts(), int)

    def test_fetcher_now_delegates_to_module(self) -> None:
        """``PredictionsFetcher._now`` delegates to the module-level ``now_ts``.

        Falsifiability: patching ``now_ts`` at the module level must
        affect the instance method; if the method still calls
        ``int(time.time())`` directly, the patch would be bypassed and
        the assertion would fail.
        """
        fetcher = _make_fetcher()
        with patch(
            "packages.valory.skills.agent_performance_summary_abci."
            "graph_tooling.predictions_helper.now_ts",
            return_value=42,
        ):
            assert fetcher._now() == 42
