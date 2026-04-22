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

"""Tests for the composition module of the trader_abci skill."""

# pylint: skip-file

import pytest

from packages.valory.skills.check_stop_trading_abci.rounds import CheckStopTradingRound
from packages.valory.skills.decision_maker_abci.states.final_states import (
    FinishedPostBetUpdateRound,
)
from packages.valory.skills.decision_maker_abci.states.post_bet_update import (
    PostBetUpdateRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem_router import (
    RedeemRouterRound,
)
from packages.valory.skills.market_manager_abci.rounds import (
    FinishedMarketManagerRound,
    FinishedPolymarketFetchMarketRound,
)
from packages.valory.skills.staking_abci.rounds import CallCheckpointRound
from packages.valory.skills.termination_abci.rounds import (
    BackgroundRound,
    Event,
    TerminationAbciApp,
)
from packages.valory.skills.trader_abci.composition import (
    TraderAbciApp,
    abci_app_transition_mapping,
    termination_config,
)
from packages.valory.skills.tx_settlement_multiplexer_abci.rounds import (
    FinishedBetPlacementTxRound,
    FinishedRedeemingTxRound,
    FinishedSellOutcomeTokensTxRound,
)

EXPECTED_TRANSITION_MAPPING_LENGTH = 48

# Transitions introduced or rewired by the always-redeem-first /
# `PostBetUpdateRound` FSM restructure (PR #904). Each pair must hold
# exactly; a typo, swap, or accidental retarget will trip the matching
# parametrised assertion. The count tripwire above stays in place to
# catch additions/removals that preserve every listed edge.
RESTRUCTURE_TRANSITIONS = {
    # Always-redeem-first: market fetch → redeem router, so any unclaimed
    # winnings are redeemed before the next mech/bet cycle.
    FinishedMarketManagerRound: RedeemRouterRound,
    FinishedPolymarketFetchMarketRound: RedeemRouterRound,
    # Redeem terminals now feed CheckStopTrading (previously the other
    # way around).
    FinishedRedeemingTxRound: CheckStopTradingRound,
    # Omen on-chain bet / sell settle into the new PostBetUpdateRound
    # which runs the local-state bookkeeping that legacy RedeemBehaviour
    # used to do as a post-tx side effect.
    FinishedBetPlacementTxRound: PostBetUpdateRound,
    FinishedSellOutcomeTokensTxRound: PostBetUpdateRound,
    FinishedPostBetUpdateRound: CallCheckpointRound,
}


@pytest.mark.parametrize(
    "src,dst",
    list(RESTRUCTURE_TRANSITIONS.items()),
    ids=lambda cls: getattr(cls, "__name__", str(cls)),
)
def test_restructure_transition(src: type, dst: type) -> None:
    """Each PR-#904 transition must resolve to its exact target round."""
    assert src in abci_app_transition_mapping, f"{src.__name__} missing from mapping"
    assert abci_app_transition_mapping[src] is dst, (
        f"{src.__name__} -> {abci_app_transition_mapping[src].__name__}, "
        f"expected {dst.__name__}"
    )


def test_only_expected_edges_enter_post_bet_update() -> None:
    """Exactly the Omen bet / sell tx-settlement terminals feed PostBetUpdateRound.

    An accidental additional route into PostBetUpdateRound would let
    non-bet/sell flows trigger the post-bet bookkeeping helpers.
    """
    edges_into = {
        src
        for src, dst in abci_app_transition_mapping.items()
        if dst is PostBetUpdateRound
    }
    assert edges_into == {
        FinishedBetPlacementTxRound,
        FinishedSellOutcomeTokensTxRound,
    }


def test_abci_app_transition_mapping_type() -> None:
    """Test that abci_app_transition_mapping is a dict."""
    assert isinstance(abci_app_transition_mapping, dict)


def test_abci_app_transition_mapping_length() -> None:
    """Test that abci_app_transition_mapping has the expected number of entries."""
    assert len(abci_app_transition_mapping) == EXPECTED_TRANSITION_MAPPING_LENGTH, (
        f"Expected {EXPECTED_TRANSITION_MAPPING_LENGTH} entries, "
        f"got {len(abci_app_transition_mapping)}"
    )


def test_abci_app_transition_mapping_keys_are_round_classes() -> None:
    """Test that all keys in the transition mapping are round classes (types)."""
    for key in abci_app_transition_mapping:
        assert isinstance(key, type), f"Key {key} is not a class"


def test_abci_app_transition_mapping_values_are_round_classes() -> None:
    """Test that all values in the transition mapping are round classes (types)."""
    for value in abci_app_transition_mapping.values():
        assert isinstance(value, type), f"Value {value} is not a class"


def test_termination_config_round_cls() -> None:
    """Test that termination_config has the correct round_cls."""
    assert termination_config.round_cls is BackgroundRound


def test_termination_config_start_event() -> None:
    """Test that termination_config has the correct start_event."""
    assert termination_config.start_event == Event.TERMINATE


def test_termination_config_abci_app() -> None:
    """Test that termination_config has the correct abci_app."""
    assert termination_config.abci_app is TerminationAbciApp


def test_trader_abci_app_is_type() -> None:
    """Test that TraderAbciApp is a type (class), not an instance."""
    assert isinstance(TraderAbciApp, type)
