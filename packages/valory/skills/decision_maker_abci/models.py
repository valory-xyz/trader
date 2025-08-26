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

"""This module contains the models for the skill."""

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union, cast

from aea.exceptions import enforce
from aea.skills.base import Model, SkillContext
from hexbytes import HexBytes
from web3.constants import HASH_ZERO
from web3.types import BlockIdentifier

from packages.valory.contracts.multisend.contract import MultiSendOperation
from packages.valory.skills.abstract_round_abci.base import AbciApp
from packages.valory.skills.abstract_round_abci.models import ApiSpecs
from packages.valory.skills.abstract_round_abci.models import (
    BenchmarkTool as BaseBenchmarkTool,
)
from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
from packages.valory.skills.abstract_round_abci.models import TypeCheckMixin
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.decision_maker_abci.redeem_info import Trade
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.market_manager_abci.bets import Bet
from packages.valory.skills.market_manager_abci.models import MarketManagerParams
from packages.valory.skills.market_manager_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.market_manager_abci.models import Subgraph
from packages.valory.skills.mech_interact_abci.models import (
    Params as MechInteractParams,
)


FromBlockMappingType = Dict[HexBytes, Union[int, str]]
ClaimParamsType = Tuple[List[bytes], List[str], List[int], List[bytes]]


RE_CONTENT_IN_BRACKETS = r"\{([^}]*)\}"
REQUIRED_BET_TEMPLATE_KEYS = {"yes", "no", "question"}
DEFAULT_FROM_BLOCK = "earliest"
ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)
STRATEGY_KELLY_CRITERION = "kelly_criterion"
L0_START_FIELD = "l0_start"
L1_START_FIELD = "l1_start"
L0_END_FIELD = "l0_end"
L1_END_FIELD = "l1_end"
YES = "yes"
NO = "no"

CHATUI_PARAM_STORE = "chatui_param_store.json"


class PromptTemplate(Template):
    """A prompt template."""

    delimiter = "@"


Requests = BaseRequests
BenchmarkTool = BaseBenchmarkTool


@dataclass
class LiquidityInfo:
    """The structure to have liquidity information before and after a bet is done"""

    # Liquidity of tokens for option 0, before placing the bet
    l0_start: Optional[int] = None
    # Liquidity of tokens for option 1, before placing the bet
    l1_start: Optional[int] = None
    # Liquidity of tokens for option 0, after placing the bet
    l0_end: Optional[int] = None
    # Liquidity of tokens for option 1, after placing the bet
    l1_end: Optional[int] = None

    def validate_start_information(self) -> Tuple[int, int]:
        """Check if the start liquidity information is complete, otherwise raise an error."""
        if self.l0_start is None or self.l1_start is None:
            raise ValueError("The liquidity information is incomplete!")
        # return the values for type checking purposes (`mypy` would complain that they might be `None` otherwise)
        return self.l0_start, self.l1_start

    def validate_end_information(self) -> Tuple[int, int]:
        """Check if the end liquidity information is complete, otherwise raise an error."""
        if self.l0_end is None or self.l1_end is None:
            raise ValueError("The liquidity information is incomplete!")
        # return the values for type checking purposes (`mypy` would complain that they might be `None` otherwise)
        return self.l0_end, self.l1_end

    def get_new_prices(self, liquidity_constants: List[float]) -> List[float]:
        """Calculate and return the new prices based on the end liquidity and the liquidity constants of the market."""
        l0_end, l1_end = self.validate_end_information()
        new_p0 = liquidity_constants[0] / l0_end
        new_p1 = liquidity_constants[1] / l1_end
        return [new_p0, new_p1]

    def get_end_liquidity(self) -> List[int]:
        """Return the end liquidity."""
        l0_end, l1_end = self.validate_end_information()
        return [l0_end, l1_end]


@dataclass
class RedeemingProgress:
    """A structure to keep track of the redeeming check progress."""

    trades: Set[Trade] = field(default_factory=set)
    utilized_tools: Dict[str, str] = field(default_factory=dict)
    policy: Optional[EGreedyPolicy] = None
    claimable_amounts: Dict[HexBytes, int] = field(default_factory=dict)
    earliest_block_number: int = 0
    event_filtering_batch_size: int = 0
    check_started: bool = False
    check_from_block: BlockIdentifier = "earliest"
    check_to_block: BlockIdentifier = "latest"
    cleaned: bool = False
    payouts: Dict[str, int] = field(default_factory=dict)
    unredeemed_trades: Dict[str, int] = field(default_factory=dict)
    claim_started: bool = False
    claim_from_block: BlockIdentifier = "earliest"
    claim_to_block: BlockIdentifier = "latest"
    answered: list = field(default_factory=list)
    claiming_condition_ids: List[str] = field(default_factory=list)
    claimed_condition_ids: List[str] = field(default_factory=list)

    @property
    def check_finished(self) -> bool:
        """Whether the check has finished."""
        return self.check_started and self.check_from_block == self.check_to_block

    @property
    def claim_finished(self) -> bool:
        """Whether the claiming has finished."""
        return self.claim_started and self.claim_from_block == self.claim_to_block

    @property
    def claim_params(self) -> Optional[ClaimParamsType]:
        """The claim parameters, prepared for the `claimWinnings` call."""
        history_hashes = []
        addresses = []
        bonds = []
        answers = []
        try:
            for i, answer in enumerate(reversed(self.answered)):
                # history_hashes second-last-to-first, the hash of each history entry, calculated as described here:
                # https://realitio.github.io/docs/html/contract_explanation.html#answer-history-entries.
                if i == len(self.answered) - 1:
                    history_hashes.append(ZERO_BYTES)
                else:
                    history_hashes.append(self.answered[i + 1]["args"]["history_hash"])

                # last-to-first, the address of each answerer or commitment sender
                addresses.append(answer["args"]["user"])
                # last-to-first, the bond supplied with each answer or commitment
                bonds.append(answer["args"]["bond"])
                # last-to-first, each answer supplied, or commitment ID if the answer was supplied with commit->reveal
                answers.append(answer["args"]["answer"])
        except KeyError:
            return None

        return history_hashes, addresses, bonds, answers


@dataclass
class ChatUIParams:
    """Parameters for the chat UI."""

    trading_strategy: str
    initial_trading_strategy: str
    mech_tool: Optional[str] = None


class SharedState(BaseSharedState):
    """Keep the current shared state of the skill."""

    abci_app_cls: Type[AbciApp] = DecisionMakerAbciApp

    def __init__(self, *args: Any, skill_context: SkillContext, **kwargs: Any) -> None:
        """Initialize the state."""
        super().__init__(*args, skill_context=skill_context, **kwargs)
        self.redeeming_progress: RedeemingProgress = RedeemingProgress()
        self.strategy_to_filehash: Dict[str, str] = {}
        self.strategies_executables: Dict[str, Tuple[str, str]] = {}
        self.in_flight_req: bool = False
        self.req_to_callback: Dict[str, Callable] = {}
        self.mock_data: Optional[BenchmarkingMockData] = None
        # a mapping from market id to scaled liquidity measure
        # also used for the benchmarking mode
        self.liquidity_cache: Dict[str, float] = {}
        # list with the simulated timestamps for the benchmarking mode
        self.simulated_days: List[int] = []
        self.simulated_days_idx: int = 0
        # latest liquidity information (only relevant to the benchmarking mode)
        self.liquidity_amounts: Dict[str, List[int]] = {}
        self.liquidity_prices: Dict[str, List[float]] = {}
        # whether this is the last run of the benchmarking mode
        self.last_benchmarking_has_run: bool = False
        # the mapping from bet id to the row number in the dataset
        # the key is the market id/question_id
        self.bet_id_row_manager: Dict[str, List[int]] = {}
        # mech call counter for benchmarking behaviour
        self.benchmarking_mech_calls: int = 0
        # whether the code has detected the new mech marketplace being used
        self.new_mm_detected: Optional[bool] = None

        self._chat_ui_params: Optional["ChatUIParams"] = None

    @property
    def chat_ui_params(self) -> "ChatUIParams":
        """Get the chat UI parameters."""
        self._ensure_chatui_store()

        if self._chat_ui_params is None:
            raise ValueError("The chat UI parameters have not been set!")
        return self._chat_ui_params

    @property
    def mock_question_id(self) -> Any:
        """Get the mock question id."""
        mock_data = self.mock_data
        if mock_data is None:
            raise ValueError("The mock data have not been set!")
        return mock_data.id

    def _get_liquidity_info(
        self, liquidity_data: Union[Dict[str, List[int]], Dict[str, List[float]]]
    ) -> Any:
        """Get the current liquidity information from the given data."""
        _id = self.mock_question_id
        if _id not in liquidity_data:
            raise ValueError(
                f"There are no liquidity information for benchmarking mock data with question id {_id!r}."
            )
        return liquidity_data[_id]

    @property
    def current_liquidity_prices(self) -> List[float]:
        """Return the current liquidity prices."""
        return self._get_liquidity_info(self.liquidity_prices)

    @current_liquidity_prices.setter
    def current_liquidity_prices(self, value: List[float]) -> None:
        """Set the current liquidity prices."""
        self.liquidity_prices[self.mock_question_id] = value

    @property
    def current_liquidity_amounts(self) -> List[int]:
        """Return the current liquidity amounts."""
        return self._get_liquidity_info(self.liquidity_amounts)

    @current_liquidity_amounts.setter
    def current_liquidity_amounts(self, value: List[int]) -> None:
        """Set the current liquidity amounts."""
        self.liquidity_amounts[self.mock_question_id] = value

    def _initialize_simulated_now_timestamps(
        self, bets: List[Bet], safe_voting_range: int
    ) -> None:
        """Creates the list of simulated days for the benchmarking mode"""
        self.simulated_days_idx = 0
        # Find the maximum timestamp from openingTimestamp field
        max_timestamp = max(bet.openingTimestamp for bet in bets)
        # adding some time range to allow voting
        # in the sampling round the within_safe condition is designed to check
        # the openingtimestamp of the market strickly less than the safe voting range
        # so we need to create a timestamp that passes this condition for the max openingtimestamp
        max_timestamp = max_timestamp - safe_voting_range - 1

        # Get current timestamp
        now_timestamp = int(time.time())
        # Convert timestamps to datetime objects
        max_date = datetime.fromtimestamp(max_timestamp)
        current_date = datetime.fromtimestamp(now_timestamp)
        self.context.logger.info(
            f"Simulating timestamps between {current_date} and {max_date}"
        )
        # Generate list of timestamps with one day intervals
        timestamps = []
        while current_date <= max_date:
            timestamps.append(int(current_date.timestamp()))
            current_date += timedelta(days=1)
        self.context.logger.info(f"Simulated timestamps: {timestamps}")
        self.simulated_days = timestamps

    def increase_one_day_simulation(self) -> None:
        """Increased the index used for the current simulated day."""
        self.simulated_days_idx += 1

    def check_benchmarking_finished(self) -> bool:
        """Checks if we simulated already all days."""
        return self.simulated_days_idx >= len(self.simulated_days)

    def get_simulated_now_timestamp(
        self, bets: List[Bet], safe_voting_range: int
    ) -> int:
        """Gets the current simulated day timestamp."""
        if len(self.simulated_days) == 0:
            self._initialize_simulated_now_timestamps(bets, safe_voting_range)

        return self.simulated_days[self.simulated_days_idx]

    def setup(self) -> None:
        """Set up the model."""
        super().setup()
        params = self.context.params
        self.redeeming_progress.event_filtering_batch_size = (
            params.event_filtering_batch_size
        )
        self.strategy_to_filehash = {
            value: key
            for key, values in params.file_hash_to_strategies.items()
            for value in values
        }
        selected_strategy = params.trading_strategy
        strategy_exec = self.strategy_to_filehash.keys()
        if selected_strategy not in strategy_exec:
            raise ValueError(
                f"The selected trading strategy {selected_strategy} "
                f"is not in the strategies' executables {strategy_exec}."
            )

    def _get_current_json_store(self) -> Dict[str, Any]:
        """Get the current store."""
        chatui_store_path = self.context.params.store_path / CHATUI_PARAM_STORE
        try:
            if os.path.exists(chatui_store_path):
                with open(chatui_store_path, "r") as f:
                    current_store: dict = json.load(f)
            else:
                current_store = {}
        except (FileNotFoundError, json.JSONDecodeError):
            current_store = {}
        return current_store

    def _set_json_store(self, store: Dict[str, Any]) -> None:
        """Set the store with the chat UI parameters."""
        chatui_store_path = self.context.params.store_path / CHATUI_PARAM_STORE

        with open(chatui_store_path, "w") as f:
            json.dump(store, f, indent=4)

    def _ensure_chatui_store(self) -> None:
        """Ensure that the chat UI store is set up correctly."""

        if self._chat_ui_params is not None:
            return

        current_store = self._get_current_json_store()

        # Trading strategy
        trading_strategy_yaml = self.context.params.trading_strategy

        trading_strategy_store = current_store.get("trading_strategy", None)
        initial_trading_strategy_store = current_store.get(
            "initial_trading_strategy", None
        )

        if trading_strategy_store is None or not isinstance(
            trading_strategy_store, str
        ):
            current_store["trading_strategy"] = trading_strategy_yaml

        if initial_trading_strategy_store is None or not isinstance(
            initial_trading_strategy_store, str
        ):
            current_store["initial_trading_strategy"] = trading_strategy_yaml

        # This is to ensure that changes made in the YAML file
        # are reflected in the store.
        if initial_trading_strategy_store != trading_strategy_yaml:
            # update the store with the YAML value
            current_store["trading_strategy"] = trading_strategy_yaml
            current_store["initial_trading_strategy"] = trading_strategy_yaml

        self._set_json_store(current_store)

        self._chat_ui_params = ChatUIParams(**current_store)


def extract_keys_from_template(delimiter: str, template: str) -> Set[str]:
    """Extract the keys from a string template, given the delimiter."""
    # matches the placeholders of the template's keys
    pattern = re.escape(delimiter) + RE_CONTENT_IN_BRACKETS
    keys = re.findall(pattern, template)
    return set(keys)


def check_prompt_template(bet_prompt_template: PromptTemplate) -> None:
    """Check if the keys required for a bet are given in the provided prompt's template."""
    delimiter = bet_prompt_template.delimiter
    template_keys = extract_keys_from_template(delimiter, bet_prompt_template.template)
    if template_keys != REQUIRED_BET_TEMPLATE_KEYS:
        example_key = (REQUIRED_BET_TEMPLATE_KEYS - template_keys).pop()
        n_found = len(template_keys)
        found = "no keys" if n_found == 0 else f"keys {template_keys}"
        raise ValueError(
            f"The bet's template should contain exclusively the following keys: {REQUIRED_BET_TEMPLATE_KEYS}.\n"
            f"Found {found} instead in the given template:\n{bet_prompt_template.template!r}\n"
            f"Please make sure that you are using the right delimiter {delimiter!r} for the prompt's template.\n"
            f"For example, to parametrize {example_key!r} you may use "
            f"'{delimiter}{{{example_key}}}'"
        )


def _raise_incorrect_config(key: str, values: Any) -> None:
    """Raise a `ValueError` for incorrect configuration of a nested_list workaround."""
    raise ValueError(
        f"The given configuration for {key!r} is incorrectly formatted: {values}!"
        "The value is expected to be a list of lists that can be represented as a dictionary."
    )


class DecisionMakerParams(MarketManagerParams, MechInteractParams):
    """Decision maker's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""

        # do not pop the registry and metadata addresses, because they are also required for the `MechInteractParams`
        agent_registry_address: Optional[str] = kwargs.get(
            "agent_registry_address", None
        )
        enforce(
            agent_registry_address is not None,
            "Agent registry address not specified!",
        )
        agent_registry_address = cast(str, agent_registry_address)

        metadata_address: Optional[str] = kwargs.get(
            "complementary_service_metadata_address", None
        )
        enforce(
            metadata_address is not None,
            "Complementary service metadata address not specified!",
        )
        metadata_address = cast(str, metadata_address)

        # the number of days to sample bets from
        self.sample_bets_closing_days: int = self._ensure(
            "sample_bets_closing_days", kwargs, int
        )
        if self.sample_bets_closing_days <= 0:
            msg = "The number of days to sample bets from must be positive!"
            raise ValueError(msg)

        # the trading strategy to use for placing bets
        self.trading_strategy: str = self._ensure("trading_strategy", kwargs, str)
        self.use_fallback_strategy: bool = self._ensure(
            "use_fallback_strategy", kwargs, bool
        )
        self.tools_accuracy_hash: str = self._ensure("tools_accuracy_hash", kwargs, str)
        # the threshold amount in WEI starting from which we are willing to place a bet
        self.bet_threshold: int = self._ensure("bet_threshold", kwargs, int)
        self._prompt_template: str = self._ensure("prompt_template", kwargs, str)
        check_prompt_template(self.prompt_template)
        self.dust_threshold: int = self._ensure("dust_threshold", kwargs, int)
        self.conditional_tokens_address: str = self._ensure(
            "conditional_tokens_address", kwargs, str
        )
        self.realitio_proxy_address: str = self._ensure(
            "realitio_proxy_address", kwargs, str
        )
        self.realitio_address: str = self._ensure("realitio_address", kwargs, str)
        # this is the maximum batch size that will be used when filtering blocks for events.
        # increasing this number allows for faster filtering operations,
        # but also increases the chances of getting a timeout error from the RPC
        self.event_filtering_batch_size: int = self._ensure(
            "event_filtering_batch_size", kwargs, int
        )
        self.reduce_factor: float = self._ensure("reduce_factor", kwargs, float)
        # the minimum batch size for redeeming operations, this is added to avoid the batch size to be too small
        self.minimum_batch_size: int = self._ensure("minimum_batch_size", kwargs, int)
        self.max_filtering_retries: int = self._ensure(
            "max_filtering_retries", kwargs, int
        )
        # this is the max number of redeeming operations that will be batched on a single multisend transaction.
        # increasing this number equals fewer fees but more chances for the transaction to fail
        self.redeeming_batch_size: int = self._ensure(
            "redeeming_batch_size", kwargs, int
        )
        self.redeem_round_timeout: float = self._ensure(
            "redeem_round_timeout", kwargs, float
        )
        # a slippage in the range of [0, 1] to apply to the `minOutcomeTokensToBuy` when buying shares on a fpmm
        self._slippage: float = 0.0
        self.slippage: float = self._ensure("slippage", kwargs, float)
        self.epsilon: float = self._ensure("policy_epsilon", kwargs, float)
        self.agent_registry_address: str = agent_registry_address
        self.metadata_address: str = metadata_address
        self.store_path: Path = self.get_store_path(kwargs)
        self.irrelevant_tools: set = set(self._ensure("irrelevant_tools", kwargs, list))
        self.tool_punishment_multiplier: int = self._ensure(
            "tool_punishment_multiplier", kwargs, int
        )
        self.contract_timeout: float = self._ensure("contract_timeout", kwargs, float)
        self.file_hash_to_strategies: Dict[str, List[str]] = self._ensure(
            "file_hash_to_strategies", kwargs, Dict[str, List[str]]
        )
        self.strategies_kwargs: Dict[str, Any] = self._ensure(
            "strategies_kwargs", kwargs, Dict[str, Any]
        )
        self.use_subgraph_for_redeeming = self._ensure(
            "use_subgraph_for_redeeming",
            kwargs,
            bool,
        )
        self.use_nevermined = self._ensure("use_nevermined", kwargs, bool)
        self.rpc_sleep_time: int = self._ensure("rpc_sleep_time", kwargs, int)
        self.mech_to_subscription_params: Dict[str, str] = self._ensure(
            "mech_to_subscription_params",
            kwargs,
            Dict[str, str],
        )
        self.service_endpoint = self._ensure("service_endpoint", kwargs, str)
        self.safe_voting_range = self._ensure("safe_voting_range", kwargs, int)
        self.rebet_chance = self._ensure("rebet_chance", kwargs, float)
        self.policy_store_update_offset = self._ensure(
            "policy_store_update_offset", kwargs, int
        )
        self.expected_mech_response_time = self._ensure(
            "expected_mech_response_time", kwargs, int
        )
        self.mech_invalid_response: str = self._ensure(
            "mech_invalid_response", kwargs, str
        )
        self.policy_threshold: int = self._ensure(
            "mech_consecutive_failures_threshold", kwargs, int
        )
        self.tool_quarantine_duration: int = self._ensure(
            "tool_quarantine_duration", kwargs, int
        )
        self.enable_position_review: bool = self._ensure(
            "enable_position_review", kwargs, bool
        )
        self.review_period_seconds: int = self._ensure(
            "review_period_seconds", kwargs, int
        )
        self.min_confidence_for_selling: float = 0.5
        super().__init__(*args, **kwargs)

    @property
    def using_kelly(self) -> bool:
        """Get the max bet amount if the `bet_amount_per_conf_threshold` strategy is used."""
        return self.trading_strategy == STRATEGY_KELLY_CRITERION

    @property
    def prompt_template(self) -> PromptTemplate:
        """Get the prompt template as a string `PromptTemplate`."""
        return PromptTemplate(self._prompt_template)

    @property
    def slippage(self) -> float:
        """Get the slippage."""
        return self._slippage

    @slippage.setter
    def slippage(self, slippage: float) -> None:
        """Set the slippage."""
        if slippage < 0 or slippage > 1:
            raise ValueError(
                f"The configured slippage {slippage!r} is not in the range [0, 1]."
            )
        self._slippage = slippage

    def get_store_path(self, kwargs: Dict) -> Path:
        """Get the path of the store."""
        path = self._ensure("store_path", kwargs, str)
        # check if path exists, and we can write to it
        if (
            not os.path.isdir(path)
            or not os.access(path, os.W_OK)
            or not os.access(path, os.R_OK)
        ):
            raise ValueError(
                f"Policy store path {path!r} is not a directory or is not writable."
            )
        return Path(path)


class AccuracyInfoFields(Model, TypeCheckMixin):
    """Configuration which holds the accuracy information file's fieldnames."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the `AccuracyInfoFields` object."""
        self.tool: str = self._ensure("tool", kwargs, str)
        self.requests: str = self._ensure("requests", kwargs, str)
        self.accuracy: str = self._ensure("accuracy", kwargs, str)
        self.sep: str = self._ensure("sep", kwargs, str)
        self.max: str = self._ensure("max", kwargs, str)
        self.datetime_format: str = self._ensure("datetime_format", kwargs, str)
        super().__init__(*args, **kwargs)


class AgentToolsSpecs(ApiSpecs):
    """A model that wraps ApiSpecs for the Mech agent's tools specifications."""


@dataclass
class MultisendBatch:
    """A structure representing a single transaction of a multisend."""

    to: str
    data: HexBytes
    value: int = 0
    operation: MultiSendOperation = MultiSendOperation.CALL


@dataclass
class BenchmarkingMockData:
    """The mock data for a `BenchmarkingMode`."""

    id: str
    question: str
    answer: str
    p_yes: float

    @property
    def is_winning(self) -> bool:
        """Whether the current position is winning."""
        return (
            self.answer == YES
            and self.p_yes > 0.5
            or self.answer == NO
            and self.p_yes < 0.5
        )


class TradesSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the OMEN's subgraph specifications for trades."""


class ConditionalTokensSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Conditional Tokens' subgraph specifications."""


class RealitioSubgraph(Subgraph):
    """A model that wraps ApiSpecs for the Realitio's subgraph specifications."""
