#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
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
from typing import Any, Dict, Generator, List, Optional, cast

from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.agent_performance_summary_abci.graph_tooling.queries import (
    GET_MECH_SENDER_QUERY,
    GET_OPEN_MARKETS_QUERY,
    GET_STAKING_SERVICE_QUERY,
    GET_TRADER_AGENT_BETS_QUERY,
    GET_TRADER_AGENT_QUERY,
)
from packages.valory.skills.agent_performance_summary_abci.models import (
    AgentPerformanceSummaryParams,
)


QUERY_BATCH_SIZE = 1000
MAX_LOG_SIZE = 1000

OLAS_TOKEN_ADDRESS = "0xce11e14225575945b8e6dc0d4f2dd4c570f79d9f"
DECIMAL_SCALING_FACTOR = 10**18
USD_PRICE_FIELD = "usd"

QUESTION_DATA_SEPARATOR = "\u241f"


def to_content(query: str, variables: Dict) -> bytes:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {"query": query, "variables": variables}
    encoded_query = json.dumps(finalized_query, sort_keys=True).encode("utf-8")

    return encoded_query


class FetchStatus(Enum):
    """The status of a fetch operation."""

    SUCCESS = auto()
    IN_PROGRESS = auto()
    FAIL = auto()
    NONE = auto()


class APTQueryingBehaviour(BaseBehaviour, ABC):
    """Abstract behaviour that implements subgraph querying functionality."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a querying behaviour."""
        super().__init__(**kwargs)
        self._call_failed: bool = False
        self._fetch_status: FetchStatus = FetchStatus.NONE
        self._current_market: str = ""

    @property
    def params(self) -> AgentPerformanceSummaryParams:
        """Get the params."""
        return cast(AgentPerformanceSummaryParams, self.context.params)

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
        clean_res_str = res_str.replace(
            QUESTION_DATA_SEPARATOR, " "
        )  # Windows terminal can't print this character
        self.context.logger.info(f"Retrieved {res_context}: {clean_res_str}.")
        self._call_failed = False
        subgraph.reset_retries()
        self._fetch_status = FetchStatus.SUCCESS
        return res

    def _fetch_from_subgraph(
        self,
        query: str,
        variables: Dict[str, Any],
        subgraph: ApiSpecs,
        res_context: str,
    ) -> Generator[None, None, Optional[Any]]:
        """Fetch details from a subgraph using the given query and variables."""
        self._fetch_status = FetchStatus.IN_PROGRESS

        res_raw = yield from self.get_http_response(
            content=to_content(query, variables=variables),
            **subgraph.get_spec(),
        )

        res = subgraph.process_response(res_raw)

        result = yield from self._handle_response(
            subgraph,
            res,
            res_context=res_context,
        )

        return result

    def _fetch_mech_sender(
        self, agent_safe_address, timestamp_gt
    ) -> Generator[None, None, Optional[Dict]]:
        """Fetch mech sender details."""
        return (
            yield from self._fetch_from_subgraph(
                query=GET_MECH_SENDER_QUERY,
                variables={"id": agent_safe_address, "timestamp_gt": int(timestamp_gt)},
                subgraph=self.context.olas_mech_subgraph,
                res_context="mech_sender",
            )
        )

    def _fetch_trader_agent(
        self, agent_safe_address
    ) -> Generator[None, None, Optional[Dict]]:
        """Fetch trader agent details."""
        return (
            yield from self._fetch_from_subgraph(
                query=GET_TRADER_AGENT_QUERY,
                variables={"id": agent_safe_address},
                subgraph=self.context.olas_agents_subgraph,
                res_context="trader_agent",
            )
        )

    def _fetch_staking_service(
        self, service_id
    ) -> Generator[None, None, Optional[Dict]]:
        """Fetch trader agent details."""
        return (
            yield from self._fetch_from_subgraph(
                query=GET_STAKING_SERVICE_QUERY,
                variables={"id": service_id},
                subgraph=self.context.gnosis_staking_subgraph,
                res_context="staking_service",
            )
        )

    def _fetch_open_markets(
        self, timestamp_gt
    ) -> Generator[None, None, Optional[List]]:
        """Fetch Open markets."""
        return (
            yield from self._fetch_from_subgraph(
                query=GET_OPEN_MARKETS_QUERY,
                variables={"timestamp_gt": int(timestamp_gt)},
                subgraph=self.context.open_markets_subgraph,
                res_context="open_markets",
            )
        )

    def _fetch_trader_agent_bets(
        self, agent_safe_address
    ) -> Generator[None, None, Optional[Dict]]:
        """Fetch trader agent details."""
        return (
            yield from self._fetch_from_subgraph(
                query=GET_TRADER_AGENT_BETS_QUERY,
                variables={"id": agent_safe_address},
                subgraph=self.context.olas_agents_subgraph,
                res_context="trader_agent_bets",
            )
        )

    def _fetch_olas_in_usd_price(
        self,
    ) -> Generator[None, None, Optional[int]]:
        """Fetch details from a subgraph using the given query and variables."""
        self._fetch_status = FetchStatus.IN_PROGRESS

        res_raw = yield from self.get_http_response(
            method="GET",
            url=self.params.coingecko_olas_in_usd_price_url,
        )

        decoded_response = res_raw.body.decode()

        try:
            response_data = json.loads(decoded_response)
        except json.JSONDecodeError:
            self.context.logger.error(
                f"Could not parse the response body: {decoded_response}"
            )
            return None

        usd_price = response_data.get(OLAS_TOKEN_ADDRESS, {}).get(USD_PRICE_FIELD, None)
        if usd_price is None:
            self.context.logger.error(
                f"Could not get {USD_PRICE_FIELD} price for OLAS from the response: {response_data}"
            )
            return None
        return int(usd_price * DECIMAL_SCALING_FACTOR)  # scale to 18 decimals
