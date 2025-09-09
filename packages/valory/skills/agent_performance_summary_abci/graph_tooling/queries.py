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

"""Subgraph queries."""

GET_TRADER_AGENT_QUERY = """
query GetOlasTraderAgent($id: ID!) {
  traderAgent(id: $id) {
    id
    serviceId
    totalTraded
    totalPayout
    totalFees
  }
}
"""

GET_MECH_SENDER_QUERY = """
query MechSender($id: ID!, $timestamp_gt: Int!) {
  sender(id: $id) {
    totalRequests
    requests(first: 1000, where: { blockTimestamp_gt: $timestamp_gt }) {
      questionTitle
    }
  }
}
"""

GET_OPEN_MARKETS_QUERY = """
query Fpmms($timestamp_gt: Int!) {
  questions(where: { fixedProductMarketMaker_: { blockTimestamp_gt: $timestamp_gt } }) {
    id
    question
  }
}
"""

GET_STAKING_SERVICE_QUERY = """
query StakingService($id: ID!) {
  service(id: $id) {
    id
    olasRewardsEarned
  }
}
"""

GET_TRADER_AGENT_BETS_QUERY = """
query GetOlasTraderAgentBets($id: ID!) {
    traderAgent(id: $id) {
      id
      bets(first: 1000, orderBy: timestamp, orderDirection: desc) {
        outcomeIndex
        fixedProductMarketMaker {
          id
          currentAnswer
        }
      }
    }
  }"""
