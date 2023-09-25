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

import json
from abc import ABC
from collections import defaultdict
from sys import maxsize
from typing import Any, Dict, Generator, Iterator, List, Optional, Set, Union

from hexbytes import HexBytes
from web3.constants import HASH_ZERO

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
from packages.valory.skills.decision_maker_abci.payloads import RedeemPayload
from packages.valory.skills.decision_maker_abci.redeem_info import (
    Condition,
    FPMM,
    Trade,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    QueryingBehaviour,
)


ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)
DEFAULT_FROM_BLOCK = "earliest"


FromBlockMappingType = Dict[HexBytes, Union[int, str]]


class RedeemInfoBehaviour(DecisionMakerBaseBehaviour, QueryingBehaviour, ABC):
    """A behaviour responsible for building and handling the redeeming information."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a `RedeemInfo` object."""
        super().__init__(**kwargs)
        self.utilized_tools: Dict[str, int] = {}
        self.trades: Set[Trade] = set()

        # blocks in which the markets were created mapped to the corresponding condition ids
        self.from_block_mapping: FromBlockMappingType = defaultdict(
            lambda: DEFAULT_FROM_BLOCK
        )

        # this is a mapping from condition id to amount
        # the purpose of this attribute is to rectify the claimable amount within a redeeming information object.
        # this adjustment is necessary because the redeeming information is generated based on a single trade
        # per condition or question.
        # consequently, the claimable amount must reflect the cumulative sum of claimable amounts
        # from all trades associated with it.
        self.claimable_amounts: Dict[HexBytes, int] = {}

    @property
    def synced_timestamp(self) -> int:
        """Return the synchronized timestamp across the agents."""
        return int(self.round_sequence.last_round_transition_timestamp.timestamp())

    def setup(self) -> None:
        """Setup the behaviour"""
        self._policy = self.synchronized_data.policy
        self.utilized_tools = self.synchronized_data.utilized_tools

    def _set_block_number(self, trade: Trade) -> Generator:
        """Set the block number of the given trade's market."""
        timestamp = trade.fpmm.creationTimestamp

        while True:
            block = yield from self._fetch_block_number(timestamp)
            if self._fetch_status != FetchStatus.IN_PROGRESS:
                break

        condition_id = trade.fpmm.condition.id
        if self._fetch_status == FetchStatus.SUCCESS:
            block_number = block.get("id", "")
            if block_number.isdigit():
                self.from_block_mapping[condition_id] = int(block_number)

        self.context.logger.info(
            f"Chose block number {self.from_block_mapping[condition_id]!r} as closest to timestamp {timestamp!r}"
        )

    def _update_policy(self, update: Trade) -> None:
        """Update the policy."""
        claimable_xdai = self.wei_to_native(update.claimable_amount)
        # the mapping might not contain a tool for a bet placement because it might have happened on a previous run
        tool_index = self.utilized_tools.get(update.transactionHash, None)
        if tool_index is not None:
            # we try to avoid an ever-increasing dictionary of utilized tools by removing a tool when not needed anymore
            del self.utilized_tools[update.transactionHash]
            self.policy.add_reward(tool_index, claimable_xdai)

    def _stats_report(self) -> None:
        """Report policy statistics."""
        stats_report = "Policy statistics so far (only for resolved markets):\n"
        available_tools = self.synchronized_data.available_mech_tools
        for i, tool in enumerate(available_tools):
            stats_report += (
                f"{tool} tool:\n"
                f"\tTimes used: {self.policy.counts[i]}\n"
                f"\tReward rate: {self.policy.reward_rates[i]}\n"
            )
        best_tool = available_tools[self.policy.best_tool]
        stats_report += f"Best tool so far is {best_tool!r}."
        self.context.logger.info(stats_report)

    def update_redeem_info(self, chunk: list) -> Generator:
        """Update the redeeming information using the given chunk."""
        trades_updates: Iterator[Trade] = (
            Trade(**trade)
            for trade in chunk
            if int(trade.get("fpmm", {}).get("answerFinalizedTimestamp", maxsize))
            <= self.synced_timestamp
        )

        for update in trades_updates:
            self._update_policy(update)

            # do not use the information if position is not winning
            if not update.is_winning:
                continue

            condition_id = update.fpmm.condition.id
            # If not in the trades, add it as is, along with its corresponding block number and claimable amount
            if update not in self.trades:
                self.trades.add(update)
                yield from self._set_block_number(update)
                self.claimable_amounts[condition_id] = update.claimable_amount
                continue

            # Find any matching object and combine them
            for unique_obj in self.trades:
                if update == unique_obj:
                    self.claimable_amounts[condition_id] += update.claimable_amount

        if self.policy.has_updated:
            self._stats_report()


class RedeemBehaviour(RedeemInfoBehaviour):
    """Redeem the winnings."""

    matching_round = RedeemRound

    UTILIZED_TOOLS_PATH = "utilized_tools.json"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self._finalized: bool = False
        self._already_resolved: bool = False
        self._payouts: Dict[str, int] = {}
        self._built_data: Optional[HexBytes] = None
        self._current_redeem_info: Optional[Trade] = None
        self._expected_winnings: int = 0
        self._history_hash: bytes = ZERO_BYTES

    @property
    def current_redeem_info(self) -> Trade:
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
    def current_question_id(self) -> bytes:
        """Get the current question's id."""
        return self.current_fpmm.question.id

    @property
    def current_collateral_token(self) -> str:
        """Get the current collateral token."""
        return self.current_fpmm.collateralToken

    @property
    def current_condition_id(self) -> HexBytes:
        """Get the current condition id."""
        return self.current_condition.id

    @property
    def current_index_sets(self) -> List[int]:
        """Get the current index sets."""
        return self.current_condition.index_sets

    @property
    def current_claimable_amount(self) -> int:
        """Return the current claimable amount."""
        return self.claimable_amounts[self.current_condition_id]

    @property
    def is_dust(self) -> bool:
        """Return whether the claimable amount of the given condition id is dust or not."""
        return self.current_claimable_amount < self.params.dust_threshold

    @property
    def payouts(self) -> Dict[str, int]:
        """Get the trades' transaction hashes mapped to payouts for the current market."""
        return self._payouts

    @payouts.setter
    def payouts(self, payouts: Dict[str, int]) -> None:
        """Set the trades' transaction hashes mapped to payouts for the current market."""
        self._payouts = payouts

    @property
    def finalized(self) -> bool:
        """Get whether the current market has been finalized."""
        return self._finalized

    @finalized.setter
    def finalized(self, flag: bool) -> None:
        """Set whether the current market has been finalized."""
        self._finalized = flag

    @property
    def history_hash(self) -> bytes:
        """Get the history hash for the current question."""
        return self._history_hash

    @history_hash.setter
    def history_hash(self, history_hash: bytes) -> None:
        """Set the history hash for the current question."""
        self._history_hash = history_hash

    @property
    def is_history_hash_null(self) -> bool:
        """Return whether the current history hash is null."""
        return self.history_hash == b"\x00" * 32

    @property
    def already_resolved(self) -> bool:
        """Get whether the current market has already been resolved."""
        return self._already_resolved

    @already_resolved.setter
    def already_resolved(self, flag: bool) -> None:
        """Set whether the current market has already been resolved."""
        self._already_resolved = flag

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
                yield from self.update_redeem_info(trades_market_chunk)

        self.context.logger.info(f"Fetched redeeming information: {self.trades}")

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
        if len(self.trades) == 0:
            return True

        kwargs: Dict[str, Any] = {
            key: []
            for key in (
                "collateral_tokens",
                "parent_collection_ids",
                "condition_ids",
                "index_sets",
                "from_block_numbers",
            )
        }
        for trade in self.trades:
            kwargs["collateral_tokens"].append(trade.fpmm.collateralToken)
            kwargs["parent_collection_ids"].append(ZERO_BYTES)
            kwargs["condition_ids"].append(trade.fpmm.condition.id)
            kwargs["index_sets"].append(trade.fpmm.condition.index_sets)

        kwargs["from_block_numbers"] = self.from_block_mapping

        safe_address_lower = self.synchronized_data.safe_contract_address.lower()
        result = yield from self._conditional_tokens_interact(
            contract_callable="check_redeemed",
            data_key="payouts",
            placeholder=get_name(RedeemBehaviour.payouts),
            redeemer=safe_address_lower,
            **kwargs,
        )
        return result

    def _clean_redeem_info(self) -> Generator:
        """Clean the redeeming information based on whether any positions have already been redeemed."""
        yield from self.wait_for_condition_with_sleep(self._check_already_redeemed)
        payout_so_far = sum(self.payouts.values())
        if payout_so_far > 0:
            self.trades = {
                trade
                for trade in self.trades
                if trade.fpmm.condition.id not in self.payouts.keys()
            }
            msg = f"The total payout so far has been {self.wei_to_native(payout_so_far)} wxDAI."
            self.context.logger.info(msg)

    def _realitio_interact(
        self, contract_callable: str, data_key: str, placeholder: str, **kwargs: Any
    ) -> WaitableConditionType:
        """Interact with the realitio contract."""
        status = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.realitio_address,
            contract_public_id=RealitioContract.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _check_finalized(self) -> WaitableConditionType:
        """Check whether the question has been finalized."""
        result = yield from self._realitio_interact(
            contract_callable="check_finalized",
            data_key="finalized",
            placeholder=get_name(RedeemBehaviour.finalized),
            question_id=self.current_question_id,
        )
        return result

    def _get_history_hash(self) -> WaitableConditionType:
        """Get the history hash for the current question id."""
        result = yield from self._realitio_interact(
            contract_callable="get_history_hash",
            data_key="data",
            placeholder=get_name(RedeemBehaviour.history_hash),
            question_id=self.current_question_id,
        )
        return result

    def _check_already_resolved(self) -> WaitableConditionType:
        """Check whether someone has already resolved for this market."""
        result = yield from self._conditional_tokens_interact(
            contract_callable="check_resolved",
            data_key="resolved",
            placeholder=get_name(RedeemBehaviour.already_resolved),
            condition_id=self.current_condition_id,
        )
        return result

    def _build_resolve_data(self) -> WaitableConditionType:
        """Prepare the safe tx to resolve the condition."""
        result = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.realitio_proxy_address,
            contract_public_id=RealitioProxyContract.contract_id,
            contract_callable="build_resolve_tx",
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
        result = yield from self._realitio_interact(
            contract_callable="build_claim_winnings",
            data_key="data",
            placeholder=get_name(RedeemBehaviour.built_data),
            from_block=self.from_block_mapping[self.current_condition_id],
            question_id=self.current_question_id,
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
            contract_callable="build_redeem_positions_tx",
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

    def _prepare_single_redeem(self) -> Generator:
        """Prepare a multisend transaction for a single redeeming action."""
        yield from self.wait_for_condition_with_sleep(self._check_already_resolved)
        steps = []
        if not self.already_resolved:
            # 1. resolve the question if it hasn't been resolved yet
            steps.append(self._build_resolve_data)

        yield from self.wait_for_condition_with_sleep(self._get_history_hash)
        if not self.is_history_hash_null:
            # 2. claim the winnings if claiming has not been done yet
            steps.append(self._build_claim_data)

        # 3. we always redeem the position
        steps.append(self._build_redeem_data)
        for build_step in steps:
            yield from self.wait_for_condition_with_sleep(build_step)

    def _process_candidate(
        self, redeem_candidate: Trade
    ) -> Generator[None, None, bool]:
        """Process a redeeming candidate and return whether winnings were found."""
        self._current_redeem_info = redeem_candidate

        msg = f"Processing position with condition id {self.current_condition_id!r}..."
        self.context.logger.info(msg)

        # double check whether the market is finalized
        yield from self.wait_for_condition_with_sleep(self._check_finalized)
        if not self.finalized:
            self.context.logger.warning(
                f"Conflict found! The current market, with condition id {self.current_condition_id!r}, "
                f"is reported as not finalized by the realitio contract. "
                f"However, an answer was finalized on {redeem_candidate.fpmm.answerFinalizedTimestamp}, "
                f"and the last service transition occurred on {self.synced_timestamp}."
            )
            return False

        # in case that the claimable amount is dust
        if self.is_dust:
            self.context.logger.info("Position's redeeming amount is dust.")
            return False

        yield from self._prepare_single_redeem()
        self._expected_winnings += self.current_claimable_amount
        return True

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
        if len(self.trades) > 0:
            self.context.logger.info("Preparing a multisend tx to redeem payout...")

        winnings_found = 0

        for redeem_candidate in self.trades:
            is_claimable = yield from self._process_candidate(redeem_candidate)
            if not is_claimable:
                msg = "Not redeeming position. Moving to the next one..."
                self.context.logger.info(msg)
                continue

            if self.params.redeeming_batch_size > 1:
                self.context.logger.info("Adding position to the multisend batch...")

            winnings_found += 1

            if winnings_found == self.params.redeeming_batch_size:
                break

        if winnings_found == 0:
            self.context.logger.info("No winnings to redeem.")
            return None

        winnings = self.wei_to_native(self._expected_winnings)
        self.context.logger.info(
            "Preparing the multisend transaction to redeem winnings of "
            f"{winnings} wxDAI for {winnings_found} position(s)."
        )
        for build_step in (
            self._build_multisend_data,
            self._build_multisend_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(build_step)

        self.context.logger.info("Transaction successfully prepared.")
        return self.tx_hex

    def _store_utilized_tools(self) -> None:
        """Store the tools utilized by the behaviour."""
        path = self.params.policy_store_path / self.UTILIZED_TOOLS_PATH
        with path.open("w") as f:
            json.dump(self.utilized_tools, f)

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self._get_redeem_info()
            yield from self._clean_redeem_info()
            agent = self.context.agent_address
            redeem_tx_hex = yield from self._prepare_safe_tx()
            tx_submitter = policy = utilized_tools = None
            if redeem_tx_hex is not None:
                tx_submitter = self.matching_round.auto_round_id()
                policy = self.policy.serialize()
                utilized_tools = json.dumps(self.utilized_tools)

            payload = RedeemPayload(
                agent, tx_submitter, redeem_tx_hex, policy, utilized_tools
            )
        self._store_utilized_tools()
        yield from self.finish_behaviour(payload)
