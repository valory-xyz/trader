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
from copy import deepcopy
from math import prod
from typing import Any, Dict, Generator, Optional, Tuple, Union

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.io_.loader import ComponentPackageLoader
from packages.valory.skills.decision_maker_abci.models import (
    BenchmarkingMockData,
    LiquidityInfo,
)
from packages.valory.skills.decision_maker_abci.payloads import DecisionReceivePayload
from packages.valory.skills.decision_maker_abci.states.decision_receive import (
    DecisionReceiveRound,
)
from packages.valory.skills.market_manager_abci.bets import (
    BINARY_N_SLOTS,
    Bet,
    CONFIDENCE_FIELD,
    INFO_UTILITY_FIELD,
    P_NO_FIELD,
    P_YES_FIELD,
    PredictionResponse,
)
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

            next_row: Optional[Dict[str, str]] = next(reader, {})
            if not next_row:
                self.shared_state.last_benchmarking_has_run = True

        msg = f"Processing question in row with index {next_mock_data_row}: {row_with_headers}"
        self.context.logger.info(msg)
        return row_with_headers

    def _parse_dataset_row(self, row: Dict[str, str]) -> str:
        """Parse a dataset's row to store the mock market data and to mock a prediction response."""
        mode = self.benchmarking_mode
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

        # set the benchmarking mock data
        self.shared_state.mock_data = BenchmarkingMockData(
            row[mode.question_id_field],
            row[mode.question_field],
            row[mode.answer_field],
            float(fields[P_YES_FIELD]),
        )

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
        if mech_responses:
            self._mech_response = mech_responses[0]
            return
        error = "No Mech responses in synchronized_data."
        self._mech_response = MechInteractionResponse(error=error)

    def _get_decision(
        self,
    ) -> Optional[PredictionResponse]:
        """Get vote, win probability and confidence."""
        if self.benchmarking_mode.enabled:
            self._mock_response()
        else:
            self._get_response()

        if self._mech_response is None:
            self.context.logger.info("The benchmarking has finished!")
            return None

        self.context.logger.info(f"Decision has been received:\n{self.mech_response}")
        if self.mech_response.result is None:
            self.context.logger.error(
                f"There was an error on the mech's response: {self.mech_response.error}"
            )
            return None

        try:
            return PredictionResponse(**json.loads(self.mech_response.result))
        except (json.JSONDecodeError, ValueError) as exc:
            self.context.logger.error(f"Could not parse the mech's response: {exc}")
            return None

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
        """Prepare the mocked bet based on the stored liquidity info."""
        shared_state = self.shared_state
        question_id = shared_state.mock_question_id
        benchmarking_mode = self.benchmarking_mode
        outcome_token_amounts = shared_state.liquidity_amounts.setdefault(
            question_id, benchmarking_mode.outcome_token_amounts
        )
        outcome_token_marginal_prices = shared_state.liquidity_prices.setdefault(
            question_id, benchmarking_mode.outcome_token_marginal_prices
        )
        return Bet(
            id="",
            market="",
            title="",
            collateralToken="",
            creator="",
            fee=self.benchmarking_mode.pool_fee,
            openingTimestamp=0,
            outcomeSlotCount=2,
            outcomeTokenAmounts=outcome_token_amounts,
            outcomeTokenMarginalPrices=outcome_token_marginal_prices,
            outcomes=["Yes", "No"],
            scaledLiquidityMeasure=10,
        )

    def _calculate_new_liquidity(self, bet_amount: int, vote: int) -> LiquidityInfo:
        """Calculate and return the new liquidity information."""
        liquidity_amounts = self.shared_state.current_liquidity_amounts
        selected_type_tokens_in_pool = liquidity_amounts[vote]
        opposite_vote = vote ^ 1
        other_tokens_in_pool = liquidity_amounts[opposite_vote]
        new_selected = selected_type_tokens_in_pool + bet_amount
        new_other = other_tokens_in_pool * selected_type_tokens_in_pool / new_selected
        if vote == 0:
            return LiquidityInfo(
                selected_type_tokens_in_pool,
                other_tokens_in_pool,
                new_selected,
                int(new_other),
            )
        return LiquidityInfo(
            other_tokens_in_pool,
            selected_type_tokens_in_pool,
            int(new_other),
            new_selected,
        )

    def _update_liquidity_info(self, bet_amount: int, vote: int) -> LiquidityInfo:
        """Update the liquidity information and the prices after placing a bet for a market."""
        liquidity_info = self._calculate_new_liquidity(bet_amount, vote)
        self.shared_state.current_liquidity_prices = liquidity_info.get_new_prices()
        self.shared_state.current_liquidity_amounts = liquidity_info.get_end_liquidity()
        return liquidity_info

    def rebet_allowed(
        self, prediction_response: PredictionResponse, potential_net_profit: int
    ) -> bool:
        """Whether a rebet is allowed or not."""
        bet = self.sampled_bet
        previous_response = deepcopy(bet.prediction_response)
        previous_liquidity = bet.position_liquidity
        previous_net_profit = bet.potential_net_profit
        bet.prediction_response = prediction_response
        vote = bet.prediction_response.vote
        bet.position_liquidity = bet.outcomeTokenAmounts[vote] if vote else 0
        bet.potential_net_profit = potential_net_profit
        rebet_allowed = bet.rebet_allowed(
            previous_response, previous_liquidity, previous_net_profit
        )
        if not rebet_allowed:
            # reset the in-memory bets so that the updates of the sampled bet above are reverted
            self.read_bets()
            self.context.logger.info("Conditions for rebetting are not met!")
        return rebet_allowed

    def _is_profitable(
        self, prediction_response: PredictionResponse
    ) -> Generator[None, None, Tuple[bool, int]]:
        """Whether the decision is profitable or not."""
        if prediction_response.vote is None:
            return False, 0

        bet = (
            self.sampled_bet
            if not self.benchmarking_mode.enabled
            else self._get_mocked_bet()
        )
        selected_type_tokens_in_pool, other_tokens_in_pool = self._get_bet_sample_info(
            bet, prediction_response.vote
        )

        bet_amount = yield from self.get_bet_amount(
            prediction_response.win_probability,
            prediction_response.confidence,
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            bet.fee,
            self.synchronized_data.weighted_accuracy,
        )
        bet_threshold = self.params.bet_threshold
        bet_amount = max(bet_amount, bet_threshold)

        self.context.logger.info(f"Bet amount: {bet_amount}")
        self.context.logger.info(f"Bet fee: {bet.fee}")
        net_bet_amount = remove_fraction_wei(bet_amount, self.wei_to_native(bet.fee))
        self.context.logger.info(f"Net bet amount: {net_bet_amount}")

        num_shares, available_shares = self._calc_binary_shares(
            bet, net_bet_amount, prediction_response.vote
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
            f"from buying {self.wei_to_native(num_shares)} shares for the option {bet.get_outcome(prediction_response.vote)}.\n"
            f"Decision for profitability of this market: {is_profitable}."
        )

        if self.benchmarking_mode.enabled:
            if is_profitable:
                liquidity_info = self._update_liquidity_info(
                    net_bet_amount, prediction_response.vote
                )
                self._write_benchmark_results(
                    prediction_response, bet_amount, liquidity_info
                )
            else:
                self._write_benchmark_results(prediction_response)

        if is_profitable:
            is_profitable = self.rebet_allowed(
                prediction_response, potential_net_profit
            )

        return is_profitable, bet_amount

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            prediction_response = self._get_decision()
            is_profitable = None
            bet_amount = None
            next_mock_data_row = None
            bets_hash = None
            if prediction_response is not None and prediction_response.vote is not None:
                is_profitable, bet_amount = yield from self._is_profitable(
                    prediction_response
                )
                if is_profitable:
                    self.store_bets()
                    bets_hash = self.hash_stored_bets()

                if self.benchmarking_mode.enabled:
                    next_mock_data_row = self.synchronized_data.next_mock_data_row + 1

            elif (
                prediction_response is not None
                and self.benchmarking_mode.enabled
                and not self._rows_exceeded
            ):
                self._write_benchmark_results(
                    prediction_response,
                    bet_amount,
                )
                next_mock_data_row = self.synchronized_data.next_mock_data_row + 1

            payload = DecisionReceivePayload(
                self.context.agent_address,
                bets_hash,
                is_profitable,
                prediction_response.vote if prediction_response else None,
                prediction_response.confidence if prediction_response else None,
                bet_amount,
                next_mock_data_row,
            )

        yield from self.finish_behaviour(payload)
