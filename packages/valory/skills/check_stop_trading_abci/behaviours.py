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

"""This module contains the behaviours for the check stop trading skill."""

import math
from typing import Any, Generator, NamedTuple, Set, Tuple, Type, cast

from packages.valory.contracts.agent_mech.contract import AgentMech
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


class StopTradingResult(NamedTuple):
    """The outcome of a stop-trading evaluation for one cycle.

    ``stop``                — the vote (drives ``SKIP_TRADING`` / ``DONE``).
    ``staking_kpi_met``     — on-chain (livenessRatio-derived) KPI; healthcheck only.
    ``activity_target_met`` — regime-aware "epoch work done"; the rotation signal.
    ``target`` / ``completed`` — per-epoch progress (target source differs by regime).
    """

    stop: bool
    staking_kpi_met: bool
    activity_target_met: bool
    target: int
    completed: int


class CheckStopTradingBehaviour(StakingInteractBaseBehaviour):
    """A behaviour that checks stop trading conditions."""

    matching_round = CheckStopTradingRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the behaviour."""
        super().__init__(**kwargs)
        self._staking_kpi_request_count: int = 0

    @property
    def staking_kpi_request_count(self) -> int:
        """Get the staking KPI request count."""
        return self._staking_kpi_request_count

    @staking_kpi_request_count.setter
    def staking_kpi_request_count(self, staking_kpi_request_count: int) -> None:
        """Set the staking KPI request count."""
        self._staking_kpi_request_count = staking_kpi_request_count

    def _get_staking_kpi_request_count(self) -> WaitableConditionType:
        """Get the request count from the appropriate contract based on configuration."""
        if self.params.use_mech_marketplace:
            mech_contract_id = AgentMech.contract_id
            request_count_callable = "get_request_count"
        else:
            mech_contract_id = MechContract.contract_id
            request_count_callable = "get_requests_count"

        status = yield from self.contract_interact(
            contract_address=self.params.staking_kpi_mech_count_request_address,
            contract_public_id=mech_contract_id,
            contract_callable=request_count_callable,
            data_key="requests_count",
            placeholder=get_name(CheckStopTradingBehaviour.staking_kpi_request_count),
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

    def _required_mech_requests(
        self,
        last_ts_checkpoint: int,
        liveness_period: int,
        liveness_ratio: int,
    ) -> int:
        """The on-chain (livenessRatio-derived) requirement.

        Pure function of already-read inputs — the same arithmetic the on-chain
        KPI has always used, extracted so the reads can be shared with the
        activity-target branch.

        :param last_ts_checkpoint: timestamp of the last checkpoint.
        :param liveness_period: the staking liveness period.
        :param liveness_ratio: the staking liveness ratio.
        :return: the required number of mech requests this epoch.
        """
        return (
            math.ceil(
                max(liveness_period, (self.synced_timestamp - last_ts_checkpoint))
                * liveness_ratio
                / LIVENESS_RATIO_SCALE_FACTOR
            )
            + REQUIRED_MECH_REQUESTS_SAFETY_MARGIN
        )

    def _compute_activity_status(
        self,
    ) -> Generator[None, None, Tuple[bool, bool, int, int]]:
        """Read activity once and derive every coherent quantity for the cycle.

        Returns ``(staking_kpi_met, activity_target_met, target, completed)``:

        * ``staking_kpi_met`` — the ON-CHAIN KPI (livenessRatio-derived), both
          regimes; surfaced on ``/healthcheck`` only.
        * ``activity_target_met`` — the regime-aware "agent has done its epoch
          work" signal that drives the stop vote and Pearl auto-run rotation.
        * ``target`` / ``completed`` — per-epoch progress; ``target`` is the
          off-chain config target in the new regime, the derived on-chain
          requirement in the old.

        Every on-chain read happens exactly once here, so all derived values are
        mutually coherent even if a mech request lands mid-cycle.

        :return: the activity status tuple.
        :yield: contract-read steps.
        """
        yield from self.wait_for_condition_with_sleep(self._check_service_staked)
        self.context.logger.debug(f"{self.service_staking_state=}")
        if self.service_staking_state != StakingState.STAKED:
            return False, False, 0, 0

        # --- single read of every input (shared across KPI + activity target) ---
        yield from self.wait_for_condition_with_sleep(
            self._get_staking_kpi_request_count
        )
        yield from self.wait_for_condition_with_sleep(self._get_service_info)
        yield from self.wait_for_condition_with_sleep(self._get_ts_checkpoint)
        yield from self.wait_for_condition_with_sleep(self._get_liveness_period)
        yield from self.wait_for_condition_with_sleep(self._get_liveness_ratio)

        # length-2 ``getMultisigNonces`` on both V1 and V2 ⇒ index 1 is requests
        completed = self.staking_kpi_request_count - self.service_info[2][1]
        self.context.logger.debug(f"{completed=}")
        required = self._required_mech_requests(
            self.ts_checkpoint, self.liveness_period, self.liveness_ratio
        )
        self.context.logger.debug(f"{required=}")
        staking_kpi_met = completed >= required

        new_regime = yield from self._is_new_staking_regime()
        if new_regime:
            target = self.params.activity_target
            activity_target_met = completed >= target
        else:
            target = required
            activity_target_met = staking_kpi_met

        self.context.logger.debug(
            f"{staking_kpi_met=} {activity_target_met=} {target=}"
        )
        return staking_kpi_met, activity_target_met, target, completed

    def is_staking_kpi_met(self) -> Generator[None, None, bool]:
        """Return whether the on-chain staking KPI has been met (staked services only).

        Thin public wrapper retained for existing callers; the arithmetic now
        lives in :meth:`_compute_activity_status` so the reads are shared.

        :return: whether the on-chain staking KPI is met.
        :yield: contract-read steps.
        """
        staking_kpi_met, _, _, _ = yield from self._compute_activity_status()
        return staking_kpi_met

    def _compute_stop_trading(self) -> Generator[None, None, StopTradingResult]:
        """Compute the stop-trading decision and the activity signals for the cycle.

        :return: the :class:`StopTradingResult` for this cycle.
        :yield: contract-read steps.
        """
        self.context.logger.debug(f"{self.params.disable_trading=}")
        if self.params.disable_trading:
            return StopTradingResult(
                stop=True,
                staking_kpi_met=False,
                activity_target_met=False,
                target=0,
                completed=0,
            )

        (
            staking_kpi_met,
            activity_target_met,
            target,
            completed,
        ) = yield from self._compute_activity_status()
        self.context.logger.debug(f"{self.params.stop_trading_if_staking_kpi_met=}")
        stop = self.params.stop_trading_if_staking_kpi_met and activity_target_met
        return StopTradingResult(
            stop, staking_kpi_met, activity_target_met, target, completed
        )

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            result = yield from self._compute_stop_trading()
            stop_trading = result.stop
            self.context.logger.info(f"Computed {stop_trading=}")
            payload = CheckStopTradingPayload(
                self.context.agent_address,
                result.stop,
                is_staking_kpi_met=result.staking_kpi_met,
                is_activity_target_met=result.activity_target_met,
                activity_target=result.target,
                activity_completed=result.completed,
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
