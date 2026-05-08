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

"""Omen withdrawal behaviour (defensive stub, D27).

POST /api/v1/withdrawal returns 501 on Omenstrat, so this behaviour is
unreachable in normal operation. It exists only to keep the FSM symmetric
across services and to provide a sane failure mode if the on-disk flag is
somehow set on Omen.
"""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import WithdrawalPayload
from packages.valory.skills.decision_maker_abci.states.omen_withdraw import (
    OmenWithdrawRound,
)


class OmenWithdrawBehaviour(DecisionMakerBaseBehaviour):
    """OmenWithdrawBehaviour (defensive stub)."""

    matching_round = OmenWithdrawRound

    def async_act(self) -> Generator:
        """Log a warning and route to idle — Omen sell-off is not yet implemented."""
        self.context.logger.warning(
            "withdrawal: omen stub invoked — agent will halt without selling"
        )
        payload = WithdrawalPayload(sender=self.context.agent_address, vote=True)
        yield from self.finish_behaviour(payload)
