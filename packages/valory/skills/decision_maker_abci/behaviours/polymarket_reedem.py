# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023-2026 Valory AG
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

from typing import Any, Generator, Optional, cast

from hexbytes import HexBytes
from web3.constants import HASH_ZERO

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.contracts.conditional_tokens.contract import (
    ConditionalTokensContract,
)
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    MultisendBatch,
)
from packages.valory.skills.decision_maker_abci.models import DecisionMakerParams
from packages.valory.skills.decision_maker_abci.payloads import PolymarketRedeemPayload
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_redeem import (
    PolymarketRedeemRound,
)


ZERO_HEX = HASH_ZERO[2:]
ZERO_BYTES = bytes.fromhex(ZERO_HEX)
BLOCK_NUMBER_KEY = "number"
DEFAULT_TO_BLOCK = "latest"

WaitableConditionType = Generator[None, None, bool]


class PolymarketRedeemBehaviour(DecisionMakerBaseBehaviour):
    """Redeem the winnings."""

    matching_round = PolymarketRedeemRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize `RedeemBehaviour`."""
        super().__init__(**kwargs)
        self._user_token_balance: Optional[int] = None

    @property
    def user_token_balance(self) -> Optional[int]:
        """Get the token balance."""
        return self._user_token_balance

    @user_token_balance.setter
    def user_token_balance(self, user_token_balance: Optional[int]) -> None:
        """Set the token balance."""
        self._user_token_balance = user_token_balance

    @property
    def params(self) -> DecisionMakerParams:
        """Return the params."""
        return cast(DecisionMakerParams, self.context.params)

    def _conditional_tokens_interact(
        self, contract_callable: str, data_key: str, placeholder: str, **kwargs: Any
    ) -> WaitableConditionType:
        """Interact with the conditional tokens contract."""
        status = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.params.polymarket_ctf_address,
            contract_public_id=ConditionalTokensContract.contract_id,
            contract_callable=contract_callable,
            data_key=data_key,
            placeholder=placeholder,
            **kwargs,
        )
        return status

    def _get_token_balance(self, token_id: int) -> Generator[None, None, Optional[int]]:
        """Get the ERC1155 token balance from CTF contract.

        :param token_id: The token ID to check balance for
        :return: Balance as integer, or None if error
        :yield: None
        """

        response_status = yield from self._conditional_tokens_interact(
            contract_callable="get_balance_of",
            placeholder=get_name(PolymarketRedeemBehaviour.user_token_balance),
            owner=self.synchronized_data.safe_contract_address.lower(),
            data_key="balance",
            position_id=token_id,
        )

        if not response_status:
            self.context.logger.error("Failed to get token balance from contract")
            return None

        return self.user_token_balance

    def _fetch_redeemable_positions(self) -> Generator[None, None, list]:
        """Fetch redeemable positions from Polymarket."""
        # Prepare payload data
        polymarket_bet_payload = {
            "request_type": RequestType.FETCH_ALL_POSITIONS.value,
            "params": {
                "redeemable": True,
            },
        }
        redeemable_positions = yield from self.send_polymarket_connection_request(
            polymarket_bet_payload
        )

        # Filter out positions with no redemption value (losing positions)
        # A position is only worth redeeming if currentValue > 0
        valuable_positions = []
        for position in redeemable_positions:
            current_value = position.get("currentValue", 0)
            size = position.get("size", 0)

            # Only include positions that have actual value to redeem
            # currentValue is the total value of the position in USD
            if current_value <= 0:
                self.context.logger.info(
                    f"Skipping worthless position {position.get('conditionId')} "
                    f"with value ${current_value:.2f} (size: {size})"
                )
                continue

            valuable_positions.append(position)

        return valuable_positions

    def _redeem_position(
        self,
        condition_id: str,
        outcome_index: int,
        collateral_token: str,
        is_neg_risk: bool = False,
        size: float = 0,
    ) -> Generator[None, None, dict]:
        """Redeem a single position.

        :param condition_id: The condition ID for the position
        :param outcome_index: The outcome index (0 for Yes, 1 for No typically)
        :param collateral_token: The collateral token address
        :param is_neg_risk: Whether this is a negative risk market
        :param size: The size of the position to redeem (for neg risk markets)
        :return: Redemption result
        :yield: None
        """
        # For negative risk markets, the connection expects different handling
        # The connection will need to be updated to support neg risk redemption
        # For now, we prepare the payload with neg_risk flag

        # Prepare redemption payload
        # index_sets should be calculated as 1 << outcome_index
        index_sets = [1 << outcome_index]

        polymarket_redeem_payload = {
            "request_type": RequestType.REDEEM_POSITIONS.value,
            "params": {
                "condition_id": condition_id,
                "index_sets": index_sets,
                "collateral_token": collateral_token,
                "is_neg_risk": is_neg_risk,
                "size": size,
            },
        }

        redeem_result = yield from self.send_polymarket_connection_request(
            polymarket_redeem_payload
        )

        return redeem_result

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            # Fetch redeemable positions once for both flows
            redeemable_positions = yield from self._fetch_redeemable_positions()
            self.context.logger.info(
                f"Fetched {len(redeemable_positions)} redeemable positions"
            )

            if redeemable_positions == []:
                self.context.logger.info("No redeemable positions found.")
                self.payload = PolymarketRedeemPayload(
                    sender=self.context.agent_address,
                    tx_submitter=None,
                    tx_hash=None,
                    mocking_mode=False,
                    event=Event.NO_REDEEMING.value,
                )
                yield from self.finish_behaviour(self.payload)
                return

            # Check if builder program is enabled
            if self.context.params.polymarket_builder_program_enabled:
                self.context.logger.info(
                    "Polymarket builder program enabled - calling connection to redeem positions..."
                )
                # Call the polymarket client to redeem positions
                yield from self._redeem_via_builder(redeemable_positions)
            else:
                self.context.logger.info(
                    "Polymarket builder program disabled - preparing redemption transaction..."
                )
                # Prepare Safe transaction for redemption
                tx_submitter = self.matching_round.auto_round_id()
                tx_hash = yield from self._prepare_redeem_tx(redeemable_positions)

                self.payload = PolymarketRedeemPayload(
                    sender=self.context.agent_address,
                    tx_submitter=tx_submitter,
                    tx_hash=tx_hash,
                    mocking_mode=False,
                    event=Event.PREPARE_TX.value,
                )

        yield from self.finish_behaviour(self.payload)

    def _redeem_via_builder(self, redeemable_positions: list) -> Generator:
        """Redeem positions via builder flow (connection request)."""

        # Redeem each position
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size", 0)
            is_neg_risk = position.get("negativeRisk", False)

            market_type = "negative risk" if is_neg_risk else "standard"
            self.context.logger.info(
                f"Redeeming {market_type} position: {condition_id} - {outcome} (size: {size})"
            )

            result = yield from self._redeem_position(
                condition_id=condition_id,
                outcome_index=outcome_index,
                collateral_token=self.params.polymarket_usdc_address,
                is_neg_risk=is_neg_risk,
                size=size,
            )

            self.context.logger.info(f"Redemption result for {condition_id}: {result}")

        self.payload = PolymarketRedeemPayload(
            sender=self.context.agent_address,
            tx_submitter=None,
            tx_hash=None,
            mocking_mode=False,
            event=Event.DONE.value,
        )

    def _get_token_balance_from_chain(
        self, token_id: int
    ) -> Generator[None, None, Optional[int]]:
        """Get token balance from the chain.

        :param token_id: The token ID to check balance for
        :return: Token balance as integer, or None if error
        :yield: None
        """
        balance = yield from self._get_token_balance(token_id)

        if balance is None:
            self.context.logger.error(
                f"Failed to get balance for token ID {token_id} from chain"
            )
            return None

        if balance == 0:
            self.context.logger.info(f"Token ID {token_id} has zero balance")
            return 0

        self.context.logger.info(f"Token ID {token_id} has balance: {balance}")

        return balance

    def _prepare_redeem_tx(
        self, redeemable_positions: list
    ) -> Generator[None, None, Optional[str]]:
        """Prepare Safe transaction for redeeming positions."""
        if not redeemable_positions:
            self.context.logger.info("No redeemable positions found")
            return ""

        # Build redemption transactions and add to multisend_batches
        for position in redeemable_positions:
            condition_id = position.get("conditionId")
            outcome_index = position.get("outcomeIndex")
            outcome = position.get("outcome")
            size = position.get("size", 0)
            is_neg_risk = position.get("negativeRisk", False)

            market_type = "negative risk" if is_neg_risk else "standard"
            self.context.logger.info(
                f"Preparing redeem tx for {market_type} position: {condition_id} - {outcome} (size: {size})"
            )

            # Build the redemption data based on market type
            if is_neg_risk:
                # For negative risk markets, query actual token balances from chain
                token_id = position.get("asset")
                if not token_id:
                    self.context.logger.error(
                        f"Missing asset (token ID) for position {condition_id}"
                    )
                    continue

                balance = yield from self._get_token_balance_from_chain(int(token_id))

                if balance is None or balance == 0:
                    self.context.logger.info(
                        f"Skipping redemption for {condition_id} due to zero balance"
                    )
                    continue

                # For neg risk, we need to query both Yes and No tokens
                # The outcome_index tells us which one this position is
                # We need to build amounts array [yes_amount, no_amount]
                redeem_amounts = [0, 0]
                redeem_amounts[outcome_index] = int(balance)

                redeem_data = self._build_redeem_neg_risk_data(
                    collateral_token=self.params.polymarket_usdc_address,
                    condition_id=condition_id,
                    redeem_amounts=redeem_amounts,
                )
                target_address = self.params.polymarket_neg_risk_adapter_address
            else:
                # For standard markets, use CTF contract
                index_sets = [outcome_index + 1]
                redeem_data = self._build_redeem_positions_data(
                    collateral_token=self.params.polymarket_usdc_address,
                    condition_id=condition_id,
                    index_sets=index_sets,
                )
                target_address = self.params.polymarket_ctf_address

            # Add to multisend batch
            redeem_batch = MultisendBatch(
                to=target_address,
                data=HexBytes(redeem_data),
                value=0,
            )
            self.multisend_batches.append(redeem_batch)

        # Build the multisend transaction
        success = yield from self._build_multisend_data()
        if not success:
            self.context.logger.error("Failed to build multisend data for redemptions")
            return ""

        success = yield from self._build_multisend_safe_tx_hash()
        if not success:
            self.context.logger.error("Failed to build safe tx hash for redemptions")
            return ""

        return self.tx_hex

    def _build_redeem_positions_data(
        self, collateral_token: str, condition_id: str, index_sets: list
    ) -> str:
        """Build redeemPositions function data for standard CTF contract."""
        # redeemPositions(address,bytes32,bytes32,uint256[])
        function_signature = "0x01b7037c"  # keccak256("redeemPositions(address,bytes32,bytes32,uint256[])")[:4]

        # Encode parameters
        collateral_padded = collateral_token[2:].zfill(64).lower()

        # parentCollectionId (bytes32) - always zeros
        parent_collection = "0" * 64

        condition_id_clean = condition_id.removeprefix("0x")
        condition_id_padded = condition_id_clean.zfill(64).lower()

        # indexSets (uint256[])
        # Array encoding: offset to array data (4 * 32 bytes from start = 0x80)
        array_offset = (
            "0000000000000000000000000000000000000000000000000000000000000080"
        )

        # Array length
        array_length = hex(len(index_sets))[2:].zfill(64)

        # Array elements
        array_elements = "".join([hex(idx)[2:].zfill(64) for idx in index_sets])

        return f"{function_signature}{collateral_padded}{parent_collection}{condition_id_padded}{array_offset}{array_length}{array_elements}"

    def _build_redeem_neg_risk_data(
        self, collateral_token: str, condition_id: str, redeem_amounts: list
    ) -> str:
        """Build redeemPositions function data for negative risk adapter.

        :param collateral_token: The collateral token address (USDC) - unused but kept for API compatibility
        :param condition_id: The condition ID for the market
        :param redeem_amounts: Array of [yes_amount, no_amount] to redeem
        :return: Encoded function call data
        """
        # redeemPositions(bytes32,uint256[])
        # Note: neg risk adapter does NOT take collateral token as parameter
        function_signature = (
            "0x6f0f6f3a"  # keccak256("redeemPositions(bytes32,uint256[])")[:4]
        )

        # Encode parameters
        condition_id_clean = condition_id.removeprefix("0x")
        condition_id_padded = condition_id_clean.zfill(64).lower()

        # redeemAmounts (uint256[])
        # Array encoding: offset to array data (1 * 32 bytes from start = 0x20)
        array_offset = (
            "0000000000000000000000000000000000000000000000000000000000000020"
        )

        # Array length (always 2 for binary outcomes)
        array_length = (
            "0000000000000000000000000000000000000000000000000000000000000002"
        )

        # Array elements (yes_amount, no_amount)
        # Convert to int to handle both int and string inputs
        array_elements = "".join(
            [hex(int(amt))[2:].zfill(64) for amt in redeem_amounts]
        )

        return f"{function_signature}{condition_id_padded}{array_offset}{array_length}{array_elements}"
