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

"""This module contains the behaviours for the check stop trading skill."""

from datetime import datetime, timedelta
from typing import Any, Callable, Generator, Optional, Set, Type, cast

from aea.configurations.data_types import PublicId

from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
    StakingState,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    BaseBehaviour,
    TimeoutException,
)
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.check_stop_trading_abci.models import CheckStopTradingParams
from packages.valory.skills.check_stop_trading_abci.payloads import CheckStopTradingPayload
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingRound,
    CheckStopTradingAbciApp,
    SynchronizedData,
)


WaitableConditionType = Generator[None, None, bool]


class CheckStopTradingBehaviour(BaseBehaviour):
    """A behaviour that checks stop trading conditions."""

    matching_round = CheckStopTradingRound

    @property
    def params(self) -> CheckStopTradingParams:
        """Return the params."""
        return cast(CheckStopTradingParams, self.context.params)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            stop_trading = self.params.disable_trading
            self.context.logger.info(
                f"self.params.disable_trading={self.params.disable_trading}"
            )

            self.context.logger.info(f"stop_trading={stop_trading}")
            payload = CheckStopTradingPayload(
                self.context.agent_address, stop_trading
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()


class CheckStopTradingRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the check stop trading behaviour."""

    initial_behaviour_cls = CheckStopTradingBehaviour
    abci_app_cls = CheckStopTradingAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {CheckStopTradingBehaviour}  # type: ignore
