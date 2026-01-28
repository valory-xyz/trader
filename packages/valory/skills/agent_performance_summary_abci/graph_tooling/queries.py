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
    totalTradedSettled
    totalPayout
    totalFees
    totalFeesSettled
  }
}
"""

GET_MECH_SENDER_QUERY = """
query MechSender($id: ID!, $timestamp_gt: Int!, $skip: Int, $first: Int) {
  sender(id: $id) {
    totalMarketplaceRequests
    requests(first: $first, skip: $skip, where: { blockTimestamp_gt: $timestamp_gt }) {
      parsedRequest {
        questionTitle
      }
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
    totalTradedSettled
    totalPayout
    totalFees
    totalFeesSettled
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
  marketParticipants(
    where: { traderAgent_: { id: $id } }
    orderBy: blockTimestamp
    orderDirection: desc
    first: $first
    skip: $skip
  ) {
    id
    totalBets
    totalPayout
    totalTraded
    totalFees
    totalTradedSettled
    totalFeesSettled
    fixedProductMarketMaker {
      id
      question
      outcomes
      currentAnswer
      currentAnswerTimestamp
    }
    bets {
      id
      timestamp
      amount
      feeAmount
      outcomeIndex
    }
  }
}
"""

GET_RESOLVED_MARKETS_QUERY = """
query GetResolvedMarkets($timestamp_gt: BigInt!, $timestamp_lte: BigInt) {
  fixedProductMarketMakers(
    where: {
      currentAnswerTimestamp_gt: $timestamp_gt
      currentAnswerTimestamp_lte: $timestamp_lte
    }
    orderBy: currentAnswerTimestamp
    orderDirection: asc
    first: $first
    skip: $skip
  ) {
    id
    question
    currentAnswer
    currentAnswerTimestamp
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
  sender(id: $sender) {
    requests(
      first: 1000
      skip: $skip
      orderBy: requestId
      orderDirection: asc
    ) {
      id
      requestId
      parsedRequest {
        questionTitle
      }
    }
  }
}
"""

GET_MECH_REQUESTS_BY_TITLES_QUERY = """
query GetMechRequestsByTitles($sender: String!, $questionTitles: [String!]!) {
  sender(id: $sender) {
    requests(
      where: {
        parsedRequest_: { questionTitle_in: $questionTitles }
      }
    ) {
      id
      parsedRequest {
        questionTitle
      }
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

GET_MECH_TOOL_FOR_QUESTION_QUERY = """
query GetMechToolForQuestion($sender: String!, $questionTitle: String!) {
  sender(id: $sender) {
    requests(
      where: { parsedRequest_: { questionTitle: $questionTitle } }
      first: 1
      orderDirection: desc
    ) {
      deliveries {
        model
      }
    }
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
    orderBy: blockTimestamp
    orderDirection: desc
    where: {traderAgent_: {id: $id}}
    first: $first
    skip: $skip
  ) {
    question {
      questionId
      metadata {
        outcomes
        title
      }
      resolution {
        winningIndex
        settledPrice
        timestamp
      }
    }
    bets {
      id
      outcomeIndex
      amount
      shares
      blockTimestamp
      transactionHash
    }
  }
}
"""

GET_MECH_RESPONSE_QUERY = """
query GetMechResponse($sender: String!, $questionTitle: String!) {
  requests(
    where: { sender: $sender, parsedRequest_: { questionTitle: $questionTitle } }
    first: 1
    orderBy: requestId
    orderDirection: desc
  ) {
    parsedRequest {
      questionTitle
    }
    deliveries(first: 1, orderBy: deliveryId, orderDirection: desc) {
      toolResponse
      model
    }
  }
}
"""

GET_SPECIFIC_MARKET_BETS_QUERY = """
query GetSpecificMarketBets($id: ID!, $betId: ID!) {
          traderAgent(id: $id) {
            bets(where: { id: $betId }, orderBy: timestamp, orderDirection: desc) {
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
