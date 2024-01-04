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
from typing import Any, Generator, Optional, Dict

from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.transfer_nft_condition.contract import TransferNftCondition
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload, SubscriptionPayload
from packages.valory.skills.decision_maker_abci.states.purchase_subscription import SubscriptionRound


class PurchaseSubscriptionBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents purchase a subscriptions."""

    matching_round = SubscriptionRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self.purchase_tx: str = ""
        self.approval_tx: str = ""

    def _get_purchase_params(self) -> Generator[None, None, Optional[Dict[str, Any]]]:
        """Get purchase params."""
        # this data was taken from the nervermined api, by analyzing the following subscription
        # https://gnosis.nevermined.app/en/subscription/did:nv:416e35cb209ecbfbf23e1192557b06e94c5d9a9afb025cce2e9baff23e907195
        # more specifically the subscription creation tx: https://gnosisscan.io/tx/0x4cac38e6e28992ca8c20c92ffb8d0564dc7d1c3ca9f6b08db0a04b5f5fb23631
        # and the purchase tx: https://gnosisscan.io/tx/0x086e693fac1c3d084dffdc899adaca773ad986e6e2bff5700549e1ae8364731e (this is what the service should do)

        purchase_params = {}

        mech = self.params.mech_agent_address
        params = self.params.mech_to_subscription_params[mech]

        base_url = params["base_url"]
        did = params["did"]
        purchase_params["did"] = did
        purchase_params["nft_receiver"] = self.synchronized_data.safe_contract_address
        purchase_params["contract_address"] = params["transfer_nft_condition_address"]

        did_url = f"{base_url}/{did}"
        response = yield from self.get_http_response(
            method="GET",
            url=did_url,
            headers={"accept": "application/json"},
        )
        if response.status_code != 200:
            self.context.logger.error(
                f"Could not retrieve data from did url {did_url}. "
                f"Received status code {response.status_code}."
            )
            return None

        try:
            # TODO: would be good to get a sanity check here, whether its possible to get this information from somewhere else
            data = json.loads(response.body)["data"]
            service = data["service"]
            for s in service:
                if s["type"] == "nft_sales":
                    template = s["attributes"]["serviceAgreementTemplate"]
                    conditions = template["conditions"]
                    for condition in conditions:
                        if condition["type"] == "transferNFT":
                            transfer_params = condition["parameters"]
                            for param in transfer_params:
                                if param["name"] == "_nftHolder":
                                    purchase_params["nft_holder"] = param["value"]
                                elif param["name"] == "_numberNfts":
                                    purchase_params["nft_amount"] = int(param["value"])
                                elif param["name"] == "_contractAddress":
                                    purchase_params[
                                        "nft_contract_address"
                                    ] = param["value"]

        except (ValueError, TypeError) as e:
            self.context.logger.error(
                f"Could not parse response from nervermined api, "
                f"the following error was encountered {type(e).__name__}: {e}"
            )
            return None

        # TODO
        # purchase_params["agreement_id"] = "agreement_id"
        # purchase_params["lock_payment_condition"] = "lock_payment_condition"
        # purchase_params["transfer"] = "transfer", this might be always False from the txs I analyzed
        # purchase_params["expiration_block"], this might be always 0 from the txs I analyzed

        return purchase_params

    def _get_approval_params(self) -> Dict[str, Any]:
        """Get approval params."""
        approval_params = {}
        mech = self.params.mech_agent_address
        params = self.params.mech_to_subscription_params[mech]
        approval_params["token"] = params["token"]
        approval_params["spender"] = params["transfer_nft_condition_address"]
        approval_params["amount"] = params["nft_price"]
        return approval_params

    def _prepare_purchase_tx(
        self,
        contract_address: str,
        agreement_id: str,
        did: str,
        nft_holder: str,
        nft_receiver: str,
        nft_amount: int,
        lock_payment_condition: str,
        nft_contract_address: str,
        transfer: bool,
        expiration_block: int,
    ) -> Generator[None, None, bool]:
        """Prepare a purchase tx."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=contract_address,
            contract_public_id=TransferNftCondition.contract_id,
            contract_callable="build_fulfill_for_delegate_tx",
            data_key="data",
            placeholder="approval_tx",
            agreement_id=agreement_id,
            did=did,
            nft_holder=nft_holder,
            nft_receiver=nft_receiver,
            nft_amount=nft_amount,
            lock_payment_condition=lock_payment_condition,
            nft_contract_address=nft_contract_address,
            transfer=transfer,
            expiration_block=expiration_block,
        )
        if not result:
            return False

        self.multisend_batches.append(
            MultisendBatch(
                to=contract_address,
                data=HexBytes(self.purchase_tx),
            )
        )

    def _prepare_approval_tx(self, token: str, spender: str, amount: int) -> Generator[None, None, bool]:
        """Prepare an approval tx."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=token,
            contract_public_id=ERC20.contract_id,
            contract_callable="build_approval_tx",
            data_key="data",
            placeholder="approval_tx",
            amount=amount,
            spender=spender,
        )
        if not result:
            return False

        self.multisend_batches.append(
            MultisendBatch(
                to=token,
                data=HexBytes(self.approval_tx),
            )
        )

    def _should_purchase(self) -> Generator[None, None, bool]:
        """Check if the subscription should be purchased."""
        # TODO: check if the subscription should be purchased
        # possible things to check:
        # is the subscription already purchased?
        # does the agent have enough funds?
        # has the subscription run out?

    def get_payload_content(self) -> Generator[None, None, str]:
        """Get the payload."""
        if not self._should_purchase():
            return SubscriptionRound.NO_TX_PAYLOAD

        approval_params = self._get_approval_params()
        result = yield from self._prepare_approval_tx(**approval_params)
        if not result:
            return SubscriptionRound.ERROR_PAYLOAD

        purchase_params = yield from self._get_purchase_params()
        if purchase_params is None:
            return SubscriptionRound.ERROR_PAYLOAD

        result = yield from self._prepare_purchase_tx(**purchase_params)
        if not result:
            return SubscriptionRound.ERROR_PAYLOAD

        for build_step in (
            self._build_multisend_data,
            self._build_multisend_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(build_step)

        return self.safe_tx_hash

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload_data = yield from self.get_payload_content()
            sender = self.context.agent_address
            payload = SubscriptionPayload(
                sender,
                tx_submitter=SubscriptionRound.auto_round_id(),
                tx_hash=payload_data,
            )
        yield from self.finish_behaviour(payload)
