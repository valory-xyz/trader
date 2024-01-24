# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
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

"""This module contains the behaviours for the staking skill."""

from datetime import datetime, timedelta
from typing import Any, Callable, Generator, Optional, Set, Type, Union, cast

from aea.configurations.data_types import PublicId

from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.behaviour_utils import (
    BaseBehaviour,
    TimeoutException,
)
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.staking_abci.models import StakingParams
from packages.valory.skills.staking_abci.payloads import CallCheckpointPayload
from packages.valory.skills.staking_abci.rounds import (
    CallCheckpointRound,
    StakingAbciApp,
    StakingState,
    SynchronizedData,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


WaitableConditionType = Generator[None, None, bool]


ETH_PRICE = 0
# setting the safe gas to 0 means that all available gas will be used
# which is what we want in most cases
# more info here: https://safe-docs.dev.gnosisdev.com/safe/docs/contracts_tx_execution/
SAFE_GAS = 0


class CallCheckpointBehaviour(BaseBehaviour):
    """Behaviour that calls the checkpoint contract function if the service is staked and if it is necessary."""

    matching_round = CallCheckpointRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the behaviour."""
        super().__init__(**kwargs)
        self._service_staking_state: StakingState = StakingState.UNSTAKED
        self._next_checkpoint: int = 0
        self._checkpoint_data: bytes = b""
        self._safe_tx_hash: str = ""

    @property
    def params(self) -> StakingParams:
        """Return the params."""
        return cast(StakingParams, self.context.params)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(self.round_sequence.last_round_transition_timestamp.timestamp())

    @property
    def service_staking_state(self) -> StakingState:
        """Get the service's staking state."""
        return self._service_staking_state

    @service_staking_state.setter
    def service_staking_state(self, state: Union[StakingState, int]) -> None:
        """Set the service's staking state."""
        if isinstance(state, int):
            state = StakingState(state)
        self._service_staking_state = state

    @property
    def next_checkpoint(self) -> int:
        """Get the next checkpoint."""
        return self._next_checkpoint

    @next_checkpoint.setter
    def next_checkpoint(self, next_checkpoint: int) -> None:
        """Whether the service is staked."""
        self._next_checkpoint = next_checkpoint

    @property
    def is_checkpoint_reached(self) -> bool:
        """Whether the next checkpoint is reached."""
        return self.next_checkpoint <= self.synced_timestamp

    @property
    def checkpoint_data(self) -> bytes:
        """Get the checkpoint data."""
        return self._checkpoint_data

    @checkpoint_data.setter
    def checkpoint_data(self, data: bytes) -> None:
        """Set the request data."""
        self._checkpoint_data = data

    @property
    def safe_tx_hash(self) -> str:
        """Get the safe_tx_hash."""
        return self._safe_tx_hash

    @safe_tx_hash.setter
    def safe_tx_hash(self, safe_hash: str) -> None:
        """Set the safe_tx_hash."""
        length = len(safe_hash)
        if length != TX_HASH_LENGTH:
            raise ValueError(
                f"Incorrect length {length} != {TX_HASH_LENGTH} detected "
                f"when trying to assign a safe transaction hash: {safe_hash}"
            )
        self._safe_tx_hash = safe_hash[2:]

    def wait_for_condition_with_sleep(
        self,
        condition_gen: Callable[[], WaitableConditionType],
        timeout: Optional[float] = None,
    ) -> Generator[None, None, None]:
        """Wait for a condition to happen and sleep in-between checks.

        This is a modified version of the base `wait_for_condition` method which:
            1. accepts a generator that creates the condition instead of a callable
            2. sleeps in-between checks

        :param condition_gen: a generator of the condition to wait for
        :param timeout: the maximum amount of time to wait
        :yield: None
        """

        deadline = (
            datetime.now() + timedelta(0, timeout)
            if timeout is not None
            else datetime.max
        )

        while True:
            condition_satisfied = yield from condition_gen()
            if condition_satisfied:
                break
            if timeout is not None and datetime.now() > deadline:
                raise TimeoutException()
            self.context.logger.info(f"Retrying in {self.params.sleep_time} seconds.")
            yield from self.sleep(self.params.sleep_time)

    def default_error(
        self, contract_id: str, contract_callable: str, response_msg: ContractApiMessage
    ) -> None:
        """Return a default contract interaction error message."""
        self.context.logger.error(
            f"Could not successfully interact with the {contract_id} contract "
            f"using {contract_callable!r}: {response_msg}"
        )

    def contract_interact(
        self,
        contract_address: str,
        contract_public_id: PublicId,
        contract_callable: str,
        data_key: str,
        placeholder: str,
        **kwargs: Any,
    ) -> WaitableConditionType:
        """Interact with a contract."""
        contract_id = str(contract_public_id)
        response_msg = yield from self.get_contract_api_response(
            ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address,
            contract_id,
            contract_callable,
            **kwargs,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.default_error(contract_id, contract_callable, response_msg)
            return False

        data = response_msg.raw_transaction.body.get(data_key, None)
        if data is None:
            self.default_error(contract_id, contract_callable, response_msg)
            return False

        setattr(self, placeholder, data)
        return True

    def _staking_contract_interact(
        self,
        contract_callable: str,
        placeholder: str,
        data_key: str = "data",
        **kwargs: Any,
    ) -> WaitableConditionType:
        """Interact with the staking contract."""
        status = yield from self.contract_interact(
            contract_address=self.params.staking_contract_address,
            contract_public_id=ServiceStakingTokenContract.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _check_service_staked(self) -> WaitableConditionType:
        """Check whether the service is staked."""
        if self.synchronized_data.period_count != 0:
            self.is_service_staked = self.synchronized_data.is_service_staked
            return True

        service_id = self.params.on_chain_service_id
        if service_id is None:
            self.context.logger.warning(
                "Cannot perform any staking-related operations without a configured on-chain service id. "
                "Setting status to 'not staked'."
            )
            return True

        status = yield from self._staking_contract_interact(
            contract_callable="get_service_staking_state",
            placeholder=get_name(CallCheckpointBehaviour.service_staking_state),
            service_id=service_id,
        )

        return status

    def _get_next_checkpoint(self) -> WaitableConditionType:
        """Get the timestamp in which the next checkpoint is reached."""
        status = yield from self._staking_contract_interact(
            contract_callable="get_next_checkpoint_ts",
            placeholder=get_name(CallCheckpointBehaviour.next_checkpoint),
        )
        return status

    def _build_checkpoint_tx(self) -> WaitableConditionType:
        """Get the request tx data encoded."""
        result = yield from self._staking_contract_interact(
            contract_callable="build_checkpoint_tx",
            placeholder=get_name(CallCheckpointBehaviour.checkpoint_data),
        )

        return result

    def _get_safe_tx_hash(self) -> WaitableConditionType:
        """Prepares and returns the safe tx hash."""
        status = yield from self.contract_interact(
            contract_address=self.synchronized_data.safe_contract_address,
            contract_public_id=GnosisSafeContract.contract_id,
            contract_callable="get_raw_safe_transaction_hash",
            data_key="tx_hash",
            placeholder=get_name(CallCheckpointBehaviour.safe_tx_hash),
            to_address=self.params.staking_contract_address,
            value=ETH_PRICE,
            data=self.checkpoint_data,
        )
        return status

    def _prepare_safe_tx(self) -> Generator[None, None, str]:
        """Prepare the safe transaction for calling the checkpoint and return the hex for the tx settlement skill."""
        yield from self.wait_for_condition_with_sleep(self._build_checkpoint_tx)
        yield from self.wait_for_condition_with_sleep(self._get_safe_tx_hash)
        return hash_payload_to_hex(
            self.safe_tx_hash,
            ETH_PRICE,
            SAFE_GAS,
            self.params.staking_contract_address,
            self.checkpoint_data,
        )

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self.wait_for_condition_with_sleep(self._check_service_staked)

            checkpoint_tx_hex = None
            if self.service_staking_state == StakingState.STAKED:
                yield from self.wait_for_condition_with_sleep(self._get_next_checkpoint)
                if self.is_checkpoint_reached:
                    checkpoint_tx_hex = yield from self._prepare_safe_tx()

            tx_submitter = self.matching_round.auto_round_id()
            payload = CallCheckpointPayload(
                self.context.agent_address,
                tx_submitter,
                checkpoint_tx_hex,
                self.service_staking_state.value,
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()


class StakingRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the staking behaviour."""

    initial_behaviour_cls = CallCheckpointBehaviour
    abci_app_cls = StakingAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {CallCheckpointBehaviour}  # type: ignore
