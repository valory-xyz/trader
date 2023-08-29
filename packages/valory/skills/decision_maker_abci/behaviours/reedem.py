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

from typing import Any, Generator, List, Optional, Union

from hexbytes import HexBytes

from packages.valory.contracts.conditional_tokens.contract import (
    ConditionalTokensContract,
)
from packages.valory.contracts.realitio.contract import RealitioContract
from packages.valory.contracts.realitio_proxy.contract import RealitioProxyContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload
from packages.valory.skills.decision_maker_abci.redeem_info import (
    Condition,
    FPMM,
    RedeemInfo,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    QueryingBehaviour,
)


ZERO_BYTES = "0x0000000000000000000000000000000000000000000000000000000000000000"


class RedeemBehaviour(DecisionMakerBaseBehaviour, QueryingBehaviour):
    """Redeem the winnings."""

    matching_round = RedeemRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self._waitable_flag_result: bool = False
        self._built_data: Optional[HexBytes] = None
        self._redeem_info: List[RedeemInfo] = []
        self._current_redeem_info: Optional[RedeemInfo] = None
        self._expected_winnings: float = 0

    @property
    def current_redeem_info(self) -> RedeemInfo:
        """Get the current redeem info."""
        if self._current_redeem_info is None:
            raise ValueError("Current redeem information have not been set.")
        return self._current_redeem_info

    @property
    def current_fpmm(self) -> FPMM:
        """Get the current FPMM."""
        return self.current_redeem_info.fpmm

    @property
    def current_condition(self) -> Condition:
        """Get the current condition."""
        return self.current_fpmm.condition

    @property
    def current_question_id(self) -> str:
        """Get the current question's id."""
        return self.current_fpmm.question.id

    @property
    def current_collateral_token(self) -> str:
        """Get the current collateral token."""
        return self.current_fpmm.collateralToken

    @property
    def current_condition_id(self) -> str:
        """Get the current condition id."""
        return self.current_condition.id

    @property
    def current_index_sets(self) -> List[str]:
        """Get the current index sets."""
        return self.current_condition.index_sets

    @property
    def safe_address_lower(self) -> str:
        """Get the safe's address converted to lower case."""
        return self.synchronized_data.safe_contract_address.lower()

    @property
    def waitable_flag_result(self) -> bool:
        """Get a waitable flag's result for the current market."""
        return self._waitable_flag_result

    @waitable_flag_result.setter
    def waitable_flag_result(self, flag: bool) -> None:
        """Set a waitable flag's result for the current market."""
        self._waitable_flag_result = flag

    @property
    def built_data(self) -> HexBytes:
        """Get the built transaction's data."""
        return self._built_data

    @built_data.setter
    def built_data(self, built_data: Union[str, bytes]) -> None:
        """Set the built transaction's data."""
        self._built_data = HexBytes(built_data)

    def _get_redeem_info(
        self,
    ) -> Generator:
        """Fetch the trades from all the prediction markets and store them as redeeming information."""
        while True:
            can_proceed = self._prepare_fetching()
            if not can_proceed:
                break

            trades_market_chunk = yield from self._fetch_redeem_info()
            if trades_market_chunk is not None:
                redeem_updates = (RedeemInfo(**trade) for trade in trades_market_chunk)
                self._redeem_info.extend(redeem_updates)

        if self._fetch_status != FetchStatus.SUCCESS:
            self._redeem_info = []

        self.context.logger.info(f"Fetched redeeming information: {self._redeem_info}")

    def _is_winning_position(self) -> bool:
        """Return whether the current position is winning."""
        our_answer = self.current_redeem_info.outcomeIndex
        correct_answer = self.current_redeem_info.fpmm.currentAnswer
        return our_answer == correct_answer

    def _is_dust(self) -> bool:
        """Return whether the current claimable amount is dust or not."""
        return self.current_redeem_info.claimable_amount < self.params.dust_threshold

    def _conditional_tokens_interact(
        self, contract_callable: str, data_key: str, placeholder: str, **kwargs: Any
    ) -> WaitableConditionType:
        """Interact with the conditional tokens contract."""
        status = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.conditional_tokens_address,
            contract_public_id=ConditionalTokensContract.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _check_already_redeemed(self) -> WaitableConditionType:
        """Check whether we have already redeemed for this bet."""
        result = yield from self._conditional_tokens_interact(
            performative=ContractApiMessage.Performative.GET_STATE,
            contract_callable=get_name(ConditionalTokensContract.check_redeemed),
            data_key="redeemed",
            placeholder=get_name(RedeemBehaviour.waitable_flag_result),
            redeemer=self.safe_address_lower,
            collateral_token=self.current_collateral_token,
            parent_collection_id=ZERO_BYTES,
            condition_id=self.current_condition_id,
            index_sets=self.current_index_sets,
        )
        return result

    def _check_already_resolved(self) -> WaitableConditionType:
        """Check whether someone has already resolved for this market."""
        result = yield from self._conditional_tokens_interact(
            performative=ContractApiMessage.Performative.GET_STATE,
            contract_callable=get_name(ConditionalTokensContract.check_resolved),
            data_key="resolved",
            placeholder=get_name(RedeemBehaviour.waitable_flag_result),
            condition_id=self.current_condition_id,
        )
        return result

    def _build_resolve_data(self) -> WaitableConditionType:
        """Prepare the safe tx to resolve the condition."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.params.realitio_proxy_address,
            contract_public_id=RealitioProxyContract.contract_id,
            contract_callable=get_name(RealitioProxyContract.build_resolve_tx),
            data_key="data",
            placeholder=get_name(RedeemBehaviour.built_data),
            question_id=self.current_question_id,
            template_id=self.current_fpmm.templateId,
            question=self.current_fpmm.question.data,
            num_outcomes=self.current_condition.outcomeSlotCount,
        )

        if not result:
            return False

        batch = MultisendBatch(
            to=self.params.realitio_proxy_address,
            data=HexBytes(self.built_data),
        )
        self.multisend_batches.append(batch)
        return True

    def _build_claim_data(self) -> WaitableConditionType:
        """Prepare the safe tx to claim the winnings."""
        answer_data = self.current_fpmm.question.answer_data
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.params.realitio_address,
            contract_public_id=RealitioContract.contract_id,
            contract_callable=get_name(RealitioContract.build_claim_winnings),
            data_key="data",
            placeholder=get_name(RedeemBehaviour.built_data),
            question_id=self.current_question_id,
            # `history_hashes` is calculated as described here:
            # https://realitio.github.io/docs/html/contract_explanation.html#answer-history-entries.
            # however, the current implementation of the service does not place multiple answers for a single market.
            # therefore, this value is always set to zero bytes
            history_hashes=ZERO_BYTES,
            addresses=self.safe_address_lower,
            bonds=answer_data.bonds,
            answers=answer_data.answers,
        )

        if not result:
            return False

        batch = MultisendBatch(
            to=self.params.realitio_address,
            data=HexBytes(self.built_data),
        )
        self.multisend_batches.append(batch)
        return True

    def _build_redeem_data(self) -> WaitableConditionType:
        """Prepare the safe tx to redeem the position."""
        result = yield from self._conditional_tokens_interact(
            performative=ContractApiMessage.Performative.GET_STATE,
            contract_callable=get_name(
                ConditionalTokensContract.build_redeem_positions_tx
            ),
            data_key="data",
            placeholder=get_name(RedeemBehaviour.built_data),
            collateral_token=self.current_collateral_token,
            parent_collection_id=ZERO_BYTES,
            condition_id=self.current_condition_id,
            index_sets=self.current_index_sets,
        )

        if not result:
            return False

        batch = MultisendBatch(
            to=self.params.conditional_tokens_address,
            data=HexBytes(self.built_data),
        )
        self.multisend_batches.append(batch)
        return True

    def _prepare_single_redeem(self) -> Generator[None, None, bool]:
        """Prepare a multisend transaction for a single redeeming action."""
        yield from self.wait_for_condition_with_sleep(self._check_already_redeemed)
        if self.waitable_flag_result:
            return False

        yield from self.wait_for_condition_with_sleep(self._check_already_resolved)
        steps = [] if self.waitable_flag_result else [self._build_resolve_data]
        steps.extend(
            [
                self._build_claim_data,
                self._build_redeem_data,
                self._build_multisend_data,
                self._build_multisend_safe_tx_hash,
            ]
        )

        for build_step in steps:
            yield from self.wait_for_condition_with_sleep(build_step)

        self.multisend_batches = []
        self.multisend_data = b""
        self._safe_tx_hash = ""
        return True

    def _process_candidate(
        self, redeem_candidate: RedeemInfo
    ) -> Generator[None, None, Optional[bool]]:
        """Process a redeeming candidate and return whether winnings were found."""
        self._current_redeem_info = redeem_candidate
        # in case of a non-winning position or the claimable amount is dust
        if not self._is_winning_position() or self._is_dust():
            return None

        self._expected_winnings += self.current_redeem_info.claimable_amount
        winnings_found = yield from self._prepare_single_redeem()
        return winnings_found

    def _prepare_safe_tx(self) -> Generator[None, None, Optional[str]]:
        """
        Prepare the safe tx to redeem the positions of the trader.

        Steps:
            1. Get all the trades of the trader.
            2. For each trade, check if the trader has not already redeemed a non-dust winning position.
            3. If so, prepare a multisend transaction like this:
            TXS:
                1. resolve (optional)
                Check if the condition needs to be resolved. If so, add the tx to the multisend.

                2. claimWinnings
                Prepare a claim winnings tx for each winning position. Add it to the multisend.

                3. redeemPositions
                Prepare a redeem positions tx for each winning position. Add it to the multisend.

        We do not convert claimed wxDAI to xDAI, because this is the currency that the service is using to place bets.

        :yields: None
        :returns: the safe's transaction hash for the redeeming operation.
        """
        self.context.logger.info("Preparing a multisend tx to redeem payout...")
        winnings_found = False

        for redeem_candidate in self._redeem_info:
            processing_result = yield from self._process_candidate(redeem_candidate)
            if processing_result is None:
                continue
            winnings_found |= processing_result

        if not winnings_found:
            self.context.logger.info("No winnings to redeem.")
            return None

        winnings = self.wei_to_native(int(self._expected_winnings))
        msg = (
            f"Prepared a multisend transaction to redeem winnings of {winnings} wxDAI."
        )
        self.context.logger.info(msg)
        return self.tx_hex

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._get_redeem_info()
            agent = self.context.agent_address
            redeem_tx_hex = yield from self._prepare_safe_tx()
            tx_submitter = (
                self.matching_round.auto_round_id()
                if redeem_tx_hex is not None
                else None
            )
            payload = MultisigTxPayload(agent, tx_submitter, redeem_tx_hex)

        yield from self.finish_behaviour(payload)
