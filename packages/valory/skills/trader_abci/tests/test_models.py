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

"""Tests for trader_abci models."""

from typing import Any, Dict
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.agent_performance_summary_abci.models import (
    GnosisStakingSubgraph as APTGnosisStakingSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    OlasAgentsSubgraph as APTOlasAgentsSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    OlasMechSubgraph as APTOlasMechSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    OpenMarketsSubgraph as APTOpenMarketsSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    PolygonMechSubgraph as APTPolygonMechSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    PolygonStakingSubgraph as APTPolygonStakingSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    PolymarketAgentsSubgraph as APTPolymarketAgentsSubgraph,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    PolymarketBetsSubgraph as APTPolymarketBetsSubgraph,
)
from packages.valory.skills.decision_maker_abci.models import (
    AccuracyInfoFields as BaseAccuracyInfoFields,
)
from packages.valory.skills.decision_maker_abci.models import (
    AgentToolsSpecs as DecisionMakerAgentToolsSpecs,
)
from packages.valory.skills.decision_maker_abci.models import (
    ConditionalTokensSubgraph as DecisionMakerConditionalTokensSubgraph,
)
from packages.valory.skills.decision_maker_abci.models import (
    RealitioSubgraph as DecisionMakerRealitioSubgraph,
)
from packages.valory.skills.decision_maker_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.decision_maker_abci.models import (
    TradesSubgraph as DecisionMakerTradesSubgraph,
)
from packages.valory.skills.decision_maker_abci.rounds import (
    Event as DecisionMakerEvent,
)
from packages.valory.skills.market_manager_abci.models import (
    BenchmarkingMode as BaseBenchmarkingMode,
)
from packages.valory.skills.market_manager_abci.models import (
    NetworkSubgraph as MarketManagerNetworkSubgraph,
)
from packages.valory.skills.market_manager_abci.models import (
    OmenSubgraph as MarketManagerOmenSubgraph,
)
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)
from packages.valory.skills.mech_interact_abci.models import (
    MechResponseSpecs as BaseMechResponseSpecs,
)
from packages.valory.skills.mech_interact_abci.models import (
    MechsSubgraph as InteractMechsSubgraph,
)
from packages.valory.skills.mech_interact_abci.models import (
    MechToolsSpecs as InteractMechToolsSpecs,
)
from packages.valory.skills.mech_interact_abci.rounds import Event as MechInteractEvent
from packages.valory.skills.reset_pause_abci.rounds import Event as ResetPauseEvent
from packages.valory.skills.trader_abci.composition import TraderAbciApp
from packages.valory.skills.trader_abci.models import (
    MARGIN,
    AccuracyInfoFields,
    AgentToolsSpecs,
    BenchmarkingMode,
    BenchmarkTool,
    ConditionalTokensSubgraph,
    EventToTimeoutMappingType,
    EventType,
    GnosisStakingSubgraph,
    MechResponseSpecs,
    MechsSubgraph,
    MechToolsSpecs,
    NetworkSubgraph,
    OlasAgentsSubgraph,
    OlasMechSubgraph,
    OmenSubgraph,
    OpenMarketsSubgraph,
    PolygonMechSubgraph,
    PolygonStakingSubgraph,
    PolymarketAgentsSubgraph,
    PolymarketBetsSubgraph,
    RandomnessApi,
    RealitioSubgraph,
    Requests,
    SharedState,
    TraderParams,
    TradesSubgraph,
)
from packages.valory.skills.transaction_settlement_abci.rounds import Event as TSEvent


class TestModelAliases:
    """Tests for all re-export aliases in models.py."""

    @pytest.mark.parametrize(
        "alias, base",
        [
            (Requests, BaseRequests),
            (BenchmarkTool, BaseBenchmarkTool),
            (OmenSubgraph, MarketManagerOmenSubgraph),
            (NetworkSubgraph, MarketManagerNetworkSubgraph),
            (MechResponseSpecs, BaseMechResponseSpecs),
            (AgentToolsSpecs, DecisionMakerAgentToolsSpecs),
            (TradesSubgraph, DecisionMakerTradesSubgraph),
            (ConditionalTokensSubgraph, DecisionMakerConditionalTokensSubgraph),
            (RealitioSubgraph, DecisionMakerRealitioSubgraph),
            (BenchmarkingMode, BaseBenchmarkingMode),
            (AccuracyInfoFields, BaseAccuracyInfoFields),
            (GnosisStakingSubgraph, APTGnosisStakingSubgraph),
            (PolygonStakingSubgraph, APTPolygonStakingSubgraph),
            (OlasMechSubgraph, APTOlasMechSubgraph),
            (OlasAgentsSubgraph, APTOlasAgentsSubgraph),
            (OpenMarketsSubgraph, APTOpenMarketsSubgraph),
            (MechToolsSpecs, InteractMechToolsSpecs),
            (MechsSubgraph, InteractMechsSubgraph),
            (PolygonMechSubgraph, APTPolygonMechSubgraph),
            (PolymarketAgentsSubgraph, APTPolymarketAgentsSubgraph),
            (PolymarketBetsSubgraph, APTPolymarketBetsSubgraph),
        ],
    )
    def test_alias_identity(self, alias: type, base: type) -> None:
        """Each re-exported alias is the same object as its base."""
        assert alias is base


class TestMarginConstant:
    """Test the MARGIN module-level constant."""

    def test_margin_value(self) -> None:
        """MARGIN equals 5."""
        assert MARGIN == 5


class TestTypeAliases:
    """Test that module-level type aliases exist."""

    def test_event_type_exists(self) -> None:
        """EventType is defined in the module."""
        assert EventType is not None

    def test_event_to_timeout_mapping_type_exists(self) -> None:
        """EventToTimeoutMappingType is defined in the module."""
        assert EventToTimeoutMappingType is not None


class TestRandomnessApi:
    """Tests for the RandomnessApi model."""

    def test_is_subclass_of_api_specs(self) -> None:
        """RandomnessApi inherits from ApiSpecs."""
        assert issubclass(RandomnessApi, ApiSpecs)


class TestTraderParams:
    """Tests for the TraderParams model."""

    def test_init_sets_attributes(self) -> None:
        """TraderParams.__init__ sets all 7 custom attributes from kwargs."""
        kwargs: Dict[str, Any] = {
            "mech_interact_round_timeout_seconds": 300,
            "genai_api_key": "test-key",
            "x402_payment_requirements": {"threshold": 100},
            "lifi_quote_to_amount_url": "https://example.com/lifi",
            "gnosis_ledger_rpc": "https://gnosis-rpc.example.com",
            "polygon_ledger_rpc": "https://polygon-rpc.example.com",
            "use_x402": True,
            "skill_context": MagicMock(),
        }
        # Patch the first parent class in the MRO to avoid deep dependency chain
        with patch.object(
            TraderParams.__mro__[1], "__init__", return_value=None
        ):
            params = TraderParams.__new__(TraderParams)
            TraderParams.__init__(params, **kwargs)

        assert params.mech_interact_round_timeout_seconds == 300
        assert params.genai_api_key == "test-key"
        assert params.x402_payment_requirements == {"threshold": 100}
        assert params.lifi_quote_to_amount_url == "https://example.com/lifi"
        assert params.gnosis_ledger_rpc == "https://gnosis-rpc.example.com"
        assert params.polygon_ledger_rpc == "https://polygon-rpc.example.com"
        assert params.use_x402 is True


class TestSharedState:
    """Tests for the SharedState model."""

    def test_abci_app_cls(self) -> None:
        """SharedState.abci_app_cls points to TraderAbciApp."""
        assert SharedState.abci_app_cls is TraderAbciApp

    def test_params_property(self) -> None:
        """The params property casts context.params to TraderParams."""
        state = SharedState.__new__(SharedState)
        mock_params = MagicMock(spec=TraderParams)
        mock_context = MagicMock()
        mock_context.params = mock_params

        with patch.object(type(state), "context", new_callable=PropertyMock, return_value=mock_context):
            result = state.params
            assert result is mock_params

    def test_setup_updates_event_to_timeout(self) -> None:
        """SharedState.setup sets event_to_timeout overrides and req_to_callback."""
        state = SharedState.__new__(SharedState)

        mock_params = MagicMock()
        mock_params.round_timeout_seconds = 30
        mock_params.mech_interact_round_timeout_seconds = 300
        mock_params.reset_pause_duration = 10
        mock_params.validate_timeout = 15
        mock_params.finalize_timeout = 20
        mock_params.history_check_timeout = 25
        mock_params.redeem_round_timeout = 3600

        # Save original event_to_timeout so we can restore it after test
        original_event_to_timeout = TraderAbciApp.event_to_timeout.copy()

        try:
            with patch.object(
                type(state),
                "params",
                new_callable=PropertyMock,
                return_value=mock_params,
            ), patch.object(BaseSharedState, "setup", return_value=None):
                state.setup()

            # Verify req_to_callback is set
            assert hasattr(state, "req_to_callback")
            assert state.req_to_callback == {}

            # Verify round_timeout overrides for the six event types
            assert (
                TraderAbciApp.event_to_timeout[MarketManagerEvent.ROUND_TIMEOUT] == 30
            )
            assert (
                TraderAbciApp.event_to_timeout[DecisionMakerEvent.ROUND_TIMEOUT] == 30
            )
            assert TraderAbciApp.event_to_timeout[TSEvent.ROUND_TIMEOUT] == 30
            assert (
                TraderAbciApp.event_to_timeout[ResetPauseEvent.ROUND_TIMEOUT] == 30
            )

            # Verify MechInteractEvent.ROUND_TIMEOUT uses mech-specific timeout
            assert (
                TraderAbciApp.event_to_timeout[MechInteractEvent.ROUND_TIMEOUT] == 300
            )

            # Verify TSEvent-specific overrides
            assert TraderAbciApp.event_to_timeout[TSEvent.RESET_TIMEOUT] == 30
            assert TraderAbciApp.event_to_timeout[TSEvent.VALIDATE_TIMEOUT] == 15
            assert TraderAbciApp.event_to_timeout[TSEvent.FINALIZE_TIMEOUT] == 20
            assert TraderAbciApp.event_to_timeout[TSEvent.CHECK_TIMEOUT] == 25

            # Verify DecisionMakerEvent redeem timeout
            assert (
                TraderAbciApp.event_to_timeout[
                    DecisionMakerEvent.REDEEM_ROUND_TIMEOUT
                ]
                == 3600
            )

            # Verify reset_pause_timeout = reset_pause_duration + MARGIN
            expected_reset_pause = 10 + MARGIN
            assert (
                TraderAbciApp.event_to_timeout[
                    ResetPauseEvent.RESET_AND_PAUSE_TIMEOUT
                ]
                == expected_reset_pause
            )
        finally:
            # Restore original event_to_timeout to avoid side effects
            TraderAbciApp.event_to_timeout = original_event_to_timeout
