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
import time
from abc import ABC
from json import JSONDecodeError
from typing import Any, Dict, Generator, List, Optional, Set, Type, cast

from aea.helpers.ipfs.base import IPFSHashOnly

from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetsDecoder,
    BinaryOutcome,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    MAX_LOG_SIZE,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    get_bet_id_to_balance,
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

    @property
    def shared_state(self) -> SharedState:
        """Get the shared state."""
        return cast(SharedState, self.context.state)

    @property
    def benchmarking_mode(self) -> BenchmarkingMode:
        """Return the benchmarking mode configurations."""
        return cast(BenchmarkingMode, self.context.benchmarking_mode)

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
        read_path = self.multi_bets_filepath

        if not os.path.isfile(read_path):
            self.context.logger.warning(
                f"No stored bets file was detected in {read_path}. "
                "Assuming trader is being run for the first time in multi-bets mode."
            )
            read_path = self.bets_filepath

        if not os.path.isfile(read_path):
            self.context.logger.warning(
                f"No stored bets file was detected in {read_path}. Assuming bets are empty."
            )
            return

        try:
            with open(read_path, READ_MODE) as bets_file:
                try:
                    self.bets = json.load(bets_file, cls=BetsDecoder)
                    return
                except (JSONDecodeError, TypeError):
                    err = f"Error decoding file {read_path!r} to a list of bets!"
        except (FileNotFoundError, PermissionError, OSError):
            err = f"Error opening file {read_path!r} in read mode!"

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

    def _requeue_bets_for_selling(self) -> None:
        """Requeue sell bets."""
        for bet in self.bets:
            time_since_last_sell_check = (
                self.synced_time - bet.last_processed_sell_check
            )
            if (
                bet.is_ready_to_sell(self.synced_time, self.params.opening_margin)
                and not bet.queue_status.is_expired()
                and bet.invested_amount > 0
                and (
                    not bet.last_processed_sell_check
                    or time_since_last_sell_check > self.params.sell_check_interval
                )
            ):
                self.context.logger.info(
                    f"Requeueing bet {bet.id!r} for selling, with invested amount: {bet.invested_amount!r}."
                )
                bet.queue_status = bet.queue_status.move_to_fresh()

    def _blacklist_expired_bets(self) -> None:
        """Blacklist bets that are older than the opening margin."""
        for bet in self.bets:
            if self.synced_time >= bet.openingTimestamp - self.params.opening_margin:
                bet.blacklist_forever()

    def review_bets_for_selling(self) -> bool:
        """Review bets for selling."""
        return self.synchronized_data.review_bets_for_selling

    def update_bets_investments(self) -> Generator:
        """Update the investments of the bets."""
        self.context.logger.info("Updating bets investments.")
        balances = yield from self.get_active_bets()
        self.context.logger.debug(f"Balances: {balances=}")

        for bet in self.bets:
            if bet.queue_status.is_expired():
                self.context.logger.debug(f"Bet {bet.id} is expired")
                continue

            bet.reset_investments()

            for outcome, value in balances[bet.id].items():
                outcome_is_no = BinaryOutcome.from_string(outcome) is BinaryOutcome.NO
                outcome_int = 0 if outcome_is_no else 1
                self.context.logger.debug(f"Outcome {outcome_int} value {value}")
                bet.append_investment_amount(outcome_int, value)
                self.context.logger.debug(
                    f"Bet {bet.id} investments: {bet.investments=}"
                )

    def get_active_bets(self) -> Generator[None, None, Dict[str, Dict[str, int]]]:
        """Get the active bets."""
        trades = yield from self.fetch_trades(
            self.synchronized_data.safe_contract_address.lower(), 0.0, time.time()
        )
        if trades is None:
            return {}

        user_positions = yield from self.fetch_user_positions(
            self.synchronized_data.safe_contract_address.lower()
        )
        if user_positions is None:
            return {}

        balances = get_bet_id_to_balance(trades, user_positions)
        return balances

    def setup(self) -> None:
        """Set up the behaviour."""

        # Read the bets from the agent's data dir as JSON, if they exist
        self.read_bets()

        self.context.logger.info(
            f"Check point is reached: {self.synchronized_data.is_checkpoint_reached=}"
        )

        # fetch checkpoint status and if reached requeue all bets
        if (
            self.synchronized_data.is_checkpoint_reached
            and self.params.use_multi_bets_mode
        ):
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
        # single-bets mode case - mark any market with a `FRESH` status as processable
        if not self.params.use_multi_bets_mode:
            for bet in self.bets:
                if bet.queue_status.is_fresh():
                    bet.queue_status = bet.queue_status.move_to_process()
            return

        # muti-bets mode case - mark markets as processable only if all the unexpired ones have a `FRESH` status
        # this will happen if the agent just started or the checkpoint has just been reached
        all_bets_fresh = all(
            bet.queue_status.is_fresh()
            for bet in self.bets
            if not bet.queue_status.is_expired()
        )

        if all_bets_fresh:
            for bet in self.bets:
                bet.queue_status = bet.queue_status.move_to_process()

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Update the bets list with new bets or update existing ones
            yield from self._update_bets()
            yield from self.update_bets_investments()

            if self.review_bets_for_selling():
                self._requeue_bets_for_selling()

            # if trader is run after a long time, there is a possibility that
            # all bets are fresh and this should be updated to DAY_0_FRESH
            if self.bets:
                self._bet_freshness_check_and_update()

            # Store the bets to the agent's data dir as JSON
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
