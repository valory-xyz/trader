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

"""This module contains the behaviour of the skill which is responsible for requesting a decision from the mech."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import mkdtemp
from typing import Any, Dict, Generator, Optional, cast
from uuid import uuid4

import multibase
import multicodec
from aea.helpers.cid import to_v1
from hexbytes import HexBytes

from packages.valory.contracts.erc20.contract import ERC20
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.io_.store import SupportedFiletype
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    SAFE_GAS,
    WXDAI,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.models import MultisendBatch
from packages.valory.skills.decision_maker_abci.payloads import RequestPayload
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)


METADATA_FILENAME = "metadata.json"
V1_HEX_PREFIX = "f01"
Ox = "0x"


@dataclass
class MechMetadata:
    """A Mech's metadata."""

    prompt: str
    tool: str
    nonce: str = field(default_factory=lambda: str(uuid4()))


class DecisionRequestBehaviour(DecisionMakerBaseBehaviour):
    """A behaviour in which the agents prepare a tx to initiate a request to a mech to determine the answer to a bet."""

    matching_round = DecisionRequestRound

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Behaviour."""
        super().__init__(**kwargs)
        self._metadata: Optional[MechMetadata] = None
        self._v1_hex_truncated: str = ""
        self._request_data: bytes = b""
        self._price: int = 0

    @property
    def metadata_filepath(self) -> str:
        """Get the filepath to the metadata."""
        return str(Path(mkdtemp()) / METADATA_FILENAME)

    @property
    def metadata(self) -> Dict[str, str]:
        """Get the metadata as a dictionary."""
        return asdict(self._metadata)

    @property
    def request_data(self) -> bytes:
        """Get the request data."""
        return self._request_data

    @request_data.setter
    def request_data(self, data: bytes) -> None:
        """Set the request data."""
        self._request_data = data

    @property
    def price(self) -> int:
        """Get the price."""
        return self._price

    @price.setter
    def price(self, price: int) -> None:
        """Set the price."""
        self._price = price

    @property
    def n_slots_supported(self) -> bool:
        """Whether the behaviour supports the current number of slots as it currently only supports binary decisions."""
        return self.params.slot_count == BINARY_N_SLOTS

    @property
    def xdai_deficit(self) -> int:
        """Get the amount of missing xDAI for sending the request."""
        return self.price - self.wallet_balance

    @property
    def multisend_optional(self) -> bool:
        """Whether a multisend transaction does not need to be prepared."""
        return len(self.multisend_batches) == 0

    def setup(self) -> None:
        """Setup behaviour."""
        if not self.n_slots_supported:
            return

        sampled_bet = self.synchronized_data.sampled_bet
        prompt_params = dict(
            question=sampled_bet.title, yes=sampled_bet.yes, no=sampled_bet.no
        )
        prompt = self.params.prompt_template.substitute(prompt_params)
        tool = self.synchronized_data.mech_tool
        self._metadata = MechMetadata(prompt, tool)
        msg = f"Prepared metadata {self.metadata!r} for the request."
        self.context.logger.info(msg)

    def _send_metadata_to_ipfs(
        self,
    ) -> WaitableConditionType:
        """Send Mech metadata to IPFS."""
        metadata_hash = yield from self.send_to_ipfs(
            self.metadata_filepath, self.metadata, filetype=SupportedFiletype.JSON
        )
        if metadata_hash is None:
            return False

        v1_file_hash = to_v1(metadata_hash)
        cid_bytes = cast(bytes, multibase.decode(v1_file_hash))
        multihash_bytes = multicodec.remove_prefix(cid_bytes)
        v1_file_hash_hex = V1_HEX_PREFIX + multihash_bytes.hex()
        ipfs_link = self.params.ipfs_address + v1_file_hash_hex
        self.context.logger.info(f"Prompt uploaded: {ipfs_link}")
        self._v1_hex_truncated = Ox + v1_file_hash_hex[9:]
        return True

    def _get_price(self) -> WaitableConditionType:
        """Get the price of the mech request."""
        result = yield from self._mech_contract_interact(
            "get_price", "price", get_name(DecisionRequestBehaviour.price)
        )
        return result

    def _build_unwrap_tx(self) -> WaitableConditionType:
        """Exchange wxDAI to xDAI."""
        response_msg = yield from self.get_contract_api_response(
            performative=ContractApiMessage.Performative.GET_STATE,  # type: ignore
            contract_address=WXDAI,
            contract_id=str(ERC20.contract_id),
            contract_callable="build_withdraw_tx",
            amount=self.xdai_deficit,
        )

        if response_msg.performative != ContractApiMessage.Performative.STATE:
            self.context.logger.info(f"Could not build withdraw tx: {response_msg}")
            return False

        withdraw_data = response_msg.state.body.get("data")
        if withdraw_data is None:
            self.context.logger.info(f"Could not build withdraw tx: {response_msg}")
            return False

        batch = MultisendBatch(
            to=self.collateral_token,
            data=HexBytes(withdraw_data),
        )
        self.multisend_batches.append(batch)
        return True

    def _check_unwrap(self) -> WaitableConditionType:
        """Check whether the payment for the mech request is possible and unwrap some wxDAI if needed."""
        yield from self.wait_for_condition_with_sleep(self.check_balance)
        missing = self.xdai_deficit
        if missing <= 0:
            return True

        # if the collateral token is wxDAI, subtract the wxDAI balance from the xDAI that is missing for paying the mech
        if self.is_wxdai:
            missing -= self.token_balance

        # if we can cover the required amount by unwrapping some wxDAI, proceed to add this to a multisend tx
        if missing <= 0:
            yield from self.wait_for_condition_with_sleep(self._build_unwrap_tx)
            return True

        self.context.logger.warning(
            "The balance is not enough to pay for the mech's price. "
            f"Please refill the safe with at least {missing} xDAI."
        )
        self.sleep(self.params.sleep_time)
        return False

    def _build_request_data(self) -> Generator[None, None, bool]:
        """Get the request tx data encoded."""
        result = yield from self._mech_contract_interact(
            "get_request_data",
            "data",
            get_name(DecisionRequestBehaviour.request_data),
            request_data=self._v1_hex_truncated,
        )

        if not result:
            return False

        if self.multisend_optional:
            return True

        batch = MultisendBatch(
            to=self.params.mech_agent_address,
            data=HexBytes(self.request_data),
            value=self.price,
        )
        self.multisend_batches.append(batch)
        return True

    def _get_safe_tx_hash(self) -> Generator[None, None, bool]:
        """Prepares and returns the safe tx hash."""
        status = yield from self.contract_interact(
            performative=ContractApiMessage.Performative.GET_RAW_TRANSACTION,  # type: ignore
            contract_address=self.synchronized_data.safe_contract_address,
            contract_public_id=GnosisSafeContract.contract_id,
            contract_callable="get_raw_safe_transaction_hash",
            to_address=self.params.mech_agent_address,
            value=self.price,
            data=self.request_data,
            data_key="tx_hash",
            placeholder=get_name(DecisionRequestBehaviour.safe_tx_hash),
        )
        return status

    def _single_tx(self) -> Generator[None, None, str]:
        """Prepare a hex for a single transaction."""
        yield from self.wait_for_condition_with_sleep(self._get_safe_tx_hash)
        return hash_payload_to_hex(
            self.safe_tx_hash,
            self.price,
            SAFE_GAS,
            self.params.mech_agent_address,
            self.request_data,
        )

    def _multisend_tx(self) -> Generator[None, None, str]:
        """Prepare a hex for a multisend transaction."""
        for step in (
            self._build_multisend_data,
            self._build_multisend_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        tx_hex = self.tx_hex
        if tx_hex is None:
            raise ValueError("The multisend transaction was not prepared properly.")
        return tx_hex

    def _prepare_safe_tx(self) -> Generator[None, None, str]:
        """Prepare the safe transaction for sending a request to mech and return the hex for the tx settlement skill."""
        for step in (
            self._send_metadata_to_ipfs,
            self._get_price,
            self._check_unwrap,
            self._build_request_data,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        if self.multisend_optional:
            tx_hex = yield from self._single_tx()
        else:
            tx_hex = yield from self._multisend_tx()

        return tx_hex

    def async_act(self) -> Generator:
        """Do the action."""
        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_submitter = mech_tx_hex = price = None
            if self.n_slots_supported:
                tx_submitter = self.matching_round.auto_round_id()
                mech_tx_hex = yield from self._prepare_safe_tx()
                price = self.price
            agent = self.context.agent_address
            # log the payload
            self.context.logger.info(
                f"Sending request to mech with payload: {
                    agent, tx_submitter, mech_tx_hex, price
                }"
            )
            payload = RequestPayload(agent, tx_submitter, mech_tx_hex, price)
        yield from self.finish_behaviour(payload)
