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

"""This module contains the behaviour for the decision-making of the skill."""

from math import prod
from typing import Any, Generator, Optional, Tuple, Union

from packages.valory.contracts.mech.contract import Mech
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    CID_PREFIX,
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader
from packages.valory.skills.decision_maker_abci.models import (
    MechInteractionResponse,
    MechResponseSpecs,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS, Bet


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SLIPPAGE = 1.05


class DecisionReceiveBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents receive the mech response."""

    matching_round = DecisionReceiveRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs, loader_cls=ComponentPackageLoader)
        self._from_block: int = 0
        self._request_id: int = 0
        self._response_hex: str = ""
        self._mech_response: Optional[MechInteractionResponse] = None

    @property
    def from_block(self) -> int:
        """Get the block number in which the request to the mech was settled."""
        return self._from_block

    @from_block.setter
    def from_block(self, from_block: int) -> None:
        """Set the block number in which the request to the mech was settled."""
        self._from_block = from_block

    @property
    def request_id(self) -> int:
        """Get the request id."""
        return self._request_id

    @request_id.setter
    def request_id(self, request_id: Union[str, int]) -> None:
        """Set the request id."""
        try:
            self._request_id = int(request_id)
        except ValueError:
            msg = f"Request id {request_id} is not a valid integer!"
            self.context.logger.error(msg)

    @property
    def response_hex(self) -> str:
        """Get the hash of the response data."""
        return self._response_hex

    @response_hex.setter
    def response_hex(self, response_hash: bytes) -> None:
        """Set the hash of the response data."""
        try:
            self._response_hex = response_hash.hex()
        except AttributeError:
            msg = f"Response hash {response_hash!r} is not valid hex bytes!"
            self.context.logger.error(msg)

    @property
    def mech_response_api(self) -> MechResponseSpecs:
        """Get the mech response api specs."""
        return self.context.mech_response

    def set_mech_response_specs(self) -> None:
        """Set the mech's response specs."""
        full_ipfs_hash = CID_PREFIX + self.response_hex
        ipfs_link = self.params.ipfs_address + full_ipfs_hash + f"/{self.request_id}"
        # The url must be dynamically generated as it depends on the ipfs hash
        self.mech_response_api.__dict__["_frozen"] = False
        self.mech_response_api.url = ipfs_link
        self.mech_response_api.__dict__["_frozen"] = True

    @property
    def mech_response(self) -> MechInteractionResponse:
        """Get the mech's response."""
        if self._mech_response is None:
            error = "The mech's response has not been set!"
            return MechInteractionResponse(error=error)
        return self._mech_response

    def _get_block_number(self) -> WaitableConditionType:
        """Get the block number in which the request to the mech was settled."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            # we do not need the address to get the block number, but the base method does
            contract_address=ZERO_ADDRESS,
            contract_public_id=Mech.contract_id,
            contract_callable="get_block_number",
            data_key="number",
            placeholder=get_name(DecisionReceiveBehaviour.from_block),
            tx_hash=self.synchronized_data.final_tx_hash,
        )

        return result

    def _get_request_id(self) -> WaitableConditionType:
        """Get the request id."""
        result = yield from self._mech_contract_interact(
            contract_callable="process_request_event",
            data_key="requestId",
            placeholder=get_name(DecisionReceiveBehaviour.request_id),
            tx_hash=self.synchronized_data.final_tx_hash,
        )
        return result

    def _get_response_hash(self) -> WaitableConditionType:
        """Get the hash of the response data."""
        self.context.logger.info(
            f"Filtering the mech's events from block {self.from_block} "
            f"for a response to our request with id {self.request_id!r}."
        )
        result = yield from self._mech_contract_interact(
            contract_callable="get_response",
            data_key="data",
            placeholder=get_name(DecisionReceiveBehaviour.response_hex),
            request_id=self.request_id,
            from_block=self.from_block,
            timeout=self.params.contract_timeout,
        )

        if result:
            self.set_mech_response_specs()

        return result

    def _handle_response(
        self,
        res: Optional[str],
    ) -> Optional[Any]:
        """Handle the response from the IPFS.

        :param res: the response to handle.
        :return: the response's result, using the given keys. `None` if response is `None` (has failed).
        """
        if res is None:
            msg = f"Could not get the mech's response from {self.mech_response_api.api_id}"
            self.context.logger.error(msg)
            self.mech_response_api.increment_retries()
            return None

        self.context.logger.info(f"Retrieved the mech's response: {res}.")
        self.mech_response_api.reset_retries()
        return res

    def _get_response(self) -> WaitableConditionType:
        """Get the response data from IPFS."""
        specs = self.mech_response_api.get_spec()
        res_raw = yield from self.get_http_response(**specs)
        res = self.mech_response_api.process_response(res_raw)
        res = self._handle_response(res)

        if self.mech_response_api.is_retries_exceeded():
            error = "Retries were exceeded while trying to get the mech's response."
            self._mech_response = MechInteractionResponse(error=error)
            return True

        if res is None:
            return False

        try:
            self._mech_response = MechInteractionResponse(**res)
        except (ValueError, TypeError, KeyError):
            self._mech_response = MechInteractionResponse.incorrect_format(res)

        return True

    def _get_decision(
        self,
    ) -> Generator[None, None, Tuple[Optional[int], Optional[float], Optional[float]]]:
        """Get vote, win probability and confidence."""
        for step in (
            self._get_block_number,
            self._get_request_id,
            self._get_response_hash,
            self._get_response,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        self.context.logger.info(f"Decision has been received:\n{self.mech_response}")
        if self.mech_response.result is None:
            self.context.logger.error(
                f"There was an error on the mech's response: {self.mech_response.error}"
            )
            return None, None, None

        return (
            self.mech_response.result.vote,
            self.mech_response.result.win_probability,
            self.mech_response.result.confidence,
        )

    @staticmethod
    def _get_bet_sample_info(bet: Bet, vote: int) -> Tuple[int, int]:
        """Get the bet sample information."""
        token_amounts = bet.outcomeTokenAmounts
        selected_type_tokens_in_pool = token_amounts[vote]
        opposite_vote = vote ^ 1
        other_tokens_in_pool = token_amounts[opposite_vote]

        return selected_type_tokens_in_pool, other_tokens_in_pool

    def _calc_binary_shares(self, net_bet_amount: int, vote: int) -> Tuple[int, int]:
        """Calculate the claimed shares. This calculation only works for binary markets."""
        bet = self.synchronized_data.sampled_bet

        # calculate the pool's k (x*y=k)
        token_amounts = bet.outcomeTokenAmounts
        self.context.logger.info(f"Token amounts: {[x for x in token_amounts]}")
        k = prod(token_amounts)
        self.context.logger.info(f"k: {k}")

        # the OMEN market trades an equal amount of the investment to each of the tokens in the pool
        # here we calculate the bet amount per pool's token
        bet_per_token = net_bet_amount / BINARY_N_SLOTS
        self.context.logger.info(f"Bet per token: {bet_per_token}")

        # calculate the number of the traded tokens
        prices = bet.outcomeTokenMarginalPrices
        self.context.logger.info(f"Prices: {prices}")

        if prices is None:
            return 0, 0
        tokens_traded = [int(bet_per_token / prices[i]) for i in range(BINARY_N_SLOTS)]
        self.context.logger.info(f"Tokens traded: {[x for x in tokens_traded]}")

        # get the shares for the answer that the service has selected
        selected_shares = tokens_traded.pop(vote)
        self.context.logger.info(f"Selected shares: {selected_shares}")

        # get the shares for the opposite answer
        other_shares = tokens_traded.pop()
        self.context.logger.info(f"Other shares: {other_shares}")

        # get the number of tokens in the pool for the answer that the service has selected
        selected_type_tokens_in_pool = token_amounts.pop(vote)
        self.context.logger.info(
            f"Selected type tokens in pool: {selected_type_tokens_in_pool}"
        )

        # get the number of tokens in the pool for the opposite answer
        other_tokens_in_pool = token_amounts.pop()
        self.context.logger.info(f"Other tokens in pool: {other_tokens_in_pool}")

        # the OMEN market then trades the opposite tokens to the tokens of the answer that has been selected,
        # preserving the balance of the pool
        # here we calculate the number of shares that we get after trading the tokens for the opposite answer
        tokens_remaining_in_pool = int(k / (other_tokens_in_pool + other_shares))
        self.context.logger.info(
            f"Tokens remaining in pool: {tokens_remaining_in_pool}"
        )

        swapped_shares = selected_type_tokens_in_pool - tokens_remaining_in_pool
        self.context.logger.info(f"Swapped shares: {swapped_shares}")

        # calculate the resulting number of shares if the service would take that position
        num_shares = selected_shares + swapped_shares
        self.context.logger.info(f"Number of shares: {num_shares}")

        # calculate the available number of shares
        price = prices[vote]
        self.context.logger.info(f"Price: {prices[vote]}")

        available_shares = int(selected_type_tokens_in_pool * price)
        self.context.logger.info(f"Available shares: {available_shares}")

        return num_shares, available_shares

    def _is_profitable(
        self, vote: int, win_probability: float, confidence: float
    ) -> Generator[None, None, Tuple[bool, int]]:
        """Whether the decision is profitable or not."""
        bet = self.synchronized_data.sampled_bet
        selected_type_tokens_in_pool, other_tokens_in_pool = self._get_bet_sample_info(
            bet, vote
        )

        bet_amount = yield from self.get_bet_amount(
            win_probability,
            confidence,
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            bet.fee,
        )

        self.context.logger.info(f"Bet amount: {bet_amount}")
        self.context.logger.info(f"Bet fee: {bet.fee}")
        net_bet_amount = remove_fraction_wei(bet_amount, self.wei_to_native(bet.fee))
        self.context.logger.info(f"Net bet amount: {net_bet_amount}")

        num_shares, available_shares = self._calc_binary_shares(net_bet_amount, vote)

        self.context.logger.info(f"Adjusted available shares: {available_shares}")
        if num_shares > available_shares * SLIPPAGE:
            self.context.logger.warning(
                "Kindly contemplate reducing your bet amount, as the pool's liquidity is low compared to your bet. "
                "Consequently, this situation entails a higher level of risk as the obtained number of shares, "
                "and therefore the potential net profit, will be lower than if the pool had higher liquidity!"
            )
        bet_threshold = self.params.bet_threshold
        if bet_threshold <= 0:
            self.context.logger.warning(
                f"A non-positive bet threshold was given ({bet_threshold}). The threshold will be disabled, "
                f"which means that any non-negative potential profit will be considered profitable!"
            )
            bet_threshold = 0

        potential_net_profit = num_shares - net_bet_amount - bet_threshold
        is_profitable = potential_net_profit >= 0

        self.context.logger.info(
            f"The current liquidity of the market is {bet.scaledLiquidityMeasure} xDAI. "
            f"The potential net profit is {self.wei_to_native(potential_net_profit)} xDAI "
            f"from buying {self.wei_to_native(num_shares)} shares for the option {bet.get_outcome(vote)}.\n"
            f"Decision for profitability of this market: {is_profitable}."
        )
        return is_profitable, bet_amount

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            vote, win_probability, confidence = yield from self._get_decision()
            is_profitable = None
            bet_amount = None
            if (
                vote is not None
                and confidence is not None
                and win_probability is not None
            ):
                is_profitable, bet_amount = yield from self._is_profitable(
                    vote, win_probability, confidence
                )
            payload = DecisionReceivePayload(
                self.context.agent_address,
                is_profitable,
                vote,
                confidence,
                bet_amount,
            )

        yield from self.finish_behaviour(payload)
