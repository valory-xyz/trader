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

"""Polymarket queries."""

from string import Template


questions_polymarket_gamma = Template(
    """
    {
      markets(
        where: "active=true AND closed=false AND outcomes='[\\\"Yes\\\", \\\"No\\\"]'"
        order: "start_date DESC"
        limit: 100
      ) {
        marketMakerAddress
        question
        denominationToken
        submitted_by
        fee
        endDate
        outcomes
        outcomePrices
        liquidity
      }
    }
    """
)


questions_polymarket = Template(
    """
    {
      fixedProductMarketMakers(
        where: {
          outcomeSlotCount: ${slot_count},
        },
        orderBy: creationTimestamp
        orderDirection: desc
        first: 1000
      ){
        id
        collateralToken {
          id
          name
          symbol
        }
        creator
        fee
        outcomeSlotCount
        outcomeTokenAmounts
        outcomeTokenPrices
        scaledLiquidityParameter
        conditions {
          id
          questionId
        }
      }
    }
    """
)

# Missing fields:
#  language_in: ${languages},
#  openingTimestamp
#  outcomes


# Different fields:
#   outcomeTokenMarginalPrices == outcomeTokenPrices  ?
#   scaledLiquidityParameter == scaledLiquidityMeasure ?


trades = Template(
    """
    {
      fpmmTrades (
        where: {
          type: Buy,
          creator: "${creator}",
          fpmm_: {
            creationTimestamp_gt: "${creationTimestamp_gt}",
            answerFinalizedTimestamp_not: null,
            isPendingArbitration: false
          }
        }
        orderBy: fpmm__creationTimestamp
        orderDirection: asc
        first: ${first}
      ){
        fpmm {
          answerFinalizedTimestamp
          collateralToken
          condition {
            id
            outcomeSlotCount
          }
          creator
          creationTimestamp
          currentAnswer
          question {
            id
            data
          }
          templateId
        }
        outcomeIndex
        outcomeTokenMarginalPrice
        outcomeTokensTraded
        transactionHash
      }
    }
    """
)
