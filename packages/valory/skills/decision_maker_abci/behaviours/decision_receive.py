# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2025 Valory AG
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
from datetime import datetime
from math import prod
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from packages.valory.skills.decision_maker_abci.behaviours.base import (
    remove_fraction_wei,
)
from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    StorageManagerBehaviour,
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
    QueueStatus,
)
from packages.valory.skills.mech_interact_abci.states.base import (
    MechInteractionResponse,
)


SLIPPAGE = 1.05
WRITE_TEXT_MODE = "w+t"
COMMA = ","
TOKEN_PRECISION = 10**18


class DecisionReceiveBehaviour(StorageManagerBehaviour):
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
    def review_bets_for_selling_mode(self) -> bool:
        """Get the review bets for selling mode."""
        return self.synchronized_data.review_bets_for_selling

    @property
    def mech_response(self) -> MechInteractionResponse:
        """Get the mech's response."""
        if self._mech_response is None:
            error = "The mech's response has not been set!"
            return MechInteractionResponse(error=error)
        return self._mech_response

    @property
    def is_invalid_response(self) -> bool:
        """Check if the response is invalid."""
        if self.mech_response.result is None:
            self.context.logger.warning(
                "Trying to check whether the mech's response is invalid but no response has been detected! "
                "Assuming invalid response."
            )
            return True
        return self.mech_response.result == self.params.mech_invalid_response

    def _next_dataset_row(self) -> Optional[Dict[str, str]]:
        """Read the next row from the input dataset which is used during the benchmarking mode.

        :return: a dictionary with the header fields mapped to the values of the first row.
            If no rows are left to process in the file, returns `None`.
        """
        sep = self.benchmarking_mode.sep
        dataset_filepath = (
            self.params.store_path / self.benchmarking_mode.dataset_filename
        )
        active_sampled_bet = self.get_active_sampled_bet()
        sampled_bet_id = active_sampled_bet.id

        # we have now one reader pointer per market
        available_rows_for_market = self.shared_state.bet_id_row_manager[sampled_bet_id]
        if available_rows_for_market:
            next_mock_data_row = available_rows_for_market[0]
        else:
            # no more bets available for this market
            msg = f"No more mock responses for the market with id: {sampled_bet_id}"
            self.sampled_bet.queue_status = QueueStatus.BENCHMARKING_DONE
            self.context.logger.info(msg)
            self.shared_state.last_benchmarking_has_run = True
            self._rows_exceeded = True
            return None

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
            self.context.logger.info("The mech response is None")
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
        opposite_vote = bet.opposite_vote(vote)
        other_tokens_in_pool = token_amounts[opposite_vote]

        return selected_type_tokens_in_pool, other_tokens_in_pool

    def _compute_new_tokens_distribution(
        self,
        token_amounts: List[int],
        prices: List[float],
        net_bet_amount: int,
        vote: int,
    ) -> Tuple[int, int, int, int, int]:
        k = prod(token_amounts)
        self.context.logger.info(f"k: {k}")

        # the OMEN market trades an equal amount of the investment to each of the tokens in the pool
        # here we calculate the bet amount per pool's token
        bet_per_token = net_bet_amount / BINARY_N_SLOTS
        self.context.logger.info(f"Bet per token: {bet_per_token}")

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

        return (
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            other_shares,
            num_shares,
            available_shares,
        )

    def _calc_binary_shares(
        self, bet: Bet, net_bet_amount: int, vote: int
    ) -> Tuple[int, int]:
        """Calculate the claimed shares. This calculation only works for binary markets."""
        # calculate the pool's k (x*y=k)
        token_amounts = bet.outcomeTokenAmounts
        self.context.logger.info(f"Token amounts: {[x for x in token_amounts]}")

        # calculate the number of the traded tokens
        prices = bet.outcomeTokenMarginalPrices
        self.context.logger.info(f"Prices: {prices}")

        if prices is None:
            return 0, 0

        _, _, _, num_shares, available_shares = self._compute_new_tokens_distribution(
            token_amounts.copy(), prices, net_bet_amount, vote
        )

        return num_shares, available_shares

    def _update_market_liquidity(self) -> None:
        """Update the current market's liquidity information."""
        active_sampled_bet = self.get_active_sampled_bet()
        question_id = active_sampled_bet.id
        # check if share state information is empty and we need to initialize
        empty_dict = len(self.shared_state.liquidity_amounts) == 0
        new_market = question_id not in self.shared_state.liquidity_amounts.keys()
        if empty_dict or new_market:
            self.shared_state.current_liquidity_amounts = (
                active_sampled_bet.outcomeTokenAmounts
            )
            self.shared_state.current_liquidity_prices = (
                active_sampled_bet.outcomeTokenMarginalPrices
            )
            self.shared_state.liquidity_cache[
                question_id
            ] = active_sampled_bet.scaledLiquidityMeasure

    def _calculate_new_liquidity(self, net_bet_amount: int, vote: int) -> LiquidityInfo:
        """Calculate and return the new liquidity information."""
        token_amounts = self.shared_state.current_liquidity_amounts
        k = prod(token_amounts)
        prices = self.shared_state.current_liquidity_prices

        (
            selected_type_tokens_in_pool,
            other_tokens_in_pool,
            other_shares,
            _,
            _,
        ) = self._compute_new_tokens_distribution(
            token_amounts.copy(), prices, net_bet_amount, vote
        )

        new_other = other_tokens_in_pool + other_shares
        new_selected = int(k / new_other)
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

    def _compute_scaled_liquidity_measure(
        self, token_amounts: List[int], token_prices: List[float]
    ) -> float:
        """Function to compute the scaled liquidity measure from token amounts and prices."""
        return (
            sum(amount * price for amount, price in zip(token_amounts, token_prices))
            / TOKEN_PRECISION
        )

    def _update_liquidity_info(self, net_bet_amount: int, vote: int) -> LiquidityInfo:
        """Update the liquidity information at shared state and the prices after placing a bet for a market."""
        liquidity_info = self._calculate_new_liquidity(net_bet_amount, vote)
        l0_start, l1_start = liquidity_info.validate_start_information()

        # to compute the new price we need the previous constants
        prices = self.shared_state.current_liquidity_prices

        liquidity_constants = [
            l0_start * prices[0],
            l1_start * prices[1],
        ]
        active_sampled_bet = self.get_active_sampled_bet()
        market_id = active_sampled_bet.id
        self.shared_state.current_liquidity_prices = liquidity_info.get_new_prices(
            liquidity_constants
        )
        self.shared_state.current_liquidity_amounts = liquidity_info.get_end_liquidity()
        log_message = (
            f"New liquidity amounts: {self.shared_state.current_liquidity_amounts}"
        )
        self.context.logger.info(log_message)

        # update the scaled liquidity Measure
        self.shared_state.liquidity_cache[
            market_id
        ] = self._compute_scaled_liquidity_measure(
            self.shared_state.current_liquidity_amounts,
            self.shared_state.current_liquidity_prices,
        )

        return liquidity_info

    def rebet_allowed(
        self, prediction_response: PredictionResponse, potential_net_profit: int
    ) -> bool:
        """Whether a rebet is allowed or not."""
        # WARNING: Every time you call self.sampled_bet a reset in self.bets is done so any changes there will be lost
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

        if self.benchmarking_mode.enabled:
            bet = self.get_active_sampled_bet()  # no reset
            self.context.logger.info(f"Bet used for benchmarking: {bet}")
            self._update_market_liquidity()
        else:
            # this call is destroying what it was in self.bets
            bet = self.sampled_bet

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
        if is_profitable:
            is_profitable = self.rebet_allowed(
                prediction_response, potential_net_profit
            )

        if self.benchmarking_mode.enabled:
            if is_profitable:
                # update the information at the shared state
                liquidity_info = self._update_liquidity_info(
                    net_bet_amount, prediction_response.vote
                )
                bet.outcomeTokenAmounts = self.shared_state.current_liquidity_amounts
                bet.outcomeTokenMarginalPrices = (
                    self.shared_state.current_liquidity_prices
                )
                bet.scaledLiquidityMeasure = self.shared_state.liquidity_cache[bet.id]
                self.store_bets()
                self._write_benchmark_results(
                    prediction_response, bet_amount, liquidity_info
                )
            else:
                self._write_benchmark_results(prediction_response)

            self.context.logger.info("Increasing Mech call count by 1")
            self.shared_state.benchmarking_mech_calls += 1

        return is_profitable, bet_amount

    def _update_selected_bet(
        self, prediction_response: Optional[PredictionResponse]
    ) -> None:
        """Update the selected bet."""
        # update the bet's timestamp of processing and its number of bets for the given id
        active_sampled_bet = self.get_active_sampled_bet()
        active_sampled_bet.processed_timestamp = (
            self.shared_state.get_simulated_now_timestamp(
                self.bets, self.params.safe_voting_range
            )
        )
        self.context.logger.info(f"Updating bet id: {active_sampled_bet.id}")
        self.context.logger.info(
            f"with the timestamp:{datetime.fromtimestamp(active_sampled_bet.processed_timestamp)}"
        )

        active_sampled_bet.update_investments(active_sampled_bet.invested_amount)

        self.store_bets()

    def should_sell_outcome_tokens(
        self, prediction_response: Optional[PredictionResponse]
    ) -> bool:
        """Whether the outcome tokens should be sold."""
        # self.bets is empty. Read from file
        self.read_bets()

        if prediction_response is None or prediction_response.vote is None:
            return False

        tokens_to_be_sold = self.sampled_bet.get_vote_amount(prediction_response.vote)

        current_time = datetime.now().timestamp()
        self.sampled_bet.set_processed_sell_check(int(current_time))

        if not tokens_to_be_sold:
            return False

        if prediction_response.confidence >= self.params.min_confidence_for_selling:
            self.sell_amount = tokens_to_be_sold
            return True
        return False

    def initialize_bet_id_row_manager(self) -> Dict[str, List[int]]:
        """Initialization of the dictionary used to traverse mocked tool responses."""
        bets_mapping: Dict[str, List[int]] = {}
        dataset_filepath = (
            self.params.store_path / self.benchmarking_mode.dataset_filename
        )

        with open(dataset_filepath, mode="r") as file:
            reader = csv.DictReader(file)
            for row_number, row in enumerate(reader, start=1):
                question_id = row[self.benchmarking_mode.question_id_field]
                if question_id not in bets_mapping:
                    bets_mapping[question_id] = []
                bets_mapping[question_id].append(row_number)
        return bets_mapping

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            success = yield from self._setup_policy_and_tools()
            if not success:
                return None

            prediction_response = self._get_decision()
            is_profitable = None
            bet_amount = None
            next_mock_data_row = None
            bets_hash = None
            decision_received_timestamp = None
            policy = None
            should_be_sold = False
            if prediction_response is not None and prediction_response.vote is not None:
                if (
                    self.review_bets_for_selling_mode
                    and self.should_sell_outcome_tokens(prediction_response)
                ):
                    self.context.logger.info(
                        "The bet response has changed, so we need to sell the outcome tokens"
                    )
                    should_be_sold = True
                    decision_received_timestamp = self.synced_timestamp
                    bet_amount = self.sell_amount
                    self.store_bets()
                    bets_hash = self.hash_stored_bets()

                if not should_be_sold and not self.review_bets_for_selling_mode:
                    self.context.logger.info(
                        "Not selling. Checking if the bet is profitable"
                    )
                    is_profitable, bet_amount = yield from self._is_profitable(
                        prediction_response
                    )
                    decision_received_timestamp = self.synced_timestamp
                    if is_profitable:
                        self.store_bets()
                        bets_hash = self.hash_stored_bets()

            elif (
                prediction_response is not None
                and self.benchmarking_mode.enabled
                and not self._rows_exceeded
            ):
                self._write_benchmark_results(
                    prediction_response,
                    bet_amount,
                )
                self.context.logger.info("Increasing Mech call count by 1")
                self.shared_state.benchmarking_mech_calls += 1

            if prediction_response is not None:
                self.policy.tool_responded(
                    self.synchronized_data.mech_tool,
                    self.synced_timestamp,
                    self.is_invalid_response,
                )
                policy = self.policy.serialize()

            # always remove the processed trade from the benchmarking input file
            # now there is one reader pointer per market
            if self.benchmarking_mode.enabled:
                # always remove the processed trade from the benchmarking input file
                # now there is one reader pointer per market
                bet = self.get_active_sampled_bet()
                rows_queue = self.shared_state.bet_id_row_manager[bet.id]
                if rows_queue:
                    rows_queue.pop(0)

                self._update_selected_bet(prediction_response)

            vote = prediction_response.vote if prediction_response else None
            confidence = prediction_response.confidence if prediction_response else None

            if should_be_sold and self.review_bets_for_selling_mode and vote:
                # for selling we are returning vote that needs to be sold. i.e. the opposite vote
                vote = self.sampled_bet.opposite_vote(vote)

            payload = DecisionReceivePayload(
                self.context.agent_address,
                bets_hash,
                is_profitable,
                vote,
                confidence,
                bet_amount,
                next_mock_data_row,
                policy,
                decision_received_timestamp,
                should_be_sold,
            )

        self._store_all()
        yield from self.finish_behaviour(payload)
