# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2024 Valory AG
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

"""Test the models.py module of the MarketManager skill."""
import builtins
import unittest
from copy import deepcopy
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext
from packages.valory.skills.abstract_round_abci.tests.test_models import (
    BASE_DUMMY_PARAMS,
    BASE_DUMMY_SPECS_CONFIG,
)
from packages.valory.skills.market_manager_abci.models import (
    MarketManagerParams,
    NetworkSubgraph,
    OmenSubgraph,
    SharedState,
    Subgraph,
)


DUMMY_SPECS_CONFIG = deepcopy(BASE_DUMMY_SPECS_CONFIG)
DUMMY_SPECS_CONFIG.update(the_graph_error_mesage_key="the_graph_error_message_key")

MARKET_MANAGER_PARAMS = dict(
    creator_per_subgraph=dict(creator_per_subgraph=[]),
    slot_count=2,
    opening_margin=1,
    languages=[],
    average_block_time=1,
    abt_error_mult=1,
    the_graph_error_message_key="test",
    the_graph_payment_required_error="test",
)


class TestSharedState:
    """Test SharedState of MarketManager."""

    def test_initialization(self) -> None:
        """Test initialization."""
        SharedState(name="", skill_context=DummyContext())


class TestSubgraph:
    """Test Subgraph of MarketManager."""

    def setup(
        self,
    ) -> None:
        """Setup test."""

        self.subgraph = Subgraph(
            **BASE_DUMMY_SPECS_CONFIG,
            response_key="value",
            response_index=0,
            response_type="float",
            error_key="error",
            error_index=None,
            error_type="str",
            error_data="error text",
        )
        self.subgraph.context.logger.error = MagicMock()

    @pytest.mark.parametrize(
        "api_specs_config, message, expected_res, expected_error",
        (
            (
                dict(
                    **BASE_DUMMY_SPECS_CONFIG,
                    response_key="value",
                    response_index=None,
                    response_type="float",
                    error_key=None,
                    error_index=None,
                    error_data=None,
                ),
                MagicMock(body=b'{"value": "10.232"}'),
                10.232,
                None,
            ),
            (
                dict(
                    **BASE_DUMMY_SPECS_CONFIG,
                    response_key="test:response:key",
                    response_index=2,
                    error_key="error:key",
                    error_index=3,
                    error_type="str",
                    error_data=1,
                ),
                MagicMock(body=b'{"test": {"response": {"key": [""]}}}'),
                None,
                None,
            ),
        ),
    )
    def test_process_response(
        self,
        api_specs_config: dict,
        message: MagicMock,
        expected_res: Any,
        expected_error: Any,
    ) -> None:
        """Test process response."""
        api_specs = Subgraph(**api_specs_config)
        actual_res = api_specs.process_response(message)
        assert actual_res == expected_res
        if actual_res is not None:
            pass


class TestOmenSubgraph:
    """Test OmenSubgraph of MarketManager."""

    def test_initialization(self) -> None:
        """Test initialization of OmenSubgraph."""
        OmenSubgraph(**BASE_DUMMY_SPECS_CONFIG)


class TestNetworkSubgraph:
    """Test NetworkSubgraph of MarketManager."""

    def test_initialization(self) -> None:
        """Test initialization of NetworkSubgraph."""
        NetworkSubgraph(**BASE_DUMMY_SPECS_CONFIG)



