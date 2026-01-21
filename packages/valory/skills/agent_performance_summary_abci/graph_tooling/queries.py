# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025-2026 Valory AG
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
query MechSender($id: ID!, $timestamp_gt: Int!, $skip: Int, $first: Int) {
  sender(id: $id) {
    totalRequests
    requests(first: $first, skip: $skip, where: { blockTimestamp_gt: $timestamp_gt }) {
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

GET_TRADER_AGENT_DETAILS_QUERY = """
query GetTraderAgentDetails($id: ID!) {
  traderAgent(id: $id) {
    id
    blockTimestamp
    lastActive
  }
}
"""

GET_TRADER_AGENT_PERFORMANCE_QUERY = """
query GetTraderAgentPerformance($id: ID!, $first: Int, $skip: Int) {
  traderAgent(id: $id) {
    id
    totalTraded
    totalPayout
    totalFees
    totalBets
    bets(first: $first, skip: $skip, orderBy: timestamp, orderDirection: desc) {
      amount
      outcomeIndex
      fixedProductMarketMaker {
        currentAnswer
      }
    }
  }
}
"""

GET_PREDICTION_HISTORY_QUERY = """
query GetPredictionHistory($id: ID!, $first: Int!, $skip: Int!) {
  traderAgent(id: $id) {
    totalBets
    totalTraded
    totalPayout
    totalFees
    bets(first: $first, skip: $skip, orderBy: timestamp, orderDirection: desc) {
      id
      timestamp
      amount
      feeAmount
      outcomeIndex
      fixedProductMarketMaker {
        id
        question
        outcomes
        currentAnswer
        currentAnswerTimestamp
        participants(where: { traderAgent: $id }) {
          totalBets
          totalTraded
          totalPayout
          totalFees
        }
      }
    }
  }
}
"""

GET_FPMM_PAYOUTS_QUERY = """
query GetFPMMPayouts($fpmmIds: [ID!]!) {
  fixedProductMarketMakers(where: { id_in: $fpmmIds }, first: 1000) {
    id
    payouts
    resolutionTimestamp
  }
}
"""

GET_PENDING_BETS_QUERY = """
query GetPendingBets($id: ID!) {
  traderAgent(id: $id) {
    bets(where: { fixedProductMarketMaker_: { currentAnswer: null } }) {
      amount
      feeAmount
    }
  }
}
"""

GET_DAILY_PROFIT_STATISTICS_QUERY = """
query GetDailyProfitStatistics($agentId: ID!, $startTimestamp: BigInt!, $first: Int, $skip: Int) {
  traderAgent(id: $agentId) {
    dailyProfitStatistics(
      where: { 
        date_gte: $startTimestamp,
      }
      orderBy: date
      orderDirection: asc
      first: $first
      skip: $skip
    ) {
      id
      date
      totalBets
      totalTraded
      totalFees
      totalPayout
      dailyProfit
      profitParticipants {
        id
        question
      }
    }
  }
}
"""

GET_ALL_MECH_REQUESTS_QUERY = """
query GetAllMechRequests($sender: String!, $skip: Int!) {
  requests(
    where: { sender: $sender }
    first: 1000
    skip: $skip
    orderBy: requestId
    orderDirection: asc
  ) {
    id
    requestId
    questionTitle
  }
}
"""

GET_MECH_REQUESTS_BY_TITLES_QUERY = """
query GetMechRequestsByTitles($sender: String!, $questionTitles: [String!]!) {
  sender(id: $sender) {
    requests(
      where: { 
        questionTitle_in: $questionTitles
      }
    ) {
      id
      questionTitle
    }
  }
}
"""

# Polymarket-specific queries
GET_POLYMARKET_TRADER_AGENT_DETAILS_QUERY = """
query GetPolymarketTraderAgentDetails($id: ID!) {
  traderAgent(id: $id) {
    id
    blockTimestamp
    lastActive
  }
}
"""

GET_POLYMARKET_TRADER_AGENT_PERFORMANCE_QUERY = """
query GetPolymarketTraderAgentPerformance($id: ID!) {
  traderAgent(id: $id) {
    totalBets
    totalPayout
    totalTraded
    totalTradedSettled
  }
}
"""

GET_POLYMARKET_PREDICTION_HISTORY_QUERY = """
query GetPolymarketPredictionHistory($id: ID!, $first: Int!, $skip: Int!) {
  marketParticipants(
    where: {traderAgent: $id}
    first: $first
    skip: $skip
    orderBy: blockTimestamp
    orderDirection: desc
  ) {
    traderAgent {
      bets {
        amount
        outcomeIndex
        shares
        question {
          questionId
          metadata {
            outcomes
            rawAncillaryData
            title
          }
          resolution {
            settledPrice
            winningIndex
          }
        }
      }
    }
  }
}
"""
