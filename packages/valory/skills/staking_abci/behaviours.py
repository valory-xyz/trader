# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
import json
from abc import ABC
from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    Any,
    Callable,
    Generator,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    cast,
)

from aea.configurations.data_types import PublicId
from aea.contracts.base import Contract

from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.contracts.mech_activity.contract import MechActivityContract
from packages.valory.contracts.service_staking_token.contract import (
    ServiceStakingTokenContract,
)
from packages.valory.contracts.staking_token.contract import StakingTokenContract
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


NULL_ADDRESS = "0x0000000000000000000000000000000000000000"
CHECKPOINT_FILENAME = "checkpoint.txt"
READ_MODE = "r"
WRITE_MODE = "w"
CID_PREFIX = "f01701220"
GET = "GET"
OK_CODE = 200


class StakingInteractBaseBehaviour(BaseBehaviour, ABC):
    """Base behaviour that contains methods to interact with the staking contract."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the behaviour."""
        super().__init__(**kwargs)
        self._service_ids: List[str] = []
        self._max_num_services: int = 0
        self._service_staking_state: StakingState = StakingState.UNSTAKED
        self._checkpoint_ts = 0
        self._staking_contract_name: str = ""
        self._staking_contract_metadata_hash: str = ""
        self._epoch_end_ts: int = 0

    @property
    def params(self) -> StakingParams:
        """Return the params."""
        return cast(StakingParams, self.context.params)

    @property
    def use_v2(self) -> bool:
        """Whether to use the v2 staking contract."""
        return self.params.mech_activity_checker_contract != NULL_ADDRESS

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(self.round_sequence.last_round_transition_timestamp.timestamp())

    @property
    def staking_contract_address(self) -> str:
        """Get the staking contract address."""
        return self.params.staking_contract_address

    @property
    def staking_contract_name(self) -> str:
        """Get the staking contract name."""
        return self._staking_contract_name

    @staking_contract_name.setter
    def staking_contract_name(self, name: str) -> None:
        """Set the staking contract name."""
        self._staking_contract_name = name

    @property
    def mech_activity_checker_contract(self) -> str:
        """Get the staking contract address."""
        return self.params.mech_activity_checker_contract

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
        """Set the next checkpoint."""
        self._next_checkpoint = next_checkpoint

    @property
    def is_checkpoint_reached(self) -> bool:
        """Whether the next checkpoint is reached."""
        return self.next_checkpoint <= self.synced_timestamp

    @property
    def ts_checkpoint(self) -> int:
        """Get the last checkpoint timestamp."""
        return self._checkpoint_ts

    @ts_checkpoint.setter
    def ts_checkpoint(self, checkpoint_ts: int) -> None:
        """Set the last checkpoint timestamp."""
        self._checkpoint_ts = checkpoint_ts

    @property
    def liveness_period(self) -> int:
        """Get the liveness period."""
        return self._liveness_period

    @liveness_period.setter
    def liveness_period(self, liveness_period: int) -> None:
        """Set the liveness period."""
        self._liveness_period = liveness_period

    @property
    def liveness_ratio(self) -> int:
        """Get the liveness ratio."""
        return self._liveness_ratio

    @liveness_ratio.setter
    def liveness_ratio(self, liveness_ratio: int) -> None:
        """Set the liveness period."""
        self._liveness_ratio = liveness_ratio

    @property
    def service_info(self) -> Tuple[Any, Any, Tuple[Any, Any]]:
        """Get the service info."""
        return self._service_info

    @service_info.setter
    def service_info(self, service_info: Tuple[Any, Any, Tuple[Any, Any]]) -> None:
        """Set the service info."""
        self._service_info = service_info

    @property
    def max_num_services(self) -> int:
        """Get the max number of services."""
        return self._max_num_services

    @max_num_services.setter
    def max_num_services(self, max_num_services: int) -> None:
        """Set the max number of services."""
        self._max_num_services = max_num_services

    @property
    def service_ids(self) -> List[str]:
        """Get the service ids staked on the contract."""
        return self._service_ids

    @service_ids.setter
    def service_ids(self, service_ids: List[str]) -> None:
        """Set the service ids staked on the contract."""
        self._service_ids = service_ids

    @property
    def available_staking_slots(self) -> int:
        """Get the number of available staking slots"""
        if self._service_ids is None or self._max_num_services is None:
            return 0
        return self.max_num_services - len(self._service_ids)

    @property
    def staking_contract_metadata_hash(self) -> str:
        """Get the staking contract metadata hash."""
        return self._staking_contract_metadata_hash

    @staking_contract_metadata_hash.setter
    def staking_contract_metadata_hash(self, metadata_hash: str) -> None:
        """Set the staking contract metadata hash."""
        self._staking_contract_metadata_hash = metadata_hash

    @property
    def epoch_end_ts(self) -> int:
        """Get the epoch end timestamp."""
        return self._epoch_end_ts

    @epoch_end_ts.setter
    def epoch_end_ts(self, epoch_end_ts: int) -> None:
        """Set the epoch end timestamp."""
        self._epoch_end_ts = epoch_end_ts

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
            msg = f"Retrying in {self.params.staking_interaction_sleep_time} seconds."
            self.context.logger.info(msg)
            yield from self.sleep(self.params.staking_interaction_sleep_time)

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
            chain_id=self.params.mech_chain_id,
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
        contract_public_id = cast(
            Contract,
            StakingTokenContract if self.use_v2 else ServiceStakingTokenContract,
        )
        status = yield from self.contract_interact(
            contract_address=self.staking_contract_address,
            contract_public_id=contract_public_id.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _mech_activity_checker_contract_interact(
        self,
        contract_callable: str,
        placeholder: str,
        data_key: str = "data",
        **kwargs: Any,
    ) -> WaitableConditionType:
        """Interact with the staking contract."""
        status = yield from self.contract_interact(
            contract_address=self.mech_activity_checker_contract,
            contract_public_id=MechActivityContract.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _check_service_staked(self) -> WaitableConditionType:
        """Check whether the service is staked."""
        service_id = self.params.on_chain_service_id
        if service_id is None:
            self.context.logger.warning(
                "Cannot perform any staking-related operations without a configured on-chain service id. "
                "Assuming service status 'UNSTAKED'."
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

    def _get_ts_checkpoint(self) -> WaitableConditionType:
        """Get the timestamp in which the next checkpoint is reached."""
        status = yield from self._staking_contract_interact(
            contract_callable="ts_checkpoint",
            placeholder=get_name(CallCheckpointBehaviour.ts_checkpoint),
        )
        return status

    def _get_liveness_period(self) -> WaitableConditionType:
        """Get the liveness period."""
        status = yield from self._staking_contract_interact(
            contract_callable="get_liveness_period",
            placeholder=get_name(CallCheckpointBehaviour.liveness_period),
        )
        return status

    def _get_liveness_ratio(self) -> WaitableConditionType:
        """Get the liveness ratio."""
        contract_interact = (
            self._mech_activity_checker_contract_interact
            if self.use_v2
            else self._staking_contract_interact
        )
        status = yield from contract_interact(
            contract_callable="liveness_ratio",
            placeholder=get_name(CallCheckpointBehaviour.liveness_ratio),
        )
        return status

    def _get_service_info(self) -> WaitableConditionType:
        """Get the service info."""
        service_id = self.params.on_chain_service_id
        if service_id is None:
            self.context.logger.warning(
                "Cannot perform any staking-related operations without a configured on-chain service id. "
                "Assuming service status 'UNSTAKED'."
            )
            return True

        status = yield from self._staking_contract_interact(
            contract_callable="get_service_info",
            placeholder=get_name(CallCheckpointBehaviour.service_info),
            service_id=service_id,
        )
        return status

    # def _get_max_num_services(self) -> WaitableConditionType:
    #     """Get the max_num_services."""
    #     status = yield from self._staking_contract_interact(
    #         contract_callable="max_num_services",
    #         placeholder=get_name(CallCheckpointBehaviour.max_num_services),
    #     )
    #     return status
    #
    # def _get_service_ids(self) -> WaitableConditionType:
    #     """Get the staked service ids."""
    #     status = yield from self._staking_contract_interact(
    #         contract_callable="get_service_ids",
    #         placeholder=get_name(CallCheckpointBehaviour.service_ids),
    #     )
    #     return status
    #
    def _get_staking_contract_metadata_hash(self) -> Generator:
        """Get the staking contract metadata hash."""
        status = yield from self._staking_contract_interact(
            contract_callable="get_metadata_hash",
            placeholder=get_name(
                CallCheckpointBehaviour.staking_contract_metadata_hash
            ),
        )
        return status

    def _get_staking_contract_name(self) -> WaitableConditionType:
        """Get the staking contract name."""
        self.context.logger.info("Reading staking contract name from IPFS...")
        staking_contract_metadata_hash = self.staking_contract_metadata_hash
        staking_contract_metadata_hash_formatted = (
            staking_contract_metadata_hash.replace("0x", CID_PREFIX)
        )
        staking_contract_link = (
            self.params.ipfs_address + staking_contract_metadata_hash_formatted
        )
        response = yield from self.get_http_response(
            method=GET, url=staking_contract_link
        )
        if response.status_code != OK_CODE:
            self.context.logger.error(
                f"Could not retrieve data from the url {staking_contract_link}. "
                f"Received status code {response.status_code}."
            )
            return False

        self.context.logger.info("Parsing staking contract name...")
        try:
            response_body = response.body.decode()
            response_json = json.loads(response_body)
            self.staking_contract_name = response_json["name"]
        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"Could not parse response from ipfs server, "
                f"the following error was encountered {type(e).__name__}: {e}"
            )
            return False

        return True

    def _get_epoch_end(self) -> WaitableConditionType:
        """Get the epoch end."""
        status = yield from self._staking_contract_interact(
            contract_callable="get_epoch_end",
            placeholder=get_name(CallCheckpointBehaviour.epoch_end_ts),
        )
        return status


class CallCheckpointBehaviour(
    StakingInteractBaseBehaviour
):  # pylint-disable too-many-ancestors
    """Behaviour that calls the checkpoint contract function if the service is staked and if it is necessary."""

    matching_round = CallCheckpointRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the behaviour."""
        super().__init__(**kwargs)
        self._service_staking_state: StakingState = StakingState.UNSTAKED
        self._next_checkpoint: int = 0
        self._checkpoint_data: bytes = b""
        self._safe_tx_hash: str = ""
        self._checkpoint_filepath: Path = self.params.store_path / CHECKPOINT_FILENAME

    @property
    def params(self) -> StakingParams:
        """Return the params."""
        return cast(StakingParams, self.context.params)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    @property
    def is_first_period(self) -> bool:
        """Return whether it is the first period of the service."""
        return self.synchronized_data.period_count == 0

    @property
    def new_checkpoint_detected(self) -> bool:
        """Whether a new checkpoint has been detected."""
        previous_checkpoint = self.synchronized_data.previous_checkpoint
        return bool(previous_checkpoint) and previous_checkpoint != self.ts_checkpoint

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

    def read_stored_timestamp(self) -> Optional[int]:
        """Read the timestamp from the agent's data dir."""
        try:
            with open(self._checkpoint_filepath, READ_MODE) as checkpoint_file:
                try:
                    return int(checkpoint_file.readline())
                except (ValueError, TypeError, StopIteration):
                    err = f"Stored checkpoint timestamp could not be parsed from {self._checkpoint_filepath!r}!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {self._checkpoint_filepath!r} in {READ_MODE!r} mode!"

        self.context.logger.error(err)
        return None

    def store_timestamp(self) -> int:
        """Store the timestamp to the agent's data dir."""
        if self.ts_checkpoint == 0:
            self.context.logger.warning("No checkpoint timestamp to store!")
            return 0

        try:
            with open(self._checkpoint_filepath, WRITE_MODE) as checkpoint_file:
                try:
                    return checkpoint_file.write(str(self.ts_checkpoint))
                except (IOError, OSError):
                    err = f"Error writing to file {self._checkpoint_filepath!r}!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {self._checkpoint_filepath!r} in {WRITE_MODE!r} mode!"

        self.context.logger.error(err)
        return 0

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

    def check_new_epoch(self) -> Generator[None, None, bool]:
        """Check if a new epoch has been reached."""
        yield from self.wait_for_condition_with_sleep(self._get_ts_checkpoint)
        stored_timestamp_invalidated = False

        # if it is the first period of the service,
        #     1. check if the stored timestamp is the same as the current checkpoint
        #     2. if not, update the corresponding flag
        # That way, we protect from the case in which the user stops their service
        # before the next checkpoint is reached and restarts it afterward.
        if self.is_first_period:
            stored_timestamp = self.read_stored_timestamp()
            stored_timestamp_invalidated = stored_timestamp != self.ts_checkpoint

        is_checkpoint_reached = (
            stored_timestamp_invalidated or self.new_checkpoint_detected
        )
        if is_checkpoint_reached:
            self.context.logger.info("An epoch change has been detected.")
            status = self.store_timestamp()
            if status:
                self.context.logger.info(
                    "Successfully updated the stored checkpoint timestamp."
                )

        return is_checkpoint_reached

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self.wait_for_condition_with_sleep(self._check_service_staked)

            checkpoint_tx_hex = None
            if self.service_staking_state == StakingState.STAKED:
                yield from self.wait_for_condition_with_sleep(self._get_next_checkpoint)
                yield from self.wait_for_condition_with_sleep(
                    self._get_staking_contract_metadata_hash
                )
                yield from self.wait_for_condition_with_sleep(
                    self._get_staking_contract_name
                )
                yield from self.wait_for_condition_with_sleep(self._get_epoch_end)
                if self.is_checkpoint_reached:
                    checkpoint_tx_hex = yield from self._prepare_safe_tx()

            if self.service_staking_state == StakingState.EVICTED:
                self.context.logger.critical("Service has been evicted!")

            tx_submitter = self.matching_round.auto_round_id()
            is_checkpoint_reached = yield from self.check_new_epoch()
            payload = CallCheckpointPayload(
                self.context.agent_address,
                tx_submitter,
                checkpoint_tx_hex,
                self.service_staking_state.value,
                self.ts_checkpoint,
                is_checkpoint_reached,
                self.available_staking_slots,
                self.staking_contract_name,
                self.epoch_end_ts,
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
