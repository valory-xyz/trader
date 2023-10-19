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
from packages.valory.contracts.erc20.contract import ERC20

from packages.valory.contracts.mech.contract import Mech
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    CID_PREFIX,
    DecisionMakerBaseBehaviour,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.behaviours.bet_placement import WXDAI
from packages.valory.skills.decision_maker_abci.models import (
    MechInteractionResponse,
    MechResponseSpecs,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
SLIPPAGE = 1.05


class DecisionReceiveBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents receive the mech response."""

    matching_round = DecisionReceiveRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
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
    def collateral_token(self) -> str:
        """Get the contract address of the token that the market maker supports."""
        return self.synchronized_data.sampled_bet.collateralToken
    
    @property
    def is_wxdai(self) -> bool:
        """Get whether the collateral address is wxDAI."""
        return self.collateral_token.lower() == WXDAI.lower()

    @property
    def mech_price(self) -> int:
        """Get the mech price."""
        return self._mech_price

    @mech_price.setter
    def mech_price(self, price: int) -> None:
        """Set the mech price."""
        self._mech_price = price

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
        except (ValueError, TypeError):
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
            return None, None, None, None

        return self.mech_response.result.vote, self.mech_response.result.odds, self.mech_response.result.win_probability, self.mech_response.result.confidence
    

    def _get_bet_sample_info(bet, vote) -> Tuple[int, int]:
        token_amounts = bet.outcomeTokenAmounts
        if token_amounts is None:
            return None, None, None
        
        selected_type_tokens_in_pool = token_amounts.pop(vote)
        other_tokens_in_pool = token_amounts.pop()
        bet_fee = bet.fee
        
        return selected_type_tokens_in_pool, other_tokens_in_pool, bet_fee


    def _calc_binary_shares(self, bet_amount: int, win_probability: float, confidence: float, vote: int) -> Tuple[int, int]:
        """Calculate the claimed shares. This calculation only works for binary markets."""
        bet = self.synchronized_data.sampled_bet

        # calculate the pool's k (x*y=k)
        token_amounts = bet.outcomeTokenAmounts
        self.context.logger.info(f"Token amounts: {[x/(10**18) for x in token_amounts]}")
        if token_amounts is None:
            return 0, 0
        k = prod(token_amounts)
        self.context.logger.info(f"k: {k}")

        # the OMEN market trades an equal amount of the investment to each of the tokens in the pool
        # here we calculate the bet amount per pool's token
        bet_per_token = bet_amount / BINARY_N_SLOTS
        self.context.logger.info(f"Bet per token: {bet_per_token/(10**18)}")

        # calculate the number of the traded tokens
        prices = bet.outcomeTokenMarginalPrices
        self.context.logger.info(f"Prices: {prices}")

        if prices is None:
            return 0, 0
        tokens_traded = [int(bet_per_token / prices[i]) for i in range(BINARY_N_SLOTS)]
        self.context.logger.info(f"Tokens traded: {[x/(10**18) for x in tokens_traded]}")

        # get the shares for the answer that the service has selected
        selected_shares = tokens_traded.pop(vote)
        self.context.logger.info(f"Selected shares: {selected_shares/(10**18)}")

        # get the shares for the opposite answer
        other_shares = tokens_traded.pop()
        self.context.logger.info(f"Other shares: {other_shares/(10**18)}")

        # get the number of tokens in the pool for the answer that the service has selected
        selected_type_tokens_in_pool = token_amounts.pop(vote)
        self.context.logger.info(f"Selected type tokens in pool: {selected_type_tokens_in_pool/(10**18)}")

        # get the number of tokens in the pool for the opposite answer
        other_tokens_in_pool = token_amounts.pop()
        self.context.logger.info(f"Other tokens in pool: {other_tokens_in_pool/(10**18)}")

        # the OMEN market then trades the opposite tokens to the tokens of the answer that has been selected,
        # preserving the balance of the pool
        # here we calculate the number of shares that we get after trading the tokens for the opposite answer
        tokens_remaining_in_pool = int(k / (other_tokens_in_pool + other_shares))
        self.context.logger.info(f"Tokens remaining in pool: {tokens_remaining_in_pool/(10**18)}")
        
        swapped_shares = selected_type_tokens_in_pool - tokens_remaining_in_pool
        self.context.logger.info(f"Swapped shares: {swapped_shares/(10**18)}")

        # calculate the resulting number of shares if the service would take that position
        num_shares = selected_shares + swapped_shares
        self.context.logger.info(f"Number of shares: {num_shares/(10**18)}")

        # calculate the available number of shares
        price = prices[vote]
        self.context.logger.info(f"Price: {prices[vote]}")

        available_shares = int(selected_type_tokens_in_pool * price)
        self.context.logger.info(f"Available shares: {available_shares/(10**18)}")

        return num_shares, available_shares

    def _get_mech_price(self) -> WaitableConditionType:
        """Get the price of the mech request."""
        result = yield from self._mech_contract_interact(
            "get_price", "price", get_name(DecisionReceiveBehaviour.mech_price)
        )
        return result
    
    def _collateral_amount_info(self, amount: int) -> str:
        """Get a description of the collateral token's amount."""
        return (
            f"{self.wei_to_native(amount)} wxDAI"
            if self.is_wxdai
            else f"{amount} WEI of the collateral token with address {self.collateral_token}"
        )

    def _check_balance(self) -> WaitableConditionType:
        """Check the safe's balance."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.collateral_token,
            contract_id=str(ERC20.contract_id),
            contract_callable="check_balance",
            account=self.synchronized_data.safe_contract_address,
        )
        if response_msg.performative != ContractApiMessage.Performative.RAW_TRANSACTION:
            self.context.logger.error(
                f"Could not calculate the balance of the safe: {response_msg}"
            )
            return False

        token = response_msg.raw_transaction.body.get("token", None)
        wallet = response_msg.raw_transaction.body.get("wallet", None)
        if token is None or wallet is None:
            self.context.logger.error(
                f"Something went wrong while trying to get the balance of the safe: {response_msg}"
            )
            return False

        self.token_balance = int(token)
        self.wallet_balance = int(wallet)

        native = self.wei_to_native(self.wallet_balance)
        collateral = self._collateral_amount_info(self.token_balance)
        self.context.logger.info(f"The safe has {native} xDAI and {collateral}.")
        return True

    def _is_profitable(self, vote: int, odds: float, win_probability: float, confidence: float) -> bool:
        """Whether the decision is profitable or not."""
        bet = self.synchronized_data.sampled_bet
        yield from self._check_balance()
        bankroll = self.wallet_balance + self.token_balance
        self.context.logger.info(f"Wallet balance: {self.wallet_balance}")
        self.context.logger.info(f"Token balance: {self.token_balance}")
        self.context.logger.info(f"Bankroll: {bankroll}")
        selected_type_tokens_in_pool, other_tokens_in_pool, bet_fee = self._get_bet_sample_info(bet, vote)
        
        # Testing and printing kelly bet amount
        self.context.logger.info("Start kelly bet amount calculation")
        bet_amount = self.get_bet_amount(
            bankroll,
            "kelly_criterion",
            win_probability,
            confidence,
            selected_type_tokens_in_pool,
            other_tokens_in_pool, 
            bet_fee,
        )
        
        # Actual bet amount
        self.context.logger.info("Start bet amount per conf threshold calculation")
        bet_amount = self.get_bet_amount(
            bankroll,
            self.params.trading_strategy,
            win_probability,
            confidence,
            selected_type_tokens_in_pool,
            other_tokens_in_pool, 
            bet_fee,
        )

        self.context.logger.info(f"Bet amount: {bet_amount/(10**18)}")
        self.context.logger.info(f"Bet fee: {bet.fee/(10**18)}")

        num_shares, available_shares = self._calc_binary_shares(bet_amount, win_probability, confidence, vote)
        bet_threshold = self.params.bet_threshold
        self.context.logger.info(f"Bet threshold: {bet_threshold/(10**18)}")

        if bet_threshold <= 0:
            self.context.logger.warning(
                f"A non-positive bet threshold was given ({bet_threshold}). The threshold will be disabled, "
                f"which means that any non-negative potential profit will be considered profitable!"
            )
            bet_threshold = 0

        yield from self.wait_for_condition_with_sleep(self._get_mech_price)
        self.context.logger.info(f"Mech price: {self.mech_price/(10**18)}")
        potential_net_profit = num_shares - bet_amount - self.mech_price - bet_threshold
        self.context.logger.info(f"Potential net profit: {potential_net_profit/(10**18)}")
        is_profitable = potential_net_profit >= 0 and num_shares <= available_shares
        self.context.logger.info(f"Is profitable: {is_profitable}")
        shares_out = self.wei_to_native(num_shares)
        self.context.logger.info(f"Shares out: {shares_out}")
        available_in = self.wei_to_native(available_shares)
        self.context.logger.info(f"Available in: {available_in}")
        shares_out_of = f"{shares_out} / {available_in}"
        self.context.logger.info(f"Shares out of: {shares_out_of}")
        potential_net_profit = num_shares - bet_amount - bet_threshold
        is_profitable = potential_net_profit >= 0

        if num_shares > available_shares * SLIPPAGE:
            self.context.logger.warning(
                "Kindly contemplate reducing your bet amount, as the pool's liquidity is low compared to your bet. "
                "Consequently, this situation entails a higher level of risk as the obtained number of shares, "
                "and therefore the potential net profit, will be lower than if the pool had higher liquidity!"
            )

        self.context.logger.info(
            f"The current liquidity of the market is {bet.scaledLiquidityMeasure} xDAI. "
            f"The potential net profit is {self.wei_to_native(potential_net_profit)} xDAI "
            f"from buying {self.wei_to_native(num_shares)} shares for the option {bet.get_outcome(vote)}.\n"
            f"Decision for profitability of this market: {is_profitable}."
        )

        return is_profitable

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            vote, odds, win_probability, confidence = yield from self._get_decision()
            is_profitable = None
            if vote is not None and confidence is not None and odds is not None and win_probability is not None:
                is_profitable = yield from self._is_profitable(vote, odds, win_probability, confidence)
            payload = DecisionReceivePayload(
                self.context.agent_address,
                is_profitable,
                vote,
                odds,
                win_probability,
                confidence,
            )

        yield from self.finish_behaviour(payload)
