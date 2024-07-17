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

"""This module contains the behaviours for the MarketManager skill."""

import json
import os.path
from abc import ABC
from json import JSONDecodeError
from typing import Any, Generator, Iterator, List, Set, Tuple, Type

from aea.helpers.ipfs.base import IPFSHashOnly

from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetStatus,
    BetsDecoder,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    MAX_LOG_SIZE,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import (
    MarketManagerAbciApp,
    UpdateBetsRound,
)


BETS_FILENAME = "bets.json"
READ_MODE = "r"
WRITE_MODE = "w"


class BetsManagerBehaviour(BaseBehaviour, ABC):
    """Abstract behaviour responsible for bets management, such as storing, hashing, reading."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `BetsManagerBehaviour`."""
        super().__init__(**kwargs)
        self.bets: List[Bet] = []
        self.bets_filepath: str = os.path.join(self.context.data_dir, BETS_FILENAME)

    def store_bets(self) -> None:
        """Store the bets to the agent's data dir as JSON."""
        serialized = serialize_bets(self.bets)
        if serialized is None:
            self.context.logger.warning("No bets to store.")
            return

        try:
            with open(self.bets_filepath, WRITE_MODE) as bets_file:
                try:
                    bets_file.write(serialized)
                    return
                except (IOError, OSError):
                    err = f"Error writing to file {self.bets_filepath!r}!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {self.bets_filepath!r} in write mode!"

        self.context.logger.error(err)

    def read_bets(self) -> None:
        """Read the bets from the agent's data dir as JSON."""
        self.bets = []

        if not os.path.isfile(self.bets_filepath):
            self.context.logger.warning(
                f"No stored bets file was detected in {self.bets_filepath}. Assuming bets are empty."
            )
            return

        try:
            with open(self.bets_filepath, READ_MODE) as bets_file:
                try:
                    self.bets = json.load(bets_file, cls=BetsDecoder)
                    return
                except (JSONDecodeError, TypeError):
                    err = (
                        f"Error decoding file {self.bets_filepath!r} to a list of bets!"
                    )
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {self.bets_filepath!r} in read mode!"

        self.context.logger.error(err)

    def hash_stored_bets(self) -> str:
        """Get the hash of the stored bets' file."""
        return IPFSHashOnly.hash_file(self.bets_filepath)


class UpdateBetsBehaviour(BetsManagerBehaviour, QueryingBehaviour):
    """Behaviour that fetches and updates the bets."""

    matching_round = UpdateBetsRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `UpdateBetsBehaviour`."""
        super().__init__(**kwargs)

    def is_frozen_bet(self, bet: Bet) -> bool:
        """Return if a bet should not be updated."""
        return (
            bet.blacklist_expiration > self.synced_time
            and bet.status == BetStatus.BLACKLISTED
        ) or bet.status == BetStatus.PROCESSED

    @property
    def frozen_local_bets(self) -> Iterator[Bet]:
        """Get the frozen, already existing, bets."""
        return filter(self.is_frozen_bet, self.bets)

    @property
    def frozen_bets_and_ids(self) -> Tuple[List[Bet], Set[str]]:
        """Get the ids of the frozen, already existing, bets."""
        bets = []
        ids = set()
        for bet in self.frozen_local_bets:
            bets.append(bet)
            ids.add(bet.id)
        return bets, ids

    def _update_bets(
        self,
    ) -> Generator:
        """Fetch the questions from all the prediction markets and update the local copy of the bets."""
        self.bets, existing_ids = self.frozen_bets_and_ids

        while True:
            can_proceed = self._prepare_fetching()
            if not can_proceed:
                break

            bets_market_chunk = yield from self._fetch_bets()
            if bets_market_chunk is not None:
                bets_updates = (
                    Bet(**bet, market=self._current_market)
                    for bet in bets_market_chunk
                    if bet.get("id", "") not in existing_ids
                )
                self.bets.extend(bets_updates)

        if self._fetch_status != FetchStatus.SUCCESS:
            self.bets = []

        # truncate the bets, otherwise logs get too big
        bets_str = str(self.bets)[:MAX_LOG_SIZE]
        self.context.logger.info(f"Updated bets: {bets_str}")

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            self.read_bets()
            yield from self._update_bets()
            self.store_bets()
            bets_hash = self.hash_stored_bets() if self.bets else None
            payload = UpdateBetsPayload(self.context.agent_address, bets_hash)

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
