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
from typing import Any, Generator, Optional, Dict, List

from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.transfer_nft_condition.contract import TransferNftCondition
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour, BaseSubscriptionBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload, SubscriptionPayload
from packages.valory.skills.decision_maker_abci.states.order_subscription import SubscriptionRound
from packages.valory.skills.decision_maker_abci.utils.nevermined import generate_id, zero_x_transformer, \
    no_did_prefixed, get_lock_payment_seed, get_price, get_transfer_nft_condition_seed, get_escrow_payment_seed, \
    get_timeouts_and_timelocks, get_reward_address


LOCK_CONDITION_INDEX = 1



class OrderSubscriptionBehaviour(BaseSubscriptionBehaviour):
    """A behaviour in which the agents purchase a subscriptions."""

    matching_round = SubscriptionRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self.order_tx: str = ""
        self.approval_tx: str = ""
        self.balance: int = 0
        self.agreement_id: str = ""

    def _get_condition_ids(self, did_doc: Dict[str, Any]) -> List[str]:
        """Get the condition ids."""
        price = get_price(did_doc)
        receivers = list(price.keys())
        amounts = list(price.values())
        lock_payment_seed = get_lock_payment_seed(
            did_doc,
            self.escrow_payment_condition_address,
            self.token_address,
            amounts,
            receivers,
        )
        transfer_nft_condition_seed = get_transfer_nft_condition_seed(
            did_doc,
            self.transfer_nft_condition_address,
            self.purchase_amount,
            lock_payment_seed,
            self.token_address,
        )
        escrow_payment_seed = get_escrow_payment_seed(
            did_doc,
            amounts,
            receivers,
            self.synchronized_data.safe_contract_address,
            self.escrow_payment_condition_address,
            self.token_address,
            lock_payment_seed,
            transfer_nft_condition_seed,
        )
        condition_ids = [
            lock_payment_seed,
            transfer_nft_condition_seed,
            escrow_payment_seed,
        ]
        return condition_ids


    def _get_purchase_params(self) -> Generator[None, None, Optional[Dict[str, Any]]]:
        """Get purchase params."""
        agreement_id = zero_x_transformer(generate_id())
        did = zero_x_transformer(no_did_prefixed(self.did))
        did_doc = yield from self._resolve_did()
        if did_doc is None:
            # something went wrong
            return None
        condition_ids = self._get_condition_ids(did_doc)
        timeouts, timelocks = get_timeouts_and_timelocks(did_doc)
        reward_address = get_reward_address(did_doc)
        price = get_price(did_doc)
        receivers = list(price.keys())
        amounts = list(price.values())

        return {
            "agreement_id": agreement_id,
            "did": did,
            "condition_ids": condition_ids,
            "consumer": self.synchronized_data.safe_contract_address,
            "index": LOCK_CONDITION_INDEX,
            "timeouts": timeouts,
            "timelocks": timelocks,
            "reward_address": reward_address,
            "receivers": receivers,
            "amounts": amounts,
        }

    def _get_approval_params(self) -> Dict[str, Any]:
        """Get approval params."""
        # TODO: get these from the did doc
        approval_params = {}
        approval_params["token"] = self.token_address
        approval_params["spender"] = self.transfer_nft_condition_address
        approval_params["amount"] = self.price
        return approval_params

    def _prepare_order_tx(
        self,
        contract_address: str,
        agreement_id: str,
        did: str,
        condition_ids: List[str],
        time_locks: List[int],
        time_outs: List[int],
        consumer: str,
        index: int,
        reward_address: str,
        token_address: str,
        amounts: List[int],
        receives: List[str],
    ) -> Generator[None, None, bool]:
        """Prepare a purchase tx."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=contract_address,
            contract_public_id=TransferNftCondition.contract_id,
            contract_callable="build_order_tx",
            data_key="data",
            placeholder="order_tx",
            agreement_id=agreement_id,
            did=did,
            condition_ids=condition_ids,
            time_locks=time_locks,
            time_outs=time_outs,
            consumer=consumer,
            index=index,
            reward_address=reward_address,
            token_address=token_address,
            amounts=amounts,
            receives=receives,
        )
        if not result:
            return False

        self.multisend_batches.append(
            MultisendBatch(
                to=contract_address,
                data=HexBytes(self.order_tx),
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
    def _get_balance(self, token: str, address: str) -> Generator[None, None, bool]:
        """Prepare an approval tx."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=token,
            contract_public_id=ERC20.contract_id,
            contract_callable="check_balance",
            data_key="token",
            placeholder="balance",
            account=address,
        )
        if not result:
            return False


    def _should_purchase(self) -> Generator[None, None, bool]:
        """Check if the subscription should be purchased."""
        result = yield from self._get_balance(self.token_address, self.synchronized_data.safe_contract_address)
        if not result:
            self.context.logger.warning("Failed to get balance")
            return False

        return self.balance <= 0

    def get_payload_content(self) -> Generator[None, None, str]:
        """Get the payload."""
        if not self._should_purchase():
            return SubscriptionRound.NO_TX_PAYLOAD

        approval_params = self._get_approval_params()
        result = yield from self._prepare_approval_tx(**approval_params)
        if not result:
            return SubscriptionRound.ERROR_PAYLOAD

        self.agreement_id = approval_params["agreement_id"]

        purchase_params = yield from self._get_purchase_params()
        if purchase_params is None:
            return SubscriptionRound.ERROR_PAYLOAD

        result = yield from self._prepare_order_tx(**purchase_params)
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
                agreement_id=self.agreement_id,
            )
        yield from self.finish_behaviour(payload)
