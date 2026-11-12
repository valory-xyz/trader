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

"""This module contains the behaviour for sampling a bet."""

import json
import re
from typing import Any, Dict, Generator, Optional

from packages.valory.connections.polymarket_client.request_types import RequestType
from packages.valory.skills.abstract_round_abci.base import BaseTxPayload
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    SKIP_ORDER_IMPOSSIBLE,
    SKIP_ORDER_NOT_FILLED,
)
from packages.valory.skills.decision_maker_abci.behaviours.polymarket_deposit_wallet import (
    ORDER_STATUS_MATCHED,
    PolymarketDepositWalletBehaviour,
)
from packages.valory.skills.decision_maker_abci.behaviours.storage_manager import (
    StorageManagerBehaviour,
)
from packages.valory.skills.decision_maker_abci.payloads import (
    PolymarketBetPlacementPayload,
)
from packages.valory.skills.decision_maker_abci.states.base import Event
from packages.valory.skills.decision_maker_abci.states.polymarket_bet_placement import (
    PolymarketBetPlacementRound,
)

# Prefixes the signed-order cache key so that entries from a prior CLOB version
# (v1, signed against the retired CTF exchange) naturally orphan after cutover
# rather than being replayed and rejected by the server.
CLOB_VERSION = "v2"
# Seconds to wait before each lookup confirming a "Duplicated" order; ~57 s in all,
# well inside the round timeout.
DUPLICATE_CONFIRM_BACKOFFS_S = (2.0, 5.0, 10.0, 15.0, 25.0)
# The CLOB's answer to a resent order: "order 0x... is invalid. Duplicated."
DUPLICATED_ORDER_ID_RE = re.compile(r"order\s+(0x[0-9a-fA-F]+)\s+is invalid", re.I)


class PolymarketBetPlacementBehaviour(
    PolymarketDepositWalletBehaviour, StorageManagerBehaviour
):
    """A behaviour in which the agents blacklist the sampled bet."""

    matching_round = PolymarketBetPlacementRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the bet placement behaviour."""
        super().__init__(**kwargs)
        self.buy_amount = 0

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            yield from self.wait_for_condition_with_sleep(self.check_balance)

        outcome = self.sampled_bet.get_outcome(self.outcome_index)
        if self.sampled_bet.outcome_token_ids is None:
            self.context.logger.error("Failed to place bet: outcome_token_ids is None")
            payload = PolymarketBetPlacementPayload(
                self.context.agent_address,
                None,
                None,
                False,
                event=Event.BET_PLACEMENT_FAILED.value,
            )
            yield from self.finish_behaviour(payload)
            return

        token_id = self.sampled_bet.outcome_token_ids[outcome]
        # The full ``investment_amount`` reaches the book. The SDK sizes a market
        # buy against the funder's live balance and holds the CLOB taker fee back
        # out of it, so the top-up round funds the DepositWallet with the bet
        # *plus* the quoted fee (see ``PolymarketTopUpBehaviour._top_up_amount``);
        # the fee then comes out of that reserve instead of out of the bet.
        amount = self.usdc_to_native(self.investment_amount)

        if self.investment_amount > self.token_balance:
            self.context.logger.error("Failed to place bet: insufficient token balance")
            payload = PolymarketBetPlacementPayload(
                self.context.agent_address,
                None,
                None,
                False,
                event=Event.INSUFFICIENT_BALANCE.value,
            )
            yield from self.finish_behaviour(payload)
            return

        # Generate cache key and check for cached order. The CLOB_VERSION
        # prefix guarantees v1 cache entries orphan on cutover.
        cache_key = (
            f"{CLOB_VERSION}_{self.synchronized_data.period_count}_"
            f"{self.sampled_bet.id}_{token_id}"
        )
        cached_orders = self.synchronized_data.cached_signed_orders
        cached_signed_order_json = cached_orders.get(cache_key)

        # Prepare payload data. Under CLOB v2 the order is funded by
        # the DepositWallet (signature_type=3); pass it so the connection signs
        # with funder=DW even if it learned a different/no DW at startup.
        params = {
            "token_id": token_id,
            "amount": amount,
            "market_version": self.sampled_bet.market_version,
        }
        dw_address = self._resolve_deposit_wallet()
        if dw_address:
            params["funder"] = dw_address

        # Add cached order if available
        if cached_signed_order_json:
            params["cached_signed_order_json"] = cached_signed_order_json

        polymarket_bet_payload = {
            "request_type": RequestType.PLACE_BET.value,
            "params": params,
        }

        response = yield from self.send_polymarket_connection_request(
            polymarket_bet_payload
        )

        error_message = None
        event: Event
        skip_reason = SKIP_ORDER_IMPOSSIBLE
        updated_cache = dict(cached_orders)
        signed_order_json = None

        if response is None:
            error_message = "Failed to place bet: No response from connection"
            self.context.logger.error(error_message)
            event = Event.BET_PLACEMENT_FAILED
        else:
            signed_order_json = response.get("signed_order_json")
            error_msg = response.get("error")
            status = response.get("status")
            order_id = response.get("orderID")
            tx_hashes = response.get("transactionsHashes", [])
            # Only the order POST's own answer says anything about the order;
            # an error before it leaves the market open for a retry.
            posted = bool(response.get("posted"))
            is_duplicate_error = posted and "duplicated" in str(error_msg).lower()

            self.context.logger.info(
                f"Bet placement: Status={status}, OrderID={order_id}, TX={tx_hashes}, IsDuplicate={is_duplicate_error}"
            )

            # The amount is baked into the signature, so retrying cannot change
            # it; BET_PLACEMENT_FAILED would loop straight back into this round.
            response_str = str(response)
            if response.get("below_minimum"):
                error_message = f"Failed to place bet: {error_msg}"
                self.context.logger.error(error_message)
                event = Event.BET_PLACEMENT_IMPOSSIBLE
            elif "No orderbook exists for the requested token id" in response_str:
                error_message = "Failed to place bet: No orderbook exists for the requested token id"
                self.context.logger.error(error_message)
                event = Event.BET_PLACEMENT_IMPOSSIBLE
            # The CLOB answers "Duplicated" to any order id it has seen, matched
            # or not, so only the earlier attempt's own record says it was placed.
            elif is_duplicate_error:
                matched = yield from self._duplicate_order_matched(str(error_msg))
                if matched:
                    self.update_bet_transaction_information()
                    event = Event.BET_PLACEMENT_DONE
                else:
                    event = Event.BET_PLACEMENT_IMPOSSIBLE
                    skip_reason = SKIP_ORDER_NOT_FILLED
            elif posted and not response.get("retryable"):
                error_message = f"Failed to place bet: {error_msg}"
                self.context.logger.error(error_message)
                event = Event.BET_PLACEMENT_IMPOSSIBLE
                if response.get("fok_killed"):
                    skip_reason = SKIP_ORDER_NOT_FILLED
            elif bool(response.get("success") or tx_hashes):
                self.update_bet_transaction_information()
                self.context.logger.info("Bet placement successful.")
                event = Event.BET_PLACEMENT_DONE
            else:
                self.context.logger.error("Bet placement failed.")
                event = Event.BET_PLACEMENT_FAILED

        if event == Event.BET_PLACEMENT_FAILED:
            if signed_order_json:
                updated_cache[cache_key] = signed_order_json
        else:
            updated_cache.pop(cache_key, None)

        if event == Event.BET_PLACEMENT_IMPOSSIBLE:
            self._record_market_skipped(self.get_active_sampled_bet(), skip_reason)

        # On success, record conditionId → (identity, tool) key so the redeem behaviour
        # can later update the e-greedy policy's accuracy store for this position.
        utilized_tools_json = None
        policy_str = None
        if event == Event.BET_PLACEMENT_DONE:
            condition_id = self.get_active_sampled_bet().condition_id
            mech_tool_key = self.synchronized_data.mech_tool_key
            if condition_id is None:
                self.context.logger.warning(
                    "No condition_id found on the sampled bet; "
                    "utilized_tools will not be updated for this placement."
                )
            elif mech_tool_key is not None:
                self.utilized_tools[condition_id] = mech_tool_key
                utilized_tools_json = json.dumps(self.utilized_tools, sort_keys=True)
                self.context.logger.info(
                    f"Recorded mech tool {mech_tool_key!r} "
                    f"for condition_id {condition_id!r} in utilized_tools."
                )

            # Increment pending for the tool that was used
            if self.synchronized_data.is_policy_set and mech_tool_key is not None:
                self._policy = self.synchronized_data.policy
                self.policy.tool_used(mech_tool_key)
                policy_str = self.policy.serialize()
                self._store_policy()

        payload = PolymarketBetPlacementPayload(
            self.context.agent_address,
            None,
            None,
            False,
            event=event.value,
            cached_signed_orders=json.dumps(updated_cache),
            utilized_tools=utilized_tools_json,
            policy=policy_str,
        )

        yield from self.finish_behaviour(payload)

    def _duplicate_order_matched(self, error_msg: str) -> Generator[None, None, bool]:
        """Whether the earlier attempt behind a "Duplicated" answer was matched.

        :param error_msg: the CLOB's "Duplicated" error text, carrying the order id.
        :yield: framework yields between lookups.
        :return: ``True`` only when the CLOB's record of the order says matched.
        """
        found = DUPLICATED_ORDER_ID_RE.search(error_msg)
        if found is None:
            self.context.logger.error(
                f"No order id in the duplicate answer {error_msg!r}; "
                "the bet is not recorded."
            )
            return False
        order_id = found.group(1)
        order: Optional[Dict[str, Any]]
        order, _ = yield from self._poll_order_until_terminal_cooperative(
            order_id, DUPLICATE_CONFIRM_BACKOFFS_S, "bet placement: "
        )
        status = order.get("status") if order else None
        if status == ORDER_STATUS_MATCHED:
            self.context.logger.info(f"Duplicate order {order_id} was matched.")
            return True
        self.context.logger.warning(
            f"Duplicate order {order_id} not confirmed as matched "
            f"(status={status}); the bet is not recorded."
        )
        return False

    def finish_behaviour(self, payload: BaseTxPayload) -> Generator:
        """Finish the behaviour."""
        self._store_utilized_tools()
        yield from super().finish_behaviour(payload)
