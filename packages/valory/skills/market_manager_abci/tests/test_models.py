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

"""Tests for market_manager_abci models."""

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from aea.skills.base import Model

from packages.valory.skills.abstract_round_abci.models import (
    ApiSpecs,
    BaseParams,
)
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.market_manager_abci.models import (
    BenchmarkingMode,
    BenchmarkTool,
    MarketManagerParams,
    NetworkSubgraph,
    OmenSubgraph,
    Requests,
    SharedState,
    Subgraph,
)
from packages.valory.skills.market_manager_abci.rounds import MarketManagerAbciApp


class TestModelAliases:
    """Tests for model aliases Requests and BenchmarkTool."""

    def test_requests_alias(self) -> None:
        """Requests is an alias for BaseRequests."""
        assert Requests is BaseRequests

    def test_benchmark_tool_alias(self) -> None:
        """BenchmarkTool is an alias for BaseBenchmarkTool."""
        assert BenchmarkTool is BaseBenchmarkTool


class TestSharedState:
    """Tests for SharedState model."""

    def test_abci_app_cls(self) -> None:
        """SharedState points to MarketManagerAbciApp."""
        assert SharedState.abci_app_cls is MarketManagerAbciApp


class _TestableSubgraph(Subgraph):
    """Subclass that overrides the read-only context property for testing.

    Model.context is a property from the AEA framework; this subclass
    shadows it with a plain attribute so tests can inject a MagicMock.
    """

    context = None  # type: ignore[assignment]


class TestSubgraphProcessResponse:
    """Tests for Subgraph.process_response."""

    def _make_subgraph(self) -> _TestableSubgraph:
        """Create a testable Subgraph instance with mocked internals."""
        subgraph = object.__new__(_TestableSubgraph)
        subgraph.__dict__["_frozen"] = False
        subgraph.context = MagicMock()  # type: ignore[assignment]
        subgraph.response_info = MagicMock()
        subgraph.response_info.error_type = "dict"
        return subgraph

    def test_returns_result_when_super_returns_non_none(self) -> None:
        """When super().process_response returns a non-None value, return it directly."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()
        expected_result = {"data": {"markets": []}}

        with patch.object(
            ApiSpecs, "process_response", return_value=expected_result
        ):
            result = subgraph.process_response(mock_response)

        assert result is expected_result

    def test_returns_none_and_logs_payment_required(self) -> None:
        """When super returns None and error_data matches payment required, log error."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        error_message_key = "message"
        payment_required_error = "payment required"
        subgraph.context.params.the_graph_error_message_key = error_message_key
        subgraph.context.params.the_graph_payment_required_error = (
            payment_required_error
        )
        subgraph.response_info.error_data = {
            "message": "402 payment required for this request"
        }
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            result = subgraph.process_response(mock_response)

        assert result is None
        subgraph.context.logger.error.assert_called_once_with(
            "Payment required for subsequent requests for the current 'The Graph' API key!"
        )

    def test_returns_none_no_payment_required_match(self) -> None:
        """When super returns None and error does not match payment required, no log."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        error_message_key = "message"
        payment_required_error = "payment required"
        subgraph.context.params.the_graph_error_message_key = error_message_key
        subgraph.context.params.the_graph_payment_required_error = (
            payment_required_error
        )
        subgraph.response_info.error_data = {
            "message": "some other error occurred"
        }
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            result = subgraph.process_response(mock_response)

        assert result is None
        subgraph.context.logger.error.assert_not_called()

    def test_returns_none_when_error_data_is_not_expected_type(self) -> None:
        """When error_data does not match expected_error_type, skip the check."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        subgraph.response_info.error_data = "a string error, not a dict"
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            result = subgraph.process_response(mock_response)

        assert result is None
        subgraph.context.logger.error.assert_not_called()

    def test_returns_none_when_error_message_key_missing(self) -> None:
        """When error_data is a dict but missing the error_message_key, return None."""
        subgraph = self._make_subgraph()
        mock_response = MagicMock()

        error_message_key = "message"
        payment_required_error = "payment required"
        subgraph.context.params.the_graph_error_message_key = error_message_key
        subgraph.context.params.the_graph_payment_required_error = (
            payment_required_error
        )
        # error_data is a dict but does NOT have the expected key
        subgraph.response_info.error_data = {"other_key": "some value"}
        subgraph.response_info.error_type = "dict"

        with patch.object(ApiSpecs, "process_response", return_value=None):
            # error_data.get(error_message_key, None) returns None
            # "payment required" in None will raise TypeError
            # The code does not guard against this; it will raise
            # We test the actual behavior
            with pytest.raises(TypeError):
                subgraph.process_response(mock_response)


class TestOmenSubgraph:
    """Tests for OmenSubgraph."""

    def test_is_subclass_of_subgraph(self) -> None:
        """OmenSubgraph is a subclass of Subgraph."""
        assert issubclass(OmenSubgraph, Subgraph)

    def test_is_subclass_of_api_specs(self) -> None:
        """OmenSubgraph is also a subclass of ApiSpecs."""
        assert issubclass(OmenSubgraph, ApiSpecs)


class TestNetworkSubgraph:
    """Tests for NetworkSubgraph."""

    def test_is_subclass_of_subgraph(self) -> None:
        """NetworkSubgraph is a subclass of Subgraph."""
        assert issubclass(NetworkSubgraph, Subgraph)

    def test_is_subclass_of_api_specs(self) -> None:
        """NetworkSubgraph is also a subclass of ApiSpecs."""
        assert issubclass(NetworkSubgraph, ApiSpecs)


# Default kwargs for MarketManagerParams init
DEFAULT_MM_KWARGS: Dict[str, Any] = {
    "creator_per_subgraph": {"omen": ["creator1", "creator2"]},
    "slot_count": 2,
    "opening_margin": 100,
    "languages": ["en"],
    "average_block_time": 12,
    "abt_error_mult": 3,
    "the_graph_error_message_key": "message",
    "the_graph_payment_required_error": "payment required",
    "use_multi_bets_mode": False,
    "is_running_on_polymarket": False,
    "enable_multi_bets_fallback": False,
}


class TestMarketManagerParamsInit:
    """Tests for MarketManagerParams.__init__."""

    def test_init_sets_all_attributes(self) -> None:
        """MarketManagerParams init sets all required attributes from kwargs."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None):
            params = MarketManagerParams(
                skill_context=mock_skill_context,
                **DEFAULT_MM_KWARGS,
            )
        assert params.creator_per_market == {"omen": ["creator1", "creator2"]}
        assert params.slot_count == 2
        assert params.opening_margin == 100
        assert params.languages == ["en"]
        assert params.average_block_time == 12
        assert params.abt_error_mult == 3
        assert params.the_graph_error_message_key == "message"
        assert params.the_graph_payment_required_error == "payment required"
        assert params.use_multi_bets_mode is False
        assert params.is_running_on_polymarket is False
        assert params.enable_multi_bets_fallback is False

    def test_init_calls_super(self) -> None:
        """MarketManagerParams init calls BaseParams.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(BaseParams, "__init__", return_value=None) as mock_super:
            MarketManagerParams(
                skill_context=mock_skill_context,
                **DEFAULT_MM_KWARGS,
            )
        mock_super.assert_called_once()

    def test_init_slot_count_not_two_raises(self) -> None:
        """MarketManagerParams raises ValueError when slot_count is not 2."""
        mock_skill_context = MagicMock()
        bad_kwargs = {**DEFAULT_MM_KWARGS, "slot_count": 3}
        with patch.object(BaseParams, "__init__", return_value=None):
            with pytest.raises(
                ValueError,
                match="Only a slot_count `2` is currently supported. `3` was found",
            ):
                MarketManagerParams(
                    skill_context=mock_skill_context,
                    **bad_kwargs,
                )

    def test_init_slot_count_one_raises(self) -> None:
        """MarketManagerParams raises ValueError when slot_count is 1."""
        mock_skill_context = MagicMock()
        bad_kwargs = {**DEFAULT_MM_KWARGS, "slot_count": 1}
        with patch.object(BaseParams, "__init__", return_value=None):
            with pytest.raises(
                ValueError,
                match="Only a slot_count `2` is currently supported. `1` was found",
            ):
                MarketManagerParams(
                    skill_context=mock_skill_context,
                    **bad_kwargs,
                )

    def test_init_empty_creators(self) -> None:
        """MarketManagerParams init accepts empty creator_per_subgraph dict."""
        mock_skill_context = MagicMock()
        kwargs = {**DEFAULT_MM_KWARGS, "creator_per_subgraph": {}}
        with patch.object(BaseParams, "__init__", return_value=None):
            params = MarketManagerParams(
                skill_context=mock_skill_context,
                **kwargs,
            )
        assert params.creator_per_market == {}

    def test_init_multiple_creators(self) -> None:
        """MarketManagerParams init handles multiple market-creator mappings."""
        mock_skill_context = MagicMock()
        creators = {
            "omen": ["creator1", "creator2"],
            "polymarket": ["creator3"],
        }
        kwargs = {**DEFAULT_MM_KWARGS, "creator_per_subgraph": creators}
        with patch.object(BaseParams, "__init__", return_value=None):
            params = MarketManagerParams(
                skill_context=mock_skill_context,
                **kwargs,
            )
        assert params.creator_per_market == creators


class TestMarketManagerParamsCreatorsIterator:
    """Tests for MarketManagerParams.creators_iterator property."""

    def _make_params(
        self, creators: Dict[str, List[str]]
    ) -> MarketManagerParams:
        """Create a MarketManagerParams instance with given creators mapping."""
        mock_skill_context = MagicMock()
        kwargs = {**DEFAULT_MM_KWARGS, "creator_per_subgraph": creators}
        with patch.object(BaseParams, "__init__", return_value=None):
            params = MarketManagerParams(
                skill_context=mock_skill_context,
                **kwargs,
            )
        return params

    def test_creators_iterator_returns_items(self) -> None:
        """creators_iterator yields (market, creators) tuples."""
        creators = {"omen": ["creator1", "creator2"]}
        params = self._make_params(creators)
        result = list(params.creators_iterator)
        assert result == [("omen", ["creator1", "creator2"])]

    def test_creators_iterator_multiple_markets(self) -> None:
        """creators_iterator yields all market-creators pairs."""
        creators = {
            "omen": ["creator1"],
            "polymarket": ["creator2", "creator3"],
        }
        params = self._make_params(creators)
        result = list(params.creators_iterator)
        assert ("omen", ["creator1"]) in result
        assert ("polymarket", ["creator2", "creator3"]) in result
        assert len(result) == 2

    def test_creators_iterator_empty_dict(self) -> None:
        """creators_iterator on empty dict yields no items."""
        params = self._make_params({})
        result = list(params.creators_iterator)
        assert result == []

    def test_creators_iterator_is_exhaustible(self) -> None:
        """creators_iterator returns a fresh iterator each time (property)."""
        creators = {"omen": ["creator1"]}
        params = self._make_params(creators)
        # Exhaust the first iterator
        first = list(params.creators_iterator)
        # Get a new iterator via the property
        second = list(params.creators_iterator)
        assert first == second == [("omen", ["creator1"])]


# Default kwargs for BenchmarkingMode init
DEFAULT_BM_KWARGS: Dict[str, Any] = {
    "enabled": True,
    "native_balance": 1000,
    "collateral_balance": 500,
    "mech_cost": 10,
    "pool_fee": 5,
    "sep": ",",
    "dataset_filename": "data.csv",
    "question_field": "question",
    "question_id_field": "question_id",
    "answer_field": "answer",
    "p_yes_field_part": "p_yes",
    "p_no_field_part": "p_no",
    "confidence_field_part": "confidence",
    "part_prefix_mode": True,
    "bet_amount_field": "bet_amount",
    "results_filename": "results.csv",
    "randomness": "0xdeadbeef",
    "nr_mech_calls": 3,
}


class TestBenchmarkingModeInit:
    """Tests for BenchmarkingMode.__init__."""

    def test_init_sets_all_attributes(self) -> None:
        """BenchmarkingMode init sets all required attributes from kwargs."""
        mock_skill_context = MagicMock()
        with patch.object(Model, "__init__", return_value=None):
            bm = BenchmarkingMode(
                skill_context=mock_skill_context,
                **DEFAULT_BM_KWARGS,
            )
        assert bm.enabled is True
        assert bm.native_balance == 1000
        assert bm.collateral_balance == 500
        assert bm.mech_cost == 10
        assert bm.pool_fee == 5
        assert bm.sep == ","
        assert bm.dataset_filename == Path("data.csv")
        assert bm.question_field == "question"
        assert bm.question_id_field == "question_id"
        assert bm.answer_field == "answer"
        assert bm.p_yes_field_part == "p_yes"
        assert bm.p_no_field_part == "p_no"
        assert bm.confidence_field_part == "confidence"
        assert bm.part_prefix_mode is True
        assert bm.bet_amount_field == "bet_amount"
        assert bm.results_filename == Path("results.csv")
        assert bm.randomness == "0xdeadbeef"
        assert bm.nr_mech_calls == 3

    def test_init_calls_super(self) -> None:
        """BenchmarkingMode init calls Model.__init__."""
        mock_skill_context = MagicMock()
        with patch.object(Model, "__init__", return_value=None) as mock_super:
            BenchmarkingMode(
                skill_context=mock_skill_context,
                **DEFAULT_BM_KWARGS,
            )
        mock_super.assert_called_once()

    def test_dataset_filename_is_path(self) -> None:
        """BenchmarkingMode converts dataset_filename string to Path."""
        mock_skill_context = MagicMock()
        kwargs = {**DEFAULT_BM_KWARGS, "dataset_filename": "/tmp/my_data.csv"}
        with patch.object(Model, "__init__", return_value=None):
            bm = BenchmarkingMode(
                skill_context=mock_skill_context,
                **kwargs,
            )
        assert isinstance(bm.dataset_filename, Path)
        assert bm.dataset_filename == Path("/tmp/my_data.csv")

    def test_results_filename_is_path(self) -> None:
        """BenchmarkingMode converts results_filename string to Path."""
        mock_skill_context = MagicMock()
        kwargs = {**DEFAULT_BM_KWARGS, "results_filename": "/tmp/results.csv"}
        with patch.object(Model, "__init__", return_value=None):
            bm = BenchmarkingMode(
                skill_context=mock_skill_context,
                **kwargs,
            )
        assert isinstance(bm.results_filename, Path)
        assert bm.results_filename == Path("/tmp/results.csv")

    def test_enabled_false(self) -> None:
        """BenchmarkingMode can be initialized with enabled=False."""
        mock_skill_context = MagicMock()
        kwargs = {**DEFAULT_BM_KWARGS, "enabled": False}
        with patch.object(Model, "__init__", return_value=None):
            bm = BenchmarkingMode(
                skill_context=mock_skill_context,
                **kwargs,
            )
        assert bm.enabled is False

    def test_part_prefix_mode_false(self) -> None:
        """BenchmarkingMode correctly sets part_prefix_mode to False."""
        mock_skill_context = MagicMock()
        kwargs = {**DEFAULT_BM_KWARGS, "part_prefix_mode": False}
        with patch.object(Model, "__init__", return_value=None):
            bm = BenchmarkingMode(
                skill_context=mock_skill_context,
                **kwargs,
            )
        assert bm.part_prefix_mode is False
