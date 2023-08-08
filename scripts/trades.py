#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
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

"""This script queries the OMEN subgraph to obtain the trades of a given address."""

import json
from argparse import ArgumentParser
from string import Template

import requests


trades_query = Template(
    """
    {
      fpmmTrades(
        where: {type: Buy, creator: "${creator}"}
      ) {
        title
        outcomeTokensTraded
        collateralAmount
        feeAmount
        outcomeIndex
        fpmm {
          outcomes
        }
      }
    }
    """
)


def parse_arg() -> str:
    """Parse the creator positional argument."""
    parser = ArgumentParser()
    parser.add_argument("creator")
    args = parser.parse_args()
    return args.creator


def to_content(q: str) -> bytes:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {"query": q}
    encoded_query = json.dumps(finalized_query, sort_keys=True).encode("utf-8")

    return encoded_query


def query_subgraph() -> requests.Response:
    """Query the subgraph."""
    query = trades_query.substitute(creator=creator.lower())
    data = to_content(query)
    url = "https://api.thegraph.com/subgraphs/name/protofire/omen-xdai"
    return requests.post(url, data)


def parse_response() -> str:
    """Parse the trades from the response."""
    serialized_res = res.json()
    trades = serialized_res.get("data", {}).get("fpmmTrades", [])
    return json.dumps(trades, indent=4)


if __name__ == "__main__":
    creator = parse_arg()
    res = query_subgraph()
    parsed = parse_response()
    print(parsed)
