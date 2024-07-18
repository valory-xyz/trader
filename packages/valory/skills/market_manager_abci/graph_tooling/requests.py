#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2021-2024 Valory AG
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

"""Tooling to perform subgraph requests from a behaviour."""

import json
from abc import ABC
from enum import Enum, auto
from typing import Any, Dict, Generator, Iterator, List, Optional, Tuple, cast

from web3 import Web3

from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.market_manager_abci.graph_tooling.queries.conditional_tokens import (
    user_positions as user_positions_query,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.network import (
    block_number,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.omen import (
    questions,
    trades,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.realitio import (
    answers as answers_query,
)
from packages.valory.skills.market_manager_abci.graph_tooling.queries.trades import (
    trades as trades_query,
)
from packages.valory.skills.market_manager_abci.models import (
    MarketManagerParams,
    SharedState,
)
from packages.valory.skills.market_manager_abci.rounds import SynchronizedData


QUERY_BATCH_SIZE = 1000
MAX_LOG_SIZE = 1000


def to_content(query: str) -> bytes:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {"query": query}
    encoded_query = json.dumps(finalized_query, sort_keys=True).encode("utf-8")

    return encoded_query


def to_graphql_list(li: list) -> str:
    """Convert the given list to a string representing a list for a GraphQL query."""
    return repr(li).replace("'", '"')


class FetchStatus(Enum):
    """The status of a fetch operation."""

    SUCCESS = auto()
    IN_PROGRESS = auto()
    FAIL = auto()
    NONE = auto()


class QueryingBehaviour(BaseBehaviour, ABC):
    """Abstract behaviour that implements subgraph querying functionality."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a querying behaviour."""
        super().__init__(**kwargs)
        self._call_failed: bool = False
        self._fetch_status: FetchStatus = FetchStatus.NONE
        self._creators_iterator: Iterator[
            Tuple[str, List[str]]
        ] = self.params.creators_iterator
        self._current_market: str = ""
        self._current_creators: List[str] = []

    @property
    def params(self) -> MarketManagerParams:
        """Get the params."""
        return cast(MarketManagerParams, self.context.params)

    @property
    def shared_state(self) -> SharedState:
        """Get the shared state."""
        return cast(SharedState, self.context.state)

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return cast(SynchronizedData, super().synchronized_data)

    @property
    def synced_time(self) -> int:
        """Get the synchronized time among agents."""
        synced_time = self.shared_state.round_sequence.last_round_transition_timestamp
        return int(synced_time.timestamp())

    @property
    def current_subgraph(self) -> ApiSpecs:
        """Get a subgraph by prediction market's name."""
        return getattr(self.context, self._current_market)

    def _prepare_fetching(self) -> bool:
        """Prepare for fetching a bet."""
        if self._fetch_status in (FetchStatus.SUCCESS, FetchStatus.NONE):
            res = next(self._creators_iterator, None)
            if res is None:
                return False
            self._current_market, self._current_creators = res

        if self._fetch_status == FetchStatus.FAIL:
            return False

        self._fetch_status = FetchStatus.IN_PROGRESS
        return True

    def _handle_response(
        self,
        subgraph: ApiSpecs,
        res: Optional[Dict],
        res_context: str,
        sleep_on_fail: bool = True,
    ) -> Generator[None, None, Optional[Any]]:
        """Handle a response from a subgraph.

        :param subgraph: the subgraph to handle the response for.
        :param res: the response to handle.
        :param res_context: the context of the current response.
        :param sleep_on_fail: whether we want to sleep if we fail to get the response's result.
        :return: the response's result, using the given keys. `None` if response is `None` (has failed).
        :yield: None
        """
        if res is None:
            self.context.logger.error(
                f"Could not get {res_context} from {subgraph.api_id}"
            )
            self._call_failed = True
            subgraph.increment_retries()

            if subgraph.is_retries_exceeded():
                self._fetch_status = FetchStatus.FAIL

            if sleep_on_fail:
                sleep_time = subgraph.retries_info.suggested_sleep_time
                yield from self.sleep(sleep_time)
            return None

        # truncate the response, otherwise logs get too big
        res_str = str(res)[:MAX_LOG_SIZE]
        self.context.logger.info(f"Retrieved {res_context}: {res_str}.")
        self._call_failed = False
        subgraph.reset_retries()
        self._fetch_status = FetchStatus.SUCCESS
        return res

    def _fetch_bets(self) -> Generator[None, None, Optional[list]]:
        """Fetch questions from the current subgraph, for the current creators."""
        self._fetch_status = FetchStatus.IN_PROGRESS

        query = questions.substitute(
            creators=to_graphql_list(self._current_creators),
            slot_count=self.params.slot_count,
            opening_threshold=self.synced_time + self.params.opening_margin,
            languages=to_graphql_list(self.params.languages),
        )

        res_raw = yield from self.get_http_response(
            content=to_content(query),
            **self.current_subgraph.get_spec(),
        )
        res = self.current_subgraph.process_response(res_raw)

        bets = yield from self._handle_response(
            self.current_subgraph,
            res,
            res_context="questions",
        )

        return bets

    def _fetch_redeem_info(self) -> Generator[None, None, Optional[list]]:
        """Fetch redeeming information from the current subgraph."""
        self._fetch_status = FetchStatus.IN_PROGRESS

        current_subgraph = self.context.trades_subgraph
        safe = self.synchronized_data.safe_contract_address
        creation_timestamp_gt = (
            0  # used to allow for batching based on creation timestamp
        )
        all_trades: List[Dict[str, Any]] = []
        # fetch trades in batches of `QUERY_BATCH_SIZE`
        while True:
            query = trades.substitute(
                creator=safe.lower(),
                first=QUERY_BATCH_SIZE,
                creationTimestamp_gt=creation_timestamp_gt,
            )

            res_raw = yield from self.get_http_response(
                content=to_content(query),
                **current_subgraph.get_spec(),
            )
            res = current_subgraph.process_response(res_raw)
            trades_chunk = yield from self._handle_response(
                current_subgraph,
                res,
                res_context="trades",
            )
            if res is None:
                # something went wrong
                self.context.logger.error("Failed to process all trades.")
                return all_trades

            trades_chunk = cast(List[Dict[str, Any]], trades_chunk)
            if len(trades_chunk) == 0:
                # no more trades to fetch
                return all_trades

            # this is the last trade's creation timestamp
            # they are sorted by creation timestamp in ascending order
            # so we can use this to fetch the next batch
            creation_timestamp_gt = trades_chunk[-1]["fpmm"]["creationTimestamp"]
            all_trades.extend(trades_chunk)

    def _fetch_block_number(
        self, timestamp: int
    ) -> Generator[None, None, Dict[str, str]]:
        """Get a block number by its timestamp."""
        self._fetch_status = FetchStatus.IN_PROGRESS

        margin = self.params.average_block_time * self.params.abt_error_mult
        query = block_number.substitute(
            timestamp_from=timestamp, timestamp_to=timestamp + margin
        )

        current_subgraph = self.context.network_subgraph
        res_raw = yield from self.get_http_response(
            content=to_content(query),
            **current_subgraph.get_spec(),
        )
        res = current_subgraph.process_response(res_raw)

        block = yield from self._handle_response(
            current_subgraph,
            res,
            res_context="block number",
        )

        return {} if block is None else block

    def fetch_claim_params(
        self, question_id: str
    ) -> Generator[None, None, Optional[List[Dict[str, Any]]]]:
        """Fetch claim parameters from the subgraph."""
        self._fetch_status = FetchStatus.IN_PROGRESS
        current_subgraph = self.context.realitio_subgraph
        query = answers_query.substitute(
            question_id=question_id,
        )
        res_raw = yield from self.get_http_response(
            content=to_content(query),
            **current_subgraph.get_spec(),
        )
        res = current_subgraph.process_response(res_raw)
        raw_answers = yield from self._handle_response(
            current_subgraph,
            res,
            res_context="answers",
        )
        if raw_answers is None:
            # we failed to get the answers
            self.context.logger.error(
                f"Failing to get answers for question {question_id} from {current_subgraph.api_id}"
            )
            return None
        answers = [
            {
                "args": {
                    "answer": bytes.fromhex(answer["answer"][2:]),
                    "question_id": bytes.fromhex(answer["question"]["questionId"][2:]),
                    "history_hash": bytes.fromhex(
                        answer["question"]["historyHash"][2:]
                    ),
                    "user": Web3.to_checksum_address(answer["question"]["user"]),
                    "bond": int(answer["bondAggregate"]),
                    "timestamp": int(answer["timestamp"]),
                    "is_commitment": False,
                }
            }
            for answer in raw_answers
        ]
        return answers

    def fetch_trades(
        self,
        creator: str,
        from_timestamp: float,
        to_timestamp: float,
    ) -> Generator[None, None, Optional[List[Dict[str, Any]]]]:
        """Fetch trades from the subgraph."""
        self._fetch_status = FetchStatus.IN_PROGRESS
        current_subgraph = self.context.trades_subgraph

        all_trades: List[Dict[str, Any]] = []
        creation_timestamp_gt = (
            0  # used to allow for batching based on creation timestamp
        )
        # fetch trades in batches of `QUERY_BATCH_SIZE`
        while True:
            query = trades_query.substitute(
                creator=creator.lower(),
                creationTimestamp_lte=int(to_timestamp),
                creationTimestamp_gte=int(from_timestamp),
                first=QUERY_BATCH_SIZE,
                creationTimestamp_gt=creation_timestamp_gt,
            )

            res_raw = yield from self.get_http_response(
                content=to_content(query),
                **current_subgraph.get_spec(),
            )
            res = current_subgraph.process_response(res_raw)
            trades_chunk = yield from self._handle_response(
                current_subgraph,
                res,
                res_context="trades",
            )
            if res is None:
                # something went wrong
                self.context.logger.error("Failed to process all trades.")
                return all_trades

            trades_chunk = cast(List[Dict[str, Any]], trades_chunk)
            if len(trades_chunk) == 0:
                # no more trades to fetch
                return all_trades

            # this is the last trade's creation timestamp
            # they are sorted by creation timestamp in ascending order
            # so we can use this to fetch the next batch
            creation_timestamp_gt = trades_chunk[-1]["creationTimestamp"]
            all_trades.extend(trades_chunk)

    def fetch_user_positions(
        self, user: str
    ) -> Generator[None, None, Optional[List[Dict[str, Any]]]]:
        """Fetch positions for a user from the subgraph."""
        self._fetch_status = FetchStatus.IN_PROGRESS
        current_subgraph = self.context.conditional_tokens_subgraph

        user_positions_id_gt = (
            0  # used to allow for batching based on user positions id
        )
        all_positions: List[Dict[str, Any]] = []
        while True:
            query = user_positions_query.substitute(
                id=user.lower(),
                first=QUERY_BATCH_SIZE,
                userPositions_id_gt=user_positions_id_gt,
            )
            res_raw = yield from self.get_http_response(
                content=to_content(query),
                **current_subgraph.get_spec(),
            )
            res = current_subgraph.process_response(res_raw)

            positions = yield from self._handle_response(
                current_subgraph,
                res,
                res_context="positions",
            )
            if res is None:
                # something went wrong
                self.context.logger.error("Failed to process all positions.")
                return all_positions

            positions = cast(List[Dict[str, Any]], positions)
            if len(positions) == 0:
                # no more positions to fetch
                return all_positions

            all_positions.extend(positions)
            user_positions_id_gt = positions[-1]["id"]

    def clean_up(self) -> None:
        """Clean up the resources."""
        markets_subgraphs = tuple(market for market, _ in self.params.creators_iterator)
        other_subgraphs = (
            "conditional_tokens_subgraph",
            "network_subgraph",
            "realitio_subgraph",
            "trades_subgraph",
        )
        for subgraph in markets_subgraphs + other_subgraphs:
            subgraph_specs = getattr(self.context, subgraph)
            subgraph_specs.reset_retries()
