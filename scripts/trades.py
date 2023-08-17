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

from argparse import ArgumentParser
from string import Template
from typing import Any

import requests


headers = {
    "Accept": "application/json, multipart/mixed",
    "Content-Type": "application/json",
}

trades_query = Template(
    """
    {
      fpmmTrades(
        where: {type: Buy, creator: "${creator}"}
      ) {
        id
        title
        collateralToken
        outcomeTokenMarginalPrice
        oldOutcomeTokenMarginalPrice
        type
        creator {
          id
        }
        creationTimestamp
        collateralAmount
        collateralAmountUSD
        feeAmount
        outcomeIndex
        outcomeTokensTraded
        transactionHash
        fpmm {
          id
          outcomes
          title
          answerFinalizedTimestamp
          currentAnswer
          isPendingArbitration
          arbitrationOccurred
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


def to_content(q: str) -> dict[str, Any]:
    """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
    finalized_query = {
        "query": q,
        "variables": None,
        "extensions": {"headers": None},
    }
    return finalized_query


def query_subgraph() -> requests.Response:
    """Query the subgraph."""
    query = trades_query.substitute(creator=creator.lower())
    content_json = to_content(query)
    url = "https://api.thegraph.com/subgraphs/name/protofire/omen-xdai"
    return requests.post(url, headers=headers, json=content_json)


def _wei_to_dai(wei: int) -> str:
    dai = wei / 10**18
    formatted_dai = "{:.4f}".format(dai)
    return f"{formatted_dai} DAI"


def parse_response(res: requests.Response) -> str:  # pylint: disable=too-many-locals
    """Parse the trades from the response."""
    output = "------\n"
    output += "Trades\n"
    output += "------\n"
    res_json = res.json()

    total_collateral_amount = 0
    total_fee_amount = 0
    total_profits = 0
    total_losses = 0
    total_pending_finalization = 0
    for fpmmTrade in res_json["data"]["fpmmTrades"]:
        try:
            collateral_amount = int(fpmmTrade["collateralAmount"])
            total_collateral_amount += collateral_amount
            outcome_index = int(fpmmTrade["outcomeIndex"])
            fee_amount = int(fpmmTrade["feeAmount"])
            total_fee_amount += fee_amount
            outcomes_tokens_traded = int(fpmmTrade["outcomeTokensTraded"])

            fpmm = fpmmTrade["fpmm"]
            answer_finalized_timestamp = fpmm["answerFinalizedTimestamp"]
            is_pending_arbitration = fpmm["isPendingArbitration"]

            output += f'Market:   https://aiomen.eth.limo/#/{fpmm["id"]}\n'
            output += f'Question: {fpmmTrade["title"]}\n'
            output += f"Bought:   {_wei_to_dai(collateral_amount)} for {_wei_to_dai(outcomes_tokens_traded)} {fpmm['outcomes'][outcome_index]!r} tokens\n"
            output += f"Fee:      {_wei_to_dai(fee_amount)}\n"

            if answer_finalized_timestamp is not None and not is_pending_arbitration:
                current_answer = int(fpmm["currentAnswer"], 16)
                if outcome_index == current_answer:
                    profit = outcomes_tokens_traded - collateral_amount
                    output += f"Profit:   {_wei_to_dai(profit)}\n"
                    total_profits += profit
                else:
                    output += f"Loss:     {_wei_to_dai(collateral_amount)}\n"
                    total_losses += collateral_amount
            else:
                output += "Market not yet finalized.\n"
                total_pending_finalization += 1

            output += "\n"
        except TypeError:
            output += "ERROR RETRIEVING TRADE INFORMATION.\n"

    output += "-------\n"
    output += "Summary\n"
    output += "-------\n"

    output += f'Num. trades: {len(res_json["data"]["fpmmTrades"])} ({total_pending_finalization} pending finalization)\n'
    output += f"Invested:    {_wei_to_dai(total_collateral_amount)}\n"
    output += f"Fees:        {_wei_to_dai(total_fee_amount)}\n"
    output += f"Profits:     {_wei_to_dai(total_profits)}\n"
    output += f"Losses:      {_wei_to_dai(total_losses)}\n"

    return output


if __name__ == "__main__":
    creator = parse_arg()
    response = query_subgraph()
    parsed = parse_response(response)
    print(parsed)
