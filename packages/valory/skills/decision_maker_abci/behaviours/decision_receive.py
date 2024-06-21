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

"""This module contains the behaviour for the decision-making of the skill."""

import csv
import json
from math import prod
from typing import Any, Dict, Generator, Optional, Tuple, Union, List

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader
from packages.valory.skills.decision_maker_abci.models import (
    BenchmarkingMockData,
    CONFIDENCE_FIELD,
    INFO_UTILITY_FIELD,
    P_NO_FIELD,
    P_YES_FIELD,
    PredictionResponse,
    LiquidityInfo,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS, Bet
from packages.valory.skills.mech_interact_abci.states.base import (
    MechInteractionResponse,
)


SLIPPAGE = 1.05
WRITE_TEXT_MODE = "w+t"
COMMA = ","


class DecisionReceiveBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents receive the mech response."""

    matching_round = DecisionReceiveRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs, loader_cls=ComponentPackageLoader)
        self._request_id: int = 0
        self._mech_response: Optional[MechInteractionResponse] = None
        self._rows_exceeded: bool = False

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
    def mech_response(self) -> MechInteractionResponse:
        """Get the mech's response."""
        if self._mech_response is None:
            error = "The mech's response has not been set!"
            return MechInteractionResponse(error=error)
        return self._mech_response

    def _next_dataset_row(self) -> Optional[Dict[str, str]]:
        """Read the next row from the input dataset which is used during the benchmarking mode.

        :return: a dictionary with the header fields mapped to the values of the first row.
            If no rows are left to process in the file, returns `None`.
        """
        sep = self.benchmarking_mode.sep
        dataset_filepath = (
            self.params.store_path / self.benchmarking_mode.dataset_filename
        )
        next_mock_data_row = self.synchronized_data.next_mock_data_row

        row_with_headers: Optional[Dict[str, str]] = None
        with open(dataset_filepath) as read_dataset:
            reader = csv.DictReader(read_dataset, delimiter=sep)

            for _ in range(next_mock_data_row):
                row_with_headers = next(reader, {})

            if not row_with_headers:
                # if no rows are in the file, then we finished the benchmarking
                self._rows_exceeded = True
                return None

        msg = f"Processing question in row with index {next_mock_data_row}: {row_with_headers}"
        self.context.logger.info(msg)
        return row_with_headers

    def _parse_dataset_row(self, row: Dict[str, str]) -> str:
        """Parse a dataset's row to store the mock market data and to mock a prediction response."""
        mode = self.benchmarking_mode
        self.shared_state.mock_data = BenchmarkingMockData(
            row[mode.question_id_field],
            row[mode.question_field],
            row[mode.answer_field],
        )
        mech_tool = self.synchronized_data.mech_tool
        fields = {}

        for prediction_attribute, field_part in {
            P_YES_FIELD: mode.p_yes_field_part,
            P_NO_FIELD: mode.p_no_field_part,
            CONFIDENCE_FIELD: mode.confidence_field_part,
        }.items():
            if mode.part_prefix_mode:
                fields[prediction_attribute] = row[field_part + mech_tool]
            else:
                fields[prediction_attribute] = row[mech_tool + field_part]

        # set the info utility to zero as it does not matter for the benchmark
        fields[INFO_UTILITY_FIELD] = "0"
        return json.dumps(fields)

    def _mock_response(self) -> None:
        """Mock the response data."""
        dataset_row = self._next_dataset_row()
        if dataset_row is None:
            return
        mech_response = self._parse_dataset_row(dataset_row)
        self._mech_response = MechInteractionResponse(result=mech_response)

    def _get_response(self) -> None:
        """Get the response data."""
        mech_responses = self.synchronized_data.mech_responses
        if not mech_responses:
            error = "No Mech responses in synchronized_data."
            self._mech_response = MechInteractionResponse(error=error)

        self._mech_response = mech_responses[0]

    def _get_decision(
        self,
    ) -> Tuple[
        Optional[int],
        Optional[float],
        Optional[float],
        Optional[float],
        Optional[float],
    ]:
        """Get vote, win probability and confidence."""
        if self.benchmarking_mode.enabled:
            self._mock_response()
        else:
            self._get_response()

        if self._mech_response is None:
            self.context.logger.info("The benchmarking has finished!")
            return None, None, None, None, None

        self.context.logger.info(f"Decision has been received:\n{self.mech_response}")
        if self.mech_response.result is None:
            self.context.logger.error(
                f"There was an error on the mech's response: {self.mech_response.error}"
            )
            return None, None, None, None, None

        try:
            result = PredictionResponse(**json.loads(self.mech_response.result))
        except (json.JSONDecodeError, ValueError) as exc:
            self.context.logger.error(f"Could not parse the mech's response: {exc}")
            return None, None, None, None, None

        return (
            result.vote,
            result.p_yes,
            result.p_no,
            result.win_probability,
            result.confidence,
        )

    @staticmethod
    def _get_bet_sample_info(bet: Bet, vote: int) -> Tuple[int, int]:
        """Get the bet sample information."""
        token_amounts = bet.outcomeTokenAmounts
        selected_type_tokens_in_pool = token_amounts[vote]
        opposite_vote = vote ^ 1
        other_tokens_in_pool = token_amounts[opposite_vote]

        return selected_type_tokens_in_pool, other_tokens_in_pool

    def _calc_binary_shares(
        self, bet: Bet, net_bet_amount: int, vote: int
    ) -> Tuple[int, int]:
        """Calculate the claimed shares. This calculation only works for binary markets."""
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

    def _get_mocked_bet(self) -> Bet:
        """Function to prepare the mocked bet based on liquidity info at the shared state"""
        liquidity_amounts = self.shared_state.liquidity_amounts
        liquidity_prices = self.shared_state.liquidity_prices
        markets = list(liquidity_amounts.keys())
        if self.shared_state.mock_data is not None:
            question_id = self.shared_state.mock_data.id
        else:
            raise ValueError("No mocked data information")

        # check if the question is at the dictionary
        outcome_token_amounts = self.benchmarking_mode.outcome_token_amounts
        outcome_token_prices = self.benchmarking_mode.outcome_token_marginal_prices
        if question_id in markets:  # read the previous information
            outcome_token_amounts = liquidity_amounts[question_id]
            outcome_token_prices = liquidity_prices[question_id]
        else:  # initializing liquidity info
            liquidity_amounts[question_id] = outcome_token_amounts
            liquidity_prices[question_id] = outcome_token_prices

        self.context.logger.info(f"outcome token amounts: {outcome_token_amounts}")
        self.context.logger.info(f"outcome token prices: {outcome_token_prices}")

        mocked_bet = Bet(
            id="",
            market="",
            title="",
            collateralToken="",
            creator="",
            fee=self.benchmarking_mode.pool_fee,
            openingTimestamp=0,
            outcomeSlotCount=2,
            outcomeTokenAmounts=outcome_token_amounts,
            outcomeTokenMarginalPrices=outcome_token_prices,
            outcomes=["Yes", "No"],
            scaledLiquidityMeasure=10,
        )
        return mocked_bet

    def _update_liquidity_info(self, bet_amount: float, vote: int) -> LiquidityInfo:
        """Function to update the liquidity information after placing a bet for a market
        and to return the old and new prices"""
        liquidity_amounts = self.shared_state.liquidity_amounts
        liquidity_prices = self.shared_state.liquidity_prices
        markets = list(liquidity_amounts.keys())
        if self.shared_state.mock_data is not None:
            question_id = self.shared_state.mock_data.id
        else:
            raise ValueError("No mocked data information")
        if question_id not in markets:
            raise ValueError(
                f"The market id {question_id} is not at the shared state dictionary"
            )

        old_liquidity_amounts = liquidity_amounts[question_id]
        selected_type_tokens_in_pool = old_liquidity_amounts[vote]
        opposite_vote = vote ^ 1
        other_tokens_in_pool = old_liquidity_amounts[opposite_vote]
        self.context.logger.info(f"Voting for option = {vote}")
        if vote == 0:
            old_L0, old_L1 = selected_type_tokens_in_pool, other_tokens_in_pool
            new_L0, new_L1 = old_L0 + bet_amount, old_L0 * old_L1 / (
                old_L0 + bet_amount
            )
        else:
            old_L0, old_L1 = other_tokens_in_pool, selected_type_tokens_in_pool
            new_L0, new_L1 = (
                old_L0 * old_L1 / (old_L1 + bet_amount),
                old_L1 + bet_amount,
            )
        # new liquidity prices computed from the new amounts
        new_p0 = new_L0 / (new_L0 + new_L1)
        new_p1 = new_L1 / (new_L0 + new_L1)
        liquidity_prices[question_id] = [new_p0, new_p1]
        self.context.logger.info(
            f"updating liquidity prices for question: {question_id}"
        )
        self.shared_state.liquidity_prices = liquidity_prices

        # updating liquidity amounts
        new_amounts = [int(new_L0), int(new_L1)]
        liquidity_amounts[question_id] = new_amounts

        self.context.logger.info(
            f"updating liquidity amounts for question: {question_id}"
        )
        self.context.logger.info(f"New amounts={new_amounts}")
        self.shared_state.liquidity_amounts = liquidity_amounts

        return LiquidityInfo(old_L0, old_L1, int(new_L0), int(new_L1))

    def _is_profitable(
        self,
        vote: int,
        p_yes: float,
        p_no: float,
        win_probability: float,
        confidence: float,
    ) -> Generator[None, None, Tuple[bool, int]]:
        """Whether the decision is profitable or not."""

        bet = (
            self.sampled_bet
            if not self.benchmarking_mode.enabled
            else self._get_mocked_bet()
        )
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
        bet_threshold = self.params.bet_threshold
        bet_amount = max(bet_amount, bet_threshold)

        self.context.logger.info(f"Bet amount: {bet_amount}")
        self.context.logger.info(f"Bet fee: {bet.fee}")
        net_bet_amount = remove_fraction_wei(bet_amount, self.wei_to_native(bet.fee))
        self.context.logger.info(f"Net bet amount: {net_bet_amount}")

        num_shares, available_shares = self._calc_binary_shares(
            bet, net_bet_amount, vote
        )

        self.context.logger.info(f"Adjusted available shares: {available_shares}")
        if num_shares > available_shares * SLIPPAGE:
            self.context.logger.warning(
                "Kindly contemplate reducing your bet amount, as the pool's liquidity is low compared to your bet. "
                "Consequently, this situation entails a higher level of risk as the obtained number of shares, "
                "and therefore the potential net profit, will be lower than if the pool had higher liquidity!"
            )
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

        if self.benchmarking_mode.enabled:
            if is_profitable:
                liquidity_info: LiquidityInfo = self._update_liquidity_info(
                    net_bet_amount, vote
                )
                self._write_benchmark_results(
                    p_yes, p_no, confidence, bet_amount, liquidity_info
                )
            else:
                self._write_benchmark_results(p_yes, p_no, confidence)

        return is_profitable, bet_amount

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            vote, p_yes, p_no, win_probability, confidence = self._get_decision()
            is_profitable = None
            bet_amount = None
            next_mock_data_row = None
            if (
                vote is not None
                and p_yes is not None
                and p_no is not None
                and confidence is not None
                and win_probability is not None
            ):
                is_profitable, bet_amount = yield from self._is_profitable(
                    vote, p_yes, p_no, win_probability, confidence
                )

                if self.benchmarking_mode.enabled:
                    next_mock_data_row = self.synchronized_data.next_mock_data_row + 1

            elif self.benchmarking_mode.enabled and not self._rows_exceeded:
                self._write_benchmark_results(p_yes, p_no, confidence, bet_amount)
                next_mock_data_row = self.synchronized_data.next_mock_data_row + 1

            payload = DecisionReceivePayload(
                self.context.agent_address,
                is_profitable,
                vote,
                confidence,
                bet_amount,
                next_mock_data_row,
            )

        yield from self.finish_behaviour(payload)
