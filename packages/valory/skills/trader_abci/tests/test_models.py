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

import inspect
import re
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, PropertyMock, patch

import yaml

from packages.valory.skills.chatui_abci.models import ChatuiParams
from packages.valory.skills.decision_maker_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.decision_maker_abci.rounds import (
    Event as DecisionMakerEvent,
)
from packages.valory.skills.market_manager_abci.rounds import (
    Event as MarketManagerEvent,
)
from packages.valory.skills.mech_interact_abci.models import MechParams
from packages.valory.skills.mech_interact_abci.rounds import Event as MechInteractEvent
from packages.valory.skills.reset_pause_abci.rounds import Event as ResetPauseEvent
from packages.valory.skills.trader_abci.composition import TraderAbciApp
from packages.valory.skills.trader_abci.models import MARGIN, SharedState, TraderParams
from packages.valory.skills.transaction_settlement_abci.rounds import Event as TSEvent


class TestTraderParams:
    """Tests for the TraderParams model."""

    def test_init_sets_attributes(self) -> None:
        """TraderParams.__init__ sets its own attributes from kwargs."""
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
        with patch.object(TraderParams.__mro__[1], "__init__", return_value=None):
            params = TraderParams.__new__(TraderParams)
            TraderParams.__init__(params, **kwargs)

        assert params.mech_interact_round_timeout_seconds == 300
        assert params.genai_api_key == "test-key"
        assert params.x402_payment_requirements == {"threshold": 100}
        assert params.lifi_quote_to_amount_url == "https://example.com/lifi"
        assert params.gnosis_ledger_rpc == "https://gnosis-rpc.example.com"
        assert params.polygon_ledger_rpc == "https://polygon-rpc.example.com"
        assert params.use_x402 is True


def test_trader_params_set_every_chat_param() -> None:
    """The chat handler reads `context.params`, which is `TraderParams` in the agent.

    `TraderParams` does not inherit `ChatuiParams`, so each chat param has to be
    read by `TraderParams` or one of its parents, or the chat fails at runtime.
    """
    ensured = re.compile(r'_ensure\(\s*"([a-z_]+)"')
    chat_params = set(ensured.findall(inspect.getsource(ChatuiParams.__init__)))
    trader_params = {
        key
        for cls in TraderParams.__mro__
        if inspect.isfunction(vars(cls).get("__init__"))
        for key in ensured.findall(inspect.getsource(vars(cls)["__init__"]))
    }
    assert chat_params, "no chat params found"
    assert chat_params <= trader_params, chat_params - trader_params


def test_the_chat_can_read_mechs_through_the_composed_context() -> None:
    """`read_mech` and `read_live_rate` read the params and these models from the chat's context.

    In the agent that context is the trader skill's, so its params must be
    `MechParams` (for `mech_chain_id` and `marketplace_api_url`) and it must
    declare every model the reader uses.
    """
    assert issubclass(TraderParams, MechParams)
    config = yaml.safe_load(
        (Path(__file__).parents[1] / "skill.yaml").read_text(encoding="utf-8")
    )
    models = config["models"]
    assert {
        "mechs_subgraph",
        "http_dialogues",
        "contract_api_dialogues",
        "requests",
    } <= set(models)
    assert models["params"]["class_name"] == "TraderParams"
    assert "marketplace_api_url" in models["params"]["args"]


class TestSharedState:
    """Tests for the SharedState model."""

    def test_params_property(self) -> None:
        """The params property casts context.params to TraderParams."""
        state = SharedState.__new__(SharedState)
        mock_params = MagicMock(spec=TraderParams)
        mock_context = MagicMock()
        mock_context.params = mock_params

        with patch.object(
            type(state), "context", new_callable=PropertyMock, return_value=mock_context
        ):
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
        mock_params.withdrawal_round_timeout = 1800

        # Save original event_to_timeout so we can restore it after test
        original_event_to_timeout = TraderAbciApp.event_to_timeout.copy()

        try:
            with (
                patch.object(
                    type(state),
                    "params",
                    new_callable=PropertyMock,
                    return_value=mock_params,
                ),
                patch.object(
                    type(state),
                    "context",
                    new_callable=PropertyMock,
                    return_value=MagicMock(shared_state={}),
                ),
                patch.object(BaseSharedState, "setup", return_value=None),
            ):
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
            assert TraderAbciApp.event_to_timeout[ResetPauseEvent.ROUND_TIMEOUT] == 30

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
                TraderAbciApp.event_to_timeout[DecisionMakerEvent.REDEEM_ROUND_TIMEOUT]
                == 3600
            )

            # Verify DecisionMakerEvent withdrawal timeout
            assert (
                TraderAbciApp.event_to_timeout[
                    DecisionMakerEvent.WITHDRAWAL_ROUND_TIMEOUT
                ]
                == 1800
            )

            # Verify reset_pause_timeout = reset_pause_duration + MARGIN
            expected_reset_pause = 10 + MARGIN
            assert (
                TraderAbciApp.event_to_timeout[ResetPauseEvent.RESET_AND_PAUSE_TIMEOUT]
                == expected_reset_pause
            )
        finally:
            # Restore original event_to_timeout to avoid side effects
            TraderAbciApp.event_to_timeout = original_event_to_timeout
