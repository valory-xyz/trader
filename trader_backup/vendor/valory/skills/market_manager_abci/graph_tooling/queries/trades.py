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

"""Trades queries."""

from string import Template


trades = Template(
    """
        {
            fpmmTrades(
                where: {
                    type: Buy,
                    creator: "${creator}",
                    fpmm_: {
                        creationTimestamp_gte: "${creationTimestamp_gte}",
                        creationTimestamp_lt: "${creationTimestamp_lte}"
                    },
                    creationTimestamp_gte: "${creationTimestamp_gte}",
                    creationTimestamp_lte: "${creationTimestamp_lte}"
                    creationTimestamp_gt: "${creationTimestamp_gt}"
                }
                first: ${first}
                orderBy: creationTimestamp
                orderDirection: asc
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
                    openingTimestamp
                    condition {
                        id
                    }
                }
            }
        }
        """
)
