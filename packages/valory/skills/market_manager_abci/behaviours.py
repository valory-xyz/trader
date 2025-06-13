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

"""This module contains the behaviours for the MarketManager skill."""

import json
import os.path
from abc import ABC
from json import JSONDecodeError
from typing import Any, Dict, Generator, List, Optional, Set, Type, cast

from aea.helpers.ipfs.base import IPFSHashOnly

from packages.valory.contracts.service_registry.contract import ServiceRegistryContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetsDecoder,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    MAX_LOG_SIZE,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.models import (
    BenchmarkingMode,
    SharedState,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import (
    MarketManagerAbciApp,
    UpdateBetsRound,
)

WaitableConditionType = Generator[None, None, bool]

BETS_FILENAME = "bets.json"
MULTI_BETS_FILENAME = "multi_bets.json"
READ_MODE = "r"
WRITE_MODE = "w"


class BetsManagerBehaviour(BaseBehaviour, ABC):
    """Abstract behaviour responsible for bets management, such as storing, hashing, reading."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `BetsManagerBehaviour`."""
        super().__init__(**kwargs)
        self.bets: List[Bet] = []
        self.multi_bets_filepath: str = self.params.store_path / MULTI_BETS_FILENAME
        self.bets_filepath: str = self.params.store_path / BETS_FILENAME
        self.service_owner_address: str = ""

    @property
    def shared_state(self) -> SharedState:
        """Get the shared state."""
        return cast(SharedState, self.context.state)

    @property
    def benchmarking_mode(self) -> BenchmarkingMode:
        """Return the benchmarking mode configurations."""
        return cast(BenchmarkingMode, self.context.benchmarking_mode)

    def get_service_owner(self) -> WaitableConditionType:
        """Method that returns the service owner."""

        response = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_id=str(ServiceRegistryContract.contract_id),
            contract_callable="get_service_owner",
            contract_address=self.params.service_registry_address,
            service_id=self.params.on_chain_service_id,
            chain_id=self.params.default_chain_id,
        )

        if response.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Couldn't get the service owner for service with id={self.params.on_chain_service_id}. "
                f"Expected response performative {ContractApiMessage.Performative.STATE.value}, "  # type: ignore
                f"received {response.performative.value}."
            )
            return False

        self.service_owner_address = response.state.body.get("service_owner", None)
        return True

    def store_bets(self) -> None:
        """Store the bets to the agent's data dir as JSON."""
        serialized = serialize_bets(self.bets)
        if serialized is None:
            self.context.logger.warning("No bets to store.")
            return

        try:
            with open(self.multi_bets_filepath, WRITE_MODE) as bets_file:
                try:
                    bets_file.write(serialized)
                    return
                except (IOError, OSError):
                    err = f"Error writing to file {self.multi_bets_filepath!r}!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {self.multi_bets_filepath!r} in write mode!"

        self.context.logger.error(err)

    def read_bets(self) -> None:
        """Read the bets from the agent's data dir as JSON."""
        self.bets = []

        if not self.benchmarking_mode.enabled and self.shared_state.first_read:
            # this is a temporary hack to overcome a multi-bets issue
            # if a bet that is in the `TO_PROCESS` queue cannot be selected because of the constraints
            # (e.g., not in opening margin), then everything is blocked because the `FRESH` status will never be updated:
            # https://github.com/valory-xyz/trader/blob/v0.23.1/packages/valory/skills/market_manager_abci/behaviours.py#L200-L202
            self.context.logger.info(
                "Multi-bets storage temporarily disabled on startup!"
            )
            self.shared_state.first_read = False
            return

        _read_path = self.multi_bets_filepath

        if not os.path.isfile(_read_path):
            self.context.logger.warning(
                f"No stored bets file was detected in {_read_path}. Assuming trader is being run for the first time in multi-bets mode."
            )
            _read_path = self.bets_filepath
        elif not os.path.isfile(_read_path):
            self.context.logger.warning(
                f"No stored bets file was detected in {_read_path}. Assuming bets are empty"
            )
            return

        try:
            with open(_read_path, READ_MODE) as bets_file:
                try:
                    self.bets = json.load(bets_file, cls=BetsDecoder)
                    return
                except (JSONDecodeError, TypeError):
                    err = f"Error decoding file {_read_path!r} to a list of bets!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {_read_path!r} in read mode!"

        self.context.logger.error(err)

    def hash_stored_bets(self) -> str:
        """Get the hash of the stored bets' file."""
        return IPFSHashOnly.hash_file(self.multi_bets_filepath)


class UpdateBetsBehaviour(BetsManagerBehaviour, QueryingBehaviour):
    """Behaviour that fetches and updates the bets."""

    matching_round = UpdateBetsRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `UpdateBetsBehaviour`."""
        super().__init__(**kwargs)

    def _requeue_all_bets(self) -> None:
        """Requeue all bets."""
        for bet in self.bets:
            bet.queue_status = bet.queue_status.move_to_fresh()

    def _blacklist_expired_bets(self) -> None:
        """Blacklist bets that are older than the opening margin."""
        for bet in self.bets:
            if self.synced_time >= bet.openingTimestamp - self.params.opening_margin:
                bet.blacklist_forever()

    def setup(self) -> None:
        """Set up the behaviour."""

        # Read the bets from the agent's data dir as JSON, if they exist
        self.read_bets()

        # fetch checkpoint status and if reached requeue all bets
        if self.synchronized_data.is_checkpoint_reached:
            self._requeue_all_bets()

        # blacklist bets that are older than the opening margin
        # if trader ran after a long time
        # helps in resetting the queue number to 0
        if self.bets:
            self._blacklist_expired_bets()

    def get_bet_idx(self, bet_id: str) -> Optional[int]:
        """Get the index of the bet with the given id, if it exists, otherwise `None`."""
        return next((i for i, bet in enumerate(self.bets) if bet.id == bet_id), None)

    def _process_chunk(self, chunk: Optional[List[Dict[str, Any]]]) -> None:
        """Process a chunk of bets."""
        if chunk is None:
            return

        for raw_bet in chunk:
            bet = Bet(**raw_bet, market=self._current_market)
            index = self.get_bet_idx(bet.id)
            if index is None:
                self.bets.append(bet)
            else:
                self.bets[index].update_market_info(bet)

    def _update_bets(
        self,
    ) -> Generator:
        """Fetch the questions from all the prediction markets and update the local copy of the bets."""

        # Fetching bets from the prediction markets
        while True:
            can_proceed = self._prepare_fetching()
            if not can_proceed:
                break

            bets_market_chunk = yield from self._fetch_bets()
            self._process_chunk(bets_market_chunk)

        if self._fetch_status != FetchStatus.SUCCESS:
            # this won't wipe the bets as the `store_bets` of the `BetsManagerBehaviour` takes this into consideration
            self.bets = []

        # truncate the bets, otherwise logs get too big
        bets_str = str(self.bets)[:MAX_LOG_SIZE]
        self.context.logger.info(f"Updated bets: {bets_str}")

    def _bet_freshness_check_and_update(self) -> None:
        """Check the freshness of the bets."""
        all_bets_fresh = all(
            bet.queue_status.is_fresh()
            for bet in self.bets
            if not bet.queue_status.is_expired()
        )

        if all_bets_fresh:
            for bet in self.bets:
                bet.queue_status = bet.queue_status.move_to_process()

        return

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Update the bets list with new bets or update existing ones
            yield from self._update_bets()
            yield from self.get_service_owner()

            # if trader is run after a long time, there is a possibility that
            # all bets are fresh and this should be updated to DAY_0_FRESH
            if self.bets:
                self._bet_freshness_check_and_update()

            # Store the bets to the agent's data dir as JSON
            self.store_bets()

            bets_hash = self.hash_stored_bets() if self.bets else None
            service_owner_address = self.service_owner_address
            payload = UpdateBetsPayload(
                self.context.agent_address, bets_hash, service_owner_address
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()


class MarketManagerRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the MarketManager behaviour."""

    initial_behaviour_cls = UpdateBetsBehaviour
    abci_app_cls = MarketManagerAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {
        UpdateBetsBehaviour,  # type: ignore
    }
