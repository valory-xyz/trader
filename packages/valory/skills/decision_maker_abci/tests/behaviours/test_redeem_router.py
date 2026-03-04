# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""Tests for RedeemRouterBehaviour."""

from unittest.mock import MagicMock

from packages.valory.skills.decision_maker_abci.behaviours.redeem_router import (
    RedeemRouterBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import RedeemRouterPayload
from packages.valory.skills.decision_maker_abci.states.redeem_router import (
    RedeemRouterRound,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_behaviour():
    """Return a RedeemRouterBehaviour with mocked dependencies."""
    behaviour = object.__new__(RedeemRouterBehaviour)
    context = MagicMock()
    context.agent_address = "test_agent"
    behaviour.__dict__["_context"] = context
    return behaviour


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRedeemRouterBehaviour:
    """Tests for RedeemRouterBehaviour."""

    def test_matching_round(self) -> None:
        """matching_round should be RedeemRouterRound."""
        assert RedeemRouterBehaviour.matching_round == RedeemRouterRound

    def test_async_act_sends_vote_true(self) -> None:
        """async_act should always send a payload with vote=True."""
        behaviour = _make_behaviour()

        payloads_sent = []

        def mock_finish(payload):
            payloads_sent.append(payload)
            yield

        behaviour.finish_behaviour = mock_finish

        gen = behaviour.async_act()
        try:
            while True:
                next(gen)
        except StopIteration:
            pass

        assert len(payloads_sent) == 1
        payload = payloads_sent[0]
        assert isinstance(payload, RedeemRouterPayload)
        assert payload.vote is True
        assert payload.sender == "test_agent"
