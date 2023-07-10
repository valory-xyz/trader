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

"""This module contains the behaviours for the MarketManager skill."""

from typing import Any, Generator, Iterator, List, Set, Type

from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.market_manager_abci.bets import (
    Bet,
    BetStatus,
    serialize_bets,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.payloads import UpdateBetsPayload
from packages.valory.skills.market_manager_abci.rounds import (
    MarketManagerAbciApp,
    UpdateBetsRound,
)


class UpdateBetsBehaviour(QueryingBehaviour):
    """Behaviour that fetches and updates the bets."""

    matching_round = UpdateBetsRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `UpdateBetsBehaviour`."""
        super().__init__(**kwargs)
        # list of bets mapped to prediction markets
        self.bets: List[Bet] = []

    @property
    def bets_ids(self) -> List[str]:
        """Get the ids of the already existing bets."""
        return [bet.id for bet in self.bets]

    def is_valid_bet(self, bet: Bet) -> bool:
        """Return if a bet is valid or not."""
        return (
            bet.blacklist_expiration > self.synced_time
            or bet.status != BetStatus.BLACKLISTED
        )

    @property
    def valid_local_bets(self) -> Iterator[Bet]:
        """Get the valid already existing bets."""
        return filter(self.is_valid_bet, self.synchronized_data.bets)

    def _update_bets(
        self,
    ) -> Generator:
        """Fetch the questions from all the prediction markets and update the local copy of the bets."""
        self.bets = list(self.valid_local_bets)
        existing_ids = self.bets_ids

        while True:
            can_proceed = self._prepare_bets_fetching()
            if not can_proceed:
                break

            bets_market_chunk = yield from self._fetch_bets()
            if bets_market_chunk is not None:
                bets_updates = (
                    Bet(**bet, market=self._current_market)
                    for bet in bets_market_chunk
                    if bet.id not in existing_ids and bet.outcomes is not None
                )
                self.bets.extend(bets_updates)

        if self._fetch_status != FetchStatus.SUCCESS:
            self.bets = []

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._update_bets()
            payload = UpdateBetsPayload(
                self.context.agent_address, serialize_bets(self.bets)
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
