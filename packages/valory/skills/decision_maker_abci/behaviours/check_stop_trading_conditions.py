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

"""This module contains the behaviour of the skill which is responsible for checking stop trading conditions."""

from typing import Generator

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    CheckStopTradingConditionsPayload,
)
from packages.valory.skills.decision_maker_abci.states.check_stop_trading_conditions import (
    CheckStopTradingConditionsRound,
)


class CheckStopTradingConditionsBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents select a mech tool."""

    matching_round = CheckStopTradingConditionsRound

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            stop_trading = self.params.stop_trading
            self.context.logger.info(
                f"self.params.stop_trading={self.params.stop_trading}"
            )

            self.context.logger.info(f"stop_trading={stop_trading}")
            payload = CheckStopTradingConditionsPayload(
                self.context.agent_address, stop_trading
            )

        yield from self.finish_behaviour(payload)
