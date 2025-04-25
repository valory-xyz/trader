# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024-2025 Valory AG
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

import math
from typing import Any, Generator, Set, Type, cast

from packages.valory.contracts.mech.contract import Mech as MechContract
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.check_stop_trading_abci.models import CheckStopTradingParams
from packages.valory.skills.check_stop_trading_abci.payloads import (
    CheckStopTradingPayload,
)
from packages.valory.skills.check_stop_trading_abci.rounds import (
    CheckStopTradingAbciApp,
    CheckStopTradingRound,
)
from packages.valory.skills.staking_abci.behaviours import (
    StakingInteractBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.staking_abci.rounds import StakingState


# Liveness ratio from the staking contract is expressed in calls per 10**18 seconds.
LIVENESS_RATIO_SCALE_FACTOR = 10**18

# A safety margin in case there is a delay between the moment the KPI condition is
# satisfied, and the moment where the checkpoint is called.
REQUIRED_MECH_REQUESTS_SAFETY_MARGIN = 1


class CheckStopTradingBehaviour(StakingInteractBaseBehaviour):
    """A behaviour that checks stop trading conditions."""

    matching_round = CheckStopTradingRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the behaviour."""
        super().__init__(**kwargs)
        self._mech_requests_since_last_cp: int = 0
        self._mech_request_count: int = 0

    @property
    def mech_request_count(self) -> int:
        """Get the liveness period."""
        return self._mech_request_count

    @mech_request_count.setter
    def mech_request_count(self, mech_request_count: int) -> None:
        """Set the liveness period."""
        self._mech_request_count = mech_request_count

    @property
    def mech_requests_since_last_cp(self) -> int:
        """Get the mech requests since last checkpoint."""
        return self._mech_requests_since_last_cp

    @mech_requests_since_last_cp.setter
    def mech_requests_since_last_cp(self, mech_requests_since_last_cp: int) -> None:
        """Set the mech requests since last checkpoint."""
        self._mech_requests_since_last_cp = mech_requests_since_last_cp

    def _get_mech_request_count(self) -> WaitableConditionType:
        """Get the mech request count."""
        status = yield from self.contract_interact(
            contract_address=self.params.mech_contract_address,
            contract_public_id=MechContract.contract_id,
            contract_callable="get_requests_count",
            data_key="requests_count",
            placeholder=get_name(CheckStopTradingBehaviour.mech_request_count),
            address=self.synchronized_data.safe_contract_address,
        )
        return status

    @property
    def is_first_period(self) -> bool:
        """Return whether it is the first period of the service."""
        return self.synchronized_data.period_count == 0

    @property
    def params(self) -> CheckStopTradingParams:
        """Return the params."""

        return cast(CheckStopTradingParams, self.context.params)

    def is_staking_kpi_met(self) -> Generator[None, None, bool]:
        """Return whether the staking KPI has been met (only for staked services)."""
        yield from self.wait_for_condition_with_sleep(self._check_service_staked)
        self.context.logger.debug(f"{self.service_staking_state=}")
        if self.service_staking_state != StakingState.STAKED:
            self.mech_requests_since_last_cp = 0
            return False

        yield from self.wait_for_condition_with_sleep(self._get_mech_request_count)
        mech_request_count = self.mech_request_count
        self.context.logger.debug(f"{mech_request_count=}")

        yield from self.wait_for_condition_with_sleep(self._get_service_info)
        mech_request_count_on_last_checkpoint = self.service_info[2][1]
        self.context.logger.debug(f"{mech_request_count_on_last_checkpoint=}")

        yield from self.wait_for_condition_with_sleep(self._get_ts_checkpoint)
        last_ts_checkpoint = self.ts_checkpoint
        self.context.logger.debug(f"{last_ts_checkpoint=}")

        yield from self.wait_for_condition_with_sleep(self._get_liveness_period)
        liveness_period = self.liveness_period
        self.context.logger.debug(f"{liveness_period=}")

        yield from self.wait_for_condition_with_sleep(self._get_liveness_ratio)
        liveness_ratio = self.liveness_ratio
        self.context.logger.debug(f"{liveness_ratio=}")

        self.mech_requests_since_last_cp = (
            mech_request_count - mech_request_count_on_last_checkpoint
        )
        self.context.logger.debug(f"{self.mech_requests_since_last_cp=}")

        current_timestamp = self.synced_timestamp
        self.context.logger.debug(f"{current_timestamp=}")

        required_mech_requests = (
            math.ceil(
                max(liveness_period, (current_timestamp - last_ts_checkpoint))
                * liveness_ratio
                / LIVENESS_RATIO_SCALE_FACTOR
            )
            + REQUIRED_MECH_REQUESTS_SAFETY_MARGIN
        )
        self.context.logger.debug(f"{required_mech_requests=}")

        if self.mech_requests_since_last_cp >= required_mech_requests:
            return True
        return False

    def _compute_stop_trading(self) -> Generator[None, None, bool]:
        # This is a "hacky" way of getting required data initialized on
        # the Trader: On first period, the FSM needs to initialize some
        # data on the trading branch so that it is available in the
        # cross-period persistent keys.
        if self.is_first_period:
            self.context.logger.debug(f"{self.is_first_period=}")
            yield  # ensures this is a generator
            return False

        self.context.logger.debug(f"{self.params.disable_trading=}")
        if self.params.disable_trading:
            yield  # ensures this is a generator
            return True

        self.context.logger.debug(f"{self.params.stop_trading_if_staking_kpi_met=}")
        if self.params.stop_trading_if_staking_kpi_met:
            staking_kpi_met = yield from self.is_staking_kpi_met()
            self.context.logger.debug(f"{staking_kpi_met=}")
            return staking_kpi_met

        yield
        return False

    def async_act(self) -> Generator:
        """Do the action."""
        print("HERE")
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            stop_trading = yield from self._compute_stop_trading()
            self.context.logger.info(f"Computed {stop_trading=}")
            payload = CheckStopTradingPayload(
                self.context.agent_address,
                stop_trading,
                self.mech_requests_since_last_cp,
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
