# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2024 Valory AG
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

"""This module contains the behaviour for the decision-making of the skill."""
import json
from typing import Any, Generator


from packages.valory.skills.decision_maker_abci.behaviours.base import (
    BaseSubscriptionBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import ClaimPayload
from packages.valory.skills.decision_maker_abci.states.claim_subscription import ClaimRound
from packages.valory.skills.decision_maker_abci.utils.nevermined import get_creator, get_claim_endpoint

SERVICE_INDEX = -1
ERC1155 = 1155


class ClaimSubscriptionBehaviour(BaseSubscriptionBehaviour):
    """A behaviour in which the agents claim the subscription they purchased."""

    matching_round = ClaimRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self.order_tx: str = ""
        self.approval_tx: str = ""
        self.balance: int = 0

    def _claim_subscription(self) -> Generator[None, None, bool]:
        """Claim the subscription."""
        did_doc = yield from self._resolve_did()
        if did_doc is None:
            return False

        creator = get_creator(did_doc)
        claim_endpoint = get_claim_endpoint(did_doc)
        body = {
            "agreementId": self.synchronized_data.agreement_id,
            "did": self.did,
            "nftHolder": creator,
            "nftReceiver": self.synchronized_data.safe_contract_address,
            "nftAmount": str(self.purchase_amount),
            "nftType": ERC1155,
            "serviceIndex": SERVICE_INDEX,
        }
        res = yield from self.get_http_response(
            'POST',
            claim_endpoint,
            json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'},
        )
        if res.status_code != 200:
            self.context.logger.warning(
                f'Failed to claim subscription: {res.status_code} - {res.body}',
            )
            return False

        return True

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            claim = yield from self._claim_subscription()
            sender = self.context.agent_address
            payload = ClaimPayload(
                sender,
                vote=claim,
            )
        yield from self.finish_behaviour(payload)
