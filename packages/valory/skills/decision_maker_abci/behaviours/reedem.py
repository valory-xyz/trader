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

"""This module contains the redeeming state of the decision-making abci app."""

import json
from typing import Generator, Optional, Any, Dict, List

from packages.valory.contracts.realtio_proxy.contract import RealtioProxyContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import DecisionMakerBaseBehaviour
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload

TRADES_QUERY = Template(
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


class RedeemBehaviour(DecisionMakerBaseBehaviour):
    """Redeem the winnings."""

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_submitter = self.matching_round.auto_round_id()
            mech_tx_hex = yield from self.get_payload()
            payload = MultisigTxPayload(agent, tx_submitter, mech_tx_hex)

        yield from self.finish_behaviour(payload)

    def get_payload(self) -> Generator[None, None, Optional[str]]:
        """
        Prepare the safe tx to reedem the positions of the trader.

        Steps:
            1. Get all trades of the trader.
            2. For each trade, check if the trader has a winning position.
            3. If so, prepare a multisend transaction like this:
            TXS:
                1. resolveCondition (optional)
                Check if the condition needs to be resolved. If so, add the tx to the multisend.

                2. claimWinnings
                Prepare a claim winnings tx for each winning position. Add it to the multisend.

                3. redeemPosition
                Prepare a redeem position tx for each position. Add it to the multisend.
        """
        response = yield from self._get_subgraph_result(
            query=TRADES_QUERY.substitute(
                creator=self.synchronized_data.safe_contract_address,
            )
        )
        for fpmmTrade in response["data"]["fpmmTrades"]:
            correct_answer = int(fpmmTrade["outcomeIndex"])
            fpmm = fpmmTrade["fpmm"]
            answer_finalized_timestamp, is_pending_arbitration = fpmm["answerFinalizedTimestamp"], fpmm["isPendingArbitration"]
            if answer_finalized_timestamp is not None and not is_pending_arbitration:
                our_answer = int(fpmm["currentAnswer"], 16)
                # in case of a winning position
                if correct_answer == our_answer:
                    # TODO: check if we have alredy claimed from this market
                    ...

        return None


    def _resolve_condition(
        self,
        question_id: bytes,
        history_hash: List[bytes],
        addresses: List[str],
        bonds: List[int],
        claim_amounts: List[bytes],
    ) -> Generator[None, None, Optional[str]]:
        """Prepare the safe tx to resolve the condition."""
        response = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,
            contract_address=self.context.realitio_proxy,
            contract_id=str(RealtioProxyContract.contract_id),
            contract_callable=get_name(RealtioProxyContract.build_resolve_tx),
            question_id=question_id,
            history_hash=history_hash,
            addresses=addresses,
            bonds=bonds,
            claim_amounts=claim_amounts,
        )
        return response.body["data"]

    def _claim_winnings(self, ) -> Generator[None, None, Optional[str]]:
        """Prepare the safe tx to claim the winnings."""
        ...

    def _redeem_position(self, ) -> Generator[None, None, Optional[str]]:
        """Prepare the safe tx to redeem the position."""
        ...

    @staticmethod
    def to_content(q: str) -> Dict[str, Any]:
        """Convert the given query string to payload content, i.e., add it under a `queries` key and convert it to bytes."""
        finalized_query = {
            "query": q,
            "variables": None,
            "extensions": {"headers": None},
        }
        return finalized_query


    def _get_subgraph_result(
        self,
        query: str,
    ) -> Generator[None, None, Optional[Dict[str, Any]]]:
        """Get question ids."""
        response = yield from self.get_http_response(
            content=self.to_content(query).encode(),
            url=self.context.params.subgraph_url,
            method="POST",
        )
        return json.loads(response.body.decode())
