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

"""This module contains the class to connect to the Agent Registry contract."""

from aea.common import JSONLike
from aea.configurations.base import PublicId
from aea.contracts.base import Contract
from aea.crypto.base import LedgerApi


class AgentRegistryContract(Contract):
    """The Agent Registry contract."""

    contract_id = PublicId.from_str("valory/agent_registry:0.1.0")

    @classmethod
    def get_hash(
        cls,
        ledger_api: LedgerApi,
        contract_address: str,
        agent_id: int,
    ) -> JSONLike:
        """Retrieve an operator given its agent instance."""

        contract_instance = cls.get_instance(ledger_api, contract_address)
        res = contract_instance.functions.getHashes(agent_id).call()
        # ensure that the returned object has the expected format
        if len(res) != 2:
            msg = f"The `getHashes` method for {contract_address=} returned data in an unexpected format: {res}"
            return dict(error=msg)

        # get the agent hashes
        hashes = res.pop(-1)
        # ensure that there are hashes returned for the agent
        if len(hashes) == 0:
            msg = f"The `getHashes` method for {contract_address=} returned no hashes for {agent_id=}: {res}"
            return dict(error=msg)

        # get the most recent agent hash
        hash_ = hashes.pop(-1)
        # ensure that the hash is in bytes
        if not isinstance(hash_, bytes):
            msg = f"The `getHashes` method for {contract_address=} returned non-bytes {hash_=} for {agent_id=}: {res}"
            return dict(error=msg)

        # return the hash in hex
        return dict(hash=hash_.hex())
