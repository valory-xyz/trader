# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2026 Valory AG
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

"""This module contains the behaviours for the agent top-up skill."""

import time
from typing import Any, Dict, Generator, Optional, Set, Type, cast

from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20TokenContract
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.behaviour_utils import BaseBehaviour
from packages.valory.skills.abstract_round_abci.behaviours import AbstractRoundBehaviour
from packages.valory.skills.agent_topup_abci.models import Params
from packages.valory.skills.agent_topup_abci.payloads import AgentTopUpPayload
from packages.valory.skills.agent_topup_abci.rounds import (
    AgentTopUpAbciApp,
    AgentTopUpRound,
    SynchronizedData,
)
from packages.valory.skills.agent_topup_abci.utils import (
    GNOSIS_CHAIN_NAME,
    NO_TOPUP,
    TOPUP_SUCCEEDED_KEY,
    WXDAI_ADDRESS,
    get_agent_topups,
    get_safe_native_balance,
)
from packages.valory.skills.funds_manager.behaviours import (
    GET_AGENT_TOPUP_METHOD_NAME,
    GET_FUNDS_STATUS_METHOD_NAME,
)
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
    skill_input_hex_to_payload,
)

LAST_TOPUP_CHECK_KEY = "last_topup_check"
TOPUP_CHECK_INTERVAL_SECONDS = 60 * 60
SAFE_GAS = 0


class AgentTopUpBehaviour(BaseBehaviour):
    """Moves native token from the Agent Safe to the Agent Signer when it is due."""

    matching_round = AgentTopUpRound

    @property
    def synchronized_data(self) -> SynchronizedData:
        """Return the synchronized data."""
        return SynchronizedData(super().synchronized_data.db)

    @property
    def params(self) -> Params:
        """Return the params."""
        return cast(Params, super().params)

    @property
    def skill_shared_state(self) -> Dict[str, Any]:
        """Return the state shared across the agent's skills."""
        return self.context.shared_state

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_hex = yield from self._get_topup_tx()
            tx_submitter = None
            if tx_hex is not None:
                tx_submitter = self.matching_round.auto_round_id()
            payload = AgentTopUpPayload(
                self.context.agent_address, tx_submitter, tx_hex
            )

        with self.context.benchmark_tool.measure(self.behaviour_id).consensus():
            yield from self.send_a2a_transaction(payload)
            yield from self.wait_until_round_end()
            self.set_done()

    def _get_topup_tx(self) -> Generator[None, None, Optional[str]]:
        """Prepare the top-up tx this visit sends, if any."""
        settled_to = self._get_settled_topup_to()
        if settled_to == self.context.agent_address:
            self.skill_shared_state[TOPUP_SUCCEEDED_KEY] = True
            return None
        if settled_to == WXDAI_ADDRESS:
            # An unwrap is followed by the transfer it funds, never by a second unwrap.
            return (yield from self._prepare_topup_tx(allow_unwrap=False))
        if not self._is_retry() and not self._is_check_due():
            return None
        return (yield from self._prepare_topup_tx(allow_unwrap=True))

    def _get_settled_topup_to(self) -> Optional[str]:
        """Return the recipient of the top-up tx that settled just before this visit, if any."""
        last_submitter = self.synchronized_data.db.get(
            get_name(SynchronizedData.tx_submitter), None
        )
        if last_submitter != self.matching_round.auto_round_id():
            return None
        tx = skill_input_hex_to_payload(self.synchronized_data.most_voted_tx_hash)
        return tx["to_address"]

    def _is_retry(self) -> bool:
        """Whether this visit repeats one that ended in no majority or a timeout."""
        last_round_id = self.context.state.round_sequence.last_round_id
        return last_round_id == self.matching_round.auto_round_id()

    def _is_check_due(self) -> bool:
        """Whether a new check starts: on start, then once an hour."""
        now = int(time.time())
        last_check = self.skill_shared_state.get(LAST_TOPUP_CHECK_KEY)
        if last_check is not None and now - last_check < TOPUP_CHECK_INTERVAL_SECONDS:
            return False

        self.skill_shared_state[LAST_TOPUP_CHECK_KEY] = now
        self.skill_shared_state[TOPUP_SUCCEEDED_KEY] = False
        return True

    def _prepare_topup_tx(
        self, allow_unwrap: bool
    ) -> Generator[None, None, Optional[str]]:
        """Prepare the next top-up Safe tx: the wxDAI unwrap when Agent Safe xDAI is short, otherwise the transfer."""
        chain = self.params.default_chain_id
        agent_address = self.context.agent_address
        try:
            funds = self.skill_shared_state[GET_FUNDS_STATUS_METHOD_NAME]()
            topup = get_agent_topups(
                self.skill_shared_state[GET_AGENT_TOPUP_METHOD_NAME],
                funds,
                agent_address,
                self.params.agent_balance_threshold,
            ).get(chain, NO_TOPUP)
        except Exception as exc:  # pylint: disable=broad-except
            # The round starts every period: a failed read skips the top-up, never the period.
            self.context.logger.warning(
                f"Agent Signer top-up skipped: {type(exc).__name__}({exc})."
            )
            return None
        if topup.move == 0:
            self.context.logger.info(f"No Agent Signer top-up on {chain}.")
            return None

        safe_native = cast(int, get_safe_native_balance(funds, chain, agent_address))
        if allow_unwrap and chain == GNOSIS_CHAIN_NAME and safe_native < topup.move:
            unwrap_amount = topup.move - safe_native
            self.context.logger.info(
                f"Unwrapping {unwrap_amount} wxDAI in the Agent Safe."
            )
            return (yield from self._prepare_unwrap_tx(unwrap_amount))

        # After an unwrap, the Agent Signer paid its gas, so the rule asks for slightly
        # more than was unwrapped; move what the Agent Safe holds rather than unwrap again.
        amount = min(topup.move, safe_native)
        if amount == 0:
            return None
        self.context.logger.info(f"Moving {amount} wei to the Agent Signer.")
        return (yield from self._prepare_safe_tx(agent_address, amount, b""))

    def _prepare_unwrap_tx(self, amount: int) -> Generator[None, None, Optional[str]]:
        """Prepare the Safe tx unwrapping `amount` wxDAI into xDAI."""
        response = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=WXDAI_ADDRESS,
            contract_id=str(ERC20TokenContract.contract_id),
            contract_callable="build_withdraw_tx",
            amount=amount,
            chain_id=self.params.default_chain_id,
        )
        if response.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(f"Could not build the wxDAI unwrap: {response}")
            return None

        data = bytes(HexBytes(response.state.body["data"]))
        return (yield from self._prepare_safe_tx(WXDAI_ADDRESS, 0, data))

    def _prepare_safe_tx(
        self, to_address: str, value: int, data: bytes
    ) -> Generator[None, None, Optional[str]]:
        """Prepare a single-CALL Safe tx and return its hex for the tx settlement skill."""
        response = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_id=str(GnosisSafeContract.contract_id),
            contract_callable="get_raw_safe_transaction_hash",
            to_address=to_address,
            value=value,
            data=data,
            safe_tx_gas=SAFE_GAS,
            chain_id=self.params.default_chain_id,
        )
        if response.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.error(
                f"Could not get the top-up Safe tx hash: {response}"
            )
            return None

        safe_tx_hash = cast(str, response.state.body["tx_hash"])[2:]
        return hash_payload_to_hex(safe_tx_hash, value, SAFE_GAS, to_address, data)


class AgentTopUpRoundBehaviour(AbstractRoundBehaviour):
    """This behaviour manages the consensus stages for the agent top-up."""

    initial_behaviour_cls = AgentTopUpBehaviour
    abci_app_cls = AgentTopUpAbciApp
    behaviours: Set[Type[BaseBehaviour]] = {AgentTopUpBehaviour}  # type: ignore
