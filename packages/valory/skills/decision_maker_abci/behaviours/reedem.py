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

"""This module contains the redeeming state of the decision-making abci app."""

import json
import time
from abc import ABC
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
from packages.valory.protocols.ledger_api import LedgerApiMessage
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload, get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    StorageManagerBehaviour,
)
from packages.valory.skills.decision_maker_abci.models import (
    MultisendBatch,
    RedeemingProgress,
)
from packages.valory.skills.decision_maker_abci.payloads import RedeemPayload
from packages.valory.skills.decision_maker_abci.redeem_info import (
    Condition,
    FPMM,
    Trade,
)
from packages.valory.skills.decision_maker_abci.states.bet_placement import (
    BetPlacementRound,
)
from packages.valory.skills.decision_maker_abci.states.redeem import RedeemRound
from packages.valory.skills.decision_maker_abci.states.sell_outcome_tokens import (
    SellOutcomeTokensRound,
)
from packages.valory.skills.market_manager_abci.graph_tooling.requests import (
    FetchStatus,
    MAX_LOG_SIZE,
    QueryingBehaviour,
)
from packages.valory.skills.market_manager_abci.graph_tooling.utils import (
    filter_claimed_conditions,
    get_condition_id_to_balances,
)


ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)
BLOCK_NUMBER_KEY = "number"
DEFAULT_TO_BLOCK = "latest"


class RedeemInfoBehaviour(StorageManagerBehaviour, QueryingBehaviour, ABC):
    """A behaviour responsible for building and handling the redeeming information."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a `RedeemInfo` object."""
        super().__init__(**kwargs)
        self.utilized_tools: Dict[str, str] = {}
        self.redeemed_condition_ids: Set[str] = set()
        self.payout_so_far: int = 0
        self.trades: Set[Trade] = set()
        self.earliest_block_number: int = 0

        # this is a mapping from condition id to amount
        # the purpose of this attribute is to rectify the claimable amount within a redeeming information object.
        # this adjustment is necessary because the redeeming information is generated based on a single trade
        # per condition or question.
        # consequently, the claimable amount must reflect the cumulative sum of claimable amounts
        # from all trades associated with it.
        self.claimable_amounts: Dict[HexBytes, int] = {}

    def setup(self) -> None:
        """Setup the behaviour"""
        super().setup()
        self.redeemed_condition_ids = self.synchronized_data.redeemed_condition_ids
        self.payout_so_far = self.synchronized_data.payout_so_far

    def _set_block_number(self, trade: Trade) -> Generator:
        """Set the block number of the given trade's market."""
        timestamp = trade.fpmm.creationTimestamp

        while True:
            block = yield from self._fetch_block_number(timestamp)
            if self._fetch_status != FetchStatus.IN_PROGRESS:
                break

        if self._fetch_status == FetchStatus.SUCCESS:
            block_number = block.get("id", "")
            if block_number.isdigit():
                self.earliest_block_number = int(block_number)

        self.context.logger.info(
            f"Chose block number {self.earliest_block_number!r} as closest to timestamp {timestamp!r}"
        )

    def _try_update_policy(self, tool: str, winning: bool) -> None:
        """Try to update the policy."""
        try:
            self.policy.update_accuracy_store(tool, winning)
        except KeyError:
            self.context.logger.warning(
                f"The stored utilized tools seem to be outdated as no {tool=} was found. "
                "The policy will not be updated. "
                "No action is required as this will be automatically resolved."
            )

    def _update_policy(self, update: Trade) -> None:
        """Update the policy."""
        # the mapping might not contain a tool for a bet placement because it might have happened on a previous run
        tool = self.utilized_tools.get(update.transactionHash, None)
        if tool is None:
            return

        # we try to avoid an ever-increasing dictionary of utilized tools by removing a tool when not needed anymore
        del self.utilized_tools[update.transactionHash]
        self._try_update_policy(tool, update.is_winning)

    def update_redeem_info(self, chunk: list) -> Generator:
        """Update the redeeming information using the given chunk."""
        trades_updates: Iterator[Trade] = (
            Trade(**trade)
            for trade in chunk
            if int(trade.get("fpmm", {}).get("answerFinalizedTimestamp", maxsize))
            <= self.synced_timestamp
        )

        is_first_update = True
        for update in trades_updates:
            self._update_policy(update)

            # do not use the information if position is not winning
            if not update.is_winning:
                continue

            if is_first_update:
                yield from self._set_block_number(update)
                is_first_update = False

            condition_id = update.fpmm.condition.id
            # If not in the trades, add it as is, along with its claimable amount
            if update not in self.trades:
                self.trades.add(update)
                self.claimable_amounts[condition_id] = update.claimable_amount
                continue

            # Find any matching object and combine them
            for unique_obj in self.trades:
                if update == unique_obj:
                    self.claimable_amounts[condition_id] += update.claimable_amount

        self.context.logger.info(self.policy.stats_report())


class RedeemBehaviour(RedeemInfoBehaviour):
    """Redeem the winnings."""

    matching_round = RedeemRound

    UTILIZED_TOOLS_PATH = "utilized_tools.json"

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self._claim_params_batch: list = []
        self._latest_block_number: Optional[int] = None
        self._finalized: bool = False
        self._already_resolved: bool = False
        self._payouts: Dict[str, int] = {}
        self._built_data: Optional[HexBytes] = None
        self._current_redeem_info: Optional[Trade] = None
        self._expected_winnings: int = 0
        self._history_hash: bytes = ZERO_BYTES
        self._claim_winnings_simulation_ok: bool = False

    @property
    def redeeming_progress(self) -> RedeemingProgress:
        """Get the redeeming check progress from the shared state."""
        return self.shared_state.redeeming_progress

    @redeeming_progress.setter
    def redeeming_progress(self, progress: RedeemingProgress) -> None:
        """Set the redeeming check progress in the shared state."""
        self.shared_state.redeeming_progress = progress

    @property
    def latest_block_number(self) -> int:
        """Get the latest block number."""
        if self._latest_block_number is None:
            error = "Attempting to retrieve the latest block number, but it hasn't been set yet."
            raise ValueError(error)
        return self._latest_block_number

    @latest_block_number.setter
    def latest_block_number(self, latest_block_number: str) -> None:
        """Set the latest block number."""
        try:
            self._latest_block_number = int(latest_block_number)
        except (TypeError, ValueError) as exc:
            error = f"{latest_block_number=} cannot be converted to a valid integer."
            raise ValueError(error) from exc

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
    def payouts_batch(self) -> Dict[str, int]:
        """Get the trades' transaction hashes mapped to payouts for the current market."""
        return self._payouts

    @payouts_batch.setter
    def payouts_batch(self, payouts: Dict[str, int]) -> None:
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
    def claim_params_batch(self) -> list:
        """Get the current batch of the claim parameters."""
        return self._claim_params_batch

    @claim_params_batch.setter
    def claim_params_batch(self, claim_params_batch: list) -> None:
        """Set the current batch of the claim parameters."""
        self._claim_params_batch = claim_params_batch

    @property
    def built_data(self) -> HexBytes:
        """Get the built transaction's data."""
        return self._built_data

    @built_data.setter
    def built_data(self, built_data: Union[str, bytes]) -> None:
        """Set the built transaction's data."""
        self._built_data = HexBytes(built_data)

    @property
    def claim_winnings_simulation_ok(self) -> bool:
        """Get whether the claim winnings simulation is ok."""
        return self._claim_winnings_simulation_ok

    @claim_winnings_simulation_ok.setter
    def claim_winnings_simulation_ok(self, claim_winnings_simulation_ok: bool) -> None:
        """Get whether the claim winnings simulation is ok."""
        self._claim_winnings_simulation_ok = claim_winnings_simulation_ok

    def _store_progress(self) -> None:
        """Store the redeeming progress."""
        self.redeeming_progress.trades = self.trades
        self.redeeming_progress.utilized_tools = self.utilized_tools
        self.redeeming_progress.policy = self.policy
        self.redeeming_progress.claimable_amounts = self.claimable_amounts
        self.redeeming_progress.earliest_block_number = self.earliest_block_number

    def _load_progress(self) -> None:
        """Load the redeeming progress."""
        self.trades = self.redeeming_progress.trades
        self.utilized_tools = self.redeeming_progress.utilized_tools
        self._policy = self.redeeming_progress.policy
        self.claimable_amounts = self.redeeming_progress.claimable_amounts
        self.earliest_block_number = self.redeeming_progress.earliest_block_number

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

        # truncate the trades, otherwise logs get too big
        trades_str = str(self.trades)[:MAX_LOG_SIZE]
        self.context.logger.info(f"Fetched redeeming information: {trades_str}")

    def _filter_trades(self) -> None:
        """Filter the trades, removing the redeemed condition ids."""
        redeemed_condition_ids = [
            condition_id.lower() for condition_id in self.redeemed_condition_ids
        ]
        self.trades = {
            trade
            for trade in self.trades
            if trade.fpmm.condition.id.hex().lower() not in redeemed_condition_ids
        }
        self.redeeming_progress.trades = self.trades

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

    def _get_latest_block(self) -> WaitableConditionType:
        """Get the latest block's timestamp."""
        ledger_api_response = yield from self.get_ledger_api_response(
            performative=LedgerApiMessage.Performative.GET_STATE,  # type: ignore
            ledger_callable="get_block",
            block_identifier=DEFAULT_TO_BLOCK,
            chain_id=self.params.mech_chain_id,
        )
        if ledger_api_response.performative != LedgerApiMessage.Performative.STATE:
            self.context.logger.error(f"Failed to get block: {ledger_api_response}")
            return False
        self.latest_block_number = ledger_api_response.state.body.get(BLOCK_NUMBER_KEY)
        return True

    def _check_already_redeemed_via_events(self) -> WaitableConditionType:
        """Check whether the condition ids have already been redeemed via events."""
        if len(self.trades) == 0:
            return True

        safe_address_lower = self.synchronized_data.safe_contract_address.lower()
        kwargs: Dict[str, Any] = {
            key: []
            for key in (
                "collateral_tokens",
                "parent_collection_ids",
                "condition_ids",
                "index_sets",
            )
        }
        for trade in self.trades:
            kwargs["collateral_tokens"].append(trade.fpmm.collateralToken)
            kwargs["parent_collection_ids"].append(ZERO_BYTES)
            kwargs["condition_ids"].append(trade.fpmm.condition.id)
            kwargs["index_sets"].append(trade.fpmm.condition.index_sets)

        if not self.redeeming_progress.check_started:
            self.redeeming_progress.check_from_block = self.earliest_block_number
            yield from self.wait_for_condition_with_sleep(self._get_latest_block)
            self.redeeming_progress.check_to_block = self.latest_block_number
            self.redeeming_progress.check_started = True

        n_retries = 0
        from_block = self.redeeming_progress.check_from_block
        batch_size = self.redeeming_progress.event_filtering_batch_size
        while from_block < self.redeeming_progress.check_to_block:
            max_to_block = from_block + batch_size
            to_block = min(max_to_block, self.redeeming_progress.check_to_block)
            result = yield from self._conditional_tokens_interact(
                contract_callable="check_redeemed",
                data_key="payouts",
                placeholder=get_name(RedeemBehaviour.payouts_batch),
                redeemer=safe_address_lower,
                from_block=from_block,
                to_block=to_block,
                timeout=self.params.contract_timeout,
                **kwargs,
            )

            if not result and n_retries == self.params.max_filtering_retries:
                err = "Skipping the redeeming round as the RPC is misbehaving."
                self.context.logger.error(err)
                return False

            if not result:
                n_retries += 1
                keep_fraction = 1 - self.params.reduce_factor
                reduced_batch_size = int(batch_size * keep_fraction)
                # ensure that the batch size is at least the minimum batch size
                batch_size = max(reduced_batch_size, self.params.minimum_batch_size)
                self.redeeming_progress.event_filtering_batch_size = batch_size
                self.context.logger.warning(
                    f"Repeating this call with a decreased batch size of {batch_size}."
                )

                continue

            self.redeeming_progress.payouts.update(self.payouts_batch)
            self.redeeming_progress.check_from_block = to_block
            from_block += batch_size

        return True

    def _check_already_redeemed_via_subgraph(self) -> WaitableConditionType:
        """Check whether the condition ids have already been redeemed via subgraph."""
        safe_address = self.synchronized_data.safe_contract_address.lower()
        from_timestamp, to_timestamp = 0.0, time.time()  # from beginning to now

        # get the trades
        trades = yield from self.fetch_trades(
            safe_address, from_timestamp, to_timestamp
        )
        if trades is None:
            return False

        # get the user's positions
        user_positions = yield from self.fetch_user_positions(safe_address)
        if user_positions is None:
            return False

        # process the positions
        payouts, unredeemed_raw = get_condition_id_to_balances(trades, user_positions)

        # filter out positions that are already claimed
        unredeemed = filter_claimed_conditions(
            unredeemed_raw, self.redeeming_progress.claimed_condition_ids
        )

        self.redeeming_progress.payouts = payouts
        self.redeeming_progress.unredeemed_trades = unredeemed

        return True

    def _check_already_redeemed(self) -> WaitableConditionType:
        """Check whether we have already redeemed for this bet."""
        if self.params.use_subgraph_for_redeeming:
            return self._check_already_redeemed_via_subgraph()

        return self._check_already_redeemed_via_events()

    def _clean_redeem_info(self) -> WaitableConditionType:
        """Clean the redeeming information based on whether any positions have already been redeemed."""
        if self.payout_so_far > 0:
            # filter the trades to avoid checking positions that we are already aware have been redeemed.
            self._filter_trades()

        success = yield from self._check_already_redeemed()
        if not success:
            return False

        payouts = self.redeeming_progress.payouts
        payouts_amount = sum(payouts.values())
        if payouts_amount > 0:
            self.redeemed_condition_ids |= set(payouts.keys())
            if self.params.use_subgraph_for_redeeming:
                self.payout_so_far = payouts_amount
            else:
                self.payout_so_far += payouts_amount

            # filter the trades again if new payouts have been found
            self._filter_trades()
            wxdai_amount = self.wei_to_native(self.payout_so_far)
            msg = f"The total payout so far has been {wxdai_amount} wxDAI."
            self.context.logger.info(msg)

        return True

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

    def _simulate_claiming(self) -> WaitableConditionType:
        """Check whether we have already claimed the winnings."""
        result = yield from self._realitio_interact(
            contract_callable="simulate_claim_winnings",
            data_key="data",
            placeholder=get_name(RedeemBehaviour.claim_winnings_simulation_ok),
            question_id=self.current_question_id,
            claim_params=self.redeeming_progress.claim_params,
            sender_address=self.synchronized_data.safe_contract_address,
        )
        return result

    def _build_claim_data(self) -> WaitableConditionType:
        """Prepare the safe tx to claim the winnings."""
        claim_params = self.redeeming_progress.claim_params
        if claim_params is None:
            self.context.logger.error(
                f"Cannot parse incorrectly formatted realitio `LogNewAnswer` events: {self.redeeming_progress.answered}"
            )
            return False

        result = yield from self._realitio_interact(
            contract_callable="build_claim_winnings",
            data_key="data",
            placeholder=get_name(RedeemBehaviour.built_data),
            question_id=self.current_question_id,
            claim_params=self.redeeming_progress.claim_params,
        )

        if not result:
            return False

        batch = MultisendBatch(
            to=self.params.realitio_address,
            data=HexBytes(self.built_data),
        )
        self.multisend_batches.append(batch)
        return True

    def get_claim_params(self) -> WaitableConditionType:
        """Get the claim params for the current question id."""
        if self.params.use_subgraph_for_redeeming:
            return self._get_claim_params_via_subgraph()

        return self._get_claim_params_via_events()

    def _get_claim_params_via_events(self) -> WaitableConditionType:
        """Get claim params using an RPC to get the events."""
        if not self.redeeming_progress.claim_started:
            self.redeeming_progress.claim_from_block = self.earliest_block_number
            self.redeeming_progress.claim_to_block = (
                self.redeeming_progress.check_to_block
            )
            self.redeeming_progress.claim_started = True

        n_retries = 0
        from_block = self.redeeming_progress.claim_from_block
        batch_size = self.redeeming_progress.event_filtering_batch_size
        while from_block < self.redeeming_progress.claim_to_block:
            max_to_block = from_block + batch_size
            to_block = min(max_to_block, self.redeeming_progress.claim_to_block)
            result = yield from self._realitio_interact(
                contract_callable="get_claim_params",
                data_key="answered",
                placeholder=get_name(RedeemBehaviour.claim_params_batch),
                from_block=from_block,
                to_block=to_block,
                question_id=self.current_question_id,
                timeout=self.params.contract_timeout,
            )

            if not result and n_retries == self.params.max_filtering_retries:
                err = "Skipping redeeming for the current position as the RPC is misbehaving."
                self.context.logger.error(err)
                return False

            if not result:
                n_retries += 1
                keep_fraction = 1 - self.params.reduce_factor
                batch_size = int(batch_size * keep_fraction)
                self.redeeming_progress.event_filtering_batch_size = batch_size
                self.context.logger.warning(
                    f"Repeating this call with a decreased batch size of {batch_size}."
                )
                continue

            self.redeeming_progress.answered.extend(self.claim_params_batch)
            self.redeeming_progress.claim_from_block = to_block
            from_block += batch_size

        return True

    def _get_claim_params_via_subgraph(self) -> WaitableConditionType:
        """Get claim params using a subgraph."""
        question_id_str = "0x" + self.current_question_id.hex()
        result = yield from self.fetch_claim_params(question_id_str)
        if not result:
            return False

        self.redeeming_progress.answered = result
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

    def _prepare_single_redeem(self) -> WaitableConditionType:
        """Prepare a multisend transaction for a single redeeming action."""
        yield from self.wait_for_condition_with_sleep(self._check_already_resolved)
        steps = []
        if not self.already_resolved:
            # 1. resolve the question if it hasn't been resolved yet
            steps.append(self._build_resolve_data)

        yield from self.wait_for_condition_with_sleep(self._get_history_hash)
        if not self.is_history_hash_null:
            # 2. claim the winnings if claiming has not been done yet
            if not self.redeeming_progress.claim_finished:
                success = yield from self.get_claim_params()
                if not success:
                    return False

                # simulate claiming to get the claim params
                success = yield from self._simulate_claiming()
                if not success:
                    return False

            if self.claim_winnings_simulation_ok:
                steps.append(self._build_claim_data)

        # 3. we always redeem the position
        steps.append(self._build_redeem_data)
        for build_step in steps:
            yield from self.wait_for_condition_with_sleep(build_step)

        return True

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

        if self.params.use_subgraph_for_redeeming:
            condition_id = redeem_candidate.fpmm.condition.id.hex().lower()
            if (
                condition_id not in self.redeeming_progress.unredeemed_trades
                or self.redeeming_progress.unredeemed_trades[condition_id] == 0
            ):
                return False

        # in case that the claimable amount is dust
        if self.is_dust:
            self.context.logger.info("Position's redeeming amount is dust.")
            return False

        if self.params.use_subgraph_for_redeeming:
            condition_id = redeem_candidate.fpmm.condition.id.hex().lower()
            if (
                condition_id not in self.redeeming_progress.unredeemed_trades
                or self.redeeming_progress.unredeemed_trades[condition_id] == 0
            ):
                return False

        success = yield from self._prepare_single_redeem()
        if not success:
            return False

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
            # we mark this condition id as being claimed.
            # once the transaction gets successfully through, it will be moved to
            # self.redeeming_progress.claiming_condition_ids, and will no longer be taken into
            # consideration. This is done to avoid cases where the subgraph is not up-to date
            # and the same condition id is returned multiple times.
            claiming_condition_id = redeem_candidate.fpmm.condition.id.hex()
            self.redeeming_progress.claiming_condition_ids.append(claiming_condition_id)

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
        path = self.params.store_path / self.UTILIZED_TOOLS_PATH
        with path.open("w") as f:
            json.dump(self.utilized_tools, f)

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        self._store_utilized_tools()
        yield from super().finish_behaviour(payload)

    def _setup_policy_and_tools(self) -> Generator[None, None, bool]:
        """Set up the policy and tools."""
        if self.synchronized_data.is_policy_set:
            self._policy = self.synchronized_data.policy
            self.mech_tools = self.synchronized_data.available_mech_tools
            return True
        status = yield from super()._setup_policy_and_tools()
        return status

    def _build_payload(self, redeem_tx_hex: Optional[str] = None) -> RedeemPayload:
        """Build the redeeming round's payload."""
        agent = self.context.agent_address
        tx_submitter = self.matching_round.auto_round_id()
        benchmarking_enabled = self.benchmarking_mode.enabled
        serialized_tools = json.dumps(self.mech_tools)
        policy = self.policy.serialize()
        utilized_tools = json.dumps(self.utilized_tools)
        condition_ids = json.dumps(list(self.redeemed_condition_ids))
        payout = self.payout_so_far
        return RedeemPayload(
            agent,
            tx_submitter,
            redeem_tx_hex,
            benchmarking_enabled,
            serialized_tools,
            policy,
            utilized_tools,
            condition_ids,
            payout,
        )

    def _benchmarking_act(self) -> RedeemPayload:
        """The act of the agent while running in benchmarking mode."""
        tool = self.synchronized_data.mech_tool
        winning = self.mock_data.is_winning
        self._try_update_policy(tool, winning)
        return self._build_payload()

    def _normal_act(self) -> Generator[None, None, Optional[RedeemPayload]]:
        """The act of the agent while running in normal mode."""
        if not self.redeeming_progress.check_started:
            yield from self._get_redeem_info()
            self._store_progress()
        else:
            msg = "Picking up progress from where it was left off before the timeout occurred."
            self.context.logger.info(msg)
            self._load_progress()

        if not self.redeeming_progress.check_finished:
            self.redeeming_progress.cleaned = yield from self._clean_redeem_info()

        serialized_tools = json.dumps(self.mech_tools)
        payload = RedeemPayload(self.context.agent_address, mech_tools=serialized_tools)
        if self.redeeming_progress.cleaned:
            redeem_tx_hex = yield from self._prepare_safe_tx()
            if redeem_tx_hex is not None:
                payload = self._build_payload(redeem_tx_hex)

        return payload

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            success = yield from self._setup_policy_and_tools()
            if not success:
                return

            payload: Optional[RedeemPayload]
            if self.benchmarking_mode.enabled:
                payload = self._benchmarking_act()
            else:
                # Checking if the last round that submitted the transaction was the bet placement round
                # If so, we need to update the bet transaction information, because the transaction was successful
                # tx settlement multiplexer assures transitions from Post transaction to Redeem round
                # only if the transaction was successful
                if (
                    self.synchronized_data.did_transact
                    and self.synchronized_data.tx_submitter
                    in (
                        BetPlacementRound.auto_round_id(),
                        SellOutcomeTokensRound.auto_round_id(),
                    )
                ):
                    self.update_bet_transaction_information()

                payload = yield from self._normal_act()
                if payload is None:
                    return

            self._store_all()

        yield from self.finish_behaviour(payload)
