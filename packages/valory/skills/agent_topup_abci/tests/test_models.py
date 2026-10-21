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

"""Tests for the models of the agent top-up skill."""

from unittest.mock import MagicMock

from packages.valory.skills.agent_topup_abci.models import SharedState
from packages.valory.skills.agent_topup_abci.rounds import AgentTopUpAbciApp


def test_shared_state_runs_the_agent_topup_app() -> None:
    """The shared state is bound to the agent top-up app."""
    shared_state = SharedState(name="state", skill_context=MagicMock())

    assert shared_state.abci_app_cls is AgentTopUpAbciApp
