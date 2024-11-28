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

"""This module contains the models for the skill."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)

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
from packages.valory.skills.abstract_round_abci.models import (
    SharedState as BaseSharedState,
)
from packages.valory.skills.abstract_round_abci.models import TypeCheckMixin
from packages.valory.skills.decision_maker_abci.policy import EGreedyPolicy
from packages.valory.skills.decision_maker_abci.redeem_info import Trade
from packages.valory.skills.decision_maker_abci.rounds import DecisionMakerAbciApp
from packages.valory.skills.market_manager_abci.models import (
    MarketManagerParams,
    Subgraph,
)
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
        self.liquidity_cache: Dict[str, float] = {}
        # latest liquidity information (only relevant to the benchmarking mode)
        self.liquidity_amounts: Dict[str, List[int]] = {}
        self.liquidity_prices: Dict[str, List[float]] = {}
        # whether this is the last run of the benchmarking mode
        self.last_benchmarking_has_run: bool = False

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


def nested_list_todict_workaround(
    kwargs: Dict,
    key: str,
) -> Dict:
    """Get a nested list from the kwargs and convert it to a dictionary."""
    values = list(kwargs.get(key, []))
    if len(values) == 0:
        raise ValueError(f"No {key!r} specified in agent's configurations: {kwargs}!")
    if any(not issubclass(type(nested_values), Iterable) for nested_values in values):
        _raise_incorrect_config(key, values)
    if any(len(nested_values) % 2 == 1 for nested_values in values):
        _raise_incorrect_config(key, values)
    return {value[0]: value[1] for value in values}


class DecisionMakerParams(MarketManagerParams, MechInteractParams):
    """Decision maker's parameters."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the parameters' object."""
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
        self.agent_registry_address: str = self._ensure(
            "agent_registry_address", kwargs, str
        )
        self.store_path: Path = self.get_store_path(kwargs)
        self.irrelevant_tools: set = set(self._ensure("irrelevant_tools", kwargs, list))
        self.tool_punishment_multiplier: int = self._ensure(
            "tool_punishment_multiplier", kwargs, int
        )
        self.contract_timeout: float = self._ensure("contract_timeout", kwargs, float)
        self.file_hash_to_strategies: Dict[
            str, List[str]
        ] = nested_list_todict_workaround(
            kwargs,
            "file_hash_to_strategies_json",
        )
        self.strategies_kwargs: Dict[str, List[Any]] = nested_list_todict_workaround(
            kwargs, "strategies_kwargs"
        )
        self.use_subgraph_for_redeeming = self._ensure(
            "use_subgraph_for_redeeming",
            kwargs,
            bool,
        )
        self.use_nevermined = self._ensure("use_nevermined", kwargs, bool)
        self.rpc_sleep_time: int = self._ensure("rpc_sleep_time", kwargs, int)
        self.mech_to_subscription_params: Dict[
            str, Any
        ] = nested_list_todict_workaround(
            kwargs,
            "mech_to_subscription_params",
        )
        self.service_endpoint = self._ensure("service_endpoint", kwargs, str)
        self.safe_voting_range = self._ensure("safe_voting_range", kwargs, int)
        self.rebet_chance = self._ensure("rebet_chance", kwargs, float)
        self.policy_store_update_offset = self._ensure(
            "policy_store_update_offset", kwargs, int
        )
        self.agent_balance_threshold: int = self._ensure(
            "agent_balance_threshold", kwargs, int
        )
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


class BenchmarkingMode(Model, TypeCheckMixin):
    """Configuration for the benchmarking mode."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the `BenchmarkingMode` object."""
        self.enabled: bool = self._ensure("enabled", kwargs, bool)
        self.native_balance: int = self._ensure("native_balance", kwargs, int)
        self.collateral_balance: int = self._ensure("collateral_balance", kwargs, int)
        self.mech_cost: int = self._ensure("mech_cost", kwargs, int)
        self.pool_fee: int = self._ensure("pool_fee", kwargs, int)
        self.outcome_token_amounts: List[int] = self._ensure(
            "outcome_token_amounts", kwargs, List[int]
        )
        self.outcome_token_marginal_prices: List[float] = self._ensure(
            "outcome_token_marginal_prices", kwargs, List[float]
        )
        self.sep: str = self._ensure("sep", kwargs, str)
        self.dataset_filename: Path = Path(
            self._ensure("dataset_filename", kwargs, str)
        )
        self.question_field: str = self._ensure("question_field", kwargs, str)
        self.question_id_field: str = self._ensure("question_id_field", kwargs, str)
        self.answer_field: str = self._ensure("answer_field", kwargs, str)
        self.p_yes_field_part: str = self._ensure("p_yes_field_part", kwargs, str)
        self.p_no_field_part: str = self._ensure("p_no_field_part", kwargs, str)
        self.confidence_field_part: str = self._ensure(
            "confidence_field_part", kwargs, str
        )
        # this is the mode for the p and confidence parts
        # if the flag is `True`, then the field parts are used as prefixes, otherwise as suffixes
        self.part_prefix_mode: bool = self._ensure("part_prefix_mode", kwargs, bool)
        self.bet_amount_field: str = self._ensure("bet_amount_field", kwargs, str)
        self.results_filename: Path = Path(
            self._ensure("results_filename", kwargs, str)
        )
        self.randomness: str = self._ensure("randomness", kwargs, str)
        super().__init__(*args, **kwargs)


class AccuracyInfoFields(Model, TypeCheckMixin):
    """Configuration which holds the accuracy information file's fieldnames."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the `AccuracyInfoFields` object."""
        self.tool: str = self._ensure("tool", kwargs, str)
        self.requests: str = self._ensure("requests", kwargs, str)
        self.accuracy: str = self._ensure("accuracy", kwargs, str)
        self.sep: str = self._ensure("sep", kwargs, str)
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
