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

from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.skills.abstract_round_abci.base import get_name
from packages.valory.skills.abstract_round_abci.io_.store import SupportedFiletype
from packages.valory.skills.decision_maker_abci.behaviours.base import (
    DecisionMakerBaseBehaviour,
    SAFE_GAS,
    WaitableConditionType,
)
from packages.valory.skills.decision_maker_abci.payloads import MultisigTxPayload
from packages.valory.skills.decision_maker_abci.states.decision_request import (
    DecisionRequestRound,
)
from packages.valory.skills.market_manager_abci.bets import BINARY_N_SLOTS
from packages.valory.skills.transaction_settlement_abci.payload_tools import (
    hash_payload_to_hex,
)
from packages.valory.skills.transaction_settlement_abci.rounds import TX_HASH_LENGTH


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
        self._safe_tx_hash: str = ""

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
    def safe_tx_hash(self) -> str:
        """Get the safe_tx_hash."""
        return self._safe_tx_hash

    @safe_tx_hash.setter
    def safe_tx_hash(self, safe_hash: str) -> None:
        """Set the safe_tx_hash."""
        length = len(safe_hash)
        if length != TX_HASH_LENGTH:
            raise ValueError(
                f"Incorrect length {length} != {TX_HASH_LENGTH} detected "
                f"when trying to assign a safe transaction hash: {safe_hash}"
            )
        self._safe_tx_hash = safe_hash[2:]

    @property
    def n_slots_supported(self) -> bool:
        """Whether the behaviour supports the current number of slots as it currently only supports binary decisions."""
        return self.params.slot_count == BINARY_N_SLOTS

    def setup(self) -> None:
        """Setup behaviour."""
        if not self.n_slots_supported:
            return

        sampled_bet = self.synchronized_data.sampled_bet
        prompt_params = dict(
            question=sampled_bet.title, yes=sampled_bet.yes, no=sampled_bet.no
        )
        prompt = self.params.prompt_template.substitute(prompt_params)
        self._metadata = MechMetadata(prompt=prompt, tool=self.params.mech_tool)
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

    def _build_request_data(self) -> Generator[None, None, bool]:
        """Get the request tx data encoded."""
        result = yield from self._mech_contract_interact(
            "get_request_data",
            "data",
            get_name(DecisionRequestBehaviour.request_data),
            request_data=self._v1_hex_truncated,
        )
        return result

    def _get_price(self) -> WaitableConditionType:
        """Get the price of the mech request."""
        result = yield from self._mech_contract_interact(
            "get_price", "price", get_name(DecisionRequestBehaviour.price)
        )
        return result

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

    def _prepare_safe_tx(self) -> Generator[None, None, str]:
        """Prepare the safe transaction for sending a request to mech and return the hex for the tx settlement skill."""
        for step in (
            self._send_metadata_to_ipfs,
            self._build_request_data,
            self._get_price,
            self._get_safe_tx_hash,
        ):
            yield from self.wait_for_condition_with_sleep(step)

        return hash_payload_to_hex(
            self.safe_tx_hash,
            self.price,
            SAFE_GAS,
            self.params.mech_agent_address,
            self.request_data,
        )

    def async_act(self) -> Generator:
        """Do the action."""

        with self.context.benchmark_tool.measure(self.behaviour_id).local():
            tx_submitter = mech_tx_hex = None
            if self.n_slots_supported:
                tx_submitter = self.matching_round.auto_round_id()
                mech_tx_hex = yield from self._prepare_safe_tx()
            agent = self.context.agent_address
            payload = MultisigTxPayload(agent, tx_submitter, mech_tx_hex)

        yield from self.finish_behaviour(payload)
