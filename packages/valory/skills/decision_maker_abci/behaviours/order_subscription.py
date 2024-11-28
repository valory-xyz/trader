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
from typing import Any, Dict, Generator, List, Optional, cast

from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.transfer_nft_condition.contract import (
    TransferNftCondition,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    BaseSubscriptionBehaviour,
    WXDAI,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import SubscriptionPayload
from packages.valory.skills.decision_maker_abci.states.order_subscription import (
    SubscriptionRound,
)
from packages.valory.skills.decision_maker_abci.utils.nevermined import (
    generate_id,
    get_agreement_id,
    get_escrow_payment_seed,
    get_lock_payment_seed,
    get_price,
    get_timeouts_and_timelocks,
    get_transfer_nft_condition_seed,
    no_did_prefixed,
    zero_x_transformer,
)


LOCK_CONDITION_INDEX = 0


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
        self.credits_per_req: int = 0
        self.pending_reqs: int = 0

    def _get_condition_ids(
        self, agreement_id_seed: str, did_doc: Dict[str, Any]
    ) -> List[str]:
        """Get the condition ids."""
        self.agreement_id = get_agreement_id(
            agreement_id_seed, self.synchronized_data.safe_contract_address
        )
        price = get_price(did_doc)
        receivers = list(price.keys())
        amounts = list(price.values())
        lock_payment_seed, lock_payment_id = get_lock_payment_seed(
            self.agreement_id,
            did_doc,
            self.lock_payment_condition_address,
            self.escrow_payment_condition_address,
            self.payment_token,
            amounts,
            receivers,
        )
        (
            transfer_nft_condition_seed,
            transfer_nft_condition_id,
        ) = get_transfer_nft_condition_seed(
            self.agreement_id,
            did_doc,
            self.synchronized_data.safe_contract_address,
            self.purchase_amount,
            self.transfer_nft_condition_address,
            lock_payment_id,
            self.token_address,
        )
        escrow_payment_seed, _ = get_escrow_payment_seed(
            self.agreement_id,
            did_doc,
            amounts,
            receivers,
            self.synchronized_data.safe_contract_address,
            self.escrow_payment_condition_address,
            self.payment_token,
            lock_payment_id,
            transfer_nft_condition_id,
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
        condition_ids = self._get_condition_ids(agreement_id, did_doc)
        timeouts, timelocks = get_timeouts_and_timelocks(did_doc)
        price = get_price(did_doc)
        receivers = list(price.keys())
        amounts = list(price.values())

        return {
            "agreement_id": agreement_id,
            "did": did,
            "condition_ids": condition_ids,
            "consumer": self.synchronized_data.safe_contract_address,
            "index": LOCK_CONDITION_INDEX,
            "time_outs": timeouts,
            "time_locks": timelocks,
            "reward_address": self.escrow_payment_condition_address,
            "receivers": receivers,
            "amounts": amounts,
            "contract_address": self.order_address,
            "token_address": self.payment_token,
        }

    def _get_approval_params(self) -> Dict[str, Any]:
        """Get approval params."""
        approval_params = {}
        approval_params["token"] = self.payment_token
        approval_params["spender"] = self.lock_payment_condition_address
        approval_params["amount"] = self.price  # type: ignore
        return approval_params

    def _build_withdraw_wxdai_tx(self, amount: int) -> WaitableConditionType:
        """Exchange xDAI to wxDAI."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=WXDAI,
            contract_id=str(ERC20.contract_id),
            contract_callable="build_withdraw_tx",
            amount=amount,
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.info(f"Could not build deposit tx: {response_msg}")
            return False

        approval_data = response_msg.state.body.get("data")
        if approval_data is None:
            self.context.logger.info(f"Could not build deposit tx: {response_msg}")
            return False

        batch = MultisendBatch(
            to=WXDAI,
            data=HexBytes(approval_data),
        )
        self.multisend_batches.append(batch)
        return True

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
        receivers: List[str],
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
            receives=receivers,
        )
        if not result:
            return False

        value = self.price if self.is_xdai else 0
        self.multisend_batches.append(
            MultisendBatch(
                to=contract_address,
                data=HexBytes(self.order_tx),
                value=value,
            )
        )
        return True

    def _prepare_approval_tx(
        self, token: str, spender: str, amount: int
    ) -> Generator[None, None, bool]:
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
        return True

    def _get_pending_requests(self) -> Generator[None, None, bool]:
        """Get the required balance for the subscription."""
        result = yield from self._mech_contract_interact(
            contract_callable="get_pending_requests",
            data_key="pending_requests",
            placeholder="pending_reqs",
            sender_address=self.synchronized_data.safe_contract_address,
        )
        if not result:
            self.context.logger.info("Could not get the pending requests.")
            return False

        return result

    def _get_nevermined_price(self) -> Generator[None, None, bool]:
        """Get the price of the subscription."""
        result = yield from self._mech_contract_interact(
            contract_callable="get_price",
            data_key="price",
            placeholder="credits_per_req",
        )
        if not result:
            self.context.logger.info("Could not get the price.")
            return False

        return result

    def _should_purchase(self) -> Generator[None, None, bool]:
        """Check if the subscription should be purchased."""
        if not self.params.use_nevermined:
            self.context.logger.info("Nevermined subscriptions are turned off.")
            return False

        result = yield from self._get_nevermined_price()
        if not result:
            return False

        result = yield from self._get_pending_requests()
        if not result:
            return False

        result = yield from self._get_nft_balance(
            self.token_address,
            self.synchronized_data.safe_contract_address,
            zero_x_transformer(no_did_prefixed(self.did)),
        )
        if not result:
            self.context.logger.warning("Failed to get balance")
            return False

        credits_required = (self.pending_reqs + 1) * self.credits_per_req

        return credits_required > self.balance

    def get_payload_content(self) -> Generator[None, None, str]:
        """Get the payload."""
        should_purchase = yield from self._should_purchase()
        if not should_purchase:
            return SubscriptionRound.NO_TX_PAYLOAD

        result = yield from self.check_balance()
        if not result:
            return SubscriptionRound.ERROR_PAYLOAD

        if not self.is_xdai:
            self.context.logger.warning(
                f"Subscription is not using xDAI: {self.is_xdai}"
            )
            approval_params = self._get_approval_params()
            result = yield from self._prepare_approval_tx(**approval_params)
            if not result:
                return SubscriptionRound.ERROR_PAYLOAD

        else:
            self.context.logger.info(
                f"Using wxDAI to purchase subscription: {self.wallet_balance} < {self.price}"
            )
            if self.wallet_balance < self.price:
                if self.wallet_balance + self.token_balance < self.price:
                    self.context.logger.info(
                        f"Insufficient funds to purchase subscription: {self.wallet_balance + self.token_balance} < {self.price}"
                    )
                    return SubscriptionRound.ERROR_PAYLOAD
                amount_to_withdraw = self.price - self.wallet_balance
                self.context.logger.info(f"Withdrawing {amount_to_withdraw} from WxDAI")
                result = yield from self._build_withdraw_wxdai_tx(amount_to_withdraw)
                if not result:
                    return SubscriptionRound.ERROR_PAYLOAD

        purchase_params = yield from self._get_purchase_params()
        self.context.logger.info(
            f"Purchase params for subscription: {purchase_params}. Agreement ID: {self.agreement_id}"
        )
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

        return cast(str, self.tx_hex)

    def async_act(self) -> Generator:
        """Do the action."""
        sender = self.context.agent_address

        if self.context.benchmarking_mode.enabled:
            payload = SubscriptionPayload(sender)
            yield from self.finish_behaviour(payload)

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            payload_data = yield from self.get_payload_content()
            payload = SubscriptionPayload(
                sender,
                tx_submitter=SubscriptionRound.auto_round_id(),
                tx_hash=payload_data,
                agreement_id=self.agreement_id,
                wallet_balance=self.wallet_balance,
            )
        yield from self.finish_behaviour(payload)
